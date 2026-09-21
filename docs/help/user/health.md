# Production Readiness (Health)

Answers one question: **can I start production?**

![Production readiness — system health at a glance](asset:health)

## Readiness banner
- ✓ **Production Ready** — all good.
- ⚠ **Ready with Warnings** — usable, with risk.
- ✖ **Production Blocked** — a critical check failed.

## Three views
Toggle the detail level:
- **Operator** — what failed, the **business impact**, and **what to do** (steps), plus any known-issue remedy.
- **Technician** — adds the diagnostic summary + data.
- **Engineer** — adds check id, duration, failure signature, raw error.

Checks are grouped by **business function** (Core Software, Production Systems, Test Equipment, External Systems), not technical domains.

## Running checks
- **Re-test** runs a suite; each check has its own Re-test.
- **Disruptive** checks (self-test, loopback) run only in **Maintenance** mode.

## Trends & schedule
- **Trend analysis** — MTBF, fail rate, repeated failures, flaky checks, from run history.
- **Scheduled runs** — startup, shutdown, every 30 min, daily at a set time.
