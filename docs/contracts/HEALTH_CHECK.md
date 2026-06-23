# HEALTH_CHECK.md — System Health & Diagnostic Module

> Status: **Design** (contract-first, not yet implemented).
> Reads: `PRINCIPLES.md` (constitution), `CORE.md` (platform + module framework),
> `LABVIEW_BRIDGE.md` (the seam — see §13 for assumptions made in its absence),
> `DATA_TRANSFER.md` (wire shapes), `LOGGING.md` (the Diagnostics Bus this module
> sits beside, not inside).
>
> This document is the contract. Build against the doc, not against memory
> (`PRINCIPLES.md` §6).

---

## 0. What this module is — and what it is deliberately NOT

The Health Check module answers one question on demand: **"is this station
healthy, across web, LabVIEW, and hardware — and if not, what is known about
why?"** It does this by running a registry of **checks** through a **health
sequencer**, recording every run as an append-only record, and matching any
failure against a hand-authored **known-issues catalog** to surface a documented
cause and a *referenced* (never executed) remedy.

It is three things:

1. A **check registry** — pluggable checks spanning three domains
   (`web` / `bridge` / `hardware`), selected by config into named **suites**.
2. A **health sequencer** — runs a list of check ids, collects verdicts,
   produces a health-run record. Structurally a sibling of the test sequencer,
   but it runs *checks*, not *test steps*, and it has no UUT.
3. A **knowledge surface** — a known-issues catalog keyed by structured
   failure **signatures**, plus an operator-facing free-text **search** over
   that catalog. It proposes remedies; it never runs them.

### 0.1 What it is NOT (hard scope boundaries)

These are not pedantry — each one, if violated, collapses this module into a
god-module that depends on everything, breaking `CORE.md` §6.1.

- **It is NOT the Diagnostics Bus.** The bus (`LOGGING.md`) is the always-on
  event spine every subsystem emits into. This module *emits to* the bus like
  everyone else and *reads from* it for context, but it does not own it, wrap
  it, or replace it. The **Diagnostics Viewer** (§10) is a frontend over the
  bus, not part of this module's backend contract.
- **It is NOT the hardware driver path.** Per `PRINCIPLES.md` §0 (Control),
  **LabVIEW owns all hardware I/O.** A hardware check is a *bridge request*;
  its executor lives in LabVIEW. This module never imports a driver, never
  touches a capability service for a hardware check, never holds an instance
  lock. (See §4.2.)
- **It is NOT a remedy executor.** The module's hands are empty (§7.3). It
  *references* remedies that live in other, independently permission-gated
  contracts. A fuzzy match can never trigger a privileged action.
- **It is NOT the maintenance-mode authority.** Maintenance mode is a
  **station state owned by LabVIEW** (the controller). This module *reads* it
  and *gates on* it; the **Maintenance Console** (§9) *requests* entry/exit but
  LabVIEW decides. (See §8.)
