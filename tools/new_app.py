"""Scaffold a customer application from a framework release (secure distribution P-b2).

An application forks a framework **tag** (editable source) and adds only app-owned paths
(TEMPLATE.md §1). This tool writes those app-owned files into an already-cloned fork:

  - backend/config/app.json          product identity + branding + update source
  - backend/modules/<mod>/           a prefixed, collision-proof app module stub
  - .github/workflows/release.yml    the APP-track CI (build → sign → publish, uses the
                                     framework tools it inherited)
  - APP_SETUP.md                     the do-this checklist (remotes, secrets, first release)

It never touches framework-owned code, and never pushes — the maintainer owns the git +
GitHub side. Usage:

  python tools/new_app.py --slug exeliq.acme_eol --customer "Acme EOL" \
      --framework-tag v1.1.0 --app-repo exeliq/app-acme-eol --out ../App_Acme_EOL
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

# ---- templates (token = __NAME__; str.replace, so GitHub's ${{ }} survives) ----

RELEASE_YML = r"""# APP-track release CI (secure distribution). Forked from the framework; builds THIS
# application's licensed artifact. Secrets KS_INTERMEDIATE_SEED + KS_INTERMEDIATE_CERT
# live on THIS app repo. Tag vX.Y.Z -> signed app .ksupdate + GitHub Release.
name: release
on:
  push:
    tags: ["v*"]
permissions:
  contents: write
jobs:
  release:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - uses: actions/setup-node@v4
        with: { node-version: "20", cache: npm, cache-dependency-path: frontend/package-lock.json }

      - name: Backend tests
        working-directory: backend
        run: |
          pip install -e ".[dev]"
          python -m pytest -q

      - name: Frontend tests + build
        working-directory: frontend
        run: |
          npm ci
          npx tsc --noEmit
          npx vitest run
          npm run build

      - name: Nuitka app build
        working-directory: backend
        run: |
          pip install -e ".[release]"
          python build_release.py --track app --product __PRODUCT__ --pinned-fw-version __PINNED_FW__

      - name: Package + hash artifact
        shell: python
        run: |
          import hashlib, json, shutil, os
          tag = os.environ["GITHUB_REF_NAME"]
          zip_base = f"__MOD__-{tag}"
          shutil.make_archive(zip_base, "zip", "release-build")
          zp = zip_base + ".zip"
          h = hashlib.sha256(open(zp, "rb").read()).hexdigest()
          rel = json.load(open("release-build/RELEASE.json"))
          rel["full_artifact_hash"] = h; rel["artifact"] = zp
          json.dump(rel, open("release-build/RELEASE.json", "w"), indent=2)
          print("artifact", zp, h)

      - name: Sign .ksupdate
        env:
          KS_INTERMEDIATE_SEED: ${{ secrets.KS_INTERMEDIATE_SEED }}
          KS_INTERMEDIATE_CERT: ${{ secrets.KS_INTERMEDIATE_CERT }}
        run: |
          pip install cryptography
          python tools/ks_release_signer/sign_update.py release-build/RELEASE.json __MOD__-${{ github.ref_name }}.ksupdate

      - name: Publish GitHub Release
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          gh release create ${{ github.ref_name }} `
            "__MOD__-${{ github.ref_name }}.zip" `
            "__MOD__-${{ github.ref_name }}.ksupdate" `
            "release-build/RELEASE.json" `
            --title "__CUSTOMER__ ${{ github.ref_name }}" --generate-notes
"""

MANIFEST = """{
  "schema_version": 1,
  "module": {
    "id": "__MOD__",
    "version": "1.0.0",
    "contract_version": 1,
    "display_name": "__CUSTOMER__",
    "description": "Application module for __CUSTOMER__ (app-owned; prefixed per TEMPLATE.md)."
  },
  "entitlement_key": "__MOD__",
  "variants": ["default"],
  "core_dependencies": ["diagnostics", "web"],
  "contract_dependencies": [],
  "contributes": { "api_prefix": "", "mqtt_subscriptions": [], "migrations": null, "frontend_flags": [] },
  "config_schema": "schemas/__MOD__.config.schema.json"
}
"""

VARIANT = '''"""__CUSTOMER__ application module (app-owned). Add customer-specific endpoints and
logic here; it is prefixed so upstream framework merges never collide (TEMPLATE.md §1).
Gated on the `plugin.__MOD__` entitlement in the app's lease."""

