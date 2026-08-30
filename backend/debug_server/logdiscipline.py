"""Logging discipline (REMOTE_DEBUG.md §4) — the gate in front of the rolling sink.

Three kinds of data, three rules (§4). The in-memory ring stays raw + lossless for
live inspection and the digest; what reaches DISK goes through here so the sink stays
bounded and honest:

- Analog (§4.2): never per-sample. Deadband change-logging + a batched periodic
  summary (one record per interval carrying ALL variables) + threshold crossings.
- Digital (§4.3): edges only + a heartbeat + chatter collapse.
- Global suppressors (§4.4): repeat collapse + per-message-type rate limit.

Everything a variable's discipline suppresses is counted into `suppressed`, surfaced
honestly in /debug/health (§5). The performance rule (§5.3) is respected by the
caller: this runs on the sidecar's own ingest task, never on a test step's thread.
"""

from __future__ import annotations

import time
from collections import Counter, defaultdict, deque


def load_variable_meta(app_json: dict) -> dict[str, dict]:
    """name -> {deadband: float|None, range: (min,max)|None} from the variables module
    config in app.json (or the top-level `variables` block, whichever a fork uses)."""
    var_block: dict = {}
    for m in app_json.get("modules", []):
        if m.get("id") == "variables":
            var_block = (m.get("config") or {}).get("variables", {}) or {}
            break
    if not var_block:
        var_block = (app_json.get("variables") or {}) if isinstance(app_json.get("variables"), dict) else {}
    meta: dict[str, dict] = {}
    for name, defn in var_block.items():
        if not isinstance(defn, dict):
            continue
        rng = defn.get("range") or defn.get("clamp")
        rng_t = None
        if isinstance(rng, dict) and rng.get("min") is not None and rng.get("max") is not None:
            rng_t = (float(rng["min"]), float(rng["max"]))
        meta[name] = {"deadband": defn.get("deadband"), "range": rng_t}
    return meta


