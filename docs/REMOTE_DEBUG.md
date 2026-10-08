# REMOTE_DEBUG.md — Remote Debugging & Logging Discipline

**Addendum to `DEBUG_SERVER.md`.** That document defines the station-local
Debug Server sidecar (DS1–DS6, built). This document extends it to the
**bench-PC ↔ developer-laptop** case and locks the **logging volume
discipline** that makes the captured data usable.

Read `DEBUG_SERVER.md`, `LOGGING.md`, and `PRINCIPLES.md` first. Nothing here
overrides them; everything here is additive.

**Design premise.** Developers using this tool are not Python experts. They
depend on Claude Code to diagnose faults. Therefore the primary deliverable of
this system is **not a human-readable log view** — it is a **machine-readable
artifact small enough and dense enough for Claude Code to reason over.**
Every decision below follows from that premise.

**Standing constraint.** The bench runs a frozen (PyInstaller) backend, no source in sight. There are no
breakpoints and there never will be. The recording must be complete enough
that stepping through code is unnecessary.

---

## 0. Locked decisions

| Decision | Choice | Rationale |
|---|---|---|
| **Transport** | Existing **REST + WebSocket** on the sidecar's port. **No custom TCP protocol.** | Framing, reconnect, backpressure, filtering, and versioning are already solved and shipped in DS1–DS6. A raw socket rebuilds all of it for zero new capability. |
| **First client** | **CLI (`tmf-debug`)**, not a GUI. Library → CLI → GUI (only if later proven necessary). | Claude Code can invoke a CLI and take its own captures. It cannot click a GUI. The sidecar already serves a browser UI at `/` for eyeball debugging, so the GUI need is met. |
| **Reachability** | Bind to an **explicit interface or subnet**. `0.0.0.0` is **not a legal value**. | Bench PCs commonly have a plant NIC and a corporate NIC. `0.0.0.0` binds both. Off-by-default does not help once enabled. |
| **Auth** | **Static `debug.token` checked by the sidecar itself**, with zero core dependency. Core-token (`/auth/me`) path retained as a convenience. | The sidecar exists to watch the core *while the core is broken* (`DEBUG_SERVER.md` §2). Auth that calls the core fails exactly when the tool is needed most. |
| **Debug control transport** | Debug control is **HTTP to the sidecar**. It does **NOT** ride the `cmd/` MQTT topic tree. | `cmd/` is the control plane that moves hardware. A debug op adjacent to `cmd/dut.power_on` creates a path from a dev tool to the control plane, and every future debug op inherits that adjacency. This boundary can only be drawn cheaply once. |
| **Snapshot buffer** | **30 s pre-trigger**, in memory, flushed to disk on failure. **Variable values only — raw `stream/#` data is NOT buffered or flushed.** | Gives full detail exactly when it matters at negligible steady-state cost. Excluding raw streams keeps flush size bounded and preserves the `stream/#`-is-never-captured rule of `DEBUG_SERVER.md` §0. |
| **Analog logging** | **Deadband change-logging + batched periodic summary + threshold crossings.** Never per-sample. | 1 kHz per-sample logging is 3.6 M records/hour: useless, and destructive to the disk and the signal-to-noise ratio. |
| **Digital logging** | **Edges only**, plus a 60 s heartbeat, plus chatter collapse. | A signal high for two hours is one record, not two hours of records. |
| **Deadband config** | **One global default** (% of expected range). Per-variable override field **exists from day one but stays unset.** | Nobody should tune 40 variables before the tool has ever run. Reserving the field now avoids a retrofit later. |
| **Retention** | **Size-capped, not day-capped.** `retention_days` exists but defaults to `null`. The server **measures its own output**. | Real volume is unknown. A size cap cannot fill a disk regardless of station busyness; days can be set later from measured fact. |
| **Logging cost** | **The logging call never touches disk.** Bounded in-memory queue, background writer, **drop-and-count, never block**, early return before formatting. | Delaying a test step is unacceptable. Losing log lines is acceptable and must be reported honestly. |
| **Replay** | **Deferred to v2.** Out of scope here. | Confirmed with `DEBUG_SERVER.md` §5.7. |
| **LabVIEW** | **Out of scope of this document.** | Explicitly dropped from this phase. |

