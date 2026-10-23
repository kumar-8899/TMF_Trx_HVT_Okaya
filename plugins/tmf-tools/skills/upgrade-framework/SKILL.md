---
name: upgrade-framework
description: Upgrade an existing forked test application to a newer Super_Test_App framework release safely - preflight (clean tree, no framework-owned file edited, doctor), fetch + merge the tag, reinstall, reconcile live config, run the tests, then explain what is new for THIS app. Use when the user says "upgrade/update/pull the new framework version", "merge the latest framework", "bring this app up to v1.x", or asks what changed in a newer framework release for their app. Do NOT use to fork a new app (new-test-app) or to patch a framework file in a fork (framework-change-request).
---

# Upgrade a fork to a newer framework release

One command replaces the ten manual steps of `docs/TEMPLATE.md` section 3. It never pushes and never
overwrites your app's files.

```pwsh
python tools\upgrade.py --to latest --dry-run    # preflight + what would merge; changes nothing
python tools\upgrade.py --to latest              # newest tag of this MAJOR   (or --to v1.32.0)
python tools\upgrade.py --to v2.0.0 --major      # a MAJOR jump is deliberate - read CHANGELOG first
```

## How to run it for the user

1. **Dry run first**, show the user the target version and the "what's new" summary (CHANGELOG sections, any module
   `contract_version` change, screen overrides whose framework screen changed, a newer Debug Tool).
2. **Make sure the machine is sane**: `python tools\doctor.py --json`. The upgrade refuses on a doctor *error*
   (typically: an editable install importing ANOTHER fork's code, so the post-merge tests would test the wrong code).
   It also only runs the installs inside a virtualenv - if there is no `.venv`, say so and use `doctor --fix`.
3. **Run it for real.** Steps: clean tree -> `fork_check` -> fetch + merge -> editable installs + `npm install` ->
   `config_doctor --apply` -> backend `pytest` + frontend `tsc` + build -> "What's new for you".
4. **If it stops**, report which step and why, and do what the message says - do not work around it:
   - *framework-owned file edited downstream* (`fork_check`): those files WILL conflict. Use the
     `framework-change-request` skill to raise each one, or revert it (`git checkout <base-tag> -- <path>`).
   - *merge conflict*: the files are listed with their ownership class and the merge is aborted (repo unchanged).
     A conflict in an app-owned file (e.g. `app.example.json`) is merged by hand; in a framework-owned file it means it was edited here.
   - *tests fail after the merge*: read the output; an override that replaced a framework screen is the usual cause
     (the summary names overrides whose screen changed). `git reset --hard ORIG_HEAD` undoes the merge if wanted.
5. **Afterwards tell the user**: restart the app and **log in again** (permissions/modules resolve at login/boot);
   `git push` is theirs to do - the tool never pushes.

## Rules

- Never `git merge` the framework by hand when this tool is available - it is what keeps the fork mergeable.
- Never use `--major` without having read the CHANGELOG sections it prints; check the app's own `<slug>_*` modules
  against any `contract_version` change.
- Never edit a framework-owned file to make the merge or the tests pass (`docs/TEMPLATE.md` section 1).
