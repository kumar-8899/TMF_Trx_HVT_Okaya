"""debug_tool.scripts / files - containment of approved scripts and the bounded, redacted file read."""

import asyncio
import os
import shutil
import sys
import time
from pathlib import Path

import pytest

from debug_tool import files as filesmod
from debug_tool import scripts as sc
from debug_tool.scripts import ScriptBusy, ScriptError, ScriptRunner

SYS_PY = lambda: {"kind": "system", "path": sys.executable, "version": "x", "notes": []}      # noqa: E731
needs_ps = pytest.mark.skipif(not shutil.which("powershell") or sys.platform != "win32", reason="PowerShell is Windows-only")


def runner(tmp_path):
    return ScriptRunner(tmp_path / "scripts", SYS_PY)


def test_environment_is_scrubbed_of_secrets_and_python_overrides():
    env = sc.scrubbed_env({"PATH": "p", "TMF_UPDATE_TOKEN": "t", "MY_API_KEY": "k", "DB_PASSWORD": "x", "PYTHONPATH": "z",
                           "TMF_DEBUG_TOKEN": "d", "SystemRoot": "C:\\Windows", "CONNECTION_STRING": "c"})
    assert env == {"PATH": "p", "SystemRoot": "C:\\Windows"}


def test_encoding_is_what_gets_hashed_and_run():
    ps = sc.encode_script("powershell", "a\nb")
    assert ps.startswith(b"\xef\xbb\xbf") and ps.endswith(b"a\r\nb")
    assert sc.encode_script("cmd", "a\nb") == b"a\r\nb" and sc.encode_script("python", "a\r\nb") == b"a\nb"
    assert sc.sha256_of("python", "print(1)") == sc.sha256_of("python", "print(1)\r\n".strip())
    for bad in (("bash", "x"), ("python", "   "),):
        with pytest.raises(ScriptError):
            sc.encode_script(*bad)
    assert sc.clamp_timeout(None) == 60 and sc.clamp_timeout(9999) == 300 and sc.clamp_timeout(0) == 60 and sc.clamp_timeout(5) == 5
    with pytest.raises(ScriptError):
        sc.check_args(["x"] * 21)


@pytest.mark.asyncio
async def test_runs_a_python_script_and_keeps_the_evidence(tmp_path):
    r = runner(tmp_path)
    res = await r.run("python", "import os, sys\nprint('hello', os.path.basename(os.getcwd()))\nprint('oops', file=sys.stderr)\nsys.exit(3)",
                      approved_by="op")
    assert res["exit_code"] == 3 and "hello scripts" in res["stdout"] and "oops" in res["stderr"] and not res["timed_out"]
    saved = Path(res["script_file"])
    assert saved.is_file() and saved.name.endswith(res["sha256"][:12] + ".py") and saved.parent == tmp_path / "scripts"
    assert saved.read_bytes() == sc.encode_script("python", "import os, sys\nprint('hello', os.path.basename(os.getcwd()))\nprint('oops', file=sys.stderr)\nsys.exit(3)")
    hist = r.history()
    assert len(hist) == 1 and hist[0]["approved_by"] == "op" and hist[0]["exit_code"] == 3 and "stdout" not in hist[0]


@pytest.mark.asyncio
async def test_secrets_in_the_operators_environment_do_not_reach_the_script(tmp_path, monkeypatch):
    monkeypatch.setenv("TMF_UPDATE_TOKEN", "super-secret")
    monkeypatch.setenv("VISIBLE_THING", "ok")
    res = await runner(tmp_path).run("python", "import os\nprint(os.environ.get('TMF_UPDATE_TOKEN'), os.environ.get('VISIBLE_THING'))")
    assert res["stdout"].strip() == "None ok"


@pytest.mark.asyncio
async def test_timeout_kills_the_script_and_its_children(tmp_path):
    marker = tmp_path / "marker.txt"
    script = (f"import subprocess, sys, time\n"
              f"subprocess.Popen([sys.executable, '-c', \"import time; time.sleep(6); open('{marker.as_posix()}', 'w').write('child survived')\"])\n"
              f"time.sleep(60)\n")
    t0 = time.time()
    res = await runner(tmp_path).run("python", script, timeout_s=2)
    assert res["timed_out"] is True and res["exit_code"] == -1 and time.time() - t0 < 20
    await asyncio.sleep(7)
    assert not marker.exists()                                                  # the whole tree died, not just the parent


