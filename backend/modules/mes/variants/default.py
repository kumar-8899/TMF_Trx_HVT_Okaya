"""MES `default` variant — fills the core.interlock port, publishes on run-finish.

The pluggable transport (folder/db/xml) is chosen by config; gate + publish can be
toggled at runtime from the Settings page (persisted as a `mes_setting` record).
"""

from __future__ import annotations

from core.framework.contract import CoreServices, Health, HealthStatus
from core.services.interlock import InterlockResult
from modules.mes.api import build_router
from modules.mes.providers import make_provider

_SETTING_ID = "mes"


class DefaultMes:
    def __init__(self, core: CoreServices, config: dict) -> None:
        self.core = core
        self.config = config
        self.stage = config.get("stage", core.station)
        self.provider_kind = config.get("provider", "folder")
        gate = config.get("gate", {}) or {}
        publish = config.get("publish", {}) or {}
        self.on_missing = gate.get("on_missing", "block")
        # runtime-toggleable flags (config = the default; Settings overrides)
        self.gate_enabled = bool(gate.get("enabled", False))
        self.publish_enabled = bool(publish.get("enabled", False))
        self.provider = make_provider(self.provider_kind, config, on_missing=self.on_missing)
        self.router = build_router(self)
        self.mqtt_handlers = [("event/#", self._on_event)]

    @classmethod
    def construct(cls, core: CoreServices, config: dict) -> "DefaultMes":
        return cls(core, config)

    async def init(self) -> None:
        # load persisted Settings toggles (override config defaults)
        rec = await self.core.db.repo.get("mes_setting", _SETTING_ID)
        if rec:
            d = rec["data"]
            self.gate_enabled = bool(d.get("gate_enabled", self.gate_enabled))
            self.publish_enabled = bool(d.get("publish_enabled", self.publish_enabled))
        # fill the interlock port so the runs module can gate on us
        if self.core.interlock is not None:
            self.core.interlock.register(self.check)

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def health(self) -> Health:
        return Health(status=HealthStatus.OK,
                      detail=f"{self.provider_kind} · gate={self.gate_enabled} publish={self.publish_enabled}")

    # --- interlock port (called by runs at run start) ----------------------

    async def check(self, serial: str, ctx: dict) -> InterlockResult:
        if not self.gate_enabled or not serial:
            return InterlockResult(allowed=True, detail="gate disabled")
        res = await self.provider.check_upstream(serial)
        self.core.diag.info("mes", "interlock check", serial=serial,
                            allowed=res.allowed, prior=res.prior_result)
        return res

    async def publish(self, serial: str, result: str, payload: dict) -> None:
        if not self.publish_enabled or not serial:
            return
        await self.provider.publish_result(serial, result, payload)
        self.core.diag.info("mes", "result published", serial=serial, result=result, stage=self.stage)

    # --- run-finished -> publish downstream --------------------------------

    async def _on_event(self, topic: str, payload: dict | None) -> None:
        if not payload:
            return
        etype = payload.get("type") or topic.rsplit("/", 1)[-1]
        if etype != "run-finished" or not self.publish_enabled:
            return
        body = payload.get("payload", {}) or {}
        run_id = body.get("run_id") or body.get("id")
        if not run_id:
            return
        rec = await self.core.db.repo.get("run", run_id)
        data = rec["data"] if rec else {}
        serial = data.get("serial_no")
        if not serial:
            return
        result = body.get("result") or data.get("result") or "UNKNOWN"
        await self.publish(serial, result, {
            "stage": self.stage, "station": self.core.station,
            "model": data.get("model"), "operator": data.get("operator"),
            "recipe_id": data.get("recipe_id"), "run_id": run_id,
        })

    # --- runtime config (Settings page) ------------------------------------

    def status(self) -> dict:
        return {
            "stage": self.stage, "provider": self.provider_kind,
            "gate_enabled": self.gate_enabled, "publish_enabled": self.publish_enabled,
            "on_missing": self.on_missing, "provider_detail": self.provider.describe(),
        }

    async def set_config(self, gate_enabled: bool | None = None, publish_enabled: bool | None = None) -> dict:
        if gate_enabled is not None:
            self.gate_enabled = bool(gate_enabled)
        if publish_enabled is not None:
            self.publish_enabled = bool(publish_enabled)
        await self.core.db.repo.put(
            "mes_setting",
            {"gate_enabled": self.gate_enabled, "publish_enabled": self.publish_enabled},
            id=_SETTING_ID, summary="mes settings",
        )
        self.core.diag.info("mes", "settings updated",
                            gate=self.gate_enabled, publish=self.publish_enabled)
        return self.status()
