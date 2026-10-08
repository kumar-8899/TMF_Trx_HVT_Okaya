# The release gate

`cut-release.ps1` step **5b** boots the **built** `run.exe` the way a client's first boot would and **fails the release
before anything is signed or published** unless it works. Source-mode tests cannot catch this bug class: shipped config
drift, a module the shipped license does not entitle, a `__file__`-relative path that is wrong inside the exe, package
metadata PyInstaller dropped, and native drivers that crash only in the frozen exe.

```pwsh
.\deploy\verify-build.ps1                # after build_release.py --track app (cut-release runs it for you)
.\deploy\verify-build.ps1 -Slug <app> -Port 18765
```

## What it checks

| # | Check | Fails when |
|---|---|---|
| 1 | **Metadata** - `release-probes.json` `required_metadata` | a listed package's `*.dist-info` is not inside `run.dist` (PyInstaller drops it; `nidaqmx`/`nitypes`/`pyvisa` fail at import without it). `build_release.py` already derives the set from the app's drivers (`_driver_metadata_packages`); list here what you want *proven*. |
| 1b | **Forbidden GUI toolkits** - built-in: `PyQt5/6`, `PySide2/6`, `matplotlib`, `tkinter`, `Qt5Core.dll`; the app may add to `forbid_in_dist` | any is bundled. Qt ships an old `MSVCP140.dll`; Windows reuses an already-loaded DLL by name, so NI-DAQmx's `DAQmxCreateTask` died with *access violation* - only in the frozen exe. `run.exe` is built with `--exclude-module` for all of them (`_BACKEND_EXCLUDED_MODULES`). |
| 1c | `forbid_in_dist_root` (optional, app-owned) | a listed runtime DLL sits next to `run.exe` and would shadow the system MSVC runtime. |
| 2 | **First boot** on an EMPTY state dir (`TMF_STATE_DIR`), private port (`TMF_PORT`, default 18765) | `/healthz` does not answer; config was not seeded from the shipped `*.example.json`. |
| 3 | **Every module in the shipped config is loaded** (`/modules/status`) | any is skipped (not licensed, unknown variant, not registered) or missing. |
| 4 | **API probes** - `probes[]` (`path`, `auth`, `min_items`) as the seeded admin | a probe returns fewer than `min_items`. |
| 5 | **Controller probes** - `controller_probes[]` | a *real driver call* through the built exe's controller (`run.exe --controller` over a private Mosquitto) fails or gets no reply. Skipped (loudly) when the required device is absent on the build PC. **Read-only calls only** - the device may be real hardware. |

## `app/<slug>/release-probes.json`

Optional but recommended; schema `deploy/release-probes.schema.json`, example `docs/templates/release-probes.example.json`.
Add a probe **whenever a bug shows up only in an installed build**. The framework defaults (1b) apply even with no file.

## Related build rules (enforced in `build_release.py`)

- **Entitlements.** Licensing is fail-closed and `license.example.json` can only name framework modules, so an app
  module stays OFF on a fresh install. Put the app's entitlements in `app/<slug>/license.entitlements.json`
  (`{"modules": {"<id>": true}, "variants": {"<id>": ["default"]}}`); the build merges it into the shipped
  `config/license.example.json` and **fails** when any module in the shipped app config would not activate.
- **Package metadata** is derived from what `instrument_libs/` imports (plus its dependencies), on top of `pyvisa`,
  `nidaqmx`, `nitypes`.
- **`TMF_PORT`** (backend) lets the gate run while a real station owns :8000.

## Resume and preflight

`cut-release.ps1` checks at the **start** that :8000 is free (the `run_station.exe` smoke test refuses to pass against a
running station) and whether Mosquitto is pre-staged. A failure after the tag push is **resumable**: re-run the same
command; a tag already at HEAD is reused and an existing GitHub Release gets its assets/notes replaced - no version bump.
Release notes are read and written as UTF-8 without a BOM (PowerShell 5.1 otherwise mangles non-ASCII such as the em dash).
Pre-stage `deploy/vendor/mosquitto/win64` once (it needs a UAC click) so unattended runs work; `fetch-mosquitto.ps1` is a
no-op when it is present (`-Force` re-fetches).
