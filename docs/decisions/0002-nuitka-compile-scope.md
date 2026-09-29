# ADR 0002 — Narrow the Nuitka compile surface for app-track builds

**Status:** Accepted · **Date:** 2026-09-29 · **Area:** build / release / updates

## Context

`build_release.py` compiles the whole backend with Nuitka for IP protection (a
real one — "decompilation ≈ reverse-engineering a C binary" vs. PyInstaller's
"only zips `.pyc`s — no protection"). For `--track app` this historically meant
force-compiling `core` + `modules` + `controller` **and** the app's own
`step_type_packages` / `library_packages` / `instrument_libs` into one `run.exe`.

Two problems came from treating all of that as one undifferentiated blob:

1. **Build time.** Nuitka's Python→C analysis and codegen phase re-runs over
   everything included on every build; only the C-compiler step is cached
   (clcache/ccache). A warm rebuild still pays full analysis+codegen cost for
   app-owned packages that may not have changed at all.
2. **Patch granularity.** The update mechanism (`core/services/updates.py`,
   `launcher.py`) only knew how to swap the *entire* `run.dist` tree, because
   everything — framework code and app-owned code alike — was baked into one
   binary. A one-line bugfix in a customer's step type required a full
   recompile + full-tree swap, identical in cost and blast radius to a
   framework upgrade.

Neither of these is really about the framework's own IP. Per `CLAUDE.md`'s
fork-ownership boundary, `app/<name>/` (step types, recipes, variable maps,
`controller.json`) is explicitly **app-owned**, not framework IP — a fork's own
test logic and drivers are the integrator's business logic, not
Super_Test_App's. Compiling it in was protecting something this repo doesn't
actually claim to own.

## Decision

**Narrow the compile surface by default.** `--track app` builds still
force-compile `core` + `modules` + `controller` (the actual framework IP) into
`run.exe`, but no longer force-compile the app's `step_type_packages` /
`library_packages` / `instrument_libs`. Those ship as plain `.py` under
`run.dist/app/<product>/` and `run.dist/instrument_libs/` instead, loaded at
runtime via `sys.path` + `importlib.import_module` — a mechanism the controller
(`controller/controller/packages.py`, `controller/controller/instruments/
registry.py`) already had for dev/standalone use; this just wires it into the
frozen build too (`controller_supervisor.py` now auto-appends the app-payload
directory to `step_type_paths`/`library_paths` in the generated config).

`--compile-app-payload` opts back into the old fully-compiled behavior, for any
fork that wants its OWN step types/drivers protected too and doesn't need
patch-sized updates for them. That is the fork owner's call, not a
framework-wide policy.

Once app payload is decoupled from the compiled binary, a second, smaller
release artifact becomes possible: `package_app_payload_artifact()` zips just
`run.dist/app/` + `run.dist/instrument_libs/`. `sign_update.py` gains
`KS_ARTIFACT_SCOPE` (`full` default, or `app-payload`) to pick which of
`RELEASE.json`'s two hashes becomes the signed `full_artifact_hash` field —
**there is deliberately no new field on the signed manifest itself**. The
station instead *detects* scope after hash verification, from the extracted
content: a top-level `run.exe` means a full artifact; its absence means an
app-payload-only one. `updates.py`'s `_stage_zip_bytes` does this detection
once, and every caller (`download()`, `install_from_file()`,
`request_relaunch()`) threads the *detected* scope through as plain
(unsigned, but no longer trust-relevant) offer/marker metadata. The launcher's
swap, for a detected `"app-payload"` scope, reuses `SwapManager` (already
fully path-generic — nothing run.dist-specific about it) scoped to
`run.dist/app` and `run.dist/instrument_libs` as two independent swap units,
leaving `run.exe` untouched.

