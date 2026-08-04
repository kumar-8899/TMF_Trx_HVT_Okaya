"""Wire envelope — request/reply convention (LABVIEW_BRIDGE.md §5), broker-free."""

from controller.bridge import envelope as e


def test_op_from_topic():
    assert e.op_from_topic("tmf/st1/cmd/hello.echo") == "hello.echo"
    assert e.op_from_topic("tmf/st1/cmd/run.start") == "run.start"
    assert e.op_from_topic("tmf/st1/status") is None
    assert e.op_from_topic("tmf/st1/cmd/resp/abc") is None   # reply topic, 5 levels


def test_decode():
    assert e.decode(b'{"a":1}') == {"a": 1}
    assert e.decode("") is None
    assert e.decode(b"not json") is None
    assert e.decode(b'[1,2]') is None                        # non-object


def test_reply_payload_success_merges_flat():
    r = e.reply_payload({"id": "x1"}, result={"ts": 12.0, "n": 3})
    assert r == {"id": "x1", "ok": True, "ts": 12.0, "n": 3}


def test_reply_payload_error():
    r = e.reply_payload({"id": "x1"}, error={"code": "unknown_op", "message": "no"})
    assert r == {"id": "x1", "ok": False, "error": {"code": "unknown_op", "message": "no"}}