---

## 1. The flow this system implements

```
1.  Bench PC runs normally. The sidecar records to a rolling file on disk,
    continuously, whether or not anyone is connected.

2.  A failure occurs, unattended. The snapshot buffer flushes 30 s of
    pre-trigger detail alongside it.

3.  Developer, from their own laptop:
        tmf-debug pull --host bench1 --last-run

4.  tmf-debug digest .debug/bench1-run-8842.jsonl

5.  Developer to Claude Code:
        "Read .debug/bench1-run-8842.digest.json — why did run 8842 fail
         at step 4?"

6.  Claude Code reads the digest, identifies the first fault, points at the
    source, proposes a fix.

7.  If the digest is insufficient:
        tmf-debug level --host bench1 --module daq --set debug
    Operator re-runs the test. No rebuild, no redeploy.
```

Step 7 is the replacement for "add a print statement and ship a new build."

---

## 2. Architecture

```
BENCH PC                                     DEVELOPER LAPTOP
┌──────────────────────────────┐
│ backend (frozen, PyInstaller)   │
│ mosquitto (loopback)         │
│                              │
│ DEBUG SERVER sidecar :8001   │
│  ├ ring buffer (existing)    │             ┌──────────────────────┐
│  ├ snapshot buffer 30 s NEW  │◄── HTTP ────┤  tmf-debug (CLI)     │
│  ├ rolling JSONL sink   NEW  │    + WS     │   pull / watch /      │
│  ├ volume self-measure  NEW  │             │   digest / level /    │
│  └ level control        NEW  │             │   capture / why       │
│                              │             └──────────┬───────────┘
│  bind: explicit iface   NEW  │                        │ writes
│  auth: static token     NEW  │                        ▼
└──────────────────────────────┘                    .debug/*.jsonl
                                                    .debug/*.digest.json
                                                             │
                                                             ▼
                                                       CLAUDE CODE
```

The sidecar's only inputs remain bus messages (`DEBUG_SERVER.md` §3). It never
reaches into a module's memory and never connects to LabVIEW directly.

---

## 3. Server-side additions

### 3.1 Bind address

```json
"debug": { "bind_host": "192.168.10.21", "port": 8001 }
```

- Default `127.0.0.1`.
- `0.0.0.0` **MUST be rejected at startup** with a clear diagnostic. Bind to a
  named interface address or refuse to start remotely.
- Remote reachability is **off by default**: absent config = loopback.

### 3.2 Authentication

```json
"debug": { "token": "<opaque random string>" }
```

- Every REST and WS request carries `Authorization: Bearer <token>`.
- The sidecar validates this **itself**, in-process, with **no call to the
  core**. This is the path that works when the core is down.
- The existing core `/auth/me` validation is retained as an alternative
  credential, never as the only one.
- If `debug.token` is unset and `bind_host` is not loopback, **refuse to
  start.** No unauthenticated remote surface, ever.

### 3.3 Rolling JSONL sink (the biggest current gap)

Today the ring is in-memory only: if no client was connected when the fault
occurred, the evidence is gone. That is unacceptable for unattended benches.

- Append-only JSONL on the station, one record per line.
- Rotate at `max_file_mb`; gzip rotated files.
- Evict oldest when total exceeds `max_total_mb`.
- **Size cap is authoritative.** `retention_days`, when set, is an additional
  (not alternative) constraint.
- Compression runs on the background writer thread at low priority and
  **never during an active run**.

### 3.4 Snapshot buffer (30 s pre-trigger)

