"""`tmf-debug-tool selftest` - the release gate for the frozen build and the field check for a client PC."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from debug_tool import selftest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.asyncio
async def test_selftest_passes_end_to_end_without_touching_a_real_app():
    steps = await selftest.selftest_async()
    bad = [s for s in steps if s.status == selftest.FAIL]
    assert not bad, selftest.render(steps)
    names = {s.name for s in steps}
    assert {"off by default", "token", "token cannot approve", "mcp handshake", "passive tool", "action waits for approval", "deny",
            "no answer = denied", "collect + analyze", "stop"} <= names
    assert not selftest.render(steps).startswith("FAIL")


def test_cli_selftest_json_and_exit_code():
    r = subprocess.run([sys.executable, "-m", "debug_tool", "selftest", "--json"], capture_output=True, text=True, timeout=240, cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr
    out = json.loads(r.stdout)
    assert out["ok"] is True and any(s["name"] == "mcp handshake" and s["status"] == "pass" for s in out["steps"])


def test_require_python_means_the_bundled_interpreter_not_just_any_python(tmp_path):
    import asyncio
    from debug_tool.tester.make_embed import build_embeddable_like
    if sys.platform != "win32":
        pytest.skip("embeddable package is Windows-only")
    tool = tmp_path / "tool"
    tool.mkdir()
    (tool / "python-embed-3.12.zip").write_bytes(build_embeddable_like(tmp_path / "e").read_bytes())
    steps = asyncio.run(selftest.selftest_async(require_python=True, tool_dir=tool))
    py = next(s for s in steps if s.name == "python script")
    assert py.status == selftest.PASS and "bundled" in py.detail            # extracted from the zip and used, not the system Python
    steps = asyncio.run(selftest.selftest_async(require_python=True, tool_dir=tmp_path / "no-zip-here"))
    py = next(s for s in steps if s.name == "python script")
    assert py.status == selftest.FAIL and "BUNDLED" in py.detail           # this PC has a system Python, which is not good enough for a release


def test_require_python_turns_a_missing_interpreter_into_a_failure(tmp_path, monkeypatch):
    from debug_tool import pyenv
    monkeypatch.setattr(pyenv.PythonEnv, "status", lambda self: {"will_use": "none"})
    import asyncio
    steps = asyncio.run(selftest.selftest_async(require_python=True, tool_dir=tmp_path))
    py = next(s for s in steps if s.name == "python script")
    assert py.status == selftest.FAIL and "no Python" in py.detail
    steps = asyncio.run(selftest.selftest_async(require_python=False, tool_dir=tmp_path))
    assert next(s for s in steps if s.name == "python script").status == selftest.SKIP
