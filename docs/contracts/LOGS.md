# LOGS.md — Action & Error Logs Module

The `logs` module is the **durable, queryable record of what happened** on a
station: operator/controller **actions** and system **errors/diagnostics**. It
is the persistence + history side of the Diagnostics Bus (`LOGGING.md`). The
live tail stays in the bus (`/diagnostics/stream`); `logs` owns the **history**.

This is **build-order step 2** (after Auth — `PRINCIPLES.md` Build order). It
implements `PRINCIPLES.md` §5 (RAG-ready by construction) and `CORE.md` §7
(persistence + the RAG envelope) for the logging domain.

Read `PRINCIPLES.md`, `CORE.md`, and `LOGGING.md` first. This doc is the
contract; build against **this doc**, not memory.

---

## 0. Locked decisions

Settled in design chat. Re-open only by editing this file.

| # | Question | Decision |
|---|---|---|
| 1 | Unify or split record types? | **Split.** Two record types (`error_log`, `action_log`), one module, two endpoints. A future merged timeline is a query-layer concern (§11), not a shared record shape. |
| 2 | How do actions arrive? | **Explicit `LogsContract.record_action(...)`**, resolved via `core.get_contract("logs")`. NOT auto-derived from a `category=action` diag convention. |
| 3 | Variant(s)? | **`db` only** for now. The `jsonl` variant slot is reserved in the manifest, not built. |
| 4 | Retention? | **Append-only** by default, with **dedup/coalescing on write** (§6) and **optional pruning** (§9) bounded by config + license. |
| 5 | Double-write risk? | **Single write path.** One internal sink, two callers (in-process Python diag + MQTT LabVIEW diag). `source` is stamped at emit; Python events never loop back over MQTT. |
| 6 | Permissions? | `VIEWER` reads errors, `OPERATOR` reads actions, `ADMIN` deletes. `record_action` takes a `Principal` — attribution enforced at the call site (§10). |

---

## 1. Where it sits

```
  Auth · Recipe · Report · Analytics · …          (siblings — never import logs)
        │ record_action(...)         ▲ query_errors / query_actions
        ▼ via core.get_contract      │
  ┌──────────────────────────────────────────────────────────────┐
  │  logs module  (contract: LogsContract; variant: db)           │
  │   ── ingestion ──────────────────────────────────────────────│
  │   Python diag  ─ core.diag.add_sink ─┐                        │
  │                                       ├─► LogsDiagSink ──► error_log
  │   LabVIEW diag ─ bridge tmf/diag/# ──┘     (dedup, §6)         │
  │   actions      ─ record_action() ────────────────────► action_log
  │   run actions  ─ bridge tmf/event/run-* ─► record_action() ──┘ │
  │   ── query ──────────────────────────────────────────────────│
  │   /logs/errors · /logs/actions · /logs/stats · DELETE (admin) │
  └───────────────────────────────┬──────────────────────────────┘
                                   ▼ base Repository (RAG envelope, append-only)
                                  core.db
```

Depends only on the core: `db`, `bridge`, `config`, `auth`, `diag`, `web`
(`CORE.md` §1). No `contract_dependencies` — `logs` is a **leaf**; it is
consumed by Report/Analytics later and consumes nothing.

---

## 2. Manifest

```json
{
  "schema_version": 1,
  "module": {
    "id": "logs",
    "version": "1.0.0",
    "contract_version": 1,
    "display_name": "Action & Error Logs",
    "description": "Durable, queryable record of operator actions and system errors. Persistence and history side of the diagnostics bus."
  },
  "entitlement_key": "logs",
  "variants": ["db"],
  "core_dependencies": ["db", "bridge", "config", "auth", "diag", "web"],
  "contract_dependencies": [],
  "contributes": {
    "api_prefix": "/logs",
    "mqtt_subscriptions": ["tmf/diag/#", "tmf/event/run-#"],
    "migrations": "migrations/",
    "frontend_flags": ["logs.errors_enabled", "logs.actions_enabled"]
  },
  "config_schema": "schemas/logs.config.schema.json"
}
```

---

## 3. Config

`config/logs.config.schema.json` validates this shape. The live values come
from the module's `config` block in `config/app.json` (`CORE.md` §3.2).

```json
{
  "schema_version": 1,
  "persist": {
    "min_level": "warning",
    "subsystems": []
  },
  "dedup": {
    "enabled": true,
    "window_s": 10
  },
  "retention": {
    "error_log":  { "max_days": 90,  "max_records": 500000 },
    "action_log": { "max_days": 365, "max_records": 1000000 }
  },
  "pruning": {
    "enabled": true,
    "run_at_hour_utc": 2
  }
}
```

- `persist.min_level` — minimum diag level written to the DB. `debug`/`info`
  are usually too chatty for a queryable store; `warning` is the default.
- `persist.subsystems` — allow-list filter; empty means **all**.
- `dedup` — §6.
- `retention` / `pruning` — §9. The license MAY cap `max_records` downward.

---

## 4. Record shapes

