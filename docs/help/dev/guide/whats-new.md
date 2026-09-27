# What's new & upgrading

## Release feed

Generated from `CHANGELOG.md`. Filter by bump type; click a release to expand its notes.
**MAJOR** = a contract broke (read before merging) · **MINOR** = new features · **PATCH** = fixes.

```tmf:changelog
20
```

## Upgrading your fork

```bash
git fetch upstream --tags
git merge v<X.Y.Z>                       # clean, if the ownership boundary was respected
cd backend && pip install -e instrumentlib && pip install -e ".[dev]"
python -m tools.config_doctor            # dry-run: new modules / roles / permissions
python -m tools.config_doctor --apply    # additive reconcile of live config
python -m pytest -q
cd ../frontend && npm install && npx vitest run && npm run build
```

Then restart the backend and **log in again** — permissions and modules resolve at login/boot.

- Read the release notes above first; on a **MAJOR** release also check your `<app>_*` modules against the
  new `contract_version`.
- Your **app version** is independent of the framework's (`app/<name>/VERSION`, starts at 1.0.0). A framework
  upgrade doesn't change it unless you ship a new app release.
- Build and release with `deploy/cut-release.ps1` (`-BuildOnly` to build without publishing).

Reference: [Application template](help:dev-template) · [Cutting a release](help:dev-release-howto).
