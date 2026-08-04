"""The process boundary is real (PYTHON_CONTROLLER.md §0): the controller imports
NOTHING from the framework app. Same language, no compiler to enforce it — so this
test does. It scans every controller source for a forbidden import."""

import re
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "controller"

# backend/ top-level packages the controller must never reach into.
_FORBIDDEN = re.compile(r"^\s*(from|import)\s+(backend|core|modules)\b", re.MULTILINE)


def test_controller_imports_nothing_from_backend():
    offenders = []
    for py in PKG.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        for m in _FORBIDDEN.finditer(text):
            offenders.append(f"{py.relative_to(PKG.parent)}: {m.group(0).strip()}")
    assert offenders == [], "controller reached into the app:\n" + "\n".join(offenders)
