"""
IIB (Incident in a Box) — FastAPI incident management service.
"""

from __future__ import annotations

import sqlite3
import logging
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, field_validator

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DB_PATH = "/data/iib.db"
VICTORIAMETRICS_URL = "http://iib-victoriametrics:8428"

import os
VICTORIAMETRICS_URL = os.getenv("VICTORIAMETRICS_URL", VICTORIAMETRICS_URL)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("iib")

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS incidents (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'P3',
            status TEXT NOT NULL DEFAULT 'open',
            source TEXT NOT NULL DEFAULT 'manual',
            source_id TEXT,
            affected_services TEXT NOT NULL DEFAULT '[]',
            assignee TEXT,
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            resolved_at TEXT
        );

        CREATE TABLE IF NOT EXISTS timeline_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_id TEXT NOT NULL REFERENCES incidents(id),
            message TEXT NOT NULL,
            author TEXT,
            ts TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status);
        CREATE INDEX IF NOT EXISTS idx_incidents_source_id ON incidents(source_id);
        CREATE INDEX IF NOT EXISTS idx_timeline_incident ON timeline_events(incident_id);
    """)
    conn.commit()
    conn.close()


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def row_to_incident(row: sqlite3.Row) -> dict:
    d = dict(row)
    import json
    d["affected_services"] = json.loads(d.get("affected_services") or "[]")
    return d


def row_to_event(row: sqlite3.Row) -> dict:
    return dict(row)


def generate_incident_id(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        "SELECT id FROM incidents ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        num = 1
    else:
        match = re.search(r"INC-(\d+)", row["id"])
        num = (int(match.group(1)) + 1) if match else 1
    return f"INC-{num:04d}"

# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    log.info("IIB database initialised at %s", DB_PATH)
    yield


app = FastAPI(title="IIB — Incident in a Box", version="0.1.0", lifespan=lifespan)

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

VALID_SEVERITY = {"P1", "P2", "P3", "P4"}
VALID_STATUS = {"open", "investigating", "resolved", "closed"}
VALID_SOURCE = {"manual", "alertmanager", "gatus", "sib"}


class IncidentCreate(BaseModel):
    title: str
    severity: str = "P3"
    status: str = "open"
    source: str = "manual"
    source_id: Optional[str] = None
    affected_services: list[str] = []
    assignee: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v: str) -> str:
        if v not in VALID_SEVERITY:
            raise ValueError(f"severity must be one of {VALID_SEVERITY}")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in VALID_STATUS:
            raise ValueError(f"status must be one of {VALID_STATUS}")
        return v

    @field_validator("source")
    @classmethod
    def validate_source(cls, v: str) -> str:
        if v not in VALID_SOURCE:
            raise ValueError(f"source must be one of {VALID_SOURCE}")
        return v


class IncidentPatch(BaseModel):
    title: Optional[str] = None
    severity: Optional[str] = None
    status: Optional[str] = None
    assignee: Optional[str] = None
    notes: Optional[str] = None
    affected_services: Optional[list[str]] = None

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_SEVERITY:
            raise ValueError(f"severity must be one of {VALID_SEVERITY}")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_STATUS:
            raise ValueError(f"status must be one of {VALID_STATUS}")
        return v


class TimelineEventCreate(BaseModel):
    message: str
    author: Optional[str] = None


# Alertmanager webhook payload
class AlertManagerAlert(BaseModel):
    labels: dict = {}
    status: str = "firing"
    fingerprint: Optional[str] = None
    generatorURL: Optional[str] = None


class AlertManagerPayload(BaseModel):
    alerts: list[AlertManagerAlert] = []
    version: Optional[str] = None
    groupLabels: Optional[dict] = None
    commonLabels: Optional[dict] = None


# Gatus webhook payload
class GatusService(BaseModel):
    name: str


class GatusPayload(BaseModel):
    success: bool
    service: GatusService
    conditionResults: Optional[list] = None

# ---------------------------------------------------------------------------
# Metrics helpers
# ---------------------------------------------------------------------------

def _push_metrics_to_vm(metrics_text: str) -> None:
    """Push Prometheus-format metrics to VictoriaMetrics. Silently logs on failure."""
    try:
        url = f"{VICTORIAMETRICS_URL}/api/v1/import/prometheus"
        resp = requests.post(url, data=metrics_text, timeout=5)
        if resp.status_code not in (200, 204):
            log.warning("VictoriaMetrics push returned %d: %s", resp.status_code, resp.text[:200])
    except Exception as exc:
        log.warning("Failed to push metrics to VictoriaMetrics: %s", exc)


def build_metrics_text(conn: sqlite3.Connection) -> str:
    """Build Prometheus-format metrics text from current DB state."""
    import json

    lines: list[str] = []
    ts_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    # iib_incidents_total{status, severity}
    rows = conn.execute(
        "SELECT status, severity, COUNT(*) as cnt FROM incidents GROUP BY status, severity"
    ).fetchall()
    lines.append("# HELP iib_incidents_total Total incidents by status and severity")
    lines.append("# TYPE iib_incidents_total gauge")
    for row in rows:
        lines.append(
            f'iib_incidents_total{{status="{row["status"]}",severity="{row["severity"]}"}} {row["cnt"]} {ts_ms}'
        )

    # iib_open_incidents{severity} — status=open or investigating
    open_rows = conn.execute(
        "SELECT severity, COUNT(*) as cnt FROM incidents WHERE status IN ('open','investigating') GROUP BY severity"
    ).fetchall()
    lines.append("# HELP iib_open_incidents Currently open or investigating incidents by severity")
    lines.append("# TYPE iib_open_incidents gauge")
    for row in open_rows:
        lines.append(
            f'iib_open_incidents{{severity="{row["severity"]}"}} {row["cnt"]} {ts_ms}'
        )
    # Ensure all severities are emitted even if zero
    reported_sevs = {row["severity"] for row in open_rows}
    for sev in VALID_SEVERITY:
        if sev not in reported_sevs:
            lines.append(f'iib_open_incidents{{severity="{sev}"}} 0 {ts_ms}')

    # iib_mttr_seconds{severity} — avg resolution time last 30 days
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    mttr_rows = conn.execute(
        """
        SELECT severity,
               AVG(
                   CAST((julianday(resolved_at) - julianday(created_at)) * 86400 AS INTEGER)
               ) AS avg_seconds
        FROM incidents
        WHERE status IN ('resolved','closed')
          AND resolved_at IS NOT NULL
          AND created_at >= ?
        GROUP BY severity
        """,
        (cutoff,),
    ).fetchall()
    lines.append("# HELP iib_mttr_seconds Average MTTR in seconds for resolved incidents (last 30d)")
    lines.append("# TYPE iib_mttr_seconds gauge")
    for row in mttr_rows:
        avg = row["avg_seconds"] or 0
        lines.append(f'iib_mttr_seconds{{severity="{row["severity"]}"}} {avg:.2f} {ts_ms}')

    return "\n".join(lines) + "\n"


def push_metrics(conn: sqlite3.Connection) -> None:
    """Build and push metrics; never raises."""
    try:
        text = build_metrics_text(conn)
        _push_metrics_to_vm(text)
    except Exception as exc:
        log.warning("Metrics build/push failed: %s", exc)

# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------

@app.post("/api/v1/incidents", status_code=201)
def create_incident(body: IncidentCreate):
    import json
    conn = get_db()
    try:
        inc_id = generate_incident_id(conn)
        ts = now_iso()
        conn.execute(
            """
            INSERT INTO incidents
            (id, title, severity, status, source, source_id, affected_services,
             assignee, notes, created_at, updated_at, resolved_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                inc_id,
                body.title,
                body.severity,
                body.status,
                body.source,
                body.source_id,
                json.dumps(body.affected_services),
                body.assignee,
                body.notes,
                ts,
                ts,
                None,
            ),
        )
        # Auto timeline event
        conn.execute(
            "INSERT INTO timeline_events (incident_id, message, author, ts) VALUES (?,?,?,?)",
            (inc_id, f"Incident created with severity {body.severity} from {body.source}", "system", ts),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM incidents WHERE id=?", (inc_id,)).fetchone()
        result = row_to_incident(row)
        push_metrics(conn)
        return result
    finally:
        conn.close()


@app.get("/api/v1/incidents")
def list_incidents(
    status: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
):
    conn = get_db()
    try:
        query = "SELECT * FROM incidents WHERE 1=1"
        params: list = []
        if status:
            query += " AND status=?"
            params.append(status)
        if severity:
            query += " AND severity=?"
            params.append(severity)
        query += " ORDER BY created_at DESC"
        rows = conn.execute(query, params).fetchall()
        return [row_to_incident(r) for r in rows]
    finally:
        conn.close()


@app.get("/api/v1/incidents/{incident_id}")
def get_incident(incident_id: str):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM incidents WHERE id=?", (incident_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")
        return row_to_incident(row)
    finally:
        conn.close()


