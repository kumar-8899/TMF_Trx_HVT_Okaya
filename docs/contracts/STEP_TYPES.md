# STEP_TYPES.md — Starter Step Type Catalog

This doc is the catalog of the 15 starter step types the Recipe module
ships with. Each entry has:

- A one-line purpose.
- The JSON Schema for its `params`.
- A short usage example.
- A handler note for the Test Sequencer DQMH `Execute` case.

The schemas use JSON Schema **draft 2020-12**. Each ships in its own
directory under `backend/modules/recipe/step_types/`. The validator
uses `$ref` to pull in shared definitions from `_common/`.

Read `RECIPE.md` first.

---

## 0. How a step is validated

Every step is validated in two passes:

1. **Envelope pass** — validate against `_common/envelope.schema.json`
   (the base step shape). Confirms `step_id`, `step_type`, and the
   common envelope fields.
2. **Params pass** — look up `step_type` in the registry; validate
   `params` against that step type's schema.

If either pass fails, the recipe is rejected at save / load / run-start
per the strictness rules in `RECIPE.md` §7.

---

## 1. Common building blocks (`_common/`)

These ship once and are referenced by every step-type schema.

### 1.1 `_common/envelope.schema.json`

The base step shape. Every step type's schema `$ref`s this and adds its
own `params` constraints.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "tmf:recipe:_common/envelope",
  "title": "Step envelope",
  "type": "object",
  "required": ["step_id", "step_type"],
  "additionalProperties": false,
  "properties": {
    "step_id": {
      "type": "string",
      "pattern": "^[a-z][a-z0-9_]{0,63}$",
      "description": "Stable identifier within the recipe; appears in run records."
    },
    "step_type":       { "type": "string" },
    "name":            { "type": "string" },
    "description":     { "type": "string" },
    "enabled":         { "type": "boolean",  "default": true },
    "timeout_ms":      { "type": "integer",  "minimum": 0 },
    "retry_count":     { "type": "integer",  "minimum": 0, "default": 0 },
    "on_fail":         { "enum": ["stop", "continue", "retry"], "default": "stop" },
    "safety_critical": { "type": "boolean",  "default": false },
    "params":          { "type": "object" }
  }
}
```

### 1.2 `_common/condition.schema.json`

The small fixed grammar for conditions. Used by `wait_until`,
`ramp_until`, `if_then_else`, `abort_if`. Intentionally not an
expression language.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "tmf:recipe:_common/condition",
  "title": "Condition over a Variable Engine variable",
  "type": "object",
  "required": ["variable", "op", "value"],
  "additionalProperties": false,
  "properties": {
    "variable": {
      "type": "string",
      "description": "Variable name from variables.toml; resolved at run time."
    },
    "op": { "enum": ["==", "!=", "<", "<=", ">", ">=", "between"] },
    "value":  { "type": ["number", "boolean", "string"] },
    "value2": { "type": "number", "description": "Required when op == 'between'." }
  },
  "allOf": [
    {
      "if":   { "properties": { "op": { "const": "between" } } },
      "then": { "required": ["value2"] }
    }
  ]
}
```

### 1.3 `_common/limits.schema.json`

Pass/fail limits. At least one of `min` or `max` must be present.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "tmf:recipe:_common/limits",
  "title": "Numeric pass/fail limits",
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "min":      { "type": "number" },
    "max":      { "type": "number" },
    "expected": { "type": "number", "description": "Nominal value, diagnostics only." }
  },
  "anyOf": [
    { "required": ["min"] },
    { "required": ["max"] }
  ]
}
```

### 1.4 `_common/value_ref.schema.json`

A value that is either a literal number or a `${run.<name>}`
substitution from `run_parameters` (resolved before the recipe is sent
to LabVIEW).

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "tmf:recipe:_common/value_ref",
  "title": "Number or run-parameter substitution",
  "oneOf": [
    { "type": "number" },
    {
      "type": "string",
      "pattern": "^\\$\\{run\\.[a-z_][a-z0-9_]*\\}$"
    }
  ]
}
```

---

## 2. Primitive step types (10)

### 2.1 `set_output` — write a variable

