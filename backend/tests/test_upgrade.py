"""tools/upgrade.py against a throw-away upstream + fork (real git; pip/npm/pytest faked)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import upgrade  # noqa: E402


def git(repo, *args, check=True):
    r = subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false", *args],
                       cwd=repo, capture_output=True, text=True)
    if check:
        assert r.returncode == 0, r.stderr
    return r.stdout


def write(repo, rel, text):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def release(up, version, files, changelog_entry):
    for rel, text in files.items():
        write(up, rel, text)
    write(up, "backend/core/__init__.py", f'__version__ = "{version}"\n')
    cl = (up / "CHANGELOG.md").read_text(encoding="utf-8") if (up / "CHANGELOG.md").exists() else "# Changelog\n\n"
    write(up, "CHANGELOG.md", cl.replace("# Changelog\n\n", f"# Changelog\n\n## v{version} - 2026-01-01\n\n{changelog_entry}\n\n", 1))
    git(up, "add", "-A")
    git(up, "commit", "-q", "-m", f"v{version}")
    git(up, "tag", f"v{version}")


@pytest.fixture
def world(tmp_path):
    up = tmp_path / "framework"
    up.mkdir()
    git(up, "init", "-q", "-b", "main")
    manifest = lambda cv: json.dumps({"schema_version": 1, "module": {"id": "recipe", "version": "1.0.0", "contract_version": cv}})  # noqa: E731
    release(up, "1.0.0", {"backend/modules/recipe/manifest.json": manifest(1), "backend/modules/recipe/api.py": "v1\n",
                          "frontend/src/screens/Runs.tsx": "runs v1\n", "docs/TEMPLATE.md": "t\n"}, "First release.")
    fork = tmp_path / "fork"
    git(tmp_path, "clone", "-q", str(up), str(fork))
    git(fork, "remote", "rename", "origin", "upstream")
    write(fork, "app/acme/VERSION", "1.0.0\n")
    write(fork, "app/acme/debug-tool.json", json.dumps({"delivery": "on-demand", "version": "1.0.0"}))
    write(fork, "frontend/src/app/overrides/runs.tsx", 'export default { key: "runs", component: X };\n')
    git(fork, "add", "-A")
    git(fork, "commit", "-q", "-m", "app payload")
    # framework moves on
    release(up, "1.1.0", {"backend/modules/recipe/manifest.json": manifest(2), "backend/modules/recipe/api.py": "v2\n",
                          "frontend/src/screens/Runs.tsx": "runs v2\n"}, "- **New**: a feature.\n- Runs screen reworked.")
    release(up, "1.1.1", {"docs/TEMPLATE.md": "t2\n"}, "- A fix.")
    release(up, "2.0.0", {"docs/TEMPLATE.md": "t3\n"}, "- A breaking change.")
    git(up, "tag", "debug-tool-v1.2.0")
    return up, fork


class FakeRunner:
    def __init__(self, fail_on=None):
        self.calls, self.fail_on = [], fail_on

    def __call__(self, cmd, cwd=None, timeout=0):
        self.calls.append(cmd)
        if self.fail_on and self.fail_on in " ".join(cmd):
            return 1, "boom: " + " ".join(cmd)
        return 0, "ok\n"


def run(fork, to, **kw):
    kw.setdefault("runner", FakeRunner())
    kw.setdefault("doctor_fn", lambda repo: [])
    kw.setdefault("say", lambda s: None)
    return upgrade.run_upgrade(fork, to, **kw)


def test_happy_path_merges_reinstalls_verifies_and_reports_whats_new(world, monkeypatch):
    up, fork = world
    monkeypatch.setattr(upgrade, "_in_venv", lambda: True)
    fr = FakeRunner()
    res = run(fork, "v1.1.0", runner=fr)
    assert res.ok, res.error
    assert upgrade.framework_version(fork) == "1.1.0"
    assert [s["step"] for s in res.steps if not s["ok"]] == []
    cmds = [" ".join(c) for c in fr.calls]
    assert any(c.endswith("tools.config_doctor --apply") for c in cmds)
    assert any("pytest" in c for c in cmds)
    new = res.new
    assert [s["version"] for s in new["changelog"]] == ["1.1.0"]
    assert new["contract_changes"] == [{"module": "recipe", "from": 1, "to": 2}]
    assert new["overrides"] and "runs.tsx" in new["overrides"][0]["override"]
    assert new["debug_tool"] == {"file": "app/acme/debug-tool.json", "pinned": "1.0.0", "newest": "1.2.0", "in_pin": False,
                                 "advice": "bump `version` in app/acme/debug-tool.json"}
    text = upgrade.render_new(new)
    assert "LOG IN AGAIN" in text and "contract" in text.lower() and "Debug Tool" in text


def test_latest_picks_the_newest_tag_of_the_same_major_not_the_next_major(world, monkeypatch):
    monkeypatch.setattr(upgrade, "_in_venv", lambda: False)
    res = run(world[1], "latest", skip_tests=True)
    assert res.ok and res.target == "v1.1.1"
    assert [s["version"] for s in res.new["changelog"]] == ["1.1.1", "1.1.0"]


def test_major_jump_is_refused_without_the_flag_and_allowed_with_it(world, monkeypatch):
    monkeypatch.setattr(upgrade, "_in_venv", lambda: False)
    res = run(world[1], "v2.0.0", skip_tests=True)
    assert not res.ok and "MAJOR" in res.error and upgrade.framework_version(world[1]) == "1.0.0"
    res = run(world[1], "v2.0.0", allow_major=True, skip_tests=True)
    assert res.ok and upgrade.framework_version(world[1]) == "2.0.0"


def test_dirty_tree_stops_before_anything_happens(world):
    _, fork = world
    write(fork, "app/acme/notes.txt", "wip\n")
    res = run(fork, "v1.1.0")
    assert not res.ok and "commit or stash" in res.error and upgrade.framework_version(fork) == "1.0.0"


def test_a_framework_file_edited_downstream_stops_the_upgrade_and_names_it(world):
    _, fork = world
    write(fork, "docs/TEMPLATE.md", "local patch\n")
    git(fork, "add", "-A")
    git(fork, "commit", "-q", "-m", "patch")
    res = run(fork, "v1.1.0")
    assert not res.ok and "docs/TEMPLATE.md" in res.error and "framework-change-request" in res.error
    assert upgrade.framework_version(fork) == "1.0.0"


def test_a_real_merge_conflict_is_listed_with_ownership_and_aborted_cleanly(world, monkeypatch):
    """An app-owned file that upstream ALSO changed conflicts; the repo must end up exactly as it was."""
    up, fork = world
    monkeypatch.setattr(upgrade, "_in_venv", lambda: False)
    # upstream v1.1.2 touches a path the fork treats as app-owned (.github/workflows is fork-local)
    release(up, "1.1.2", {".github/workflows/ci.yml": "upstream ci\n"}, "- ci")
    write(fork, ".github/workflows/ci.yml", "fork ci\n")
    git(fork, "add", "-A")
    git(fork, "commit", "-q", "-m", "fork ci")
    head = git(fork, "rev-parse", "HEAD").strip()
    res = run(fork, "v1.1.2", skip_tests=True)
    assert not res.ok and ".github/workflows/ci.yml" in res.error and "app-owned" in res.error
    assert git(fork, "rev-parse", "HEAD").strip() == head and git(fork, "status", "--porcelain").strip() == ""


def test_keep_conflicts_leaves_the_conflict_in_place(world, monkeypatch):
    up, fork = world
    release(up, "1.1.2", {".github/workflows/ci.yml": "upstream ci\n"}, "- ci")
    write(fork, ".github/workflows/ci.yml", "fork ci\n")
    git(fork, "add", "-A")
    git(fork, "commit", "-q", "-m", "fork ci")
    res = run(fork, "v1.1.2", keep_conflicts=True, skip_tests=True)
    assert not res.ok and "LEFT in place" in res.error
    status = git(fork, "status", "--porcelain")
    assert "AA .github/workflows/ci.yml" in status or "UU .github/workflows/ci.yml" in status
    git(fork, "merge", "--abort")


def test_dry_run_changes_nothing_and_still_reports_whats_coming(world):
    _, fork = world
    head = git(fork, "rev-parse", "HEAD").strip()
    res = run(fork, "v1.1.0", dry_run=True)
    assert res.ok and git(fork, "rev-parse", "HEAD").strip() == head
    assert upgrade.framework_version(fork) == "1.0.0"
    assert res.new["contract_changes"] and any(s["step"] == "dry run" for s in res.steps)


def test_doctor_errors_block_the_upgrade(world):
    _, fork = world
    bad = [{"id": "editable_installs", "ok": False, "severity": "error", "detail": "core imports another fork"}]
    res = run(fork, "v1.1.0", doctor_fn=lambda r: bad)
    assert not res.ok and "doctor" in res.error and upgrade.framework_version(fork) == "1.0.0"


def test_a_failing_test_run_is_reported_and_the_merge_is_not_hidden(world, monkeypatch):
    monkeypatch.setattr(upgrade, "_in_venv", lambda: False)
    res = run(world[1], "v1.1.0", runner=FakeRunner(fail_on="pytest"))
    assert not res.ok and "backend tests fail" in res.error and "ORIG_HEAD" in res.error


def test_installs_are_skipped_outside_a_virtualenv_with_a_pointer(world, monkeypatch):
    monkeypatch.setattr(upgrade, "_in_venv", lambda: False)
    res = run(world[1], "v1.1.0", skip_tests=True)
    inst = next(s for s in res.steps if s["step"].startswith("install"))
    assert "not inside a virtualenv" in inst["detail"]


def test_not_a_fork_is_refused(tmp_path):
    r = tmp_path / "fw"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    res = run(r, "v1.1.0")
    assert not res.ok and "not a fork" in res.error


def test_unknown_or_older_tags_are_clear_errors(world, monkeypatch):
    monkeypatch.setattr(upgrade, "_in_venv", lambda: False)
    assert "not found" in run(world[1], "v9.9.9").error
    run(world[1], "v1.1.0", skip_tests=True)
    assert "not newer" in run(world[1], "v1.0.0").error


def test_changelog_between_is_exclusive_of_old_and_inclusive_of_new():
    text = "# C\n\n## v1.3.0 - d\n\nthree\n\n## v1.2.0 - d\n\ntwo\n\n## v1.1.0 - d\n\none\n"
    assert [s["version"] for s in upgrade.changelog_between(text, "1.1.0", "1.3.0")] == ["1.3.0", "1.2.0"]
    assert upgrade.changelog_between(text, "1.3.0", "1.3.0") == []


def test_semver_ordering_is_numeric_not_lexical():
    assert upgrade.semver("v1.10.0") > upgrade.semver("v1.9.0")
    with pytest.raises(upgrade.UpgradeError):
        upgrade.semver("main")


def test_cli_json_output(world, capsys, monkeypatch):
    monkeypatch.setattr(upgrade, "_in_venv", lambda: False)
    rc = upgrade.main(["--repo", str(world[1]), "--to", "v1.1.0", "--dry-run", "--json"])
    out = json.loads(capsys.readouterr().out)
    # doctor runs for real here; if THIS machine has doctor errors the upgrade correctly refuses - both are valid outcomes
    assert rc in (0, 1) and set(out) == {"ok", "target", "error", "steps", "new"} and (rc == 0) == out["ok"]


def test_a_floating_debug_tool_pin_only_reports_releases_the_fork_does_not_have_yet(world):
    up, fork = world
    from fork_check import Git
    write(fork, "app/acme/debug-tool.json", json.dumps({"delivery": "bundle", "version": "1.x"}))
    git(fork, "fetch", "-q", "upstream", "--tags")
    g = Git(fork)
    news = upgrade.newer_debug_tool(fork, g)                                  # 1.2.0 exists, nothing cached: fetch it
    assert news["newest"] == "1.2.0" and news["in_pin"] is True and "debug_tool_delivery.py fetch --slug acme" in news["advice"]
    cache = fork / "tools" / "debug-tool"
    cache.mkdir(parents=True)
    (cache / "tmf-debug-tool-1.2.0.zip").write_bytes(b"PK")
    assert upgrade.newer_debug_tool(fork, g) is None                          # already cached: no news
    git(up, "tag", "debug-tool-v2.0.0")
    git(fork, "fetch", "-q", "upstream", "--tags")
    major = upgrade.newer_debug_tool(fork, Git(fork))
    assert major["newest"] == "2.0.0" and major["in_pin"] is False and "bump `version`" in major["advice"]


def test_the_upgrade_never_tries_to_pip_install_the_debug_tool_dir():
    text = (REPO / "tools" / "upgrade.py").read_text(encoding="utf-8")
    assert './debug_tool' not in text                                          # runs as `python -m debug_tool`; no pyproject to install
