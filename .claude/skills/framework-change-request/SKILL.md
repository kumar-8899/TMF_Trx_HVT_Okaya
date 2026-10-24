---
name: framework-change-request
description: Raise a change to the Super_Test_App FRAMEWORK from inside a forked application, without patching the framework file in the fork. Use when the user hit a bug or limitation in framework-owned code (core, controller, build/release scripts, shared screens, deploy tooling), when `tools/fork_check.py` reports a framework-owned file edited downstream, or when they say "fix this in the framework", "the framework should do X", or "write up a change request / framework CR". Produces docs/framework-cr/CR-<n>.md with symptom, evidence, root cause, a proposed .diff and a test - and leaves the framework file in the fork untouched. Do NOT use for app-owned changes (app/<slug>/, instrument_libs/, overrides) - just make those.
---

# Framework change request (instead of a downstream patch)

A downstream patch to a framework-owned file makes every later `git merge vX.Y.Z` conflict, and two forks that patch
the same file diverge from each other. The sanctioned path is: **write it up here, the framework maintainer releases
it, the fork merges the release.** `docs/TEMPLATE.md` section 1 is the boundary; `python tools\ownership.py <path>`
tells you which side a path is on.

## Steps

1. **Confirm it is framework-owned**: `python tools\ownership.py <path>` (or `python tools\fork_check.py`). If it is
   app-owned, stop - this skill is not needed.
2. **Reproduce and collect evidence** (do not guess): the exact failing command/output, the app and framework
   versions (`core.__version__`, `app/<slug>/VERSION`), the bench/PC if it is a field issue, and - if a bench
   was involved - the debug bundle or `bench_why` result. Quote errors verbatim.
3. **Find the root cause** in the framework source (cite `file:line`), not just the symptom.
4. **Draft the fix without leaving it in the fork's tree**: make the change, save it with
   `git diff > docs/framework-cr/CR-<n>.diff`, then restore the fork's file (`git checkout -- <path>`) - or work in
   `git worktree add ../fw-cr-<n> <base tag>`. The fork's framework files must end identical to the base tag.
5. **Write the test that fails without the fix** (framework test conventions: pytest in `backend/tests/` or the
   module's `tester/`; vitest for the frontend) and include it in the diff.
6. **Write `docs/framework-cr/CR-<n>.md`** from `docs/templates/framework-cr.md`: symptom, evidence, root cause,
   proposed change (link the `.diff`), the test, files touched, who is affected (which forks/builds), and whether the
   fix is generic or app-specific (app-specific needs stay in the app).
7. **Tell the user** where the CR is and that the maintainer takes it from there; do **not** push to the framework
   repo (the `upstream` remote is push-disabled on purpose).
8. **Until the framework releases it**: the fork runs on the unpatched base. If the user insists on a temporary local
   patch, say plainly that `fork_check` will flag it, the next `tools/upgrade.py` will stop on it, and give the exact
   revert command.

## Rules

- One CR per problem. Never bundle unrelated fixes.
- Never edit the framework file in the fork "just for now".
- Never claim a fix works without the failing-then-passing test; say plainly when something could not be verified
  (for example: needs a real SQL Server, a real bench, or a frozen build).
