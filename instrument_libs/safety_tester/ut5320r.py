"""UNI-T UT5320R+ (UT5320R-SxA series) electrical-safety (hipot) tester — `safety_tester`
capability: insulation-resistance (measure_ir) and AC-withstand (measure_acw).

Wire dialect: VISA/SCPI (the manual documents RS232 and LAN; a VISA resource string works
uniformly through pyvisa either way). The same manual also documents a Modbus RTU register map
(read-only step results + a start/stop coil) — that path is deliberately NOT used here: it
cannot set a step's test voltage or AC dwell time (register 0x0100+ is read-only, and the manual
says "register only includes fetch test result and start/stop test... contact UNI-T" for
anything else), so it could only trigger a program someone already set up by hand on the front
panel. SCPI can both program AND trigger, which is what `measure_ir(voltage, ...)` /
`measure_acw(voltage, dwell, ...)` need in order to actually honor their arguments instead of
just hoping the front-panel program matches. CONFIRMED ON THE BENCH 2026-09: the unit answers
over VISA (SCPI); the Modbus path was not exercised.

Source: "UT5300X+ and UT5320R-SxA Series Hipot Tester Programming Manual (SCPI&MODBUS RTU)"
REV.1.0, Feb 2023, UNI-TREND TECHNOLOGY (China) Co., Ltd. — §1.5 FUNCtion (STEP/TYPE + per-mode
AC/DC/IR setpoints), §1.8 TEST, §1.9 RESET, §1.10 IDN?, §1.12 FETCh?.

Per-call programming — only what the capability interface actually exposes; everything else
(rise/fall time, current range, current limits, total step count) is whatever that step already
has, normally set up once from the front panel or FILE:LOAD:
    measure_ir(voltage, step):          FUNC:TYPE <step>,IR  ->  FUNC:IR:VOLT <step>,<voltage>
    measure_acw(voltage, dwell, step):  FUNC:TYPE <step>,AC  ->  FUNC:AC:VOLT <step>,<voltage>
                                         -> FUNC:AC:TTIM <step>,<dwell>
Then TEST starts the run and FETCh? is polled until that step's segment carries a sorting
result (5 comma-separated fields; 4 means the step hasn't finished — manual §1.12 "Additional
Notes"). FETCh? only answers from the <Measurement Display> page (§1.12 "Notice"), so
`connect()` sends `DISP:PAGE TEST` once, on real hardware only.

FETCh? sorting-result vocabulary (§1.12): PASS, SHORT, ARC, GFI, VOLT ERR, HI-Limit, LO-Limit,
Charge Lo, CK FAIL. `measure_acw`'s `breakdown` flag is True only for the dielectric-fault codes
{SHORT, ARC, GFI, VOLT ERR} — a genuine breakdown event during the withstand test, distinct from
a plain current-limit judgement (HI-Limit/LO-Limit) that the recipe/step-type layer already
re-derives itself from the returned leakage_mA against its own limits. Any other token (e.g.
CK FAIL turning up on an AC step) means our step-type assumption doesn't match what actually
ran on the instrument, and is surfaced as a structured error rather than guessed at (§4.4
error-not-value rule).

NOT verified by this authoring pass: the exact IDN? string this unit reports — the manual's own
worked example is an OEM-rebadged "HAOYI,UT5310,HIPOT TESTER,REV A1.5" (different manufacturer
field, sibling model), so `EXPECTED_IDN` is left unset (identity is logged via `identify()` but
never gated on reconnect) until confirmed live; pin it once known. The VISA `resource` string
(RS232 "ASRLn::INSTR" vs. a LAN "TCPIP0::<ip>::<port>::SOCKET") is a connection param — supply
whichever the bench actually uses.
"""

from __future__ import annotations

import asyncio

from instrumentlib import ISafetyTester, InstrumentBase, SimTransport
from instrumentlib.errors import DeviceError, GarbageResponse

from instrument_libs.transports import VisaTransport

