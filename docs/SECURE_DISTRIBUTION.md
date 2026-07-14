# Secure distribution — Keystation integration

How Super_Test_App is licensed, protected, and updated. The licensing system is
**Keystation** (repo `Build License Track`): a native Rust core (Ed25519, embedded
trust roots), a Python SDK (`keystation`, a cffi shim that *asks, never asserts*),
an issuer server + portal, and a 3-track signed release/update model
(core DLL · framework · app). Super_Test_App is registered as Keystation's
**framework track** (`runtime=python_framework`); each client deployment is an
*app-track* release pinning the `(core, framework)` versions it was validated with.

Phases: **P1 licensing (done)** → P2 obfuscated release build + CI (Nuitka,
`release/*` branch) → P3 signed code updates (`.ksupdate`, operator-gated apply).

---

## 1. Architecture (P1)

```
app.json licensing.provider ──► build_licensing()          core/services/licensing_keystation.py
        "stub" (default)   ──►  Licensing (path-based license.json, dev only)
        "keystation"       ──►  KeystationLicensing ──► keystation SDK ──► keystation_core.dll
                                                                             (Ed25519 verify,
                                                                              machine-bound lease,
                                                                              DPAPI/TPM key)
```

The three Keystation touch-points (its `framework.py` reference contract):

1. **init-runs-SDK-init** — `core/app.py` builds the provider at startup; `ks.status()`
   is read; an unactivated station boots honestly *unlicensed* (premium modules OFF),
   never crashes.
2. **runner-wraps-session** — `runs.run_start` executes inside `licensing.session()`
   (entitlement snapshot pinned; issuer notice shown once). LabVIEW owns execution, so
   Python's run boundary is the start decision.
3. **plugin-loader-gates** — the existing activation gate (`core/framework/gate.py`)
   calls `License.allows_module/variant` — **unchanged**; with the Keystation provider
   those answers come from `ks.has()`.

**Fail-closed everywhere**: SDK missing, DLL missing, unactivated, expired, tripwire,
or any core error ⇒ not licensed ⇒ the gate leaves the module OFF.

## 2. Configuration (`backend/config/app.json`)

```json
"licensing": {
  "provider": "keystation",                       // or "stub" (default; dev only)
  "core_lib": "C:/path/to/keystation_core.dll",   // optional; else KEYSTATION_CORE_LIB env
  "key_map": {                                     // optional overrides; default plugin.<module_id>
    "daq": "plugin.daq_premium"
  }
}
```

## 3. Entitlement map (the contract with the issuer)

Keys are namespaced (`plugin.* / feature.* / quota.* / metered.*`). Defaults:
module `<id>` → `plugin.<id>`; feature `<k>` → `feature.<k>`; a variant is only
restricted when a `key_map` entry `"<module>:<variant>"` exists.

| Super_Test_App unit | Keystation key |
|---|---|
| module `report` | `plugin.report` |
| module `daq` | `plugin.daq` |
| module `recipe` | `plugin.recipe` |
| module `runs` | `plugin.runs` |
| module `health` | `plugin.health` |
| module `mes` | `plugin.mes` |
| module `variables` | `plugin.variables` |
| module `config` / `auth` / `logs` / `help` / `hello` | `plugin.<id>` |
| report DB store | `feature.report_db` |
| shifts / business day | `feature.shift` |
| (optional metering) | `metered.test_executions` |

Register the same keys as entitlement grants on the license in the Keystation issuer.

## 4. Activation (Settings → License, gated SYSTEM.SETTINGS)

- **Status**: `GET /license/status` → provider, state (`VALID/WARNING/GRACE/EXPIRED`),
  bootstrap (`FRESH/UNACTIVATED/ACTIVE`), key tier (tpm/dpapi), tripwire.
- **Air-gapped (Path B)**: *Export activation request* → device-signed `.ksreq`
  downloads → mint a `.kslease` on the issuer → copy to the station → *Install lease*
  (`POST /license/activate {bundle_path}`) → restart re-runs the module gate.
- **Online (Path A)**: the issuer returns the `.kslease` inline; install is the same
  ingest. (UI wiring for inline activation follows with the server deployment.)

Dev without the production PKI: the SDK e2e harness
(`Build License Track/sdk-python/tests/test_sdk_e2e.py`) builds a test-roots core and
mints a dev lease — verified green on this workstation.

