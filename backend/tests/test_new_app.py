"""new_app.py scaffolder — app-repo generation (secure distribution P-b2).

Runs the scaffolder into a minimal fake fork and asserts the app-owned files are
correct: product identity in app.json, a valid prefixed module, and an app-track
release.yml. The generated variant is byte-compiled to catch template breakage.
"""

import compileall
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
NEW_APP = REPO / "tools" / "new_app.py"


def _scaffold(tmp_path):
    # minimal fake fork: just the framework's app.example.json
    cfgdir = tmp_path / "backend" / "config"
    cfgdir.mkdir(parents=True)
    src = REPO / "backend" / "config" / "app.example.json"
    (cfgdir / "app.example.json").write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    r = subprocess.run([sys.executable, str(NEW_APP),
                        "--slug", "exeliq.acme_eol", "--customer", "Acme EOL",
                        "--framework-tag", "v1.1.0", "--app-repo", "exeliq/app-acme-eol",
                        "--out", str(tmp_path)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr + r.stdout
    return tmp_path


def test_app_json_identity(tmp_path):
    out = _scaffold(tmp_path)
    cfg = json.loads((out / "backend" / "config" / "app.json").read_text())
    assert cfg["licensing"]["product"] == "exeliq.acme_eol"
    assert cfg["updates"]["github_repo"] == "exeliq/app-acme-eol"
    assert cfg["branding"]["name"] == "Acme EOL"
    assert any(m["id"] == "acme_eol" for m in cfg["modules"])


def test_module_stub_valid(tmp_path):
    out = _scaffold(tmp_path)
    md = out / "backend" / "modules" / "acme_eol"
    man = json.loads((md / "manifest.json").read_text())
    assert man["module"]["id"] == "acme_eol" and man["entitlement_key"] == "acme_eol"
    # the config schema parses
    json.loads((md / "schemas" / "acme_eol.config.schema.json").read_text())
    # the variant + api compile (template tokens all substituted)
    variant = (md / "variants" / "default.py").read_text()
    assert "class DefaultAcmeEol" in variant and "__MOD__" not in variant
    assert compileall.compile_file(str(md / "variants" / "default.py"), quiet=1)
    assert compileall.compile_file(str(md / "api.py"), quiet=1)


def test_app_release_yml_is_app_track(tmp_path):
    out = _scaffold(tmp_path)
    yml = (out / ".github" / "workflows" / "release.yml").read_text()
    assert "--track app" in yml
    assert "--product exeliq.acme_eol" in yml
    assert "--pinned-fw-version 1.1.0" in yml
    assert "acme_eol-${{ github.ref_name }}.ksupdate" in yml
    assert (out / "APP_SETUP.md").is_file()


def test_all_framework_modules_enabled(tmp_path):
    # a fork with the real framework modules + a fake "future" module not in the example
    cfgdir = tmp_path / "backend" / "config"
    cfgdir.mkdir(parents=True)
    (cfgdir / "app.example.json").write_text(
        (REPO / "backend" / "config" / "app.example.json").read_text(encoding="utf-8"), encoding="utf-8")
    fut = tmp_path / "backend" / "modules" / "future_mod"
    fut.mkdir(parents=True)
    (fut / "manifest.json").write_text(json.dumps({
        "schema_version": 1, "module": {"id": "future_mod", "version": "1.0.0",
        "contract_version": 1, "display_name": "Future", "description": "x"},
        "entitlement_key": "future_mod", "variants": ["default"], "core_dependencies": [],
        "contract_dependencies": [], "contributes": {}}), encoding="utf-8")
    r = subprocess.run([sys.executable, str(NEW_APP), "--slug", "exeliq.acme_eol",
                        "--customer", "Acme", "--framework-tag", "v1.1.0",
                        "--app-repo", "exeliq/app-acme-eol", "--out", str(tmp_path)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr + r.stdout
    cfg = json.loads((cfgdir / "app.json").read_text())
    ids = {m["id"] for m in cfg["modules"]}
    # all 11 framework modules + the discovered future module + the app module
    assert {"daq", "runs", "auth", "report", "variables"} <= ids
    assert "future_mod" in ids and "acme_eol" in ids


def test_bad_slug_rejected(tmp_path):
    (tmp_path / "backend").mkdir()
    r = subprocess.run([sys.executable, str(NEW_APP),
                        "--slug", "Bad.Slug-X", "--customer", "X",
                        "--framework-tag", "v1.0.0", "--app-repo", "o/r", "--out", str(tmp_path)],
                       capture_output=True, text=True)
    assert r.returncode != 0
