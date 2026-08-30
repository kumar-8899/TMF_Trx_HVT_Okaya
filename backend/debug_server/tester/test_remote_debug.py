"""REMOTE_DEBUG.md PR-A — bind guard + static-token auth (no core call)."""

import asyncio

import pytest

from debug_server.auth import TokenChecker
from debug_server.config import DebugConfig


def test_from_app_json_reads_debug_block():
    cfg = DebugConfig.from_app_json({
        "stations": ["st2"],
        "debug": {"bind_host": "192.168.1.5", "token": "t", "rolling": {"max_file_mb": 32},
                  "snapshot": {"pre_seconds": 15}},
    })
    assert cfg.station == "st2"
    assert cfg.bind_host == "192.168.1.5" and cfg.token == "t"
    assert cfg.rolling.max_file_mb == 32 and cfg.snapshot.pre_seconds == 15
    # unset sub-config falls back to defaults
    assert cfg.analog.default_deadband_pct == 1.0 and cfg.limits.queue_size == 20_000


def test_validate_truth_table():
    DebugConfig.from_app_json({}).validate()                                   # loopback default: ok
    DebugConfig.from_app_json({"debug": {"bind_host": "10.0.0.2", "token": "x"}}).validate()  # remote+token: ok
    with pytest.raises(ValueError, match="0.0.0.0"):
        DebugConfig.from_app_json({"debug": {"bind_host": "0.0.0.0"}}).validate()
    with pytest.raises(ValueError, match="token is required"):
        DebugConfig.from_app_json({"debug": {"bind_host": "10.0.0.2"}}).validate()


def test_static_token_validated_without_core():
    # core_url points at a dead port — a static-token match must NOT touch it.
    checker = TokenChecker("http://127.0.0.1:59999", require_auth=True, static_token="sekret")
    assert asyncio.run(checker.check("sekret")) is True
    assert asyncio.run(checker.check("wrong")) is False       # falls through to dead core → False
    assert asyncio.run(checker.check(None)) is False


def test_no_auth_bypass_unchanged():
    checker = TokenChecker("http://127.0.0.1:59999", require_auth=False)
    assert asyncio.run(checker.check(None)) is True