@pytest.mark.asyncio
async def test_runaway_output_is_stopped_and_the_result_is_capped(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "RAW_LIMIT", 200_000)
    res = await runner(tmp_path).run("python", "while True:\n    print('x' * 1000)", timeout_s=30)
    assert res["output_limit_exceeded"] is True and res["exit_code"] == -1 and res["elapsed_s"] < 25
    assert len(res["stdout"]) <= sc.OUTPUT_CAP + 100


@pytest.mark.asyncio
async def test_large_but_finite_output_keeps_head_and_tail(tmp_path):
    res = await runner(tmp_path).run("python", "print('HEAD')\nprint('y' * 600000)\nprint('TAIL')")
    assert res["output_truncated"] and res["stdout"].startswith("HEAD") and res["stdout"].rstrip().endswith("TAIL") and "bytes omitted" in res["stdout"]


@pytest.mark.asyncio
async def test_one_script_at_a_time(tmp_path):
    r = runner(tmp_path)
    first = asyncio.create_task(r.run("python", "import time\ntime.sleep(2)"))
    await asyncio.sleep(0.5)
    assert r.busy
    with pytest.raises(ScriptBusy):
        await r.run("python", "print(1)")
    assert (await first)["exit_code"] == 0 and not r.busy


@pytest.mark.asyncio
async def test_a_missing_interpreter_is_a_clear_error_and_does_not_leave_the_runner_locked(tmp_path):
    def none():
        from debug_tool.pyenv import PythonUnavailable
        raise PythonUnavailable("no python anywhere")
    r = ScriptRunner(tmp_path / "s", none)
    from debug_tool.pyenv import PythonUnavailable
    with pytest.raises(PythonUnavailable):
        await r.run("python", "print(1)")
    assert not r.busy


@needs_ps
@pytest.mark.asyncio
async def test_powershell_and_cmd_scripts(tmp_path):
    r = runner(tmp_path)
    ps = await r.run("powershell", "Write-Output 'héllo from ps'\n[Console]::Error.WriteLine('bad')\nexit 4")
    assert ps["exit_code"] == 4 and "héllo from ps" in ps["stdout"] and "bad" in ps["stderr"]
    cmd = await r.run("cmd", "@echo off\r\necho from cmd %1", args=["arg one"])
    assert cmd["exit_code"] == 0 and "from cmd" in cmd["stdout"]


# ------------------------------------------------------------------------------------------------ files

def test_read_text_is_bounded_redacted_and_confined(tmp_path):
    root = tmp_path / "deploy"
    (root / "config").mkdir(parents=True)
    (root / "config" / "app.json").write_text('{\n "report_db": {"host": "h", "password": "hunter2"},\n "liquid": 3,\n'
                                              ' "dsn": "Driver={X};Server=h;PWD=s3cret;"\n}\n', encoding="utf-8")
    out = filesmod.read_text("config/app.json", [root])
    assert "hunter2" not in out["text"] and "s3cret" not in out["text"] and "***redacted***" in out["text"]
    assert '"liquid": 3' in out["text"] and out["redacted_values"] >= 2 and not out["truncated"]
    (root / "big.log").write_text("\n".join(f"line {i}" for i in range(50_000)), encoding="utf-8")
    big = filesmod.read_text(root / "big.log", [root])
    assert big["truncated"] and len(big["text"]) <= filesmod.MAX_BYTES
    tail = filesmod.read_text(root / "big.log", [root], tail_lines=3)
    assert tail["text"].splitlines() == ["line 49997", "line 49998", "line 49999"]
    (root / "x.bin").write_bytes(b"\x00\x01\x02" * 100)
    with pytest.raises(filesmod.FileRefused, match="binary"):
        filesmod.read_text(root / "x.bin", [root])
    outside = tmp_path / "secret.txt"
    outside.write_text("nope")
    with pytest.raises(filesmod.FileRefused, match="outside"):
        filesmod.read_text(outside, [root])
    with pytest.raises(filesmod.FileRefused, match="outside"):
        filesmod.read_text(root / ".." / "secret.txt", [root])
    with pytest.raises(filesmod.FileRefused, match="not a file"):
        filesmod.read_text(root / "config", [root])


def test_a_symlink_cannot_lead_out_of_the_root(tmp_path):
    root = tmp_path / "deploy"
    root.mkdir()
    target = tmp_path / "private.txt"
    target.write_text("private")
    try:
        os.symlink(target, root / "link.txt")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks need privileges on this PC")
    with pytest.raises(filesmod.FileRefused, match="outside"):
        filesmod.read_text(root / "link.txt", [root])
