# Changelog

All notable changes to IIB (Incident in a Box) are documented here.

## [0.1.0] — 2024-01-01

### Added

- **FastAPI REST API** — full incident CRUD with auto-generated `INC-NNNN` IDs
- **Incident model** — severity (P1–P4), status lifecycle (open → investigating → resolved → closed), source tracking, affected services, assignee, notes
- **Timeline events** — per-incident append-only event log with author and timestamp
- **Alertmanager v2 webhook receiver** — auto-create incidents from firing alerts, auto-resolve on resolved alerts, deduplication by fingerprint, severity mapping (critical→P1, warning→P2, info→P4)
- **Gatus webhook receiver** — auto-create P2 incidents on service-down events, auto-resolve on recovery, deduplication by service name
- **VictoriaMetrics integration** — metrics pushed after every write: `iib_incidents_total`, `iib_open_incidents`, `iib_mttr_seconds`
- **Prometheus scrape endpoint** (`GET /metrics`) for pull-based scraping
- **MTTR calculation** — average resolution time per severity for resolved incidents in last 30 days
- **Grafana dashboard** — `iib-overview` with 10 panels, `severity` template variable, 1-minute refresh
- **Grafana provisioning** — datasource and dashboard auto-provisioned on container start
- **SQLite backend** — WAL mode, thread-safe, no ORM dependency
- **Docker Compose stack** — three services (iib-manager, iib-victoriametrics, iib-grafana), named network and volumes, configurable ports via `.env`
- **Health endpoint** (`GET /health`) for liveness probes
- **Makefile** — `up`, `down`, `restart`, `build`, `logs`, `clean` targets