- Holds the last **30 seconds** of **variable values** in memory. Raw
  `stream/#` frames are **excluded** — never buffered, never flushed.
- On trigger, flush the buffer plus a **5 s post-trigger tail** to a separate
  `snapshot-<ts>.jsonl` beside the rolling file.
- **Triggers (exhaustive):**
  1. step failure
  2. any `error`-level diagnostic event
  3. safety trip
  4. stuck command (request with no reply past timeout)

  **Warnings do NOT trigger a flush.** They are too frequent.
- **Flush encoding is compact arrays, never per-sample records:**
  ```
  FORBIDDEN: {"ts":1748513761.001,"var":"vbus","v":12.01}   × N
  REQUIRED:  {"var":"vbus","t0":1748513761.0,"dt":0.02,
              "v":[12.01,12.02,12.00, ...]}
  ```
  Roughly 15× smaller for identical information, and Claude Code parses it
  without difficulty.
- **Cap: `max_snapshots_per_hour` (default 6).** A station failing every unit
  must not write half a gigabyte before anyone notices. Suppressed flushes are
  counted and the count appears in `/debug/health` and in the file.

### 3.5 Live level control

- `POST /debug/level {subsystem, level}` — HTTP to the sidecar, which relays to
  the core. **Not** an MQTT `cmd/` publish (§0).
- Per-subsystem, effective immediately, not persisted across restart by
  default.
- The call site **returns before formatting** when the level filters the event
  out (`DEBUG_SERVER.md` §7.1 already requires this for LabVIEW; Python is
  identical).

---

## 4. Logging discipline — three kinds of data, three rules

Log too little and Claude Code cannot find the fault. Log everything and the
signal drowns and the disk fills. The three data kinds are handled
differently and the distinction is **normative**.

### 4.1 Events — log all, in full

Run started/finished, step started/finished, command sent, reply received,
error, safety trip, operator action, limit evaluated. A few hundred per run.
Cost is negligible; diagnostic value is the highest of the three.

**An event record MUST be self-contained.** If a step fails, that single record
carries step id, measured value, limit, unit, instrument/instance id, and
`run_id` — **as fields, not prose.** Claude Code must never need the preceding
line to interpret the current one.

Naming hygiene is inherited unchanged from `LOGGING.md` §6: `subsystem`
lowercase and dotless; `message` short and **stable across versions**; all IDs
in `context`, never interpolated into the message string. Stable wording is
what makes the corpus machine-matchable.

### 4.2 Analog variables — never per-sample

Four mechanisms, all required:

1. **Deadband change-logging.** Record a value only when it moves more than the
   deadband. A rail sitting at 12.0 V writes nothing; the drop to 9.5 V is one
   record.
   - `debug.analog.default_deadband_pct` (default `1.0`), as a percentage of
     the variable's expected range (`VARIABLE_ENGINE.md`).
   - Per-variable `deadband` field **exists in the variable definition from day
     one and is left unset** in phase 1.
2. **Batched periodic summary — one record per interval containing ALL
   variables.** This is normative, not stylistic:
   ```
   FORBIDDEN: 10 variables × 1 record/s        = 864,000 records/day
   REQUIRED:  1 record/s carrying 10 variables =  86,400 records/day
   ```
   Each variable contributes `{min, max, avg, n}`. This proves the signal was
   alive and gives Claude Code the shape without the bulk.
   - Interval: **1 s during an active run, 2 s when idle.**
3. **Threshold crossings.** One record on exceeding a limit, one on returning
   within it.
4. **Snapshot-buffer detail** around failures (§3.4).

### 4.3 Digital variables — edges only

1. **Every transition**, both directions, with a precise timestamp.
2. **60 s heartbeat** carrying the current state of all digital points. Proves
   the logger is alive and gives any capture a known starting state.
