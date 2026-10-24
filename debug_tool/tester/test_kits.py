"""Air-gapped kits: the PowerShell must parse, run, produce ONE zip, and `tmf_debug.bundle.analyze` must read it back."""

import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from debug_tool import kits
from debug_tool.tester.test_engine import make_app

PS = shutil.which("powershell") or shutil.which("pwsh")
needs_ps = pytest.mark.skipif(not PS or sys.platform != "win32", reason="PowerShell kits are Windows-only")


def ps_parse_errors(path: Path) -> list[str]:
    cmd = ("$e=$null;$t=$null;[void][System.Management.Automation.Language.Parser]::ParseFile('%s',[ref]$t,[ref]$e);"
           "$e | ForEach-Object { $_.Message }" % str(path).replace("'", "''"))
    r = subprocess.run([PS, "-NoProfile", "-NonInteractive", "-Command", cmd], capture_output=True, text=True, timeout=60)
    return [ln for ln in r.stdout.splitlines() if ln.strip()]


def run_ps(path: Path, *args, timeout=180):
    return subprocess.run([PS, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(path), *args],
                          capture_output=True, text=True, timeout=timeout, cwd=path.parent)


def test_collect_kit_files_are_crlf_and_documented(tmp_path):
    out = kits.collect_kit(tmp_path / "kit")
    assert out["files"] == ["collect.ps1", "README.txt"]
    raw = (tmp_path / "kit" / "collect.ps1").read_bytes()
    assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")
    assert "READ-ONLY" in raw.decode() and b"-StateDir" in raw
    assert "ONE zip" in (tmp_path / "kit" / "README.txt").read_text()


@needs_ps
def test_both_generated_powershell_files_parse_cleanly(tmp_path):
    kits.collect_kit(tmp_path / "c")
    kits.script_kit("Write-Output hi", "powershell", tmp_path / "s")
    assert ps_parse_errors(tmp_path / "c" / "collect.ps1") == []
    assert ps_parse_errors(tmp_path / "s" / "run-script.ps1") == []


def test_script_kit_validation_and_hash(tmp_path):
    with pytest.raises(ValueError, match="interpreter"):
        kits.script_kit("x", "bash", tmp_path / "k")
    with pytest.raises(ValueError, match="empty"):
        kits.script_kit("  \n", "cmd", tmp_path / "k")
    with pytest.raises(ValueError, match="file names"):
        kits.script_kit("x", "cmd", tmp_path / "k", name="a/b")
    out = kits.script_kit("Write-Output 1", "powershell", tmp_path / "k", timeout_s=9999, args=["-x"], name="probe")
    meta = json.loads((tmp_path / "k" / "kit.json").read_text())
    assert meta["timeout_s"] == 300 and meta["script"] == "probe.ps1" and meta["args"] == ["-x"]
    import hashlib
    assert meta["sha256"] == out["sha256"] == hashlib.sha256((tmp_path / "k" / "probe.ps1").read_bytes()).hexdigest()
    assert out["sha256"] in (tmp_path / "k" / "README.txt").read_text()


@needs_ps
def test_script_kit_round_trip_runs_the_script_and_the_analyser_reads_the_result(tmp_path):
    kits.script_kit("Write-Output 'psu1 says hello'\nexit 3", "powershell", tmp_path / "k", name="probe")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    r = run_ps(tmp_path / "k" / "run-script.ps1", "-OutDir", str(out_dir))
    assert "Send this ONE file" in r.stdout, r.stdout + r.stderr
    zips = list(out_dir.glob("tmf-script-*.zip"))
    assert len(zips) == 1
    names = zipfile.ZipFile(zips[0]).namelist()
    assert {"script/result.json", "script/output.txt", "script/probe.ps1"} <= set(n.replace("\\", "/") for n in names)
    from tmf_debug.bundle import analyze
    a = analyze(zips[0], tmp_path / "an")
    assert a["script"]["result"]["exit_code"] == 3 and "psu1 says hello" in a["script"]["output_tail"]
    assert any(f["area"] == "script" and "exited 3" in f["title"] for f in a["findings"])
    assert "psu1 says hello" in Path(a["paths"]["analysis_md"]).read_text()


@needs_ps
def test_script_kit_refuses_a_script_changed_after_the_kit_was_made(tmp_path):
    kits.script_kit("Write-Output safe", "powershell", tmp_path / "k", name="probe")
    (tmp_path / "k" / "probe.ps1").write_text("Write-Output tampered", encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    r = run_ps(tmp_path / "k" / "run-script.ps1", "-OutDir", str(out_dir))
    assert r.returncode == 4 and "sha256 mismatch" in r.stdout and list(out_dir.glob("*.zip")) == []


@needs_ps
def test_script_kit_timeout_kills_the_script_and_says_so(tmp_path):
    kits.script_kit("Start-Sleep -Seconds 60", "powershell", tmp_path / "k", timeout_s=2, name="slow")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    run_ps(tmp_path / "k" / "run-script.ps1", "-OutDir", str(out_dir))
    z = next(out_dir.glob("*.zip"))
    res = json.loads(zipfile.ZipFile(z).read("script/result.json"))
    assert res["timed_out"] is True and res["exit_code"] == -1 and res["elapsed_s"] < 30


@needs_ps
def test_cmd_kit_runs(tmp_path):
    kits.script_kit("@echo off\r\necho from cmd", "cmd", tmp_path / "k", name="c")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    run_ps(tmp_path / "k" / "run-script.ps1", "-OutDir", str(out_dir))
    z = next(out_dir.glob("*.zip"))
    assert "from cmd" in zipfile.ZipFile(z).read("script/output.txt").decode("utf-8")


@needs_ps
def test_collect_ps1_packs_raw_files_when_no_exporter_exists_and_fills_in_the_system_facts(tmp_path):
    app = make_app(tmp_path)                                   # a fake install: run.dist/RELEASE.json, config, data/tmf.sqlite
    (app.state_root / "data" / "launcher.log").write_text("2026-10-15 01:20:58 launcher: swap FAILED: locked\n", encoding="utf-8")
    kits.collect_kit(tmp_path / "kit")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    r = run_ps(tmp_path / "kit" / "collect.ps1", "-StateDir", str(app.state_root), "-OutDir", str(out_dir), "-NoIntegrity")
    assert "Send this ONE file" in r.stdout, r.stdout + r.stderr
    z = next(out_dir.glob("tmf-debug-*.zip"))
    names = {n.replace("\\", "/") for n in zipfile.ZipFile(z).namelist()}
    assert {"system/processes.json", "system/ports.json", "system/odbc.json", "system/health.json"} <= names
    ports = json.loads(zipfile.ZipFile(z).read("system/ports.json"))["ports"]
    assert set(ports) == {"8000", "1883", "8001", "8010", "5173"}
    from tmf_debug.bundle import analyze
    a = analyze(z, tmp_path / "an")                            # the analyser reads a kit-made zip like any other
    assert a["system"]["ports"]["1883"] in (True, False)


@needs_ps
def test_collect_ps1_says_clearly_when_it_cannot_find_the_install(tmp_path):
    kits.collect_kit(tmp_path / "kit")
    r = run_ps(tmp_path / "kit" / "collect.ps1", "-StateDir", "", "-OutDir", str(tmp_path))
    # no running app and nothing near the script: exit 2 with the instruction (a dev PC running the app would find it - accept both)
    assert r.returncode in (0, 2)
    if r.returncode == 2:
        assert "-StateDir" in r.stdout