Write a value to an analog or digital output variable. Clamping is
enforced by the Variable Engine (`VARIABLE_ENGINE.md` §5).

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "tmf:recipe:step_types/set_output/params",
  "type": "object",
  "required": ["variable", "value"],
  "additionalProperties": false,
  "properties": {
    "variable":  { "type": "string", "description": "Variable Engine name." },
    "value":     { "$ref": "tmf:recipe:_common/value_ref" },
    "settle_ms": { "type": "integer", "minimum": 0,
                   "description": "Delay after writing before the step completes." }
  }
}
```

**Example:**
```json
{
  "step_id":   "preset_bus",
  "step_type": "set_output",
  "name":      "Preset DC bus to 264 V",
  "params":    { "variable": "dc_bus_setpoint", "value": 264.0, "settle_ms": 300 }
}
```

**LabVIEW:** call Variable Engine `Write.vi` with `(variable, value)`;
sleep `settle_ms`; return `{status: PASSED}`.

---

### 2.2 `measure` — read and store

Read a variable, optionally average over N samples, and store the
result under the step_id (so later steps can reference it).

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "tmf:recipe:step_types/measure/params",
  "type": "object",
  "required": ["variable"],
  "additionalProperties": false,
  "properties": {
    "variable":  { "type": "string" },
    "samples":   { "type": "integer", "minimum": 1, "default": 1,
                   "description": "If > 1, returns the mean of N reads at sample_rate_hz." },
    "sample_rate_hz": { "type": "number", "minimum": 1, "default": 100 },
    "store_as":  { "type": "string", "pattern": "^[a-z][a-z0-9_]*$",
                   "description": "Override the store key (defaults to step_id)." }
  }
}
```

**Example:**
```json
{
  "step_id":   "vbus_settled",
  "step_type": "measure",
  "params":    { "variable": "vbus_main", "samples": 10, "sample_rate_hz": 1000 }
}
```

**LabVIEW:** Variable Engine `Read.vi` × N at rate; mean; emit
measurement onto the run record under `store_as` (or `step_id`).

---

### 2.3 `compare` — assert measured value against limits

Compare either a live variable read or a stored measurement from an
earlier `measure` step to a limits envelope.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "tmf:recipe:step_types/compare/params",
  "type": "object",
  "required": ["source", "limits"],
  "additionalProperties": false,
  "properties": {
    "source": {
      "oneOf": [
        {
          "type": "object",
          "required": ["variable"],
          "additionalProperties": false,
          "properties": { "variable": { "type": "string" } },
          "description": "Live read from Variable Engine at compare time."
        },
        {
          "type": "object",
          "required": ["measurement"],
          "additionalProperties": false,
          "properties": { "measurement": { "type": "string" } },
          "description": "Reference an earlier measure step by its store key."
        }
      ]
    },
    "limits": { "$ref": "tmf:recipe:_common/limits" }
  }
}
```

**Example:**
```json
{
  "step_id":   "vbus_in_band",
  "step_type": "compare",
  "params":    {
    "source": { "measurement": "vbus_settled" },
    "limits": { "min": 250.0, "max": 278.0, "expected": 264.0 }
  }
}
```

**LabVIEW:** look up `source` (live or stored); compare against
limits; return PASSED / FAILED with the measurement attached.

---

### 2.4 `measure_and_compare` — the common case in one step

Convenience for the 80% case: read, optionally settle, compare,
return.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "tmf:recipe:step_types/measure_and_compare/params",
  "type": "object",
  "required": ["variable", "limits"],
  "additionalProperties": false,
  "properties": {
    "variable":       { "type": "string" },
    "settle_ms":      { "type": "integer", "minimum": 0, "default": 0 },
    "samples":        { "type": "integer", "minimum": 1, "default": 1 },
    "sample_rate_hz": { "type": "number",  "minimum": 1, "default": 100 },
    "limits":         { "$ref": "tmf:recipe:_common/limits" }
  }
}
```

**Example:**
```json
{
  "step_id":   "vbus_check",
  "step_type": "measure_and_compare",
  "params":    {
    "variable":  "vbus_main",
    "settle_ms": 500,
    "samples":   10,
    "limits":    { "min": 250.0, "max": 278.0, "expected": 264.0 }
  }
}
```

**LabVIEW:** sleep `settle_ms`; mean of N reads; compare; emit
measurement + verdict.

---

### 2.5 `ramp_until` — sweep a variable until a condition is met

