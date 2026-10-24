"""debug_tool.compat - what the tool says about an app version it was not tested with."""

import asyncio
import json

import pytest

from debug_tool import compat
from debug_tool.engine import Engine, EngineConfig
from debug_tool.tester.test_engine import fake_subscriber, make_app

C = {"tool_version": "1.0.0", "framework": {"min": "1.0.0", "max_tested": "1.32.0"}}


def test_inside_the_tested_range_is_ok():
    for v in ("1.0.0", "1.31.1", "v1.32.0", "1.32"):
        assert compat.check(v, C)["status"] == "ok", v


def test_newer_older_and_unknown_never_raise_and_say_what_it_means():
    newer = compat.check("1.40.0", C)
    assert newer["status"] == "newer" and "1.32.0" in newer["note"] and "update the Debug Tool" in newer["note"]
    assert compat.check("0.9.0", C)["status"] == "older"
    unk = compat.check(None, C)
    assert unk["status"] == "unknown" and "assuming" in unk["note"]
    assert compat.check("garbage", C)["status"] == "unknown"
    assert compat.check("1.0.0", {})["status"] == "ok"                      # no COMPAT info = no complaint


def test_the_shipped_compat_file_is_valid_and_matches_the_tool_version():
    from debug_tool import VERSION
    c = compat.load()
    assert c["schema"] == "tmf-debug-tool/compat/1" and c["tool_version"] == VERSION
    assert compat._tuple(c["framework"]["min"]) <= compat._tuple(c["framework"]["max_tested"])


@pytest.mark.asyncio
async def test_health_carries_the_compat_verdict(tmp_path):
    app = make_app(tmp_path)
    (app.bundle_root / "RELEASE.json").write_text(json.dumps({"product": "acme", "version": "2.0.0", "framework_version": "9.9.9"}))
    from debug_tool.appinfo import discover
    app = discover(app.state_root, processes=lambda: [])
    eng = Engine(EngineConfig(app=app, data_dir=tmp_path / "t"), subscriber=fake_subscriber([]))
    await eng.start()
    await asyncio.sleep(0.05)
    try:
        h = eng.health()["compat"]
        assert h["status"] == "newer" and h["tested_up_to"]
    finally:
        await eng.stop()
