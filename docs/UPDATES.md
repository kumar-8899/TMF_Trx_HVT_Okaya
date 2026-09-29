# UPDATES.md — Update Delivery, Rollback, Recovery & AMC

**Locked design contract.** Peer to `SECURE_DISTRIBUTION.md`, which defines the
signed `.ksupdate` bundle, the Keystation trust chain, `UpdateService`
(ingest/apply/relaunch), and `launcher.py`'s exit-42 swap. Those exist and are
proven live. **This document adds the front half (discovery + download), the
failure semantics, and the commercial model.**

Read `SECURE_DISTRIBUTION.md` §5–6, `TEMPLATE.md`, `APP_REPO.md`, and
`RELEASE_HOWTO.md` first.

**Business premise, and it inverts the usual default.** This is not a
consumer product. A bench PC installed a year ago should keep running exactly
as it is, indefinitely. **An update is a risk to a working production line, not
a benefit.** Updates matter only when a customer is paying for an AMC. Every
decision below follows from that.

---

## 0. Locked decisions

| Decision | Choice | Rationale |
|---|---|---|
| **Discovery** | **Notify only.** The station polls GitHub Releases and raises a notification. It downloads nothing. | Line uptime beats freshness. Nothing arrives on a bench unasked. |
| **Download** | **Manual**, engineer-initiated. | Same. |
| **Install** | **Manual**, engineer-initiated, two distinct clicks (Download, then Install). | Same. |
| **During a run** | Apply is **refused with 409** while a run is active. | Never swap a binary mid-test. |
| **Air-gapped** | `auto_check_minutes: 0` disables discovery. Update from USB via **`/update/install-file`** (`.ksupdate` + `.zip` local paths) — same verify + stage + swap as online, only the source differs (§E-bis); or re-run `setup.exe`. | No internet needed; identical trust + rollback. |
| **Verify failure** | **Terminal, never retried.** | A tampered bundle must never sit in a retry loop. |
| **Idempotency key** | `release_id` + **bundle SHA-256**. Re-ingesting a known hash returns the existing offer and **does not advance the anti-rollback tripwire.** | The tripwire advances on ingest even when declined. A retried download would otherwise advance it twice. |
| **Swap safety** | **Journal-first, rename-only.** The launcher writes a journal before touching anything and reconciles it on every startup. | Power loss between `live→.bak` and `staged→live` leaves the station with no `run.dist` and nothing running to fix it. This is the worst failure mode in the system. |
| **Backups** | **2 by default (configurable), plus a protected `last_known_good` that is never evicted.** Each backup carries a metadata sidecar, not a bare `.bak-<ts>` name. | "Go back one" is wrong when the previous build is also broken. Rollback must target a build *known* to work. |
| **Tripwire on rollback** | **Bypassed for local backups only.** Never for anything re-ingested from outside. | That artifact was already signature-verified when it was installed. It is not new untrusted code. |
| **Auto-recovery** | **Two consecutive failed boots → revert to `last_known_good` → one more attempt → then STOP with a clear on-screen message.** Bounded, never looping. | An unbounded self-heal loop flaps the machine forever and hides the real fault (dead DAQ card, corrupt config). |
| **Failed boot definition** | Backend does not return **`/healthz` 200 within `boot_timeout_s`**. | A clean process exit is not a sufficient signal; a backend can exit cleanly for many reasons. |
| **`last_known_good`** | Earned on **boot + `/healthz` 200 + `good_after_minutes` uptime.** Not "completed a run." | A station that sits idle over a weekend must still be able to mark a good build. |
| **DB migrations** | **Both**: (a) additive-only within a MAJOR is a written rule; (b) a **pre-upgrade DB snapshot** is taken anyway and restored on rollback. | Every rollback design silently assumes only `run.dist` changes. It is not true: a rolled-back binary opens a database the newer build already migrated. The rule is pure; the snapshot is what saves you when someone breaks it. |
| **Licence model** | **Perpetual software licence + separate, time-limited AMC.** | The software must never stop working. |
| **AMC check** | Against the **signed `build_timestamp`** of the candidate build, **never the PC clock.** | Fair, stable, clock-tamper-proof, and it survives a disk replacement years later. |
| **AMC scope** | **Updates only.** Never a module, never a run, never an operator-visible warning. | The product's job is to keep the line running. |
| **AMC tier** | Present in the schema, **non-functional in phase 1.** | Reserved without committing to semantics. |
| **Framework sync** | Weekly workflow that **opens a PR and never auto-merges**, restricted to the **same MAJOR**. | Its real purpose is drift detection, not updating. |
| **Traceability** | No additional stamping. `RELEASE.json` already carries the pinned framework version. | Already covered. |
| **Patch granularity** | A release publishes either a full or an app-payload-only artifact (`sign_update.py`'s `KS_ARTIFACT_SCOPE`), never a manifest-side "choose one" flag. The station **detects** which kind it received from the hash-verified content (top-level `run.exe` present → full) and swaps only `run.dist/app` + `run.dist/instrument_libs` for the app-payload kind, never `run.exe`. | Narrow compile surface (ADR [0002](decisions/0002-nuitka-compile-scope.md)) means app-owned code (step types, drivers) is no longer compiled into `run.exe` by default — a bugfix to it doesn't need a full-tree swap. A signed `scope` field was considered and rejected: `manifest_signing_bytes()` mirrors a fixed external Rust struct, so an extra field would ride along **unsigned** — detecting scope from already-hash-verified content has no such gap. |

---

## 1. State machine

```
                    ┌──────────────┐
                    │   (none)     │
                    └──────┬───────┘
                POST /update/check
                           ▼
                    ┌──────────────┐
                    │  AVAILABLE   │  notification only; nothing on disk
                    └──────┬───────┘
             POST /update/download/{id}
                           ▼
                    ┌──────────────┐        network/HTTP error
                    │ DOWNLOADING  ├───────────────┐
                    └──────┬───────┘               ▼
                    verify (Keystation)     ┌────────────────┐
                           │                │ DOWNLOAD_FAILED│ retryable
              ┌────────────┴────────┐       └────────────────┘
      sig bad │                     │ sig ok
              ▼                     ▼
    ┌──────────────┐        ┌──────────────┐
    │ VERIFY_FAILED│        │  DOWNLOADED  │  verified, on disk, not staged
    │  TERMINAL    │        └──────┬───────┘
    └──────────────┘   POST /update/apply/{id}   ── 409 if a run is active
                                   ▼
                            ┌──────────────┐        ┌─────────────┐
                            │   STAGING    ├───────►│ STAGE_FAILED│ retryable
                            └──────┬───────┘        └─────────────┘
                                   ▼
                            ┌──────────────┐
                            │    STAGED    │  UI shows "Relaunch to update vX"
                            └──────┬───────┘
                    POST /update/relaunch/{id} → exit 42
                                   ▼
                          launcher: journal → swap → restart
                                   ▼
                     ┌─────────────────────────┐
             /healthz │                         │ no /healthz in boot_timeout_s
             200      ▼                         ▼
                ┌──────────────┐        ┌──────────────┐
                │  INSTALLED   │        │  BOOT_FAILED │
                └──────┬───────┘        └──────┬───────┘
        good_after_minutes                     │ 2 consecutive
                       ▼                       ▼
              ┌──────────────────┐    revert to last_known_good
              │ LAST_KNOWN_GOOD  │    one retry → then STOP
              └──────────────────┘
```

`VERIFIED`/`READY` from earlier drafts are deliberately absent: verification
happens *inside* download, and "ready" and "staged" are the same state.

**Terminal states:** `VERIFY_FAILED`. **Retryable:** `DOWNLOAD_FAILED`,
`STAGE_FAILED`. **Recoverable by the launcher:** `BOOT_FAILED`.

Every transition is persisted (DB `update_offer`) so a restart mid-flow resumes
correctly rather than starting over.

---

## 2. Endpoints

```
POST /update/check
     → { checked_at, current: {version, framework_version},
         available: { release_id, version, published_at, notes,
                      asset_name, asset_bytes, amc_ok } | null }
     Contacts GitHub. Downloads nothing. Idempotent.

POST /update/download/{release_id}
     → 200 { state: "downloaded", sha256 }
     Fetches the asset, then runs the EXISTING ingest (verify + offer).
     Idempotent on (release_id, sha256): a known hash returns the existing
     offer and does NOT advance the tripwire.
     → 402 if the AMC does not cover this build's build_timestamp.

POST /update/apply/{release_id}
     → 200 { state: "staged" }
     → 409 if a run is active, or if the offer is not applicable.

POST /update/install-file   { ksupdate_path, zip_path }
     → 200 { source: "file", state: "downloaded", staged_dir, scope, ... }
     AIR-GAPPED (§E-bis): stage an update from LOCAL .ksupdate + .zip (USB),
     no network. Runs the SAME verify (ingest → signature + tripwire) +
     full_artifact_hash check + stage pipeline as /update/download — only the
     SOURCE differs. Then Install + Relaunch the staged offer as usual.
     → 402 AMC, 404 missing file, 502 bad signature / hash mismatch.

POST /update/scan-incoming   {}
     → 200 { found: [ {source:"file", scope, version, ...} | {slot, error} ] }
     AIR-GAPPED convenience over /update/install-file: no paths to type — looks
     in two FIXED slots, <data_dir>/updates/incoming/{full,app-payload}/
     update.{ksupdate,zip}, and stages whichever are present (§3.2). A bad
     slot doesn't block the other — its entry carries an `error` instead. The
     delivery tool (deploy/build-update-package.ps1's Inno .exe) drops files
     at these fixed names; this is what "Scan for updates on this PC" calls.
     → 409 if station_mode is "online" (same source gate as install-file).

POST /update/relaunch/{release_id}
     → 200, then exit(42). Launcher swaps. (Existing.)

POST /update/rollback   { target: "last_known_good" | "<backup_id>" }
     → 200, then exit(42). Launcher swaps back and restores the DB snapshot.

GET  /update/offers     → { current, offers: [...] }        (existing)
GET  /update/status     → { app_version, framework_version, build_sha,
                            last_check, state, amc: {...},
                            backups: [ {id, version, installed_at,
                                        last_known_good: bool} ] }
```

All errors RFC-7807 per `DATA_TRANSFER.md`. All endpoints behind
`SYSTEM.SETTINGS`.

---

## 3. GitHub release contract

The station discovers updates by reading the app repo's Releases. That only
works if a Release is predictable. These are normative on the **app repo**:

| Element | Rule |
|---|---|
| Tag | `vX.Y.Z`. **This is the version. Nothing else is.** |
| Assets | **Exactly one** `.ksupdate`, named `<slug>-<version>.ksupdate`. Zero or two → the station **rejects the release** rather than guessing. |
| Body | Generated from that version's `CHANGELOG.md` section. This is what an engineer reads before clicking Download. |
| `prerelease` | `true` = beta channel, `false` = stable. |

**CI guard, first step of `release.yml`:**

```yaml
- name: Tag must match version
  run: |
    test "v$(python -c 'import core; print(core.__version__)')" = "${{ github.ref_name }}"
```

Cheap, and it stops the most common release mistake — tagging `v1.2.0` while
the code still reports `1.1.0`. The station compares tag to
`core.__version__`, so a mismatch makes updates silently stop working.

### 3.1 Private-repo asset download (known pitfall)

For a **private** repo, `browser_download_url` does **not** work with a token.
Use the asset API:

```
GET /repos/{owner}/{repo}/releases/latest          → assets[].id
GET /repos/{owner}/{repo}/releases/assets/{id}
    Accept: application/octet-stream
    Authorization: Bearer <read-only token>
```

Channel selection: `GET /releases/latest` already excludes prereleases (stable).
For beta, `GET /releases` and take the newest entry regardless of the flag.

Rate limits are a non-issue: 5,000 requests/hour authenticated against an
hourly poll. **No network must log and continue.** A bench that cannot reach
GitHub still boots and still runs tests.

### 3.2 App-payload-scope releases (patch-only)

`build_release.py`'s `package_app_payload_artifact()` produces a SECOND,
smaller zip — `<slug>-<version>-app-payload.zip` — alongside the full one
whenever there is app-owned payload to package (skipped for `--track
framework` or `--compile-app-payload`). A release whose diff is entirely
app-owned (a step-type bugfix, a new instrument driver, updated maps/specs)
signs **that** artifact instead of the full one —
`tools/ks_release_signer/sign_update.py`'s `KS_ARTIFACT_SCOPE=app-payload`
picks `RELEASE.json`'s `app_payload_artifact_hash` as the signed
`full_artifact_hash` field — and publishes the matching zip as the release's
one `.zip` asset, under the SAME standard name (§3's "exactly one
`.ksupdate`, exactly one `.zip`" rule is completely unchanged — a release
ships one scope, decided at signing time, never both).

In practice, cut a patch-only release with `deploy/cut-release.ps1 -Scope
app-payload` — the wrapper that sets `KS_ARTIFACT_SCOPE`, verifies
`RELEASE.json` actually has an `app_payload_artifact_hash` first (a build with
nothing app-owned to package fails loudly with a clear message instead of
silently falling back to full), and aliases the smaller zip onto the
standard `<slug>-<ver>.zip` path before publishing — every other step is
identical to a normal (`-Scope full`, the default) release: same version bump
on `app/<slug>/VERSION`, same tag, same GitHub Release.

**The signed manifest itself carries no `scope` field.** Station side:
`UpdateService._stage_zip_bytes` verifies the single `full_artifact_hash` as
always, then inspects the verified zip's own content — a top-level `run.exe`
means a full artifact, its absence means app-payload-only — and stages
accordingly (`staged/run.dist/` vs. `staged/app-payload/`).
`download()`/`install_from_file()` record that *detected* scope on the offer;
`request_relaunch`'s marker carries it through to the launcher. This
avoids adding an unsigned field to the trust boundary — see ADR
[0002](decisions/0002-nuitka-compile-scope.md) for why a manifest-side
`scope` flag was rejected (it would ride along unsigned and could redirect a
legitimately-signed manifest's hash check onto attacker-chosen content).

### 3.3 Incoming-folder delivery (no manual paths, no manual scope choice)

`install_from_file` needs two typed paths per update — fine occasionally, friction for a fleet.
`UpdateService.scan_incoming` (`POST /update/scan-incoming`) instead looks in two FIXED slots:

```
<data_dir>/updates/incoming/full/{update.ksupdate, update.zip}
<data_dir>/updates/incoming/app-payload/{update.ksupdate, update.zip}
```

and stages whichever pair(s) are present through the identical `install_from_file` pipeline (same
verify, same hash check, same content-based scope detection — this is a convenience over WHERE the
two paths come from, not a second trust path). `deploy/build-update-package.ps1` builds an Inno
tool that drops files at exactly these fixed names on an EXISTING install — see
`docs/DEPLOY_STATION.md`'s air-gapped section. A bad slot's error is returned alongside a good
slot's success (`{"slot": ..., "error": ...}` vs. a normal offer dict) so one bad file never blocks
the other.

---

## 4. The swap journal (highest-severity item in this document)

The launcher performs `live → .bak-<id>` then `staged → live`. **Power loss
between those two renames leaves no `run.dist` at all**, and no API can repair
it because nothing is running.

Required:

1. Before touching anything, write `data/swap-journal.json`:
   `{ step, from, to, backup_id, expected_hash, started_at }`.
2. Use **renames only, never copies.** Each rename is atomic on NTFS.
3. Update the journal after each step.
4. Delete the journal on success.
5. **On every launcher startup, read the journal first.** An incomplete swap is
   completed or reversed **before anything else runs.**

Without this, every other guarantee in this document is conditional on the
power staying on.

### 4.1 The swap needs a clean process tree first

`live → .bak` is a **rename**, so it fails (`WinError 32`) if any process still
holds a file inside `run.dist` open. On an **app-track** build the backend
(`run.exe`) spawns `run.exe --controller` as its **own** child; a relaunch/rollback
exits the backend with a hard `os._exit(42)` that skips the lifespan teardown, so
that controller child would be orphaned — still alive, still holding its own image
in `run.dist` open (blocking every swap), and still a second process driving
instrument I/O. Three layers stop that:

1. **The relaunch/rollback endpoints stop the controller first.** `_exit_relaunch`
   in `core/app.py` calls `ControllerSupervisor.stop()` — graceful `CTRL_BREAK`
   → every instrument to safe state → confirmed dead (hard `taskkill /T` on
   timeout) — *before* scheduling `os._exit(42)`.
2. **Each backend generation runs in a Windows Job Object** with
   `KILL_ON_JOB_CLOSE` (`launcher.py` `_WinJob`). After `proc.wait()` the
   supervisor terminates the job, so any descendant that outlived the backend is
   gone before the swap — unconditionally, without trusting shutdown ordering.
3. **The rename retries with backoff** (`_rename_with_retry`): a just-exited
   process can hold its image open for a brief, non-deterministic window.

If the swap still fails, the launcher writes `data/last_swap_error.json`; the
Updates page shows `swap_failed` with the error and strike count instead of
looping forever on `relaunch_requested`.

### 4.1a App-payload scope: the same journal, two smaller swap units

`SwapManager` (`launcher.py`) is already path-generic — nothing about it is
`run.dist`-specific. An `"app-payload"`-scope marker (§3.2) reuses it
unchanged, twice: one instance scoped to `run.dist/app` (own journal/backups
under `state/app-payload-swap/app/`), one scoped to `run.dist/instrument_libs`
(`state/app-payload-swap/instrument_libs/`) — each independently
journal-safe, reconciled at every launcher startup exactly like the full-tree
swap. Either unit can be absent from a given patch (staged_dir missing →
`apply_staged` no-ops cleanly), so a step-type-only patch doesn't touch
`instrument_libs` and vice versa.

No separate rollback path was built for this scope: the existing "two failed
boots → revert to `last_known_good`" auto-recovery (§6) already covers it,
because `mark_last_known_good()` snapshots the whole live `run.dist` —
including whatever app payload an app-payload-scope swap most recently put
there — so reverting the full tree correctly undoes a bad patch too.

### 4.2 Config-supplied paths must resolve OUTSIDE run.dist

A frozen station runs with `cwd = run.dist`. Any module that turns a **relative**
config value into a filesystem path (`recipe.root`, `report.outbox_path`,
`report.sinks[].path`, `mes.folder.upstream_dir`/`downstream_dir`) must resolve it
against the external deploy root, or that data lands inside `run.dist` and an
update swap renames it into the backup — silent data loss. `core.services.config`
provides:

- `state_root()` — `TMF_STATE_DIR` when frozen, `backend/` in source/tests.
- `resolve_state_path(rel)` — `rel` if absolute, else `state_root() / rel`. So the
  shipped `"data/recipes"` → `<deploy>/data/recipes`, the same tree that holds
  `tmf.sqlite`. Source/test layout is unchanged.
- `migrate_cwd_state(rel, resolved, diag)` — one-time rescue: if a pre-fix build
  wrote data at the CWD-relative location and the corrected path is still empty,
  copy it across (recipes + the report outbox do this; the folder mirror sinks and
  MES handoff dirs just resolve correctly going forward — lower severity, they
  regenerate).

The recipe store was the **critical** case: operator-authored recipes with no
other copy. The report **outbox** is second (reports queued for the pro DB but not
yet forwarded). The folder sinks and MES dirs are export/integration convenience.

### 4.3 The Updates page waits for the station to return

`relaunch()` / `rollback()` in `UpdatesConfig.tsx` no longer just print "will
reconnect shortly" and leave the page on the stale pre-relaunch state. After the
POST they poll `/healthz` (2 s interval, ~90 s budget — the `BOOT_TIMEOUT_S`
convention) and call `refresh()` once it answers, so the page resolves into the
real post-relaunch view; a timeout shows a "reload manually" error.

---

## 5. Backups and rollback

### 5.1 Backup identity

A bare `.bak-<timestamp>` name is not enough. Each backup directory carries a
sidecar:

```json
{ "backup_id": "bak-20260829-1042",
  "app_version": "1.1.0",
  "framework_version": "1.0.3",
  "build_sha": "a91f2c…",
  "installed_at": "2026-05-02T09:11:00Z",
  "last_known_good": true,
  "db_snapshot": "data/backups/bak-20260829-1042/app.db" }
```

### 5.2 Retention

- `keep_backups` default **2**, configurable.
- The `last_known_good` backup is **never evicted**, regardless of count.
- Rationale for 2 rather than 3: going back three versions means the last two
  were both bad — at that point someone is on a phone call, not clicking a UI.
  The protected `last_known_good` is a better guarantee than a deeper stack.

### 5.3 `last_known_good`

Earned when a build **boots, returns `/healthz` 200, and stays up for
`good_after_minutes`** (default 30). Not "completed a test run" — an idle
station over a weekend must still be able to mark a good build.

Rollback **always targets `last_known_good` by default**, not "the previous
one," because the previous one may also be broken.

### 5.4 Tripwire

Rollback to a local backup **bypasses the Keystation anti-rollback tripwire.**
That artifact was signature-verified when it was installed and has not left the
disk. The bypass applies **only** to local backups; anything re-ingested from
outside follows the normal path.

---

## 6. Auto-recovery

- **Failed boot** = backend does not return `/healthz` 200 within
  `boot_timeout_s` (default 120).
- **Two consecutive** failed boots → revert to `last_known_good` (binary **and**
  DB snapshot) → **one** further attempt.
- If that also fails, **stop and stay down** with a clear on-screen message
  identifying the last two attempted versions and the journal state.
- **Never loop.** If the real cause is a dead DAQ card or a corrupt config, an
  unbounded rollback loop flaps the machine and buries the actual fault. One
  bounded rollback attempt followed by honest failure is strictly better.

---

## 7. Database migrations (the assumption everything else was making)

A rolled-back **binary** opens a database the newer build **already migrated**.
Depending on the migration that is anything from a crash loop to silent
corruption of run records. Both mitigations are required:

**(a) Rule — additive-only within a MAJOR.** No drops, no renames, no type
changes. Enforced by review and, where practical, by a CI migration linter.

**(b) Safety net — pre-upgrade snapshot.** Before the first boot of a new
version, copy the DB into the backup directory. Rollback restores it. Cost is
one file copy.

The rule is the pure answer; the snapshot is what saves you when someone
breaks the rule silently. Ship both.

**Accepted trade-off:** restoring the snapshot discards test data recorded
between the upgrade and the rollback. This is recorded here so it is a known
consequence, not a discovery. Runs already exported or pushed to MES are
unaffected.

---

## 8. AMC (Annual Maintenance Contract)

### 8.1 Model

> The **software licence is perpetual.** The **AMC is a separate, time-limited
> right to receive updates.**

The software never stops working. If the AMC lapses, the customer simply cannot
install anything newer. Their line keeps running, forever, untouched.

### 8.2 The check — build timestamp, never the PC clock

```
May this station install this build?
    is the build's signed build_timestamp  <=  amc.expires ?
        yes → allowed
        no  → "This update was released after your AMC ended on 31 Mar 2026."
```

Keystation already verifies `valid_from ≤ build_timestamp ≤ valid_until`
(`SECURE_DISTRIBUTION.md` §6). This is **one lease field and one comparison.**

Why the build timestamp and not "today":

- **Fair.** An AMC ending March 2026 grants every build released up to March
  2026.
- **Stable.** That same build is still installable in 2029 — on a fresh PC,
  after a disk failure, mid-support-call. This is the behaviour customers
  expect and it never bites you during an incident.
- **Tamper-resistant.** Independent of the station clock.

**Semantics, explicit:** `amc.expires` is a **date**, inclusive, interpreted at
`23:59:59` **UTC** on that date. Comparison is `build_timestamp <= expires`.
No timezone ambiguity, no off-by-one.

### 8.3 Lease schema addition

```json
"amc": {
  "starts":  "2025-04-01",
  "expires": "2026-03-31",
  "tier":    "standard"
}
```

`tier` is **reserved and non-functional in phase 1.** Absent `amc` = no AMC =
updates unavailable, software fully operational.

### 8.4 Keystation issuer requirements

- Set and renew AMC per customer.
- **Renewal = mint a new lease with a later `expires`**, delivered to the
  customer. Installed exactly like the original activation, so this already
  works air-gapped via email + USB. No new station code.
- A report of AMC expiries in the next 90 days. This is a sales instrument as
  much as a technical one.

### 8.5 Station behaviour

- Settings → License: *"AMC valid until 31 Mar 2026"*, or *"AMC expired on
  31 Mar 2026 — software continues to run normally."*
- Update available + AMC valid → offer it.
- Update available + AMC expired → **show it**, mark *"requires an active
  AMC"*, block download (402). That message is a renewal prompt sitting on the
  customer's own screen.

### 8.6 The rule that must never be broken

**An expired AMC never stops a test, never disables a module, never blocks a
run, and never shows a warning to an operator on the shop floor.** It affects
the Updates page only, which only an engineer ever opens.

---

## 9. Configuration (`app.json`)

```json
"updates": {
  "github_repo": "exeliq/app-acme-eol",
  "github_token": "<read-only>",
  "channel": "stable",
  "station_mode": "online",
  "allow_unverified": false,
  "auto_check_minutes": 60,
  "auto_download": false,
  "auto_apply": false,

  "keep_backups": 2,
  "boot_timeout_s": 120,
  "good_after_minutes": 30,
  "db_snapshot_on_upgrade": true
}
```

`auto_check_minutes: 0` → discovery disabled entirely (air-gapped sites).
`auto_download` and `auto_apply` exist but **must remain `false`**; they are
present so the decision is visible in config rather than buried in code.

### `station_mode` — one update SOURCE per station

`docs/DEPLOY_STATION.md` describes two supported update paths — online
(`Config → Updates → Check/Download`) and USB (`/update/install-file`) — but the
running station accepts **both** unless told otherwise. `station_mode` enforces the
split so a deployment can only do what its site actually allows:

| value | `/update/check`, `/update/download` | `/update/install-file` |
|---|---|---|
| `"online"` (default) | reachable | **409** |
| `"air_gapped"` | **409** (`StationModeBlocked`) | reachable |

Default `"online"` → every existing deployment keeps today's fully-permissive
behavior; **zero migration**. It is a **source** restriction, orthogonal to
`allow_unverified` (a **trust** restriction). The Updates page reads it from
`GET /update/offers` and hides the disallowed half with an explanation. Set it
explicitly in each deployment's `app.release.json` rather than relying on the
permissive default in production.

---

## 10. CI/CD

### 10.1 Framework repo — `ci.yml` only

Tests. **No build, no signing, no secrets, no Release.** A framework release is
a `git tag` (`RELEASE_HOWTO.md`). Unchanged.

### 10.2 App repo — `ci.yml`

Fast, every push and PR: `pytest` + lint + `npm run build`.

Python needs no build to be tested — it runs from source, so `pytest` on source
is a real test. The frontend is different: TypeScript must be compiled before a
browser can use it, so `npm run build` is a **compile check** that catches
broken TypeScript in the PR rather than at release time.

Nuitka is deliberately **excluded** from `ci.yml`: it takes many minutes and
proves nothing `pytest` did not already prove.

> `ci.yml` = *is the code correct?* — fast, frequent.
> `release.yml` = *make the shippable thing* — slow, rare.

### 10.3 App repo — `release.yml` (on tag `app-v*`) OR `deploy/cut-release.ps1` (local)

`version guard (tag == VERSION **and** strictly newer than the latest published
`app-v*`) → tests → vendor Mosquitto → Nuitka → zip + hash → sign .ksupdate →
WebView2 + setup.exe → publish Release with the changelog body`. Signing secrets
(`KS_INTERMEDIATE_*`) live only in app-repo Actions secrets or the releasing
developer's environment — never committed, never in the framework repo.

**Two ways to run those steps, same Release + four assets:**

- **GitHub-hosted `release.yml`** — on the `app-v*` tag push. Simple, but every
  tagged build is **cold**: GitHub Actions cache is ref-scoped, a cache saved on
  one tag is unreachable from the next, and nothing runs the Nuitka build on the
  default branch to seed the fallback scope. Measured ~45 min ≈ 90 GitHub-Free
  minutes (Windows bills 2×) **per release**.
- **`deploy/cut-release.ps1`** (rendered from `deploy/cut-release.ps1.template` by
  `new-test-app`) — the identical steps on a developer's machine with a
  **persistent** local `NUITKA_CACHE_DIR` (warm after the first build), no CI
  minutes. A fork that adopts it retargets its own `release.yml` to
  `on: workflow_dispatch:` so the tag push doesn't fire both. Prereqs:
  `CONTRIBUTING.md`.

**Tag with the `app-v<version>` prefix and push ONLY that tag:**

```
git tag app-v1.2.0 && git push origin app-v1.2.0
```

A fork inherits every framework `v*` tag (v1.0.0 … the current framework
release), so the app's own v1.0.0/v1.1.0/… line collides with the framework
baseline and `git tag v1.0.0` fails. The `app-v` prefix keeps the two version
lines apart. It also makes `git push --tags` a footgun to avoid: that pushes all
the inherited framework tags, and if the workflow triggered on `v*` each one
would fire it. `release.yml` triggers on `app-v*` only, so push just the one tag.
The prefix is a **tag convention only** — release asset names stay plain
`<slug>-<ver>.zip` / `.ksupdate`, and the in-app updater reads the version from
the `.ksupdate` manifest (never the tag), so the prefix is invisible to a client.

`release.yml` still has a `Cache Nuitka build` step, but see the comment block at
the top of the template: on GitHub-hosted runs it effectively never hits, because
the cache is scoped per-ref and no run ever seeds a reusable scope. The local
`cut-release.ps1` is what actually gives you a warm cache.

### 10.4 App repo — `upstream-sync.yml` (weekly)

**Its purpose is drift detection, not updating.**

```
fetch upstream --tags
select newest framework tag within the SAME MAJOR as the pinned version
git merge <tag>
python tools/config_doctor.py --apply
pytest + vitest
open a PR titled "Framework vX.Y.Z"      ← NEVER auto-merge
```

Two outcomes, both useful:

- **Green PR** — the merge is clean and tests pass. A developer merges whenever
  they choose, or ignores it indefinitely. Nothing is forced onto anyone.
- **Conflict** — someone edited a framework-owned path, which `TEMPLATE.md` §1
  forbids. You learn this **this week** instead of in two years, when the fork
  has become unmergeable.

Because updates are deliberately rare in this business, drift accumulates
silently over long periods. That makes this workflow **more** valuable here,
not less.

**Compatibility needs no matrix.** Semver plus `contract_version` already
encodes it, in one rule:

> **Auto-sync proposes only framework versions within the same MAJOR. A MAJOR
> bump is a deliberate manual migration, never a robot's PR.**

Version skipping: if the app is on v1.2 and the framework is at v1.5, propose
**v1.5 directly** in one PR. `config_doctor` reconciles additively, so stepping
through v1.3 and v1.4 buys nothing.

---

## 11. Build order

| # | Work | Delivers |
|---|---|---|
| 1 | **Swap journal + startup reconciliation** in `launcher.py` | the un-brickable station |
| 2 | Backup metadata sidecars + `last_known_good` marking | rollback has a correct target |
| 3 | Auto-recovery: `/healthz` boot gate, 2 strikes, one revert, then stop | survives a bad build unattended |
| 4 | DB snapshot on upgrade + restore on rollback; additive-only rule documented | rollback is actually a rollback |
| 5 | `POST /update/check` — GitHub poll, notify only, AppBar chip | discovery |
| 6 | `POST /update/download/{id}` — private asset API → existing ingest; idempotent on hash; tripwire guard | download |
| 7 | Settings → Updates page: notes, Download, Install, Rollback | the two-click flow |
| 8 | 409 on apply during an active run | line safety |
| 9 | `POST /update/rollback` + local-backup tripwire bypass | manual recovery |
| 10 | AMC field, build-timestamp check, 402, Settings → License display | the commercial model |
| 11 | `release.yml` tag guard + asset naming + changelog body | predictable releases |
| 12 | `upstream-sync.yml` | drift detection |

**Items 1–4 come before any discovery work.** They are the ones whose failure
mode is *a production line is down at 2 a.m. and nobody on site can fix it.*
Items 5–8 are the visible feature; they are worth less than the four above.

---

## 12. Required contract for re-implementation

1. Never download or install without an explicit human action.
2. Never apply while a run is active.
3. Journal before every swap; reconcile the journal on every launcher start;
   renames only.
4. Key ingest idempotency on bundle hash; never advance the tripwire twice for
   the same bundle; `VERIFY_FAILED` is terminal.
5. Identify backups by metadata, not by timestamp; protect `last_known_good`
   from eviction.
6. Bound auto-recovery: two strikes, one revert, then stop with a clear message.
7. Snapshot the DB before the first boot of a new version; restore it on
   rollback.
8. Check the AMC against the signed `build_timestamp`, never the PC clock.
9. **Never let an expired AMC affect anything except the Updates page.**
