"""`okaya_tower` default variant — drives the relay2 tower stack from run state.

The bench tower is two lamps + a buzzer on the second Waveshare relay card (`relay2`): green,
red, buzzer (variable-map signals `tl_green` / `tl_red` / `buzzer`; this bench has no yellow).
This module watches the controller's run lifecycle over MQTT (`event/#`) and writes those signals
through the bridge `variable.write` op — never from a recipe, so no recipe has to carry it:

  - run-started  -> both lamps OFF, buzzer OFF  (nothing lit while a test is running)
  - run-finished PASS      -> green ON
  - run-finished non-PASS  -> red ON + buzzer for `buzzer_duration_s` (if `buzzer_enabled`)
  - run-aborted            -> red ON, NO buzzer (operator/safety stop, not a failed part)

After showing a result the lamp is held for `result_hold_s`, then cleared to OFF (idle = all off).
Every output write is logged as a diag event, so tower activity is visible in a flight-recorder
bundle. The tower is advisory: a failed lamp/buzzer write is logged, never raised into a run.

Settings (enable, buzzer on/off, buzzer duration, lamp hold) live in a record edited via the
tower settings endpoint; `app.json` only supplies the defaults.
"""

from __future__ import annotations

import asyncio

from core.framework.contract import CoreServices, Health, HealthStatus
from modules.okaya_tower.api import build_router

_SETTING_TYPE, _SETTING_ID = "okaya_tower_setting", "okaya_tower"
_DEFAULT_SIGNALS = {"green": "tl_green", "red": "tl_red", "buzzer": "buzzer"}
_WRITE_TIMEOUT_S = 5.0