class LogDiscipline:
    def __init__(self, analog_cfg, digital_cfg, limits_cfg, var_meta: dict[str, dict],
                 emit, *, clock=time.time) -> None:
        self.analog = analog_cfg
        self.digital = digital_cfg
        self.limits = limits_cfg
        self.meta = var_meta or {}
        self._emit = emit                    # callable(dict) -> writes to the rolling sink
        self._clock = clock
        self.suppressed = 0

        # analog state
        self._last_analog: dict[str, float] = {}
        self._acc: dict[str, dict] = {}       # name -> {min,max,sum,n}
        self._last_summary = 0.0
        self._out_of_range: set[str] = set()

        # digital state
        self._last_digital: dict[str, bool] = {}
        self._toggles: dict[str, deque] = defaultdict(deque)
        self._chattering: set[str] = set()
        self._last_heartbeat = 0.0

        # global suppressors
        self._repeat_key = None
        self._repeat_count = 0
        self._rate_bucket: Counter = Counter()
        self._rate_second = 0

    # --- entry -------------------------------------------------------------

    def feed(self, rec: dict, *, active: bool) -> None:
        ts = rec.get("ts") or self._clock()
        if rec.get("kind") == "value":
            name = self._var_name(rec)
            if name is not None:
                self._value(name, rec.get("payload", {}).get("value"), ts)
            self._maybe_summary(ts, active)
            self._maybe_heartbeat(ts)
            return
        # non-value: heartbeat/summary cadence still advances off wall-clock, then the
        # global suppressors decide whether this record reaches disk.
        self._maybe_summary(ts, active)
        self._maybe_heartbeat(ts)
        self._emit_suppressed(rec, ts)

    @staticmethod
    def _var_name(rec: dict) -> str | None:
        sub = rec.get("subtopic") or ""
        return sub[len("value/"):] if sub.startswith("value/") else None

    # --- analog ------------------------------------------------------------

    def _value(self, name: str, value, ts: float) -> None:
        if isinstance(value, bool):
            self._digital(name, value, ts)
            return
        if not isinstance(value, (int, float)):
            self._out({"kind": "value-change", "name": name, "value": value, "ts": ts})
            return
        v = float(value)
        # accumulate the periodic summary (proves the signal was alive)
        a = self._acc.setdefault(name, {"min": v, "max": v, "sum": 0.0, "n": 0})
        a["min"] = min(a["min"], v)
        a["max"] = max(a["max"], v)
        a["sum"] += v
        a["n"] += 1
        # threshold crossings
        self._threshold(name, v, ts)
        # deadband change-logging
        last = self._last_analog.get(name)
        if last is None or abs(v - last) > self._deadband(name):
            self._last_analog[name] = v
            self._out({"kind": "analog-change", "name": name, "value": v, "ts": ts})
        else:
            self.suppressed += 1

    def _deadband(self, name: str) -> float:
        m = self.meta.get(name, {})
        if m.get("deadband") is not None:
            return float(m["deadband"])
        rng = m.get("range")
        if rng:
            return (self.analog.default_deadband_pct / 100.0) * abs(rng[1] - rng[0])
        return 0.0   # no range metadata → log any real change (flat rail still writes nothing)

    def _threshold(self, name: str, v: float, ts: float) -> None:
        rng = self.meta.get(name, {}).get("range")
        if not rng:
            return
        lo, hi = rng
        out = v < lo or v > hi
        was_out = name in self._out_of_range
        if out and not was_out:
            self._out_of_range.add(name)
            self._out({"kind": "threshold", "name": name, "value": v, "edge": "exceed",
                       "limit": {"min": lo, "max": hi}, "ts": ts})
        elif not out and was_out:
            self._out_of_range.discard(name)
            self._out({"kind": "threshold", "name": name, "value": v, "edge": "return",
                       "limit": {"min": lo, "max": hi}, "ts": ts})

    def _maybe_summary(self, ts: float, active: bool) -> None:
        interval = self.analog.summary_interval_run_s if active else self.analog.summary_interval_idle_s
        if not self._acc:
            return
        if self._last_summary == 0.0:
            self._last_summary = ts
            return
        if ts - self._last_summary < interval:
            return
        vars_summary = {n: {"min": a["min"], "max": a["max"],
                            "avg": round(a["sum"] / a["n"], 6) if a["n"] else None, "n": a["n"]}
                        for n, a in self._acc.items()}
        # ONE record per interval carrying ALL variables (§4.2, normative)
        self._out({"kind": "analog-summary", "ts": ts, "interval_s": interval,
                   "active": active, "vars": vars_summary})
        self._acc.clear()
        self._last_summary = ts

    # --- digital -----------------------------------------------------------

    def _digital(self, name: str, value: bool, ts: float) -> None:
        last = self._last_digital.get(name)
        self._last_digital[name] = value
        if last is None or last == value:
            return
        # a transition — chatter-collapse a burst into one record
        dq = self._toggles[name]
        dq.append(ts)
        window = self.digital.chatter_window_ms / 1000.0
        while dq and dq[0] < ts - window:
            dq.popleft()
        if len(dq) > self.digital.chatter_threshold:
            if name not in self._chattering:
                self._chattering.add(name)
                self._out({"kind": "digital-chatter", "name": name, "toggles": len(dq),
                           "window_ms": self.digital.chatter_window_ms, "ts": ts})
            else:
                self.suppressed += 1   # already reported as chattering; collapse the rest
            return
        self._chattering.discard(name)
        self._out({"kind": "digital-edge", "name": name, "value": value, "ts": ts})

    def _maybe_heartbeat(self, ts: float) -> None:
        if not self._last_digital:
            return
        if self._last_heartbeat == 0.0:
            self._last_heartbeat = ts
            return
        if ts - self._last_heartbeat < self.digital.heartbeat_s:
            return
        self._out({"kind": "digital-heartbeat", "ts": ts, "state": dict(self._last_digital)})
        self._last_heartbeat = ts

    # --- global suppressors (non-value records) ----------------------------

    def _emit_suppressed(self, rec: dict, ts: float) -> None:
        # repeat collapse: identical consecutive record → one record + count
        if self.limits.repeat_collapse:
            key = (rec.get("kind"), rec.get("subsystem"), rec.get("level"),
                   rec.get("message"), rec.get("type"))
            if key == self._repeat_key:
                self._repeat_count += 1
                self.suppressed += 1
                return
            if self._repeat_count > 0:
                self._out({"kind": "repeat-collapsed", "of": self._repeat_key,
                           "count": self._repeat_count, "ts": ts})
            self._repeat_key = key
            self._repeat_count = 0

        # per-message-type rate limit
        second = int(ts)
        if second != self._rate_second:
            self._rate_second = second
            self._rate_bucket.clear()
        rtype = rec.get("subsystem") or rec.get("type") or rec.get("kind") or "?"
        self._rate_bucket[rtype] += 1
        if self._rate_bucket[rtype] > self.limits.per_type_rate_per_s:
            self.suppressed += 1
            if self._rate_bucket[rtype] == self.limits.per_type_rate_per_s + 1:
                self._out({"kind": "rate-limited", "type": rtype,
                           "cap_per_s": self.limits.per_type_rate_per_s, "ts": ts})
            return

        self._out(rec)

    # --- sink --------------------------------------------------------------

    def _out(self, record: dict) -> None:
        self._emit(record)
