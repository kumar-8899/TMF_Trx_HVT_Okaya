"""Logs `db` variant (LOGS.md §12).

Wires the single error_log sink to the diag bus + the LabVIEW diag topic,
implements record_action and the cursor-paginated queries. REST (L4) and pruning
+ run-event subscriber (L5) land next.
"""

from __future__ import annotations

import base64

from core.framework.contract import CoreServices, Health, HealthStatus
from core.services.auth_verify import Principal
from modules.logs.contract import LEVEL_ORDER, Page
from modules.logs.sink import LogsDiagSink


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
        self.router = None  # built in L4
        # caller 2: LabVIEW diag over MQTT (station-relative topic, our tree).
        self.mqtt_handlers = [("diag", self._on_lv_diag)]

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

    async def stop(self) -> None:
        await self._sink.stop()

    async def health(self) -> Health:
        return Health(status=HealthStatus.OK, detail="logs db variant")

    def _on_lv_diag(self, _topic: str, payload: dict | None) -> None:
        if payload:
            self._sink.receive(payload, source=f"labview:{self.station}")

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
