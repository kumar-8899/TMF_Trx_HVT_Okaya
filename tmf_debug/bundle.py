"""Analyse an offline diagnostics bundle (the zip from `run.exe --debug-export` / the TMF Debug Tool's Collect).

    tmf-debug analyze <bundle.zip> [--out .debug] [--name bench1]

Unzips (safely) into `.debug/<name>-<stamp>/` and writes **analysis.json + analysis.md** - the digest a developer
reads (or hands to Claude Code) instead of scrolling raw JSONL:

  versions + environment · the FIRST FAULT of the last run (existing `digest_records`) · recent errors/actions ·
  the instrument table (passive history) · process/port findings (a second controller, a foreign broker) ·
  driver findings · install integrity · config highlights (already redacted) · launcher log highlights ·
  what the bundle could NOT contain (`MANIFEST.missing`) · script output when the bundle came from a script kit ·
  and an ordered "look here first" list.

Pure (stdlib + tmf_debug); never writes outside the target folder; a malformed member never aborts the analysis.
"""

from __future__ import annotations

import gzip
import json
import re
import time
import zipfile
from collections import Counter
from pathlib import Path

from tmf_debug.api import safe_label
from tmf_debug.digest import digest_records
from tmf_debug.instrument import instrument_digest

MAX_RECORDS = 400_000
SEV_ORDER = {"critical": 0, "error": 1, "warning": 2, "info": 3}


class BundleError(Exception):
    pass


def safe_extract(zf: zipfile.ZipFile, dest: Path) -> list[str]:
    """Extract without ever writing outside `dest` (zip-slip) and without absolute/drive paths."""
    dest = dest.resolve()
    names = []
    for info in zf.infolist():
        target = (dest / info.filename).resolve()
        if dest != target and dest not in target.parents:
            raise BundleError(f"unsafe path in bundle: {info.filename!r}")
        if info.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, target.open("wb") as out:
            out.write(src.read())
        names.append(info.filename)
    return names


