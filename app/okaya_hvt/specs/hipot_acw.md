---
test: hipot_acw
type: hipot_acw
kind: authored
spec_source: "Okaya HVT bench — test engineer request 2026-09; instrument dialect from the UNI-T UT5300X+/UT5320R-SxA Hipot Tester Programming Manual (SCPI&MODBUS RTU) REV.1.0"
---
# Hipot AC withstand (multiplexed)

## Purpose
Apply an AC withstand (hipot) test between two points of the transformer under test and
confirm the leakage current stays under the acceptance limit, with no dielectric breakdown
(arc, short, ground fault, or overvoltage trip) during the test. One shared UT5320R+ tester
covers every test point on the bench; the Waveshare relay card selects which pair of points is
connected before each test.

This is a **common step type** — the same handler runs each of the six physical test points
below, one recipe step per point, differing only in which relays are energised (`route`) and
the recorded measurement name.

| # | Test point | Relay route (channel) |
|---|---|---|
| 1 | Primary → Secondary | `hipot_route_pri_sec` (Ch0) |
| 2 | Primary → Core | `hipot_route_pri_core` (Ch1) |
| 3 | Secondary → Core | `hipot_route_sec_core` (Ch2) |
| 4 | Feedback → Core | `hipot_route_fb_core` (Ch3) |
| 5 | Primary → Feedback | `hipot_route_pri_fb` (Ch4) |
| 6 | Secondary → Feedback | `hipot_route_sec_fb` (Ch5) |

**Channel numbering is still unconfirmed against the real board** — `relay1` now carries only
these six routes (Ch0-5; the digital I/O and `dimmer_output`/`w1_meas`/`w2_meas`/`w3_meas`
coil writes that used to share it were removed 2026-09, so there's no coil-address collision
left, just the numbering itself to confirm). Confirm the real board wiring before running any
of these six against live hardware (see `maps/st1.json`'s `//relay_modules` note and
`INSTRUMENT_DRIVERS.md`).

## Procedure
1. Energise every relay signal named in `route` (closes the routing path for this test point).
2. Wait `settle_s` for the relays to settle.
3. Invoke the hipot tester's AC-withstand test (`measure_acw`) at `voltage` for `test_time`,
   on the tester's program `step`. The tester's own rise/fall time and current range are
   whatever is already configured on that step — this step type only sets type, voltage, and
   dwell time per call.
4. Hold the route closed for at least `test_time + off_margin_s` from the moment the tester was
   invoked, even if the tester's result posted earlier (or the call failed) — the tester may
   still be ramping HV down, and the relays must never hot-switch.
5. Always de-energise every `route` relay again, whether step 3 succeeded, failed, or the run
   was aborted (r3/safety — a DUT tap is never left connected to a live HV output), then wait
   `settle_off_s`.