## 5. Release protection (P2)

- **Nuitka** compiles the backend Python → C → native machine code (real IP
  protection; decompilation ≈ reverse-engineering a C binary). This is the Keystation
  `python_framework` **framework-track** artifact. PyInstaller (`tmf-sidecar.spec`)
  remains for dev-only bundles (it only zips `.pyc`s — no protection).
- Build: `cd backend && pip install -e ".[release]" && python build_release.py`
  → `release-build/` = `run.dist/` (compiled backend + bundled manifests/schemas)
  + `docs/` (in-app help) + `frontend/` (built SPA) + `keystation_core.dll`
  + `RELEASE.json` (version + SHA-256 of every file).
- CI: `.github/workflows/ci.yml` (tests on every push/PR — no DLL needed) and
  `release.yml` (on `release/*` or a `v*` tag: tests → Nuitka build → artifact upload).
- Registration as a **signed** Keystation framework release (manifest + signed
  `build_timestamp` + SBOM) is issuer-side; private signing keys live in the issuer /
  HSM / CI secrets — never in this repo.

## 6. Signed updates (P3)

Station side = **intake · trust · resolve · operator-gate**. A running Nuitka binary
can't replace its own file, so *applying* is a launcher/restart step; the app verifies,
records intent, and stages. `core/services/updates.py` (`UpdateService`):

- **ingest** `POST /update/ingest {bundle_path}` → `licensing.ingest_manifest()` verifies
  through the core (cert chain → embedded root; `valid_from ≤ build_timestamp ≤
  valid_until`) and advances the anti-rollback tripwire (fires even if declined) → the
  parsed manifest is recorded as an offer (DB `update_offer`). A tampered bundle → 502.
- **resolve** (`publish ≠ deploy`): applicable only if track ∈ {framework, app},
  signature verified, offered version > installed (`core.__version__`), and
  `min_abi_required ≤` the station's core ABI. Verdict stored with the offer.
- **offers** `GET /update/offers` → `{current: {version, abi}, offers: [...]}`.
- **apply** `POST /update/apply/{release_id}` (operator-gated) → records `apply_pending`
  + stages; inapplicable → 409. The **launcher** swaps the artifact / core DLL on next
  start, honoring `abi_version` / `min_abi_required` and the app's pin mode
  (`floor` | `hard`) — same model as the LabVIEW A7 launcher shell.

Endpoints share the `_LIC` guard (SYSTEM.SETTINGS when operational; open in activation
mode). Verified live: signed framework `.ksupdate` v1.1.0 ingested → applicable → apply →
`apply_pending`; v0.9.0 → rejected (not newer); tampered manifest → 502.

## 7. Git & CI cheat-sheet (newcomer-friendly)

```
main            protected; always releasable; never commit to it directly
feat/<topic>    branch per change:        git checkout -b feat/<topic>
                commit small + often:     git add <files> && git commit
                push + open a PR:         git push -u origin feat/<topic>
                merge via the PR once CI is green
release/x.y     cut from main for a release; CI builds + signs here
vX.Y.Z          annotated tag = the immutable release:  git tag -a vX.Y.Z -m "..."
```

Rules: secrets (keys, leases, `.env`) never enter Git — `app.json`/`license.json` are
gitignored; CI secrets hold tokens; the signing key lives in the issuer, not here.

## 8. Status / verification

- **P1 done + proven live** on the real `keystation_core.dll`: unactivated →
  all modules gated off + activation mode open; `.ksreq` exported from the app; dev
  issuer minted a `.kslease` (Ed25519 intermediate → dev ceremony root); installed via
  `POST /license/activate` → `VALID/ACTIVE`; restart → 11/11 modules licensed via
  `ks.has()`; operational mode re-gates `/license/*` behind SYSTEM.SETTINGS.
  Backend suite green; adapter tests use a fake SDK (CI needs no DLL).
- **P2**: `build_release.py` (Nuitka) + `ci.yml`/`release.yml` in place. Remaining
  issuer-side: SBOM (cyclonedx) + `POST /releases` registration + Authenticode
  code-signing cert (ops; see Keystation runbook `windows-packaging.md`).
- Deferred (explicit): secrets-at-rest (DPAPI), MQTT/web hardening, telemetry consent,
  LabVIEW-side licensing (`sdk-labview` A7 launcher shell — parallel effort).
