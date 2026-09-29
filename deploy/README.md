# deploy/ — broker, bundling, local run

The MQTT broker is **Mosquitto**, a standalone program (not Python, not
LabVIEW). Both sides are clients of it (LABVIEW_BRIDGE.md §2). One local broker
per station, bound to loopback.

## Files

| File | Purpose |
|---|---|
| **`cut-release.ps1`** | **The ONE build/release entry.** Builds (and, without `-BuildOnly`, publishes) an app release — it invokes `fetch-mosquitto.ps1`, `backend/build_release.py`, the signer, and `build-installer.ps1` internally. Run this, not the sub-scripts. (To *run* the app, use `station.py`.) |
| `mosquitto.conf` | Station broker config — loopback `127.0.0.1:1883`, anonymous (local trust boundary). Central-uplink template commented in. |
| `fetch-mosquitto.ps1` | Internal step (invoked by `cut-release.ps1`): vendors the broker runtime into `vendor/mosquitto/win64/` for bundling. |
| `run-local.ps1` | Brings up broker + app + LabVIEW stub for a graphical-first demo (niche; `station.py` is the normal way to run). |
| `vendor/mosquitto/` | Vendored broker runtime (gitignored; produced by `fetch-mosquitto.ps1`). |
| `installer.iss.template` | Inno Setup template for the OFFLINE first-install `setup.exe` (rendered per fork). |
| `build-installer.ps1` | Internal step (invoked by `cut-release.ps1`): renders `installer.iss` from the template + branding/VERSION and compiles it with ISCC. |
| `install-station.ps1` | Scriptable/headless first-install fallback (needs Python + a broker service). |
| `update-package.iss.template` | Inno Setup template for the OFFLINE **update delivery** tool `<AppShort>-Update-<ver>.exe` — drops an already-signed update into an EXISTING install's fixed incoming-update slot. It never applies/verifies anything itself — see the template's header. |
| `build-update-package.ps1` | Optional step (invoked by `cut-release.ps1 -BuildUpdatePackage`): signs the update from an existing `release-build/`, renders `update-package.iss` and compiles it. Air-gapped fleets only — a networked station never needs this. |

## Shipping the broker with the frozen station

The frozen app carries its **own** broker — no Mosquitto installer, no Windows
service, no admin:

1. **Build prep** — `./deploy/fetch-mosquitto.ps1` downloads the official build
   and copies the minimal runtime (`mosquitto.exe` + DLLs + loopback
   `mosquitto.conf`) into `deploy/vendor/mosquitto/win64/`. CI runs it before the
   build; it is gitignored.
2. **Bundle** — `build_release.py --track app` copies that folder **into**
   `run.dist/vendor/mosquitto/win64/`, so it rides inside the swap unit: every
   app-track build and every in-app update carries the broker and it survives a
   run.dist swap.
3. **Launch** — `station.py` (or the frozen `run_station.exe`) `start_broker()` prefers
   `run.dist/vendor/mosquitto/win64/mosquitto.exe` and launches it with `-c` on
   the sibling loopback `mosquitto.conf` (Mosquitto 2.x refuses anonymous clients
   with no config), before the controller/bridge connect. The bridge retries
   until the broker is up, so ordering is forgiving.

The offline `setup.exe` (built from `installer.iss.template` by
`build-installer.ps1`) therefore ships no broker of its own — it's already inside
`run.dist`. `deploy/run-local.ps1` demonstrates the launch sequence for dev and
prefers the vendored broker when present.

## Verify it works

```pwsh
./deploy/fetch-mosquitto.ps1     # once, to vendor the broker
./deploy/run-local.ps1           # broker + app + stub
```

Then watch `tmf/#` in MQTT Explorer and hit
`http://127.0.0.1:8000/hello/ping` (see ../docs/PHASE0_ACCEPTANCE.md).

## Note: stray Mosquitto service

The official Windows installer registers an **always-on `mosquitto` Windows
service** on port 1883. The bundled-broker model does not want that (the shell
manages the broker per station). If a machine has that service from a prior
install, disable it (admin shell), or it will hold 1883:

```pwsh
Stop-Service mosquitto; Set-Service mosquitto -StartupType Disabled
```

The test suite is unaffected — it spins brokers on ephemeral ports.
