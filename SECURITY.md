# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |

## Reporting a vulnerability

Please do **not** open a public GitHub issue for security vulnerabilities.

Email: security@in-a-box-tools.tech

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

You will receive acknowledgement within 48 hours and a full response within 7 days.

## Scope

- IIB manager API (`manager/manager.py`)
- Docker Compose configuration
- Grafana provisioning

## Out of scope

- Third-party dependencies (VictoriaMetrics, Grafana) — report to their respective projects
- Issues in your deployment environment or network configuration

## Security considerations for deployment

- Change `GRAFANA_ADMIN_PASSWORD` from the default before deploying
- The API has no authentication by default — deploy behind a reverse proxy with auth (e.g. basic auth, OAuth2 proxy) if exposed outside localhost
- The SQLite database at `/data/iib.db` contains all incident data — ensure the volume is not world-readable
- Webhook endpoints accept unauthenticated POST requests — use network segmentation to restrict access to trusted sources (Alertmanager, Gatus) only
