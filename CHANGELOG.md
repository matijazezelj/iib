# Changelog

All notable changes to IIB (Identity in a Box) are documented here.

## [0.1.0] — 2026-05-29

### Added

- **Authentik IdP** — full-featured identity provider with OIDC, SAML 2.0, LDAP, SCIM, MFA, and SSO
- **iib-monitor** — Python service polling the Authentik REST API and pushing metrics to VictoriaMetrics
- **Metrics collected** — `iib_users_total`, `iib_users_active`, `iib_users_superuser`, `iib_logins_total`, `iib_login_failures_total`, `iib_password_changes_total`, `iib_applications_total`, `iib_providers_total`, `iib_groups_total`, `iib_outpost_healthy`, `iib_last_sync_timestamp`
- **Outpost health tracking** — aggregates `health_check_applications` from all outposts
- **VictoriaMetrics** — metrics storage with 90d default retention (port 8432)
- **Grafana dashboard** — `iib-overview` with 11 panels covering users, login events, outpost health, 1-minute refresh
- **Grafana provisioning** — datasource and dashboard auto-provisioned on container start
- **Auto-secret generation** — `make up` generates `AUTHENTIK_SECRET_KEY`, `AUTHENTIK_BOOTSTRAP_TOKEN`, and `POSTGRES_PASSWORD` on first run
- **Docker Compose stack** — seven services (postgresql, redis, server, worker, monitor, victoriametrics, grafana), named network and volumes, configurable ports via `.env`
- **Makefile** — `up`, `down`, `restart`, `build`, `logs`, `generate-secrets`, `sync-now`, `clean` targets
