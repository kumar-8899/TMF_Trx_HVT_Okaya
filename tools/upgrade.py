"""upgrade - move this fork to a newer framework release in one command (replaces the ten manual steps of TEMPLATE.md §3).

    python tools/upgrade.py --to v1.32.0          # or --to latest (newest v<MAJOR>.* tag)
    python tools/upgrade.py --to v1.32.0 --dry-run   # preflight + show what would merge; changes nothing
    python tools/upgrade.py --to v2.0.0 --major      # a MAJOR jump is a deliberate migration; it needs --major

Steps (each reported; the first failure stops the run and says what to do):
  1. preflight      clean working tree; `fork_check` (no framework-owned file edited - such an edit WILL conflict);
                    `doctor` (errors only)
  2. fetch + merge  `git fetch upstream --tags`, `git merge --no-edit <tag>`. On a conflict the files are listed with
                    their ownership class and the merge is ABORTED (the repo is left exactly as it was) unless
                    --keep-conflicts is given
  3. reinstall      the editable installs (only inside a virtualenv - never the global interpreter) and `npm install`
  4. config         `python -m tools.config_doctor --apply` (additive: new permissions/modules; never overwrites yours)
  5. verify         backend `pytest -q`, frontend `tsc --noEmit` + build (skip with --skip-tests)
  6. what's new     the CHANGELOG sections between your version and the new one, module contract_version changes,
                    screen overrides whose framework screen changed, a newer Debug Tool release if you pin an older one
Then it reminds you to restart the app and log in again. It never pushes anything.

Stdlib only; all subprocess work goes through `Runner` so tests can fake pip/npm/pytest.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fork_check  # noqa: E402
import ownership  # noqa: E402

OVERRIDE_SCREEN = {"runs": "Runs", "recipes": "Recipes", "recipe-editor": "RecipeEditor",
                   "recipe-detail": "RecipeDetail", "maintenance": "Maintenance", "portal": "Portal"}


class UpgradeError(RuntimeError):
    pass


def semver(tag: str) -> tuple[int, int, int]:
    m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)", tag)
    if not m:
        raise UpgradeError(f"not a version: {tag!r}")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def framework_version(repo: Path, ref: str | None = None, git: fork_check.Git | None = None) -> str:
    """core.__version__ at `ref` (or the working tree)."""
    if ref:
        text = (git or fork_check.Git(repo)).run("show", f"{ref}:backend/core/__init__.py", check=False)
    else:
        p = repo / "backend" / "core" / "__init__.py"
        text = p.read_text(encoding="utf-8") if p.is_file() else ""
    m = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.M)
    return m.group(1) if m else "0.0.0"


class Runner:
    """Every external command (pip, npm, pytest, config_doctor) goes through here."""

    def __init__(self, repo: Path, say=print) -> None:
        self.repo, self.say = repo, say

    def __call__(self, cmd: list[str], cwd: Path | None = None, timeout: int = 1800) -> tuple[int, str]:
        self.say(f"      $ {' '.join(cmd)}")
        try:
            r = subprocess.run(cmd, cwd=cwd or self.repo, capture_output=True, text=True, timeout=timeout)
            return r.returncode, (r.stdout or "") + (r.stderr or "")
        except FileNotFoundError as exc:
            return 127, str(exc)
        except subprocess.TimeoutExpired:
            return 124, "timed out"


# ------------------------------------------------------------------------------------------ target selection

def resolve_target(git: fork_check.Git, to: str, current: str, allow_major: bool) -> str:
    tags = [t for t in git.run("tag", "-l", "v[0-9]*").split() if re.match(r"^v\d+\.\d+\.\d+$", t)]
    if to == "latest":
        same = [t for t in tags if semver(t)[0] == semver(current)[0]]
        if not same:
            raise UpgradeError(f"no v{semver(current)[0]}.* framework tag found - run `git fetch upstream --tags`")
        to = max(same, key=semver)
    if to not in tags:
        raise UpgradeError(f"framework tag {to} not found (have {', '.join(sorted(tags, key=semver)[-5:])}) - `git fetch upstream --tags`?")
    if semver(to)[0] > semver(current)[0] and not allow_major:
        raise UpgradeError(f"{to} is a MAJOR jump from {current}: module contracts may have changed - read CHANGELOG.md, "
                           "check your <app>_* modules, then re-run with --major")
    if semver(to) <= semver(current):
        raise UpgradeError(f"already at {current}; {to} is not newer")
    return to


# ------------------------------------------------------------------------------------------ what's new

def changelog_between(text: str, old: str, new: str) -> list[dict]:
    """Sections of CHANGELOG.md with old < version <= new, newest first."""
    out, cur = [], None
    for line in text.splitlines():
        m = re.match(r"^## v(\d+\.\d+\.\d+)\b(.*)$", line)
        if m:
            cur = {"version": m.group(1), "heading": line[3:].strip(), "body": []}
            out.append(cur)
        elif cur is not None:
            cur["body"].append(line)
    keep = [s for s in out if semver(old) < semver(s["version"]) <= semver(new)]
    for s in keep:
        s["body"] = "\n".join(s["body"]).strip()
    return keep


def contract_changes(git: fork_check.Git, old: str, new: str) -> list[dict]:
    def versions(ref: str) -> dict[str, int]:
        res = {}
        for ln in git.run("ls-tree", "-r", "--name-only", ref, "--", "backend/modules", check=False).splitlines():
            m = re.match(r"^backend/modules/([^/]+)/manifest\.json$", ln)
            if not m:
                continue
            try:
                res[m.group(1)] = int(json.loads(git.run("show", f"{ref}:{ln}")).get("module", {}).get("contract_version", 0))
            except (ValueError, GitErrorTypes):
                continue
        return res
    a, b = versions(old), versions(new)
    return [{"module": m, "from": a.get(m), "to": b[m]} for m in sorted(b) if m in a and a[m] != b[m]]


GitErrorTypes = (fork_check.GitError, TypeError)


def overrides_affected(repo: Path, git: fork_check.Git, old: str, new: str) -> list[dict]:
    """Screen overrides this fork has whose framework screen changed between the two releases."""
    od = repo / "frontend" / "src" / "app" / "overrides"
    if not od.is_dir():
        return []
    res = []
    for f in sorted(od.glob("*.tsx")):
        text = f.read_text(encoding="utf-8", errors="replace")
        for key in re.findall(r"""key:\s*["']([a-z-]+)["']""", text):
            screen = OVERRIDE_SCREEN.get(key)
            if not screen:
                continue
            paths = ["frontend/src/screens/%s.tsx" % screen]
            changed = git.run("diff", "--name-only", old, new, "--", *paths, check=False).split()
            if changed:
                res.append({"override": f"{f.name} (key '{key}')", "framework_screen": paths[0],
                            "advice": "the framework screen you replaced changed in this release - compare and port what you need"})
    return res


def newer_debug_tool(repo: Path, git: fork_check.Git) -> dict | None:
    """A Debug Tool release newer than what this fork has pinned / cached. `1.x` pins float within the major: only a release the
    fork does not have yet (not in its cache) is news; a release outside the pin (a new MAJOR) says to bump `version`."""
    import debug_tool_delivery as dd
    tags = [t for t in git.run("tag", "-l", "debug-tool-v*").split()]
    versions = [semver(t.replace("debug-tool-", "")) for t in tags if re.match(r"^debug-tool-v\d+\.\d+\.\d+$", t)]
    if not versions:
        return None
    newest = max(versions)
    for f in sorted((repo / "app").glob("*/debug-tool.json")) if (repo / "app").is_dir() else []:
        try:
            pinned = str(json.loads(f.read_text(encoding="utf-8")).get("version") or "")
        except ValueError:
            continue
        if not re.match(r"^\d+(\.(\d+|x))?(\.(\d+|x))?$", pinned):
            continue
        floor = tuple(int(x) if x != "x" else 0 for x in (pinned.split(".") + ["0", "0"])[:3])
        cached = dd.find_zip(pinned, repo)
        have = max(floor, dd._ver(cached.name) or (0, 0, 0)) if cached else floor
        if newest > have:
            in_pin = dd.matches(pinned, newest)
            return {"file": f.relative_to(repo).as_posix(), "pinned": pinned, "newest": ".".join(map(str, newest)), "in_pin": in_pin,
                    "advice": (f"python tools/debug_tool_delivery.py fetch --slug {f.parent.name}" if in_pin and "x" in pinned
                               else f"bump `version` in {f.relative_to(repo).as_posix()}")}
    return None


def whats_new(repo: Path, git: fork_check.Git, old_tag: str, new_tag: str, old_version: str, new_version: str) -> dict:
    cl = repo / "CHANGELOG.md"
    return {
        "changelog": changelog_between(cl.read_text(encoding="utf-8") if cl.is_file() else "", old_version, new_version),
        "contract_changes": contract_changes(git, old_tag, new_tag),
        "overrides": overrides_affected(repo, git, old_tag, new_tag),
        "debug_tool": newer_debug_tool(repo, git),
    }


# ------------------------------------------------------------------------------------------ the run

@dataclass
class Result:
    ok: bool
    steps: list[dict] = field(default_factory=list)
    target: str = ""
    new: dict | None = None
    error: str = ""


def _in_venv() -> bool:
    return sys.prefix != sys.base_prefix


def run_upgrade(repo: Path, to: str, *, allow_major=False, dry_run=False, skip_tests=False, keep_conflicts=False,
                runner: Runner | None = None, doctor_fn=None, say=print) -> Result:
    repo = Path(repo)
    git = fork_check.Git(repo)
    runner = runner or Runner(repo, say)
    res = Result(ok=False)

    def step(name: str, ok: bool, detail: str = "", **extra) -> bool:
        res.steps.append({"step": name, "ok": ok, "detail": detail, **extra})
        say(f"  [{'ok' if ok else 'FAIL'}] {name}" + (f": {detail}" if detail else ""))
        return ok

    def fail(msg: str) -> Result:
        res.error = msg
        say(f"\nupgrade stopped: {msg}")
        return res

    if not fork_check.is_fork(repo):
        return fail("this is not a fork (no app/<name>/VERSION) - the framework repo itself is not upgraded this way")

    # 1. preflight -------------------------------------------------------------------------------
    if git.run("status", "--porcelain").strip():
        step("preflight: working tree", False, "uncommitted changes")
        return fail("commit or stash your changes first (a merge on a dirty tree is unrecoverable)")
    step("preflight: working tree", True, "clean")
    git.run("fetch", "upstream", "--tags", check=False)
    try:
        fc = fork_check.check(repo)
    except fork_check.GitError as exc:
        return fail(str(exc))
    edits = [e for e in fc["framework_edits"] if e["severity"] == "error"]
    if edits:
        step("preflight: fork_check", False, f"{len(edits)} framework-owned file(s) edited downstream", files=[e["path"] for e in edits])
        return fail("these framework-owned files were edited in this fork and WILL conflict:\n    "
                    + "\n    ".join(e["path"] for e in edits) + "\n  Raise them as framework change requests (skill `framework-change-request`), "
                    "or revert them (`git checkout " + fc["base"] + " -- <path>`), then re-run.")
    step("preflight: fork_check", True, f"no framework-owned file edited (base {fc['base']})")
    if doctor_fn is not None:
        errs = [c for c in doctor_fn(repo) if not c["ok"] and c["severity"] == "error"]
        if errs:
            step("preflight: doctor", False, "; ".join(f"{c['id']}: {c['detail']}" for c in errs))
            return fail("`python tools/doctor.py --fix` first (errors above)")
        step("preflight: doctor", True, "no errors")

    old_version = framework_version(repo)
    try:
        target = resolve_target(git, to, old_version, allow_major)
    except UpgradeError as exc:
        return fail(str(exc))
    res.target = target
    new_version = target.lstrip("v")
    step("target", True, f"{old_version} -> {new_version} ({target})")
    if dry_run:
        incoming = git.run("diff", "--stat", "HEAD", target, check=False).strip().splitlines()
        step("dry run", True, f"would merge {target}; {incoming[-1].strip() if incoming else 'no file changes'} - nothing changed")
        res.new = whats_new(repo, git, fc["base"], target, old_version, new_version)
        res.ok = True
        return res

    # 2. merge -----------------------------------------------------------------------------------
    r = subprocess.run(["git", "merge", "--no-edit", target], cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        mods = fork_check.framework_modules_at(git, fc["base"])
        conflicted = [p for p in git.run("diff", "--name-only", "--diff-filter=U", check=False).split()]
        rows = [f"{p}  [{ownership.owner_of(p, mods) or '?'}-owned]" for p in conflicted]
        if not keep_conflicts:
            git.run("merge", "--abort", check=False)
        step("merge", False, f"{len(conflicted)} conflicted file(s)", files=conflicted)
        return fail(f"merging {target} conflicts in:\n    " + "\n    ".join(rows or [r.stderr.strip() or r.stdout.strip()])
                    + ("\n  Conflicts are LEFT in place (--keep-conflicts): resolve, `git commit`, then re-run the remaining steps by hand."
                       if keep_conflicts else "\n  The merge was aborted; the repo is exactly as before. A conflict in a framework-owned file means it "
                       "was edited here; in an app-owned file (e.g. app.example.json) merge by hand."))
    step("merge", True, f"merged {target}")

    # 3. reinstall ---------------------------------------------------------------------------------
    py = sys.executable
    if _in_venv():
        for target_dir, spec in (("backend/instrumentlib", "./backend/instrumentlib"), ("backend", "./backend[dev,report-db]"),
                                 ("controller", "./controller"), ("tmf_debug", "./tmf_debug")):
            if (repo / target_dir).is_dir():
                rc, out = runner([py, "-m", "pip", "install", "-e", spec])
                if not step(f"install {spec}", rc == 0, "" if rc == 0 else out.strip()[-200:]):
                    return fail("an editable install failed - fix it, then run `python tools/doctor.py --fix`")
    else:
        step("install (editable)", True, "SKIPPED - not inside a virtualenv; create/activate .venv and run `python tools/doctor.py --fix`")
    if (repo / "frontend" / "package.json").is_file():
        rc, out = runner(["npm", "install"], cwd=repo / "frontend")
        if not step("npm install", rc == 0, "" if rc == 0 else out.strip()[-200:]):
            return fail("npm install failed")

    # 4. config ------------------------------------------------------------------------------------
    rc, out = runner([py, "-m", "tools.config_doctor", "--apply"], cwd=repo / "backend")
    step("config_doctor --apply", rc == 0, (out.strip().splitlines() or [""])[0][:200])

    # 5. verify ------------------------------------------------------------------------------------
    if skip_tests:
        step("verify", True, "skipped (--skip-tests)")
    else:
        rc, out = runner([py, "-m", "pytest", "-q"], cwd=repo / "backend")
        if not step("backend pytest", rc == 0, (out.strip().splitlines() or [""])[-1][:200]):
            return fail("backend tests fail after the upgrade - see the output above; the merge is committed (revert with `git reset --hard ORIG_HEAD` if you want it undone)")
        if (repo / "frontend" / "package.json").is_file():
            rc, out = runner(["npx", "tsc", "--noEmit"], cwd=repo / "frontend")
            if not step("frontend type-check", rc == 0, "" if rc == 0 else out.strip()[-200:]):
                return fail("frontend type-check fails after the upgrade - an override probably uses something that changed")
            rc, out = runner(["npm", "run", "build"], cwd=repo / "frontend")
            if not step("frontend build", rc == 0, "" if rc == 0 else out.strip()[-200:]):
                return fail("frontend build fails after the upgrade")

    # 6. what's new --------------------------------------------------------------------------------
    res.new = whats_new(repo, git, fc["base"], target, old_version, new_version)
    res.ok = True
    return res


def render_new(new: dict) -> str:
    L = ["\n=== What's new for you ==="]
    for s in new["changelog"]:
        L.append(f"\n## {s['heading']}\n{s['body'][:1500]}" + ("\n  ..." if len(s["body"]) > 1500 else ""))
    if new["contract_changes"]:
        L.append("\nModule contract versions changed (check your <app>_* modules):")
        L += [f"  - {c['module']}: {c['from']} -> {c['to']}" for c in new["contract_changes"]]
    if new["overrides"]:
        L.append("\nYour screen overrides whose framework screen changed:")
        L += [f"  - {o['override']} <- {o['framework_screen']}" for o in new["overrides"]]
    if new["debug_tool"]:
        d = new["debug_tool"]
        L.append(f"\nA newer TMF Debug Tool is available: pinned {d['pinned']}, newest {d['newest']} ({d['advice']}).")
    L.append("\nNext: restart the app and LOG IN AGAIN (permissions and modules resolve at login/boot). Nothing was pushed.")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="upgrade", description="Upgrade this fork to a newer framework release.")
    ap.add_argument("--to", required=True, help="a framework tag (v1.32.0) or `latest` (newest of this MAJOR)")
    ap.add_argument("--major", action="store_true", help="allow a MAJOR version jump")
    ap.add_argument("--dry-run", action="store_true", help="preflight + show what would merge; change nothing")
    ap.add_argument("--skip-tests", action="store_true")
    ap.add_argument("--keep-conflicts", action="store_true", help="leave merge conflicts in the tree instead of aborting")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--repo", default=str(REPO))
    args = ap.parse_args(argv)

    def doctor_fn(repo: Path) -> list[dict]:
        import doctor
        return [c.as_dict() for c in doctor.run_checks(doctor.Ctx(repo=repo))]

    say = (lambda s: print(s, file=sys.stderr)) if args.json else print
    res = run_upgrade(Path(args.repo), args.to, allow_major=args.major, dry_run=args.dry_run, skip_tests=args.skip_tests,
                      keep_conflicts=args.keep_conflicts, doctor_fn=doctor_fn, say=say)
    if args.json:
        print(json.dumps({"ok": res.ok, "target": res.target, "error": res.error, "steps": res.steps, "new": res.new}, indent=2))
    elif res.ok and res.new:
        print(render_new(res.new))
    return 0 if res.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
