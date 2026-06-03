# Phase-0 acceptance — walking skeleton "done"

Maps each CORE.md §10 criterion to where it is proven and how to see it by hand.
The skeleton is "done" when this table is green. The automated walk is
[`backend/tests/test_phase0_acceptance.py`](../backend/tests/test_phase0_acceptance.py).

## Status

| # | Criterion | Proven by | Status |
|---|---|---|---|
| 1 | Boots through the §5 lifecycle; core services up | `test_phase0_end_to_end` (#1) | ✅ |
| 2 | hello activates through the gate; `/modules/status` shows it loaded | `test_phase0_end_to_end` (#2) | ✅ |
| 3 | Flip `hello:false` in license → not loaded, reason shown | `test_criterion3_license_flip` | ✅ |
| 4 | `/healthz` green; `/readyz` green only once bridge `status` online | `test_phase0_end_to_end` (#4) | ✅ |
| 5 | `/hello/ping` round-trips through MQTT to the stub | `test_phase0_end_to_end` (#5) | ✅ (stub) |
| 6 | One `stream` frame + retained `value` + `diag` flow LV→Py | `test_phase0_end_to_end` (#6), `test_lv_stub` | ✅ (stub) |
| 7 | Kill the stub → `status` flips offline → `/readyz` not-ready | `test_phase0_end_to_end` (#7) | ✅ (stub) |
| 8 | CI builds PyInstaller sidecar + LabVIEW EXE + Tauri installer | `python.yml` sidecar; `labview.yml` | ⚠️ partial |

**"(stub)"** = proven against the Python reference stub
([`backend/tools/lv_stub.py`](../backend/tools/lv_stub.py)), which is the §12
wire contract. The literal "LabVIEW stub" reading flips to ✅ when the real DQMH
Bridge VI runs (see Open items).

The broker-backed walk needs Mosquitto; it is skipped locally when absent and
runs in CI (`python.yml` installs Mosquitto).

## Open items (the LabVIEW desk)

1. **Build the real DQMH Bridge VI** per
   [`labview/bridge/README.md`](../labview/bridge/README.md). Its wire behaviour
   must match `lv_stub.py`. This flips #5–#7 to real-LabVIEW.
2. **Register a self-hosted Windows runner** (LabVIEW + g-cli) so `labview.yml`
   builds the EXE — the LabVIEW half of #8.

Both are environment tasks, not platform code; the Python platform and the
React frontend work unchanged once they land (`LABVIEW_BRIDGE.md` §13).

## See it by hand (MQTT Explorer)

Phase 0 is graphical-first debuggable (PRINCIPLES §6). One command brings up the
broker, the stub, and the app:

```pwsh
./deploy/run-local.ps1
```

Then:

1. Open **MQTT Explorer** → connect to `127.0.0.1:1883` → watch the `tmf/#` tree:
   - `tmf/st1/status` retained `online`
   - `tmf/st1/stream/ai` ticking ~10 Hz
   - `tmf/st1/value/vbus_main` retained
   - `tmf/st1/diag` heartbeats
2. Browser/curl `http://127.0.0.1:8000/hello/ping` → JSON with the echoed
   round-trip. Watch `tmf/st1/cmd/hello.echo` + the reply fly past in Explorer.
3. `http://127.0.0.1:8000/readyz` → 200 with `bridge: true`.
4. **Ctrl-C the stub window** (ungraceful) → `tmf/st1/status` flips `offline`
   via the LWT → `/readyz` goes 503.
```
