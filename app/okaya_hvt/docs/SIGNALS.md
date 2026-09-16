# Signal dump — Okaya HVT Testbench

Full inventory of every signal/action currently in `maps/st1.json`, organized by instrument
instance, plus the hipot ACW reading and the start/stop question. This is a snapshot (2026-09);
`maps/st1.json` is the source of truth if the two ever drift.

**Source**: this bench was cloned from `okaya_transformer` (`TMF_Trx_Functional_Oakay`,
`app/okaya_transformer/maps/st1.json`), which had ONE `relay` instance carrying every
tower-light + measurement-mux signal. Cross-checked against the real production control
software for this Okaya bench family, `transformerTester_Okaya` (LabVIEW,
`D:\Repositories\transformerTester_Okaya`):
- `Configuration/Instrument Configuration/Instr Config.ini` confirms the real hardware
  architecture is **two separate Modbus relay cards** (`Modbus Relay Card 1` /
  `Modbus Relay Card 2`, distinct IPs) plus a separate `HV_Tester` and `MFM` — matching this
  bench's `relay1`/`relay2` split, not the single-`relay` map it was cloned from. Its IPs are on
  a different subnet (`192.168.0.x`) than this bench's already-verified-live `relay1`
  (`192.168.10.16:4196`) — **not assumed to apply here**, listed only as a lead if `relay2`'s
  real address is ever sourced from that same network plan.
- `Configuration/Recipe/001.json`'s `"Hi-Pot Tests"` block confirms **exactly six** hipot test
  points (Winding-to-winding, Primary→Feedback, Secondary→Feedback, Primary-winding→Core,
  Secondary-winding→Core, Feedback-winding→Core) — matching this bench's six `hipot_acw` recipe
  steps, not eight. It also carries a fourth parameter, `Min Current(mA)`, that this bench's
  recipe form does not currently expose (only Voltage/Test Time/Max Current) — noted here, not
  added, since the form's three params were specified explicitly and adding a fourth is a
  product decision, not an inference.
- `APIs Library\UNIT Hi-POT` has separate `Function Start.vi` / `Function Stop.vi` — see
  "Starting/stopping the hipot" below.

## `relay1` (8 channels, confirmed) — hipot routes only

Real Modbus path verified live 2026-09 against `192.168.10.16:4196` (RTU-over-TCP, unit 1).

| signal | dir | channel | notes |
|---|---|---|---|
| `hipot_route_pri_sec` | write (coil) | 0 | hipot test 1/6 — Primary → Secondary |
| `hipot_route_pri_core` | write (coil) | 1 | hipot test 2/6 — Primary → Core |
| `hipot_route_sec_core` | write (coil) | 2 | hipot test 3/6 — Secondary → Core |
| `hipot_route_fb_core` | write (coil) | 3 | hipot test 4/6 — Feedback → Core |
| `hipot_route_pri_fb` | write (coil) | 4 | hipot test 5/6 — Primary → Feedback |
| `hipot_route_sec_fb` | write (coil) | 5 | hipot test 6/6 — Secondary → Feedback |

Only 6 of 8 channels used (6-7 unused). **Removed 2026-09**: `push_button1`/`push_button2`
(digital_input), `safety_curtain`/`emergency` (digital_input), and `dimmer_output`/`w1_meas`/
`w2_meas`/`w3_meas` (coil writes) — none were bound to any step type or recipe on this bench.
Removing them also cleared the coil-address collision that used to exist between
`dimmer_output`(ch4)/`w1_meas`(ch5) and `hipot_route_pri_fb`/`hipot_route_sec_fb` on this same
card. If any of the removed signals are needed again (the safety-curtain/emergency reads in
particular, before live HV testing), re-add them with real, board-confirmed channel numbers.

## `relay2` (8 channels, confirmed) — tower-light stack

Second, physically separate card (2026-09). Connection params (`host`/`port`/`unit_id`) are
still unconfirmed — only the channel assignments are. Only 3 of 8 channels are used.

| signal | dir | channel | notes |
|---|---|---|---|
| `tl_red` | write (coil) | 0 | |
| `tl_green` | write (coil) | 1 | |
| `buzzer` | write (coil) | 2 | |

**No Yellow tower light on this bench** (confirmed) — there is no `tl_yellow` signal, unlike the
source `okaya_transformer` map this bench was cloned from, which had one on `relay` ch1.

## `hipot` (action, non-scalar) — UT5320R+ safety_tester

Not a `signals` entry — reached only through the `hipot` action
(`"actions": {"hipot": {"instance": "hipot", "capability": "safety_tester"}}`), per the
`safety_tester` capability's non-scalar contract (`INSTRUMENT_LIBRARY.md`).

| call | returns | used by |
|---|---|---|
| `measure_acw(voltage, dwell, step)` | `(leakage_ma, breakdown)` — **the hipot ACW reading** | `hipot_acw` step type, all six test points |
| `measure_ir(voltage, step)` | insulation resistance (MΩ) | implemented on the driver, not yet used by any step type on this bench |

**The hipot ACW reading** is `leakage_ma` (mA) + `breakdown` (bool), both returned by one
`measure_acw` call and both judged by the `hipot_acw` step type as the `<name>` and
`<name>_breakdown` measurements (default name `leakage_current`) — there is no separate scalar
signal for it; the reading only exists as the return value of that action call, recorded as a
report measurement each time a hipot test step runs.

### Starting/stopping the hipot — checked, not a signal

Checked whether "start hipot" / "stop hipot" should be their own variable-map signals. **No** —
kept as-is (not added as signals), for two reasons:
1. The `safety_tester` capability is non-scalar by design — there is no `read`/`write` slot for
   it to bind to.
2. `measure_acw`/`measure_ir` already issue the SCPI `TEST` command and poll `FETCh?` to
   completion internally as one blocking call (`ut5320r.py` `_run_and_fetch`) — there's no gap
   between "start" and "stop" for a recipe step to drive separately.

The real legacy LabVIEW software (`transformerTester_Okaya\APIs Library\UNIT Hi-POT`) does have
distinct `Function Start.vi` / `Function Stop.vi` — that's why this was worth checking — but
that reflects its own manual/UI-driven sequencing (operator or state-machine-triggered start,
separate poll, separate stop/fetch), not a hardware requirement. This driver's single blocking
call already covers the same ground. An emergency-stop path exists independently of this:
`safe_state()`/`emergency_disable()` send SCPI `RESET` (the `stop` command) and are wired into
the framework's abort/teardown handling regardless of what a step type does.

## Recap — six hipot_acw steps, not eight

The `hipot_acw` step type has **six** recipe steps (one per physical test point above), each a
separate `{id, type: "hipot_acw", params}` entry sharing the one step type. (`test_step.py` has
8 unit test *functions* covering PASS/FAIL/boundary/error/abort scenarios for that one step
type — a different count, for a different thing; don't conflate the two.)
