---
name: test-step-authoring
description: Author a new test step type for the Python Test Controller — the handler, its parameter schema, a simulated DUT, and the tests that exercise both. Use this skill whenever the user wants to add a test to a test bench, describes a measurement or DUT behaviour they need automated ("ramp the AC until it trips and check recovery", "measure standby current", "cycle the relay 500 times and watch for weld"), asks for a step type, step handler, or test step, or mentions adding a test to an application package such as inverter-eol-steps or motor-tester-steps. Trigger this even when the user only describes the physical test in plain language without naming a step type — turning a described test into a step type is exactly this skill's job. Do NOT use this for authoring recipes, which are data authored by engineers in the UI against the schemas this skill produces.
---

# Test Step Authoring

Turn a described test into a step type for the Python Test Controller.

A **step type** is three things shipped together:

```
step type = param schema      what a recipe may configure
          + handler           the code that runs the test
          + simulation        a fake DUT to review the handler against
```

Read `PYTHON_CONTROLLER.md` §7 and §8 before writing anything. This
skill implements that contract; where the two disagree, the contract
wins.

---

## Scope

**In scope:** step types for application packages
(`inverter_eol_steps`, `motor_tester_steps`, …) and, rarely, promotion
of a step type into the framework's core set.

**Out of scope:**

- Recipes. Recipes are data, authored by engineers in the UI against the
  schema this skill produces. Never generate a recipe.
- Instrument libraries. Those have their own path — see
  `INSTRUMENT_LIBRARY.md` §4.
- Anything that runs on a station. Output goes to the app package repo,
  through CI, in a normal release.

---

## Before writing: gather these

Do not start until every item is answered. A missing answer produces a
step type that looks right and behaves wrong.

### 1. What the test does

Plain language. What happens to the DUT, in what order, and what the
test is looking for.

> "Ramp the AC input down from nominal until the inverter's AC-OK signal
> drops. Record that voltage. Continue down 10 V, hold 1 s, then restore
> to nominal and time how long until AC-OK returns."

### 2. Which signals it touches

Exact names from the target station's variable map. Ask for the map, or
for `GET /variables?station=…` output. Do not invent names.

For each: is it read, written, or both. What units.

### 3. What it measures

For each measured value:

| Field | Example |
|---|---|
| name | `lower_cutoff` |
| unit | `V` |
| limit source | from `params` |
| informational? | no — this one decides pass/fail |

### 4. What the recipe must configure

Apply the parameter rule below. Get an explicit list.

### 5. The DUT's behavioural numbers

**These come from the engineer and the product spec. Never invent
them.** See "The circular check" below for why this is non-negotiable.

- What a good DUT does — trip points, recovery times, tolerances
- At least two ways a bad DUT fails

### 6. Timing and safety

- How long the whole step should take, worst case
- Anything that must be left in a specific state if the step is aborted
- Any condition that is a safety concern rather than a test failure

---

## The parameter rule

This single rule decides most of whether a step type is good.

> **Anything a test engineer might change without changing the test is a
> parameter. Anything only the DUT's physics decides is a constant.**

| Parameter | Constant |
|---|---|
| Limits, tolerances | Settling time set by the ADC's conversion rate |
| Setpoints, nominal values | A protocol-mandated inter-command delay |
| Ramp rates, step sizes | A fixed register offset |
| Dwell times from the spec | An algorithm's internal iteration count |
| Cycle counts | |
| Timeouts the engineer tunes | |

**Both failure directions are real.**

Bake a limit into the handler and changing it needs a code release —
that is variation-as-code, which `PRINCIPLES.md` §1 forbids outright.

Expose everything and the recipe form has forty fields nobody
understands, so engineers copy a working recipe and never touch it.

When genuinely unsure: make it a parameter with a sensible default. A
defaulted parameter costs one line in the schema; a hardcoded constant
costs a release.

---

## Writing the handler

### Signature

```python
def execute(self, params: dict, ctx: StepContext) -> StepResult:
```

### What `ctx` gives you — and nothing else

