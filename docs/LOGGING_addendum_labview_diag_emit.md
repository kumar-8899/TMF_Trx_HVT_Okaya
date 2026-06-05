# Addendum to LOGGING.md §5 — LabVIEW diag emit

> Paste this as a subsection under `LOGGING.md` §5 ("Decisions for
> re-implementers"). It is the **emit-side** contract for the LabVIEW host; the
> **persistence-side** consumer is the `logs` module (`LOGS.md`). The event
> shape is the one already defined in `LOGGING.md` §2.3 — this section only
> says how LabVIEW produces it.

---

## 5a. LabVIEW diag emit

The LabVIEW host is the cross-language other half of the bus. It produces the
**same event shape** as the Python side (`LOGGING.md` §2.3) so a bug across the
MQTT seam is one timeline. The rule is the same as Python: **one emit function,
safe to call from any module/clone, that never blocks.**

### Shape it produces

```
seq        monotonic, per LabVIEW process   (DVR/FGV counter)
ts         epoch seconds, float             (high-resolution timestamp)
level      debug | info | warning | error | critical
subsystem  "acquisition" | "logging" | "ui" | …   (lowercase, short, dotless)
message    short + STABLE across versions   (this is the dedup key, §2.3/§6)
context    JSON object — volatile/request-specific data goes HERE
exception  repr + call chain on the error path, else null
source     "labview:{station}"              (stamped so logs dedup never collides)
```

### Build shape (DQMH / Workers)

One Diagnostics module (a DQMH module, or a DVR-backed class / FGV) exposes
`Debug / Info / Warning / Error / Exception`. Each emit does two fan-outs:

```
Diagnostics.Error("acquisition", "TDMS write failed", error_cluster)
        │  stamp seq + ts + source="labview:st1"
        ├─ LOCAL : push onto a ring buffer + fire a broadcast User Event
        │          → visible in the Workers / DQMH message log (local-only)
        └─ WIRE  : JSONtext serialize → Bridge publishes tmf/diag/{station}
                   → the Python logs module persists it (LOGS.md §6)
```

`LOGGING.md` §5 translation hints already cover the mechanics: Emit → FGV/DVR
class pushing to an internal queue + ring buffer; topic publish → User Event
broadcast; file sink → producer-consumer VI writing JSONL.

### Mapping a LabVIEW error cluster to the event

| Event field | From the error cluster |
|---|---|
| `level` | `error` (or `critical` for a known-fatal code list) |
| `subsystem` | the module name — `acquisition`, `logging`, `ui` |
| `message` | `"Error -2501 at TDMS Write in Logging.lvclass:Log Data.vi"` — **keep stable**; this is the dedup key |
| `context` | `{ "code": -2501, "fault_vi": "Logging.lvclass:Log Data.vi", "call_chain": "…->Launcher-UI.vi" }` |
| `exception` | the full `error.source` string |

### Where to call it

Instrument **once per module, not per VI.** Every DQMH/Workers module funnels
caught errors through a single error-handling case — that case is the one place
to call `Diagnostics.Error(cluster)`. A recurring fault (e.g. `Error -2501` at
TDMS Write firing every second) emits with a stable `message`; the Python-side
coalescer (`LOGS.md` §6.2) collapses the burst into two rows, not dozens.

### Actions vs errors from LabVIEW

LabVIEW does **not** call a "log action" method across the seam. Run-lifecycle
actions (`run.start`, `run.abort`, `run.complete`) are published as domain
events on `tmf/event/run-*` (`CORE.md` §7); the `logs` module's subscriber
translates each into an internal `record_action(...)` (`LOGS.md` §6.3). Errors
and info go on `tmf/diag/{station}`; actions go on `tmf/event/#`. Two channels,
two concerns — never mixed.

### Visibility layers (so the seam is clear)

```
Layer 1  Workers / DQMH message log   in-process LabVIEW message passing.
                                       Zero instrumentation. localhost only.
                                       MQTT Explorer cannot see this.
Layer 2  MQTT Explorer on tmf/#        the cross-language seam only
                                       (event/#, value/#, status, stream/#, diag/#).
Layer 3  Diagnostics viewer (D5)       curated, leveled, BOTH-sides timeline,
                                       fleet-wide via the central broker, backed
                                       by the logs module. The one you BUILD.
```

Keep using Layer 1 locally — it is free and excellent. Do **not** push every
DQMH message onto MQTT to recreate it; that floods the broker and duplicates a
tool that already works (and `stream/#`-class internal traffic stays local per
`PRINCIPLES.md` §0). The cross-language analog you build is Layer 3, which is
*semantic* (deliberate emits), not a raw message trace — complementary to,
not a replacement for, Layer 1.
