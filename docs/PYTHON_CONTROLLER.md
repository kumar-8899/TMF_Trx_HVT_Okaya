# Python Test Controller — as-built

The controller is a **contract with two implementations**. LabVIEW served it
historically; the `controller/` package is a second, standalone implementation in
Python. The app cannot tell them apart — both serve the same MQTT ops on
`tmf/{station}/…` (see [LABVIEW_BRIDGE.md](LABVIEW_BRIDGE.md) for the wire
contract, [MULTI_STATION.md](MULTI_STATION.md) for the multi-socket model).

This document is the **as-built** reference for the Python controller: what each
build slice (C1–C10) delivers, the package layout, its config, and the ops it
serves. The governing design contract lives in the program spec (`PYTHON_CONTROLLER.md`
in the delivery bundle); where the two disagree, the contract wins.

> **Hard rule — the controller imports NOTHING from `backend/`.** It depends only
> on `paho-mqtt` and `tmf-instrumentlib`. A test (`tester/test_no_backend_import.py`)
> scans the sources and fails if a `backend.*` / `core.*` / `modules.*` import
> appears. The two processes share a *wire contract*, never code.

---

## 1. Where it runs

```
controller/                       # sibling of backend/, its own pyproject.toml
    pyproject.toml                # deps: paho-mqtt>=2.0, tmf-instrumentlib>=1.0
    controller.example.json       # the one config file (copy → controller.json / generated)
    maps/                         # per-station variable maps
    controller/                   # the package
        __main__.py               # entry point: python -m controller [config.json]
        config.py                 # load + validate the config
        loop.py                   # ONE asyncio loop on a daemon thread (instrument I/O)
        registry.py               # @register_step_type + STEP_REGISTRY
        results.py                # Measurement / StepResult / Limits + verdict rule
        context.py                # StepContext — the only surface a handler touches
        sequencer.py              # step-tree walk, dispatch, timing, retry, abort
        runstate.py               # per-station run state machine (RunEngine)
        dryrun.py                 # §12.2 dry run
        conformance.py            # §7.3 handler-rule static checker (CI gate)
        packages.py               # app step-type package loading + the CI gate
        serve.py                  # cmd/<op> handlers (core / station / run / safety)
        bridge/                   # client.py (one MQTT client per station) + envelope.py
        instruments/              # registry.py (instances), variables.py (signals+actions)
        daq/                      # source.py, stream.py, controller.py
        safety/                   # monitors.py (scope resolution), reflex.py (reflex loop)
        step_types/core.py        # THE 8 CORE STEP TYPES ONLY
    examples/demo_steps/          # a worked example app step-type package (C10)
    tester/                       # headless + live-broker integration tests
```

Run it directly:

```bash
python -m controller controller.json          # default: controller.json
```

Or let the **app start it for you** — set `controller.kind = "python"` in the
app's `app.json` and the backend spawns it on boot (see
[MULTI_STATION.md](MULTI_STATION.md) § "Choosing the controller").

---

## 2. Threading model

One process. Per station run, **one OS thread** (the run thread). All instrument
I/O funnels through **one shared asyncio loop** on its own daemon thread
(`loop.py`), because `instrumentlib` is async while the sequencer is threads —
station threads and MQTT callbacks submit coroutines with `run_coroutine_threadsafe`
and block for the result. The per-instance lock inside `InstrumentBase` then
arbitrates a shared instrument in-process, with no cross-thread races.

---

## 3. Config (`controller.json`)

```jsonc
{
  "schema_version": 1,
  "broker": { "host": "127.0.0.1", "port": 1883 },

  "library_paths":    ["D:/Experiment/Instrument_Library"],  // added to sys.path
  "library_packages": ["instrument_libs"],                   // imported → REGISTRY

  "instruments": [
    { "id": "psu_st1", "library": "keysight_e36xx", "stations": ["st1"],
      "params": { "resource": "SIM" }, "simulated": true }
  ],

  "stations": [
    { "station": "st1", "variable_map": "maps/st1.json" }
  ],

  "safety_monitors": [
    { "id": "estop",       "scope": "pc" },
    { "id": "psu_ovp_st1", "scope": "resource", "resource": "psu_st1" }
  ],

  "step_type_paths":    ["examples"],       // dev: add package repos to sys.path
  "step_type_packages": ["demo_steps"],     // app step-type packages to import

  "simulation": true,                        // force EVERY instrument simulated (§12.1)
  "abort_grace_ms": 2000,
  "teardown_timeout_ms": 30000
}
```