def _json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _jsonl(path: Path, limit: int | None = None) -> list[dict]:
    rows: list[dict] = []
    opener = (lambda p: gzip.open(p, "rt", encoding="utf-8", errors="replace")) if path.name.endswith(".gz") else \
        (lambda p: p.open("r", encoding="utf-8", errors="replace"))
    try:
        with opener(path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    v = json.loads(line)
                except ValueError:
                    continue
                if isinstance(v, dict):
                    rows.append(v)
                    if limit and len(rows) >= limit:
                        break
    except OSError:
        pass
    return rows


def _finding(severity: str, area: str, title: str, detail: str = "", hint: str = "") -> dict:
    return {"severity": severity, "area": area, "title": title, "detail": detail, "hint": hint}


def _log_rows(path: Path, n: int = 12) -> list[dict]:
    rows = _jsonl(path)
    out = []
    for r in rows[-n:]:
        d = r.get("data") or {}
        out.append({"ts": r.get("ts"), "summary": r.get("summary"),
                    "level": d.get("level"), "subsystem": d.get("subsystem") or d.get("source"),
                    "message": d.get("message") or d.get("action") or r.get("summary"),
                    "context": d.get("context")})
    return out


def _launcher_highlights(path: Path) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    hot = [ln for ln in lines if re.search(r"swap|FAILED|blocked|relaunch|rollback|reconcile|error", ln, re.I)]
    return (hot or lines)[-25:]


def _config_highlights(cfg: dict | None) -> dict:
    if not isinstance(cfg, dict):
        return {}
    mods = {m.get("id"): m for m in cfg.get("modules", []) if isinstance(m, dict)}
    rep = (mods.get("report") or {}).get("config", {})
    ctrl = cfg.get("controller") or {}
    return {"controller_kind": ctrl.get("kind"), "stations": cfg.get("stations"),
            "modules": sorted(k for k in mods if k), "debug": {k: v for k, v in (cfg.get("debug") or {}).items()
                                                                if k in ("enabled", "bind_host", "port", "remote_access")},
            "report_db_provider": (rep.get("db") or {}).get("provider") if isinstance(rep.get("db"), dict) else None}


def _system_findings(root: Path, cfg_hi: dict) -> tuple[list[dict], dict]:
    findings: list[dict] = []
    procs = (_json(root / "system" / "processes.json", {}) or {}).get("processes", [])
    ports = (_json(root / "system" / "ports.json", {}) or {}).get("ports", {})
    odbc = _json(root / "system" / "odbc.json", {}) or {}
    health = _json(root / "system" / "health.json", {}) or {}
    integ = _json(root / "install" / "integrity.json", {}) or {}

    ctrls = [p for p in procs if "--controller" in (p.get("cmdline") or "") or re.search(r"-m\s+controller\b", p.get("cmdline") or "")]
    if len(ctrls) > 1:
        findings.append(_finding("error", "processes", f"{len(ctrls)} controller processes are running",
                                 "; ".join(f"pid {p.get('pid')}" for p in ctrls),
                                 "Two controllers on one broker flicker runs FAIL/PASS. Stop the orphan by PID (never by name); "
                                 "make any hard exit go through core.serve.force_exit."))
    b = ports.get("1883") or {}
    if b.get("listening") and b.get("name") and "mosquitto" not in b["name"].lower():
        findings.append(_finding("error", "ports", f":1883 is held by {b['name']} (pid {b.get('pid')}), not a Mosquitto broker",
                                 b.get("cmdline") or "", "Something else is on the broker port; MQTT clients will talk to the wrong thing."))
    if not b.get("listening"):
        findings.append(_finding("error", "ports", "nothing is listening on :1883 (MQTT broker)",
                                 "", "No broker: the controller, the recorder and the backend cannot talk. Start Mosquitto / the station launcher."))
    p8000 = ports.get("8000") or {}
    if health.get("app_running") is False and not p8000.get("listening"):
        findings.append(_finding("error", "app", "the app was not running when the bundle was collected",
                                 health.get("note") or "", "If it should be up, read launcher.log and the last errors below."))
    ready = ((health.get("readyz") or {}).get("body")) if isinstance(health.get("readyz"), dict) else None
    if isinstance(ready, dict) and ready.get("ready") is False:
        findings.append(_finding("warning", "app", "/readyz says the app is NOT ready",
                                 json.dumps(ready.get("checks") or ready)[:300], "The failing check names the module/link."))
    if integ.get("status") == "MISMATCH":
        bad = (integ.get("modified") or []) + (integ.get("missing") or [])
        findings.append(_finding("error", "install", f"installed files differ from the release they shipped as ({len(bad)})",
                                 ", ".join(bad[:8]), integ.get("note") or "Half-applied update, antivirus quarantine or a manual edit - reinstall the release."))
    if cfg_hi.get("report_db_provider") == "sqlserver" and not odbc.get("drivers"):
        findings.append(_finding("warning", "drivers", "the report database is SQL Server but no SQL Server ODBC driver is installed",
                                 odbc.get("note") or "", "Install 'ODBC Driver 17/18 for SQL Server' on this PC (or use the built-in 'SQL Server' driver)."))
    return findings, {"controllers": len(ctrls), "ports": {k: v.get("listening") for k, v in ports.items()},
                      "odbc_drivers": odbc.get("drivers", []), "integrity": integ.get("status"),
                      "app_running": health.get("app_running")}


def _recorder_records(root: Path) -> tuple[list[dict], list[str]]:
    recs: list[dict] = []
    used: list[str] = []
    for f in sorted((root / "diagnostics").rglob("*")) if (root / "diagnostics").is_dir() else []:
        if f.is_file() and (f.suffix == ".jsonl" or f.name.endswith(".jsonl.gz")) and "snapshot" not in f.name.lower():
            got = _jsonl(f, MAX_RECORDS - len(recs))
            if got:
                recs.extend(got)
                used.append(f.relative_to(root).as_posix())
            if len(recs) >= MAX_RECORDS:
                break
    recs = [r for r in recs if isinstance(r.get("ts"), (int, float)) or r.get("kind")]
    recs.sort(key=lambda r: r.get("ts") or 0)
    return recs, used


def analyze_dir(root: Path) -> dict:
    manifest = _json(root / "MANIFEST.json", {}) or {}
    env = _json(root / "environment.json", {}) or {}
    cfg = _json(root / "config" / "app.json")
    cfg_hi = _config_highlights(cfg)
    findings: list[dict] = []

    records, used = _recorder_records(root)
    digest = digest_records(records, meta={"source_file": ", ".join(used) or None}) if records else None
    first_fault = digest.get("first_fault") if digest else None
    if first_fault:
        findings.append(_finding("error", "run", "first fault of the recorded period",
                                 json.dumps(first_fault, default=str)[:500], "Start here; the digest has the full fault list and waterfalls."))
    if not records:
        findings.append(_finding("warning", "recorder", "the flight recorder holds no records",
                                 "", "Remote debugging was off or never started, so there is no capture - enable Settings -> Remote debugging "
                                     "(or run the Debug Tool) and reproduce the fault."))

    inst_records = [r for r in records if r.get("subsystem") == "instrument"]
    inst_file = root / "logs" / "instrument_events.jsonl"
    if inst_file.is_file():
        seen = {(r.get("seq"), r.get("ts"), r.get("message")) for r in inst_records}
        inst_records += [r for r in _jsonl(inst_file) if (r.get("seq"), r.get("ts"), r.get("message")) not in seen]
    inst = instrument_digest(inst_records)
    for iid, d in inst["instruments"].items():
        if d["state"] in ("faulted", "disconnected", "reconnecting"):
            findings.append(_finding("error", "instruments", f"instrument {iid} ended in state '{d['state']}'",
                                     f"{d['drops']} link drop(s), {d['failed_calls']} failed call(s)", "See the instrument table: last failure cause + traceback tail."))
        elif d["failed_calls"] >= 3:
            findings.append(_finding("warning", "instruments", f"instrument {iid}: {d['failed_calls']} failed calls", "",
                                     "Check recent_failures for the common cause (timeout vs device error)."))

    sys_findings, sys_summary = _system_findings(root, cfg_hi)
    findings += sys_findings

    errors = _log_rows(root / "logs" / "error_log.jsonl", 15)
    actions = _log_rows(root / "logs" / "action_log.jsonl", 10)
    if errors:
        top = Counter((e.get("message") or "")[:100] for e in _jsonl(root / "logs" / "error_log.jsonl"))
        findings.append(_finding("warning", "logs", f"{sum(top.values())} error_log row(s) in the bundle",
                                 "; ".join(f"{m!r} x{c}" for m, c in top.most_common(3)), "Most frequent messages first."))
    launcher = _launcher_highlights(root / "logs" / "launcher.log")

    if manifest.get("missing"):
        findings.append(_finding("info", "bundle", f"{len(manifest['missing'])} item(s) could not be collected",
                                 "; ".join(manifest["missing"][:6]), "These are gaps in the evidence, not clean results."))

    script = None
    sd = root / "script"
    if sd.is_dir():
        script = {"files": sorted(p.name for p in sd.iterdir() if p.is_file()),
                  "result": _json(sd / "result.json"),
                  "output_tail": (lambda t: t[-4000:])((sd / "output.txt").read_text(encoding="utf-8", errors="replace")) if (sd / "output.txt").is_file() else None}
        if script["result"] and script["result"].get("exit_code") not in (0, None):
            findings.append(_finding("warning", "script", f"the collected script exited {script['result'].get('exit_code')}", "", "Output tail below."))

    findings.sort(key=lambda f: SEV_ORDER.get(f["severity"], 9))
    return {
        "schema": "tmf-debug/bundle-analysis/1",
        "analysed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "environment": {k: env.get(k) for k in ("exported_at", "platform", "python", "frozen", "framework_version", "app_version",
                                                   "state_root", "disk_free_gb", "release", "version_error")},
        "config": cfg_hi,
        "recorder": {"files": used, "records": len(records), "first_fault": first_fault,
                     "fault_count": len((digest or {}).get("faults") or []),
                     "time_range": ((digest or {}).get("header") or {}).get("time_range")},
        "instruments": inst,
        "system": sys_summary,
        "recent_errors": errors, "recent_actions": actions, "launcher_highlights": launcher,
        "manifest_missing": manifest.get("missing") or [],
        "script": script,
        "findings": findings,
        "look_here_first": [f"[{f['severity']}] {f['title']}" for f in findings[:8]],
        "_digest": digest,
    }


