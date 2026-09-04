"""TMF core — the application platform modules plug into (CORE.md).

__version__ is the FRAMEWORK release (semver; git tag v<version>). It is stamped
into every record + diag event as `source_version`. Policy (docs/TEMPLATE.md):
MAJOR = a module contract_version or locked-contract breaking change;
MINOR = new modules/features; PATCH = fixes.
"""

__version__ = "1.14.0"


def app_version() -> str | None:
    """This deployment's APP version — independent of the framework, starting at 1.0.0
    (TEMPLATE.md two-tier). Frozen: `RELEASE.json` `version` (app track). Source checkout:
    `app/<name>/VERSION`. None for a bare framework run (no app payload). The framework
    version stays `__version__`; the app's own version is what an operator sees + what
    app-track updates compare against."""
    import glob
    import json
    from pathlib import Path
    here = Path(__file__).resolve()               # backend/core/__init__.py (or run.dist/core/…)
    # Frozen: RELEASE.json rides INSIDE the swap unit (run.dist = parents[1]) so an update
    # that swaps run.dist also swaps the version manifest — otherwise app_version would keep
    # reading a stale deploy-root copy the swap never touched. parents[2]/[3] stay as the
    # human-facing deploy-root fallback build_release + launcher keep in sync.
    for rel in (here.parents[1] / "RELEASE.json", here.parents[2] / "RELEASE.json",
                here.parents[3] / "RELEASE.json"):
        try:
            data = json.loads(rel.read_text(encoding="utf-8"))
            if data.get("track") == "app" and data.get("version"):
                return data["version"]
        except (OSError, json.JSONDecodeError, IndexError):
            continue
    repo = here.parents[2]                         # core -> backend -> repo root
    for vf in glob.glob(str(repo / "app" / "*" / "VERSION")):
        try:
            v = Path(vf).read_text(encoding="utf-8").strip()
            if v:
                return v
        except OSError:
            continue
    return None
