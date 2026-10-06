"""docs/templates/run_sim.py is the harness every new app copies (new-test-app, Phase 4).

Guard the lessons baked into it: it must be valid Python, connect the instruments before the
sequencer runs (a hand-written runner forgets this and every read then fails silently), and keep
its two edit blocks, so a skill copy-and-edit stays mechanical.
"""

from __future__ import annotations

import ast
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[2] / "docs" / "templates" / "run_sim.py"


def test_template_is_valid_python():
    ast.parse(TEMPLATE.read_text(encoding="utf-8"))


def test_template_connects_instruments_before_running():
    src = TEMPLATE.read_text(encoding="utf-8")
    assert "connect_all()" in src
    assert src.index("connect_all()") < src.index("seq.run(")


def test_template_has_its_two_edit_blocks():
    src = TEMPLATE.read_text(encoding="utf-8")
    assert "EDIT 1" in src and "INSTRUMENTS" in src
    assert "EDIT 2" in src and "NEGATIVE_CASES" in src
