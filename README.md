# Test & Measurement Framework

Multi-station T&M software template (runs singleton too).

- **LabVIEW** = controller — owns test execution, sequence, step timing, abort/timeout, safety, hardware (HAL).
- **Python** = app platform + sole web edge — modules, db, web, MQTT bridge client.
- **React frontend** = unchanged. LabVIEW ↔ Python over **MQTT only**.

## Source of truth — read first
- [docs/PRINCIPLES.md](docs/PRINCIPLES.md) — rules + locked decisions (the constitution).
- [docs/CORE.md](docs/CORE.md) — Python platform, module framework, activation gate, acceptance (§10).
- [docs/LABVIEW_BRIDGE.md](docs/LABVIEW_BRIDGE.md) — MQTT wire contract + Phase-0 LabVIEW stub (§12).

Build to the docs, not to memory. Decide → update doc → build.

## Layout
```
backend/    Python — platform (core/) + modules (modules/)
labview/    controller + DQMH Bridge module
frontend/   React shell (unchanged)
src-tauri/  Tauri shell + installer
deploy/     mosquitto.conf, CI helpers
docs/       the contracts
```

## Dev quickstart (Python)
```pwsh
cd backend
python -m pip install -e ".[dev]"
pytest -q
python run.py            # serves http://127.0.0.1:8000 ; GET /healthz
```

Live config (`config/app.json`, `config/license.json`) is gitignored — copy from
the `*.example.json` on first run.

## Phase 0 — walking skeleton (complete)

End to end: core services + module framework + activation gate + MQTT bridge
client + the `hello` reference module + a runnable LabVIEW Bridge stub, all in
CI. See [docs/PHASE0_ACCEPTANCE.md](docs/PHASE0_ACCEPTANCE.md) for the §10
criteria walk and a one-command local demo:

```pwsh
./deploy/run-local.ps1     # broker + app + stub; watch tmf/# in MQTT Explorer
```

One open item remains, on the LabVIEW desk: build the real DQMH Bridge VI per
[labview/bridge/README.md](labview/bridge/README.md) and register a self-hosted
runner. Until then the Python reference stub
([backend/tools/lv_stub.py](backend/tools/lv_stub.py)) stands in as the §12 wire
contract.

## Phase 1 — DAQ / stream + controller vertical (Python half complete)

Core latest-frame cache + StreamHub; the `daq` module (ai/di streaming, WS
relays, variables) and the `runs` module (run control, run records,
`/ws/station` + `/diagnostics/stream`). Command/reply is 3.1.1-safe (payload
`reply_to` + `id`). See [docs/PHASE1_ACCEPTANCE.md](docs/PHASE1_ACCEPTANCE.md);
contracts in [docs/contracts/](docs/contracts/).

Live acceptance is gated on the real LabVIEW DAQ + controller implementing the
LABVIEW_BRIDGE.md §5.1 command catalogue:

```pwsh
cd backend; python -m tools.check_phase1 --no-stub
```

## Phase 2 — business modules (Auth complete, backend)

Permission-first `auth` module (`DOMAIN.ACTION`, one role/user, resolve-at-login,
opaque single-session, Argon2, pluggable authenticator seam, full user management
gated on `AUTH.MANAGE_USERS`). Fills the `core.auth` port; modules consume
permissions via `require_permission`. See
[docs/PHASE2_AUTH_ACCEPTANCE.md](docs/PHASE2_AUTH_ACCEPTANCE.md) and
[docs/contracts/auth.md](docs/contracts/auth.md).

Known gap: the PyInstaller sidecar needs a packaging fix to run frozen
(dynamically-discovered modules + argon2 not yet bundled) — see the acceptance
doc. Auth UI is a later frontend phase.

The `logs` module (Action & Error Logs) is also complete: persists the diag bus
to durable, queryable `error_log` records (single sink + dedup/coalescing) and
attributed `action_log` records, with cursor-paginated query/stats/delete gated on
`DIAGNOSTICS.VIEW`/`DIAGNOSTICS.PURGE` and config-driven retention/pruning. See
[docs/PHASE2_LOGS_ACCEPTANCE.md](docs/PHASE2_LOGS_ACCEPTANCE.md) and
[docs/contracts/LOGS.md](docs/contracts/LOGS.md).

Next: Recipe → Report/Analytics → harden Licensing.
