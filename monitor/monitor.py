"""
IIB Monitor — Identity in a Box

Polls the Authentik API for user, session, login, and provider metrics
and pushes them to VictoriaMetrics.
"""

import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests
import schedule

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("iib")

# ── Config ────────────────────────────────────────────────────────────────────

AUTHENTIK_URL = os.environ.get("AUTHENTIK_URL", "http://iib-server:9000").rstrip("/")
AUTHENTIK_TOKEN = os.environ.get("AUTHENTIK_TOKEN", "")
VICTORIAMETRICS_URL = os.environ.get("VICTORIAMETRICS_URL", "http://iib-victoriametrics:8428")
SYNC_INTERVAL_MINUTES = int(os.environ.get("SYNC_INTERVAL_MINUTES", "15"))
SYNC_ON_STARTUP = os.environ.get("SYNC_ON_STARTUP", "true").lower() == "true"
LOOKBACK_HOURS = int(os.environ.get("LOOKBACK_HOURS", "24"))

HEADERS = {"Authorization": f"Bearer {AUTHENTIK_TOKEN}", "Accept": "application/json"}
SESSION = requests.Session()


# ── Authentik API helpers ─────────────────────────────────────────────────────

def _api_get(path: str, params: dict | None = None) -> dict | None:
    if not AUTHENTIK_TOKEN:
        logger.warning("AUTHENTIK_TOKEN not set — skipping API call")
        return None
    try:
        r = SESSION.get(
            f"{AUTHENTIK_URL}/api/v3/{path}",
            headers=HEADERS,
            params=params,
            timeout=15,
        )
        r.raise_for_status()
        return r.json()
    except requests.exceptions.ConnectionError:
        logger.warning("Cannot reach Authentik at %s — still starting up?", AUTHENTIK_URL)
        return None
    except Exception as e:
        logger.warning("Authentik API error (%s): %s", path, e)
        return None


def _count(path: str, params: dict | None = None) -> int:
    """Return the pagination.count from a list endpoint."""
    data = _api_get(path, params={"page_size": 1, **(params or {})})
    if data is None:
        return 0
    return data.get("pagination", {}).get("count", 0)


def _since_iso(hours: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(hours=hours)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000000Z")


# ── Data collection ───────────────────────────────────────────────────────────

def collect_metrics() -> dict:
    since = _since_iso(LOOKBACK_HOURS)

    users_total = _count("core/users")
    users_active = _count("core/users", {"is_active": "true"})
    users_superuser = _count("core/users", {"is_superuser": "true"})

    logins = _count("events/events", {"action": "login", "created__gte": since})
    login_failures = _count("events/events", {"action": "login_failed", "created__gte": since})
    password_changes = _count("events/events", {"action": "password_set", "created__gte": since})

    applications = _count("core/applications")
    providers = _count("providers/all")

    # Outpost health
    outposts_data = _api_get("outposts/outposts", {"ordering": "name"})
    outposts = []
    if outposts_data:
        for o in outposts_data.get("results", []):
            health = o.get("health_check_applications", [])
            healthy = all(h.get("healthy", False) for h in health) if health else True
            outposts.append({
                "name": o.get("name", "unknown"),
                "type": o.get("type", "unknown"),
                "healthy": healthy,
            })

    # Group membership counts (lightweight check)
    groups = _count("core/groups")

    return {
        "users_total": users_total,
        "users_active": users_active,
        "users_superuser": users_superuser,
        "logins": logins,
        "login_failures": login_failures,
        "password_changes": password_changes,
        "applications": applications,
        "providers": providers,
        "groups": groups,
        "outposts": outposts,
    }


# ── Metrics push ──────────────────────────────────────────────────────────────

def _safe_label(s: str) -> str:
    return str(s).replace('"', '\\"').replace("\n", "").replace("\\", "\\\\")


def _ts_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def push_metrics(m: dict) -> None:
    ts = _ts_ms()
    lines = [
        f"iib_users_total {m['users_total']} {ts}",
        f"iib_users_active {m['users_active']} {ts}",
        f"iib_users_superuser {m['users_superuser']} {ts}",
        f'iib_logins_total{{window="{LOOKBACK_HOURS}h"}} {m["logins"]} {ts}',
        f'iib_login_failures_total{{window="{LOOKBACK_HOURS}h"}} {m["login_failures"]} {ts}',
        f'iib_password_changes_total{{window="{LOOKBACK_HOURS}h"}} {m["password_changes"]} {ts}',
        f"iib_applications_total {m['applications']} {ts}",
        f"iib_providers_total {m['providers']} {ts}",
        f"iib_groups_total {m['groups']} {ts}",
        f"iib_last_sync_timestamp {ts} {ts}",
    ]

    for o in m["outposts"]:
        val = 1 if o["healthy"] else 0
        lines.append(
            f'iib_outpost_healthy{{name="{_safe_label(o["name"])}",'
            f'type="{_safe_label(o["type"])}"}} {val} {ts}'
        )

    payload = "\n".join(lines) + "\n"
    try:
        requests.post(
            f"{VICTORIAMETRICS_URL}/api/v1/import/prometheus",
            data=payload,
            headers={"Content-Type": "text/plain"},
            timeout=10,
        ).raise_for_status()
    except Exception as e:
        logger.error("Metric push failed: %s", e)


# ── Sync cycle ────────────────────────────────────────────────────────────────

def run_sync() -> None:
    logger.info("─── IIB sync ───")
    m = collect_metrics()
    push_metrics(m)
    logger.info(
        "users=%d active=%d logins=%d failures=%d apps=%d",
        m["users_total"], m["users_active"],
        m["logins"], m["login_failures"],
        m["applications"],
    )


def main() -> None:
    if "--once" in sys.argv:
        run_sync()
        return

    logger.info("IIB monitor starting (interval=%dm, lookback=%dh)",
                SYNC_INTERVAL_MINUTES, LOOKBACK_HOURS)

    if SYNC_ON_STARTUP:
        run_sync()

    schedule.every(SYNC_INTERVAL_MINUTES).minutes.do(run_sync)

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
