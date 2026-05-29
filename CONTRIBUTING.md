# Contributing

## Rules

- Keep `manager.py` as a single-file service — no unnecessary dependencies
- All new endpoints must include error handling and return appropriate HTTP status codes
- Webhook receivers must be idempotent (deduplication required)
- Metrics must be pushed after every write operation
- Never break the SQLite schema without a migration path
- All datetime fields must be ISO 8601 UTC strings

## Dev setup

```bash
# Clone and start the stack
git clone <repo>
cd iib
cp .env.example .env

make up
# API at http://localhost:8080
# Grafana at http://localhost:3004
# VictoriaMetrics at http://localhost:8432
```

## Making changes to manager.py

```bash
# Rebuild only the manager after code changes
docker compose build iib-manager
docker compose up -d iib-manager

# Watch logs
make logs
```

## Testing webhooks locally

```bash
# Alertmanager firing
curl -X POST http://localhost:8080/api/v1/webhooks/alertmanager \
  -H 'Content-Type: application/json' \
  -d '{
    "alerts": [{
      "status": "firing",
      "labels": {"alertname": "HighMemoryUsage", "severity": "critical"},
      "fingerprint": "test-fp-001"
    }]
  }'

# Gatus service down
curl -X POST http://localhost:8080/api/v1/webhooks/gatus \
  -H 'Content-Type: application/json' \
  -d '{"success": false, "service": {"name": "homepage"}}'

# Create manual incident
curl -X POST http://localhost:8080/api/v1/incidents \
  -H 'Content-Type: application/json' \
  -d '{"title": "Test incident", "severity": "P3"}'
```

## Clean up

```bash
make clean
```

This removes all containers and volumes. Data will be lost.
