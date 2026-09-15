"""Core cmd handlers (broker-free)."""

import time

from controller.serve import hello_echo, register_maintenance_ops


def test_hello_echo_stamps_and_echoes():
    out = hello_echo({"nonce": "abc", "sent_ts": 100.0})
    assert out["nonce"] == "abc" and out["sent_ts"] == 100.0
    assert out["controller"] == "python"
    assert abs(out["ts"] - time.time()) < 5.0


def test_hello_echo_empty_args():
    out = hello_echo({})
    assert out["controller"] == "python" and "ts" in out


class _FakeClient:
    def __init__(self):
        self.served = {}
        self.published = []

    def serve(self, op, handler, *, blocking=False):
        self.served[op] = handler

    def publish(self, sub, payload, *, qos=1, retain=False):
        self.published.append((sub, payload, retain))


def test_maintenance_enter_exit_serves_and_publishes():
    """#6.2: the Python controller must serve maintenance.enter/exit (was LabVIEW-only)
    and publish the retained state/maintenance snapshot the health module reads."""
    c = _FakeClient()
    state = {"state": "off", "since": None, "by": None, "reason": None}
    register_maintenance_ops(c, state)
    assert "maintenance.enter" in c.served and "maintenance.exit" in c.served

    st = c.served["maintenance.enter"]({"operator": "admin", "reason": "swap fuse"})
    assert st["state"] == "on" and st["by"] == "admin" and st["reason"] == "swap fuse"
    assert state["state"] == "on"                       # shared PC-wide dict updated
    assert c.published[-1] == ("state/maintenance", st, True)   # retained

    off = c.served["maintenance.exit"]({"operator": "admin"})
    assert off["state"] == "off" and state["state"] == "off"
    assert c.published[-1][0] == "state/maintenance" and c.published[-1][2] is True
