"""The fork ownership boundary (docs/TEMPLATE.md section 1) as ONE machine-readable rule set.

An application fork may only create/edit **app-owned** paths; everything else is **framework-owned** and
changes through a framework release. The rules used to live only in a frontend widget
(`frontend/src/components/help/widgets/Ownership.tsx` `classifyPath`). They live here now and are consumed by

  - `tools/gen_devguide.py`  -> emitted into docs/generated/facts.json (the Developer Hub widget reads them there),
  - `tools/fork_check.py`    -> "did this fork edit a framework-owned file?",
  - `tools/doctor.py` / `tools/upgrade.py` -> preflight.

Pure and dependency-free (stdlib only). The shared test fixture `tools/ownership_cases.json` is mirrored in
`frontend/src/test/ownershipCases.json`; a test fails if the two copies differ.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# (regex, human description). Order matters: first match wins, after the app-module check below.
APP_RULES: list[tuple[str, str]] = [
    (r"^app/[^/]+(/|$)", "app/<name>/ — the app payload (step types, variable maps, recipes, controller.json, specs)"),
    (r"^instrument_libs(/|$)", "instrument_libs/ — drivers this app copied from the central Instrument_Library"),
    (r"^frontend/src/app/overrides(/|$)", "frontend/src/app/overrides/ — per-app screens and pages"),
    (r"^labview/App(/|$)", "labview/App/ — application LabVIEW (test cases, HAL)"),
    (r"^backend/config/(app|license)\.json$", "live station config + license (gitignored; the framework ships *.example.json)"),
    (r"^backend/config/known_issues(/|$)", "site data"),
    (r"^backend/data(/|$)", "runtime data (gitignored)"),
    # Fork-local files (v1.32.0): things a fork creates for itself and the framework never ships in its own form.
    (r"^\.github/workflows/", "the fork's own CI/release workflows (copied from docs/templates/)"),
    (r"^(CLAUDE|README|APP_SETUP|CONTRIBUTING)\.md$", "fork-level documents"),
    (r"^\.mcp\.json$", "the fork's MCP client config (no secrets)"),
    (r"^docs/framework-cr(/|$)", "framework change requests this fork has raised"),
]

FRAMEWORK_ADVICE = ("Framework-owned. Don't patch it in the fork — change it in the framework repo and cut a release, "
                    "then `git fetch upstream --tags && git merge vX.Y.Z`. A downstream patch makes every later merge conflict.")
APP_ADVICE = "Yours — edit freely; framework merges never touch it."


def normalise(raw: str) -> str:
    return re.sub(r"^\.?/", "", raw.strip().replace("\\", "/"))


def framework_modules(root: Path | None = None) -> list[str]:
    """Ids of the standard framework modules in a checkout (a dir under backend/modules with a manifest.json)."""
    base = (root or REPO) / "backend" / "modules"
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if (p / "manifest.json").is_file())


def classify(raw: str, modules: list[str] | None = None) -> dict | None:
    """-> {owner: "app"|"framework", rule, advice}, or None for an empty path.

    `modules` = ids of the framework modules; any OTHER backend/modules/<x>/ is an app module (TEMPLATE.md:
    prefix app modules with the app name so upstream can never collide)."""
    path = normalise(raw)
    if not path:
        return None
    modules = framework_modules() if modules is None else modules
    mod = re.match(r"^backend/modules/([^/]+)(/|$)", path)
    if mod and mod.group(1) not in modules:
        return {"owner": "app", "rule": f"backend/modules/{mod.group(1)}/ — an app-specific backend module",
                "advice": "Yours. Keep the app-name prefix (e.g. acme_eol) so a later framework module can never collide."}
    for pattern, rule in APP_RULES:
        if re.match(pattern, path):
            return {"owner": "app", "rule": rule, "advice": APP_ADVICE}
    return {"owner": "framework",
            "rule": (f"backend/modules/{mod.group(1)}/ — a standard framework module" if mod else
                     "everything outside the app-owned paths (core, controller, frontend screens, docs, deploy, tools …)"),
            "advice": FRAMEWORK_ADVICE}


def owner_of(raw: str, modules: list[str] | None = None) -> str | None:
    v = classify(raw, modules)
    return v["owner"] if v else None


def facts() -> dict:
    """The rule set in the shape the Developer Hub consumes (docs/generated/facts.json `ownership`)."""
    return {
        "app_rules": [{"pattern": p, "rule": r} for p, r in APP_RULES],
        "framework_advice": FRAMEWORK_ADVICE,
        "app_advice": APP_ADVICE,
    }


if __name__ == "__main__":   # python tools/ownership.py <path> [<path> ...]
    import sys
    for arg in sys.argv[1:]:
        print(json.dumps({"path": arg, **(classify(arg) or {})}, ensure_ascii=False))