3. **Chatter collapse.** If a point toggles more than
   `debug.digital.chatter_threshold` (default 20) within
   `chatter_window_ms` (default 1000), emit **one** record —
   `{"toggles": 400, "window_ms": 1000}` — instead of 400. The collapsed record
   *is* the diagnosis; the 400 individual records are noise.

### 4.4 Two global suppressors

- **Repeat collapse.** The identical message N times becomes one record with a
  count. This alone prevents most log explosions.
- **Per-message-type rate limit.** On exceeding the cap, log the cap and the
  suppressed count. One broken module must never drown every other module.

---

## 5. Performance contract (normative)

There are exactly three ways logging damages a test system. All three are
forbidden by construction:

1. **Disk I/O on the calling thread.** A disk stall or an AV scan would delay a
   test step by hundreds of milliseconds and corrupt step timing.
   → **The logging call enqueues to a bounded in-memory queue and returns. A
   separate background thread drains it. The call site never touches disk.**
2. **Blocking when the queue is full.** Reintroduces (1) indirectly.
   → **The queue drops and counts. It never blocks.** Drop counts appear in
   `/debug/health` and in every capture. Losing log lines is acceptable;
   delaying a test is not.
3. **Formatting before filtering.** Building JSON for a record that is then
   discarded is pure waste at high rates.
   → **Check the level first, return before any formatting or allocation.**

Expected steady-state cost under these rules: one queue push per event plus one
background thread — well under 1% CPU at the stated rates, with **zero effect
on step timing.**

**Honesty rule:** a capture must never imply completeness it does not have.
Every artifact carries `dropped`, `suppressed`, and `snapshots_suppressed`.

---

## 6. Configuration (`app.json`)

```json
"debug": {
  "bind_host": "127.0.0.1",
  "port": 8001,
  "token": null,

  "rolling": {
    "enabled": true,
    "dir": "data/debug",
    "max_file_mb": 64,
    "max_total_mb": 2048,
    "compress_rotated": true,
    "retention_days": null
  },

  "snapshot": {
    "enabled": true,
    "pre_seconds": 30,
    "post_seconds": 5,
    "max_per_hour": 6,
    "include_streams": false
  },

  "analog": {
    "default_deadband_pct": 1.0,
    "summary_interval_run_s": 1,
    "summary_interval_idle_s": 2
  },

  "digital": {
    "heartbeat_s": 60,
    "chatter_threshold": 20,
    "chatter_window_ms": 1000
  },

  "limits": {
    "queue_size": 20000,
    "repeat_collapse": true,
    "per_type_rate_per_s": 200
  }
}
```

Absent `debug` block = loopback-only, rolling sink on, defaults as shown.

---

## 7. HTTP surface (additions to `DEBUG_SERVER.md` §8)

Existing endpoints are unchanged. Added:

```
GET  /debug/rolling                  ?since= &until= &run_id=
     → stream the rolling JSONL (gzip transfer), server-side filtered

GET  /debug/snapshots                → [ {id, ts, trigger, run_id, bytes} ]
GET  /debug/snapshot/{id}            → that snapshot's JSONL

POST /debug/level    {subsystem, level}          → 200 {applied}
GET  /debug/level                                 → current per-subsystem levels

GET  /debug/health   (extended)
     → { buffer_used, buffer_capacity, dropped, suppressed,
         snapshots_suppressed, broker_connected,
         bytes_written_today, bytes_per_run_avg,
         projected_mb_per_day, disk_free_mb,
         days_retained_at_current_rate,
         app_version, framework_version, station }
```

The extended `/debug/health` is how retention stops being a guess: after a week
on a real bench, `projected_mb_per_day` is a measured fact and
`retention_days` can be set from it. Expected order of magnitude under this
document's rules, with gzip on rotation: **20–80 MB/day** for a busy station.
A measured 500 MB/day means something is misconfigured, not undersized.

All errors use RFC-7807 per `DATA_TRANSFER.md`.

---

## 8. `tmf-debug` — the laptop client

Package layout:

