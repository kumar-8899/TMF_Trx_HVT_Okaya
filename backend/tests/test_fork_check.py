"""tools/fork_check.py against a throw-away git repo shaped like a fork of a framework tag."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import fork_check  # noqa: E402


def git(repo, *args):
    r = subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false", *args],
                       cwd=repo, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


def write(repo, rel, text="x\n"):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


@pytest.fixture
def fork(tmp_path):
    """A repo at framework tag v1.0.0 plus an app payload (the shape a fork has)."""
    r = tmp_path / "fork"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    write(r, "backend/core/app.py", "core v1\n")
    write(r, "backend/modules/recipe/manifest.json", "{}")
    write(r, "backend/modules/recipe/api.py", "recipe v1\n")
    write(r, "docs/TEMPLATE.md", "doc\n")
    write(r, "deploy/cut-release.ps1", "rel\n")
    git(r, "add", "-A")
    git(r, "commit", "-q", "-m", "framework v1.0.0")
    git(r, "tag", "v1.0.0")
    write(r, "app/acme/VERSION", "1.0.0\n")
    write(r, "app/acme/controller.json", "{}")
    write(r, "backend/modules/acme_eol/api.py", "app module\n")
    write(r, ".github/workflows/release.yml", "ci\n")
    git(r, "add", "-A")
    git(r, "commit", "-q", "-m", "app payload")
    return r


def test_a_clean_fork_has_no_findings(fork):
    res = fork_check.check(fork)
    assert res["fork"] and res["base"] == "v1.0.0" and res["framework_edits"] == [] and res["ok"]
    assert "clean" in fork_check.render(res)


def test_one_app_edit_and_one_framework_edit_gives_exactly_one_finding(fork):
    write(fork, "app/acme/controller.json", '{"edited": true}')          # app-owned: fine
    write(fork, "backend/modules/acme_eol/api.py", "more app\n")          # app module: fine
    write(fork, "backend/core/app.py", "core PATCHED\n")                  # framework-owned: a finding
    git(fork, "add", "-A")
    git(fork, "commit", "-q", "-m", "oops")
    res = fork_check.check(fork)
    assert res["framework_edits"] == [{"path": "backend/core/app.py", "change": "modified", "severity": "error"}]
    assert not res["ok"]
    text = fork_check.render(res)
    assert "backend/core/app.py" in text and "framework-change-request" in text


def test_uncommitted_edits_are_included(fork):
    write(fork, "deploy/cut-release.ps1", "local tweak\n")                # not committed yet
    res = fork_check.check(fork)
    assert [e["path"] for e in res["framework_edits"]] == ["deploy/cut-release.ps1"]


def test_deleted_and_renamed_framework_files_are_errors_added_is_a_warning(fork):
    git(fork, "rm", "-q", "docs/TEMPLATE.md")
    git(fork, "mv", "backend/modules/recipe/api.py", "backend/modules/recipe/api2.py")
    write(fork, "docs/my_notes.md", "mine\n")
    git(fork, "add", "-A")
    git(fork, "commit", "-q", "-m", "changes")
    by = {e["path"]: e for e in fork_check.check(fork)["framework_edits"]}
    assert by["docs/TEMPLATE.md"]["change"] == "deleted" and by["docs/TEMPLATE.md"]["severity"] == "error"
    assert by["backend/modules/recipe/api2.py"]["change"] == "renamed" and by["backend/modules/recipe/api2.py"]["severity"] == "error"
    assert by["docs/my_notes.md"] == {"path": "docs/my_notes.md", "change": "added", "severity": "warning"}
    assert fork_check.check(fork)["ok"] is False


def test_only_warnings_means_ok(fork):
    write(fork, "docs/my_notes.md", "mine\n")
    git(fork, "add", "-A")
    git(fork, "commit", "-q", "-m", "note")
    res = fork_check.check(fork)
    assert res["ok"] and [e["severity"] for e in res["framework_edits"]] == ["warning"]


def test_merging_a_newer_framework_tag_moves_the_base_and_clears_the_diff(fork):
    """After `git merge v1.1.0` the base tag is v1.1.0, so upstream's own changes are never reported as edits."""
    git(fork, "checkout", "-q", "-b", "upstream", "v1.0.0")
    write(fork, "backend/core/app.py", "core v2 (framework release)\n")
    git(fork, "add", "-A")
    git(fork, "commit", "-q", "-m", "framework v1.1.0")
    git(fork, "tag", "v1.1.0")
    git(fork, "checkout", "-q", "main")
    git(fork, "merge", "-q", "--no-edit", "v1.1.0")
    res = fork_check.check(fork)
    assert res["base"] == "v1.1.0" and res["framework_edits"] == []


def test_an_app_prefixed_release_tag_is_not_taken_as_the_framework_base(fork):
    git(fork, "tag", "app-v1.0.0")
    assert fork_check.check(fork)["base"] == "v1.0.0"


def test_a_module_the_framework_added_later_is_judged_by_the_base_not_by_today(fork):
    """backend/modules/<x>/ is an APP module unless <x> had a manifest.json at the base tag."""
    write(fork, "backend/modules/newmod/api.py", "mine\n")
    git(fork, "add", "-A")
    git(fork, "commit", "-q", "-m", "app module")
    assert fork_check.check(fork)["framework_edits"] == []


def test_the_framework_repo_itself_is_not_a_fork(tmp_path):
    r = tmp_path / "fw"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    write(r, "backend/core/app.py")
    git(r, "add", "-A")
    git(r, "commit", "-q", "-m", "x")
    res = fork_check.check(r)
    assert res["fork"] is False and res["ok"] and "not a fork" in res["note"]


def test_no_framework_tag_is_a_clear_error(fork):
    git(fork, "tag", "-d", "v1.0.0")
    with pytest.raises(fork_check.GitError, match="fetch upstream --tags"):
        fork_check.check(fork)


def test_cli_exit_codes_and_json(fork, capsys):
    assert fork_check.main(["--repo", str(fork), "--json"]) == 0
    write(fork, "backend/core/app.py", "patched\n")
    assert fork_check.main(["--repo", str(fork), "--json"]) == 1
    out = json.loads(capsys.readouterr().out.split("\n}\n")[-2] + "\n}")
    assert out["ok"] is False and out["framework_edits"][0]["path"] == "backend/core/app.py"
    git(fork, "tag", "-d", "v1.0.0")
    assert fork_check.main(["--repo", str(fork)]) == 2


def test_base_override(fork):
    git(fork, "tag", "v0.9.0", "HEAD~1")
    write(fork, "backend/core/app.py", "x\n")
    assert fork_check.check(fork, "v0.9.0")["base"] == "v0.9.0"