```
ctx.station                          str
ctx.run_id, ctx.trace                str
ctx.run_parameters                   dict, already substituted

ctx.read(name)                       -> float
ctx.write(name, value)               -> float   returns the written (clamped) value
ctx.read_many(names)                 -> dict
ctx.invoke(action, method, args)     -> Any     non-scalar action
ctx.wait(seconds)                    -> None    deadline- and abort-aware
ctx.aborted()                        -> bool
ctx.deadline_exceeded()              -> bool
ctx.remaining_ms()                   -> int
ctx.diag(level, message, **fields)   -> None
ctx.execute_child(step)              -> StepResult   composites only
```

There is no instrument object, no instance id, no bridge, no database,
no filesystem. If a handler seems to need one, the design is wrong —
raise it rather than working around it.

### The rules — all normative

1. **No bare `time.sleep`.** Use `ctx.wait`. Bare sleep is not
   abort-aware and will hang a station past its deadline.
2. **No direct instrument, socket, file, or database access.**
3. **No unbounded loops.** Every loop checks `ctx.aborted()` and
   `ctx.deadline_exceeded()` and exits cleanly on either.
4. **No module-level or class-level mutable state.** Everything in
   `__init__` or local. Four stations share this process.
5. **Limits come from `params`.** Never hardcoded.
6. **Every measured value is a `Measurement`.** Never a number smuggled
   into `message`.
7. **Raise on impossible conditions.** Never return a value derived from
   a failed read. A silently wrong number poisons a verdict, and that is
   worse than an error.
8. **Do not set the step verdict.** The sequencer computes it from the
   measurements. Returning `status` from a handler is ignored.

### Returning results

```python
from controller.results import StepResult, Measurement, Limits

return StepResult(measurements=[
    Measurement("upper_cutoff",  upper, "V", Limits(p["upper_min"], p["upper_max"])),
    Measurement("lower_cutoff",  lower, "V", Limits(p["lower_min"], p["lower_max"])),
    Measurement("recovery_time", t_rec, "s", Limits(None, p["recovery_max_s"])),
    Measurement("ambient_temp",  amb,   "C", None, status="INFO"),
])
```

- A list, always. One result is a list of one.
- `name` unique within the step. The report addresses it as
  `step_id.measurement_name`.
- `limits=None` or `status="INFO"` → recorded, excluded from pass/fail.
- Inside a loop, set `sequence` so cycle 1 and cycle 200 do not collide.
- The sequencer computes `StepResult.status`: FAIL if any measurement
  fails.

### Abort handling — the pattern

```python
while ctx.read("ac_source_voltage") > floor:
    if ctx.aborted() or ctx.deadline_exceeded():
        raise StepAborted()
    v -= p["ramp_step_v"]
    ctx.write("ac_source_voltage", v)
    ctx.wait(p["settle_s"])
    if ctx.read("dut_ac_ok") < 0.5:
        lower = v
        break
else:
    raise StepFailed("DUT never dropped AC-OK down to the floor voltage")
```

Note the `else` on the `while`. A loop that exits without finding what it
looked for is a failure, not a pass with a missing measurement.

---

## Writing the schema

`schema.json`, JSON Schema, validated at recipe save, load, and run
start.

```jsonc
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["nominal_v", "lower_min", "lower_max", "recovery_max_s"],
  "additionalProperties": false,
  "properties": {
    "nominal_v": {
      "type": "number", "minimum": 0, "maximum": 300, "default": 230,
      "title": "Nominal AC voltage",
      "description": "Line voltage the DUT is restored to after the cutoff sweep."
    },
    "ramp_step_v": {
      "type": "number", "minimum": 0.1, "default": 1.0,
      "title": "Ramp step size",
      "description": "Voltage decrement per iteration. Smaller resolves the trip point more precisely but takes longer."
    },
    "lower_min": { "type": "number", "title": "Lower cutoff — min limit" },
    "lower_max": { "type": "number", "title": "Lower cutoff — max limit" },
    "recovery_max_s": {
      "type": "number", "minimum": 0, "default": 2.0,
      "title": "Maximum recovery time"
    }
  }
}
```

**The schema is the recipe form.** Every field's `title` and
`description` is what a test engineer reads when authoring. Write them
for that reader, not for a developer.

- `additionalProperties: false` — catches typos at save.
- `default` on everything that reasonably has one.
- `minimum` / `maximum` where physics or safety bound the value.
- Group related fields with a shared prefix so the form reads in order.

---

## Registration