```
tmf_debug/client.py    library: REST + WS client, typed records
tmf_debug/digest.py    the condenser
tmf_debug/cli.py       what a developer (or Claude Code) invokes
```

Commands:

| Command | Behaviour |
|---|---|
| `watch --host H [filters]` | Live WS tail to stdout |
| `pull --host H [--since 2h \| --last-run \| --run ID]` | Fetch to `.debug/<host>-<id>.jsonl` |
| `snapshots --host H` | List snapshots; `--get ID` downloads one |
| `capture start\|stop --host H --name N` | Drive a named capture remotely |
| `level --host H --module daq --set debug` | Live verbosity change |
| `digest <file.jsonl>` | Produce `<file>.digest.json` |
| `why --host H --last-run` | **pull + digest + print first fault**, one command |
| `health --host H` | Volume, drops, versions |

`why` is the command a non-expert developer runs. Everything else is available
when it is not enough.

**Convention:** all output lands in `.debug/` at the app-repo root, gitignored.
The app's `CLAUDE.md` states this, so Claude Code always knows where to look
without being told each time.

Filters mirror the existing REST/WS filters exactly: `--module`, `--level`,
`--topic`, `--trace`, `--since`, `--grep`.

---

## 9. The `digest` artifact (the Claude Code deliverable)

A raw capture is tens of megabytes and will not fit in a model's context. The
digest is the whole point of this system.

**Header — self-describing, so no explanation is needed alongside it:**

```json
{
  "station": "st1",
  "app_version": "1.2.0",
  "framework_version": "1.1.0",
  "host": "bench1",
  "time_range": ["2026-08-29T10:04:11Z", "2026-08-29T10:22:47Z"],
  "source_file": "bench1-run-8842.jsonl",
  "source_bytes": 21430188,
  "completeness": { "dropped": 0, "suppressed": 12, "snapshots_suppressed": 0 }
}
```

**Body — inclusion rules (normative):**

| Included in full | Rule |
|---|---|
| Every diagnostic at `level >= warning` | verbatim |
| Every **stuck command** (orphaned request) | verbatim, with `req_topic` and elapsed |
| Every **schema violation** | verbatim, with the validation error |
| **First fault** of each run | promoted to a top-level `first_fault` field |
| Full **trace waterfall** for any run containing an error | ordered |
| **Slow steps** — steps far above their own norm | with the norm and the observed |
| Liveness summary + LWT flips | one block |
| Snapshot index (ids, triggers) | list, not contents |

| Summarised, not included | Rule |
|---|---|
| `info`/`debug` events | counts by subsystem and message |
| Analog summaries | min/max/avg per variable over the window |
| Digital edges | transition counts per point, plus any chatter records |
| Everything else | counted |

**Target size: ≤ 100 KB.** If a digest exceeds this, tighten the window rather
than the rules — `--since`, `--run`, or `--module`.

**`first_fault` is the highest-value field in the file.** Later errors are
usually consequences; the first one is usually the cause.

The raw `.jsonl` is always kept beside the digest for when deeper inspection
is needed.

---

## 10. What makes this work for non-expert developers

One design consequence dominates all the tooling above:

> **The framework must produce good diagnostics on its own, without any
> app-developer effort.**

Every framework module — core, bridge, sequencer, instruments, recipe engine,
health, runs — emits complete, self-contained, stably-named events out of the
box. An app developer who writes a thin app-specific module on top and adds
**no logging whatsoever** still gets a fully debuggable system.

If this is not true, the entire scheme degrades into depending on inexperienced
developers to write good log statements, which will not happen. This is a
**framework obligation, not an application one.**

Where app-specific logging is genuinely needed, there must be **one obvious,
hard-to-misuse call** — so that Claude Code can write it correctly for them.

---

## 11. Build order

