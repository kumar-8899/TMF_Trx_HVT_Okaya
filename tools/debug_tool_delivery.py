"""How the TMF Debug Tool reaches a fork's client PCs (docs/DEBUG_TOOL.md "Deployment").

A fork never builds the tool: it pins a released, signed zip in `app/<slug>/debug-tool.json` and this helper

  plan   reads + validates the pin and finds the zip in the local cache (`tools/debug-tool/`, then `release-build-tool/`)
  stage  for delivery=bundle: unpacks it to a staging folder the installer picks up (an OPTIONAL, unticked installer task that puts it
         beside the app, outside run.dist) and copies the zip into the delivery folder; for on-demand / none it ships nothing
  fetch  downloads the pinned release asset (`debug-tool-v<version>`) from the framework's GitHub releases into the cache

`deploy/cut-release.ps1` calls `stage`. A pin that cannot be satisfied stops the release loudly - a customer must never receive a build
that silently lacks (or has a different version of) a tool the handover sheet says is there.

    python tools/debug_tool_delivery.py plan  --slug <slug> [--json]
    python tools/debug_tool_delivery.py stage --slug <slug> --stage-dir release-build/debug-tool --delivery-dir deploy/Output [--json]
    python tools/debug_tool_delivery.py fetch --slug <slug> [--repo owner/name]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIRS = ("tools/debug-tool", "release-build-tool")
ZIP_RE = re.compile(r"^tmf-debug-tool-(\d+)\.(\d+)\.(\d+)\.zip$")


class DeliveryError(Exception):
    pass


def _ver(name: str) -> tuple[int, int, int] | None:
    m = ZIP_RE.match(name)
    return tuple(int(x) for x in m.groups()) if m else None


def matches(spec: str, ver: tuple[int, int, int]) -> bool:
    parts = spec.split(".")
    for want, got in zip(parts, ver):
        if want != "x" and int(want) != got:
            return False
    return True


def load_config(slug: str, root: Path = ROOT) -> dict:
    p = root / "app" / slug / "debug-tool.json"
    if not p.is_file():
        return {"delivery": "on-demand", "_source": "default (no app/%s/debug-tool.json)" % slug}
    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise DeliveryError(f"{p} is not valid JSON: {exc}") from exc
    cfg["_source"] = str(p)
    return cfg


def validate(cfg: dict, root: Path = ROOT) -> list[str]:
    import jsonschema
    schema = json.loads((root / "deploy" / "debug-tool.schema.json").read_text(encoding="utf-8"))
    body = {k: v for k, v in cfg.items() if not k.startswith("_")}
    return [f"{'/'.join(map(str, e.path)) or '(root)'}: {e.message}" for e in jsonschema.Draft202012Validator(schema).iter_errors(body)]


def find_zip(spec: str, root: Path = ROOT) -> Path | None:
    best: tuple[tuple[int, int, int], Path] | None = None
    for d in CACHE_DIRS:
        for z in (root / d).glob("tmf-debug-tool-*.zip"):
            v = _ver(z.name)
            if v and matches(spec, v) and (best is None or v > best[0]):
                best = (v, z)
    return best[1] if best else None


def plan(slug: str, root: Path = ROOT) -> dict:
    cfg = load_config(slug, root)
    problems = validate(cfg, root)
    out = {"slug": slug, "delivery": cfg.get("delivery", "on-demand"), "version": cfg.get("version"), "zip": None,
           "source": cfg.get("_source"), "problems": problems}
    if problems:
        return out
    if out["delivery"] == "bundle":
        z = find_zip(cfg["version"], root)
        if z is None:
            out["problems"].append(f"no tmf-debug-tool-{cfg['version']}.zip in {', '.join(CACHE_DIRS)} - run: "
                                   f"python tools/debug_tool_delivery.py fetch --slug {slug}   (or build it: deploy/build-debug-tool.ps1)")
        else:
            out["zip"] = str(z)
            sums = z.with_name("SHA256SUMS.txt")
            if sums.is_file():
                want = {ln.split()[1].lstrip("*"): ln.split()[0] for ln in sums.read_text(encoding="utf-8").splitlines() if len(ln.split()) == 2}
                got = hashlib.sha256(z.read_bytes()).hexdigest()
                if z.name in want and want[z.name].lower() != got:
                    out["problems"].append(f"{z.name} does not match SHA256SUMS.txt (got {got}) - the cached zip is corrupt or was replaced")
    return out


def stage(slug: str, stage_dir: Path, delivery_dir: Path, root: Path = ROOT) -> dict:
    p = plan(slug, root)
    stage_dir, delivery_dir = Path(stage_dir), Path(delivery_dir)
    if stage_dir.exists():
        shutil.rmtree(stage_dir)                                   # never ship a leftover from an earlier build
    if p["problems"]:
        raise DeliveryError("; ".join(p["problems"]))
    if p["delivery"] != "bundle":
        p["staged"] = False
        return p
    z = Path(p["zip"])
    with zipfile.ZipFile(z) as zf:
        top = {n.split("/")[0] for n in zf.namelist() if n.strip("/")}
        root_name = top.pop() if len(top) == 1 else None
        for info in zf.infolist():                                  # flatten the zip's single top folder; refuse path escapes
            rel = info.filename.split("/", 1)[1] if root_name and "/" in info.filename else info.filename
            if not rel or info.is_dir():
                continue
            target = (stage_dir / rel).resolve()
            if stage_dir.resolve() not in target.parents:
                raise DeliveryError(f"{z.name} contains a path that escapes the staging folder: {info.filename!r}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(info))
    if not (stage_dir / "tmf-debug-tool.exe").is_file():
        raise DeliveryError(f"{z.name} does not contain tmf-debug-tool.exe")
    delivery_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(z, delivery_dir / z.name)
    p.update(staged=True, stage_dir=str(stage_dir), delivered_zip=str(delivery_dir / z.name))
    return p


def _gh(args: list[str], runner=subprocess.run) -> str:
    r = runner(["gh", *args], capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise DeliveryError(f"gh {' '.join(args[:3])} failed: {(r.stderr or r.stdout).strip()[:300]}")
    return r.stdout


def latest_tag(spec: str, repo: str, runner=subprocess.run) -> str:
    tags = [ln.split("\t")[0] for ln in _gh(["release", "list", "--repo", repo, "--limit", "100", "--json", "tagName", "--jq", ".[].tagName"], runner).splitlines()]
    found = []
    for t in tags:
        m = re.match(r"^debug-tool-v(\d+)\.(\d+)\.(\d+)$", t.strip())
        if m and matches(spec, tuple(int(x) for x in m.groups())):
            found.append((tuple(int(x) for x in m.groups()), t.strip()))
    if not found:
        raise DeliveryError(f"no debug-tool release matching {spec!r} in {repo}")
    return max(found)[1]


def fetch(slug: str, repo: str, root: Path = ROOT, runner=subprocess.run) -> Path:
    cfg = load_config(slug, root)
    spec = cfg.get("version") or "1.x"
    tag = latest_tag(spec, repo, runner)
    dest = root / CACHE_DIRS[0]
    dest.mkdir(parents=True, exist_ok=True)
    _gh(["release", "download", tag, "--repo", repo, "--pattern", "tmf-debug-tool-*.zip", "--pattern", "SHA256SUMS.txt", "--dir", str(dest), "--clobber"], runner)
    zips = sorted(dest.glob("tmf-debug-tool-*.zip"), key=lambda z: _ver(z.name) or (0, 0, 0))
    if not zips:
        raise DeliveryError(f"release {tag} has no tmf-debug-tool-*.zip asset")
    got = plan(slug, root)
    if got["problems"]:
        raise DeliveryError("; ".join(got["problems"]))
    return Path(got["zip"]) if got["zip"] else zips[-1]


def _framework_repo() -> str:
    import os
    env = os.environ.get("FRAMEWORK_REMOTE", "")
    for src in (env, subprocess.run(["git", "remote", "get-url", "upstream"], capture_output=True, text=True, cwd=ROOT).stdout):
        m = re.search(r"github\.com[:/]+([^/\s]+/[^/\s]+?)(?:\.git)?\s*$", src.strip())
        if m:
            return m.group(1)
    raise DeliveryError("cannot tell which GitHub repo publishes the Debug Tool - pass --repo owner/name (or set FRAMEWORK_REMOTE)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "stage", "fetch"):
        sp = sub.add_parser(name)
        sp.add_argument("--slug", required=True)
        sp.add_argument("--json", action="store_true")
        if name == "stage":
            sp.add_argument("--stage-dir", default="release-build/debug-tool")
            sp.add_argument("--delivery-dir", default="deploy/Output")
        if name == "fetch":
            sp.add_argument("--repo", default=None)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "plan":
            out = plan(a.slug)
        elif a.cmd == "stage":
            out = stage(a.slug, ROOT / a.stage_dir, ROOT / a.delivery_dir)
        else:
            out = {"zip": str(fetch(a.slug, a.repo or _framework_repo()))}
    except DeliveryError as exc:
        print(json.dumps({"error": str(exc)}) if a.json else f"debug-tool delivery: {exc}", file=sys.stderr if not a.json else sys.stdout)
        return 1
    if a.json:
        print(json.dumps(out))
    else:
        print(json.dumps(out, indent=2))
    return 1 if (a.cmd == "plan" and out.get("problems")) else 0


if __name__ == "__main__":
    raise SystemExit(main())