6. Record ONE measurement — the leakage current (mA) — and judge it. **A failed test is always a
   visible FAIL row, never a missing one** (this step does not raise for a test failure):
   - leakage above `max_current_ma` → the reading, FAIL;
   - the tester reports a dielectric breakdown → the reading, FAIL (asserted explicitly, so a low
     reading cannot mask it); the step message says "dielectric breakdown reported by tester";
   - the tester call fails or returns a malformed reply → value `ERROR`, FAIL (a non-numeric
     value against numeric limits is a FAIL by the framework's rule); the error text is in the
     step message and a `hipot_acw.measure_failed` diag event.
   Only an operator abort propagates (it is not a test outcome).

## Timing / delays
| after | wait (s) | why |
|---|---|---|
| relay route closes | `settle_s` (default 1.0) | relay operate time before applying HV |
| tester TEST starts | `test_time` (recipe param) | the programmed AC withstand dwell |
| tester invoked | floor of `test_time + off_margin_s` (default margin 4.0) | closed-route time never shorter than the dwell + the tester's HV fall time |
| relay route opens | `settle_off_s` (default 2.0) | relays settle open before the result is validated/displayed |

## Input — recipe parameters
| param | meaning | default | limits |
|---|---|---|---|
| route | Relay signals to energise before the test | `[]` | — |
| action | Variable-map action bound to `safety_tester` | `hipot` | — |
| step | Tester program step to program and run | `1` | 1–20 |
| voltage | AC withstand test voltage (V RMS) | — | 50–5000 |
| test_time | Test (dwell) time (s) | — | ≥ 0.1 |
| max_current_ma | Max acceptable leakage current (mA) | — | ≥ 0 |
| settle_s | Dwell after closing the route before the test | `1.0` | ≥ 0 |
| settle_off_s | Dwell after opening the route before the result is validated | `2.0` | ≥ 0 |
| off_margin_s | Extra time past `test_time` the route is held closed | `4.0` | ≥ 0 |
| name | Measurement name (the recipe form passes the test point's human label, e.g. "Primary to Secondary", which is what the Results table and reports show) | `leakage_current` | — |

## Output — report measurements
| measurement | unit | judged? | limit source |
|---|---|---|---|
| `<name>` (default `leakage_current`) | mA | yes | params.max_current_ma — and always FAIL on a reported breakdown or a tester error (see Procedure 6) |

## Signals / actions
| name | dir | via |
|---|---|---|
| `route` entries (e.g. `hipot_route_pri_sec`) | write | relay energise/de-energise |
| `hipot` (or `action` param) | action | `ctx.invoke measure_acw` |

## Complex calls
`ctx.invoke(action, "measure_acw", [voltage, test_time, step])` programs the tester's step
type/voltage/dwell over VISA/SCPI and polls internally until that step reports a result — the
handler makes one blocking call; it does not poll itself (the wait is inside the driver).
`measure_acw` returns `(leakage_ma, breakdown)`; `breakdown` is True only for a genuine
dielectric-fault sorting result (SHORT/ARC/GFI/VOLT ERR), not a plain over-limit leakage
reading, so a numerically-in-range leakage current cannot mask a real breakdown event.

## Simulation
The `ut5320r` driver's own sim (`instrument_libs/safety_tester/ut5320r.py`) returns a
plausible PASS reading (leakage well under a typical limit, no breakdown) for whichever mode
was last programmed (AC or IR) — there is no fixed absolute "good transformer" leakage figure
built into this step type or its tests, because `max_current_ma` (the actual pass/fail
threshold) is itself a recipe parameter, not a step-type constant; the real acceptance limits
for each of the six test points are the test engineer's / product spec's numbers, entered per
recipe step, not invented here. The step type's own tests
(`okaya_hvt_steps/hipot_acw/test_step.py`) instead exercise the routing/judgement/safety logic
against a scripted fake context: nominal PASS, excess-leakage FAIL, a breakdown-despite-low-
leakage FAIL (the second, distinct bad-DUT mode this step type exists to catch — returned as a
visible FAIL row carrying the reading), a leakage-exactly-at-the-limit boundary (passes —
inclusive), a non-responsive tester and a malformed reply (each a visible `ERROR` FAIL row; route
still opens and is still held closed for the full dwell margin), and an abort mid-settle or
mid-call (propagates; route still opens). The last group drives the REAL sequencer with a recipe
shaped like the recipe form's output to prove every test — including failures — reaches the
Results table under its human label, and that the recipe-level `stop_on_fail` skips only the
tests AFTER the first failure.

Run them with the build's import roots (the repo-root `controller/` folder would otherwise
shadow the real `controller` package):
`PYTHONPATH=<repo>/controller;<repo>/app/okaya_hvt;<repo>  python -m pytest app/okaya_hvt/okaya_hvt_steps`
(run from `app/okaya_hvt`). `app/` is not in the backend's default pytest paths, so CI does not
run these — run them by hand after touching the step type.