**Why not a signed `scope` field (the design's first draft, corrected before
shipping):** `tools/ks_release_signer/canonical.py`'s
`manifest_signing_bytes()` mirrors a FIXED Rust struct
(`core/src/manifest.rs`, external `Build License Track` repo) byte-for-byte —
it does not sign "whatever's in the Python dict," only the specific fields it
explicitly encodes. A `scope`/second-hash field added only to the Python side
would ride along in the JSON as **unsigned, attacker-editable metadata**: an
attacker able to edit an already-signed `.ksupdate` file (in transit, or on a
USB stick for the air-gapped path) could relabel any legitimately-signed
manifest as `scope: "app-payload"` with an attacker-chosen
`app_payload_artifact_hash`, and the hash check would then verify their own
malicious zip against their own unsigned hash claim — signature intact,
content arbitrary. Detecting scope from the already-hash-verified bytes has
no such gap: content that matches the one SIGNED `full_artifact_hash` is
exactly as trustworthy as the signature, whatever shape it turns out to have.

## Why (blunt)

1. **App-owned code isn't framework IP.** Protecting it with the framework's
   own compile step was solving the wrong problem — see the fork-ownership
   boundary in `CLAUDE.md`. Framework code keeps full protection; nothing
   changes there.
2. **Framework hot-patching was never the design intent.** `CLAUDE.md`: "a fork
   needing a framework change gets it via a framework release, never a
   downstream patch." The friction this ADR addresses — a small patch
   unlocking a bugfix/feature on a client's deployed station — is squarely
   about app-owned code, which narrowing directly enables. A full plugin/DLL
   redesign for framework-level hot-patching would solve a problem the repo's
   own design says shouldn't exist, and would partially reverse v1.11.0's
   deliberate collapse of `run.exe`+`controller.exe` into one artifact (done
   specifically to cut build time and complexity).
3. **Smaller compile graph, faster builds.** Removing app payload from
   Nuitka's analysis+codegen surface (not just the C-compile step, which was
   already cached) is a real, proportional saving on `--track app` builds —
   the common case during app development.
4. **The existing runtime-loading mechanism made this cheap.** `controller/
   controller/packages.py` and `.../instruments/registry.py` already supported
   loading step-type/library packages from disk via `sys.path` for dev use;
   narrowing just extends that same, already-tested path to the frozen build
   instead of inventing a new loading mechanism.

## Known limitations (accepted for v1)

- **`RELEASE.json`'s version field is not updated by an app-payload-only
  swap** (it lives outside the swapped subdirectories). The authoritative
  per-app version — `run.dist/app/<product>/VERSION` — *is* inside the swap
  unit and is correct after the patch; only the top-level `RELEASE.json`
  summary lags until the next full-scope release. Acceptable: `VERSION` is the
  source of truth an app already reads; `RELEASE.json` was never authoritative
  for the app's own version (see `manifest()`'s two-tier `version`/
  `framework_version` split).
- **No dedicated rollback UI for an app-payload-only patch.** The existing
  safety net (two failed boots → revert to `last_known_good`) still applies
  and correctly undoes a bad app-payload patch too, because
  `mark_last_known_good()` snapshots the whole live `run.dist` — including
  whatever app payload is live at that moment — wholesale. There is no
  separate "roll back just the last app-payload patch" operator action in
  this pass.
- **A release publishes exactly one scope** (UPDATES.md §3's existing "exactly
  one `.ksupdate`, exactly one `.zip`" rule is unchanged) — `sign_update.py`'s
  `KS_ARTIFACT_SCOPE` picks which artifact this particular release signs and
  ships, decided by the release process, not negotiated at install time. There
  is no "offer both, let the station choose" mode; that would need genuine
  cross-repo coordination with the external Rust core (`Build License Track`)
  to add a real signed field, which this pass deliberately avoided (see
  "Why not a signed `scope` field" above).
- **Framework-repo (`--track framework`) build times are unaffected** — that
  track never included app payload in the first place, so narrowing has
  nothing to remove there. If framework iteration speed is *also* a pain
  point, that is a separate question (likely just "framework code is large
  enough that Nuitka's own analysis floor is the cost," which only a
  framework-level redesign — explicitly not pursued here, see point 2 above —
  would address).
