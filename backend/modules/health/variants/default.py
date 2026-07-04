"""Health `default` variant — registry + sequencer + records + WS (HEALTH_CHECK.md §5,§6).

Runs a list of checks respecting `requires` deps and the disruptive/maintenance
gate, streams progress, and persists an append-only `health_run` record. Bridge/
hardware checks with no local executor dispatch over the bridge and degrade to
`unavailable`/`timeout` rather than hanging (§2.4).
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from dataclasses import replace
from pathlib import Path

from fastapi import WebSocket, WebSocketDisconnect

from core.framework.contract import CoreServices, Health, HealthStatus
from core.services.streaming import StreamHub
from modules.health import catalog
from modules.health import checks as registry
from modules.health.api import build_router

_CRITICAL_BAD = {"fail", "timeout", "error"}

_DEFAULT_SUITES = {
    "smoke": ["web.db_writable", "bridge.online"],
    "bridge": ["bridge.online", "bridge.roundtrip", "bridge.clock_skew", "bridge.queue_depth"],
    "hardware": ["hardware.instance_connected", "hardware.identify", "hardware.range_sane",
                 "hardware.self_test", "hardware.loopback"],
    "full": ["web.db_writable", "web.disk_space", "instruments.python", "bridge.online",
             "bridge.roundtrip", "bridge.clock_skew", "bridge.queue_depth"],
}


class DefaultHealth:
    def __init__(self, core: CoreServices, config: dict) -> None:
        self.core = core
        self.config = config
        self.suites = config.get("suites") or _DEFAULT_SUITES
        self.instances = config.get("instances", []) or []  # [{id, family, capabilities?}]
        self._family = {i["id"]: i.get("family") for i in self.instances}
        self._issue_dirs = [Path(__file__).resolve().parent.parent / "known_issues"]
        if config.get("known_issues_dir"):
            self._issue_dirs.append(Path(config["known_issues_dir"]))
        self._issues: list[dict] = []
        self._hub = StreamHub()
        self._maintenance = False
        self._maint_state = {"state": "off", "since": None, "by": None, "reason": None}
        self._aborted: set[str] = set()
        self._sched = self._norm_schedule(config.get("schedule"))
        self._sched_task: asyncio.Task | None = None
        self._sched_marks: dict[str, float] = {}   # option -> last fired ts (dedupe)
        self.router = build_router(self)
        self.mqtt_handlers = [("state/maintenance", self._on_maintenance)]

    @staticmethod
    def _norm_schedule(raw) -> dict:
        raw = raw or {}
        return {
            "suite": raw.get("suite", "smoke"),
            "startup": bool(raw.get("startup", False)),
            "shutdown": bool(raw.get("shutdown", False)),
            "every_30min": bool(raw.get("every_30min", False)),
            "daily": raw.get("daily") or None,        # "HH:MM" or None
        }

    @classmethod
    def construct(cls, core: CoreServices, config: dict) -> "DefaultHealth":
        return cls(core, config)

    async def init(self) -> None:
        self._issues = catalog.load_issues(self._issue_dirs)

    async def start(self) -> None:
        self._sched_task = asyncio.create_task(self._scheduler_loop())

    async def stop(self) -> None:
        task = self._sched_task
        self._sched_task = None
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task   # await the cancel so it isn't a dangling task at loop close
        if self._sched["shutdown"]:
            try:
                await asyncio.wait_for(self.run(suite=self._sched["suite"], trigger="shutdown"), timeout=30)
            except Exception as exc:  # noqa: BLE001 — best-effort on the way down
                self.core.diag.warning("health", "shutdown health run failed", error=str(exc))

    # --- scheduled runs (predefined cadences) ------------------------------

    async def _scheduler_loop(self) -> None:
        """Tick once a minute; fire enabled cadences. Startup fires once after a
        short grace so the bridge can connect first."""
        if self._sched["startup"]:
            await asyncio.sleep(8)
            await self._fire("startup")
        while True:
            try:
                await asyncio.sleep(60)
                now = time.time()
                if self._sched["every_30min"] and now - self._sched_marks.get("every_30min", 0) >= 1800:
                    await self._fire("every_30min")
                daily = self._sched["daily"]
                if daily and time.strftime("%H:%M", time.localtime(now)) == daily:
                    # once per calendar day
                    day = time.strftime("%Y-%m-%d", time.localtime(now))
                    if self._sched_marks.get("daily_day") != hash(day):
                        self._sched_marks["daily_day"] = hash(day)
                        await self._fire("daily")
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — never let the loop die
                self.core.diag.warning("health", "scheduler tick failed", error=str(exc))

    async def _fire(self, option: str) -> None:
        self._sched_marks[option] = time.time()
        self.core.diag.info("health", "scheduled health run", trigger=option)
        try:
            await self.run(suite=self._sched["suite"], trigger=option)
        except Exception as exc:  # noqa: BLE001
            self.core.diag.warning("health", "scheduled run failed", trigger=option, error=str(exc))

    def schedule_get(self) -> dict:
        return {**self._sched, "suites": list(self.suites.keys())}

    def schedule_set(self, patch: dict) -> dict:
        # runtime update (not persisted to config on disk — survives until restart)
        self._sched = self._norm_schedule({**self._sched, **(patch or {})})
        return self.schedule_get()

    async def health(self) -> Health:
        return Health(status=HealthStatus.OK,
                      detail=f"{len(registry.descriptors())} checks · {len(self._issues)} known issues")

    def _on_maintenance(self, _topic: str, payload: dict | None) -> None:
        if payload is not None:
            self._maint_state = payload
            self._maintenance = payload.get("state") == "on"

    # --- maintenance mode (LabVIEW-owned; we read + proxy requests, §8) -----

    def maintenance_state(self) -> dict:
        return self._maint_state

    async def maintenance_enter(self, operator: str | None, reason: str | None) -> dict:
        return await self.core.bridge.request("maintenance.enter", {"operator": operator, "reason": reason})

    async def maintenance_exit(self, operator: str | None) -> dict:
        return await self.core.bridge.request("maintenance.exit", {"operator": operator})

    # --- introspection -----------------------------------------------------

    def _matches(self, select: dict, inst: dict) -> bool:
        if not select:
            return True
        if "by_family" in select and inst.get("family") != select["by_family"]:
            return False
        if "by_capability" in select and select["by_capability"] not in (inst.get("capabilities") or []):
            return False
        return True

    def _effective(self) -> tuple[dict, set[str]]:
        """Concrete check set = static checks + templated bases expanded per matching
        instance, with same-instance `requires` rewritten (§4.4, §5.3)."""
        descs = registry.descriptors()
        bases = {cid for cid, d in descs.items() if d.instance_templated}
        eff: dict = {cid: d for cid, d in descs.items() if not d.instance_templated}
        for bid in bases:
            bd = descs[bid]
            for inst in self.instances:
                if not self._matches(bd.select, inst):
                    continue
                iid = inst["id"]
                cid = f"{bid}:{iid}"
                reqs = [f"{r}:{iid}" if r in bases else r for r in bd.requires]
                label = inst.get("label") or iid                  # human instrument name
                eff[cid] = replace(bd, id=cid, base_id=bid, instance_id=iid,
                                   title=f"{label} — {bd.title}", group=inst.get("group") or bd.group,
                                   requires=reqs, instance_templated=False)
        return eff, bases

    def _reachable(self, d) -> bool:
        if registry.executor(d.id) is not None:
            return True
        return bool(self.core.bridge and self.core.bridge.online)

    def list_checks(self) -> list[dict]:
        eff, _ = self._effective()
        return [{**d.public(), "reachable": self._reachable(d)} for d in eff.values()]

    def list_suites(self) -> list[dict]:
        return [{"name": n, "check_ids": ids, "description": ""} for n, ids in self.suites.items()]

    # --- run control -------------------------------------------------------

    def _resolve(self, suite, check_ids, eff: dict, bases: set[str]) -> list[str]:
        """Requested ids → concrete ids. A templated base id expands to all its
        instances; a concrete/static id passes through; unknown → error."""
        requested = list(self.suites[suite]) if suite else list(check_ids or [])
        if suite and suite not in self.suites:
            raise ValueError(f"unknown suite '{suite}'")
        out: list[str] = []
        for rid in requested:
            if rid in bases:
                expanded = [cid for cid, d in eff.items() if d.base_id == rid]
                if not expanded:
                    continue  # templated base with no matching instance — silently empty
                out.extend(expanded)
            elif rid in eff:
                out.append(rid)
            else:
                raise ValueError(f"unknown check '{rid}'")
        return out

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
        all_d, bases = self._effective()
        ids = self._resolve(suite, check_ids, all_d, bases)
        order = self._order(ids, all_d)

        hid = uuid.uuid4().hex
        self._emit(hid, "health-run-started", {"total_checks": len(order)})
        verdicts: list[dict] = []
        suggestions: list[dict] = []
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
            v["instance_id"] = d.instance_id
            if v["status"] == "pass":
                passed.add(cid)
            verdicts.append(v)
            self.core.diag.info("health", "check verdict", check_id=cid, status=v["status"])
            self._emit(hid, "check-completed",
                       {"check_id": cid, "status": v["status"], "elapsed_ms": v["elapsed_ms"], "summary": v["summary"]})
            if v["status"] in _CRITICAL_BAD and v.get("signature"):
                suggestions.append(await self._suggest(hid, cid, v["signature"]))

        record = self._assemble(hid, mode, trigger, operator, verdicts, all_d, suggestions)
        await self.core.db.repo.put("health_run", record, id=hid, summary=record["summary"])
        self._aborted.discard(hid)
        self._emit(hid, "health-run-finished", {"overall": record["overall"], "counts": record["counts"]})
        return hid

    async def _dispatch(self, d) -> dict:
        t0 = time.time()
        ex = registry.executor(d.base_id or d.id)
        topic = f"health.check.{d.base_id or d.id}"
        params = {"instance_id": d.instance_id} if d.instance_id else {}
        try:
            if ex is not None:
                body = await asyncio.wait_for(ex(self.core, self.config, params), d.timeout_ms / 1000)
            elif self.core.bridge is not None and self.core.bridge.online:
                reply = await self.core.bridge.request(topic, params, timeout=d.timeout_ms / 1000)
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
            err = body.get("error") or {}
            v["signature"] = {
                "check_id": d.base_id or d.id,            # family-level (§7.1)
                "instance_family": self._family.get(d.instance_id),
                "error_category": err.get("category"),
                "error_code": err.get("code"),
                "status": v["status"],
            }
        return v

    def _verdict(self, check_id, status, summary, data=None, error=None) -> dict:
        return {"check_id": check_id, "status": status, "started_ts": time.time(),
                "elapsed_ms": 0.0, "summary": summary, "data": data or {}, "error": error, "signature": None}

    async def _suggest(self, hid: str, check_id: str, signature: dict) -> dict:
        """Match a failure signature against the catalog; persist a health_suggestion
        record (incl. the valuable 'matched: false' unknown-signature case, §7.4)."""
        issue = catalog.match(signature, self._issues)
        remedy = (issue or {}).get("remedy") or {}
        sid = uuid.uuid4().hex
        rec = {
            "health_run_id": hid, "check_id": check_id, "signature": signature,
            "matched": bool(issue), "issue_id": (issue or {}).get("issue_id"),
            "remedy_kind": remedy.get("kind"), "operator_ack": None,
            "summary": (issue or {}).get("title") if issue else f"unknown signature for {check_id}",
        }
        await self.core.db.repo.put("health_suggestion", rec, id=sid, summary=rec["summary"])
        self._emit(hid, "suggestion", {"check_id": check_id, "matched": rec["matched"],
                                       "issue_id": rec["issue_id"], "remedy_kind": rec["remedy_kind"]})
        # the run record carries the operator-facing view (remedy text + refs)
        return {"id": sid, **rec, "remedy": remedy or None,
                "references": (issue or {}).get("references", [])}

    def _assemble(self, hid, mode, trigger, operator, verdicts, descs, suggestions) -> dict:
        counts: dict[str, int] = {}
        for v in verdicts:
            counts[v["status"]] = counts.get(v["status"], 0) + 1
        unhealthy = any(v["status"] in _CRITICAL_BAD and descs.get(v["check_id"]) and descs[v["check_id"]].severity == "critical" for v in verdicts)
        incomplete = any(v["status"] == "unavailable" and descs.get(v["check_id"]) and descs[v["check_id"]].severity == "critical" for v in verdicts)
        degraded = any(v["status"] == "fail" and descs.get(v["check_id"]) and descs[v["check_id"]].severity == "warning" for v in verdicts)
        overall = "unhealthy" if unhealthy else "incomplete" if incomplete else "degraded" if degraded else "healthy"
        bad = [v["check_id"] for v in verdicts if v["status"] in _CRITICAL_BAD]
        summary = f"{overall}: {len(bad)} issue(s)" + (f" — {', '.join(bad)}" if bad else "")
        return {"health_run_id": hid, "mode": mode, "trigger": trigger, "operator": operator,
                "maintenance": self._maintenance, "overall": overall, "counts": counts,
                "verdicts": verdicts, "suggestions": suggestions, "summary": summary, "ts": time.time()}

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

    async def trends(self, limit: int = 200) -> dict:
        """Derive reliability metrics from health-run history (HEALTH §6 corpus):
        MTBF, failure frequency, repeated failures, and flaky checks/hardware."""
        runs = await self.list_runs(limit=limit)
        meta = self._effective()[0]
        if not runs:
            return {"runs_analyzed": 0, "checks": [], "repeated_failures": [], "flaky": [],
                    "overall_mtbf_s": None, "window_start": None, "window_end": None}
        t_start, t_end = runs[0]["ts"], runs[-1]["ts"]
        span = max(t_end - t_start, 1e-9)

        # per-check series in chronological order
        series: dict[str, list[tuple[float, bool]]] = {}   # check_id -> [(ts, is_fail)]
        for r in runs:
            for v in r.get("verdicts", []):
                if v["status"] in ("skipped", "unavailable"):
                    continue
                series.setdefault(v["check_id"], []).append((r["ts"], v["status"] in _CRITICAL_BAD))

        checks = []
        repeated, flaky = [], []
        for cid, pts in series.items():
            total = len(pts)
            fails = sum(1 for _, f in pts if f)
            transitions = sum(1 for i in range(1, len(pts)) if pts[i][1] != pts[i - 1][1])
            streak = 0
            for _, f in reversed(pts):
                if f:
                    streak += 1
                else:
                    break
            fail_rate = round(fails / total, 3) if total else 0.0
            is_flaky = transitions >= 2 and 0.0 < fail_rate < 1.0
            d = meta.get(cid)
            checks.append({
                "check_id": cid, "title": d.title if d else cid, "group": d.group if d else "System",
                "domain": d.domain if d else "", "total": total, "fails": fails,
                "fail_rate": fail_rate, "current_fail_streak": streak, "transitions": transitions,
                "flaky": is_flaky, "last_status": "fail" if pts[-1][1] else "pass",
                "mtbf_s": round(span / fails, 1) if fails else None,   # uptime / failures
            })
            if streak >= 2:
                repeated.append(cid)
            if is_flaky:
                flaky.append(cid)

        checks.sort(key=lambda c: (-c["fail_rate"], -c["fails"]))
        bad_runs = sum(1 for r in runs if r.get("overall") in ("unhealthy", "degraded"))
        return {
            "runs_analyzed": len(runs), "window_start": t_start, "window_end": t_end,
            "overall_mtbf_s": round(span / bad_runs, 1) if bad_runs else None,
            "checks": checks, "repeated_failures": repeated, "flaky": flaky,
        }

    # --- known issues + suggestions (§7) -----------------------------------

    def list_known_issues(self, q=None, check_id=None) -> list[dict]:
        return catalog.search(self._issues, q or "", check_id)

    def get_known_issue(self, issue_id: str) -> dict | None:
        return next((i for i in self._issues if i.get("issue_id") == issue_id), None)

    async def list_suggestions(self, since=None, matched=None) -> list[dict]:
        rows = await self.core.db.repo.query("health_suggestion", since=since)
        items = [{"id": r["id"], **r["data"]} for r in rows]
        if matched is not None:
            items = [s for s in items if bool(s.get("matched")) == matched]
        return items

    async def ack_suggestion(self, sid: str, outcome: str) -> bool:
        rec = await self.core.db.repo.get("health_suggestion", sid)
        if rec is None:
            return False
        data = dict(rec["data"])
        data["operator_ack"] = outcome
        await self.core.db.repo.put("health_suggestion", data, id=sid, summary=data.get("summary", ""))
        return True

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