Both record types are persisted through the base `Repository`, which stamps the
**RAG envelope** automatically (`CORE.md` §7): `id`, `type`, `ts`, `station`,
`source_version`, `summary`. The shapes below are the module's own `data`
payload. Field rules follow `DATA_TRANSFER.md` §6 (stable names, numbers in
declared form, enums as strings, lists always present).

### 4.1 `error_log` — persisted from the diag bus

```json
{
  "source":     "python | labview:st1",
  "seq":        1024,
  "level":      "warning | error | critical",
  "subsystem":  "daq",
  "message":    "Error -2501 at TDMS Write in Logging.lvclass:Log Data.vi",
  "context":    { "code": -2501, "fault_vi": "Logging.lvclass:Log Data.vi" },
  "exception":  null,

  "repeat_count": 1,
  "coalesced":    false,
  "window_start": null,
  "window_end":   null
}
```

`summary` (stamped by the sink): `"[{level}] {subsystem}: {message}"`.
The coalescing fields (`repeat_count`, `coalesced`, `window_*`) carry the dedup
result — see §6.

### 4.2 `action_log` — persisted via `record_action`

```json
{
  "user":   "operator1",
  "role":   2,
  "action": "recipe.save",
  "target": "inverter-board-rev-c/v4",
  "result": "success | failure",
  "detail": { "version_created": 4 }
}
```

`summary` (stamped at write): `"{user} {action} {target} -> {result}"` — reads
as a sentence so it embeds and retrieves meaningfully (`PRINCIPLES.md` §5).

### 4.3 Action naming convention

`module.verb`, lowercase, dotted, **stable** across versions. The dot namespace
powers the `action` prefix filter (§7) and cheap `action LIKE 'recipe.%'`
grouping for future analytics.

```
auth.login   auth.logout   auth.user_created   auth.user_locked
recipe.save  recipe.delete recipe.activate
run.start    run.abort     run.complete
report.export
safety.emergency_disable
```

---

## 5. The `LogsContract`

The interface siblings resolve via `core.get_contract("logs")`. They MUST NOT
import the `logs` package (`CORE.md` §6.1, §6.3).

```
LogsContract:

    record_action(
        principal : Principal,             # from core.auth — enforces attribution
        action    : str,                   # "recipe.save" | "run.abort" | …
        target    : str,                   # id / name / path acted on
        result    : "success" | "failure",
        detail    : dict = {}              # free-form extra context
    ) -> str                               # persisted record id

    query_errors(
        since=None, until=None,            # epoch seconds, float
        level=None,                        # minimum: warning | error | critical
        subsystem=None,
        limit=200, cursor=None
    ) -> Page[ErrorRecord]

    query_actions(
        since=None, until=None,
        user=None,
        action=None,                       # prefix match: "recipe." → all recipe.*
        result=None,
        limit=200, cursor=None
    ) -> Page[ActionRecord]
```

`Page[T] = { items: [T], next_cursor: str | null, total: int | null }`.
**Cursor-based** pagination — the store is append-only, so offset pagination
drifts as rows arrive mid-export. The cursor is opaque (encodes `ts`+`id`).

---

## 6. Ingestion and dedup (the single write path)

### 6.1 One sink, two callers

`LogsDiagSink.receive(event)` is the **only** path that writes `error_log`. It
is fed from two places, wired at `init`:

```
init():
    sink = LogsDiagSink(repo=db.repository("error_log"),
                        min_level=cfg.persist.min_level,
                        subsystems=cfg.persist.subsystems,
                        dedup=cfg.dedup)

    core.diag.add_sink(sink)                          # caller 1: Python in-process
    bridge.subscribe("tmf/diag/#", lambda t, p:       # caller 2: LabVIEW over MQTT
        sink.receive(DiagnosticEvent.from_mqtt(p, source=f"labview:{station}")))
```

`receive()` stamps `source` if absent, applies the level/subsystem filter,
generates `summary`, runs dedup, and calls `Repository.put("error_log", …)`.

**Double-write is structurally impossible**: Python events arrive only via the
in-process sink; LabVIEW events arrive only via MQTT; the bridge does not echo
Python diag back over MQTT. `source` + `seq` is a unique key per origin even if
topologies change later.

### 6.2 Dedup / coalescing

Signature = `(source, level, subsystem, message)` — **excludes** volatile
`context`, `seq`, timestamps. (This is why `LOGGING.md` §6 requires stable
messages and request-specific data in `context`.)

Within `dedup.window_s`:

1. **First occurrence** → write immediately, `repeat_count: 1`, `coalesced:
   false`. Queryable at once, crash-safe.
2. **Identical within window** → suppressed; increment an in-memory counter,
   track `last_seen`. No row written.
3. **Window closes with count > 1** → append **one** coalescing row: same
   signature, `coalesced: true`, `repeat_count: N`, `window_start`/`window_end`.

A 47× burst produces **2 rows**, not 47. Pure append-only; first occurrence
always durable. The live `/diagnostics/stream` is **not** deduped — it shows
every tick in real time. `action_log` is **never** deduped — two identical
actions are two distinct audit facts.

