# IIB — Incident in a Box

One `docker compose up` for self-hosted incident management. Part of the **in-a-box-tools** ecosystem.

```
docker compose up -d
```

Brings up:
- **iib-manager** — FastAPI REST API + webhook receivers (port 8080)
- **VictoriaMetrics** — time-series metrics storage (port 8432)
- **Grafana** — pre-built overview dashboard (port 3004, admin / CHANGE_ME)

---

## Quick start

```bash
cp .env.example .env
# Edit .env — at minimum set GRAFANA_ADMIN_PASSWORD
docker compose up -d
```

Open Grafana at http://localhost:3004 — the IIB Overview dashboard loads automatically.

---

## Port table

| Service | Host port | Container port | Default |
|---------|-----------|----------------|---------|
| iib-manager (API) | `API_PORT` | 8080 | 8080 |
| VictoriaMetrics | `VICTORIAMETRICS_PORT` | 8428 | 8432 |
| Grafana | `GRAFANA_PORT` | 3000 | 3004 |

---

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/incidents` | Create incident |
| `GET` | `/api/v1/incidents` | List incidents (optional `?status=open&severity=P1`) |
| `GET` | `/api/v1/incidents/{id}` | Get single incident |
| `PATCH` | `/api/v1/incidents/{id}` | Partial update (title, severity, status, assignee, notes, affected_services) |
| `POST` | `/api/v1/incidents/{id}/timeline` | Add timeline event |
| `GET` | `/api/v1/incidents/{id}/timeline` | Get timeline events |
| `POST` | `/api/v1/webhooks/alertmanager` | Alertmanager v2 webhook receiver |
| `POST` | `/api/v1/webhooks/gatus` | Gatus webhook receiver |
| `GET` | `/metrics` | Prometheus scrape endpoint |
| `GET` | `/health` | Liveness check |

---

## Incident model

```json
{
  "id": "INC-0001",
  "title": "Database latency spike",
  "severity": "P2",
  "status": "investigating",
  "source": "alertmanager",
  "source_id": "abc123fingerprint",
  "affected_services": ["postgres", "api"],
  "assignee": "matija",
  "notes": "Checking slow query log",
  "created_at": "2024-01-15T09:00:00Z",
  "updated_at": "2024-01-15T09:05:00Z",
  "resolved_at": null
}
```

**Severity:** `P1` (critical) | `P2` (high) | `P3` (medium) | `P4` (low/info)

**Status:** `open` → `investigating` → `resolved` → `closed`

---

## Webhook integrations

### Alertmanager

Point Alertmanager's webhook receiver at `http://iib-manager:8080/api/v1/webhooks/alertmanager`.

```yaml
# alertmanager.yml
receivers:
  - name: iib
    webhook_configs:
      - url: http://iib-manager:8080/api/v1/webhooks/alertmanager
```

- Firing alerts create incidents (deduplicated by `fingerprint`).
- Severity mapping: `critical→P1`, `warning/high→P2`, `info→P4`, else `P3`.
- Resolved alerts auto-close the matching incident.

### Gatus

Point Gatus alert endpoints at `http://iib-manager:8080/api/v1/webhooks/gatus`.

```yaml
# gatus.yml
alerting:
  custom:
    url: http://iib-manager:8080/api/v1/webhooks/gatus
    method: POST
    body: |
      {
        "success": "[ALERT_TRIGGERED]" != "true",
        "service": {"name": "[SERVICE_NAME]"}
      }
```

- `success: false` creates a P2 incident "Service down: {name}".
- `success: true` resolves any open incident for that service.

### SIB (Status in a Box)

Send webhooks with `source: "sib"` via the manual `POST /api/v1/incidents` endpoint or integrate directly.

---

## Metrics

Pushed to VictoriaMetrics after every write operation and exposed at `GET /metrics` for scraping.

| Metric | Labels | Description |
|--------|--------|-------------|
| `iib_incidents_total` | `status`, `severity` | All incidents by status + severity |
| `iib_open_incidents` | `severity` | Currently open/investigating |
| `iib_mttr_seconds` | `severity` | Avg resolution time, resolved incidents last 30d |

---

## Grafana dashboard

The **IIB Overview** dashboard (`uid: iib-overview`) is provisioned automatically. Panels:

1. Open P1 incidents (red if > 0)
2. Open P2 incidents (orange if > 0)
3. Open P3/P4 incidents
4. Avg MTTR last 30d (minutes)
5. Total incidents count
6. Incident count by severity over time (stacked)
7. Open incidents over time (by severity)
8. Open incidents table (severity breakdown)
9. MTTR by severity (minutes, time series)
10. Incidents by status (stacked)

Template variable `severity` allows filtering all panels by P1/P2/P3/P4 or All.

---

## Data persistence

| Volume | Contents |
|--------|----------|
| `iib-data` | SQLite database (`/data/iib.db`) |
| `victoriametrics-data` | VictoriaMetrics TSDB (90d default retention) |
| `grafana-data` | Grafana state, user preferences |