```python
@register_step_type(
    type_id          = "ac_voltage_cutoff",
    display_name     = "AC upper/lower cutoff with recovery",
    schema_path      = "schema.json",
    composite        = False,
    required_signals = ("ac_source_voltage", "dut_ac_ok"),
    required_actions = (),
)
class AcVoltageCutoff:
    def execute(self, params, ctx) -> StepResult: ...
```

`required_signals` and `required_actions` are what let recipe validation
report *"station st3 has no `ac_source_voltage`"* at save time instead of
at step 12 of 47. Declare them accurately.

---

## Writing the simulation

A handler with no fake DUT to run against cannot be reviewed. The
simulation is not optional.

### The circular check — why the numbers are not yours

If the same author writes both the handler and the fake DUT, a wrong
assumption appears identically in both. The test passes, the code reads
correctly, and the bench disagrees.

> The handler looks for a trip at 275 V. The simulation trips at 275 V.
> Green everywhere. The real inverter trips at 265 V and the handler
> misses it entirely.

**So: the engineer supplies the behavioural numbers, from the product
spec. This skill writes the simulation code around them.** If the
numbers were not supplied, stop and ask. Do not pick plausible ones.

### Failure modes are mandatory

A simulation that only models a good DUT proves nothing. A production
test exists to catch bad units.

Write at least four scenarios:

| Scenario | Expect |
|---|---|
| Nominal DUT | PASS, measurements near spec centre |
| Out-of-limit DUT | FAIL, on the specific measurement that is out |
| Non-responsive DUT | Clean failure, no hang, no exception leak |
| Aborted mid-step | Clean abort, hardware left safe, teardown reached |

Add a boundary case where a measurement sits exactly on a limit, and
state which way it should resolve.

### Shape

```python
# simulate.py
class FakeInverter:
    """Behaviour per Acme INV-C spec rev 4, table 3.
    Numbers supplied by the test engineer — do not adjust to make a test pass."""

    def __init__(self, trip_low_v=265.0, trip_high_v=None, recovery_s=1.5):
        ...
```

Docstring the source of every number. When a test later fails on real
hardware, the first question is whether the spec or the handler was
wrong, and that docstring answers it.

---

## Output

Five files in the application package:

```
inverter_eol_steps/ac_voltage_cutoff/
    __init__.py
    handler.py        the step type + @register_step_type
    schema.json       parameter schema
    simulate.py       fake DUT, numbers from the engineer
    test_step.py      the four+ scenarios
    README.md         what it does, params, measurements, spec reference
```

`README.md` covers: what the test does in plain language, every
parameter and what changing it does, every measurement and its unit,
which spec section the behaviour comes from, and known limitations.

---

## Review checklist

Walk this before handing the step type over.

**Parameters**
- [ ] Every limit comes from `params`, none hardcoded
- [ ] Every parameter is something an engineer would plausibly change
- [ ] Every parameter has a `title` and `description` a test engineer
      can read
- [ ] `additionalProperties: false`

**Handler**
- [ ] No `time.sleep`, no direct I/O, no module-level state
- [ ] Every loop checks abort and deadline
- [ ] Every loop that can exit without finding its target handles that
      as a failure
- [ ] Signal names match the station map exactly
- [ ] Every measured value is a `Measurement` with name, unit, limits
- [ ] Measurement names unique within the step
- [ ] `sequence` set for measurements inside a loop
- [ ] The handler does not set the step verdict
- [ ] Reads that could fail raise rather than returning a default

**Simulation**
- [ ] Behavioural numbers came from the engineer, cited in a docstring
- [ ] Nominal, out-of-limit, non-responsive, and abort scenarios present
- [ ] At least one boundary case, with the expected resolution stated

**Before release**
- [ ] Runs green in simulation
- [ ] **Run once against a real DUT.** Simulation proves the logic;
      hardware proves the assumptions. This step is not skippable.
- [ ] Through CI into the app package repo, not copied onto a station

---

## Promotion

A step type needed by two or more applications belongs in the framework's
core set, not duplicated.

Duplication across two app packages is acceptable short-term and is
precisely the signal that promotion is due. Raise it; do not silently
copy a third time.

The core set is deliberately eight step types
(`PYTHON_CONTROLLER.md` §7.4). A candidate for promotion must be
genuinely hardware-agnostic and useful to an application nobody has
built yet. "Two customers happened to need it" is the evidence; it is
not automatic.
