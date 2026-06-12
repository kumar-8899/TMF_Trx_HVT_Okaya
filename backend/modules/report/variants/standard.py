"""Report `standard` variant — assemble on run-finished, fan out to sinks, query.

RP1: sqlite sink + assembly + queries. Folder sink + routing (RP2), analytics
(RP3), export (RP4) extend this.
"""

from __future__ import annotations

from core.framework.contract import CoreServices, Health, HealthStatus
from modules.report.api import build_router
from modules.report.assembly import build_report, result_is_pass
from modules.report.sinks import build_sinks, when_matches


class StandardReport:
    def __init__(self, core: CoreServices, config: dict) -> None:
        self.core = core
        self.config = config
        self.station = core.station
        # Config-driven sinks; sqlite system-of-record is always forced present.
        self._sinks = build_sinks(config, core.db)
        self.router = build_router(self)
        self.mqtt_handlers = [("event/#", self._on_event)]

    @classmethod
    def construct(cls, core: CoreServices, config: dict) -> "StandardReport":
        return cls(core, config)

    async def init(self) -> None:
        pass

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def health(self) -> Health:
        return Health(status=HealthStatus.OK, detail=f"{len(self._sinks)} sink(s)")

    # --- assembly + routing ------------------------------------------------

    async def _on_event(self, topic: str, payload: dict | None) -> None:
        if not payload:
            return
        etype = payload.get("type") or topic.rsplit("/", 1)[-1]
        if etype != "run-finished":
            return
        body = payload.get("payload", {}) or {}
        run_id = body.get("run_id") or body.get("id")
        if not run_id:
            return
        events = [r["data"] for r in await self.core.db.repo.query("run_event", filter={"run_id": run_id})]
        report = build_report(run_id, events, {**body, "ts": payload.get("ts")}, self.station)
        is_pass = result_is_pass(report["result"])
        for sink in self._sinks:
            if when_matches(sink.when, is_pass):
                await sink.write(report)
        self.core.diag.info("report", "report stored", run_id=run_id, result=report["result"])

    # --- queries -----------------------------------------------------------

    async def get_report(self, run_id: str) -> dict | None:
        rec = await self.core.db.repo.get("report", run_id)
        return rec["data"] if rec else None

    async def list_reports(
        self, since: float | None = None, until: float | None = None,
        recipe_id: str | None = None, result: str | None = None,
        limit: int = 200, cursor: str | None = None,
    ) -> dict:
        rows = await self.core.db.repo.query("report", since=since, until=until)
        items = []
        for r in rows:
            d = r["data"]
            if recipe_id is not None and d.get("recipe_id") != recipe_id:
                continue
            if result is not None and d.get("result") != result:
                continue
            items.append(d)
        return {"items": items[:limit], "next_cursor": None, "total": len(items)}