def render_markdown(a: dict) -> str:
    env, rec, L = a["environment"], a["recorder"], []
    L += ["# Bench diagnostics analysis", "",
          f"App {env.get('app_version')} on framework {env.get('framework_version')} · {env.get('platform')} · "
          f"collected {env.get('exported_at')} · state root `{env.get('state_root')}`", ""]
    L += ["## Look here first", ""] + ([f"{i}. {t}" for i, t in enumerate(a["look_here_first"], 1)] or ["- nothing alarming found in this bundle"]) + [""]
    L += ["## Findings", ""]
    for f in a["findings"]:
        L.append(f"- **{f['severity'].upper()} · {f['area']}** — {f['title']}" + (f" — {f['detail']}" if f["detail"] else ""))
        if f["hint"]:
            L.append(f"  - {f['hint']}")
    if not a["findings"]:
        L.append("- none")
    L += ["", "## Flight recorder", "",
          f"{rec['records']} record(s) from {', '.join(rec['files']) or 'no files'}; {rec['fault_count']} fault(s)."]
    if rec["first_fault"]:
        L += ["", "First fault:", "```json", json.dumps(rec["first_fault"], indent=2, default=str)[:1500], "```"]
    L += ["", "## Instruments", "", a["instruments"]["coverage"], ""]
    for iid, d in a["instruments"]["instruments"].items():
        L.append(f"- **{iid}** — state {d['state']}, {d['drops']} drop(s), {d['calls']} call(s) seen, {d['failed_calls']} failed")
        for fl in d["recent_failures"][-3:]:
            L.append(f"  - {fl['method']} {fl['outcome']}: {fl.get('message')} (cause: {fl.get('cause')})")
    if not a["instruments"]["instruments"]:
        L.append("- no instrument events in the bundle")
    sysm = a["system"]
    L += ["", "## System", "", f"- controllers running: {sysm['controllers']} · app running: {sysm['app_running']} · "
          f"install integrity: {sysm['integrity']}", f"- listening: {', '.join(k for k, v in sysm['ports'].items() if v) or 'none of the watched ports'}",
          f"- SQL Server ODBC drivers: {', '.join(sysm['odbc_drivers']) or 'none'}"]
    L += ["", "## Recent errors (error_log)", ""] + ([f"- {e.get('ts')} [{e.get('level')}] {e.get('subsystem')}: {e.get('message')}" for e in a["recent_errors"]] or ["- none"])
    L += ["", "## Launcher log highlights", ""] + ([f"    {ln}" for ln in a["launcher_highlights"]] or ["- none"])
    if a["manifest_missing"]:
        L += ["", "## Not collected", ""] + [f"- {m}" for m in a["manifest_missing"]]
    if a.get("script"):
        L += ["", "## Script output", "", "```", (a["script"].get("output_tail") or "(no output)"), "```"]
    return "\n".join(L) + "\n"


