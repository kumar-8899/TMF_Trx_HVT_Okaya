# Cutting a framework release

How to publish a framework version to GitHub. On a pushed tag `vX.Y.Z`,
`.github/workflows/release.yml` builds the obfuscated (Nuitka) artifact, signs a
Keystation `.ksupdate`, and creates the **GitHub Release** with three assets
(`super_test_app-vX.Y.Z.zip`, `.ksupdate`, `RELEASE.json`). Stations pull it via
Settings → Updates → **Check for updates** (SECURE_DISTRIBUTION.md §6a).

This is the **framework** track (issuer-global). A derived customer app cuts its own
**app-track** release from its own repo — see TEMPLATE.md + `tools/ks_release_signer`.

---

## 0. One-time setup (do once per repo)

**GitHub token** — a fine-grained PAT with, on this repo: **Contents, Actions,
Secrets, Workflows = Read/Write**. Then `gh auth login` and `gh auth setup-git`.

**Signing secrets** — the release CI signs the `.ksupdate` with the Keystation
intermediate key. Set them from `.secrets/` (dev keys; gitignored):
```bash
gh secret set KS_INTERMEDIATE_SEED < .secrets/KS_INTERMEDIATE_SEED.txt  --repo <owner>/<repo>
gh secret set KS_INTERMEDIATE_CERT < .secrets/KS_INTERMEDIATE_CERT.json --repo <owner>/<repo>
```
Production: replace the dev keys with a root-ceremony intermediate (runbooks
`root-ceremony.md`, `hsm-provisioning.md`); the **root private key never enters CI**.

---

## 1. Pick the version (semver — TEMPLATE.md §4)

- **MAJOR** — any module `contract_version` bump or a locked-contract break.
- **MINOR** — new modules / features / additive contract growth.
- **PATCH** — fixes.

## 2. Bump + changelog (one commit)

Edit **both** version locations to the new `X.Y.Z`:
- `backend/core/__init__.py` → `__version__`
- `backend/pyproject.toml` → `version`

Add a `## vX.Y.Z — <date>` section at the top of `CHANGELOG.md`, then:
```bash
git add backend/core/__init__.py backend/pyproject.toml CHANGELOG.md
git commit -m "release: vX.Y.Z"
```

## 3. Push the branch (CI runs the tests)

```bash
git push origin main          # triggers ci.yml (backend + frontend tests)
```
Wait for `ci.yml` green before tagging (a red tag build wastes ~30 min).

## 4. Tag + push (this publishes the Release)

```bash
git tag vX.Y.Z
git push origin vX.Y.Z         # triggers release.yml
```

`release.yml` then, automatically:
1. runs backend + frontend tests,
2. Nuitka-compiles the backend (obfuscated artifact) — **~30 min on the runner**,
3. zips it, computes the SHA-256 (`full_artifact_hash`),
4. signs `super_test_app-vX.Y.Z.ksupdate` with the secrets,
5. `gh release create vX.Y.Z` with the zip + `.ksupdate` + `RELEASE.json`.

## 5. Verify

```bash
gh run watch --repo <owner>/<repo>          # follow the release run live
gh release view vX.Y.Z --repo <owner>/<repo>   # confirm 3 assets attached
```
Or the web UI: **Releases** shows `vX.Y.Z`; the run is green under **Actions**.

## 6. Roll out to a station

`app.json → "updates": { "github_repo": "<owner>/<repo>", "github_token": "<read token if private>" }`,
then Settings → Updates → **Check for updates** → the offer appears → **Apply** →
**Relaunch to update** chip → the launcher swaps the artifact on restart.

---

## Fixing a bad release

- **Superseded** — just cut a higher version; stations only offer newer.
- **Yank** — `gh release delete vX.Y.Z` (and `git push --delete origin vX.Y.Z`) so
  no station can pull it. The anti-rollback tripwire already blocks downgrades.
- **Re-run a failed build** — `gh run rerun <run-id>` (no new tag needed if the tag
  is already pushed and only the build flaked).

## Quick reference

```bash
# after 0. one-time setup:
#  edit __version__ + pyproject version + CHANGELOG
git commit -am "release: vX.Y.Z"
git push origin main
git tag vX.Y.Z && git push origin vX.Y.Z
gh run watch      # ~30 min → GitHub Release vX.Y.Z published
```