Linear ramp on an output variable, polling a condition each step.
Terminates on condition met or timeout.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "tmf:recipe:step_types/ramp_until/params",
  "type": "object",
  "required": ["variable", "start", "end", "step_size", "dwell_ms", "until"],
  "additionalProperties": false,
  "properties": {
    "variable":   { "type": "string", "description": "Output variable to ramp." },
    "start":      { "type": "number" },
    "end":        { "type": "number" },
    "step_size":  { "type": "number", "exclusiveMinimum": 0 },
    "dwell_ms":   { "type": "integer", "minimum": 0,
                    "description": "Wait between each write before checking 'until'." },
    "until":      { "$ref": "tmf:recipe:_common/condition" },
    "on_no_match":{ "enum": ["fail", "pass_at_end"], "default": "fail",
                    "description": "What to do if 'end' is reached without meeting 'until'." }
  }
}
```

**Example:**
```json
{
  "step_id":   "find_trip_point",
  "step_type": "ramp_until",
  "params":    {
    "variable":  "dc_bus_setpoint",
    "start":     200.0, "end": 320.0, "step_size": 2.0,
    "dwell_ms":  100,
    "until":     { "variable": "overvoltage_trip", "op": "==", "value": true }
  }
}
```

**LabVIEW:** loop write + sleep + condition check; record the value at
which the condition fired into the run record.

---

### 2.6 `wait` — fixed delay

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "tmf:recipe:step_types/wait/params",
  "type": "object",
  "required": ["duration_ms"],
  "additionalProperties": false,
  "properties": {
    "duration_ms": { "type": "integer", "minimum": 0 }
  }
}
```

**Example:**
```json
{ "step_id": "settle", "step_type": "wait", "params": { "duration_ms": 1000 } }
```

**LabVIEW:** `Wait (ms).vi`.

---

### 2.7 `wait_until` — wait for a condition

Poll a variable until a condition is met or the step times out. The
poll interval is implementation-defined (typically 50 ms).

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "tmf:recipe:step_types/wait_until/params",
  "type": "object",
  "required": ["condition"],
  "additionalProperties": false,
  "properties": {
    "condition":      { "$ref": "tmf:recipe:_common/condition" },
    "poll_interval_ms": { "type": "integer", "minimum": 10, "default": 50 }
  }
}
```

**Example:**
```json
{
  "step_id":   "wait_for_interlock",
  "step_type": "wait_until",
  "timeout_ms": 5000,
  "params":    { "condition": { "variable": "interlock_ok", "op": "==", "value": true } }
}
```

**LabVIEW:** poll loop with envelope `timeout_ms` enforcement.

---

### 2.8 `prompt_operator` — modal prompt

Send a prompt to the operator UI over MQTT and wait for the response.
Captures the response into the run record.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "tmf:recipe:step_types/prompt_operator/params",
  "type": "object",
  "required": ["title", "message", "kind"],
  "additionalProperties": false,
  "properties": {
    "title":   { "type": "string" },
    "message": { "type": "string" },
    "kind":    { "enum": ["info", "confirm", "input"] },
    "options": {
      "type": "array",
      "items": { "type": "string" },
      "description": "For kind=confirm; defaults to ['OK','Cancel']."
    },
    "input_validation": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "pattern": { "type": "string" },
        "min":     { "type": "number" },
        "max":     { "type": "number" }
      },
      "description": "For kind=input."
    },
    "fail_on_cancel": { "type": "boolean", "default": true }
  }
}
```

**Example:**
```json
{
  "step_id":   "verify_fixture",
  "step_type": "prompt_operator",
  "params":    {
    "title":   "Fixture check",
    "message": "Confirm DUT is seated and clamps are closed.",
    "kind":    "confirm",
    "options": ["Confirmed", "Cancel"]
  }
}
```

**LabVIEW:** publish `prompt/<run_id>/<step_id>` with the prompt
payload; subscribe to `prompt/<run_id>/<step_id>/response`; block on
reply with `timeout_ms` enforcement.

---

### 2.9 `log_message` — structured log line into the run record

