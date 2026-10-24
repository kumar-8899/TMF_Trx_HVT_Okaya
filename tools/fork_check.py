"""fork_check - did this fork edit a FRAMEWORK-owned file?  (docs/TEMPLATE.md section 1)

    python tools/fork_check.py                 # human-readable, exit 1 if a framework-owned file was modified/deleted
    python tools/fork_check.py --json          # machine-readable (skills and CI call this)
    python tools/fork_check.py --base v1.31.1  # compare against a specific framework tag

An application fork may only create/edit app-owned paths. A downstream patch to a framework file makes every later
`git merge vX.Y.Z` conflict, and two forks that patch the same file diverge from each other. This compares the fork
(HEAD plus uncommitted changes) with its **base framework tag** - the newest `v*` tag reachable from HEAD - and lists
every framework-owned path that differs, using the single rule set in `tools/ownership.py`:

  modified / deleted / renamed  -> error   (this WILL conflict with the next framework merge)
  added                          -> warning (no conflict today, but it lives in framework territory)

The framework repo itself (no `app/<name>/VERSION`) is not a fork; there is nothing to check and it exits 0.
Nothing here changes the repo. The remedy for a finding is a framework change request, not a local patch:
the `framework-change-request` skill writes it up (docs/framework-cr/CR-<n>.md).

Stdlib only; every git call goes through `Git` so tests can use a throw-away repository.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ownership  # noqa: E402

REMEDY = ("Don't keep a local patch: write it up with the `framework-change-request` skill (docs/framework-cr/CR-<n>.md), "
          "let the framework release it, then `git fetch upstream --tags && git merge vX.Y.Z`. "
          "Until then revert the file (`git checkout <base> -- <path>`) or accept that the next merge conflicts there.")


class GitError(RuntimeError):
    pass


class Git:
    def __init__(self, repo: Path) -> None:
        self.repo = repo

    def run(self, *args: str, check: bool = True) -> str:
        r = subprocess.run(["git", *args], cwd=self.repo, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if check and r.returncode != 0:
            raise GitError(f"git {' '.join(args)}: {r.stderr.strip() or r.stdout.strip()}")
        return r.stdout


def is_fork(repo: Path) -> bool:
    base = repo / "app"
    return base.is_dir() and any((p / "VERSION").is_file() for p in base.iterdir() if p.is_dir())


def base_tag(git: Git, override: str | None = None) -> str:
    """The newest framework `v*` tag reachable from HEAD. (App releases use the `app-v` prefix, which `v*` does not match.)"""
    if override:
        git.run("rev-parse", "--verify", f"{override}^{{commit}}")
        return override
    out = git.run("describe", "--tags", "--abbrev=0", "--match", "v[0-9]*", check=False).strip()
    if not out:
        raise GitError("no framework `v*` tag is an ancestor of HEAD - run `git fetch upstream --tags` (or pass --base)")
    return out


def framework_modules_at(git: Git, ref: str) -> list[str]:
    """Framework module ids as of `ref` (a backend/modules/<id>/ that has a manifest.json) - the BASE's list, so a
    module the framework added later is not mistaken for an app module."""
    out = git.run("ls-tree", "-r", "--name-only", ref, "--", "backend/modules", check=False)
    return sorted({m.group(1) for ln in out.splitlines() if (m := re.match(r"^backend/modules/([^/]+)/manifest\.json$", ln))})


def changed_paths(git: Git, base: str) -> list[tuple[str, str]]:
    """[(status, path)] between `base` and the working tree (committed + uncommitted). R/C rows yield the NEW path."""
    out = git.run("diff", "--name-status", "-M", "--no-color", base, check=True)
    rows = []
    for ln in out.splitlines():
        parts = ln.split("\t")
        if len(parts) >= 2:
            rows.append((parts[0][0], parts[-1]))
    return rows


def check(repo: Path, base: str | None = None) -> dict:
    repo = Path(repo)
    result = {"fork": is_fork(repo), "base": None, "framework_edits": [], "ok": True, "note": ""}
    if not result["fork"]:
        result["note"] = "not a fork (no app/<name>/VERSION) - nothing to check"
        return result
    git = Git(repo)
    result["base"] = base_tag(git, base)
    modules = framework_modules_at(git, result["base"])
    kind = {"M": "modified", "D": "deleted", "R": "renamed", "A": "added", "T": "modified", "C": "added"}
    for status, path in changed_paths(git, result["base"]):
        if ownership.owner_of(path, modules) != "framework":
            continue
        result["framework_edits"].append({"path": path, "change": kind.get(status, status),
                                          "severity": "warning" if status in ("A", "C") else "error"})
    result["ok"] = not any(e["severity"] == "error" for e in result["framework_edits"])
    return result


def render(res: dict) -> str:
    if not res["fork"]:
        return f"fork_check: {res['note']}"
    lines = [f"fork_check: base framework tag {res['base']}"]
    if not res["framework_edits"]:
        lines.append("  no framework-owned file differs from the base tag - the next framework merge will be clean.")
        return "\n".join(lines)
    for e in res["framework_edits"]:
        lines.append(f"  [{'FAIL' if e['severity'] == 'error' else 'warn'}] {e['change']:9} {e['path']}")
    errs = sum(1 for e in res["framework_edits"] if e["severity"] == "error")
    lines.append(f"\n{len(res['framework_edits'])} framework-owned path(s) differ ({errs} will conflict with the next merge).")
    lines.append(REMEDY)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="fork_check", description="List framework-owned files this fork has changed.")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--base", default=None, help="framework tag to compare with (default: newest v* ancestor of HEAD)")
    ap.add_argument("--repo", default=str(REPO))
    args = ap.parse_args(argv)
    try:
        res = check(Path(args.repo), args.base)
    except GitError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}) if args.json else f"fork_check: {exc}", file=sys.stderr if not args.json else sys.stdout)
        return 2
    print(json.dumps(res, indent=2) if args.json else render(res))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
