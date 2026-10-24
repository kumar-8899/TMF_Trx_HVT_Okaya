"""tools/ownership.py - the fork ownership boundary (docs/TEMPLATE.md section 1) as one rule set.

The case table is shared with the frontend widget's tests (frontend/src/test/ownershipCases.json); the two copies
must stay identical, so the Developer Hub widget, `fork_check` and the docs can never disagree."""

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import ownership  # noqa: E402

CASES = json.loads((REPO / "tools" / "ownership_cases.json").read_text(encoding="utf-8"))


def test_shared_fixture_copies_are_identical():
    fe = json.loads((REPO / "frontend" / "src" / "test" / "ownershipCases.json").read_text(encoding="utf-8"))
    assert fe == CASES, "tools/ownership_cases.json and frontend/src/test/ownershipCases.json have drifted"


@pytest.mark.parametrize("path,owner", CASES["cases"])
def test_classify_matches_the_shared_cases(path, owner):
    assert ownership.owner_of(path, CASES["framework_modules"]) == owner


def test_empty_path_is_none():
    assert ownership.classify("   ") is None


def test_unknown_backend_module_is_an_app_module_and_known_is_framework():
    assert ownership.owner_of("backend/modules/acme_eol/x.py", ["recipe"]) == "app"
    assert ownership.owner_of("backend/modules/recipe/x.py", ["recipe"]) == "framework"


def test_framework_modules_are_read_from_manifests():
    mods = ownership.framework_modules()
    assert {"auth", "recipe", "report", "runs", "variables"} <= set(mods)


def test_facts_shape_for_the_developer_hub():
    f = ownership.facts()
    assert f["app_rules"] and all({"pattern", "rule"} <= set(r) for r in f["app_rules"])
    assert "framework" in f["framework_advice"].lower()


def test_generated_facts_carry_the_ownership_rules():
    facts = json.loads((REPO / "docs" / "generated" / "facts.json").read_text(encoding="utf-8"))
    assert facts["ownership"] == ownership.facts()


def test_every_real_app_owned_template_path_is_app_owned():
    """Paths the scaffolding writes into a fork (tools/new_app.py) must not be flagged as framework edits."""
    for p in (".github/workflows/release.yml", "APP_SETUP.md", "backend/config/app.json",
              "backend/modules/acme_eol/__init__.py", "app/acme/controller.json", ".mcp.json"):
        assert ownership.owner_of(p, ownership.framework_modules()) == "app", p