- **It is NOT a self-healing / auto-resolution engine.** v1 proposes; the
  operator disposes. No auto-apply. The probabilistic future ("this looks like
  that") is reserved for the `Knowledge` module slot (`PRINCIPLES.md` §5).

### 0.2 The three surfaces, and why only one is a module

| Surface | Kind | Backed by | New backend module? |
|---|---|---|---|
| **Health Check** | backend module | check registry + sequencer + records + catalog | **Yes** — this doc |
| **Maintenance Console** | frontend | Variable Engine, HAL instances/capabilities, this module's "run one check", LabVIEW maintenance-mode | **No** (§9) |
| **Diagnostics Viewer** | frontend | Diagnostics Bus, `/modules/status`, `/readyz` | **No** (§10) |

Holding this line is the whole game. The console *writes to hardware* and the
viewer *reads live events*, but both are compositions of **existing contracts**.
If either needs a behavior that doesn't exist, that is a gap in an existing
contract, fixed there — never a new "maintenance module" or "viewer module."

---

## 1. Where it sits in the architecture

```
            ┌──────────────── Frontend (React/Tauri, unchanged) ───────────────┐
            │  Health page   ·   Maintenance Console   ·   Diagnostics Viewer   │
            └───────┬───────────────────┬───────────────────────┬──────────────┘
                    │ REST + WS         │ REST + WS             │ WS + REST
        ┌───────────▼──────────┐  ┌─────▼──────────────┐  ┌─────▼───────────────┐
        │  Health Check module │  │ Variable Engine /  │  │ Diagnostics Bus     │
        │  (THIS DOC)          │  │ HAL capabilities   │  │ (LOGGING.md)        │
        │   • check registry   │  │ (existing)         │  │ (existing/planned)  │
        │   • health sequencer │  └─────┬──────────────┘  └─────────────────────┘
        │   • run records      │        │ writes are LabVIEW-owned
        │   • known-issues     │        │
        └───────┬──────────────┘        │
                │ bridge.request        │ bridge (Variable Engine writes ride
                │ "health.check.<id>"   │ the same seam)
                ▼                        ▼
        ┌──────────────────── MQTT (local broker, per station) ────────────────┐
        └───────┬──────────────────────────────────────────────────────────────┘
                ▼
        ┌──────────────────── LabVIEW (controller) ────────────────────────────┐
        │  DQMH Health handler (executes hardware checks)                       │
        │  Maintenance-mode state machine (OWNS the state; retained topic)      │
        │  HAL · drivers · safety controller                                    │
        └───────────────────────────────────────────────────────────────────────┘
```

The module is an ordinary Python module under the core (`CORE.md` §2): manifest,
one or more variants, registers via `@register_module`, depends only on core
services, contributes a router under `/health` and a WS stream.

---

## 2. The check — the unit of scalability

A **check** is to this module what a **step type** is to the recipe module and a
**driver** is to the HAL: the pluggable unit that lets new applications and new
hardware extend the system **without changing the framework**. This is the
answer to "how is it scalable to upcoming applications and varying hardware":
*a new product or instrument ships new checks as data + a small executor; the
registry, sequencer, records, and contract never change.*

### 2.1 A check splits across the seam

Because hardware checks execute in LabVIEW (§0.1), a check has two halves:

- **Descriptor (Python side, in this module)** — static metadata: id, domain,
  disruptive flag, timeout, the verdict schema it promises, and the
  natural-language description. This is what the registry holds and what the
  sequencer dispatches on.
- **Executor (where the work happens)** — for `web` checks, a Python callable
  in the module; for `bridge` and `hardware` checks, a handler **in LabVIEW**
  reached by `bridge.request("health.check.<id>", params)`.

The descriptor can exist before its executor does. That is a feature: a product
template can declare the full set of checks it *expects*, and each surfaces an
honest **reachability** state until its executor lands (§2.4).

### 2.2 Check descriptor shape

```
CheckDescriptor:
    id            string     # stable, unique, dotless-lowercase: "daq.self_test"
    domain        enum       # "web" | "bridge" | "hardware"
    title         string     # human-readable, for the UI
    description   string     # natural language: what this check verifies & why
    disruptive    bool       # true = perturbs hardware / state (see §3)
    timeout_ms    int        # hard cap; sequencer abandons + marks "timeout"
    severity      enum       # "critical" | "warning" | "info"
                             #   critical fail → station considered unhealthy
                             #   warning  fail → degraded, station still usable
                             #   info     fail → advisory only
    verdict_schema string    # ref to the JSON Schema the verdict.data must match
    executor      ref        # web: python callable id; bridge/hardware: implied
                             #   by convention "health.check.<id>" over the bridge
    tags          [string]   # free grouping: "daq", "connectivity", "calibration"
    requires      [string]   # check ids that must PASS first (see §5.3)
    # --- operator-facing metadata (UX §2.5) ---
    purpose       string     # plain-language: what this verifies, no jargon
    impact        string     # business consequence if it fails ("Tests cannot run")
    user_action   [string]   # ordered steps an operator can take to fix it
    group         string     # business function: "Core Software" | "Production Systems"
                             #   | "Test Equipment" | "External Systems"
```

`severity` is **not** the same as a verdict. Severity is a property of the
check (how much do we care if it fails); the verdict is the runtime result.

### 2.5 Operator-facing metadata and the three info levels

Every check carries human metadata so the UI can answer *"what failed, what does
it cost me, what do I do?"* without exposing internals. The Health page renders at
three levels (toggle, default **Operator**):

- **Operator** — `title`, status, and on failure `impact` + `user_action` steps +
  a matched **known-issue** remedy (§7). No ids, no SCPI.
- **Technician** — adds the verdict `summary` and `data` key/values (diagnostics).
- **Engineer** — adds `check_id`, `elapsed_ms`, the failure `signature`, raw `error`.

Checks are grouped by `group` (business function), **not** by technical domain. The
top of the page is a single readiness verdict derived from `overall`:
`healthy → ✓ Production Ready`, `degraded → ⚠ Ready with Warnings`,
`unhealthy → ✖ Production Blocked`. Instance-templated hardware checks inherit
`label`/`group` from the instance config (the operator sees "Digital Multimeter",
not `hardware.self_test:dmm0`).

### 2.3 Verdict shape (what every executor returns)

Every check — web, bridge, or hardware — returns the **same verdict envelope**.
This uniformity is what lets the sequencer, records, and UI be domain-agnostic.

```
CheckVerdict:
    check_id    string
    status      enum       # "pass" | "fail" | "timeout" | "skipped" |
                           #   "unavailable" | "error"
    started_ts  float      # epoch seconds
    elapsed_ms  float
    summary     string     # one-line natural language ("DAQ self-test passed")
    data        object     # check-specific, validated against verdict_schema
    error       object|null# RFC-7807 ProblemDetail when status in
                           #   {fail, timeout, error} and an error is structured
    signature   object|null# the matching key (§7.1); null when status == pass
```

Status meanings, precisely:

| status | meaning |
|---|---|
| `pass` | the check ran and the condition held |
| `fail` | the check ran and the condition did NOT hold (a real finding) |
| `timeout` | executor did not answer within `timeout_ms` |
| `skipped` | not run because a `requires` dependency failed, or operator deselected |
| `unavailable` | executor not reachable/implemented (bridge offline, no LabVIEW handler) — **distinct from fail** (§2.4) |
| `error` | the executor itself malfunctioned (bad params, internal exception) — distinct from a hardware fault, which is `fail` |

The `unavailable`/`fail`/`error` distinction is load-bearing. A diagnostic tool
that reports "DAQ FAILED" when the truth is "I couldn't reach LabVIEW" is lying
to the operator about *where* the problem is — the cardinal sin for this module.

### 2.4 Reachability — honest "I don't know"

A bridge/hardware check whose LabVIEW executor is missing, or whose bridge link
is offline (`status` retained = `offline`, `CORE.md` §5), returns
`status = "unavailable"`, never hangs and never reports `fail`. The sequencer
caps every check at `timeout_ms` regardless, so a wedged executor degrades to
`timeout`, not a frozen UI. Both are visually distinct from a genuine `fail`.

---

## 3. Disruptive checks and the maintenance gate

Some checks perturb hardware: a DAQ self-test, a relay toggle, a loopback that
drives an output and reads it back. Running one against a live UUT can damage a
board or corrupt a measurement. The rule:

> **A `disruptive: true` check MUST NOT run unless the station is in
> maintenance mode (§8) and no run is active.** The sequencer refuses with
> `status = "skipped"` and a clear reason; it does not silently run it anyway.

Non-disruptive checks (`disruptive: false` — read a status, ping the bridge,
query a setpoint read-back, check disk space) may run any time, including a
read-only health poll while a test is in progress.

**Safety is never a check.** The emergency-disable path (`HAL.md` §3.4,
`VARIABLE_ENGINE.md` §6) is owned by the safety controller and is exercised by
its own tests, not by this module. A health check may *verify the safety system
reports armed/ready*, but it may never *fire* emergency-disable as a "test." A
diagnostic must not be able to trip safety.

---

## 4. The three domains

### 4.1 `web` checks (execute in Python, in this module)

Pure-platform self-checks that need no hardware and no bridge:

- `web.db_writable` — round-trip a scratch record through the repository.
- `web.disk_space` — free space under the data/log roots over a threshold.
- `web.config_valid` — every active module's config validated clean at boot.
- `web.modules_loaded` — `/modules/status` shows no required module skipped.
- `web.clock_sane` — system clock within tolerance of bridge-reported time
  (clock skew across the seam corrupts every timestamp correlation).

These are the only checks whose executor is a Python callable inside the module.
They are always `domain = "web"`, almost always `disruptive = false`.

### 4.2 `bridge` checks (execute in LabVIEW, connectivity-focused)

Verify the seam itself, not the hardware behind it:

- `bridge.online` — retained `status` is `online`; LWT not fired (`CORE.md` §10).
- `bridge.roundtrip` — `bridge.request("health.check.bridge.roundtrip")`
  returns within budget (the `hello.echo` pattern, `CORE.md` §9).
- `bridge.clock_skew` — LabVIEW timestamp vs Python timestamp within tolerance.
- `bridge.queue_depth` — LabVIEW reports its internal bridge queue not backed up.

### 4.3 `hardware` checks (execute in LabVIEW, per instance)

The substantive ones. Each is parameterised by **instance id** (`HAL.md` §5) so
one check definition covers every instance of a family — *this is how it scales
to varying hardware*: a check is written once against a **capability**, not a
vendor.

- `hardware.instance_connected` — `{instance_id}` reports connected.
- `hardware.self_test` — driver `self_test()` (`HAL.md` §3.4) → `{pass, message}`.
  `disruptive` depends on the instrument; default `true`.
- `hardware.identify` — `*IDN?`/`identify()` returns expected vendor/model.
- `hardware.loopback` — drive a known output, read it back through a known
  input, assert within tolerance. `disruptive = true`. The single most valuable
  check for catching wiring/calibration drift; mirrors the golden-comparison
  idea (`BORROWABLE_MODULES.md` §7) but for the rack, not the UUT.
- `hardware.range_sane` — read a variable, assert within `expected_range`
  (`VARIABLE_ENGINE.md` §2.1). `disruptive = false`. Cheap, catches a floating
  input or a dead sensor.

The check executor in LabVIEW resolves the instance through the instance
registry and calls the capability service — i.e. the hardware path stays
entirely on the LabVIEW side of the seam, exactly as `PRINCIPLES.md` §0 requires.

### 4.4 Parameterised checks — one definition, many targets

A check descriptor may declare it is **instance-templated**: the registry
expands it per matching instance at load, the way the HAL expands endpoint
groups (`HAL.md` §4.6). `hardware.self_test` against a rack of four DC sources
becomes four concrete check ids (`hardware.self_test:dc_main_st1`, …) selected
by `by_family`/`by_capability` (`HAL.md` §5.3). New instance in `stations.toml`
→ new checks appear automatically. No catalog edit.

---

## 5. The health sequencer

### 5.1 What it is

A small engine that takes a **list of check ids**, runs them respecting
dependencies and the disruptive gate, collects verdicts, and emits a
**health-run record**. It deliberately reuses the *shape* of the test
sequencer's runner/step contract (`BORROWABLE_MODULES.md` §5) — abort,
per-item timeout, progress events — but it is a **separate, simpler engine**:
no UUT, no recipe, no pass/fail-the-product semantics.

> **Argued decision:** do not run health checks *through* the LabVIEW test
> sequencer. They share a shape, not a lifecycle. The test sequencer owns UUT
> run-state; overloading it with health runs muddies run-state authority
> (`PRINCIPLES.md` §0). The health sequencer is its own thing, in Python, that
> dispatches hardware checks over the bridge. The LabVIEW side only executes
> individual check handlers, never an entire health *run*.

### 5.2 Execution model

```
run_health(check_ids, *, mode) -> health_run_id
  mode: "concurrent" (default for read-only) | "serial" (for disruptive)

  1. resolve check_ids → descriptors (expand instance-templated)
  2. topologically order by `requires`; cycle → refuse the whole run, 400
  3. read maintenance state (retained) + run-active state
  4. for each check:
       if disruptive and not (maintenance and no-run): verdict = skipped(reason)
       elif a `requires` dep did not pass:               verdict = skipped(dep)
       else: dispatch
               web      → call the python executor (off-loop)
               bridge / hardware → bridge.request("health.check.<id>", params)
             cap every dispatch at descriptor.timeout_ms
       emit progress event over WS (§6); emit a diag event (LOGGING.md)
       match verdict.signature against known-issues (§7); attach suggestions
  5. assemble + persist the health-run record (§6); return id
```

Non-disruptive checks may run **concurrent** (bounded fan-out — they ride the
bridge's request/reply, so concurrency is limited by the bridge, not the
module). Disruptive checks run **serial** and only in maintenance mode, because
two disruptive operations on overlapping hardware must never interleave.

### 5.3 Dependencies (`requires`)

`hardware.self_test:daq_st1` requires `hardware.instance_connected:daq_st1`
requires `bridge.online`. If `bridge.online` fails, everything downstream is
`skipped` with the dependency named — so the operator sees *one* root cause, not
forty cascading failures. This is the same "show the root, suppress the cascade"
discipline as dedup/coalescing in the logs module.

### 5.4 Abort

A health run is abortable (operator presses stop). In-flight checks are allowed
to finish their current `timeout_ms` window (you cannot un-send a bridge
request); not-yet-started checks become `skipped: aborted`. The partial record
is still persisted — a half-finished health run is evidence, not garbage.

---

## 6. Persistence — health runs as RAG corpus

Per your locked decision: **health runs are records like run records,
append-only**, through the core repository (`CORE.md` §7), carrying the common
metadata envelope (`PRINCIPLES.md` §5).

### 6.1 Health-run record

```
record_type = "health_run"
data:
    health_run_id  string
    mode           enum         # concurrent | serial
    trigger        enum         # "manual" | "scheduled" | "on_event" | "boot"
    suite          string|null  # the named suite, if one was run
    operator       string|null  # principal, when manually triggered
    maintenance    bool         # was the station in maintenance during the run
    overall        enum         # "healthy" | "degraded" | "unhealthy" | "incomplete"
    counts         object       # {pass, fail, timeout, skipped, unavailable, error}
    verdicts       [CheckVerdict]
    suggestions    [Suggestion] # known-issue matches surfaced this run (§7)
    summary        string       # NL roll-up: "DAQ self-test failed on st1; ..."
```

`overall` derivation: any `critical` check with status in {fail, timeout,
error} → `unhealthy`; else any `warning` fail → `degraded`; any `unavailable`
on a `critical` check → `incomplete` (we don't *know* it's healthy); else
`healthy`.

### 6.2 Latest snapshot is a query, not a second store

You chose append-only history (not "both"). The "current health" the UI shows is
just *the most recent `health_run` record per trigger context* —
`repository.query("health_run", limit=1, ...)`. No separate snapshot store to
keep in sync. One source of truth.

### 6.3 Failure records are self-contained

Every `fail`/`timeout`/`error` verdict carries enough context to understand it
without reading neighbours (`LOGGING.md` §6): the instance, the resolved
address summary, the raw error, the expected-vs-actual. This is the discipline
that makes the corpus answer future questions like "every loopback failure on
ai1 across the fleet."

---

## 7. The known-issues catalog and signature matching

### 7.1 Signature — the deterministic key

A **signature** is the structured fingerprint of a failure, computed by the
module at failure time. It is **structured-only** and **deterministic** — same
failure in, same signature out, explainable in one line:

```
Signature:
    check_id        string     # "hardware.self_test"
    instance_family string|null# "daq" (not the specific instance — families
                               #   share failure modes; instance is in the record)
    error_category  string|null# from the RFC-7807 / driver error taxonomy
    error_code      string|null# vendor or driver code, when present
    status          enum       # fail | timeout | error
```

> **Argued decision (I overruled "add free-text symptom matching" here, on
> purpose):** the *automatic* match path is structured-only. Free-text fuzzy
> matching that *fires remedies* is non-deterministic, unexplainable, and would
> require embeddings this project defers (`PRINCIPLES.md` §5). Free text is not
> discarded — it lives in two safe places instead (§7.4, §7.5). Probabilistic
> "this looks like that" is reserved for the future `Knowledge` module.

### 7.2 Known-issue entry (hand-authored data)

```
KnownIssue:
    issue_id       string
    schema_version int
    match          Signature-pattern   # fields may be wildcards; most-specific wins
    title          string
    symptom        string     # NL: what the operator observes
    cause          string     # NL: the diagnosed root cause
    remedy         Remedy     # see §7.3 — referenced, never executed
    references     [string]   # links to manuals, ADRs, tickets
    confidence     enum       # "confirmed" | "probable" | "speculative"
    occurrences    int        # maintained by the corpus over time (advisory)
```

Catalog is JSON files under `data/known_issues/`, version-controlled and
schema-validated like every other config (`PRINCIPLES.md` §4). New product line
ships its own known-issues file. The catalog **grows** — which is the "growing
module to capture problem→cause→solution" you asked for, done as reviewable data
rather than mutable runtime state.

### 7.3 Remedy — the module's hands are empty (locked invariant)

```
Remedy:
    kind     enum            # "documentation" | "action_ref"
    text     string          # NL instructions, ALWAYS present
    action   ActionRef|null  # present only when kind == "action_ref"

ActionRef:
    contract    string       # which OTHER contract owns the operation
    operation   string       # the operation id within that contract
    params      object       # pre-filled params for the operator to confirm
    label       string       # button label: "Reconnect daq_st1"
```

> **Locked invariant:** the Health Check module **never executes a remedy.** A
> `documentation` remedy is text. An `action_ref` remedy renders a button that
> calls **a different contract's endpoint**, which does its **own** permission
> check and its **own** maintenance/disruptive gate at its own door. The module
> proposes; a properly-gated contract disposes. A wrong fuzzy match can never
> trigger a privileged action, because the module has no privileged actions.
>
> Corollary: a high-value remedy that doesn't exist yet (e.g. "power-cycle the
> PDU") is *blocked on adding it to the HAL/controller as a real, audited,
> permission-gated operation*. That friction is intentional — it forces
> recovery operations to be designed, not buried in a diagnostic tool.

### 7.4 Suggestion — the logged proposal (RAG corpus)

Per your locked decision, **every suggestion is itself a record** — including
the valuable negative case where a failure matched *nothing*:

```
record_type = "health_suggestion"
data:
    health_run_id  string
    signature      Signature
    matched        bool
    issue_id       string|null     # null when matched == false ("unknown signature")
    remedy_kind    enum|null
    operator_ack   enum|null       # later feedback: "helped" | "did_not_help" | null
    summary        string
```

"Unknown signature" records are gold: they are the backlog of known-issues
entries you haven't written yet, surfaced by real field failures.

### 7.5 Free text, placed safely

Free text is mandatory on records (`symptom`, `cause`, `remedy.text`,
`verdict.summary`) — that is the RAG-readiness rule, and it is what a future
Knowledge module embeds. And it powers an **operator-driven search** over the
catalog (`GET /health/known-issues?q=fan+won't+spin`) — a thin keyword/substring
search in v1, where a *human* judges relevance, so a fuzzy hit is a suggestion
to a person, never an automatic remedy. Free text travels with the data and
serves human search; it is never the automatic-match key.

---

## 8. Maintenance mode — a station state owned by LabVIEW

Per your locked decision, maintenance mode is a **first-class station state
owned by the controller (LabVIEW)**. This module and the console are clients.

### 8.1 Ownership and transport

LabVIEW owns the maintenance state machine and publishes it as a **retained**,
`status`-class topic (bridged up to the central broker as a low-rate topic, per
`PRINCIPLES.md` §0). Python and the frontend **read** it; it survives reconnect
because it is retained, the same pattern as the bridge `status`.

```
state/maintenance  (retained):
    { "state": "off" | "entering" | "on" | "exiting",
      "since": <epoch>, "by": <operator|null>, "reason": <string|null> }
```

### 8.2 Entry/exit are requests, LabVIEW decides

The console (or an admin) **requests** transitions over the bridge; LabVIEW is
the arbiter and **may refuse**:

```
maintenance.enter {operator, reason} -> {accepted, state} | {refused, reason}
maintenance.exit  {operator}         -> {accepted, state}

LabVIEW MUST refuse `enter` if a run is active.
LabVIEW MUST require the safety controller be armed before granting `on`.
On `enter`, LabVIEW SHOULD drive all safety=true variables to safe state first.
```

The disruptive gate (§3) and the console's manual writes (§9) both read
`state/maintenance` and both refuse unless `state == "on"`. One state, two
consumers, single authority.

---

## 9. Maintenance Console (frontend — NOT a backend module)

The comprehensive replacement for the classic LabVIEW "maintenance window."
Manual hands-on operation of every piece of hardware — but composed entirely
from **existing contracts**, introducing no new backend module.

### 9.1 What it composes

| Console capability | Backed by (existing contract) |
|---|---|
| List instruments, status, connect/disconnect | HAL instance registry (`HAL.md` §5), `DATA_TRANSFER.md` §5.3 |
| Read any signal (live) | Variable Engine read (`VARIABLE_ENGINE.md` §4), `/variables/{name}/value` |
| Write any output (clamped, safe) | Variable Engine write (`VARIABLE_ENGINE.md` §5) — clamping + `safety=true` already apply |
| Live-stream a channel | DAQ stream WS (`DATA_TRANSFER.md` §4.2/4.3) |
| Run one health check on demand | **this module** — `POST /health/checks/{id}/run` |
| Enter/exit maintenance mode | LabVIEW over bridge (§8) |

### 9.2 The one hard rule

> The console can command hardware (manual writes, disruptive checks) **only
> when `state/maintenance` is `on`.** Outside maintenance, the console is
> **read-only** — live values, status, non-disruptive checks. This is the same
> gate as §3; the console does not get a private exception.

This is more comprehensive than the legacy maintenance window in three ways:
it is **safe by construction** (every write is clamped and safety-reset-able via
the Variable Engine, not raw driver pokes), it is **signal-named not
channel-named** (operators toggle `fan_enable`, not `port0/line4`), and it
**folds in health checks** so "operate it by hand" and "check it" live in one
place. That is the comprehensive maintenance approach you asked for — achieved
by *composition*, not a new module.

### 9.3 Why it is NOT a backend module (and what to do if tempted)

It owns no persistent state and no new operations. If a console need appears
that no contract serves (say, "capture the current sim state as a fixture"),
that is a **gap in the HAL or Variable Engine contract**, added *there* behind
its own permission gate — never a "maintenance module" that reaches across
siblings (`CORE.md` §6.1).

---

## 10. Diagnostics Viewer (frontend — NOT a backend module)

The live "what is happening right now" surface. It is a thin React client over
things that **already exist**:

- **Diagnostics Bus** WS (`/diagnostics/stream`, `LOGGING.md` §2.7,
  `DATA_TRANSFER.md` §4.4) — live cross-language event tail, filter by
  subsystem/level.
- **`/diagnostics/events`** — history with filter/pagination (`LOGGING.md` §2.7).
- **`/modules/status`** — loaded-vs-skipped + reasons (`CORE.md` §4).
- **`/readyz`** — bridge-online + required-modules-started (`CORE.md` §5).

The viewer adds **no backend**. It is the `LOGGING.md` §4 sketch, realised. Its
only relationship to this module: a health-run failure links the operator from a
health record into the viewer, pre-filtered to that subsystem/time window, so
"the check failed" → "here is the live evidence around it" is one click.

> Why separate from the Health Check module: the bus is always-on and
> universal; the health module is on-demand and scoped. Folding the viewer into
> this module would make this module a dependency of *observing the whole
> system*, which inverts the dependency direction. The viewer reads the spine;
> it is not the spine.

---

## 11. Contract surface (REST + WS)

Follows `DATA_TRANSFER.md` verbatim: bearer auth, RFC-7807 errors, enums as
strings, lists always present, WS token via query string.

### 11.1 REST

```
# Checks & suites
GET  /health/checks                         → [CheckDescriptor]   (incl. reachability)
GET  /health/suites                         → [{name, check_ids, description}]
POST /health/checks/{id}/run                → 200 {health_run_id}  (one check)
POST /health/run            {suite|check_ids, mode}  → 200 {health_run_id}
POST /health/run/{id}/abort                 → 204

# Health runs (records)
GET  /health/runs?since=&limit=&trigger=    → [health_run summary]
GET  /health/runs/{id}                      → health_run record (full verdicts)
GET  /health/current?trigger=               → most recent health_run (the "snapshot")

# Known issues
GET  /health/known-issues?q=&check_id=      → [KnownIssue]   (q = operator free-text search)
GET  /health/known-issues/{issue_id}        → KnownIssue
GET  /health/suggestions?since=&matched=    → [health_suggestion record]
POST /health/suggestions/{id}/ack {outcome} → 204   (operator feedback: helped / did_not_help)

# Maintenance (proxied to LabVIEW authority — module does not decide)
GET  /health/maintenance                    → state/maintenance (read of retained)
POST /health/maintenance/enter {reason}     → 200 {accepted|refused, state}
POST /health/maintenance/exit               → 200 {accepted, state}
```

Permissions (tiered, mirroring the logs module): `health.view` (read checks,
runs, issues, current), `health.run` (run non-disruptive checks),
`health.maintenance` (enter/exit maintenance, run disruptive checks, ack
suggestions). Enforced at the API independent of the frontend
(`PRINCIPLES.md` §3).

### 11.2 WebSocket

```
WS /health/run/{id}/stream?token=…
   envelope events (DATA_TRANSFER.md §3.2):
     "health-run-started"   {health_run_id, total_checks}
     "check-started"        {check_id, title}
     "check-completed"      {check_id, status, elapsed_ms, summary}
     "suggestion"           {check_id, issue_id|null, matched, remedy_kind|null}
     "health-run-finished"  {health_run_id, overall, counts}
```

On reconnect: no replay; client re-queries `GET /health/runs/{id}` to fill the
gap (`DATA_TRANSFER.md` §3.7).

---

## 12. The seam — checks over the bridge (LabVIEW handlers)

For every `bridge`/`hardware` check, LabVIEW exposes a request/reply handler:

```
request  topic:  health.check.<id>      params: { instance_id?, ...check params }
reply    payload: CheckVerdict (§2.3)   — LabVIEW fills status/elapsed/data/error/signature
```

LabVIEW translation (consistent with the `LOGGING.md` §5 and `HAL.md` §6.6
hints): a DQMH "Health" module with one message per check family; the handler
resolves the instance through the instance registry, calls the capability
service, times the call, and packs the verdict as JSONtext. Reachability
(`unavailable`) is the natural default reply when no handler is registered for
an id. Maintenance-mode state is published by the controller's state machine,
not by this handler.

---

## 13. Bridge-contract assumptions (FLAGGED — reconcile against LABVIEW_BRIDGE.md)

`LABVIEW_BRIDGE.md` was not available when this doc was written. The following
shapes are **assumptions inferred** from `PRINCIPLES.md` §0, `CORE.md` §9–§10,
and `DATA_TRANSFER.md`. Reconcile each against the real bridge doc; none affects
the module's own contract (§11), only the seam (§8, §12):

1. **Request/reply topic shape.** Assumed `bridge.request("health.check.<id>",
   params)` mirrors `bridge.request("hello.echo", …)` (`CORE.md` §9). If the
   bridge uses a different request topic convention or correlation-id scheme,
   only the `<id>` → topic mapping in §12 changes.
2. **Retained state topic for maintenance.** Assumed a `status`-class retained
   topic `state/maintenance` (§8.1), bridged as low-rate. If the bridge folds
   station state into a single retained `status` document, maintenance becomes a
   field there instead of its own topic.
3. **Verdict as reply payload.** Assumed the bridge reply body can carry the
   full `CheckVerdict` JSON. If the bridge caps reply size or wraps replies in
   its own envelope, the verdict rides inside that envelope unchanged.
4. **Error envelope on the bridge.** Assumed bridge-level errors surface as
   RFC-7807-compatible objects so `verdict.error` is uniform across web and
   hardware checks. If the bridge has its own error shape, the module maps it to
   ProblemDetail at the seam.

---

## 14. Manifest (sketch)

```json
{
  "schema_version": 1,
  "module": {
    "id": "health",
    "version": "1.0.0",
    "contract_version": 1,
    "display_name": "System Health & Diagnostics",
    "description": "On-demand health checks across web, bridge, and hardware; append-only health-run records; hand-authored known-issues catalog with referenced (never executed) remedies."
  },
  "entitlement_key": "health",
  "variants": ["default"],
  "core_dependencies": ["db", "bridge", "config", "auth", "diagnostics", "web"],
  "contract_dependencies": [],
  "contributes": {
    "api_prefix": "/health",
    "mqtt_subscriptions": ["state/maintenance"],
    "migrations": "migrations/",
    "frontend_flags": ["health.maintenance_console", "health.diagnostics_viewer"]
  },
  "config_schema": "schemas/health.config.schema.json"
}
```

`contract_dependencies` is empty: the module references remedies by *data*
(`ActionRef`), resolved by the frontend against whatever contract owns the
operation — the module itself never imports a sibling (§7.3, `CORE.md` §6.3).

---

## 15. Phased build plan (R1–R5)

| Phase | Scope | Output |
|---|---|---|
| **R1** | Check registry + descriptor schema + `web` checks + sequencer (serial+concurrent, timeout, abort) + `health_run` record + REST `run`/`runs`/`current`. Bridge/hardware checks stubbed as `unavailable`. Standalone tester (core + health alone). | working on-demand health run, web domain only |
| **R2** | Bridge seam: `bridge`-domain checks (`online`, `roundtrip`, `clock_skew`) + LabVIEW Health handler stub. Reachability states real. | seam proven, bridge checks live |
| **R3** | `hardware`-domain checks (instance_connected, self_test, identify, range_sane, loopback) + instance-templated expansion + the disruptive/maintenance gate. Requires LabVIEW maintenance state machine (controller work). | hardware checks behind the maintenance gate |
| **R4** | Known-issues catalog + signature matching + suggestion records + free-text catalog search + suggestion ack feedback. | knowledge surface live (suggest-only) |
| **R5** | Frontends: Diagnostics Viewer (over existing bus) + Maintenance Console (over existing contracts) + Health page. Deep-link health-failure → viewer. | the three surfaces |

R1–R2 are pure Python + core; testable with no rack and no LabVIEW
(simulation discipline, `BORROWABLE_MODULES.md` §9). R3 is the first phase that
needs the controller and real hardware. R4 is data + matching, no hardware. R5
is frontend over proven contracts.

---

## 16. Open decisions to resolve before R1

1. **Suite definitions location** — confirm suites live in `health.config`
   (per-station, deployer-controlled) vs a shipped default set in the manifest.
   Leaning: shipped defaults (`smoke`, `full`, per-domain) overridable by config.
2. **Scheduled / on-event triggers** — v1 is manual + boot only? Or include a
   scheduled poll (cron-like) and an on-diagnostic-event trigger from R1? The
   `trigger` enum reserves the slots; the question is when to wire them.
3. **`hardware.loopback` definition format** — does the drive/read pair and
   tolerance live in `health.config` or in `variables.toml` alongside the
   signals it uses? (It references Variable Engine signals either way.)
4. **Signature error taxonomy** — confirm the `error_category`/`error_code`
   vocabulary is the same taxonomy the logs/error module already defines, so a
   signature is consistent across modules. (Strongly prefer: reuse, don't
   invent a second taxonomy.)
