# Cutting a framework release

**The framework ships source, not binaries.** A framework release is just a **git tag**
`vX.Y.Z` on `main` — the point a customer application forks from (TEMPLATE.md §2). The
framework does **not** freeze a build artifact, sign a `.ksupdate`, or publish a GitHub
Release. That build+sign+license+distribute pipeline lives in the **app repo** (per
customer), which forks the tag and uses the framework-provided tools it inherits
(`backend/build_release.py`, `tools/ks_release_signer/`). See SECURE_DISTRIBUTION.md §5–6.

```
framework repo ── git tag vX.Y.Z ──► App_<Customer> (fork the TAG = editable source)
                                          └── app-track CI: PyInstaller → sign .ksupdate → Release (LICENSED build)
```

---

## Steps (framework maintainer)

### 1. Pick the version (semver — TEMPLATE.md §4)
- **MAJOR** — module `contract_version` bump or a locked-contract break.
- **MINOR** — new modules / features / additive contract growth.
- **PATCH** — fixes.

### 2. Bump + changelog (one commit)
Edit **both** version locations to `X.Y.Z`:
- `backend/core/__init__.py` → `__version__`
- `backend/pyproject.toml` → `version`

Add a `## vX.Y.Z — <date>` section at the top of `CHANGELOG.md`, then **regenerate the Developer Hub
facts** (they embed the version and the release feed, so CI fails on a stale copy) and refresh any
screenshots whose screen changed (`cd tools/screenshots && npm run capture`, see its README):
```bash
python tools/gen_devguide.py                     # rewrites docs/generated/facts.{json,md}
git add backend/core/__init__.py backend/pyproject.toml CHANGELOG.md docs/generated
git commit -m "release: vX.Y.Z"
```

### 3. Push + tag
```bash
git push origin main            # ci.yml runs the tests
# wait for ci.yml green, then:
git tag -a vX.Y.Z -m "vX.Y.Z"
git push origin vX.Y.Z          # the fork point — no build, no Release
```

That's it. The tag is the deliverable. `ci.yml` (tests) is the only framework workflow.

### 4. Verify
```bash
git ls-remote --tags origin vX.Y.Z     # tag is on GitHub
gh run list --workflow ci.yml --repo <owner>/<repo>   # tests green on the tagged commit
```

---

## Fixing a tag
- **Before anyone forks it** — move it: `git tag -d vX.Y.Z; git push origin :refs/tags/vX.Y.Z; git tag … ; git push origin vX.Y.Z`.
- **After apps have forked it** — don't move it; cut a new version.

## Building / licensing (app repo, not here)
An application forks a tag, then its **own** CI builds + signs its licensed artifact:
```bash
cd backend && python build_release.py --track app --product <slug> --pinned-fw-version X.Y.Z
python tools/ks_release_signer/sign_update.py release-build/RELEASE.json app-<ver>.ksupdate   # app secrets
```
The app repo holds the Keystation signing secrets (`KS_INTERMEDIATE_*`); the framework
repo does not sign, so it holds none. Full app pipeline: TEMPLATE.md + the app-repo
template (secure-distribution P-b2).