from __future__ import annotations

from core.framework.contract import CoreServices
from modules.__MOD__.api import build_router


class Default__CLS__:
    def __init__(self, core: CoreServices, config: dict) -> None:
        self.core = core
        self.config = config
        self.router = build_router(self)

    @classmethod
    def construct(cls, core: CoreServices, config: dict) -> "Default__CLS__":
        return cls(core, config)

    async def init(self) -> None: pass
    async def start(self) -> None: pass
    async def stop(self) -> None: pass

    def app_info(self) -> dict:
        return {"module": "__MOD__", "customer": "__CUSTOMER__",
                "product": "__PRODUCT__", "pinned_framework": "__PINNED_FW__"}
'''

API = '''"""__MOD__ router — app-owned. GET /__MOD__/info returns the app identity."""

from __future__ import annotations

from fastapi import APIRouter


def build_router(module) -> APIRouter:
    router = APIRouter(tags=["__MOD__"])

    @router.get("/__MOD__/info")
    async def info() -> dict:
        return module.app_info()

    return router
'''

CONFIG_SCHEMA = """{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "tmf:__MOD__/config.schema.json",
  "title": "__MOD__ module config",
  "type": "object",
  "additionalProperties": true
}
"""

SETUP_MD = """# __CUSTOMER__ — application setup

Scaffolded from framework **__FWTAG__** by `tools/new_app.py`. This is a fork; edit only
app-owned paths (TEMPLATE.md §1). Framework code stays read-only so `git merge upstream
vX.Y.Z` upgrades cleanly.

## 1. Git remotes (once)
```bash
git remote rename origin upstream                 # framework stays 'upstream'
git remote add origin git@github.com:__APP_REPO__.git
git switch -c main && git push -u origin main
```

## 2. Signing secrets on THIS repo (once)
```bash
gh secret set KS_INTERMEDIATE_SEED < .secrets/KS_INTERMEDIATE_SEED.txt  --repo __APP_REPO__
gh secret set KS_INTERMEDIATE_CERT < .secrets/KS_INTERMEDIATE_CERT.json --repo __APP_REPO__
```
Production: use a Keystation app-track intermediate from the root ceremony, not the dev keys.

## 3. Register the product in Keystation (once)
Create app-track product `__PRODUCT__` pinning framework `__FWTAG__`; issue leases against it
with the customer's entitlements (`plugin.__MOD__` + the framework modules they bought).

## 4. Cut an app release
```bash
# edit backend/core/__init__.py + backend/pyproject.toml version, CHANGELOG
git commit -am "release: v1.0.0"
git push origin main
git tag v1.0.0 && git push origin v1.0.0        # release.yml builds + signs + publishes
```

## 5. Point the customer station at this repo
`app.json → "updates": { "github_repo": "__APP_REPO__", "github_token": "<read token>" }`
then Settings → Updates → Check for updates → Relaunch to update.

## Upgrade to a newer framework
```bash
git fetch upstream --tags && git merge vX.Y.Z
# re-pin: build_release --pinned-fw-version X.Y.Z (release.yml already carries it)
```
"""


def _camel(mod: str) -> str:
    return "".join(p.title() for p in mod.split("_"))


def _sub(text: str, tok: dict) -> str:
    for k, v in tok.items():
        text = text.replace(k, v)
    return text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True, help="Keystation product slug, e.g. exeliq.acme_eol")
    ap.add_argument("--customer", required=True, help='display name, e.g. "Acme EOL"')
    ap.add_argument("--framework-tag", required=True, help="framework release forked, e.g. v1.1.0")
    ap.add_argument("--app-repo", required=True, help="owner/repo of the app, e.g. exeliq/app-acme-eol")
    ap.add_argument("--out", required=True, help="path to the cloned framework fork")
    args = ap.parse_args()

    mod = args.slug.split(".")[-1]
    if not re.match(r"^[a-z][a-z0-9_]*$", mod):
        ap.error(f"slug tail '{mod}' must be a valid module id (^[a-z][a-z0-9_]*$)")
    fw_ver = args.framework_tag.lstrip("v")
    tok = {
        "__PRODUCT__": args.slug, "__CUSTOMER__": args.customer, "__MOD__": mod,
        "__CLS__": _camel(mod), "__PINNED_FW__": fw_ver, "__FWTAG__": args.framework_tag,
        "__APP_REPO__": args.app_repo,
    }
    out = Path(args.out)
    if not (out / "backend").is_dir():
        ap.error(f"{out} is not a framework fork (no backend/). Clone + checkout the tag first.")

    # app.json from the framework example + app identity
    example = out / "backend" / "config" / "app.example.json"
    cfg = json.loads(example.read_text(encoding="utf-8")) if example.is_file() else {
        "schema_version": 1, "station": "st1", "license": "config/license.json",
        "branding": {}, "modules": [],
    }
    cfg["station"] = f"{mod}_st1"
    cfg["branding"] = {"name": args.customer, "short": args.customer[:2].upper(),
                       "product": f"{args.customer} — Test & Measurement",
                       "tagline": "Authorised access only. All sessions are encrypted."}
    cfg["licensing"] = {"provider": "stub", "product": args.slug}      # deployer flips to keystation
    cfg["updates"] = {"github_repo": args.app_repo}
    mods = cfg.setdefault("modules", [])
    have = {m.get("id") for m in mods}
    # Enable EVERY framework module present in this fork (future-proof: a module added
    # to the framework after the example was written is still activated). Modules already
    # in the example keep their tuned config; newly-discovered ones get a bare entry.
    mroot = out / "backend" / "modules"
    for man in sorted(mroot.glob("*/manifest.json")):
        m = json.loads(man.read_text(encoding="utf-8"))
        mid = (m.get("module") or {}).get("id") or man.parent.name
        if mid not in have:
            mods.append({"id": mid, "variant": (m.get("variants") or ["default"])[0]})
            have.add(mid)
    if mod not in have:                                                # the app module itself
        mods.append({"id": mod, "variant": "default"})
    (out / "backend" / "config").mkdir(parents=True, exist_ok=True)
    (out / "backend" / "config" / "app.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    # app module (prefixed)
    md = out / "backend" / "modules" / mod
    (md / "variants").mkdir(parents=True, exist_ok=True)
    (md / "schemas").mkdir(parents=True, exist_ok=True)
    (md / "__init__.py").write_text("", encoding="utf-8")
    (md / "variants" / "__init__.py").write_text("", encoding="utf-8")
    (md / "manifest.json").write_text(_sub(MANIFEST, tok), encoding="utf-8")
    (md / "api.py").write_text(_sub(API, tok), encoding="utf-8")
    (md / "variants" / "default.py").write_text(_sub(VARIANT, tok), encoding="utf-8")
    (md / "schemas" / f"{mod}.config.schema.json").write_text(_sub(CONFIG_SCHEMA, tok), encoding="utf-8")

    # app-track CI + setup checklist
    (out / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
    (out / ".github" / "workflows" / "release.yml").write_text(_sub(RELEASE_YML, tok), encoding="utf-8")
    (out / "APP_SETUP.md").write_text(_sub(SETUP_MD, tok), encoding="utf-8")

    print(f"scaffolded {args.customer} ({args.slug}) into {out}")
    print(f"  module: backend/modules/{mod}/  - product pins framework {args.framework_tag}")
    print("  next: read APP_SETUP.md (remotes -> secrets -> register product -> tag a release)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
