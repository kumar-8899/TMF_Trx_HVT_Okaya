"""Runs `default` variant — controller run proxy + run-record persistence.

LabVIEW owns execution; this module relays run.start/abort and turns the
event/run-* the controller emits into durable run records (CORE.md §7). Every
event is appended (append-only history = the corpus); a current-state `run`
record is upserted per run_id for the run list.
"""

from __future__ import annotations

import time
import uuid

from fastapi import WebSocket, WebSocketDisconnect

from core.framework.contract import CoreServices, Health, HealthStatus
from core.services.streaming import StreamHub
from modules.runs.acquisition import resolve_recipe_id
from modules.runs.api import build_router

# Event types this module persists (LABVIEW_BRIDGE.md §4 event envelope).
RUN_EVENT_PREFIXES = ("run-", "step-", "safety-", "test-")


class DefaultRuns:
    def __init__(self, core: CoreServices, config: dict) -> None:
        self.core = core
        self.config = config
        acq = config.get("acquisition", {}) or {}
        self.acq_default_mode = acq.get("default_mode", "barcode")
        self._barcode_cfg = acq.get("barcode", {}) or {}
        self._identity_cfg = config.get("identity", {}) or {}
        self._live_variables = config.get("live_variables", []) or []
        self._analytics_cfg = config.get("analytics", {"daily": True}) or {}
        self._ui_cfg = config.get("ui", {}) or {}
        self._station_hub = StreamHub()   # event/* -> /ws/station
        self._diag_hub = StreamHub()      # diag    -> /diagnostics/stream
        self.router = build_router(self)
        self.mqtt_handlers = [("event/#", self._on_event), ("diag", self._on_diag)]

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

    # --- acquisition -------------------------------------------------------

    def acquisition_config(self) -> dict:
        """What the Start dialog needs (default mode + hints)."""
        return {
            "default_mode": self.acq_default_mode,
            "barcode": {
                "strategy": self._barcode_cfg.get("strategy", "prefix"),
                "length": self._barcode_cfg.get("length", 3),
            },
        }

    def profile(self) -> dict:
        """The bench profile that drives the operator testing window — declarative,
        so the window's composition changes by config, not code."""
        return {
            "acquisition": self.acquisition_config(),
            "identity": {
                "model": self._identity_cfg.get("model", "prefix"),
                "serial": self._identity_cfg.get("serial", "barcode"),
            },
            "live_variables": self._live_variables,
            "analytics": {"daily": self._analytics_cfg.get("daily", True)},
            "ui": {
                "verdict_banner": self._ui_cfg.get("verdict_banner", True),
                "message_line": self._ui_cfg.get("message_line", True),
                "today_strip": self._ui_cfg.get("today_strip", True),
            },
        }

    def _identity(self, barcode: str | None, recipe_id: str) -> dict:
        """Derive Serial No + Model for the run record (identity config)."""
        out: dict = {"model": recipe_id}
        if barcode:
            out["serial_no"] = barcode if self._identity_cfg.get("serial", "barcode") == "barcode" else barcode
        return out

    def resolve(self, barcode: str) -> str:
        return resolve_recipe_id(
            barcode,
            strategy=self._barcode_cfg.get("strategy", "prefix"),
            length=self._barcode_cfg.get("length", 3),
        )

    # --- run control -------------------------------------------------------

    async def run_start(self, body: dict | None = None) -> dict:
        """Resolve the recipe (direct id or from a barcode), mint a run_id, and
        tell LabVIEW to start. LabVIEW pulls the recipe JSON via recipe.fetch."""
        body = body or {}
        recipe_id = body.get("recipe_id")
        barcode = body.get("barcode")
        if not recipe_id and barcode:
            recipe_id = self.resolve(barcode)  # AcquisitionError -> 422
        if not recipe_id:
            from modules.runs.acquisition import AcquisitionError
            raise AcquisitionError("recipe_id or barcode required")

        run_id = body.get("run_id") or uuid.uuid4().hex
        run_parameters = dict(body.get("run_parameters") or {})
        if barcode:
            run_parameters.setdefault("barcode", barcode)
        identity = self._identity(barcode, recipe_id)  # serial_no + model
        run_parameters.update({k: v for k, v in identity.items() if k not in run_parameters})
        operator = body.get("operator")
        if operator:
            run_parameters.setdefault("operator", operator)

        # MES interlock: block before creating a run if the previous stage didn't pass
        # (fail-open when no MES module is loaded). InterlockError -> HTTP 409.
        serial = identity.get("serial_no")
        if self.core.interlock is not None and serial:
            res = await self.core.interlock.check(serial, {
                "recipe_id": recipe_id, "operator": operator, "station": self.core.station,
            })
            if not res.allowed:
                from core.services.interlock import InterlockError
                raise InterlockError(res.detail or "blocked by MES interlock")

        payload = {
            "run_id": run_id, "recipe_id": recipe_id,
            "version": body.get("version"), "run_parameters": run_parameters,
        }
        # Pre-create the run record so the UI shows it immediately.
        await self._upsert_run(run_id, status="starting", recipe_id=recipe_id,
                               run_parameters=run_parameters, operator=operator, **identity)
        reply = await self.core.bridge.request("run.start", payload)
        self.core.diag.info("runs", "run start", run_id=run_id, recipe_id=recipe_id, ok=reply.get("ok"))
        out = {"run_id": run_id, "recipe_id": recipe_id, **identity}
        if isinstance(reply, dict):
            out.update({k: v for k, v in reply.items() if k != "id"})
        return out

    async def run_abort(self) -> dict:
        reply = await self.core.bridge.request("run.abort", {})
        self.core.diag.warning("runs", "run abort", ok=reply.get("ok"))
        return reply

    # Record types wiped by Settings → Reset data: run/test history, reports, and
    # the error/action logs. (Recipes + users are intentionally left alone.)
    RESET_TYPES = ("run", "run_event", "report", "error_log", "action_log")

    async def reset_data(self) -> dict:
        """Purge run/test/report records and error/action logs (Settings → Reset
        data). Gated to SYSTEM.RESET_DATA (super_admin) at the route."""
        horizon = time.time() + 1  # delete is ts < horizon -> everything
        deleted = {t: await self.core.db.repo.delete(t, horizon) for t in self.RESET_TYPES}
        self.core.diag.warning("runs", "test data reset", **deleted)
        return {"deleted": deleted}

    # --- event intake -> records (CORE.md §7) ------------------------------

    async def _upsert_run(self, run_id: str, **changes) -> None:
        """Merge changes into the current-state run record (preserves recipe_id,
        results[], etc. across the event lifecycle)."""
        existing = await self.core.db.repo.get("run", run_id)
        data = dict(existing["data"]) if existing else {"run_id": run_id}
        data.update(changes)
        await self.core.db.repo.put("run", data, id=run_id,
                                    summary=f"run {run_id} {data.get('status', '')}".strip())

    async def _on_event(self, topic: str, payload: dict | None) -> None:
        if not payload:
            return
        self._station_hub.broadcast(payload)  # all events -> /ws/station (BRIDGE §9)
        etype = payload.get("type") or topic.rsplit("/", 1)[-1]
        if not any(etype.startswith(p) for p in RUN_EVENT_PREFIXES):
            return
        body = payload.get("payload", {}) or {}
        run_id = body.get("run_id") or body.get("id")
        # Stamp server time when the controller omits ts, so started/finished_ts are
        # always present (the daily analytics filters on finished_ts).
        ts = payload.get("ts") or time.time()

        # append-only history
        await self.core.db.repo.put(
            "run_event",
            {"type": etype, "ts": ts, "run_id": run_id, **body},
            summary=f"{etype} {run_id or ''}".strip(),
        )

        if not run_id:
            return

        # body fields to merge, minus the keys handled positionally/explicitly.
        rest = {k: v for k, v in body.items() if k not in ("run_id", "id", "status")}

        # current-state run record
        if etype == "run-started":
            await self._upsert_run(run_id, status="running", started_ts=ts, **rest)
        elif etype == "run-finished":
            # result rides in body (PASS | FAIL | ABORTED).
            await self._upsert_run(run_id, status="finished", finished_ts=ts, **rest)
        elif etype == "run-aborted":
            rest.setdefault("result", "ABORTED")
            await self._upsert_run(run_id, status="finished", finished_ts=ts, **rest)
        elif etype == "test-result":
            # Append the row to the run's results table (live UI + history + reports).
            existing = await self.core.db.repo.get("run", run_id)
            data = dict(existing["data"]) if existing else {"run_id": run_id, "status": "running"}
            results = list(data.get("results") or [])
            results.append({k: v for k, v in body.items() if k != "run_id"})
            data["results"] = results
            await self.core.db.repo.put("run", data, id=run_id, summary=f"run {run_id} {len(results)} results")

    # --- queries -----------------------------------------------------------

    async def list_runs(self, since: float | None = None, limit: int | None = None) -> list[dict]:
        return await self.core.db.repo.query("run", since=since, limit=limit)

    async def get_run(self, run_id: str) -> dict | None:
        return await self.core.db.repo.get("run", run_id)

    # --- WS fan-out (BRIDGE §9) --------------------------------------------

    def _on_diag(self, _topic: str, payload: dict | None) -> None:
        if payload is not None:
            self._diag_hub.broadcast(payload)

    async def _fanout_ws(self, ws: WebSocket, hub: StreamHub) -> None:
        await ws.accept()
        async with hub.subscription() as q:
            try:
                while True:
                    await ws.send_json(await q.get())
            except WebSocketDisconnect:
                pass

    async def station_ws(self, ws: WebSocket) -> None:
        await self._fanout_ws(ws, self._station_hub)

    async def diag_ws(self, ws: WebSocket) -> None:
        await self._fanout_ws(ws, self._diag_hub)
