"""tools/debug_tool_support_wheel.py - the framework subset a Debug Tool script on a client PC can import."""

import base64
import hashlib
import importlib.util
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("debug_tool_support_wheel", ROOT / "tools" / "debug_tool_support_wheel.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_wheel_carries_dbconn_and_a_valid_record(tmp_path):
    whl = mod.build(tmp_path)
    assert whl.name == f"tmf_support-{mod.framework_version()}-py3-none-any.whl"
    with zipfile.ZipFile(whl) as z:
        names = set(z.namelist())
        assert {"core/__init__.py", "core/services/__init__.py", "core/services/dbconn.py"} <= names
        assert z.read("core/services/dbconn.py") == (ROOT / "backend" / "core" / "services" / "dbconn.py").read_bytes()
        dist = next(n.split("/")[0] for n in names if n.endswith("METADATA"))
        record = z.read(f"{dist}/RECORD").decode().splitlines()
        for line in record:
            path, digest, size = line.split(",")
            if path.endswith("RECORD"):
                assert digest == "" and size == ""
                continue
            data = z.read(path)
            want = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
            assert digest == f"sha256={want}" and int(size) == len(data), path


def test_the_wheel_is_importable_on_its_own(tmp_path):
    pytest.importorskip("sqlalchemy")
    whl = mod.build(tmp_path)
    code = ("import sys; sys.path.insert(0, sys.argv[1]); from core.services import dbconn; "
            "print(dbconn.PROVIDERS, dbconn.__file__.endswith('dbconn.py'))")
    r = subprocess.run([sys.executable, "-I", "-c", code, str(whl)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "sqlserver" in r.stdout and "True" in r.stdout
