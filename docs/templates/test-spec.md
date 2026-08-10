---
test: <group id in the recipe, e.g. ir>
type: <step type, e.g. hipot_ir; a core-only test uses the core type e.g. measure_and_compare>
kind: <authored | core>       # authored = has a handler.py; core = composed from the core 8
spec_source: "<product spec / instrument manual section the numbers come from>"
---
# <Human title of the test>

## Purpose
Plain language — what this test checks on the DUT, and why.

## Procedure
1. <numbered algorithm — the human-editable source of truth>
2. <drive an output / settle / read a signal / compare>
3. ...

## Timing / delays
| after | wait (s) | why |
|---|---|---|
| <step> | <seconds> | <reason the delay exists> |

## Input — recipe parameters
<!-- One row per configurable parameter. Names MUST match the step type's schema.json
     properties (authored) — spec-lint checks this both ways. -->
| param | meaning | default | limits |
|---|---|---|---|
| <name> | <what it does> | <default> | <min–max / —> |

## Output — report measurements
<!-- One row per measured value the step emits. Names MUST match what the step produces
     at run time (spec-lint runs it in sim and compares). judged? = counts toward pass/fail. -->
| measurement | unit | judged? | limit source |
|---|---|---|---|
| <name> | <unit> | <yes/no> | <params.min / params.max / —> |

## Signals / actions
<!-- Named I/O the test uses. Authored: matches required_signals/required_actions (+ the
     `action` param). Core: the measure_and_compare/set_output signals, which must exist in
     the variable map. -->
| name | dir | via |
|---|---|---|
| <signal> | <read/write/action> | <how it's used> |

## Complex calls
Any non-scalar `ctx.invoke(...)` / choreography worth explaining in prose.

## Simulation
Behavioural numbers (from `spec_source`, never invented) + the failure modes the sim models.
