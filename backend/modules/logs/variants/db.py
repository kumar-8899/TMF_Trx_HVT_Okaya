"""Logs `db` variant (LOGS.md §12).

Wires the single error_log sink to the diag bus + the LabVIEW diag topic,
implements record_action and the cursor-paginated queries. REST (L4) and pruning
+ run-event subscriber (L5) land next.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import time
from datetime import datetime, timedelta, timezone

from core.framework.contract import CoreServices, Health, HealthStatus
from core.services.auth_verify import Principal
from modules.logs.api import build_router
from modules.logs.contract import LEVEL_ORDER, Page
from modules.logs.sink import LogsDiagSink

# LabVIEW run-lifecycle events -> action names (LOGS §6.3 / addendum).
_RUN_ACTION = {"run-started": "run.start", "run-finished": "run.complete", "run-aborted": "run.abort"}
# Run actions arrive from the controller, not a logged-in user.
_SYSTEM = Principal("controller", role="system", permissions=frozenset())
# run-aborted reasons that are the operator's choice, not a fault (everything else - recipe_fetch_failed,
# validation_failed, step_timeout, error, safety:<id> - is a system abort: recorded as a failure + warning).
_OPERATOR_ABORT = {"operator_abort", ""}
_BAD_FINISH = {"ABORTED", "ERROR"}   # run-finished results that are not a normal PASS/FAIL verdict


def _prune_decision(rows: list[dict], max_days: int, max_records: int, now: float) -> float | None:
    """Return a `before_ts` to delete, honoring: oldest-first, only beyond
    max_days, and never below max_records. None = nothing to prune."""
    max_deletable = max(0, len(rows) - max_records)
    if max_deletable == 0:
        return None
    age_cutoff = now - max_days * 86400
    older = [r for r in rows if r["ts"] < age_cutoff]
    n = min(len(older), max_deletable)
    return rows[n]["ts"] if n > 0 else None


def _encode_cursor(ts: float, id_: str) -> str:
    return base64.urlsafe_b64encode(f"{ts}:{id_}".encode()).decode()


def _decode_cursor(cursor: str) -> tuple[float, str]:
    raw = base64.urlsafe_b64decode(cursor.encode()).decode()
    ts_str, id_ = raw.split(":", 1)
    return float(ts_str), id_


class DbLogs:
    def __init__(self, core: CoreServices, config: dict) -> None:
        self.core = core
        self.config = config
        self.station = core.station

        persist = config.get("persist", {})
        dedup = config.get("dedup", {})
        self._sink = LogsDiagSink(
            self._put,
            min_level=persist.get("min_level", "warning"),
            subsystems=tuple(persist.get("subsystems", [])),
            dedup_enabled=dedup.get("enabled", True),
            window_s=dedup.get("window_s", 10.0),
        )
        self._retention = config.get("retention", {})
        self._pruning = config.get("pruning", {})
        self._prune_task: asyncio.Task | None = None
        self.router = build_router(self)
        # caller 2: LabVIEW diag over MQTT; run events -> action_log (our tree).
        self.mqtt_handlers = [("diag", self._on_lv_diag), ("event/#", self._on_event)]

    @classmethod
    def construct(cls, core: CoreServices, config: dict) -> "DbLogs":
        return cls(core, config)

    async def _put(self, record_type: str, data: dict, *, summary: str | None = None) -> str:
        return await self.core.db.repo.put(record_type, data, summary=summary)

    # --- lifecycle ---------------------------------------------------------

    async def init(self) -> None:
        # caller 1: Python in-process diag.
        self.core.diag.add_sink(self._sink.receive)

    async def start(self) -> None:
        await self._sink.start()
        if self._pruning.get("enabled", True) and self._retention:
            self._prune_task = asyncio.create_task(self._prune_loop(), name="logs-prune")

    async def stop(self) -> None:
        if self._prune_task is not None:
            self._prune_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._prune_task
            self._prune_task = None
        await self._sink.stop()

    async def health(self) -> Health:
        return Health(status=HealthStatus.OK, detail="logs db variant")

    def _on_lv_diag(self, _topic: str, payload: dict | None) -> None:
        if payload:
            self._sink.receive(payload, source=f"labview:{self.station}")

    async def _on_event(self, topic: str, payload: dict | None) -> None:
        if not payload:
            return
        etype = payload.get("type") or topic.rsplit("/", 1)[-1]
        action = _RUN_ACTION.get(etype)
        if action is None:
            return
        body = payload.get("payload", {}) or {}
        run_id = body.get("run_id") or body.get("id") or ""
        detail: dict = {"event": etype}
        for key in ("result", "reason", "recipe_id", "detail", "errors", "dry_run"):
            if body.get(key) not in (None, "", []):
                detail[key] = body[key]
        result = "success"
        if etype == "run-aborted" and str(body.get("reason") or "") not in _OPERATOR_ABORT:
            result = "failure"
        elif etype == "run-finished" and str(body.get("result") or "").upper() in _BAD_FINISH:
            result = "failure"
        if result == "failure":
            # a run the system ended is a field fault: surface it in the error log, not only the action log
            self.core.diag.warning("runs", f"run {run_id or '?'} ended abnormally ({etype})",
                                   run_id=run_id, **{k: v for k, v in detail.items() if k != "event"})
        await self.record_action(_SYSTEM, action, run_id, result, detail)

    # --- actions (LOGS §5) -------------------------------------------------

    async def record_action(
        self, principal: Principal, action: str, target: str, result: str,
        detail: dict | None = None,
    ) -> str:
        data = {
            "user": principal.subject,
            "role": principal.role,
            "action": action,
            "target": target,
            "result": result,
            "detail": detail or {},
        }
        summary = f"{principal.subject} {action} {target} -> {result}"
        return await self.core.db.repo.put("action_log", data, summary=summary)

    # --- queries (logs-side filter + cursor) -------------------------------

    async def _page(self, record_type, since, until, limit, cursor, predicate) -> Page:
        eff_since = since
        cur = None
        if cursor:
            cur = _decode_cursor(cursor)
            eff_since = cur[0]  # continuation starts at the cursor's ts
        rows = await self.core.db.repo.query(record_type, since=eff_since, until=until)
        rows.sort(key=lambda r: (r["ts"], r["id"]))  # match the (ts,id) cursor key
        if cur is not None:
            rows = [r for r in rows if (r["ts"], r["id"]) > cur]
        matched = [r for r in rows if predicate(r["data"])]
        items = matched[:limit]
        next_cursor = (
            _encode_cursor(items[-1]["ts"], items[-1]["id"]) if len(matched) > limit else None
        )
        return {"items": items, "next_cursor": next_cursor, "total": None}

    async def query_errors(
        self, since=None, until=None, level=None, subsystem=None, limit=200, cursor=None,
    ) -> Page:
        min_idx = LEVEL_ORDER.index(level) if level in LEVEL_ORDER else 0

        def predicate(d: dict) -> bool:
            if LEVEL_ORDER.index(d.get("level", "info")) < min_idx:
                return False
            if subsystem is not None and d.get("subsystem") != subsystem:
                return False
            return True

        return await self._page("error_log", since, until, limit, cursor, predicate)

    async def query_actions(
        self, since=None, until=None, user=None, action=None, result=None, limit=200, cursor=None,
    ) -> Page:
        def predicate(d: dict) -> bool:
            if user is not None and d.get("user") != user:
                return False
            if action is not None and not str(d.get("action", "")).startswith(action):
                return False
            if result is not None and d.get("result") != result:
                return False
            return True

        return await self._page("action_log", since, until, limit, cursor, predicate)

    # --- stats + purge -----------------------------------------------------

    async def stats(self, since: float | None = None) -> dict:
        errs = await self.core.db.repo.query("error_log", since=since)
        acts = await self.core.db.repo.query("action_log", since=since)
        error_counts = {"warning": 0, "error": 0, "critical": 0}
        subsystems: set[str] = set()
        for r in errs:
            d = r["data"]
            lvl = d.get("level")
            if lvl in error_counts:
                error_counts[lvl] += 1
            if d.get("subsystem"):
                subsystems.add(d["subsystem"])
        failures = sum(1 for r in acts if r["data"].get("result") == "failure")
        users = sorted({r["data"].get("user") for r in acts if r["data"].get("user")})
        return {
            "error_counts": error_counts,
            "action_counts": {"total": len(acts), "failures": failures},
            "subsystems": sorted(subsystems),
            "users": users,
        }

    async def delete_errors(self, before: float) -> int:
        return await self.core.db.repo.delete("error_log", before)

    async def delete_actions(self, before: float) -> int:
        return await self.core.db.repo.delete("action_log", before)

    # --- retention / pruning (LOGS §8) -------------------------------------

    async def prune_once(self) -> dict:
        deleted: dict[str, int] = {}
        now = time.time()
        for rtype, ret in self._retention.items():
            rows = await self.core.db.repo.query(rtype)  # ts asc
            before = _prune_decision(
                rows, ret.get("max_days", 3650), ret.get("max_records", 10**9), now
            )
            if before is not None:
                deleted[rtype] = await self.core.db.repo.delete(rtype, before)
        return deleted

    async def _prune_loop(self) -> None:
        hour = self._pruning.get("run_at_hour_utc", 2)
        while True:
            await asyncio.sleep(self._seconds_until_hour(hour))
            with contextlib.suppress(Exception):
                await self.prune_once()

    @staticmethod
    def _seconds_until_hour(hour: int) -> float:
        now = datetime.now(timezone.utc)
        target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return max(60.0, (target - now).total_seconds())
