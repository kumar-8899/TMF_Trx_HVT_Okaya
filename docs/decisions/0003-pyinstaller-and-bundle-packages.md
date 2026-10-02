# ADR 0003 — Replace Nuitka with PyInstaller; always bundle app packages; drop dual-scope updates

**Status:** Accepted · **Date:** 2026-09-29 · **Area:** build / release / updates

## Context

Nuitka compiles Python→C→machine code. That gave the backend real IP
protection (a compiled binary, not just zipped bytecode), but the cost was a
15–45 minute build — every `--track app` iteration during app development
paid that in full. A real timed build measured **~944s (15.7 min)** for the
PyInstaller-equivalent command with a naive flag set (see below) — over a
hard, user-set gate of 10 minutes for the whole workflow: edit code, build one
exe, test it, iterate — mirrored on the LabVIEW workflow this framework
targets, where a build is "maximum 10 min."

IP protection was also never the load-bearing reason app-track builds were
slow: ADR 0002 (narrowing the Nuitka compile surface) already established
that app-owned code (`app/<name>/`, step types, drivers) isn't framework IP
in the first place — only `core`/`modules`/`controller` are. ADR 0002's fix
was a real but partial mitigation (skip app packages, ship them as plain
`.py`, load via `sys.path`); it didn't touch the *framework* compile cost,
and it introduced its own complexity (a `sys.path`-injection mechanism in
`controller_supervisor.py`, a second release artifact, a dual-scope update
system to apply it as an independent patch).

Separately, ADR 0002's narrow-compile-surface had a live bug: excluding
`instrument_libs` from the Nuitka compile graph by default silently broke
`pyvisa`'s bundling. `pyvisa` is never imported by the framework itself — only
by fork-owned driver code (`instrument_libs/transports/visa.py`), reached via
`importlib.import_module()` at runtime. Before ADR 0002, `instrument_libs`
was force-included in the compile graph, so Nuitka's own transitive
import-following discovered `import pyvisa` inside it automatically. Once
that package was excluded by default, the transitive discovery silently
stopped — a working build shipped without a working VISA backend, with no
error at build time.

## Decision