def analyze(zip_path: Path | str, out_root: Path | str = ".debug", *, name: str | None = None) -> dict:
    """Unzip + analyse; returns the analysis dict with `paths` (folder, analysis.json, analysis.md, digest)."""
    zip_path = Path(zip_path)
    if not zip_path.is_file():
        raise BundleError(f"no such bundle: {zip_path}")
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise BundleError(f"not a zip file: {zip_path} ({exc})") from exc
    label = safe_label(name or zip_path.stem)
    dest = Path(out_root) / f"{label}-{time.strftime('%Y%m%d-%H%M%S')}"
    dest.mkdir(parents=True, exist_ok=True)
    with zf:
        safe_extract(zf, dest)
    a = analyze_dir(dest)
    digest = a.pop("_digest", None)
    paths = {"folder": str(dest), "analysis_json": str(dest / "analysis.json"), "analysis_md": str(dest / "analysis.md")}
    if digest:
        (dest / "digest.json").write_text(json.dumps(digest, indent=2, default=str), encoding="utf-8")
        paths["digest"] = str(dest / "digest.json")
    a["paths"] = paths
    (dest / "analysis.json").write_text(json.dumps(a, indent=2, default=str), encoding="utf-8")
    (dest / "analysis.md").write_text(render_markdown(a), encoding="utf-8")
    return a
