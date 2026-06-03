"""Runs `default` variant — controller run proxy + run-record persistence.

LabVIEW owns execution; this module relays run.start/abort and turns the
event/run-* the controller emits into durable run records (CORE.md §7). Every
event is appended (append-only history = the corpus); a current-state `run`
record is upserted per run_id for the run list.
"""

from __future__ import annotations

from core.framework.contract import CoreServices, Health, HealthStatus
from modules.runs.api import build_router

# Event types this module persists (LABVIEW_BRIDGE.md §4 event envelope).
RUN_EVENT_PREFIXES = ("run-", "step-", "safety-")


class DefaultRuns:
    def __init__(self, core: CoreServices, config: dict) -> None:
        self.core = core
        self.config = config
        self.router = build_router(self)
        self.mqtt_handlers = [("event/#", self._on_event)]

    @classmethod
    def construct(cls, core: CoreServices, config: dict) -> "DefaultRuns":
        return cls(core, config)

    async def init(self) -> None:
        pass

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def health(self) -> Health:
        online = bool(self.core.bridge and self.core.bridge.online)
        return Health(
            status=HealthStatus.OK if online else HealthStatus.DEGRADED,
            detail="bridge online" if online else "bridge link not online",
        )

    # --- run control -------------------------------------------------------

    async def run_start(self, params: dict | None = None) -> dict:
        reply = await self.core.bridge.request("run.start", params or {})
        self.core.diag.info("runs", "run start", ok=reply.get("ok"))
        return reply

    async def run_abort(self) -> dict:
        reply = await self.core.bridge.request("run.abort", {})
        self.core.diag.warning("runs", "run abort", ok=reply.get("ok"))
        return reply

    # --- event intake -> records (CORE.md §7) ------------------------------

    async def _on_event(self, topic: str, payload: dict | None) -> None:
        if not payload:
            return
        etype = payload.get("type") or topic.rsplit("/", 1)[-1]
        if not any(etype.startswith(p) for p in RUN_EVENT_PREFIXES):
            return
        body = payload.get("payload", {}) or {}
        run_id = body.get("run_id") or body.get("id")
        ts = payload.get("ts")

        # append-only history
        await self.core.db.repo.put(
            "run_event",
            {"type": etype, "ts": ts, "run_id": run_id, **body},
            summary=f"{etype} {run_id or ''}".strip(),
        )

        # current-state run record
        if not run_id:
            return
        if etype == "run-started":
            await self.core.db.repo.put(
                "run", {"status": "running", "started_ts": ts, **body},
                id=run_id, summary=f"run {run_id} started",
            )
        elif etype == "run-finished":
            existing = await self.core.db.repo.get("run", run_id)
            data = dict(existing["data"]) if existing else {}
            data.update({"status": "finished", "finished_ts": ts, **body})
            await self.core.db.repo.put("run", data, id=run_id, summary=f"run {run_id} finished")

    # --- queries -----------------------------------------------------------

    async def list_runs(self, since: float | None = None, limit: int | None = None) -> list[dict]:
        return await self.core.db.repo.query("run", since=since, limit=limit)

    async def get_run(self, run_id: str) -> dict | None:
        return await self.core.db.repo.get("run", run_id)
