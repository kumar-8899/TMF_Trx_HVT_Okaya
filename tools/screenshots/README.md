# Screenshot capture pipeline (dev-only)

Produces the shared image library used by the in-app manual and the developer guide:
`docs/assets/screens/<id>.png` plus `docs/assets/manifest.json`. It is **not** part of
`frontend/` and ships nothing to customers; it has its own `package.json`
(`playwright-core` only).

## Run

```pwsh
cd tools/screenshots
npm install            # once: installs playwright-core only (no browser download)
npm run capture        # = node capture.mjs; refreshes every route in routes.json
node capture.mjs --only dashboard,recipes    # refresh a subset; other manifest entries are kept
node capture.mjs --viewport 1280x800         # smaller images if the set grows past ~4 MB
node capture.mjs --no-seed                   # skip seed.py
```

## Prerequisites

- **Microsoft Edge** installed (ships with Windows). It is driven with
  `chromium.launch({ channel: "msedge" })`; if Edge is missing the run fails with a clear
  message, it never downloads a browser or skips silently.
- **Python** on PATH (`PYTHON` env var overrides) with the backend deps installed, and Node 18+.
- `backend/config/app.json` + `license.json` (copy from the `*.example.json` on first run).
- A Mosquitto broker on `:1883` is normal on a dev machine; without one the backend still
  starts, MQTT-backed panels just show offline.
- Dev login `admin` / `admin` (override with `TMF_SCREENSHOT_USER` / `TMF_SCREENSHOT_PASSWORD`).

## What a run does

1. **Starts a PRISTINE throw-away station** (`run_isolated.py`): fresh state dir in the OS temp
   folder, live config copied from the framework's own `*.example.json`, empty database,
   supervised by the same `launcher` a real station uses. It never reads or writes
   `backend/config/app.json` or `backend/data/`, so the shared images show the *neutral*
   framework — not this machine's fork branding, instruments or logs. It builds `frontend/`
   first if `dist/` is missing, waits for health, and **stops the station again** at the end
   via `POST /system/shutdown` (falling back to killing the process tree). If something already
   listens on `:8000` it **refuses to run** (that station's branding/data would leak into the
   images); `--reuse-running` overrides for a throw-away experiment — never commit that output.
   If a broker is listening on `:1883` it also starts the framework's reference LabVIEW stub
   (`backend/tools/lv_stub.py`, station `st1`, stopped again at the end) so the dashboard reads
   "station ready" instead of a red "bridge offline" banner. It uses the shared local broker, so
   don't run a real `st1` controller while capturing. Without a broker the offline state is
   captured as-is (and a warning is printed).
2. `seed.py` (stdlib only, idempotent, public REST API only) makes the UI look populated
   with obviously-labelled demo data: simulated instruments (from whichever driver
   libraries the station has registered), two "Demo recipe" recipes, two demo users
   (their generated temporary passwords are discarded). If it seeded Python instruments and
   this run started the station, the backend is relaunched once so they build. On a reused
   station that restart is left to you.
3. Logs in over REST, sets `tmf.token` + `tmf.colormode=light` in localStorage before load,
   then visits each route in `routes.json` at a fixed viewport (default 1440x900,
   `deviceScaleFactor: 1`, animations/transitions/caret disabled), waits for network idle
   and for `wait_for` text inside `<main>`, settles, and writes the PNG.
4. Merges `docs/assets/manifest.json` (sorted by id, 2-space indent, LF).

A route that lands on the login page, never shows its `wait_for` text, or has a missing
`screen_source` fails loudly: no image and no manifest entry are written for it, and the
run exits non-zero.

## routes.json

Array of `{ id, route, screen_source, alt, audience, wait_for }`. `screen_source` is the
repo-relative React file that renders the route; `audience` is `both` or `dev`; `wait_for`
is text expected in the page's `<main>`.

## How staleness works

Each manifest entry records `framework_version` (`__version__` from
`backend/core/__init__.py`), the `source` screen file, and `source_hash`: the first 16 hex
chars of the sha256 of that file's bytes with every `\r\n` replaced by `\n` (exactly
`catalog.source_hash` in `backend/modules/help/catalog.py`). When the screen's source
changes, its hash no longer matches and the help catalog can flag the image as stale; re-run
`node capture.mjs --only <id>` to refresh it.
