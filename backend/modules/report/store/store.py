"""ReportStore — the relational report system-of-record (MySQL / SQL Server).

SQLAlchemy Core, one dialect-agnostic schema + query layer. The sync engine runs in a
thread executor (writes are per-run, low rate; keeps mssql simple). Drivers are imported
lazily by SQLAlchemy on connect, so the app boots without them — `test_connection`
reports a clear "driver not installed" message.

Aggregation runs on the DB server (GROUP BY over indexed columns), so analytics scale to
millions of rows. Unit-level detail (FPY, cycle I-MR) reads a bounded set of lightweight
`report` header rows (no result payload) and reuses the pure analytics functions.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import (
    and_, case, create_engine, delete, distinct, func, insert, select, text, true,
)
from sqlalchemy.engine import URL

from modules.report import analytics as A
from modules.report.store.schema import metadata, report, report_result

_DETAIL_CAP = 50_000     # bounded header rows for FPY / cycle charts


class StoreError(Exception):
    """Report store misconfiguration / connection failure (honest, never a hang)."""


def build_url(cfg: dict) -> URL:
    p = (cfg or {}).get("provider")
    user, pw = cfg.get("user"), cfg.get("password")
    host, db = cfg.get("host"), cfg.get("database")
    if p == "mysql":
        return URL.create("mysql+pymysql", username=user, password=pw, host=host,
                          port=int(cfg.get("port") or 3306), database=db)
    if p == "sqlserver":
        q = {"driver": cfg.get("odbc_driver") or "ODBC Driver 18 for SQL Server",
             "TrustServerCertificate": "yes"}
        return URL.create("mssql+pyodbc", username=user, password=pw, host=host,
                          port=int(cfg.get("port") or 1433), database=db, query=q)
    if p == "sqlite":     # tests only
        return URL.create("sqlite", database=cfg.get("path") or ":memory:")
    raise StoreError(f"unknown DB provider '{p}'")


def _make_engine(cfg: dict):
    url = build_url(cfg)
    kw: dict = {"pool_pre_ping": True, "future": True}
    if url.get_backend_name() == "sqlite":
        kw["connect_args"] = {"check_same_thread": False}
    else:
        kw["pool_recycle"] = 1800
    return create_engine(url, **kw)


class ReportStore:
    def __init__(self, diag=None):
        self.diag = diag
        self._engine = None
        self._cfg: dict | None = None

    # --- lifecycle ---------------------------------------------------------

    @property
    def configured(self) -> bool:
        return self._engine is not None

    def configure(self, cfg: dict | None) -> None:
        self.dispose()
        if cfg and cfg.get("provider"):
            self._cfg = cfg
            self._engine = _make_engine(cfg)

    def dispose(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
        self._engine = self._cfg = None

    async def _run(self, fn, *a):
        return await asyncio.get_running_loop().run_in_executor(None, fn, *a)

    async def test_connection(self, cfg: dict) -> dict:
        def _test():
            try:
                eng = _make_engine(cfg)
            except StoreError as exc:
                return {"ok": False, "status": "error", "detail": str(exc)}
            try:
                with eng.begin() as c:
                    c.execute(text("SELECT 1"))
                    metadata.create_all(c)                # idempotent DDL
                return {"ok": True, "status": "pass", "detail": "connected; schema ready"}
            except ModuleNotFoundError as exc:            # DBAPI driver missing
                return {"ok": False, "status": "error",
                        "detail": f"driver not installed: {exc}"}
            except Exception as exc:  # noqa: BLE001 — honest failure verdict
                return {"ok": False, "status": "fail", "detail": str(exc).splitlines()[0][:300]}
            finally:
                eng.dispose()
        return await self._run(_test)

    async def ensure_schema(self) -> None:
        if not self.configured:
            return
        def _c():
            with self._engine.begin() as c:
                metadata.create_all(c)
        await self._run(_c)

    # --- writes ------------------------------------------------------------

    async def write(self, rep: dict) -> None:
        if not self.configured:
            raise StoreError("report DB not configured")
        await self._run(self._write, rep)

    def _write(self, rep: dict) -> None:
        rid = rep["run_id"]
        header = {k: rep.get(k) for k in (
            "run_id", "station", "serial_no", "model", "operator", "recipe_id",
            "recipe_version", "result", "started_ts", "finished_ts", "business_day",
            "shift_label")}
        header["created_at"] = rep.get("finished_ts")
        rows = rep.get("rows") or []
        with self._engine.begin() as c:
            c.execute(delete(report_result).where(report_result.c.run_id == rid))
            c.execute(delete(report).where(report.c.run_id == rid))      # idempotent re-forward
            c.execute(insert(report).values(**header))
            if rows:
                c.execute(insert(report_result), [{
                    "run_id": rid, "seq": i,
                    "test_name": _s(r.get("test_name")), "test_group": _s(r.get("test_group")),
                    "expected": _s(r.get("expected")), "measured": _s(r.get("measured")),
                    "result": _s(r.get("result")), "unit": _s(r.get("unit")),
                    "cycle_time_ms": _f(r.get("cycle_time_ms")),
                } for i, r in enumerate(rows)])

    # --- reads -------------------------------------------------------------

    async def get_report(self, run_id: str) -> dict | None:
        if not self.configured:
            return None
        return await self._run(self._get, run_id)

    def _get(self, run_id: str) -> dict | None:
        with self._engine.connect() as c:
            h = c.execute(select(report).where(report.c.run_id == run_id)).mappings().first()
            if h is None:
                return None
            rows = c.execute(select(report_result).where(report_result.c.run_id == run_id)
                             .order_by(report_result.c.seq)).mappings().all()
        d = dict(h)
        d["rows"] = [dict(r) for r in rows]
        return d

    async def list_reports(self, **f) -> dict:
        if not self.configured:
            return {"items": [], "total": 0, "next_cursor": None, "configured": False}
        return await self._run(self._list, f)

    def _cycle_ms(self):
        # total cycle time of a run = sum of its test rows' cycle_time_ms
        return (select(func.sum(report_result.c.cycle_time_ms))
                .where(report_result.c.run_id == report.c.run_id).scalar_subquery())

    def _list(self, f: dict) -> dict:
        limit, offset = int(f.pop("limit", 200)), int(f.pop("offset", 0))
        w = self._where(**f)
        with self._engine.connect() as c:
            total = c.execute(select(func.count()).select_from(report).where(w)).scalar() or 0
            items = c.execute(select(report, self._cycle_ms().label("cycle_ms")).where(w)
                              .order_by(report.c.started_ts.desc())
                              .limit(limit).offset(offset)).mappings().all()
        return {"items": [_with_cycle(dict(r)) for r in items], "total": int(total),
                "next_cursor": str(offset + limit) if offset + limit < total else None,
                "configured": True}

    async def report_models(self) -> list[str]:
        if not self.configured:
            return []
        def _q():
            with self._engine.connect() as c:
                return [m for (m,) in c.execute(
                    select(distinct(report.c.model)).where(report.c.model.isnot(None))
                    .where(report.c.model != "").order_by(report.c.model)).all() if m]
        return await self._run(_q)

    # --- full view (flattened test-data matrix) + export -------------------

    async def full_matrix(self, *, limit=500, **f) -> dict:
        if not self.configured:
            return {"fixed": [], "tests": [], "rows": [], "total": 0, "truncated": False, "configured": False}
        return await self._run(self._full, f, limit)

    def _full(self, f: dict, limit: int) -> dict:
        w = self._where(**f)
        with self._engine.connect() as c:
            total = c.execute(select(func.count()).select_from(report).where(w)).scalar() or 0
            runs = c.execute(select(report, self._cycle_ms().label("cycle_ms")).where(w)
                             .order_by(report.c.started_ts.desc()).limit(limit)).mappings().all()
            sub = select(report.c.run_id).where(w).order_by(report.c.started_ts.desc()).limit(limit).subquery()
            rr = report_result
            params = c.execute(select(rr.c.run_id, rr.c.seq, rr.c.test_name, rr.c.expected,
                                      rr.c.measured, rr.c.result, rr.c.unit, rr.c.cycle_time_ms)
                               .join(sub, rr.c.run_id == sub.c.run_id)
                               .order_by(rr.c.run_id, rr.c.seq)).mappings().all()
        names, per_run = [], {}
        for p in params:
            cell = {"expected": p["expected"], "measured": p["measured"], "result": p["result"],
                    "unit": p["unit"], "cycle_s": round(p["cycle_time_ms"] / 1000.0, 3) if p["cycle_time_ms"] else None}
            per_run.setdefault(p["run_id"], {})[p["test_name"]] = cell
            if p["test_name"] and p["test_name"] not in names:
                names.append(p["test_name"])
        fixed = ["serial_no", "model", "recipe_id", "result", "business_day", "shift_label", "finished_ts", "cycle_s"]
        rows = []
        for r in runs:
            base = _with_cycle(dict(r))
            row = {k: base.get(k) for k in ("run_id", *fixed)}
            row.update({n: per_run.get(r["run_id"], {}).get(n) for n in names})
            rows.append(row)
        return {"fixed": fixed, "tests": names, "rows": rows, "total": int(total),
                "truncated": len(runs) < total, "configured": True}

    async def full_csv(self, *, limit=20000, **f) -> bytes:
        m = await self.full_matrix(limit=limit, **f)
        import csv
        import io
        cols = [*m["fixed"], *m["tests"]]
        buf = io.StringIO()
        wr = csv.writer(buf)
        wr.writerow(cols)
        for r in m["rows"]:
            wr.writerow([_cell_str(r.get(k)) for k in cols])
        return buf.getvalue().encode("utf-8")

    # --- analytics (SQL headline + bounded detail) -------------------------

    def _where(self, *, since=None, until=None, model=None, shift=None, operator=None,
               recipe_id=None, result=None, serial=None, date_from=None, date_to=None):
        c = []
        if since is not None: c.append(report.c.started_ts >= since)
        if until is not None: c.append(report.c.started_ts <= until)
        if model: c.append(report.c.model == model)
        if shift: c.append(report.c.shift_label == shift)
        if operator: c.append(report.c.operator == operator)
        if recipe_id: c.append(report.c.recipe_id == recipe_id)
        if result: c.append(report.c.result == result)
        if serial: c.append(report.c.serial_no.like(f"%{serial}%"))     # serial search
        if date_from: c.append(report.c.business_day >= date_from)      # business-day range
        if date_to: c.append(report.c.business_day <= date_to)
        return and_(*c) if c else true()

    async def dashboard(self, *, since=None, until=None, model=None, operator=None, shift=None) -> dict:
        if not self.configured:
            return {"configured": False, "kpis": {}, "passfail_daily": [], "by_model": [],
                    "by_shift": [], "failure_pareto": [], "param_pareto": [], "fpy": {"series": [], "pbar": 0},
                    "cycle": {"histogram": [], "imr": {"points": []}}, "models": [], "operators": [],
                    "shifts": [], "detail_truncated": False}
        return await self._run(self._dashboard, since, until, model, operator, shift)

    def _dashboard(self, since, until, model, operator, shift) -> dict:
        w = self._where(since=since, until=until, model=model, shift=shift, operator=operator)
        is_pass = report.c.result.like("PASS%")
        with self._engine.connect() as c:
            total = c.execute(select(func.count()).select_from(report).where(w)).scalar() or 0
            passed = c.execute(select(func.count()).select_from(report).where(and_(w, is_pass))).scalar() or 0
            aborted = c.execute(select(func.count()).select_from(report).where(and_(w, report.c.result == "ABORTED"))).scalar() or 0
            avg_cycle = c.execute(select(func.avg(report.c.finished_ts - report.c.started_ts)).where(
                and_(w, report.c.finished_ts.isnot(None), report.c.started_ts.isnot(None)))).scalar()

            pf = case((is_pass, 1), else_=0)
            passfail = [{"date": d or "", "pass": int(p), "fail": int(n - p)} for d, n, p in c.execute(
                select(report.c.business_day, func.count(), func.sum(pf)).where(w)
                .group_by(report.c.business_day).order_by(report.c.business_day)).all()]
            by_model = [_grp("model", m, n, p) for m, n, p in c.execute(
                select(report.c.model, func.count(), func.sum(pf)).where(w).group_by(report.c.model)).all()]
            by_shift = [_grp("shift", s, n, p) for s, n, p in c.execute(
                select(report.c.shift_label, func.count(), func.sum(pf)).where(w)
                .where(report.c.shift_label.isnot(None)).where(report.c.shift_label != "")
                .group_by(report.c.shift_label)).all()]

            # parameter Pareto: failing result rows grouped by test_name (indexed)
            rr, fail = report_result, report_result.c.result.notlike("PASS%")
            pareto = [{"name": t or "(unnamed)", "count": int(n)} for t, n in c.execute(
                select(rr.c.test_name, func.count()).select_from(rr.join(report, rr.c.run_id == report.c.run_id))
                .where(and_(w, fail)).group_by(rr.c.test_name).order_by(func.count().desc()).limit(50)).all()]

            # bounded header detail for FPY + cycle (header-only fields)
            det = c.execute(select(report.c.run_id, report.c.serial_no, report.c.result,
                                   report.c.started_ts, report.c.finished_ts, report.c.business_day)
                            .where(w).order_by(report.c.started_ts.desc()).limit(_DETAIL_CAP)).mappings().all()
            models = [m for (m,) in c.execute(select(distinct(report.c.model)).where(report.c.model.isnot(None))).all() if m]
            operators = [o for (o,) in c.execute(select(distinct(report.c.operator)).where(report.c.operator.isnot(None))).all() if o]
            shifts = [s for (s,) in c.execute(select(distinct(report.c.shift_label)).where(report.c.shift_label.isnot(None))).all() if s]

        failed = int(total) - int(passed) - int(aborted)
        det_reports = [dict(r) for r in det]
        kpis = A._kpis(det_reports)                       # units/fpy/retest/median from bounded detail
        kpis.update({"runs": int(total), "passed": int(passed), "failed": failed, "aborted": int(aborted),
                     "yield": round(100 * passed / total, 1) if total else 0.0,
                     "avg_cycle_s": round(float(avg_cycle), 1) if avg_cycle else 0.0})
        return {
            "configured": True,
            "kpis": kpis,
            "passfail_daily": passfail,
            "by_model": by_model,
            "by_shift": by_shift,
            "failure_pareto": _cum(pareto),
            "param_pareto": _cum(pareto),
            "fpy": A._fpy_pchart(det_reports),
            "cycle": A._cycle(det_reports),
            "models": sorted(models), "operators": sorted(operators), "shifts": sorted(shifts),
            "detail_truncated": len(det) >= _DETAIL_CAP,
        }


def _cell_str(v) -> str:
    """Flatten a merged test cell {expected, measured, result, cycle_s} for CSV."""
    if isinstance(v, dict):
        exp, meas, res = v.get("expected"), v.get("measured"), v.get("result")
        s = f"exp {exp} | meas {meas} | {res}"
        if v.get("cycle_s") is not None:
            s += f" | {v['cycle_s']}s"
        return s
    return "" if v is None else str(v)


def _with_cycle(row: dict) -> dict:
    """Total run cycle time (seconds) = sum of the test rows' cycle_time_ms."""
    ms = row.pop("cycle_ms", None)
    row["cycle_s"] = round(float(ms) / 1000.0, 3) if ms else None
    return row


def _s(v):
    return None if v is None else str(v)[:255]


def _f(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _grp(key, name, total, passed):
    total, passed = int(total), int(passed or 0)
    return {key: name or "(none)", "total": total, "passed": passed, "failed": total - passed,
            ("yield" if key == "shift" else "fpy"): round(100 * passed / total, 1) if total else 0.0}


def _cum(items):
    tot = sum(i["count"] for i in items) or 1
    out, cum = [], 0
    for i in items:
        cum += i["count"]
        out.append({**i, "cum_pct": round(100 * cum / tot, 1)})
    return out