Drop a labelled message into the run record and the Diagnostics Bus
(`LOGGING.md` §2). Used for narration ("DUT identification complete")
and for cross-referencing future RAG retrieval.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "tmf:recipe:step_types/log_message/params",
  "type": "object",
  "required": ["message"],
  "additionalProperties": false,
  "properties": {
    "level":     { "enum": ["debug", "info", "warning", "error"], "default": "info" },
    "subsystem": { "type": "string", "default": "recipe" },
    "message":   { "type": "string" },
    "context":   { "type": "object",
                   "description": "Free-form key→value attached to the event." }
  }
}
```

**Example:**
```json
{
  "step_id":   "phase_marker",
  "step_type": "log_message",
  "params":    { "message": "Beginning high-line transfer phase", "level": "info" }
}
```

**LabVIEW:** call the Diagnostics emit VI.

---

### 2.10 `abort_if` — guard step

Evaluate a condition once. If it holds, abort the run immediately. Use
for safety preconditions ("interlock open" or "temperature too high").

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "tmf:recipe:step_types/abort_if/params",
  "type": "object",
  "required": ["condition", "reason"],
  "additionalProperties": false,
  "properties": {
    "condition": { "$ref": "tmf:recipe:_common/condition" },
    "reason":    { "type": "string",
                   "description": "Operator-facing reason; written into the run record." }
  }
}
```

**Example:**
```json
{
  "step_id":   "guard_thermal",
  "step_type": "abort_if",
  "params":    {
    "condition": { "variable": "heatsink_temp_c", "op": ">", "value": 70.0 },
    "reason":    "Heatsink too hot; cooldown required before continuing."
  }
}
```

**LabVIEW:** condition check; on true, emit `event/run-aborted` with
the reason and return ABORTED to the Sequencer.

---

## 3. Composite step types (4)

Composite step types contain `inner_steps`. The schema is recursive —
inner steps validate against the same envelope as top-level steps,
which means composites can nest other composites.

### 3.1 `repeat` — N iterations

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "tmf:recipe:step_types/repeat/params",
  "type": "object",
  "required": ["iterations", "inner_steps"],
  "additionalProperties": false,
  "properties": {
    "iterations":   { "type": "integer", "minimum": 1, "maximum": 1000000 },
    "stop_on_fail": { "type": "boolean", "default": true,
                      "description": "Stop the repeat loop if any inner step fails." },
    "inner_steps": {
      "type": "array", "minItems": 1,
      "items": { "$ref": "tmf:recipe:_common/envelope" }
    }
  }
}
```

**Example:**
```json
{
  "step_id":   "thermal_cycle",
  "step_type": "repeat",
  "params":    {
    "iterations":   100,
    "stop_on_fail": false,
    "inner_steps":  [ /* cycle steps */ ]
  }
}
```

**LabVIEW:** For Loop wrapping the inner-step dispatcher. Per-iteration
results aggregated into a sub-record under the parent step_id.

---

### 3.2 `sweep` — parameter sweep

Iterate a parameter across either an explicit list of values or a
linear range, running `inner_steps` once per value. The current value
is injected into the run context as `${sweep.<variable_name>}` and is
also written to the named variable at the start of each iteration.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "tmf:recipe:step_types/sweep/params",
  "type": "object",
  "required": ["variable", "inner_steps"],
  "additionalProperties": false,
  "properties": {
    "variable":     { "type": "string" },
    "values":       { "type": "array", "items": { "type": "number" }, "minItems": 1 },
    "range": {
      "type": "object",
      "additionalProperties": false,
      "required": ["start", "end", "step"],
      "properties": {
        "start": { "type": "number" },
        "end":   { "type": "number" },
        "step":  { "type": "number", "exclusiveMinimum": 0 }
      }
    },
    "stop_on_fail": { "type": "boolean", "default": true },
    "inner_steps": {
      "type": "array", "minItems": 1,
      "items": { "$ref": "tmf:recipe:_common/envelope" }
    }
  },
  "oneOf": [ { "required": ["values"] }, { "required": ["range"] } ]
}
```

**Example:**
```json
{
  "step_id":   "voltage_sweep",
  "step_type": "sweep",
  "params":    {
    "variable":    "dc_bus_setpoint",
    "range":       { "start": 200.0, "end": 320.0, "step": 20.0 },
    "inner_steps": [
      { "step_id": "settle", "step_type": "wait", "params": { "duration_ms": 500 } },
      { "step_id": "check",  "step_type": "measure_and_compare",
        "params": { "variable": "output_current",
                    "limits": { "min": -0.5, "max": 50.0 } } }
    ]
  }
}
```

