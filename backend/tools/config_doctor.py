"""config doctor — reconcile the live config/license with the examples, additively.

Stale live config (gitignored, hand-maintained) lags the examples as modules and
permissions land, surfacing later as 403s or 404s. This tool reports the drift and
(with --apply) adds only what's MISSING — new modules, roles, per-role permissions,
and licensed modules — never overwriting an existing live value.

    python -m tools.config_doctor            # dry-run: show what would change
    python -m tools.config_doctor --apply    # write the additions back

After --apply: restart the backend and re-login (permissions resolve at login).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from core.services.config import ConfigService, DEFAULT_CONFIG_DIR


def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def reconcile(config_dir: Path, apply: bool) -> list[str]:
    svc = ConfigService(config_dir)
    drift = svc.config_drift()
    changes: list[str] = []

    app_path = config_dir / "app.json"
    lic_path = config_dir / "license.json"
    live_app = _load(app_path)
    ex_app = _load(config_dir / "app.example.json")
    live_lic = _load(lic_path)
    ex_lic = _load(config_dir / "license.example.json")

    # 1. missing modules — append the example entry verbatim
    ex_modules = {m["id"]: m for m in ex_app.get("modules", []) if m.get("id")}
    for mid in drift["modules"]:
        if mid in ex_modules:
            live_app.setdefault("modules", []).append(ex_modules[mid])
            changes.append(f"+ module '{mid}'")

    # 2. roles + per-role permissions (inside the live auth module config)
    live_roles = ConfigService._roles(live_app)   # reference into live_app (if auth present)
    ex_roles = ConfigService._roles(ex_app)
    for role in drift["roles"]:
        live_roles[role] = list(ex_roles.get(role, []))
        changes.append(f"+ role '{role}'")
    for role, perms in drift["permissions"].items():
        live_roles[role] = live_roles.get(role, []) + [p for p in perms if p not in live_roles.get(role, [])]
        changes.append(f"+ permissions {role}: {perms}")

    # 3. licensed modules (+ variants for them)
    ent = live_lic.setdefault("entitlements", {})
    lm = ent.setdefault("modules", {})
    lv = ent.setdefault("variants", {})
    ex_ent = ex_lic.get("entitlements", {})
    ex_lv = ex_ent.get("variants", {})
    for mid in drift["license_modules"]:
        lm[mid] = True
        if mid in ex_lv and mid not in lv:
            lv[mid] = ex_lv[mid]
        changes.append(f"+ license module '{mid}'")

    if apply and changes:
        app_path.write_text(json.dumps(live_app, indent=2) + "\n", encoding="utf-8")
        lic_path.write_text(json.dumps(live_lic, indent=2) + "\n", encoding="utf-8")
    return changes


def main() -> None:
    ap = argparse.ArgumentParser(description="Reconcile live config/license with the examples (additive).")
    ap.add_argument("--config-dir", default=str(DEFAULT_CONFIG_DIR))
    ap.add_argument("--apply", action="store_true", help="write the additions (default: dry-run)")
    args = ap.parse_args()

    changes = reconcile(Path(args.config_dir), args.apply)
    if not changes:
        print("config doctor: live config is up to date with the examples.")
        return
    print(f"config doctor: {len(changes)} addition(s) {'APPLIED' if args.apply else '(dry-run)'}:")
    for c in changes:
        print("  " + c)
    if args.apply:
        print("\nDone. Restart the backend and re-login (permissions resolve at login).")
    else:
        print("\nRe-run with --apply to write these changes.")


if __name__ == "__main__":
    main()
