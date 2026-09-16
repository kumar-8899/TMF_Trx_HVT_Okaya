# Instrument drivers — Okaya HVT Testbench

This app is **self-contained** (TEMPLATE.md §1.2): every driver it uses lives under the fork's
own `instrument_libs/` (repo root) and nothing references the central `Instrument_Library` at
runtime. `controller.json` `library_paths` points at the fork root, `library_packages` is
`["instrument_libs"]`.

Cloned from `okaya_transformer` (TMF_Trx_Functional_Oakay) with the NI instrument (and
everything it alone backed — the motorised-Variac feedback/actuation subsystem, the
`variac_regulate` step type, and the `okaya_maintenance` manual-control module) excluded
entirely — this bench does not use it.

**`selec_mfm384` (the Selec MFM384 AC meter) was removed 2026-09** — this bench does not
measure input/winding AC voltage, current, or line frequency, and the signals that read it
(`input_voltage`, `no_load_current`, `winding_voltage1`, `winding_voltage2`, `line_frequency`)
are gone from `maps/st1.json`. If a general AC meter is needed again, author a fresh driver
against real hardware rather than reviving `selec_mfm384` from git history — it was never
hardware-verified.

## Drivers in this fork (`instrument_libs/`)

| Library id | File | Capabilities | Origin | Status |
|---|---|---|---|---|
| `waveshare_modbus_relay` | `digital_output/waveshare_modbus_relay.py` | digital_output, digital_input | **Authored here**, generalises the hardware-verified central `waveshare_8ch_relay_b` to N channels | One driver, **two physically separate 8-channel cards on this bench (2026-09, confirmed)**: `relay1` (the original card, sim complete + **real Modbus path verified live 2026-09** against `192.168.10.16:4196`, RTU-over-TCP, unit 1 — the driver defaults; TCP framing times out on this card; coil writes not yet exercised on hardware) and `relay2` (a second card dedicated to the tower-light stack — Red/Green/Buzzer only, no Yellow lamp on this bench; connection details (`host`/`port`/`unit_id`) and coil writes **not yet confirmed on hardware**). **TODO**: confirm coil map for both boards. |
| `meco_smp72` | `power_meter/meco_smp72.py` | analog_input | **Authored here** (no central driver existed) | Sim complete. Real path = Modbus register map — **TODO**. Not currently bound to any signal in `maps/st1.json` (orphaned, like `itech_it7300` below). |
| `itech_it7300` | `power_source/itech_it7300.py` | power_source | **Copied from** central `Instrument_Library` (`create-instrument-library`) | Present but **not yet wired to any instance** on this bench (carried over from the source app, where it was orphaned after a hardware revert). If this bench's new test sequence needs a programmable AC/HV source, this driver is the starting point — otherwise safe to delete. |
| `ut5320r` | `safety_tester/ut5320r.py` | safety_tester (non-scalar) | **Copied from** central `Instrument_Library` (`create-instrument-library`, 2026-09) | UNI-T UT5320R+ hipot/insulation tester. **Real VISA/SCPI path confirmed live 2026-09** on the bench (the manual's Modbus register map is read-only for step results and is NOT used — see "The hipot tester" below). Wired as the `hipot` action in `maps/st1.json`. IDN? string not yet pinned (`EXPECTED_IDN` left unset). |
| Modbus transport | `transports/modbus_tcp.py` | — | **Copied from** central `Instrument_Library`, **extended in-fork** (now upstreamed) | Grammar: R1/R2/R3 read, R4 (FC04 input reg), **R4F (FC04 2-reg IEEE-754 float32, `float_word_order`)**, W5 write coil. |
| VISA transport | `transports/visa.py` | — | **Copied verbatim** from central `Instrument_Library` | Used by `itech_it7300` (not yet wired, see above) and by `ut5320r` (wired as `hipot`, see above). |

### Why authored in the fork, not central
Scoped to this project and without the vendor Modbus register map for the MECO SMP, that meter
driver is a sim-complete skeleton. Recommend **upstreaming it to the central
`Instrument_Library`** (with a real register map, conformance-gated via
`create-instrument-library`) once hardware is available, then re-copying.

### Real-hardware status (`meco_smp72`)
`transports/modbus_tcp.py` has `R4` (FC04 read one input register) and `R4F` (FC04 read a
register pair, decoded as a 32-bit IEEE-754 float with a configurable `float_word_order`) on
top of the original R1/R2/R3/W5 grammar — everything `meco_smp72` would need for a real RMS-
voltage read is already in the shared transport; only the MECO SMP's own register map is
still TODO.

## Instrument instances to configure (Config → Instruments)

Instances are **not** in `controller.json` (v1.5.0+). Create these on the app's Instruments
page — the ids MUST match the `instance` names in `maps/st1.json` — each with its **Simulated**
toggle (leave ON until hardware is wired). These same instances are declared inline in
`tools/run_sim.py` for the headless run.

| id | library | key params | notes |
|---|---|---|---|
| `relay1` | `waveshare_modbus_relay` | `host`=`192.168.10.16`, `port`=4196, `unit_id`=1, `num_channels`=8, `framing`=`rtu` | Carries only the six `hipot_route_*` coil writes (Ch0-5); Ch6-7 unused. The digital I/O (push buttons, safety curtain, emergency) and `dimmer_output`/`w1_meas`/`w2_meas`/`w3_meas` coil writes that used to share this card were removed 2026-09 — see the note below. |
| `relay2` | `waveshare_modbus_relay` | `host`, `port`, `unit_id` — **unconfirmed**; `num_channels`=8 (confirmed) | Second 8ch relay card (2026-09, confirmed), dedicated to the tower-light stack: `tl_red` (Ch0), `tl_green` (Ch1), `buzzer` (Ch2) — only 3 of 8 channels used. This bench has **no Yellow tower light** (confirmed — no `tl_yellow` signal exists). |
| `meco` | `meco_smp72` | `host`, `unit_id` | Feedback-winding RMS voltage capability, but **not currently bound to any signal** in `maps/st1.json` — no `feedback_voltage`-style entry has been added yet. `sim_voltage` overrides sim reading. |
| `hipot` | `ut5320r` | `resource` (VISA, e.g. `ASRLn::INSTR` or `TCPIP0::<ip>::<port>::SOCKET` — confirm which this bench uses), `timeout_s`=65.0 | Insulation-resistance + AC-withstand, reached via the `hipot` action (`maps/st1.json`), never a scalar signal. Non-scalar (`capability.request`/`ctx.invoke`), so it has no `read`/`write` map entry. |

No `ni` instance — the NI instrument is excluded on this bench.

**`relay1`/`relay2` params must differ once real values are entered.** `InstrumentRegistry`
treats identical `{library, params}` as the same physical resource and refuses to start a
second instance id bound to it (`controller/controller/instruments/registry.py`
`_resource_key`) — this is the same class of startup-refusal as the `hipot` unconfigured-
instance failure already seen on this bench. Since `relay2`'s connection params are still
unconfirmed, make sure whatever is entered on Config → Instruments (host, port, and/or
`unit_id`) is distinct from `relay1`'s, not just a copy of it. `tools/run_sim.py` uses a
placeholder `unit_id` (1 vs 2) for exactly this reason.

## The hipot tester (`ut5320r`, action `hipot`)

Unlike the meters/relay, this instrument talks **VISA/SCPI**, not Modbus, even though the same
vendor manual documents both — the Modbus register map is read-only for step results (it can
only trigger a program someone already set up by hand on the front panel), while SCPI can both
program a step's voltage/dwell time AND trigger it, which is what `measure_ir(voltage, step)` /
`measure_acw(voltage, dwell, step)` need to actually honor their call arguments. Confirmed live
2026-09 that this bench's unit answers over VISA.

Per-call programming only sets what the `safety_tester` capability exposes (voltage, and for
ACW the dwell time); everything else on the targeted step (rise/fall time, current limits,
current range) is whatever is already programmed on the instrument — set up once from the front
panel or a `FILE:LOAD`, not from this driver. See the driver's module docstring
(`instrument_libs/safety_tester/ut5320r.py`) for the full SCPI command table and the FETCh?
sorting-result → `breakdown` mapping.

**`hipot_acw` step type (2026-09)**: `app/okaya_hvt/okaya_hvt_steps/hipot_acw/` drives
`ctx.invoke("hipot", "measure_acw", [voltage, test_time, step])` — same routing pattern as
`mux_measure`, six recipe steps sharing this one step type via `route`/`voltage`/`test_time`/
`max_current_ma`/`step`/`name` params, one per test point:

| # | Test point | `route` signal | Channel |
|---|---|---|---|
| 1 | Primary → Secondary | `hipot_route_pri_sec` | Ch0 |
| 2 | Primary → Core | `hipot_route_pri_core` | Ch1 |
| 3 | Secondary → Core | `hipot_route_sec_core` | Ch2 |
| 4 | Feedback → Core | `hipot_route_fb_core` | Ch3 |
| 5 | Primary → Feedback | `hipot_route_pri_fb` | Ch4 |
| 6 | Secondary → Feedback | `hipot_route_sec_fb` | Ch5 |

See `app/okaya_hvt/specs/hipot_acw.md` for the full procedure/parameter/measurement contract.

**Still open before running for real**:
- The VISA `resource` string and which tester program step(s) to use are unconfirmed — set on
  Config → Instruments once known.
- **The `hipot_route_*` channel collision is resolved.** `dimmer_output`/`w1_meas`/`w2_meas`/
  `w3_meas` and the digital-input signals (`push_button1`/`push_button2`/`safety_curtain`/
  `emergency`) were removed from `maps/st1.json` 2026-09 — `relay1` now carries only the six
  `hipot_route_*` coil writes (Ch0-5), so there is no remaining coil-address collision on that
  instance. (If the removed digital I/O is needed again later, e.g. a safety-curtain interlock
  read, it will need to be re-added deliberately with real, confirmed channel numbers — not
  revived as-is from git history, since the prior placement was never board-confirmed either.)
- **Starting/stopping the hipot test is not a variable-map signal.** The `safety_tester`
  capability is non-scalar by design (§ above) — `measure_ir`/`measure_acw` each issue the
  SCPI `TEST` command and poll `FETCh?` to completion internally as one blocking call
  (`ut5320r.py` `_run_and_fetch`), so there is no separate start/stop step for a recipe to
  drive. This was checked against the real legacy control software for this bench
  (`transformerTester_Okaya`, LabVIEW), whose `APIs Library\UNIT Hi-POT` does expose distinct
  `Function Start.vi` / `Function Stop.vi` — but that reflects its own sequencing (manual
  start, poll, manual stop/fetch as separate UI-driven steps), not a constraint imposed by the
  instrument itself. `safe_state()`/`emergency_disable()` already send `RESET` (SCPI `stop`)
  for abort/teardown, so an emergency stop path exists without a dedicated signal.
- The actual per-test-point acceptance numbers (voltage, dwell time, max leakage current) are
  the test engineer's / product spec's numbers, entered as recipe parameters when the six
  recipe steps are authored — not invented here. Once authored, each recipe group should get
  its own `specs/<group>.md` (spec-lint validates per recipe group, by group id) cloned from
  `hipot_acw.md` with the concrete route/limits filled in.
- No IR test type has been authored yet (`measure_ir` is implemented on the driver but unused
  by any step type on this bench).

## Variable map ↔ instance channel wiring (confirm against the panel)

- **No Variac / no NI**: `variac_voltage`, `variac_up`, `variac_down`, `input_w1`, `input_w2`,
  `input_w3` (all NI-backed on the source bench) are REMOVED from `maps/st1.json`. This bench's
  own voltage-application mechanism (if any) is not yet defined — author it (driver + map
  signals + step type as needed) once the new test sequence is known.
- **Two 8-channel relay cards** (2026-09, confirmed): `relay1` carries only the six
  `hipot_route_*` routes (Ch0-5; Ch6-7 unused); `relay2` carries only the tower-light stack
  (`tl_red` ch0, `tl_green` ch1, `buzzer` ch2 — no Yellow lamp on this bench). `relay2`'s
  connection params are unconfirmed (see the instances table above). The source bench's
  placeholder `R1→0 … R18→17, K2→18` silkscreen mapping does not apply here — this bench's
  actual relay1 channel assignments are the ones in `maps/st1.json` above, not that larger
  legacy numbering.
- **Digital I/O removed** (2026-09): `push_button1`, `push_button2`, `safety_curtain`,
  `emergency` (digital inputs) and `dimmer_output`, `w1_meas`, `w2_meas`, `w3_meas` (coil
  writes) were all dropped from `maps/st1.json` — none of them were bound to any step type or
  used by any recipe on this bench. If any are needed again (the safety-curtain/emergency reads
  in particular are worth revisiting before live HV testing), re-add them with confirmed real
  channel numbers.
- **No AC meter currently wired**: `selec_mfm384` (input/winding voltage, current, line
  frequency) was removed 2026-09 along with the signals it fed. `meco_smp72`'s `read_voltage`
  still accepts a `context` string (its own multi-window convention) but nothing in
  `maps/st1.json` binds it yet — add a signal here if/when a feedback-voltage measurement is
  needed.