@app.patch("/api/v1/incidents/{incident_id}")
def patch_incident(incident_id: str, body: IncidentPatch):
    import json
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM incidents WHERE id=?", (incident_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")

        updates: list[str] = []
        params: list = []

        if body.title is not None:
            updates.append("title=?")
            params.append(body.title)
        if body.severity is not None:
            updates.append("severity=?")
            params.append(body.severity)
        if body.status is not None:
            updates.append("status=?")
            params.append(body.status)
        if body.assignee is not None:
            updates.append("assignee=?")
            params.append(body.assignee)
        if body.notes is not None:
            updates.append("notes=?")
            params.append(body.notes)
        if body.affected_services is not None:
            updates.append("affected_services=?")
            params.append(json.dumps(body.affected_services))

        if not updates:
            return row_to_incident(row)

        ts = now_iso()
        updates.append("updated_at=?")
        params.append(ts)

        # Auto-set resolved_at when transitioning to resolved/closed
        current_status = row["status"]
        new_status = body.status
        if new_status in ("resolved", "closed") and current_status not in ("resolved", "closed"):
            updates.append("resolved_at=?")
            params.append(ts)
        elif new_status in ("open", "investigating") and current_status in ("resolved", "closed"):
            # Reopened — clear resolved_at
            updates.append("resolved_at=NULL")

        params.append(incident_id)
        conn.execute(f"UPDATE incidents SET {', '.join(updates)} WHERE id=?", params)

        # Timeline note for status change
        if new_status and new_status != current_status:
            conn.execute(
                "INSERT INTO timeline_events (incident_id, message, author, ts) VALUES (?,?,?,?)",
                (incident_id, f"Status changed from {current_status} to {new_status}", "system", ts),
            )

        conn.commit()
        updated = conn.execute("SELECT * FROM incidents WHERE id=?", (incident_id,)).fetchone()
        result = row_to_incident(updated)
        push_metrics(conn)
        return result
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------