When the **app** starts the controller it writes this file for you at
`backend/data/controller.generated.json` (broker + stations + simulation), so you
never hand-edit it in that mode.

**Instruments under app supervision (v1.5.0+):** the app's **Instruments page**
(Config → Instruments; `instrument` records, owner=python, enabled) is the single
source of instrument instances for the whole application — the backend variable
engine AND the controller. In supervised mode a `controller.json` `instruments`
list is **ignored** (a diag warning names the counts), and an app with nothing
configured starts the controller with **no instruments — even in simulation**.
Configure the instruments in the UI, then restart. A standalone
`python -m controller your-config.json` run (no app) still honors the file's
`instruments` — the override happens in the app's config generation, not in the
controller.

---

## 4. Build slices — what each delivers (as-built)

| Slice | Delivered |
|---|---|
| **C1 — bridge skeleton** | `StationClient` (one MQTT client/station): retained `status` `{"state":"online\|offline"}` with an LWT set before connect; subscribes `cmd/+`; `_connected` set on **SUBACK** (fixes a publish-before-subscribe race); `hello.echo` = echo + wall-clock `ts` (the app's latency + clock-skew probe). App `/readyz` goes green against it. |
| **C2 — instruments + variables** | `InstrumentRegistry` builds `instrumentlib` instances from config (double-open guard, unknown-library skip); `StationVariables` resolves **signals** by name against the station map (read = `raw*gain+offset`, write = clamp → inverse-scale). Serves `variable.read/write/read_many`, `instrument.test`; republishes retained `value/<name>`. |
| **C3 — sequencer core** | `recipe.fetch` (controller→app query), step-tree walk, the 8 core step types, `RunEngine` state machine, abort, teardown, all `event/#`. **The riskiest slice.** |
| **C4 — measurements + retry** | `Measurement`/`StepResult`, **sequencer-computed verdict**, `test-result` events, and retry semantics (§6.1): step-started/completed per attempt, `test-result` only on the final attempt; a retried-then-passed step is a PASS and never poisons the verdict. |
| **C5 — multi-station** | N clients + N run threads over the one shared registry + loop; per-station variable maps; **per-station teardown** (`safe_state_station`); the §9.3 no-lease rule enforced at config load (refuse-start, exit 3). |
| **C6 — DAQ** | `SimDaqSource`/`NiDaqSource`, `StreamPublisher` (one bg thread per signal; **batched** `stream/{ai\|di}` frames at **QoS 0**); serves `daq.{ai,di}.stream.start/stop` + `daq.*.read`. DO writes ride the variable map. |
| **C7 — safety** | Monitors-as-data with scope `pc\|station\|resource`; an **independent reflex thread** (no bridge dependency); on trip → `emergency_disable()` fan-out across the blast radius → `event/safety-trip` (no `run_id`) → affected stations abort with **teardown SKIPPED** → faulted; faulted resources fail fast. |
| **C8 — sim + dry run** | Global `simulation` forces every instrument simulated (§12.1); `dry_run` walks the whole tree + resolves every signal/action name with no hardware → `DRY_RUN_PASS/FAIL`; a static **conformance** checker for the §7.3 handler rules. |
| **C9 — actions** | `ctx.invoke(action, method, args)` resolves a non-scalar action against the calling station's map; capability↔instance bindings verified at config load (refuse-start, exit 5). |
| **C10 — app packages + AI skill** | `step_type_packages` loaded by import so a new customer test ships **without a framework release**; `validate_app_step_types()` CI gate (conformance + schema); the `test-step-authoring` skill; a worked example package `examples/demo_steps/relay_cycle`. |

---

## 5. The run state machine (`runstate.py`)

`idle → starting → running → teardown → idle`, with `aborting` and `faulted`.

- `run.start` is accepted **iff idle**; the app mints `run_id`, the controller
  **echoes** it (`{run_id, accepted}` = "command taken", not "run underway").
- **Failed start** — fetch or validate fails → `run-aborted {reason:
  recipe_fetch_failed | validation_failed}`, **no** `run-started`, back to idle.
- **Abort** → teardown → `run-aborted`. **Deadline + grace** → the watchdog fires,
  the stuck thread is **abandoned, never killed**, station → faulted.
- **Dry run** (`run.start {"dry_run": true}`) → `run-started {dry_run:true}` →
  `run-finished {result: DRY_RUN_PASS|DRY_RUN_FAIL, errors[]}`.
- **Safety trip** — different from abort: hardware state is unknown, so
  recipe teardown **MUST NOT run**; the run aborts `reason: "safety:<monitor_id>"`
  and the station faults. A faulted station refuses `run.start` (`station_faulted`)
  until cleared in maintenance.

Exactly one terminal event per run (`run-finished` **or** `run-aborted`), never
both, never neither.

---

## 6. Step types & the verdict

Eight core types, and nothing else, live in the framework
([contracts/STEP_TYPES.md](contracts/STEP_TYPES.md)):

`repeat`, `sweep`, `if`, `group` (composites) · `wait`, `prompt_operator`,
`set_output`, `measure_and_compare` (primitives).

Everything hardware- or product-specific is an **app step-type package** (§C10).
The **sequencer computes the verdict** — a step FAILs if any `Measurement` FAILs;
a handler cannot report PASS over a failed measurement. Limits come from `params`,
never from handler code.

A handler touches only `ctx` (`context.py`): `read/write/read_many/invoke`,
`wait/aborted/deadline_exceeded/remaining_ms`, `diag`, `execute_child`. **No
instrument, no instance id, no bridge, no DB, no filesystem.** The static
conformance checker (`conformance.py`) enforces the mechanical §7.3 rules (no bare
`time.sleep`, no forbidden imports/`open()`, no unbounded loops, no module/class
state) over every core and app step type.

---

## 7. Ops served (per station, on `tmf/{station}/cmd/<op>`)

```
hello.echo
variable.read | variable.write | variable.read_many | instrument.test
run.start | run.abort | sequencer.list_test_classes
daq.ai.stream.start | daq.ai.stream.stop | daq.ai.read
daq.di.stream.start | daq.di.stream.stop | daq.di.read
safety.trip | safety.clear | safety.status
```

Controller → app queries: `recipe.fetch`. Events published on
`tmf/{station}/event/<type>` (`run-started`, `step-started`, `step-completed`,
`test-result`, `run-finished`, `run-aborted`, `safety-trip`). Streams on
`tmf/{station}/stream/{ai|di}`; retained last values on `value/<name>`.

---

## 8. Safety (C7) in one picture

Blast radius is **declared, not inferred**, and resolved once at config load from
the static map:

| scope | aborts | emergency_disable targets |
|---|---|---|
| `pc` | all stations | every instrument |
| `station` | that socket | instruments serving **only** that socket |
| `resource` | the sockets the instrument lists | that instrument |

The reflex loop runs on its own thread and never touches the bridge, so the
`emergency_disable()` fan-out fires even if the broker is gone. `safety.trip` over
the bridge is one trip *source* (a manual E-stop) — it only enqueues; the reflex
thread does the work.

---

## 9. Testing

```bash
cd controller
python -m pytest -q            # 100 tests: headless + live-broker integration
```

Live integration tests (`tester/test_integration_*.py`) skip when no MQTT broker
is on `127.0.0.1:1883`. `examples/demo_steps` has its own suite, run with
`examples/` on the path (as its CI would): `PYTHONPATH=examples python -m pytest examples`.

---

## 10. Packaging note

In a **frozen** build there is no `python -m controller`. The app's supervisor
looks for a bundled `controller` executable beside the app and warns if it is
absent; source/dev runs use the current interpreter. Building the controller as
its own signed artifact is a packaging task (see
[SECURE_DISTRIBUTION.md](SECURE_DISTRIBUTION.md)).
