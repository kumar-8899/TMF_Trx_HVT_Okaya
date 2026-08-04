"""Core cmd handlers (broker-free)."""

import time

from controller.serve import hello_echo


def test_hello_echo_stamps_and_echoes():
    out = hello_echo({"nonce": "abc", "sent_ts": 100.0})
    assert out["nonce"] == "abc" and out["sent_ts"] == 100.0
    assert out["controller"] == "python"
    assert abs(out["ts"] - time.time()) < 5.0


def test_hello_echo_empty_args():
    out = hello_echo({})
    assert out["controller"] == "python" and "ts" in out
