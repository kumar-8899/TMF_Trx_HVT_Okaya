# Which skill do I use?

The framework ships skills that do the mechanical, error-prone parts of building an app. Use them
instead of hand-rolling — they encode the ownership boundary and the verification steps.

```tmf:skill-picker
```

## All skills (generated from the repo)

```tmf:facts
skills
```

## Keeping the fork healthy

- **Pull a new framework release** → `upgrade-framework` (runs `tools/upgrade.py`: preflight, merge, reinstall, tests,
  "what's new for you"). Never `git merge` the framework by hand.
- **You need a change in a framework-owned file** (a bug, a limitation) → `framework-change-request`: write it up,
  don't patch it in the fork. `python tools/fork_check.py` shows what you have already changed.
- **Something is off on this PC** → `python tools/doctor.py` (virtualenv, editable installs, ports, stale config).
- **A bench misbehaves on a client PC** → `debug-client-bench`: read the running app live through the TMF Debug Tool (or analyse an air-gapped bundle);
  anything that changes the PC waits for the engineer's approval (`docs/DEBUG_TOOL.md`).

## Rules of thumb

- **New app, nothing similar exists** → `new-test-app`. **Something similar exists** → `clone-test-app`:
  it still forks a clean framework tag (so upgrades keep working) but reuses the donor app's payload,
  and forces you to re-confirm every limit for the new product.
- **Never** copy an existing app's repo and just rename remotes: you would inherit its git history,
  customer config and any drift in framework files, and your `upstream` would no longer be the framework.
- A driver is **copied into your fork** (`instrument_libs/`); the central library is only a source.
- Limits and parameters always come from the **product spec** — never invent them.

Related: [Building blocks](help:dev-guide-building-blocks) · [Ownership boundary](help:dev-guide-ownership).
