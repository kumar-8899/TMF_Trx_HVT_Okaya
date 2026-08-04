# relay_cycle

Cycle a relay a configured number of times and check its feedback contact on every cycle.
An example **application step type** for the Python Test Controller — it ships in an app
package (`demo_steps` here), not in the framework. Authored with the `test-step-authoring`
skill (`SKILL_STEP_TYPE.md`).

## What it does

For each of `cycles` iterations: energise the coil (`relay_coil` ← `on_value`), wait
`settle_s`, read `relay_feedback`, and record it as a measurement compared against
`[fb_min, fb_max]`; then release the coil (`relay_coil` ← `off_value`) and wait again. The
sequencer fails the step if any cycle's feedback is out of range — a degraded or open
contact.

## Signals (from the station variable map)

| Name | Direction | Units | Role |
|---|---|---|---|
| `relay_coil` | write | — | Drives the relay coil on/off. |
| `relay_feedback` | read | V | Contact-closed feedback line. |

## Parameters

| Parameter | Default | What changing it does |
|---|---|---|
| `cycles` | 500 | Number of energise/release cycles. Raise for endurance runs. |
| `on_value` / `off_value` | 1 / 0 | Values written to energise / release the coil. |
| `settle_s` | 0.05 | Dwell after each coil change before reading feedback (relay operate/release time). |
| `fb_min` / `fb_max` | — | Acceptable feedback window when closed. Outside it fails that cycle. |

## Measurements

| Name | Unit | Pass/fail? |
|---|---|---|
| `cycles_commanded` | count | INFO (context) |
| `contact_closed` (one per cycle, `sequence` 1..N) | V | yes — against `[fb_min, fb_max]` |

## Spec reference

Behavioural numbers in `simulate.py` are **placeholder examples**, not a datasheet. A real
package cites the relay datasheet (operate/release time, contact resistance) and gets the
numbers from the test engineer — see the circular-check note in `SKILL_STEP_TYPE.md`.

## Known limitations

- Reads feedback only while energised, so it catches a contact that fails to *make*; it does
  not detect a welded contact that fails to *release* (that needs an additional de-energised
  read — a candidate enhancement).
- One real DUT run is required before release; simulation proves the logic, not the assumptions.