**Semantic validation note:** the sweep range / values list must lie
within the target variable's clamping limits, or the recipe is
rejected at save (per `RECIPE.md` §7).

**LabVIEW:** For Loop with the swept variable written at iteration
start; inner-step dispatcher; results aggregated per value.

---

### 3.3 `if_then_else` — conditional branch

Evaluate a condition once, run one of two branches.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "tmf:recipe:step_types/if_then_else/params",
  "type": "object",
  "required": ["condition", "then_steps"],
  "additionalProperties": false,
  "properties": {
    "condition":  { "$ref": "tmf:recipe:_common/condition" },
    "then_steps": {
      "type": "array", "minItems": 1,
      "items": { "$ref": "tmf:recipe:_common/envelope" }
    },
    "else_steps": {
      "type": "array",
      "items": { "$ref": "tmf:recipe:_common/envelope" }
    }
  }
}
```

**Example:**
```json
{
  "step_id":   "if_three_phase",
  "step_type": "if_then_else",
  "params":    {
    "condition":  { "variable": "input_phase_count", "op": "==", "value": 3 },
    "then_steps": [ /* three-phase test sequence */ ],
    "else_steps": [ /* single-phase test sequence */ ]
  }
}
```

**LabVIEW:** evaluate condition; dispatch the chosen branch.

---

### 3.4 `group` — semantic grouping

Pure organizational container. Inner steps run sequentially. The
authoring UI uses `group` for collapsible sections; execution-wise it
is a no-op around its children.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "tmf:recipe:step_types/group/params",
  "type": "object",
  "required": ["inner_steps"],
  "additionalProperties": false,
  "properties": {
    "inner_steps": {
      "type": "array", "minItems": 1,
      "items": { "$ref": "tmf:recipe:_common/envelope" }
    }
  }
}
```

**Example:**
```json
{
  "step_id":   "phase_a_tests",
  "step_type": "group",
  "name":      "Phase A — bring-up",
  "params":    { "inner_steps": [ /* steps */ ] }
}
```

**LabVIEW:** run inner steps in order. Group result is the aggregate of
children (FAILED if any failed; PASSED otherwise).

---

## 4. Escape hatch (1)

### 4.1 `test_reference` — call a registered LabVIEW test class

The exit door from the primitives. When a measurement needs analysis a
primitive can't express (FFT, custom algorithm, multi-instrument
correlation), wrap it in a LabVIEW test class and reference it from
the recipe with this step type.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "tmf:recipe:step_types/test_reference/params",
  "type": "object",
  "required": ["test_class_id"],
  "additionalProperties": false,
  "properties": {
    "test_class_id": {
      "type": "string",
      "description": "Registered test class id; validated against the Sequencer registry at recipe save."
    },
    "parameters": {
      "type": "object",
      "description": "Free-form key→value passed verbatim to the test class. Constrained only by the test class's own input contract."
    },
    "limits": {
      "type": "object",
      "additionalProperties": { "$ref": "tmf:recipe:_common/limits" },
      "description": "Named limits the test class consumes."
    }
  }
}
```

**Example:**
```json
{
  "step_id":   "ripple_fft",
  "step_type": "test_reference",
  "name":      "FFT-based output ripple analysis",
  "params":    {
    "test_class_id": "RippleFFTAnalysis",
    "parameters":    { "window": "hann", "duration_s": 0.5, "channel": "ai0" },
    "limits":        {
      "fundamental_db": { "max": -40.0 },
      "second_harmonic_db": { "max": -55.0 }
    }
  }
}
```

**Cross-reference validation:** at recipe save, Python calls
`bridge.request("sequencer.list_test_classes")` to confirm
`test_class_id` is registered. The contract for what `parameters` and
`limits` shapes each test class accepts is owned by the test class
itself on the LabVIEW side; the Python schema cannot validate it
further.

**LabVIEW:** look up the test class in the Sequencer's registry;
construct an instance with `parameters`; run it; return its result.

---

## 4b. Simplified authoring (1)

### 4b.1 `parametric_test` — UI-authored flat parameter list

The recipe-authoring shape for **phase 1** of the Recipe UI. A test is a flat
list of `{ name, value, unit }` parameter rows — no step-type/schema picker. The
operator clicks **Add** to create one of these and fills the table. The richer
step-type catalog above is the **phase-2 sequence editor**; both persist as
ordinary steps, so validation/versioning/run-fetch are unchanged.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "tmf:recipe:step_types/parametric_test/params",
  "type": "object",
  "required": ["parameters"],
  "additionalProperties": false,
  "properties": {
    "parameters": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["name"],
        "additionalProperties": false,
        "properties": {
          "name":  { "type": "string", "minLength": 1 },
          "value": { "type": ["number", "string", "boolean", "null"] },
          "unit":  { "type": "string" }
        }
      }
    }
  }
}
```

