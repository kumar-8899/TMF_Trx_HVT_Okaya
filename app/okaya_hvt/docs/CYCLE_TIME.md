# Hipot cycle time — breakdown & optimization (measured)

**Question:** a 5 s HV test takes ~12 s per step. Where does the time go, and what can we cut?

Measured live on the site tester (**UNI-T UT5310R+, REV A9.2**, SCPI over TCP socket
`TCPIP::192.168.32.121::502::SOCKET`) at the **real site settings: 2.5 kV, 5 s**, open output
(no relay cards connected — contactor times are *assumed*, flagged below).

## What the tester actually does (2.5 kV / 5 s), measured

Captured by polling `FETCh?` and reading live kV from `TEST` (t=0):

| Phase | Measured | Notes |
|-------|----------|-------|
| Programming (TYPE/VOLT/TTIM/UPPC/RANG + 2 drains) | ~0.2 s | sends are sub-ms on this LAN; two 50 ms buffer drains dominate |
| Rise 0 → 2.5 kV | ~1.0 s | 95 % by 0.77 s (~3000 V/s) |
| Dwell at 2.5 kV | ~5.1 s | the programmed `test_time` |
| Fall 2.5 kV → ~0 | ~0.7 s | voltage collapsing by t≈6.1–6.8 s |
| **PASS result posts** | **t ≈ 6.9 s** | **AFTER the fall — HV is already safe when `measure_acw` returns** |

**`measure_acw` end-to-end ≈ 7.1 s** (0.2 programming + ~6.9 instrument). The ~5 s "test" is
really rise (~1.0) + dwell (~5.1) + fall (~0.7) ≈ **6.9 s of unavoidable instrument time**.

**Key finding:** this unit posts its sorting result *after* the HV has ramped down, so the moment
`measure_acw` returns the output is already safe. The original reason for a 4 s `off_margin_s`
("the result can post *before* the fall") does **not** hold here.

## Full one-step cycle (measured tester + assumed contactors)

| # | Phase | Time | Source |
|---|-------|------|--------|
| 1 | Relay interlock (`open_all_verified`) | ~0.6 s | `verify_settle_s` 0.3 + ~16 Modbus round-trips *(assumed — no relay card connected)* |
| 2 | Route close + settle | 1.0 s | `settle_s` 1.0 *(assumed contactor pull-in)* |
| 3 | HV test window (floored) | 9.0 s | `max(measure_acw ≈7.1, test_time+off_margin_s = 5+4 = 9.0)` → **floor wins, ~1.9 s pure pad** |
| 4 | Route open + dead-time | 2.0 s | `settle_off_s` 2.0 *(assumed contactor drop-out)* |
| | **Total** | **≈ 12.6 s** | matches the observed ~12 s |

So of the ~12.6 s: **~6.9 s is real test physics** (rise+dwell+fall, irreducible), **~1.9 s is
`off_margin_s` pad waiting after the HV is already down** (pure waste on this unit), and **~3.6 s
is contactor settle/dead-time + interlock** (assumed).

## Optimization — with the measured numbers

| Lever | Now | → | Saves/step | Basis |
|-------|-----|---|-----------|-------|
| `off_margin_s` | 4.0 s | **2.0 s** | **~2.0 s** | Measured: result posts after fall, so `measure_acw` already waits for safe. 2.0 still covers the **error path** (if the call drops mid-test, the floor must out-last the tester's autonomous rise+dwell+fall ≈ 6.9 s from t0 → `test_time`+2.0 = 7.0 s ✓). Don't go below ~2.0. |
| `settle_off_s` | 2.0 s | **1.0 s** | ~1.0 s | Assumed contactor drop-out. HV is already off by here, so this only guards contactor mechanical open before the next route. Verify against the real contactor. |
| `settle_s` | 1.0 s | **0.5 s** | ~0.5 s | Assumed contactor pull-in (~tens of ms); 0.5 s stays safe for a hot-close guard. |
| `verify_settle_s` | 0.3 s | **0.15 s** | ~0.15 s | Coil register updates fast. |

**Optimized one-step ≈ 9.0 s** (0.45 interlock + 0.5 settle + ~7.0 test window + 1.0 dead-time),
down from ~12.6 s — **~3.6 s/step, ~22 s across a 6-point recipe.**

The remaining ~7 s is the tester's own rise + 5 s dwell + fall; it can't be cut in software
without changing the test spec (shorter dwell) or the tester's ramp.

## What's firm vs. assumed

- **Firm (measured on the real tester):** rise ~1.0 s, dwell ~5.1 s, fall ~0.7 s, result posts
  after fall at ~6.9 s, programming ~0.2 s, `measure_acw` ~7.1 s. → `off_margin_s` can safely drop
  to **2.0 s**.
- **Assumed (no relay cards connected):** `settle_s`, `settle_off_s`, interlock I/O. The proposed
  0.5 / 1.0 s are conservative vs. typical contactor pull-in/drop-out (~20–50 ms) but should be
  confirmed against the real contactors (especially drop-out — the earlier two-contactors-on fault
  showed real mechanical lag).

## How to tune these on the live machine

The four settle times are read from a plain JSON file you hand-edit on the client — **not** the UI,
**not** a recipe (so no content-hash mismatch), one global set for **all models**:

    <install>\config\hipot_timing.json        (next to app.json)

```json
{
  "off_margin_s": 2.0,
  "settle_off_s": 1.0,
  "settle_s": 0.5,
  "verify_settle_s": 0.15
}
```

- **Survives app updates** — the `config\` folder is preserved across an update swap, so your values
  never reset.
- **Live** — edit the file and run the next test; the new values apply (no restart). Precedence:
  an explicit recipe param > this file > the built-in default.
- **Safe** — a missing or invalid file (or a single bad value) falls back to the built-in defaults
  (`off_margin_s` 4.0 / `settle_off_s` 2.0 / `settle_s` 1.0 / `verify_settle_s` 0.3); it can never
  break a run.
- Seed it with `app\okaya_hvt\tools\install_hipot_timing.ps1` (copies the optimized example into
  `config\`, won't overwrite an edited file), or just create the file by hand.

| Param | Built-in default | Example (optimized) | Basis |
|-------|------------------|---------------------|-------|
| `off_margin_s` | 4.0 | **2.0** | data-backed; covers error-path rise+fall |
| `settle_off_s` | 2.0 | **1.0** | assumed contactor drop-out; confirm on real cards |
| `settle_s` | 1.0 | **0.5** | assumed pull-in; low risk |
| `verify_settle_s` | 0.3 | **0.15** | low risk |
