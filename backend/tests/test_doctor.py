"""tools/doctor.py - every check driven by fakes, plus the safe `--fix` behaviour.

The doctor must (a) find the environment faults gotchas.md warns about, and (b) never do anything unsafe while
fixing them: no killing processes, no touching global env vars, no re-pointing the GLOBAL interpreter's editable
installs, no overwriting an existing live config."""

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import doctor  # noqa: E402
from doctor import Check, Ctx  # noqa: E402


def _ctx(tmp_path, **kw) -> Ctx:
    """A tmp fork-shaped repo; every external effect faked (nothing listens, every module found under tmp)."""
    for d in ("backend/core", "backend/instrumentlib", "controller/controller", "tmf_debug", "frontend", "backend/config"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    base = dict(repo=tmp_path, env={"FRAMEWORK_REMOTE": "x", "TMF_INSTRUMENT_LIBRARY": str(tmp_path)},
                version_info=(3, 12, 1), prefix=str(tmp_path / ".venv"), base_prefix="C:/Python312",
                executable=str(tmp_path / ".venv" / "python.exe"), platform="linux",
                port_owner=lambda p: None,
                find_origin=lambda n: str(tmp_path / "x" / f"{n}.py"),
                which=lambda n: f"/bin/{n}", run=lambda cmd, cwd=None, timeout=0: (0, ""))
    base.update(kw)
    return Ctx(**base)


def _by_id(checks):
    return {c.id: c for c in checks}


def test_python_too_old_is_an_error(tmp_path):
    assert doctor.check_python(_ctx(tmp_path, version_info=(3, 10, 0))).severity == "error"
    assert doctor.check_python(_ctx(tmp_path)).ok


def test_venv_states(tmp_path):
    ok = doctor.check_venv(_ctx(tmp_path))
    assert ok.ok                                                      # prefix is under the repo and != base_prefix
    glob = doctor.check_venv(_ctx(tmp_path, prefix="C:/Python312", base_prefix="C:/Python312"))
    assert not glob.ok and "global interpreter" in glob.detail and glob.fixable
    (tmp_path / ".venv").mkdir()
    other = doctor.check_venv(_ctx(tmp_path, prefix="D:/other/.venv"))
    assert not other.ok and "not it" in other.detail and not other.fixable


def test_editable_install_pointing_at_another_fork_is_an_error(tmp_path):
    ctx = _ctx(tmp_path, find_origin=lambda n: r"D:\Other_Fork\backend\core\__init__.py" if n == "core"
               else str(tmp_path / n))
    c = doctor.check_editable(ctx)
    assert not c.ok and c.severity == "error" and "core" in c.detail and "Other_Fork" in c.detail
    assert doctor.check_editable(_ctx(tmp_path)).ok


def test_editable_missing_is_only_a_warning_and_absent_dirs_are_skipped(tmp_path):
    ctx = _ctx(tmp_path, find_origin=lambda n: None)
    c = doctor.check_editable(ctx)
    assert not c.ok and c.severity == "warning"
    assert "debug_tool" not in c.detail                              # that directory is not in this checkout


def test_extras(tmp_path):
    c = doctor.check_extras(_ctx(tmp_path, find_origin=lambda n: None if n == "pyodbc" else "/x"))
    assert not c.ok and "pyodbc" in c.detail and "report-db" in c.detail


def test_frontend_deps(tmp_path):
    ctx = _ctx(tmp_path)
    assert not doctor.check_node(ctx).ok                              # no node_modules yet
    (tmp_path / "frontend" / "node_modules").mkdir()
    assert doctor.check_node(ctx).ok
    assert not doctor.check_node(_ctx(tmp_path, which=lambda n: None)).ok


def test_ports_name_a_foreign_holder_and_recognise_our_own(tmp_path):
    owners = {8000: {"pid": 11, "cmdline": f"python {tmp_path}\\backend\\run.py"},
              8001: {"pid": 22, "cmdline": r"C:\Other\run.exe --debug-server"},
              1883: {"pid": 33, "cmdline": r"C:\tools\mosquitto\mosquitto.exe -c x.conf"},
              8010: {"pid": 44, "cmdline": ""}}
    by = _by_id(doctor.check_ports(_ctx(tmp_path, port_owner=lambda p: owners.get(p))))
    assert by["port_8000"].ok and "THIS repo" in by["port_8000"].detail
    assert not by["port_8001"].ok and "pid 22" in by["port_8001"].detail and "taskkill /PID 22" in by["port_8001"].fix
    assert by["port_1883"].ok and "broker" in by["port_1883"].detail      # a shared broker is not a stray
    assert not by["port_8010"].ok and "command line unknown" in by["port_8010"].detail
    assert by["port_5173"].ok and "free" in by["port_5173"].detail


def test_env_vars(tmp_path):
    by = _by_id(doctor.check_env_vars(_ctx(tmp_path, env={})))
    assert not by["env_FRAMEWORK_REMOTE"].ok and "setx" in by["env_FRAMEWORK_REMOTE"].fix
    by = _by_id(doctor.check_env_vars(_ctx(tmp_path, env={"TMF_INSTRUMENT_LIBRARY": str(tmp_path / "nope")})))
    assert by["env_TMF_INSTRUMENT_LIBRARY"].severity == "error"


def test_live_config_missing_and_drift(tmp_path):
    cfg = tmp_path / "backend" / "config"
    cfg.mkdir(parents=True)
    (cfg / "app.example.json").write_text("{}")
    (cfg / "license.example.json").write_text("{}")
    by = _by_id(doctor.check_config(_ctx(tmp_path)))
    assert not by["live_config"].ok and by["live_config"].fixable
    (cfg / "app.json").write_text("{}")
    (cfg / "license.json").write_text("{}")
    drift = "config doctor: 2 addition(s) (dry-run):\n  + permissions operator: ['SYSTEM.EXIT']\n  + modules: x\n"
    by = _by_id(doctor.check_config(_ctx(tmp_path, run=lambda cmd, cwd=None, timeout=0: (0, drift))))
    assert by["live_config"].ok and not by["config_drift"].ok and "SYSTEM.EXIT" in by["config_drift"].detail
    by = _by_id(doctor.check_config(_ctx(tmp_path, run=lambda cmd, cwd=None, timeout=0: (0, "config doctor: live config is up to date with the examples."))))
    assert by["config_drift"].ok


def test_git_upstream_checks_only_apply_to_forks(tmp_path):
    (tmp_path / ".git").mkdir()
    runs = {("git", "remote"): (0, "upstream\thttps://x/Super_Test_App.git (fetch)\nupstream\thttps://x/Super_Test_App.git (push)\n"),
            ("git", "describe"): (0, "v1.31.1\n")}

    def run(cmd, cwd=None, timeout=0):
        return runs[tuple(cmd[:2]) if cmd[1] == "remote" else ("git", "describe")]
    assert doctor.check_git(_ctx(tmp_path, run=run)) == []            # the framework repo itself (no app/<x>/VERSION)
    (tmp_path / "app" / "acme").mkdir(parents=True)
    (tmp_path / "app" / "acme" / "VERSION").write_text("1.0.0")
    by = _by_id(doctor.check_git(_ctx(tmp_path, run=run)))
    assert not by["git_upstream"].ok and "push-enabled" in by["git_upstream"].detail
    assert by["framework_base_tag"].ok and "v1.31.1" in by["framework_base_tag"].detail
    runs[("git", "remote")] = (0, "upstream\thttps://x/S.git (fetch)\nupstream\tDISABLE (push)\n")
    assert _by_id(doctor.check_git(_ctx(tmp_path, run=run)))["git_upstream"].ok


def test_line_ending_drift_is_reported(tmp_path):
    (tmp_path / ".git").mkdir()
    assert not doctor.check_line_endings(_ctx(tmp_path)).ok           # no .gitattributes
    (tmp_path / ".gitattributes").write_text("*.py text eol=lf\n")
    eol = "i/lf    w/crlf  attr/text eol=lf      \tbackend/a.py\ni/lf    w/lf    attr/text eol=lf      \tbackend/b.py\n"
    c = doctor.check_line_endings(_ctx(tmp_path, run=lambda cmd, cwd=None, timeout=0: (0, eol)))
    assert not c.ok and "backend/a.py" in c.detail and "backend/b.py" not in c.detail
    clean = "i/lf    w/lf    attr/text eol=lf      \tbackend/b.py\n"
    assert doctor.check_line_endings(_ctx(tmp_path, run=lambda cmd, cwd=None, timeout=0: (0, clean))).ok


def test_debug_tool_json_is_validated(tmp_path):
    (tmp_path / "app" / "acme").mkdir(parents=True)
    f = tmp_path / "app" / "acme" / "debug-tool.json"
    f.write_text(json.dumps({"delivery": "bundle", "version": "1.0"}))
    assert doctor.check_debug_tool(_ctx(tmp_path))[0].ok
    f.write_text(json.dumps({"delivery": "maybe"}))
    assert doctor.check_debug_tool(_ctx(tmp_path))[0].severity == "error"
    f.write_text("{not json")
    assert "not valid JSON" in doctor.check_debug_tool(_ctx(tmp_path))[0].detail


def test_debug_tool_pin_is_checked_against_the_shipped_schema_and_a_bundle_pin_needs_a_cached_zip(tmp_path):
    (tmp_path / "app" / "acme").mkdir(parents=True)
    f = tmp_path / "app" / "acme" / "debug-tool.json"
    f.write_text(json.dumps({"delivery": "bundle", "version": "latest"}))
    c = _by_id(doctor.check_debug_tool(_ctx(tmp_path)))["debug_tool_json_acme"]
    assert not c.ok and c.severity == "error" and "version" in c.detail
    f.write_text(json.dumps({"delivery": "bundle", "version": "1.x"}))
    got = _by_id(doctor.check_debug_tool(_ctx(tmp_path)))
    assert got["debug_tool_json_acme"].ok
    zip_check = got["debug_tool_zip_acme"]
    assert not zip_check.ok and zip_check.severity == "warning" and "debug_tool_delivery.py fetch --slug acme" in zip_check.fix
    cache = tmp_path / "tools" / "debug-tool"
    cache.mkdir(parents=True)
    (cache / "tmf-debug-tool-1.0.0.zip").write_bytes(b"PK")
    assert "debug_tool_zip_acme" not in _by_id(doctor.check_debug_tool(_ctx(tmp_path)))
    f.write_text(json.dumps({"delivery": "on-demand"}))                    # nothing to ship, nothing to cache
    assert "debug_tool_zip_acme" not in _by_id(doctor.check_debug_tool(_ctx(tmp_path)))


def test_debug_tool_extra_is_an_info_not_a_failure(tmp_path):
    (tmp_path / "app" / "acme").mkdir(parents=True)
    (tmp_path / "app" / "acme" / "debug-tool.json").write_text(json.dumps({"delivery": "none"}))
    miss = _by_id(doctor.check_debug_tool(_ctx(tmp_path, find_origin=lambda n: None if n == "mcp" else str(tmp_path / "x.py"))))["debug_tool_extra"]
    assert not miss.ok and miss.severity == "info" and "debug-tool" in miss.fix
    assert _by_id(doctor.check_debug_tool(_ctx(tmp_path)))["debug_tool_extra"].ok
    assert "debug_tool_extra" not in _by_id(doctor.check_debug_tool(_ctx(tmp_path / "nopins")))      # no pin, no noise


def test_debug_tool_is_not_an_editable_install(tmp_path):
    assert "debug_tool" not in doctor.EDITABLE                              # it runs as `python -m debug_tool`; there is no package to install


def test_mcp_json_benches_are_probed_when_a_prober_is_given(tmp_path):
    (tmp_path / ".mcp.json").write_text(json.dumps({"mcpServers": {"bench1": {"url": "http://10.0.0.5:8010/mcp"}}}))
    seen = []
    ctx = _ctx(tmp_path, http_ok=lambda u: seen.append(u) or True)
    c = doctor.check_debug_tool(ctx)
    assert seen == ["http://10.0.0.5:8010/debug/health"] and c[0].id == "bench_bench1" and c[0].ok


# --- --fix ------------------------------------------------------------------------------------------

def _recorder():
    calls = []

    def run(cmd, cwd=None, timeout=0):
        calls.append((list(cmd), cwd))
        return 0, ""
    return calls, run


def test_fix_copies_missing_live_config_but_never_overwrites_an_existing_one(tmp_path):
    cfg = tmp_path / "backend" / "config"
    (cfg).mkdir(parents=True)
    (cfg / "app.example.json").write_text('{"a":1}')
    (cfg / "license.example.json").write_text('{"l":1}')
    (cfg / "license.json").write_text('{"mine":true}')                 # already exists: must survive
    calls, run = _recorder()
    ctx = _ctx(tmp_path, run=run)
    checks = [Check("live_config", False, "warning", "x", fixable=True)]
    doctor.apply_fixes(checks, ctx, say=lambda s: None)
    assert json.loads((cfg / "app.json").read_text()) == {"a": 1}
    assert json.loads((cfg / "license.json").read_text()) == {"mine": True}


def test_fix_refuses_editable_installs_into_the_global_interpreter(tmp_path):
    calls, run = _recorder()
    ctx = _ctx(tmp_path, run=run, prefix="C:/Python312", base_prefix="C:/Python312")
    said = []
    done = doctor.apply_fixes([Check("editable_installs", False, "error", "x", fixable=True)], ctx, say=said.append)
    assert calls == []                                                 # nothing was installed anywhere
    assert any("GLOBAL" in s for s in said) and any("skipped" in d for d in done)


def test_fix_runs_editable_installs_inside_a_venv_and_only_for_dirs_that_exist(tmp_path):
    calls, run = _recorder()
    ctx = _ctx(tmp_path, run=run)
    doctor.apply_fixes([Check("editable_installs", False, "error", "x", fixable=True)], ctx, say=lambda s: None)
    targets = [c[0][-1] for c in calls]
    assert "./controller" in targets and "./tmf_debug" in targets and "./backend/instrumentlib" in targets
    assert "./debug_tool" not in targets
    assert all(c[0][:4] == [ctx.executable, "-m", "pip", "install"] for c in calls)


def test_fix_creates_venv_and_stops_so_installs_go_into_the_new_one(tmp_path):
    calls, run = _recorder()
    ctx = _ctx(tmp_path, run=run, prefix="C:/Python312", base_prefix="C:/Python312")
    doctor.apply_fixes([Check("venv", False, "warning", "x", fixable=True),
                        Check("editable_installs", False, "error", "x", fixable=True)], ctx, say=lambda s: None)
    assert [c[0][1:3] for c in calls] == [["-m", "venv"]]              # only the venv; no pip install into the old env


def test_fix_never_kills_anything_and_does_nothing_for_unfixable_failures(tmp_path):
    calls, run = _recorder()
    ctx = _ctx(tmp_path, run=run)
    done = doctor.apply_fixes([Check("port_8001", False, "warning", "x", fix="taskkill /PID 22 /T")], ctx, say=lambda s: None)
    assert calls == [] and done == []


def test_cli_json_and_exit_code(tmp_path, capsys):
    rc = doctor.main(["--json", "--repo", str(tmp_path)])
    out = json.loads(capsys.readouterr().out)
    assert set(out) == {"ok", "checks"} and all({"id", "ok", "severity", "detail"} <= set(c) for c in out["checks"])
    assert rc in (0, 1) and (rc == 0) == out["ok"]


def test_render_lists_the_fix_for_a_failed_check():
    text = doctor.render([Check("a", False, "error", "boom", fix="do x", fixable=True), Check("b", True, "info", "fine")])
    assert "[FAIL] a: boom" in text and "fix: do x" in text and "doctor --fix" in text and "1 error(s)" in text


@pytest.mark.parametrize("name", ["check_python", "check_venv", "check_editable", "check_extras", "check_node", "check_mosquitto"])
def test_each_check_returns_a_well_formed_check_on_the_real_environment(name):
    c = getattr(doctor, name)(Ctx())
    assert isinstance(c, Check) and c.id and c.severity in ("error", "warning", "info")