| # | Work | Gate |
|---|---|---|
| 1 | `bind_host` + static `debug.token`; refuse `0.0.0.0`; refuse remote without token | reachable and authenticated |
| 2 | `tmf_debug` library + `pull` + `watch` | the loop exists |
| 3 | `digest` | **the Claude Code artifact** |
| 4 | Rolling JSONL sink + volume self-measurement in `/debug/health` | evidence survives unattended faults |
| 5 | Analog deadband + batched summary; digital edges + chatter collapse; repeat collapse + rate limits | disk stays bounded |
| 6 | Snapshot buffer (30 s, values only, compact arrays, 4 triggers, hourly cap) | full detail at the moment of failure |
| 7 | `POST /debug/level` (HTTP, not `cmd/`) | replaces print-and-redeploy |
| 8 | `why` | usable by a non-expert |

Items 1–3 deliver a working remote-debug loop in roughly one week.

---

## 12. Out of scope (explicit)

- **Replay** — deferred to v2 (`DEBUG_SERVER.md` §5.7).
- **LabVIEW diag-emit** — separate track, dropped from this phase.
- **Raw `stream/#` capture** — never captured, never buffered, never flushed.
- **Fleet-wide / multi-station debug** — one bench, one client.
- **Fine-grained permission model** — a single bearer token in phase 1;
  granular permissions deferred, but the read/control split is already enforced
  structurally by keeping control off the `cmd/` tree.

---

## 13. Required contract for re-implementation

Any re-host MUST:

1. Refuse to bind remotely without an explicit interface address **and** a
   sidecar-validated static token.
2. Validate that token **without calling the core.**
3. Keep debug control off the `cmd/` MQTT topic tree.
4. Never perform disk I/O on the calling thread; drop and count rather than
   block; return before formatting when filtered.
5. Never log analog per-sample; never log digital steady state.
6. Batch the periodic analog summary into one record per interval for all
   variables.
7. Buffer 30 s of variable values, flush on the four defined triggers only,
   encode as compact arrays, cap flushes per hour.
8. Report `dropped`, `suppressed`, and `snapshots_suppressed` in every artifact.
9. Emit a digest that is self-describing, ≤ ~100 KB, and carries `first_fault`.

---

## 14. Installed builds and the offline export (v1.30.0)

The recorder was **source-only** (`station.py` returned early when frozen), so `debug.enabled = true` on a client
PC did nothing - no `data/debug`, nothing on :8001 - on exactly the machines this feature exists for.

- **`run.exe --debug-server`** is a third dual-entry mode of the frozen backend, beside `--controller`
  (`backend/run.py`; `debug_server` is bundled with `--collect-submodules`). It reads the live `app.json` and writes
  `data/debug/` under the **state root** (`TMF_STATE_DIR`, the external deploy root), never inside the swappable `run.dist`.
- **Supervision** (`station.py`): `run_station.exe` / `python station.py` start it when `debug.enabled` is on,
  **restart it if it dies, and stop/start it when the Settings switch changes** (polled every 5 s) - source and installed alike.
- **Offline export** for a PC with no network path to a laptop - one zip to carry out on a USB stick:

  ```
  run.exe --debug-export [out.zip] [--state-dir <deploy root>] [--rows 5000]     # installed bench, no Python needed
  tmf-debug export [out.zip] [--state-dir <root>]                                # from a source checkout
  ```

  Contents: `diagnostics/` (rolling capture + failure snapshots), `logs/error_log.jsonl`, `logs/action_log.jsonl`,
  `logs/launcher.log`, `config/app.json` and `config/controller.generated.json` (**secrets redacted**),
  `environment.json` (versions, OS, frozen/source, paths, free disk, `TMF_*`), and a `MANIFEST.json` that lists what
  was packed **and what was missing** (a bench where recording was never enabled says so instead of shipping an empty
  zip). Read-only on the station: the DB is opened `mode=ro`.
- The error/action logs it packs are no longer empty: see `contracts/LOGS.md` section 12 (central request audit,
  instrument failures, run aborts).