### 6.3 LabVIEW-originated actions

LabVIEW (the controller) does not call `record_action` across the seam. Run
lifecycle events arrive on `tmf/event/run-*` (`CORE.md` §7); the module's
subscriber translates each into an internal `record_action(...)` call — so the
contract remains the single action write path, symmetric with §6.1. See
`LOGGING.md` §5 for the LabVIEW emit contract.

---

## 7. REST surface

Mounted under `/logs` (`CORE.md` §3.1 `contributes.api_prefix`). All errors are
RFC-7807 (`DATA_TRANSFER.md` §2.2). Auth per §10.

```
GET /logs/errors
    ?since=&until=&level=warning&subsystem=daq&limit=200&cursor=…
    VIEWER → Page[ErrorRecord]

GET /logs/actions
    ?since=&until=&user=&action=recipe.&result=&limit=200&cursor=…
    OPERATOR → Page[ActionRecord]

GET /logs/stats
    ?since=
    VIEWER → { error_counts: {warning,error,critical},
               action_counts: {total,failures},
               subsystems: [..], users: [..] }      # powers UI filter dropdowns

DELETE /logs/errors?before=<epoch_s>     ADMIN → { deleted: N }
DELETE /logs/actions?before=<epoch_s>    ADMIN → { deleted: N }
```

`since`/`until` are epoch seconds (float). `level` is a **minimum** (warning
includes error+critical). `action` is a **prefix** match.

---

## 8. Retention and pruning

Append-only is the default. A station running 24/7 for years needs a bounded
hot store, so pruning is the safety valve:

- Runs as a low-priority background task, daily at `pruning.run_at_hour_utc`.
- Prunes by `ts`, **oldest first**, per record type.
- **Never** prunes below `max_records` even if `max_days` has passed — a
  low-throughput station keeps everything.
- The license MAY cap `max_records` downward (smaller plan = shorter history).
- Pruning deletes from the **DB store only**. If the optional JSONL file sink
  (`LOGGING.md` §2.8) is on, the flat files are the cold archive; pruning only
  cleans the queryable hot store.

---

## 9. Permissions (fail-closed)

| Operation | Required | Why |
|---|---|---|
| `GET /logs/errors` | `VIEWER` | an operator debugging a failing test needs errors without elevation |
| `GET /logs/actions` | `OPERATOR` | action logs carry `user` attribution — a softer audit trail |
| `GET /logs/stats` | `VIEWER` | UI dropdowns + dashboard counts |
| `record_action(principal, …)` | internal | takes a verified `Principal`; no HTTP gate — server-side callers are already inside the trust boundary |
| `DELETE /logs/*` | `ADMIN` | destructive |
| pruning task | system | no HTTP gate |

Verification goes through `core.auth` (`CORE.md` §6.4). If no Auth module is
loaded, `core.auth` rejects all tokens; the `no-auth` dev variant exists for
local work.

---

## 10. Standalone testability

`logs` boots and is fully exercised against **core + logs (db variant)** with
no broker (`PRINCIPLES.md` §1, `CORE.md` §6.2):

- **Python diag path** — fire synthetic `DiagnosticEvent`s straight into the
  sink; assert dedup coalescing (1 burst → 2 rows), `min_level` filtering,
  envelope stamping, query filters, cursor pagination. No broker.
- **Action path** — call `record_action(stub_principal, …)`; assert the
  `action_log` row, `summary` sentence, attribution.
- **LabVIEW diag path** — integration test only; needs a broker (or a mocked
  `bridge`) to publish `tmf/diag/#` and assert the same sink result with
  `source="labview:st1"`.

---

## 11. Non-goals (now) and what it unlocks

**Not built now:** the merged `GET /logs/timeline` (define the concept; defer
until Report needs it — it changes no record shapes); the `jsonl` variant (slot
reserved); any frontend (the future diag viewer is `LOGGING.md` §4 / D5); the
LabVIEW emit itself (`LOGGING.md` §5).

**Unlocks immediately once active:**

- Auth calls `record_action(principal, "auth.login", username, "success")` —
  the audit trail starts day one.
- Report/Analytics query `/logs/errors?since=run_start&until=run_end` to attach
  error context to a run — no new infrastructure.
- `diag.warning("daq", …)` persists automatically once the sink is registered —
  zero call-site changes anywhere in the codebase.
- Every `action_log` row has a sentence `summary` + `user`/`action`/`target`
  provenance — the RAG corpus is queryable by construction.

---

## 12. Repo layout (per `CORE.md` §8)

```
backend/modules/logs/
    manifest.json
    __init__.py            # @register_module + @register_variant("logs","db")
    contract.py            # LogsContract (Protocol), Page, ErrorRecord, ActionRecord
    variants/
        db.py              # the db variant: sink wiring, query impl, pruning task
    sink.py                # LogsDiagSink (single write path, dedup)
    api.py                 # FastAPI router: errors/actions/stats/deletes
    schemas/
        logs.config.schema.json
    migrations/            # if the base repo needs per-type indices
    tester/                # pytest: standalone core+logs, no broker for Python path
```
