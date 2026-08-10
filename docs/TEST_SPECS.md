# Test specs — literate test authoring (the `.md` is the source of truth)

A test authored for the Python controller ships **two** things that must agree: the code
(`handler.py` + `schema.json`, or core step data in the recipe) and a **human-readable
procedure spec** at `app/<name>/specs/<test>.md`. The spec is what a non-programmer reads to
understand the test, and edits to change it. `spec-lint` (`controller/controller/speclint.py`)
is the deterministic gate that keeps the two in sync.

## Why
An AI-authored Python test is a black box to someone who can't read Python. The spec makes the
procedure, delays, input parameters, and output measurements legible — and, because `spec-lint`
fails the build when code and spec disagree, the spec stays trustworthy instead of rotting.

## The format
One `.md` per test in `app/<name>/specs/`, plus `specs/index.md` listing them in sequence
order. Template: [`docs/templates/test-spec.md`](templates/test-spec.md). YAML front-matter +
three tables are the machine-checked **contract**; the prose (Purpose, Procedure, Complex calls,
Simulation) is human context.

| Spec section | Checked against |
|---|---|
| front-matter `test` | a top-level `group` id in the recipe (the test) |
| Input — recipe parameters | authored: the step type's `schema.json` `properties` (both ways) |
| Output — report measurements | the measurement names the step emits in a sim run |
| Signals / actions | authored: `required_signals`/`required_actions` (+ the `action` param); core: `measure_and_compare`/`set_output` signals, which must exist in the variable map |

## The round-trip loop (spec is source of truth)
1. **Author** — describe the test in plain language; the AI writes `specs/<test>.md` (Purpose +
   Procedure from you) alongside the handler/schema/sim, filling the tables from what it wrote.
2. **Edit** — change the `.md` (a limit, a delay, a procedure step, a parameter).
3. **Revalidate** — run `spec-lint`; it reports drift; the AI reconciles the **code to the spec**
   (never the reverse), re-runs `run_sim`, and spec-lint goes green.

## Running it
- Per app: `python app/<name>/tools/spec_lint.py` — prints in-sync / drift; `run_sim.py` also
  prints a spec-lint summary. `app/<name>/tests/test_specs.py` asserts no drift (fails CI on drift).
- The checker is framework code; each app wires its config (recipe + map + a sim run to collect
  emitted measurement names) into `controller.speclint.check_specs`.

Authoring is driven by the `test-step-authoring` / `add-bench-test` skills, which produce and
maintain these specs.
