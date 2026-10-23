"""tmf-debug-tool CLI: collect/analyze/kit, the operator commands against a really running `serve`, and the stdio MCP."""

import json
import socket
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import httpx
import pytest

from debug_tool import cli
from debug_tool.tester.test_engine import make_app

ROOT = Path(__file__).resolve().parents[2]


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def run_cli(*args, timeout=120):
    return subprocess.run([sys.executable, "-m", "debug_tool", *args], capture_output=True, text=True, timeout=timeout, cwd=ROOT)


def test_collect_writes_one_zip_and_analyze_reads_it_back(tmp_path, capsys):
    app = make_app(tmp_path)
    out = tmp_path / "out"
    assert cli.main(["collect", str(out), "--state-dir", str(app.state_root), "--no-integrity", "--rows", "100"]) == 0
    printed = capsys.readouterr().out
    zips = list(out.glob("tmf-debug-*.zip"))
    assert len(zips) == 1 and str(zips[0]) in printed and "Send this ONE file" in printed
    assert "MANIFEST.json" in zipfile.ZipFile(zips[0]).namelist()
    assert cli.main(["analyze", str(zips[0]), "--out", str(tmp_path / ".debug")]) == 0
    text = capsys.readouterr().out
    assert "analysis:" in text and (list((tmp_path / ".debug").glob("*/analysis.md")))


def test_collect_without_an_install_is_a_clear_error(tmp_path, capsys):
    assert cli.main(["collect", str(tmp_path / "o.zip"), "--state-dir", str(tmp_path / "nowhere")]) == 2
    assert "no app install found" in capsys.readouterr().err


def test_analyze_a_non_zip_is_a_clean_error(tmp_path, capsys):
    bad = tmp_path / "x.zip"
    bad.write_text("nope")
    assert cli.main(["analyze", str(bad), "--out", str(tmp_path)]) == 2
    assert "not a zip" in capsys.readouterr().err


def test_kit_commands(tmp_path, capsys):
    assert cli.main(["kit", "collect", "--out", str(tmp_path / "kc")]) == 0
    assert (tmp_path / "kc" / "collect.ps1").is_file()
    script = tmp_path / "probe.ps1"
    script.write_text("Write-Output hi", encoding="utf-8")
    assert cli.main(["kit", "script", "--script", str(script), "--out", str(tmp_path / "ks"), "--timeout", "30"]) == 0
    assert json.loads((tmp_path / "ks" / "kit.json").read_text())["script"] == "probe.ps1"
    assert cli.main(["kit", "script"]) == 2


def wait_http(url, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if httpx.get(url, timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise AssertionError(f"{url} never came up")


def test_serve_and_the_operator_commands_end_to_end(tmp_path):
    app = make_app(tmp_path)
    port = free_port()
    data = tmp_path / "tooldata"
    p = subprocess.Popen([sys.executable, "-m", "debug_tool", "serve", "--state-dir", str(app.state_root), "--port", str(port),
                          "--data-dir", str(data), "--approval-timeout", "20", "--no-window"], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        wait_http(f"http://127.0.0.1:{port}/healthz")
        assert (data / "operator.json").is_file()
        # off by default
        assert httpx.get(f"http://127.0.0.1:{port}/debug/health", headers={"Authorization": "Bearer x"}).status_code == 403
        r = run_cli("share", "--data-dir", str(data), "--hours", "1", "--name", "Bench One")
        assert r.returncode == 0 and "claude mcp add --transport http bench-one" in r.stdout and "Authorization: Bearer" in r.stdout
        token = r.stdout.split("Bearer ")[1].split('"')[0]
        ok = httpx.get(f"http://127.0.0.1:{port}/debug/health", headers={"Authorization": f"Bearer {token}"})
        assert ok.status_code == 200 and ok.json()["app"]["product"] == "acme"
        assert "nothing waiting" in run_cli("approvals", "--data-dir", str(data)).stdout
        assert run_cli("approve", "nope", "--data-dir", str(data)).returncode == 1
        assert "Sharing stopped" in run_cli("stop", "--data-dir", str(data)).stdout
        assert httpx.get(f"http://127.0.0.1:{port}/debug/health", headers={"Authorization": f"Bearer {token}"}).status_code == 403
    finally:
        p.terminate()
        try:
            p.wait(15)
        except subprocess.TimeoutExpired:
            p.kill()


def test_operator_command_without_a_running_tool_says_so(tmp_path):
    r = run_cli("approvals", "--data-dir", str(tmp_path / "none"))
    assert r.returncode == 2 and "no running tool found" in r.stderr


def test_serve_refuses_to_listen_on_all_interfaces(tmp_path):
    app = make_app(tmp_path)
    r = run_cli("serve", "--bind", "0.0.0.0", "--no-window", "--state-dir", str(app.state_root), "--data-dir", str(tmp_path / "d"))
    assert r.returncode != 0 and "specific address" in (r.stderr + r.stdout)


@pytest.mark.asyncio
async def test_stdio_mcp_makes_kits_and_analyses_inside_the_working_folder(tmp_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    app = make_app(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    zip_path = tmp_path / "b.zip"
    from debug_server.export import export_bundle
    export_bundle(zip_path, state_root=app.state_root, rows=50, integrity=False)
    params = StdioServerParameters(command=sys.executable, args=["-m", "debug_tool", "mcp-stdio", "--workdir", str(work)], cwd=str(ROOT))
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            names = {t.name for t in (await s.list_tools()).tools}
            assert names == {"bench_collect_kit", "bench_script_kit", "bench_analyze_bundle"}

            def data(res):
                assert not res.isError, res.content
                return json.loads(res.content[0].text)
            kit = data(await s.call_tool("bench_collect_kit", {}))
            assert kit["ok"] and (work / ".debug" / "kit-collect" / "collect.ps1").is_file()
            sk = data(await s.call_tool("bench_script_kit", {"script": "Get-Process | Select -First 1", "interpreter": "powershell", "name": "p"}))
            assert sk["ok"] and sk["data"]["sha256"]
            escape = data(await s.call_tool("bench_collect_kit", {"out_dir": "../outside"}))
            assert escape["ok"] is False and "outside the working folder" in escape["error"]["message"]
            bad = data(await s.call_tool("bench_script_kit", {"script": "x", "interpreter": "bash"}))
            assert bad["ok"] is False and bad["error"]["type"] == "ValueError"
            an = data(await s.call_tool("bench_analyze_bundle", {"zip_path": str(zip_path)}))
            assert an["ok"] and "untrusted_content" in an and an["data"]["paths"]["analysis_md"].startswith(str(work))
            missing = data(await s.call_tool("bench_analyze_bundle", {"zip_path": str(tmp_path / "none.zip")}))
            assert missing["ok"] is False and missing["error"]["type"] == "BundleError"
