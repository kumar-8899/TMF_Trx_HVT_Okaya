---
name: add-bench-test
description: Guided workflow to add or build a test (or a whole test sequence) IN AN EXISTING forked test application on the Super_Test_App framework, in the correct dependency order — instrument driver → variable map → step type (params) → recipe → verify. Use when the user wants to add/implement/wire a new test, measurement, or test sequence into an app they already have, extend a bench, "make the bench test X", turn a described measurement into a runnable recipe step, or asks "how do I add a test / what's the order". It orchestrates the create-instrument-library and test-step-authoring skills and the map/recipe data authoring, enforcing that each layer is the contract for the next. Do NOT use to fork a brand-new app (use new-test-app) — this works inside an app that already exists.
---

# Add a bench test (the development workflow)

Take a described test — or a full sequence — and build it correctly through the framework's
dependency chain in an **existing** app (already forked with `new-test-app`). The one rule
that orders everything:

> Each layer is the **contract** for the next. A recipe can only set params a step type
> declared; a step can only use signals the variable map defined; the map can only bind
> capabilities the driver has. So build **bottom-up**, and verify each layer before the next.

```
instrument driver (capabilities) → variable map (named signals/actions)
    → step type (its schema = the configurable params) → recipe (param values + limits) → run
```

App-owned locations (TEMPLATE.md §1.1–§1.2): drivers in `instrument_libs/` (fork root),
everything else under `app/<name>/` (`maps/`, `<name>_steps/`, `recipes/`, `controller.json`,
`tools/`, `tests/`).

---

## Step 0 — Pin the spec (do not build until answered)

For each test: what it drives/reads, the pass/fail logic, and the **limits + parameters from
the product spec — never invented** (see the circular-check rule in `test-step-authoring`).
List the instruments touched and the named I/O lines. This spec drives every layer below.

Decide per test: is it **generic** (drive an output, settle, read one signal, compare a
window) → core step types, no code; or **product-specific** (non-scalar instrument, multi-read
choreography, custom judgement) → an app step type.

---

## Layer 1 — Instrument driver (capabilities)

For each instrument the test uses:
- Driver already in the fork's `instrument_libs/`? → done.
- In central `Instrument_Library` but not copied? → copy it in (see the app's
  `docs/INSTRUMENT_DRIVERS.md`); import its category in `instrument_libs/__init__.py`.
- Missing entirely? → author it with the **`create-instrument-library`** skill (into central,
  conformance-gated), then copy it in.

**Gate:** `import instrument_libs` registers the driver; its capability exposes the read/write
methods the test needs. A capability newer than the fork's framework version won't register —
fork a newer framework release.

---

## Layer 2 — Variable map (`maps/<station>.json`)

For every named line/measurement the test uses, add a binding:
- **signal** → `{instance, read|write, args, scale?, clamp?, units?}` (scalar: read =
  raw·gain+offset, write = clamp→inverse-scale).
- **action** → `{instance, capability}` (non-scalar; reached via `ctx.invoke`).
Same names across identical stations. Shared analog input read into several windows? pass a
**context** string as an extra read arg and have the (sim) driver key its value off it.

**Gate:** the signal/action resolves — a quick `StationVariables.read/write/invoke` (or the
`run_sim` harness) returns a value without "unknown signal/action".

---

## Layer 3 — Step type (this defines the configurable params)

- **Generic test** → compose from the **core 8** (`set_output`, `measure_and_compare`, `wait`,
  `group`, `repeat`, `sweep`, `if`, `prompt_operator`). No code — the params (signal, limits,
  value, seconds…) are the core step's own schema.
- **Product-specific test** → **`test-step-authoring`** skill → a step type in
  `app/<name>/<name>_steps/`. Its **`schema.json` IS the parameter contract** (what a recipe
  may configure — "anything an engineer changes without changing the test is a param"). Declare
  `required_signals`/`required_actions`. Handler touches hardware only via `ctx`
  (`read/write/invoke`); the **sequencer computes the verdict** from Measurements.

**Gate:** the step type registers, passes conformance (`validate_app_step_types`), and a
one-step `dry_run` resolves its names against the map. **Only now can a recipe reference it —
this is why steps precede recipes.**

---

## Layer 4 — Recipe (`recipes/*.json`) — data

Author the sequence: an ordered list of `{type, id, params}` steps (a `group` per test),
filling each step's **params + limits from the spec**, referencing only the step types + signals
built above. This is data — no code.

**Gate:** `dry_run` → `DRY_RUN_PASS` (every step type registered, every name resolves), then
`run_sim` → the intended `VERDICT`, with a deliberately out-of-window value proving FAIL.

---

## Layer 4.5 — Test spec (`app/<name>/specs/<test>.md`) — the human source of truth

For **every** test in the sequence (authored step type OR core-only), write/refresh a procedure
spec so an engineer who can't read Python still understands and can edit it. Structured
front-matter + tables (Input params ↔ schema, Output measurements ↔ what runs, Signals/actions);
prose Procedure/Timing/Simulation. Template `docs/templates/test-spec.md`, format
`docs/TEST_SPECS.md`. The spec is **authoritative**: when the engineer edits the `.md`, reconcile
the code/recipe to it (never the reverse), then re-run spec-lint.

**Gate:** `python app/<name>/tools/spec_lint.py` → **all specs in sync** (input↔schema,
output↔sim measurements, signals↔map/registration). Drift = fix before shipping.

---

## Layer 5 — Verify end to end

- `python app/<name>/tools/run_sim.py` — in-process, prints each measurement + verdict.
- `python -m pytest app/<name>/tests -q` — lock it (pass + a negative case).
- Over the controller/MQTT (broker up): the app auto-starts the Python controller with this
  config; fire the run and tail the events.

**Recipe-UI note:** starting a recipe that uses **app** step types from the Runs screen needs
the recipe-module ↔ controller step-type registries unified (a framework task). Until then the
verified path is `run_sim`/MQTT; core-only recipes can already be authored in the UI.

---

## Order-of-operations checklist

- [ ] Spec + limits pinned (from the product spec, not invented)
- [ ] Driver present/registers for every instrument the test touches
- [ ] Variable map has every signal/action the test uses — and it resolves
- [ ] Step type exists (core, or authored) and its **schema declares the params** — verified before writing the recipe
- [ ] Recipe fills params + limits against those schemas — `dry_run` PASS
- [ ] `run_sim` gives the intended verdict; a negative case FAILs
- [ ] `specs/<test>.md` written for every test; `spec_lint.py` green (spec↔code in sync)
- [ ] Only app-owned paths touched (TEMPLATE.md §1)
