# RUNNING — launching the station

Two ways to run the app, one shared edge. Both bring up the same three processes
(broker, backend, controller); they differ only in how the UI is served and shown.

| | `dev.ps1` | `station.py` |
|---|---|---|
| Windows | three (mosquitto, Vite, backend) + browser tab | one process |
| Frontend | Vite dev server on `:5173` (HMR), proxying the API to `:8000` | backend serves the **built** bundle on `:8000` (single origin) |
| Shown in | the default browser | a native **pywebview** window (or browser) |
| For | frontend development (live reload) | operators, demos, a production-feel run |

```pwsh
powershell -ExecutionPolicy Bypass -File .\dev.ps1   # dev: Vite + HMR
python station.py                                    # one-click: built UI in a native window
```

---

## Single-origin serving (`backend/core/services/spa.py`)

In dev the app is two servers (Vite proxies the REST/WS edge). A shipped station has
no Vite: the **backend serves the built SPA itself**, so UI + REST + WebSockets all
live on one origin at `127.0.0.1:8000` and the launcher only has to open that URL.

The API and the SPA share a path namespace — the runs module serves `GET /runs` as
JSON, while the browser navigates to `/runs` for the page. Serving mirrors the dev
Vite `serveSpa` bypass, as HTTP middleware that runs ahead of routing:

- `GET` a real file under the bundle (`/assets/*`, `/favicon.svg`) → that file;
- `GET` with `Accept: text/html` (a browser navigation) → `index.html` (the SPA shell);
- everything else (JSON/WS/API clients) → normal routing.

So a hard refresh on `/runs` returns the app while `fetch("/runs")` still reaches the
runs API. When no built bundle is present (a pure-Vite dev checkout) nothing is
installed and the edge is API-only.

**Bundle resolution** (first that has an `index.html` wins): `TMF_FRONTEND_DIR` env
override → `<repo>/frontend/dist` (source) → `release-build/frontend` beside the
frozen `run.exe` (SECURE_DISTRIBUTION.md §5). A diag line at boot names the dir it
serves from.

---

## `station.py` — the one-click launcher

```pwsh
python station.py                # backend serves the built UI, native pywebview window
python station.py --dev          # Vite + HMR on :5173, window points there
python station.py --browser      # default browser instead of a native window
python station.py --fullscreen   # kiosk-style window (also --frameless)
python station.py --no-window    # run the services only (headless)
python station.py --build        # force a frontend rebuild first
```

What it does, in order:

1. **Broker** — starts the vendored `mosquitto` if `:1883` isn't already up (prefers
   `deploy/vendor/mosquitto/`, then PATH, then Program Files). An already-running
   broker is left alone.
2. **Backend** — spawns `backend/launcher.py` (so the "Relaunch to apply" + signed
   update loop keeps working), in a new process group so shutdown can signal it. The
   backend in turn supervises the Python controller when `controller.kind = "python"`.
3. **Frontend** — production mode serves the built bundle; if it's **missing or
   stale** (any `frontend/src` file newer than `dist/index.html`) it runs
   `npm run build` first, so a source checkout never serves an old UI. A frozen
   release has no `frontend/src`, so its baked bundle is trusted. `--dev` starts Vite
   instead.
4. **Window** — waits for the edge, then opens the UI. pywebview is optional
   (`pip install -e "backend[desktop]"`); without it, the launcher opens the default
   browser and says so.

### Graceful shutdown

Closing the window — or the UI's **Exit station** (in the user menu) — must leave the
bench safe. `station.py` sends the backend a console **CTRL_BREAK**; uvicorn runs its
lifespan teardown (modules stop, the controller drives every instrument to a safe
state, the bridge goes offline, the DB closes) and exits, then the launcher stops.
`launcher.py` shields *only* SIGBREAK so it survives to observe that clean exit;
SIGINT (dev-console Ctrl-C) is untouched. Only what `station.py` started is stopped —
a pre-existing broker keeps running.

This is the same graceful path as `POST /system/shutdown` (MULTI_STATION.md §safe
exit); relaunch-to-apply (exit 42) is handled by `launcher.py` and the window simply
reconnects when the backend comes back.

---

## Running a frozen app build (`release-build/`)

`python build_release.py --track app --product <slug>` produces a self-contained
`release-build/` (SECURE_DISTRIBUTION.md §5). Run it like a shipped station — from the
`release-build/` root (the deploy root), NOT from inside `run.dist/`:

```pwsh
cd release-build
python run_station.py            # native window (broker + supervised backend + controller)
python run_station.py --no-window   # headless (serves the UI on :8000)
python run.dist\launcher.py      # backend + controller only, no window
```

- `run_station.py`/`launcher.py` set `TMF_STATE_DIR` to the deploy root, so live config + DB +
  backups land in `release-build/config` + `release-build/data` (outside the swappable `run.dist`).
- On first boot `config/app.example.json` (promoted from the app's `app.release.json`) is copied to
  the live config, so the app boots with its **own** branding + `controller.kind=python`.
- The supervisor starts the controller as `run.exe --controller` (the backend exe doubles as the
  controller — one compiled exe); it loads the app's step-type
  package (compiled in) and brings the station online (`/readyz`). Configure instrument instances on
  **Config → Instruments** (site config, held in the DB — not in the artifact), then restart to run
  the app's sequence. Needs a Python on PATH (the launcher/window entry are not yet frozen).

---

## Packaging note — the OS window icon

The SVG favicon (`frontend/public/favicon.svg`) covers the **browser tab / WebView tab
icon** and the in-app title bar (`BrandMark`). The **OS window / taskbar icon** of the
pywebview window comes from the *executable's* icon, not the page — Python's icon in a
source run, the `.exe` icon in a frozen build. To brand the taskbar icon, give
`build_release.py`'s Nuitka step `--windows-icon-from-ico=<app.ico>` (needs a real
`.ico`, not the SVG). Not yet wired.

---

## See also

- [FRONTEND.md](FRONTEND.md) — the UI shell (AppBar, nav, the served bundle).
- [MULTI_STATION.md](MULTI_STATION.md) — relaunch, safe exit, `/system/*`.
- [SECURE_DISTRIBUTION.md](SECURE_DISTRIBUTION.md) — the frozen release layout the
  bundle resolver targets.
