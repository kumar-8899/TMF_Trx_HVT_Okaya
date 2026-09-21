"""Generate the developer guide's machine-readable FACTS from the code — so they cannot go stale.

    python tools/gen_devguide.py            # (re)write docs/generated/facts.json + facts.md
    python tools/gen_devguide.py --check    # exit 1 if the committed files are out of date (CI gate)
    python tools/gen_devguide.py --print    # emit facts.json to stdout (used by the drift test)

Everything here is derived from a single source of truth already in the repo: the framework version,
CHANGELOG, module manifests, the permission catalog + default roles, the controller's step-type
registry, the instrument capability interfaces, the controller's served MQTT ops, the REST route
decorators, the frontend route table and the skills' front matter. The facts embed the framework
version, so cutting a release without regenerating fails the drift test — that is what makes the
Developer Hub "continuously updated". Deliberately NOT included: test/route counts and anything else
that changes on every commit (those would make the gate noise, not signal).

Lives at repo root (not backend/) because it imports BOTH backend/ and controller/, and the backend
must never import the controller. Output is developer-only and is never shipped in a built station
(build_release.copy_user_docs ships an allowlist; help.catalog hides it when frozen).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "docs" / "generated"
FACTS_JSON = OUT_DIR / "facts.json"
FACTS_MD = OUT_DIR / "facts.md"

# This repo's own code must win over any other editable install of `core`/`controller`/
# `instrumentlib` that happens to be on the machine (developers keep several forks side by side).
for p in (REPO / "controller", REPO / "backend"):
    sys.path.insert(0, str(p))


# --------------------------------------------------------------------------------------------
# sections
# --------------------------------------------------------------------------------------------

def framework() -> dict:
    src = (REPO / "backend" / "core" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'^__version__\s*=\s*"([^"]+)"', src, re.M)
    return {"name": "Super_Test_App", "version": m.group(1) if m else None}


_REL_HEAD = re.compile(r"^## v?(\d+\.\d+\.\d+)\s*[—–-]\s*(\S+)\s*$", re.M)


def releases() -> list[dict]:
    text = (REPO / "CHANGELOG.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    heads = list(_REL_HEAD.finditer(text))
    out = []
    for i, h in enumerate(heads):
        body = text[h.end(): heads[i + 1].start() if i + 1 < len(heads) else len(text)].strip("\n")
        para = body.lstrip("\n").split("\n\n")[0]                    # first paragraph (may wrap lines)
        summary = re.sub(r"\s+", " ", para.replace("**", "")).strip()
        tags = re.findall(r"\b(MAJOR|MINOR|PATCH)\b", summary)      # older entries end "… PATCH." unparenthesised
        out.append({"version": h.group(1), "date": h.group(2), "bump": tags[-1] if tags else None,
                    "summary": summary, "body": body})
    return out


_ROUTE = re.compile(r'@(?:router|app)\.(get|post|put|delete|patch)\(\s*["\']([^"\']+)["\']')
_PERM = re.compile(r'require_permission\(\s*["\']([A-Z_]+\.[A-Z_]+)["\']')


def _scan(py_files) -> tuple[list[dict], list[str]]:
    routes, perms = [], set()
    for f in py_files:
        src = f.read_text(encoding="utf-8")
        routes += [{"method": m.upper(), "path": p} for m, p in _ROUTE.findall(src)]
        perms.update(_PERM.findall(src))
    routes.sort(key=lambda r: (r["path"], r["method"]))
    return routes, sorted(perms)


def modules() -> tuple[list[dict], dict]:
    out = []
    for mf in sorted((REPO / "backend" / "modules").glob("*/manifest.json")):
        d = json.loads(mf.read_text(encoding="utf-8"))
        mod = d["module"]
        py = [f for f in mf.parent.rglob("*.py") if "tester" not in f.parts and "__pycache__" not in f.parts]
        routes, perms = _scan(py)
        out.append({
            "id": mod["id"], "display_name": mod.get("display_name"), "description": mod.get("description"),
            "version": mod.get("version"), "contract_version": mod.get("contract_version"),
            "entitlement_key": d.get("entitlement_key"), "variants": d.get("variants", []),
            "api_prefix": (d.get("contributes") or {}).get("api_prefix"),
            "core_dependencies": d.get("core_dependencies", []),
            "contract_dependencies": d.get("contract_dependencies", []),
            "permissions_used": perms, "routes": routes,
        })
    core_routes, _ = _scan([REPO / "backend" / "core" / "app.py"])
    return out, {"routes": core_routes}


def permissions_and_roles() -> tuple[list[dict], dict]:
    from modules.auth.permissions_catalog import PERMISSIONS
    cfg = json.loads((REPO / "backend" / "config" / "app.example.json").read_text(encoding="utf-8"))
    roles: dict = {}
    for m in cfg.get("modules", []):
        if m.get("id") == "auth":
            roles = (m.get("config") or {}).get("roles", {})
    return [dict(p) for p in PERMISSIONS], {k: list(v) for k, v in sorted(roles.items())}


def step_types() -> list[dict]:
    import controller.step_types  # noqa: F401 — registers the core step types
    from controller import registry
    return registry.catalog()


def capabilities() -> list[dict]:
    import inspect
    from instrumentlib import interfaces
    out = []
    for name, cls in sorted(vars(interfaces).items()):
        if inspect.isclass(cls) and getattr(cls, "INTERFACE", None) and cls.__module__ == interfaces.__name__:
            out.append({"class": name, "interface": cls.INTERFACE, "interface_version": cls.INTERFACE_VERSION,
                        "scalar": bool(getattr(cls, "SCALAR", False)), "methods": list(cls.METHODS)})
    return out


class _OpRecorder:
    """Stand-in for StationClient: records what each register_*_ops call serves."""

    def __init__(self) -> None:
        self.ops: list[dict] = []
        self.group = ""

    def serve(self, op, handler, *, blocking=False):
        doc = (getattr(handler, "__doc__", None) or "").strip().split("\n")[0]
        self.ops.append({"op": op, "group": self.group, "blocking": bool(blocking), "doc": doc})

    def publish(self, *a, **k):  # handlers may publish at call time, never at registration
        pass


def controller_ops() -> list[dict]:
    from controller import serve
    from controller.daq import register_daq_ops
    rec = _OpRecorder()
    for group, fn, args in (
        ("core", serve.register_core_ops, ()),
        ("instruments", serve.register_station_ops, (None, None, None)),
        ("runs", serve.register_run_ops, (None,)),
        ("maintenance", serve.register_maintenance_ops, ({},)),
        ("safety", serve.register_safety_ops, (None,)),
        ("daq", register_daq_ops, (None,)),
    ):
        rec.group = group
        fn(rec, *args)
    return sorted(rec.ops, key=lambda o: o["op"])


_FE_ROUTE = re.compile(r'<Route\s+path="([^"]+)"\s+element=\{(.*?)\}\s*/>')


def frontend_routes() -> list[dict]:
    src = (REPO / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    out = []
    for path, el in _FE_ROUTE.findall(src):
        perm = re.search(r'RequirePermission perm="([^"]+)"', el)
        role = re.search(r'RequireRole role="([^"]+)"', el)
        out.append({"path": path, "permission": perm.group(1) if perm else None,
                    "role": role.group(1) if role else None})
    return sorted(out, key=lambda r: r["path"])


def skills() -> list[dict]:
    out = []
    for f in sorted((REPO / ".claude" / "skills").glob("*/SKILL.md")):
        head = f.read_text(encoding="utf-8").replace("\r\n", "\n").split("---")[1]
        name = re.search(r"^name:\s*(.+)$", head, re.M)
        desc = re.search(r"^description:\s*(.+)$", head, re.M)
        out.append({"name": name.group(1).strip() if name else f.parent.name,
                    "description": desc.group(1).strip() if desc else ""})
    return out


# --------------------------------------------------------------------------------------------
# assemble + render
# --------------------------------------------------------------------------------------------

def build_facts() -> dict:
    mods, core = modules()
    perms, roles = permissions_and_roles()
    return {
        "schema_version": 1,
        "framework": framework(),
        "releases": releases(),
        "modules": mods,
        "core": core,
        "permissions": perms,
        "roles": roles,
        "step_types": step_types(),
        "capabilities": capabilities(),
        "controller_ops": controller_ops(),
        "frontend_routes": frontend_routes(),
        "skills": skills(),
    }


def to_json(facts: dict) -> str:
    return json.dumps(facts, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def to_markdown(f: dict) -> str:
    """A compact digest of the same facts — for humans skimming the repo and for Claude sessions."""
    L = ["# Framework facts (generated — do not edit)", "",
         f"Super_Test_App **v{f['framework']['version']}**. Regenerate: `python tools/gen_devguide.py`.", "",
         "## Latest releases", ""]
    L += [f"- **v{r['version']}** ({r['date']}{', ' + r['bump'] if r['bump'] else ''}) — {r['summary']}"
          for r in f["releases"][:10]]
    L += ["", "## Modules", "", "| id | version | contract | prefix | permissions |", "|---|---|---|---|---|"]
    L += [f"| {m['id']} | {m['version']} | {m['contract_version']} | {m['api_prefix'] or ''} | "
          f"{', '.join(m['permissions_used'])} |" for m in f["modules"]]
    L += ["", "## Permissions", "", "| key | label |", "|---|---|"]
    L += [f"| {p['key']} | {p['label']} |" for p in f["permissions"]]
    L += ["", "## Roles (default grants)", ""]
    L += [f"- **{r}**: {', '.join(g)}" for r, g in f["roles"].items()]
    L += ["", "## Step types", "", "| type | kind | composite |", "|---|---|---|"]
    L += [f"| {s['type_id']} | {s['kind']} | {s['composite']} |" for s in f["step_types"]]
    L += ["", "## Instrument capabilities", ""]
    L += [f"- **{c['interface']}** v{c['interface_version']} ({'scalar' if c['scalar'] else 'non-scalar'}): "
          f"{', '.join(c['methods'])}" for c in f["capabilities"]]
    L += ["", "## Controller MQTT ops", "", "| op | group | blocking |", "|---|---|---|"]
    L += [f"| {o['op']} | {o['group']} | {o['blocking']} |" for o in f["controller_ops"]]
    L += ["", "## Frontend routes", "", "| path | needs |", "|---|---|"]
    L += [f"| {r['path']} | {r['permission'] or r['role'] or ''} |" for r in f["frontend_routes"]]
    L += ["", "## Skills", ""] + [f"- **{s['name']}** — {s['description'][:140]}" for s in f["skills"]]
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="fail if committed facts are stale")
    ap.add_argument("--print", action="store_true", help="print facts.json to stdout")
    args = ap.parse_args(argv)

    facts = build_facts()
    js, md = to_json(facts), to_markdown(facts)
    if args.print:
        sys.stdout.write(js)
        return 0
    if args.check:
        stale = [p.name for p, want in ((FACTS_JSON, js), (FACTS_MD, md))
                 if not p.is_file() or p.read_text(encoding="utf-8").replace("\r\n", "\n") != want]
        if stale:
            print(f"docs/generated/{', '.join(stale)} out of date — run: python tools/gen_devguide.py",
                  file=sys.stderr)
            return 1
        print("docs/generated facts are up to date")
        return 0
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    FACTS_JSON.write_text(js, encoding="utf-8", newline="\n")
    FACTS_MD.write_text(md, encoding="utf-8", newline="\n")
    print(f"wrote {FACTS_JSON.relative_to(REPO)} + {FACTS_MD.name} (framework v{facts['framework']['version']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
