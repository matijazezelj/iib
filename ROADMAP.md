# Roadmap

## v0.2

- **On-call rotation** — PagerDuty-style schedules with primary/secondary responders; auto-assign incidents based on rotation
- **Slack notifications** — alert on new P1/P2 incidents, status changes, and unacknowledged incidents after N minutes
- **SIB auto-create** — bidirectional integration with Status in a Box; SIB status page degradations automatically open IIB incidents

## v0.3

- **Post-mortem templates** — auto-generate post-mortem documents for resolved P1/P2 incidents; exportable as Markdown
- **SLA reporting** — configurable SLA thresholds per severity; track SLA breach rate; weekly digest
- **Escalation policies** — auto-escalate unacknowledged P1 incidents after configurable timeout

## Backlog

- Multi-user auth (API keys / JWT)
- PagerDuty webhook receiver
- OpsGenie webhook receiver
- Email notifications
- Incident tagging and search
- Bulk status updates
- Prometheus AlertManager integration improvements (grouping, inhibition awareness)
