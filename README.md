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

## Build status by phase
P1 (this commit): repo skeleton + CI spine. Web shell + `/healthz` only.
Later phases add core services, module framework + gate, bridge client, the
`hello` module, and the LabVIEW stub — see [docs/CORE.md](docs/CORE.md) §10.