class OkayaTower:
    def __init__(self, core: CoreServices, config: dict) -> None:
        self.core = core
        self.config = config or {}
        self.enabled = bool(self.config.get("enabled", True))
        self.buzzer_enabled = bool(self.config.get("buzzer_enabled", True))
        self.buzzer_duration_s = float(self.config.get("buzzer_duration_s", 5.0))
        self.result_hold_s = float(self.config.get("result_hold_s", 5.0))
        self.stations = list(self.config.get("stations") or ["st1"])
        self.sig = {**_DEFAULT_SIGNALS, **(self.config.get("signals") or {})}
        self._seq: asyncio.Task | None = None          # in-flight buzzer/lamp-clear timer
        self.router = build_router(self)
        self.mqtt_handlers = [("event/#", self._on_event)]

    @classmethod
    def construct(cls, core: CoreServices, config: dict) -> "OkayaTower":
        return cls(core, config)

    # --- lifecycle ---------------------------------------------------------------------------

    async def init(self) -> None:
        rec = await self.core.db.repo.get(_SETTING_TYPE, _SETTING_ID)
        if rec:
            d = rec["data"]
            self.enabled = bool(d.get("enabled", self.enabled))
            self.buzzer_enabled = bool(d.get("buzzer_enabled", self.buzzer_enabled))
            self.buzzer_duration_s = float(d.get("buzzer_duration_s", self.buzzer_duration_s))
            self.result_hold_s = float(d.get("result_hold_s", self.result_hold_s))

    async def start(self) -> None:
        # Known safe state at boot: everything off. Done in the background — the controller/relay
        # may not be up yet (a blocking write would stall startup), and the first run clears it anyway.
        self._seq = asyncio.create_task(self._startup_clear())

    async def stop(self) -> None:
        self._cancel_seq()

    async def _startup_clear(self) -> None:
        try:
            for st in self.stations:
                await self._all_off(st)
        except asyncio.CancelledError:
            pass

    # --- run lifecycle -> tower ----------------------------------------------------------------

    async def _on_event(self, topic: str, payload: dict | None) -> None:
        if not payload or not self.enabled:
            return
        etype = payload.get("type") or topic.rsplit("/", 1)[-1]
        station = self._station_from_topic(topic)
        body = payload.get("payload", {}) or {}
        if etype == "run-started":
            self._cancel_seq()
            await self._all_off(station)                       # nothing lit while testing
        elif etype == "run-finished":
            await self._show_result(station, str(body.get("result") or "").upper())
        elif etype == "run-aborted":
            await self._show_aborted(station)

    @staticmethod
    def _station_from_topic(topic: str) -> str:
        parts = (topic or "").split("/")
        return parts[1] if len(parts) >= 3 and parts[0] == "tmf" else "st1"

    async def _show_result(self, station: str, result: str) -> None:
        self._cancel_seq()
        if result == "PASS":
            await self._write(self.sig["green"], True, station)
            await self._write(self.sig["red"], False, station)
            self._seq = asyncio.create_task(self._clear_after(self.result_hold_s, ("green",), station))
        else:
            await self._fail(station, buzzer=self.buzzer_enabled)

    async def _show_aborted(self, station: str) -> None:
        self._cancel_seq()
        await self._fail(station, buzzer=False)                # red only, never the buzzer

    async def _fail(self, station: str, *, buzzer: bool) -> None:
        await self._write(self.sig["red"], True, station)
        await self._write(self.sig["green"], False, station)
        sound = buzzer and self.buzzer_duration_s > 0
        if sound:
            await self._write(self.sig["buzzer"], True, station)
        self._seq = asyncio.create_task(self._fail_sequence(sound, station))

    async def _fail_sequence(self, sound: bool, station: str) -> None:
        try:
            elapsed = 0.0
            if sound:
                await asyncio.sleep(self.buzzer_duration_s)
                await self._write(self.sig["buzzer"], False, station)
                elapsed = self.buzzer_duration_s
            # keep the red lamp lit at least until the buzzer stops, and for result_hold_s overall
            remaining = max(self.result_hold_s, elapsed) - elapsed
            if remaining > 0:
                await asyncio.sleep(remaining)
            await self._write(self.sig["red"], False, station)
        except asyncio.CancelledError:
            pass

    async def _clear_after(self, delay: float, keys, station: str) -> None:
        try:
            if delay > 0:
                await asyncio.sleep(delay)
            for key in keys:
                await self._write(self.sig[key], False, station)
        except asyncio.CancelledError:
            pass

    def _cancel_seq(self) -> None:
        if self._seq and not self._seq.done():
            self._seq.cancel()
        self._seq = None

    async def _all_off(self, station: str) -> None:
        for key in ("green", "red", "buzzer"):
            await self._write(self.sig[key], False, station)

    async def _write(self, name: str, on: bool, station: str) -> None:
        try:
            await self.core.bridge.request("variable.write", {"name": name, "value": 1 if on else 0},
                                           station=station, timeout=_WRITE_TIMEOUT_S)
            self.core.diag.info("okaya_tower", "tower output set", signal=name, on=bool(on), station=station)
        except Exception as exc:  # noqa: BLE001 — the tower is advisory; never break a run on a lamp write
            self.core.diag.warning("okaya_tower", "tower output write failed",
                                   signal=name, on=bool(on), station=station, error=str(exc))

    # --- health + settings + wiring self-test --------------------------------------------------

    async def health(self) -> Health:
        return Health(status=HealthStatus.OK,
                      detail=f"tower · enabled={self.enabled} · buzzer="
                             f"{'on' if self.buzzer_enabled else 'off'}/{self.buzzer_duration_s:g}s "
                             f"· hold={self.result_hold_s:g}s")

    async def status(self) -> dict:
        return {"enabled": self.enabled, "buzzer_enabled": self.buzzer_enabled,
                "buzzer_duration_s": self.buzzer_duration_s, "result_hold_s": self.result_hold_s,
                "signals": self.sig, "stations": self.stations}

    def get_config(self) -> dict:
        return {"enabled": self.enabled, "buzzer_enabled": self.buzzer_enabled,
                "buzzer_duration_s": self.buzzer_duration_s, "result_hold_s": self.result_hold_s}

    async def set_config(self, body: dict) -> dict:
        if "enabled" in body:
            self.enabled = bool(body["enabled"])
        if "buzzer_enabled" in body:
            self.buzzer_enabled = bool(body["buzzer_enabled"])
        if "buzzer_duration_s" in body:
            self.buzzer_duration_s = max(0.0, float(body["buzzer_duration_s"]))
        if "result_hold_s" in body:
            self.result_hold_s = max(0.0, float(body["result_hold_s"]))
        await self.core.db.repo.put(
            _SETTING_TYPE,
            {"enabled": self.enabled, "buzzer_enabled": self.buzzer_enabled,
             "buzzer_duration_s": self.buzzer_duration_s, "result_hold_s": self.result_hold_s},
            id=_SETTING_ID, summary="okaya tower settings")
        self.core.diag.info("okaya_tower", "settings updated", enabled=self.enabled,
                            buzzer_enabled=self.buzzer_enabled, buzzer_duration_s=self.buzzer_duration_s,
                            result_hold_s=self.result_hold_s)
        return self.get_config()

    async def self_test(self, body: dict) -> dict:
        key = str(body.get("signal") or "").lower()
        if key not in self.sig:
            return {"ok": False, "detail": f"signal must be one of {list(self.sig)}"}
        station = body.get("station") or (self.stations[0] if self.stations else "st1")
        on = bool(body.get("on", True))
        self._cancel_seq()
        await self._write(self.sig[key], on, station)
        return {"ok": True, "signal": self.sig[key], "on": on, "station": station}
