# Roadmap

## v0.2

- **SCIM provisioning metrics** — track SCIM sync events and errors per connected directory
- **MFA adoption dashboard** — breakdown of users with/without MFA enrolled, by MFA type
- **Application login heatmap** — which apps are being accessed most, by user group

## v0.3

- **Alert rules** — Grafana alert rules for login failure spikes, outpost going unhealthy, inactive admin accounts
- **SIB integration** — publish Authentik status to Status in a Box status page
- **PIB integration** — detect certificates nearing expiry in Authentik TLS config and surface in PIB

## Backlog

- Geo-IP enrichment for login events (map of login origins)
- Failed login source tracking (IP-level brute force detection)
- User lifecycle audit log (created, deactivated, deleted over time)
- LDAP bind error metrics
- Token expiry tracking
