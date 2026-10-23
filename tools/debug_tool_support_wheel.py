"""Build `tmf_support-<framework version>-py3-none-any.whl` - the framework code a Debug Tool script may import.

The Debug Tool's bundled interpreter (python.org embeddable package) installs every wheel in its `wheelhouse/` by unzipping it
(debug_tool/pyenv.py). This wheel carries `core.services.dbconn` - the same SQL Server / MySQL connection code the app uses - so a
script run on a client PC can test the report database exactly as the app would, without Python or the framework being installed
there. It needs only SQLAlchemy (+ PyMySQL / pyodbc for the server types), which the build adds to the same wheelhouse.

    python tools/debug_tool_support_wheel.py <out_dir>        # prints the wheel path
"""

from __future__ import annotations

import base64
import hashlib
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = "tmf_support"


def framework_version(root: Path = ROOT) -> str:
    text = (root / "backend" / "core" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    if not m:
        raise SystemExit("cannot read the framework version from backend/core/__init__.py")
    return m.group(1)


def _record_line(path: str, data: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
    return f"{path},sha256={digest},{len(data)}"


def build(out_dir: Path | str, root: Path = ROOT) -> Path:
    version = framework_version(root)
    dbconn = (root / "backend" / "core" / "services" / "dbconn.py").read_bytes()
    dist = f"{NAME}-{version}.dist-info"
    files: dict[str, bytes] = {
        "core/__init__.py": b'"""Subset of the TMF core shipped for Debug Tool scripts (tmf_support wheel): core.services.dbconn only."""\n',
        "core/services/__init__.py": b"",
        "core/services/dbconn.py": dbconn,
        f"{dist}/METADATA": (f"Metadata-Version: 2.1\nName: {NAME}\nVersion: {version}\nSummary: TMF framework subset for Debug Tool scripts\n"
                             "Requires-Dist: SQLAlchemy (>=2.0)\n").encode(),
        f"{dist}/WHEEL": b"Wheel-Version: 1.0\nGenerator: tmf-debug-tool\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
    }
    record = [_record_line(p, d) for p, d in files.items()] + [f"{dist}/RECORD,,"]
    files[f"{dist}/RECORD"] = ("\n".join(record) + "\n").encode()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    wheel = out / f"{NAME}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w", zipfile.ZIP_DEFLATED) as z:
        for path, data in files.items():
            z.writestr(path, data)
    return wheel


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    print(build(sys.argv[1]))
