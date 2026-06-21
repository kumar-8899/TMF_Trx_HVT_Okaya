"""Health `default` variant — registry + sequencer + records + WS (HEALTH_CHECK.md §5,§6).

Runs a list of checks respecting `requires` deps and the disruptive/maintenance
gate, streams progress, and persists an append-only `health_run` record. Bridge/
hardware checks with no local executor dispatch over the bridge and degrade to
`unavailable`/`timeout` rather than hanging (§2.4).
"""

from __future__ import annotations

import asyncio
import time
import uuid

from fastapi import WebSocket, WebSocketDisconnect

from core.framework.contract import CoreServices, Health, HealthStatus
from core.services.streaming import StreamHub
from modules.health import checks as registry
from modules.health.api import build_router

_CRITICAL_BAD = {"fail", "timeout", "error"}

_DEFAULT_SUITES = {
    "smoke": ["web.db_writable", "bridge.online"],
    "full": ["web.db_writable", "web.disk_space", "bridge.online", "bridge.roundtrip"],
}


class DefaultHealth:
    def __init__(self, core: CoreServices, config: dict) -> None:
        self.core = core
        self.config = config
        self.suites = config.get("suites") or _DEFAULT_SUITES
        self._hub = StreamHub()
        self._maintenance = False
        self._aborted: set[str] = set()
        self.router = build_router(self)
        self.mqtt_handlers = [("state/maintenance", self._on_maintenance)]

    @classmethod
    def construct(cls, core: CoreServices, config: dict) -> "DefaultHealth":
        return cls(core, config)

    async def init(self) -> None: pass
    async def start(self) -> None: pass
    async def stop(self) -> None: pass

    async def health(self) -> Health:
        return Health(status=HealthStatus.OK, detail=f"{len(registry.descriptors())} checks")

    def _on_maintenance(self, _topic: str, payload: dict | None) -> None:
        if payload is not None:
            self._maintenance = payload.get("state") == "on"

    # --- introspection -----------------------------------------------------

    def _reachable(self, d) -> bool:
        if registry.executor(d.id) is not None:
            return True
        return bool(self.core.bridge and self.core.bridge.online)

    def list_checks(self) -> list[dict]:
        return [{**d.public(), "reachable": self._reachable(d)} for d in registry.descriptors().values()]

    def list_suites(self) -> list[dict]:
        return [{"name": n, "check_ids": ids, "description": ""} for n, ids in self.suites.items()]

    # --- run control -------------------------------------------------------

    def _resolve(self, suite: str | None, check_ids: list[str] | None) -> list[str]:
        if suite:
            if suite not in self.suites:
                raise ValueError(f"unknown suite '{suite}'")
            return list(self.suites[suite])
        return list(check_ids or [])

    def _order(self, ids: list[str], descs: dict) -> list[str]:
        """Topological order by `requires` (only within the selected set)."""
        ordered: list[str] = []
        seen: set[str] = set()
        temp: set[str] = set()

        def visit(cid: str):
            if cid in seen or cid not in descs:
                return
            if cid in temp:
                raise ValueError(f"dependency cycle at '{cid}'")
            temp.add(cid)
            for dep in descs[cid].requires:
                if dep in descs:
                    visit(dep)
            temp.discard(cid)
            seen.add(cid)
            ordered.append(cid)

        for cid in ids:
            visit(cid)
        return ordered

    async def run(self, *, suite=None, check_ids=None, mode="serial",
                  trigger="manual", operator=None) -> str:
        ids = self._resolve(suite, check_ids)
        all_d = registry.descriptors()
        unknown = [c for c in ids if c not in all_d]
        if unknown:
            raise ValueError(f"unknown check(s): {', '.join(unknown)}")
        order = self._order(ids, all_d)

        hid = uuid.uuid4().hex
        self._emit(hid, "health-run-started", {"total_checks": len(order)})
        verdicts: list[dict] = []
        passed: set[str] = set()
        for cid in order:
            d = all_d[cid]
            if hid in self._aborted:
                v = self._verdict(cid, "skipped", "aborted")
            elif d.disruptive and not self._maintenance:
                v = self._verdict(cid, "skipped", "disruptive: requires maintenance mode")
            elif any(dep not in passed for dep in d.requires):
                dep = next(dep for dep in d.requires if dep not in passed)
                v = self._verdict(cid, "skipped", f"dependency '{dep}' did not pass")
            else:
                self._emit(hid, "check-started", {"check_id": cid, "title": d.title})
                v = await self._dispatch(d)
            if v["status"] == "pass":
                passed.add(cid)
            verdicts.append(v)
            self.core.diag.info("health", "check verdict", check_id=cid, status=v["status"])
            self._emit(hid, "check-completed",
                       {"check_id": cid, "status": v["status"], "elapsed_ms": v["elapsed_ms"], "summary": v["summary"]})

        record = self._assemble(hid, mode, trigger, operator, verdicts)
        await self.core.db.repo.put("health_run", record, id=hid, summary=record["summary"])
        self._aborted.discard(hid)
        self._emit(hid, "health-run-finished", {"overall": record["overall"], "counts": record["counts"]})
        return hid

    async def _dispatch(self, d) -> dict:
        t0 = time.time()
        ex = registry.executor(d.id)
        try:
            if ex is not None:
                body = await asyncio.wait_for(ex(self.core, self.config, {}), d.timeout_ms / 1000)
            elif self.core.bridge is not None and self.core.bridge.online:
                reply = await self.core.bridge.request(f"health.check.{d.id}", {}, timeout=d.timeout_ms / 1000)
                body = {"status": reply.get("status", "pass" if reply.get("ok") else "fail"),
                        "summary": reply.get("summary", ""), "data": reply.get("result", reply.get("data", {})),
                        "error": reply.get("error")}
            else:
                body = {"status": "unavailable", "summary": "executor not reachable", "data": {}, "error": None}
        except asyncio.TimeoutError:
            body = {"status": "timeout", "summary": f"no answer within {d.timeout_ms} ms", "data": {}, "error": None}
        except Exception as exc:  # noqa: BLE001 — executor malfunction is `error`, not a fault
            body = {"status": "error", "summary": str(exc), "data": {},
                    "error": {"type": "about:blank", "title": "check executor error", "detail": str(exc)}}
        v = self._verdict(d.id, body["status"], body.get("summary", ""), body.get("data", {}), body.get("error"))
        v["elapsed_ms"] = round((time.time() - t0) * 1000, 1)
        if v["status"] in _CRITICAL_BAD:
            v["signature"] = {"check_id": d.id, "status": v["status"],
                              "error_code": (body.get("error") or {}).get("code")}
        return v

    def _verdict(self, check_id, status, summary, data=None, error=None) -> dict:
        return {"check_id": check_id, "status": status, "started_ts": time.time(),
                "elapsed_ms": 0.0, "summary": summary, "data": data or {}, "error": error, "signature": None}

    def _assemble(self, hid, mode, trigger, operator, verdicts) -> dict:
        counts: dict[str, int] = {}
        for v in verdicts:
            counts[v["status"]] = counts.get(v["status"], 0) + 1
        descs = registry.descriptors()
        unhealthy = any(v["status"] in _CRITICAL_BAD and descs.get(v["check_id"]) and descs[v["check_id"]].severity == "critical" for v in verdicts)
        incomplete = any(v["status"] == "unavailable" and descs.get(v["check_id"]) and descs[v["check_id"]].severity == "critical" for v in verdicts)
        degraded = any(v["status"] == "fail" and descs.get(v["check_id"]) and descs[v["check_id"]].severity == "warning" for v in verdicts)
        overall = "unhealthy" if unhealthy else "incomplete" if incomplete else "degraded" if degraded else "healthy"
        bad = [v["check_id"] for v in verdicts if v["status"] in _CRITICAL_BAD]
        summary = f"{overall}: {len(bad)} issue(s)" + (f" — {', '.join(bad)}" if bad else "")
        return {"health_run_id": hid, "mode": mode, "trigger": trigger, "operator": operator,
                "maintenance": self._maintenance, "overall": overall, "counts": counts,
                "verdicts": verdicts, "suggestions": [], "summary": summary, "ts": time.time()}

    def abort(self, hid: str) -> None:
        self._aborted.add(hid)

    # --- queries -----------------------------------------------------------

    async def list_runs(self, since=None, limit=None, trigger=None) -> list[dict]:
        rows = await self.core.db.repo.query("health_run", since=since, limit=limit)
        items = [r["data"] for r in rows]
        if trigger:
            items = [d for d in items if d.get("trigger") == trigger]
        return items

    async def get_run(self, hid: str) -> dict | None:
        rec = await self.core.db.repo.get("health_run", hid)
        return rec["data"] if rec else None

    async def current(self, trigger=None) -> dict | None:
        items = await self.list_runs(trigger=trigger)
        return items[-1] if items else None

    # --- WS ----------------------------------------------------------------

    def _emit(self, hid: str, etype: str, payload: dict) -> None:
        self._hub.broadcast({"type": etype, "ts": time.time(), "health_run_id": hid, **payload})

    async def stream_ws(self, ws: WebSocket, hid: str) -> None:
        await ws.accept()
        async with self._hub.subscription() as q:
            try:
                while True:
                    ev = await q.get()
                    if ev.get("health_run_id") == hid:
                        await ws.send_json(ev)
            except WebSocketDisconnect:
                pass