**Example:**
```json
{
  "step_id":   "ovp_trip",
  "step_type": "parametric_test",
  "name":      "Over-voltage protection",
  "params":    { "parameters": [
    { "name": "Trip voltage", "value": 320.0, "unit": "V" },
    { "name": "Dwell",        "value": 100,   "unit": "ms" }
  ] }
}
```

**LabVIEW:** look up the test by `name`/`step_id`; consume the parameter rows by
name. (Interpretation of the rows is owned by the test bench, like
`test_reference`.)

---

## 5. The 15 starter types at a glance

| # | type_id | category | composite | Used most in |
|---|---|---|---|---|
| 1 | `set_output` | primitive | no | Type C |
| 2 | `measure` | primitive | no | Type C |
| 3 | `compare` | primitive | no | Type C |
| 4 | `measure_and_compare` | primitive | no | Type C |
| 5 | `ramp_until` | primitive | no | Type C |
| 6 | `wait` | primitive | no | All |
| 7 | `wait_until` | primitive | no | Type C |
| 8 | `prompt_operator` | primitive | no | All |
| 9 | `log_message` | primitive | no | All |
| 10 | `abort_if` | primitive | no | All (guards) |
| 11 | `repeat` | composite | yes | Type B |
| 12 | `sweep` | composite | yes | Type B |
| 13 | `if_then_else` | composite | yes | Mixed |
| 14 | `group` | composite | yes | Authoring UX |
| 15 | `test_reference` | escape | no | Type A |

Type A recipes are mostly `test_reference` + `prompt_operator` +
`log_message`. Type B recipes are `repeat` / `sweep` wrapping any
primitives. Type C recipes are the primitives. Any recipe can mix all
fifteen.

---

## 6. Adding a new step type

Same pattern as adding a new driver to the HAL.

1. Create `backend/modules/recipe/step_types/<type_id>/`.
2. Drop in `schema.json` (JSON Schema for `params`, referencing
   `_common/` where helpful).
3. Add `type.py` with the `@register_step_type(...)` decoration.
4. Add a handler sub-case to the Test Sequencer DQMH module's
   `Execute` request on the LabVIEW side.
5. Ship.

The Python registry walks the directory at startup, autodiscovers the
decoration, and the new type becomes visible on
`GET /recipes/step-types`. Authoring UIs render an editor for it from
the schema automatically — no UI code change required.

---

## 7. Notes on what is intentionally **not** in the catalog

These came up during design and were left out by choice.

- **`switch_case` / `switch_on_variable`** — covered by `if_then_else`
  composed; adding a switch construct invites operators to author
  branchy spaghetti recipes. Recommend authors compose `if_then_else`
  or split into multiple recipes.
- **`goto` / labels** — explicitly rejected. `on_fail: stop|continue|retry`
  + `abort_if` + `if_then_else` covers the cases; goto turns recipes
  into spaghetti and makes the LabVIEW dispatcher exponentially
  harder.
- **Embedded expression language** — the condition grammar in §1.2 is
  fixed: `variable op value`. No arithmetic, no boolean composition.
  If you need composite conditions, decompose into multiple steps with
  `abort_if`.
- **Inter-step dataflow beyond `measure`/`compare`** — the only
  cross-step state is a measurement store keyed by step_id (or
  `store_as`). No "step output → next step input" wiring. Anything
  more elaborate belongs in a `test_reference` step.

These are not permanent decisions — they're starter-set decisions.
Promote any of them to a real step type when there's a real-world
recipe that needs it; resist promoting them on the basis of "we
*might* need it."