**Replace Nuitka with PyInstaller for the backend** (`run.py` → `run.exe`).
No compile step, no IP protection — PyInstaller ships plain bytecode,
trivially decompilable, the same tradeoff `tmf-sidecar.spec` (retired earlier)
always made. That trade is explicit and deliberate: build time now dominates
over protecting code that (for the framework's own `core`/`modules`) nobody
has asked to protect yet, and (for app-owned code) was never this framework's
IP to protect. Re-introduce protection later as its own decision if it's ever
actually needed — nothing here forecloses it.

**Output layout stays what Nuitka produced**: `--onedir --contents-directory=.`
gives a flat `run.dist/run.exe` + siblings, no `_internal/` subfolder — every
`sys.executable`-parent-relative path resolution already in the codebase
(`spa.py`, `docs_paths.py`, `config.py`, `core/__init__.py`) works unchanged.
PyInstaller ties `--name` to both the output folder and the exe stem
(`OUT/run/run.exe`, not `OUT/run.dist/run.exe`), so `build_backend()` does one
explicit `Path.rename()` after the subprocess call — a like-for-like
replacement of what Nuitka's `.dist`-suffixed `--output-dir` already did.

**Revert ADR 0002's narrow-compile-surface entirely, not just retarget it.**
Once packages are frozen instead of compiled, "narrow vs. compile-in" stops
meaning anything — that distinction only ever mattered under a real
machine-code compiler. The app's own `step_type_packages` / `library_packages`
/ `instrument_libs` are now **always** bundled by name
(`--collect-submodules`), exactly like `core`/`modules` already were — this is
also the pyvisa fix: it restores the pre-ADR-0002 behavior where
`instrument_libs` is always in the import graph, so ordinary transitive
import-following finds `import pyvisa` inside it again. No new
dependency-declaration config surface was added for this — `_app_include_packages()`
(reading `step_type_packages`/`library_packages` from `app/<product>/controller.json`)
already existed and needed no changes.

Removed as a result (all existed solely to serve narrow-compile-surface):
`copy_app_code_packages()`, `_resolve_package_dir()`, the
`step_type_paths`/`library_paths` auto-append block in
`controller_supervisor.py:_write_config()`, `package_app_payload_artifact()`,
the `--compile-app-payload` CLI flag.

**One residual gap needed a small, explicit fix.** Ordinary import-following
(Nuitka's or PyInstaller's) still can't see `pyvisa`'s own backend discovery,
which goes through `importlib.metadata.entry_points()` — invisible to any
static analyzer. Two framework-owned constants cover it, bundled only when
installed (mirrors the existing `keystation` opt-in pattern):
`_PYVISA_METADATA_PACKAGES = ("pyvisa",)` → `--copy-metadata=pyvisa` (fixes
the entry-point lookup), `_PYVISA_BACKEND_PACKAGES = ("pyvisa_py",)` →
`--collect-all=pyvisa_py` (nothing statically imports it). This is the entire
"dependency declaration" story for this pass — no `controller.json` schema
change, no general `bundle_packages` config surface (considered and dropped:
every other case is already solved by ordinary bundling-by-name).

**Revert the dual-scope update system.** It existed only to make an
app-payload-only patch cheap under Nuitka's slow rebuilds — with PyInstaller,
a full-tree build+swap is itself fast enough that the extra mechanism (a
second release artifact, `KS_ARTIFACT_SCOPE`, scope detection in
`_stage_zip_bytes`, two independent `SwapManager`s in `launcher.py`, `-Scope`
on `cut-release.ps1`) is complexity with no remaining problem to solve.
Updates are full-tree again: one signed `.ksupdate`, one `.zip`
(`run.dist`), one `SwapManager`. **Kept, simplified to one slot**: the
"no manual path typing" convenience (`UpdateService.scan_incoming()` /
`POST /update/scan-incoming` / the Updates page's "Scan for updates on this
PC" button, `deploy/build-update-package.ps1` + `update-package.iss.template`)
— now a single `<data_dir>/updates/incoming/{update.ksupdate,update.zip}`
slot instead of two.

**A measured, minimal flag set — not "collect everything."** The first timed
build (~944s) used `--clean` plus explicit `--collect-submodules=sqlalchemy`
and `--collect-submodules=uvicorn`. Both are unnecessary: PyInstaller ships
its own hooks for both (`PyInstaller/hooks/hook-sqlalchemy.py`,
`_pyinstaller_hooks_contrib/stdhooks/hook-uvicorn.py`) that fire automatically
from ordinary import-following. sqlalchemy's own hook is actually *smarter*
than a blanket `--collect-submodules` — it explicitly excludes
`sqlalchemy.testing` ("causes bundling a lot of unnecessary modules"), which
the forced flag overrode, walking a large excluded subtree for no reason.
`--clean` wipes PyInstaller's own bytecode-analysis cache every run, so even a
warm rebuild paid full analysis cost. Removing all three (validated on a real,
uncontended build): **82–84s**, about 7x under the 10-minute gate.

## Why (blunt)

1. **Build time was the actual, stated problem**, and it had a straightforward
   fix (drop the compiler) once IP protection was explicitly deferred by the
   person who owns that tradeoff.
2. **The narrow-compile-surface / dual-scope machinery was a workaround for
   Nuitka's build time**, not an independent feature. Once the underlying
   problem (slow builds) is gone, the workaround is just standing complexity —
   removing it is not a loss, it's returning to the simpler pre-ADR-0002
   shape now that the reason for the detour no longer applies.
3. **PyInstaller's own hooks are usually better than a hand-rolled override.**
   `--collect-submodules=X` should be reserved for packages that genuinely
   need it (dynamic-discovery frameworks like `core`/`modules`, or packages
   with no contrib hook at all) — not applied blanket to everything that
   might need bundling, which can silently defeat a smarter hook already
   shipped for that exact package.
4. **Measure, then decide — not the other way around.** The whole migration
   was gated on a real, timed build before any broader change was made; the
   944s → 82s optimization was itself found by measuring, not guessed.

## Known limitations (accepted for v1)

- **No IP protection for the framework or app-owned code.** PyInstaller's
  output is plain, extractable bytecode. If protection is ever needed again,
  that is a fresh decision (Nuitka, a commercial obfuscator, or something
  else) — not a partial reintroduction of this ADR's narrow-compile idea,
  which solved a build-time problem, not a protection one.
- **A patch to app-owned code is a full-tree build + swap again**, same cost
  as a framework upgrade. Given the measured ~1.5 minute build time, this is
  judged acceptable — the dual-scope mechanism it replaces existed
  specifically to avoid a *slow* full rebuild, and that's no longer the
  situation.
- (Superseded by the addendum below — `run_station.exe` was NOT actually fast,
  and has since moved off Nuitka too.)

## Addendum (same day) — run_station.exe was not actually fast either

The "known limitation" this addendum replaces assumed `run_station.exe`'s
Nuitka onefile compile was cheap because it's a small, single-purpose target.
It measured real: a clean, isolated `build_run_station_exe()` timing came in
at **662.7s (11.05 min)** — with the C-compile step **100% cache-hit**
(528/528 files), meaning the cost was entirely Nuitka's own per-build
Python-analysis/codegen phase, the identical architectural problem the
backend had. Nuitka is now fully retired from this repo: `build_run_station_exe()`
runs PyInstaller `--onefile` too, using the same principle as the backend
(bundle by ordinary import following; exclude only what's genuinely
irrelevant). Measured: **80.2s (1.34 min)**, including a full runtime smoke
test that passed (backend reached `/healthz`, a real window opened) —
roughly 8x faster, and verified correct, not just faster.

**pywebview's platform-exclusion list carries over unchanged.**
`webview/guilib.py` tries every backend's import in turn inside a try/except
(`android`, `cocoa`, `gtk`, `qt`, `winforms`) — real
`import webview.platforms.X` statements, so PyInstaller's Analysis finds all
of them exactly like Nuitka's import-following did, regardless of which OS
actually needs which. The same exclusion set (`_WEBVIEW_NOFOLLOW`) translates
directly: Nuitka's `--nofollow-import-to` becomes PyInstaller's
`--exclude-module`, one flag per platform. `winforms`, its `win32.py` helper
(webview's own module, not pywin32), and `edgechromium` stay unexcluded, same
as before. `_pyinstaller_hooks_contrib` ships a dedicated `hook-webview.py`
(data files + DLLs) plus `hook-clr.py`/`hook-clr_loader.py` (pythonnet, which
`winforms.py` needs for its .NET interop) — solid out-of-the-box support with
no plugin-conflict workaround needed (Nuitka's own pywebview plugin had a
real bug here — see git history for the original `_WEBVIEW_NOFOLLOW` comment).

**Known, accepted tradeoff: onefile startup latency.** A PyInstaller onefile
exe unpacks itself to a temp directory on every launch — unlike Nuitka's
onefile, which is a genuinely compiled single binary with instant startup.
For `run_station.exe`, a one-click "double the icon, the app opens" launcher,
this means a brief (~1-3s) delay before the window appears, every time. This
was a known, explicit tradeoff at decision time (build-time speed over
launch-time latency), not an oversight — PyInstaller `--onedir` would avoid
it but changes `run_station.exe` from one sibling file into a folder,
touching the Inno installer template, the GitHub Release asset list, and
`RELEASE.json`'s hashing; not pursued in this pass.

**`station.py`'s frozen-detection now checks `sys.frozen`, not just
`__compiled__`.** `ROOT` is computed from `sys.executable` when frozen
(PyInstaller's own documented pattern for finding the real exe path, since
`__file__` would resolve into the onefile temp extraction dir instead).

**`deploy/cut-release.ps1`'s `NUITKA_CACHE_DIR`/`-CacheDir` mechanism is now
removed** — it is genuinely dead: nothing in this repo invokes Nuitka
anywhere anymore (confirmed by a repo-wide search). `nuitka` and `zstandard`
(onefile compression, Nuitka-specific) are dropped from
`backend/pyproject.toml`'s `release` extra; only `pyinstaller` + `pywebview`
remain. The `docs/templates/release.yml` "Cache Nuitka build" CI step is
removed for the same reason.
