# Calibration contract (analog input & output)

> Status: **built (framework v1.31.0)**. Owner: `variables` module + `core/services/calibration.py`;
> controller side `controller/instruments/variables.py` + op `calibration.reload`.
> Origin: Okaya field defect D3 — a signal's scale (`gain`/`offset`) was static in the shipped
> variable map, so a drifting analog channel meant editing a framework-shipped file and relaunching.

## 1. The rule

A calibration is an **overlay** on the variable map's static `scale`. It never edits the map the
app ships.

| | |
|---|---|
| Shipped map | `app/<slug>/maps/<station>.json` — app-owned, read-only at run time. |
| Overlay | `<state dir>/calibration/<station>.json` — operator data, written only by the Maintenance calibration screen. Survives upgrades. |
| Effective map | `<state dir>/controller.maps/<station>.json` — shipped map + overlay, **baked by the supervisor**. This is the file the Python controller reads. |
| Index | `<state dir>/controller.maps/index.json` — `{station: {shipped, effective, overlay}}`, so the variables module finds the maps without depending on the supervisor. |

`<state dir>` is the backend data dir (`DEFAULT_DB_PATH.parent`).

### Overlay file

```json
{ "schema_version": 1,
  "signals": {
    "vbus_main": { "gain": 2.0013, "offset": 0.0042,
                   "n": 3, "max_error": 0.0008,
                   "points": [{ "raw": 0.0, "reference": 0.004 }, { "raw": 5.0, "reference": 10.011 }],
                   "updated_ts": 1760000000.0, "by": "carol" } } }
```

Model: `engineering value = gain × raw + offset`, the same form as the map's `scale`.

**Semantics (tested in `backend/tests/test_calibration.py`):**
1. **Precedence: overlay > map `scale`.** An overlay entry *replaces* the signal's scale (the fit is
   from raw to the reference, so it already contains any factory scale).
2. Unknown signal names in the overlay are ignored. Extra keys (`points`, `by`, …) are ignored.
3. An entry without a finite `gain` **and** `offset`, or with `gain == 0` (the inverse scale used for
   writes would divide by it), is ignored — the signal keeps its factory scale.
4. The shipped map and the input dicts are never mutated.
5. Clamp is untouched: it applies to the engineering value, before the inverse scale, as before.
6. A signal may opt out with `"calibratable": false` in the map (e.g. a digital line); it is then
   not offered on the Maintenance screen.

## 2. One implementation, two read paths

Both paths that scale a signal consume the same pure function, `overlay_calibration()`:

| Path | How the overlay reaches it |
|---|---|
| **Python controller** (runs, `variable.read`) | The supervisor calls `bake_effective_map()` at every start and points each station's `variable_map` at the effective file. |
| **Backend engine** (`/variables/{name}/value`, LabVIEW-bridge `variable.*`) | `VariableEngine.set_overlay()`; the scale is resolved at read/write time through the same function. Loaded from the overlay file at module start. |

`backend/tests/test_calibration.py::test_controller_and_backend_reads_agree_and_reload_needs_no_relaunch`
asserts both return the same value for the same raw reading, before and after an apply.

### Degradation is loud, never silent
- **Overlay file present but unreadable/malformed** → an `error` diagnostic naming the file; the
  station runs on the **factory scale** (supervisor and engine alike). It is not silently
  uncalibrated.
- **Overlay file absent** (a fresh bench) → no-op; the effective map is an identical copy.
- **Shipped map unreadable** → the bake is skipped with a warning and the controller is pointed at
  the shipped path, so it reports the bad map exactly as before this feature.

## 3. Applying without a relaunch

`calibration.reload` (controller op, per station, inline): re-reads the station's **effective** map
and swaps the `scale` of each signal **in place**.

- Only `scale` may change. A changed `instance`/`read`/`write`/`args`/`clamp`, or a changed signal
  set, is **refused** (`restart to rewire`) — a calibration can never silently rewire hardware.
- **Refused while the station is not idle** (`{ok:false, error:{code:"Busy"}}`): changing a scale
  mid-sequence would corrupt its readings.
- A bad file leaves the live scales untouched (`{ok:false, error:{…}}`).

When the controller cannot reload now (busy, bridge down), the backend still **saves** the overlay
and re-bakes the effective map, and replies `controller: "pending"` with the reason; the calibration
takes effect on the next controller start. The Maintenance screen shows this as a warning, never as
success.

LabVIEW controller (`controller.kind == "labview"`): the overlay applies to the backend engine only
(there is no baked map). A LabVIEW engine that scales on its own side must implement its own
equivalent — the overlay file format above is the interchange.

## 4. REST (variables module) — all gated **`MAINTENANCE.CALIBRATE`**

| Route | Purpose |
|---|---|
| `GET  /calibration/signals?station=` | Calibratable signals (shipped map ∪ engine map) with factory scale and active calibration. |
| `POST /calibration/fit` `{points}` | Preview the least-squares `{gain, offset, n, max_error}` without saving. |
| `POST /calibration/{name}/raw` `{station?}` | Current **unscaled** reading of an analog input. |
| `POST /calibration/{name}/drive` `{raw, station?}` | Command an analog output so the instrument receives exactly `raw` (derived through the current scale). |
| `POST /calibration/{name}/apply` `{points, station?}` | Fit → save overlay → re-bake → `calibration.reload`. Reply includes `controller: reloaded \| pending \| not-applicable \| no-map`. |
| `DELETE /calibration/{name}?station=` | Remove the signal's overlay entry (back to factory) and propagate the same way. |

Errors are RFC-7807: 404 unknown signal, 422 bad/degenerate points (<2 points, one distinct raw
value, non-finite, flat reference), 503 controller/bridge unavailable.

`MAINTENANCE.CALIBRATE` is held by `super_admin` (via `MAINTENANCE.*`) and the `maintenance` role by
default. It is deliberately **not** `HEALTH.MAINTENANCE`: calibrating changes every later
measurement. Driving an output from the UI additionally requires maintenance mode to be on.

## 5. Operator workflow (Maintenance → Calibration)

1. Pick the signal (and station on a multi-socket PC).
2. **Input:** apply a known stimulus → *Capture raw reading* → type the reference-meter value →
   *Add point*. **Output:** enter a raw value → *Drive output* (maintenance mode) → type what the
   meter measures → *Add point*.
3. Two or more points at different values; the fit and its max error show live. Remove bad points.
4. *Apply calibration* — live immediately; no restart. *Reset to factory* removes the overlay.

Every apply/reset writes an audit diagnostic (`calibration applied` / `calibration reset`:
station, signal, gain, offset, n, max_error, user). The capture points are kept in the overlay.

## 6. What a fork does

Nothing is required. The shipped `app/<slug>/maps/<station>.json` stays the factory definition. To
hide a signal from the screen set `"calibratable": false`. Back up `<state dir>/calibration/` with
the rest of the station data if calibrations must survive a re-image.
