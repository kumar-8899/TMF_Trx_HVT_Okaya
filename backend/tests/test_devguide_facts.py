"""Developer Hub drift gate — the generated facts must match the code (docs/generated/).

`tools/gen_devguide.py` derives docs/generated/facts.json + facts.md from the version, CHANGELOG,
manifests, permission catalog, controller step-type registry, capability interfaces, controller ops,
route decorators and skills. Because the facts embed the framework version, cutting a release (or
adding a permission/module/op/step type) without regenerating fails here — which is what keeps the
Developer Hub current. Fix: `python tools/gen_devguide.py` and commit the result."""

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / "tools" / "gen_devguide.py"


def test_generated_facts_are_current():
    r = subprocess.run([sys.executable, str(TOOL), "--check"], capture_output=True, text=True, cwd=REPO)
    if r.returncode != 0 and "ModuleNotFoundError" in r.stderr:
        pytest.skip("controller dependencies not installed here (CI installs controller/): "
                    + r.stderr.strip().splitlines()[-1])
    assert r.returncode == 0, r.stderr or r.stdout


def test_facts_cover_the_core_surfaces():
    import json
    facts = json.loads((REPO / "docs" / "generated" / "facts.json").read_text(encoding="utf-8"))
    assert facts["framework"]["version"]
    assert {m["id"] for m in facts["modules"]} >= {"auth", "help", "recipe", "runs"}
    assert any(p["key"] == "HELP.DEV" for p in facts["permissions"])
    assert len(facts["step_types"]) >= 8
    assert any(o["op"] == "instrument.call" and o["blocking"] for o in facts["controller_ops"])
    assert facts["releases"][0]["version"] == facts["framework"]["version"]
