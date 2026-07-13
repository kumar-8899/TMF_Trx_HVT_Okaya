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

## 5. Release protection (P2 — planned)

- **Nuitka** compiles the backend Python → C → native (the Keystation framework-track
  artifact). PyInstaller (`tmf-sidecar.spec`) remains for dev-only bundles.
- Build runs in CI on `release/*` branches; the artifact is hashed, signed
  (manifest + signed `build_timestamp`), and registered as a framework release.
- Private signing keys live in the issuer's HSM / CI secrets — never in this repo.

## 6. Signed updates (P3 — planned)

- Station pulls a signed release manifest → `ks.ingest_manifest(.ksupdate)` verifies
  (cert chain → embedded root; `valid_from ≤ build_timestamp ≤ valid_until`) and
  advances the anti-rollback tripwire (even if the update is declined).
- Apply is **operator-gated** (publish ≠ deploy); core-DLL hot-swap honors
  `abi_version` / `min_abi_required` and the app's pin mode (`floor` | `hard`).

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

- Adapter + factory + gate wiring + `/license/*` endpoints + Settings UI: **done**;
  backend suite green (295); adapter tests run with a fake SDK (CI needs no DLL).
- Real core smoke on this machine: unactivated DLL → `bootstrap=UNACTIVATED`,
  `ks.has(...)=False` (fail-closed proven); Keystation e2e airgap test passed.
- Deferred (explicit): secrets-at-rest (DPAPI), MQTT/web hardening, telemetry consent,
  LabVIEW-side licensing (`sdk-labview` launcher shell — parallel effort).
