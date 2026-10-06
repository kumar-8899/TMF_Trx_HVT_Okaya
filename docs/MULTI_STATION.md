# Multi-station & station management — as-built

One PC, one app, one broker, one controller, **N test sockets**. This documents
the app-side multi-station work (slices M1–M7) and the station-management features
added on top: choosing the controller, auto-starting the Python controller,
changing the socket count from the UI, relaunch, and safe exit.

Companion: [PYTHON_CONTROLLER.md](PYTHON_CONTROLLER.md) (the controller side),
[LABVIEW_BRIDGE.md](LABVIEW_BRIDGE.md) (the wire contract), [CORE.md](CORE.md).

---

## 1. The model

- Station ids are `st1 … stN`. The topic grammar is unchanged: everything is
  `tmf/{station}/…`.
- **One socket behaves as a single-station system** — the frontend hides all
  station chrome when there is only one socket, so a 1-socket deployment looks and
  feels exactly like the old single-station app. `station` is optional on every
  API and defaults to the sole socket.
- The application-wide cap is the license `max_stations` (analogous to
  TestStand's `NumTestSockets`). If `app.json` lists more sockets than the license
  permits, the app starts the permitted count and records each refusal in
  `/modules/status` — fail-closed, never a boot failure.

---

## 2. App-side slices (M1–M7) — as-built

| Slice | Delivered |
|---|---|
| **M1** | `app.json` `station` → `stations: [...]` (the singular key still migrates to a 1-element list); `CoreServices.stations`; the license `max_stations` cap applied before the bridge, refusals in `/modules/status`. |
| **M2** | `MultiStationBridge` — one `BridgeClient` per station. `request/publish/query` take a **required keyword `station`** (no default — a wrong-DUT-verdict guard); `subscribe/serve` fan out to every socket. |
| **M3** | `/readyz` carries per-station link state (`{st1:"online", …}`) + refusals, so an operator sees exactly which socket is missing; ready = core up AND ≥1 link online. |
| **M4** | `runs` is per-station: a per-socket active-run gate (`RunActiveError` 409), the station reserved **before** the bridge await (concurrent starts can't both pass), released on the terminal event. |
| **M5** | Per-station variable maps + the **§9.3 shared-instrument no-lease rule** (a write signal or any action bound on an instrument serving >1 socket is refused at save and at boot). |
| **M6** | Per-station `report` analytics (`by_station` + filter), DAQ frames + WS `?station=` filters, and `health` bridge checks dispatched per station and aggregated. |
| **M7** | Frontend station context: `useStations` (from `/modules/status`, `multi = len>1`) + `StationPicker` (renders **null** when not multi). Wired into Runs, Variable Map, Instruments, Analytics, Diagnostics. |

Everything is transparent to a single-socket deployment: `?station=` is optional
everywhere and omitting it targets the sole socket.

---

## 3. Choosing the controller

`app.json` carries a `controller` block:

```jsonc
"controller": { "kind": "labview" }
```

- **`labview`** (default) — the LabVIEW engine runs externally, exactly as before.
  The app starts nothing; it just connects the bridge.
- **`python`** — the **backend owns the Python controller's lifecycle**: on boot
  it generates a controller config from the app's own stations + broker
  (`backend/data/controller.generated.json`), spawns `python -m controller` as a
  child, pipes its stdout into diagnostics (subsystem `controller`), and stops it
  on shutdown. Instrument **instances** come from the Instruments page (v1.5.0+),
  and each runs simulated or real by its own **Simulated** toggle (v1.5.1+) — there
  is no app-level simulation switch (`controller.simulation` is deprecated/ignored).

Because the supervisor lives in the backend lifespan, **every** entry point —
`dev.ps1`, the launcher, a frozen build — starts the controller with the app; no
per-launcher wiring. Source: `core/services/controller_supervisor.py`.

> Frozen builds: there is no `python -m controller`, so the supervisor looks for a
> bundled `controller` executable beside the app and warns if absent. Bundling the
> controller as its own artifact is a packaging task.

---

## 4. Settings → Station configuration

Super_admin, under **Settings** (`frontend/src/screens/config/StationConfig.tsx`):

- **Test sockets** — a number, `st1…stN`, capped at the licensed `max_stations`.
- **Controller** — LabVIEW (external) or Python (auto-started). Simulation vs
  hardware is per-instrument, on the Instruments page — not set here.
- **Save** writes `app.json` (via `ConfigService.update_app`, atomic, re-validated).
- **Relaunch to apply** — station count and controller kind are **boot config**,
  so they take effect on the next restart; the button triggers it.

API (all `SYSTEM.SETTINGS`, in `core/app.py`):

```
GET  /system/station-config   → { station_count, configured_stations, running_stations,
                                   max_stations, controller:{kind}, restart_required }
PUT  /system/station-config   { station_count?, controller_kind? }
                              → validates count ≥ 1 and ≤ max_stations, writes app.json
POST /system/relaunch         → stop controller child, exit 42 (launcher restarts)
POST /system/shutdown         → safe exit (see below)
```

---

## 5. Relaunch vs. exit

Both go through the **launcher** (`backend/launcher.py`), which supervises the
backend: it restarts on **exit 42** and stops on **any other exit**. `dev.ps1`
runs the backend under the launcher so both work in dev too.

- **Relaunch** (`POST /system/relaunch`) — applies a config change. Stops the
  controller child (a hard `os._exit(42)` would otherwise skip cleanup), then
  exits 42 → launcher restarts → new stations/controller take effect.
- **Safe exit** (`POST /system/shutdown`, the **Exit** button in the AppBar) —
  raises `SIGINT` so uvicorn shuts down **gracefully**: the full lifespan cleanup
  runs (modules stop, the Python controller is **gracefully** stopped so every
  instrument is driven to safe state, the bridge goes offline, the DB is closed),
  then the process exits 0 → the launcher stops **without** restarting. uvicorn waits at most 5 s
  (`core.serve.GRACEFUL_SHUTDOWN_TIMEOUT_S`) for open connections (a browser tab's live WebSocket)
  before cancelling them, so the lifespan cleanup always runs. A 30 s daemon watchdog hard-exits if
  the graceful path still stalls, and it stops the controller first (`core.serve.force_exit`): a bare
  `os._exit` would orphan it. The Exit button is super_admin-only.

The controller's graceful stop uses CTRL_BREAK on Windows / SIGTERM on POSIX (it
is spawned in its own process group), so the controller runs its own teardown —
`safe_state` on every instrument — before it dies. This is what makes Exit *safe*.

---

## 6. Verifying multi-station locally

```pwsh
.\dev.ps1                    # broker + backend(+controller if kind=python) + frontend
```

Then in **Settings → Station configuration**: set Test sockets = 2, Controller =
Python, Save, Relaunch. After the restart, `/readyz` shows
`{"st1":"online","st2":"online"}`, `/modules/status` lists both, and the station
picker appears across the UI. Set it back to 1 the same way and the picker
disappears — single-station transparency restored.
