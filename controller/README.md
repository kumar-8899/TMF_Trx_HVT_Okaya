# tmf-controller

A standalone **Python implementation of the Test Controller contract** — a peer of
the LabVIEW engine. The app talks to it over MQTT (`tmf/{station}/…`) and cannot
tell the two apart. It imports **nothing** from `backend/`.

Full reference: [`../docs/PYTHON_CONTROLLER.md`](../docs/PYTHON_CONTROLLER.md).
Multi-station + how the app auto-starts it: [`../docs/MULTI_STATION.md`](../docs/MULTI_STATION.md).

## Run

```bash
cd controller
python -m pip install -e .            # deps: paho-mqtt, tmf-instrumentlib
cp controller.example.json controller.json   # edit broker/stations/instruments
python -m controller controller.json
```

Needs only an MQTT broker (default `127.0.0.1:1883`); it starts fine with the app
stopped. Usually you don't run it by hand — set `controller.kind = "python"` in the
app's `app.json` and the backend starts it for you (Settings → Station configuration).

Standalone vs supervised: a hand-written config's `instruments` + global
`simulation` are honored only when you run `python -m controller` yourself. Under
app supervision (v1.5.0+/v1.5.1+) instrument instances come from the app's
**Instruments page** (a file `instruments` list is ignored) and each instrument is
simulated or real by its own page toggle (global `simulation` is written false).

## Test

```bash
python -m pytest -q                   # headless + live-broker integration (skips if no broker)
PYTHONPATH=examples python -m pytest examples   # the example app step-type package
```

## What's inside

`bridge/` MQTT client per station · `instruments/` instances + variable map
(signals + actions) · `sequencer.py` + the 8 core `step_types/` · `runstate.py`
run state machine · `daq/` AI/DI streaming · `safety/` reflex loop · `dryrun.py`
· `conformance.py` · `packages.py` (app step-type packages). See the reference doc
for the C1–C10 slice breakdown.