@app.post("/api/v1/incidents/{incident_id}/timeline", status_code=201)
def add_timeline_event(incident_id: str, body: TimelineEventCreate):
    conn = get_db()
    try:
        row = conn.execute("SELECT id FROM incidents WHERE id=?", (incident_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")
        ts = now_iso()
        cur = conn.execute(
            "INSERT INTO timeline_events (incident_id, message, author, ts) VALUES (?,?,?,?)",
            (incident_id, body.message, body.author, ts),
        )
        conn.commit()
        event = conn.execute("SELECT * FROM timeline_events WHERE id=?", (cur.lastrowid,)).fetchone()
        return row_to_event(event)
    finally:
        conn.close()


@app.get("/api/v1/incidents/{incident_id}/timeline")
def get_timeline(incident_id: str):
    conn = get_db()
    try:
        row = conn.execute("SELECT id FROM incidents WHERE id=?", (incident_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")
        events = conn.execute(
            "SELECT * FROM timeline_events WHERE incident_id=? ORDER BY ts ASC",
            (incident_id,),
        ).fetchall()
        return [row_to_event(e) for e in events]
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------

def _am_severity(labels: dict) -> str:
    sev = (labels.get("severity") or "").lower()
    if sev == "critical":
        return "P1"
    if sev in ("high", "warning"):
        return "P2"
    if sev == "info":
        return "P4"
    return "P3"


@app.post("/api/v1/webhooks/alertmanager", status_code=200)
def webhook_alertmanager(payload: AlertManagerPayload):
    import json
    conn = get_db()
    created: list[str] = []
    resolved: list[str] = []
    try:
        for alert in payload.alerts:
            fingerprint = alert.fingerprint or ""
            alertname = alert.labels.get("alertname", "Unknown Alert")

            if alert.status == "firing":
                # Dedup: skip if open incident with this source_id already exists
                if fingerprint:
                    existing = conn.execute(
                        "SELECT id FROM incidents WHERE source='alertmanager' AND source_id=? AND status IN ('open','investigating')",
                        (fingerprint,),
                    ).fetchone()
                    if existing:
                        log.info("Dedup: alertmanager fingerprint %s already tracked as %s", fingerprint, existing["id"])
                        continue

                severity = _am_severity(alert.labels)
                ts = now_iso()
                affected = [alert.labels.get("service", alert.labels.get("job", ""))]
                affected = [s for s in affected if s]
                inc_id = generate_incident_id(conn)
                conn.execute(
                    """
                    INSERT INTO incidents
                    (id, title, severity, status, source, source_id, affected_services, assignee, notes, created_at, updated_at, resolved_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        inc_id,
                        f"Alert: {alertname}",
                        severity,
                        "open",
                        "alertmanager",
                        fingerprint or None,
                        json.dumps(affected),
                        None,
                        None,
                        ts,
                        ts,
                        None,
                    ),
                )
                conn.execute(
                    "INSERT INTO timeline_events (incident_id, message, author, ts) VALUES (?,?,?,?)",
                    (inc_id, f"Alertmanager firing: {alertname}", "alertmanager", ts),
                )
                created.append(inc_id)

            elif alert.status == "resolved" and fingerprint:
                open_inc = conn.execute(
                    "SELECT id FROM incidents WHERE source='alertmanager' AND source_id=? AND status IN ('open','investigating')",
                    (fingerprint,),
                ).fetchone()
                if open_inc:
                    ts = now_iso()
                    conn.execute(
                        "UPDATE incidents SET status='resolved', resolved_at=?, updated_at=? WHERE id=?",
                        (ts, ts, open_inc["id"]),
                    )
                    conn.execute(
                        "INSERT INTO timeline_events (incident_id, message, author, ts) VALUES (?,?,?,?)",
                        (open_inc["id"], f"Auto-resolved: Alertmanager reported resolved for {alertname}", "alertmanager", ts),
                    )
                    resolved.append(open_inc["id"])

        conn.commit()
        push_metrics(conn)
        return {"created": created, "resolved": resolved}
    finally:
        conn.close()


@app.post("/api/v1/webhooks/gatus", status_code=200)
def webhook_gatus(payload: GatusPayload):
    import json
    conn = get_db()
    try:
        service_name = payload.service.name
        ts = now_iso()

        if not payload.success:
            # Check for existing open incident for this service
            existing = conn.execute(
                "SELECT id FROM incidents WHERE source='gatus' AND source_id=? AND status IN ('open','investigating')",
                (service_name,),
            ).fetchone()
            if existing:
                log.info("Dedup: gatus service %s already has open incident %s", service_name, existing["id"])
                conn.close()
                return {"created": [], "resolved": []}

            inc_id = generate_incident_id(conn)
            conn.execute(
                """
                INSERT INTO incidents
                (id, title, severity, status, source, source_id, affected_services, assignee, notes, created_at, updated_at, resolved_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    inc_id,
                    f"Service down: {service_name}",
                    "P2",
                    "open",
                    "gatus",
                    service_name,
                    json.dumps([service_name]),
                    None,
                    None,
                    ts,
                    ts,
                    None,
                ),
            )
            conn.execute(
                "INSERT INTO timeline_events (incident_id, message, author, ts) VALUES (?,?,?,?)",
                (inc_id, f"Gatus reported service down: {service_name}", "gatus", ts),
            )
            conn.commit()
            push_metrics(conn)
            return {"created": [inc_id], "resolved": []}

        else:
            # Resolve open incidents for this service
            open_incs = conn.execute(
                "SELECT id FROM incidents WHERE source='gatus' AND source_id=? AND status IN ('open','investigating')",
                (service_name,),
            ).fetchall()
            resolved_ids = []
            for inc in open_incs:
                conn.execute(
                    "UPDATE incidents SET status='resolved', resolved_at=?, updated_at=? WHERE id=?",
                    (ts, ts, inc["id"]),
                )
                conn.execute(
                    "INSERT INTO timeline_events (incident_id, message, author, ts) VALUES (?,?,?,?)",
                    (inc["id"], f"Auto-resolved: Gatus reported service recovered: {service_name}", "gatus", ts),
                )
                resolved_ids.append(inc["id"])
            conn.commit()
            push_metrics(conn)
            return {"created": [], "resolved": resolved_ids}
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# Health + Metrics scrape endpoint
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok", "service": "iib-manager"}


@app.get("/metrics")
def metrics_scrape():
    from fastapi.responses import PlainTextResponse
    conn = get_db()
    try:
        text = build_metrics_text(conn)
        return PlainTextResponse(content=text, media_type="text/plain; version=0.0.4")
    finally:
        conn.close()