# FETCh? sorting-result tokens that mean a genuine dielectric breakdown during AC withstand
# (manual §1.12) — as opposed to a plain over/under current-limit judgement, which the
# recipe/step-type layer re-derives itself from the returned leakage current. Frozen (§4.2):
# module-level constants only, never mutated.
_ACW_BREAKDOWN = frozenset({"SHORT", "ARC", "GFI", "VOLT ERR"})
_ACW_RESULTS = _ACW_BREAKDOWN | {"PASS", "HI-Limit", "LO-Limit"}
_IR_RESULTS = frozenset({"PASS", "HI-Limit", "LO-Limit", "Charge Lo"})

_POLL_S = 0.2


class Ut5320r(InstrumentBase, ISafetyTester):
    # No IDN? string confirmed live yet (see module docstring) — identity is reported, not gated.
    EXPECTED_IDN = None

    # UT5320R-SxA SCPI command table (Programming Manual REV.1.0) — the review surface.
    CMD = {
        "idn":       "IDN?",                       # §1.10 -> "<mfr>,<model>,<function>,<rev>"
        "disp_test": "DISP:PAGE TEST",              # §1.4 — FETCh? only answers from this page
        "set_type":  "FUNC:TYPE {step},{mode}",     # §1.5.6  mode in {AC,DC,IR,CK}
        "ir_volt":   "FUNC:IR:VOLT {step},{v}",     # §1.5.31  <int> 50-2500 V
        "ac_volt":   "FUNC:AC:VOLT {step},{v}",     # §1.5.7   <int> 50-5000 V
        "ac_ttim":   "FUNC:AC:TTIM {step},{t}",     # §1.5.8   <float> s, test (dwell) time
        "start":     "TEST",                        # §1.8  (== FUNC:STARt)
        "stop":      "RESET",                       # §1.9  (== FUNC:STOP) — also safe_state
        "fetch":     "FETCh?",                      # §1.12 -> "<step>,<mode>,<kV>,<mA|MΩ>[,<result>];…"
    }

    # Plausible sim responses (§3): IDN + an already-finished step-1 IR PASS so a sim run never
    # blocks polling for a result that will never arrive.
    _SIM = {
        "IDN?":  "UNI-T,UT5320R+,HIPOT TESTER,SIM",
        "FETC*": "1,IR,0.500,150.300,PASS",
    }

    def __init__(self, instance_id: str, *, simulated: bool = False, params: dict | None = None, **kw):
        params = params or {}
        if simulated:
            transport = SimTransport(responses=dict(self._SIM))
        else:
            resource = params.get("resource")
            if not resource:
                raise ValueError("Ut5320r: params.resource is required when simulated=False")
            transport = VisaTransport(
                resource,
                timeout_ms=params.get("timeout_ms", 5000),
                read_termination=params.get("read_termination", "\n"),
                write_termination=params.get("write_termination", "\n"),
            )
        # A withstand test's rise + dwell + fall time can run well past the base's 5 s default
        # per-command budget — size it from params, not the base default.
        kw.setdefault("timeout_s", float(params.get("timeout_s", 65.0)))
        super().__init__(instance_id, transport=transport, simulated=simulated, params=params, **kw)

    async def connect(self) -> None:
        await super().connect()
        if not self.simulated:
            # FETCh? only answers from the Measurement Display page (§1.12 Notice).
            await self.transport.write(self.CMD["disp_test"])

    async def identify(self) -> str:
        return await self.transport.query(self.CMD["idn"])

    # ---- ISafetyTester ------------------------------------------------------

    async def measure_ir(self, voltage: float, step: int = 1) -> float:
        step = int(step)                # conformance/callers may pass a float; normalize once
        await self._program_step(step, "IR")
        await self.transport.write(self.CMD["ir_volt"].format(step=step, v=int(round(voltage))))
        value, result = await self._run_and_fetch(step, "IR", "measure_ir")
        if result not in _IR_RESULTS:
            raise DeviceError(f"unexpected IR sorting result {result!r} on step {step}",
                              instance_id=self.instance_id, method="measure_ir")
        return value

    async def measure_acw(self, voltage: float, dwell: float, step: int = 1) -> tuple[float, bool]:
        step = int(step)                # conformance/callers may pass a float; normalize once
        await self._program_step(step, "AC")
        await self.transport.write(self.CMD["ac_volt"].format(step=step, v=int(round(voltage))))
        await self.transport.write(self.CMD["ac_ttim"].format(step=step, t=float(dwell)))
        leakage_ma, result = await self._run_and_fetch(step, "AC", "measure_acw")
        if result not in _ACW_RESULTS:
            raise DeviceError(f"unexpected ACW sorting result {result!r} on step {step}",
                              instance_id=self.instance_id, method="measure_acw")
        return leakage_ma, result in _ACW_BREAKDOWN

    # ---- mandatory base surface (RESET cuts the HV output immediately) ------

    async def safe_state(self) -> None:
        await self.transport.write(self.CMD["stop"])

    async def emergency_disable(self) -> None:
        await self.safe_state()

    # ---- helpers --------------------------------------------------------

    async def _program_step(self, step: int, mode: str) -> None:
        await self.transport.write(self.CMD["set_type"].format(step=int(step), mode=mode))
        if self.simulated:
            # The canned FETCh? reply is a static string and has no way to know which mode was
            # just programmed — keep it consistent so measure_ir vs measure_acw each see a
            # plausible, mode-matching sim result instead of a stale IR/AC mismatch.
            sim = self.transport.inner if hasattr(self.transport, "inner") else self.transport
            if isinstance(sim, SimTransport):
                value = "150.300" if mode == "IR" else "1.500"
                sim.responses["FETC*"] = f"{step},{mode},0.500,{value},PASS"

    async def _run_and_fetch(self, step: int, mode: str, method: str) -> tuple[float, str]:
        """TEST, then poll FETCh? until `step`'s segment carries a GENUINELY NEW sorting result
        (5 comma fields) — 4 fields means the step hasn't finished yet (§1.12 Additional Notes).

        FETCh? answers from the Measurement Display page, which still shows the PREVIOUS test's
        completed result for that step for some window after TEST is issued, before the
        instrument resets it to "in progress" (4 fields) for the new run. Confirmed live
        (2026-09, TMF_Trx_HVT_Okaya) that our first poll can land inside that window and return
        the stale, previous-test leakage/breakdown value with an implausibly fast completion —
        this is what surfaced as the app UI showing the prior HiPOT run's result instead of the
        one just executed. So on real hardware a 5-field answer is only trusted once we've
        actually observed the transition through a 4-field "in progress" state first — a real
        state change, not a timing guess. Skipped in sim (`self.simulated`): the canned sim
        reply is a static 5-field string with no in-progress state to observe, so requiring one
        would hang forever."""
        await self.transport.write(self.CMD["start"])
        seen_in_progress = self.simulated
        while True:
            raw = await self.transport.query(self.CMD["fetch"])
            fields = self._segment(raw, step, method).split(",")
            if len(fields) == 4:
                seen_in_progress = True
                await asyncio.sleep(_POLL_S)
                continue
            if len(fields) >= 5:
                if not seen_in_progress:
                    # Still the stale result from the PREVIOUS test on this step — keep polling
                    # until the page actually flips to in-progress, so a leftover reading is
                    # never reported as this test's own.
                    await asyncio.sleep(_POLL_S)
                    continue
                if fields[1] != mode:
                    raise GarbageResponse(
                        f"step {step} reports mode {fields[1]!r}, expected {mode!r}",
                        instance_id=self.instance_id, method=method, detail=raw)
                return self._num(fields[3], method, raw), fields[4].strip()
            raise GarbageResponse(f"malformed FETCh? segment {fields!r}",
                                  instance_id=self.instance_id, method=method, detail=raw)

    def _segment(self, raw: str, step: int, method: str) -> str:
        prefix = f"{step},"
        for seg in (raw or "").split(";"):
            seg = seg.strip()
            if seg.startswith(prefix):
                return seg
        raise GarbageResponse(f"no step {step} segment in FETCh? reply",
                              instance_id=self.instance_id, method=method, detail=raw)

    def _num(self, raw: str, method: str, detail: str) -> float:
        try:
            return float(raw)
        except (TypeError, ValueError) as e:
            raise GarbageResponse(f"implausible reading {raw!r}", instance_id=self.instance_id,
                                  method=method, detail=detail) from e
