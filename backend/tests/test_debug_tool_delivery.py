"""tools/debug_tool_delivery.py + the cut-release / installer wiring: how the Debug Tool reaches an app's client PCs."""

import importlib.util
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("debug_tool_delivery", ROOT / "tools" / "debug_tool_delivery.py")
dd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dd)
PS = shutil.which("powershell")


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "deploy").mkdir()
    shutil.copy(ROOT / "deploy" / "debug-tool.schema.json", tmp_path / "deploy" / "debug-tool.schema.json")
    (tmp_path / "app" / "acme").mkdir(parents=True)
    return tmp_path


def pin(repo, **cfg):
    (repo / "app" / "acme" / "debug-tool.json").write_text(json.dumps(cfg), encoding="utf-8")


def make_zip(repo, ver="1.2.3", where="tools/debug-tool", exe=True, extra=None):
    d = repo / where
    d.mkdir(parents=True, exist_ok=True)
    z = d / f"tmf-debug-tool-{ver}.zip"
    with zipfile.ZipFile(z, "w") as zf:
        if exe:
            zf.writestr("tmf-debug-tool/tmf-debug-tool.exe", b"MZ")
        zf.writestr("tmf-debug-tool/README-FIRST.txt", "hi")
        zf.writestr("tmf-debug-tool/wheelhouse/tmf_support-1.0.0-py3-none-any.whl", b"w")
        for name, data in (extra or {}).items():
            zf.writestr(name, data)
    return z


def test_the_shipped_schema_accepts_and_rejects_the_right_pins(repo):
    ok = lambda **c: dd.validate(c, repo)                                              # noqa: E731
    assert ok(delivery="on-demand") == [] and ok(delivery="none") == [] and ok(delivery="bundle", version="1.x") == []
    assert ok(delivery="bundle", version="1.2.3", note="customer consent ref 17") == []
    assert any("version" in e for e in ok(delivery="bundle"))                          # bundle needs a pin
    assert ok(delivery="sometimes") and ok(delivery="bundle", version="latest") and ok(delivery="none", surprise=1)
    assert ok(version="1.x")                                                           # delivery is required


def test_version_spec_matching():
    assert dd.matches("1.x", (1, 9, 9)) and not dd.matches("1.x", (2, 0, 0))
    assert dd.matches("1.2.x", (1, 2, 7)) and not dd.matches("1.2.x", (1, 3, 0))
    assert dd.matches("1.2.3", (1, 2, 3)) and not dd.matches("1.2.3", (1, 2, 4))


def test_no_pin_file_means_on_demand_and_ships_nothing(repo):
    p = dd.plan("acme", repo)
    assert p["delivery"] == "on-demand" and p["zip"] is None and p["problems"] == []
    out = dd.stage("acme", repo / "stage", repo / "out", repo)
    assert out["staged"] is False and not (repo / "stage").exists() and not (repo / "out").exists()


def test_bundle_picks_the_newest_matching_zip_and_stages_it_flat(repo):
    pin(repo, delivery="bundle", version="1.x")
    make_zip(repo, "1.1.0")
    newest = make_zip(repo, "1.2.3", where="release-build-tool")
    make_zip(repo, "2.0.0")                                                            # a different major is not a match
    p = dd.plan("acme", repo)
    assert p["zip"] == str(newest) and p["problems"] == []
    (repo / "stage").mkdir()
    (repo / "stage" / "leftover.txt").write_text("from an earlier build")
    out = dd.stage("acme", repo / "stage", repo / "out", repo)
    assert out["staged"] is True and (repo / "stage" / "tmf-debug-tool.exe").is_file()
    assert (repo / "stage" / "wheelhouse" / "tmf_support-1.0.0-py3-none-any.whl").is_file()
    assert not (repo / "stage" / "leftover.txt").exists()                              # staging never carries leftovers
    assert (repo / "out" / "tmf-debug-tool-1.2.3.zip").is_file()


def test_an_unsatisfiable_pin_stops_the_release_loudly(repo):
    pin(repo, delivery="bundle", version="1.x")
    with pytest.raises(dd.DeliveryError, match="no tmf-debug-tool-1.x.zip"):
        dd.stage("acme", repo / "stage", repo / "out", repo)
    pin(repo, delivery="bundle")
    with pytest.raises(dd.DeliveryError, match="version"):
        dd.stage("acme", repo / "stage", repo / "out", repo)
    pin(repo, delivery="bundle", version="1.x")
    make_zip(repo, "1.0.0", exe=False)
    with pytest.raises(dd.DeliveryError, match="does not contain tmf-debug-tool.exe"):
        dd.stage("acme", repo / "stage", repo / "out", repo)


def test_a_zip_that_does_not_match_its_checksum_is_refused(repo):
    pin(repo, delivery="bundle", version="1.x")
    z = make_zip(repo, "1.0.0")
    (z.parent / "SHA256SUMS.txt").write_text("0" * 64 + f"  {z.name}\n")
    assert any("SHA256SUMS" in p for p in dd.plan("acme", repo)["problems"])
    import hashlib
    (z.parent / "SHA256SUMS.txt").write_text(hashlib.sha256(z.read_bytes()).hexdigest() + f"  {z.name}\n")
    assert dd.plan("acme", repo)["problems"] == []


def test_a_zip_slip_member_cannot_escape_the_staging_folder(repo):
    pin(repo, delivery="bundle", version="1.x")
    make_zip(repo, "1.0.0", extra={"tmf-debug-tool/../../escaped.txt": "x"})
    with pytest.raises(dd.DeliveryError, match="escapes"):
        dd.stage("acme", repo / "stage", repo / "out", repo)
    assert not (repo.parent / "escaped.txt").exists() and not (repo / "escaped.txt").exists()


class FakeGh:
    def __init__(self, repo, tags):
        self.calls, self.repo, self.tags = [], repo, tags

    def __call__(self, argv, **kw):
        self.calls.append(argv)
        if argv[1:3] == ["release", "list"]:
            return subprocess.CompletedProcess(argv, 0, "\n".join(self.tags) + "\n", "")
        if argv[1:3] == ["release", "download"]:
            tag = argv[3]
            make_zip(self.repo, tag.replace("debug-tool-v", ""))
            return subprocess.CompletedProcess(argv, 0, "", "")
        return subprocess.CompletedProcess(argv, 1, "", "unexpected")


def test_fetch_downloads_the_newest_matching_release_asset(repo):
    pin(repo, delivery="bundle", version="1.x")
    gh = FakeGh(repo, ["debug-tool-v1.0.0", "debug-tool-v1.4.2", "debug-tool-v2.0.0", "v1.31.1", "debug-tool-v1.10.0"])
    z = dd.fetch("acme", "owner/fw", repo, runner=gh)
    assert z.name == "tmf-debug-tool-1.10.0.zip"
    dl = next(c for c in gh.calls if c[2] == "download")
    assert dl[3] == "debug-tool-v1.10.0" and "--repo" in dl and "owner/fw" in dl and "tmf-debug-tool-*.zip" in dl


def test_fetch_says_when_no_release_matches(repo):
    pin(repo, delivery="bundle", version="3.x")
    with pytest.raises(dd.DeliveryError, match="no debug-tool release matching"):
        dd.fetch("acme", "owner/fw", repo, runner=FakeGh(repo, ["debug-tool-v1.0.0"]))


def test_the_installer_offers_the_tool_as_an_optional_unticked_task_outside_run_dist():
    t = (ROOT / "deploy" / "installer.iss.template").read_text(encoding="utf-8")
    assert t.count('#if DebugToolDir != ""') == 3                                       # [Tasks], [Files], [Icons]
    assert 'Name: "debugtool"' in t and "Flags: unchecked" in t.split('Name: "debugtool"')[1].splitlines()[0]
    assert t.count("Tasks: debugtool") == 2
    assert 'DestDir: "{app}\\tools\\debug-tool"' in t and "run.dist\\tools" not in t
    assert "[Run]" in t and "debug-tool" not in t.split("[Run]")[1].split("[UninstallDelete]")[0]       # never auto-launched
    assert "[Registry]" not in t and "[Services]" not in t.replace("[Setup]", "")        # no startup entry, no service


def test_cut_release_and_build_installer_pass_the_staged_tool_through():
    cr = (ROOT / "deploy" / "cut-release.ps1").read_text(encoding="utf-8")
    assert "debug_tool_delivery.py" in cr and "7b/10" in cr and '$isccArg["DebugToolDir"]' in cr
    assert cr.index("7b/10") < cr.index("8/10  build setup.exe")
    bi = (ROOT / "deploy" / "build-installer.ps1").read_text(encoding="utf-8")
    assert "[string]$DebugToolDir" in bi and "/DDebugToolDir=" in bi and "tmf-debug-tool.exe" in bi


@pytest.mark.skipif(not PS, reason="PowerShell parser needed")
@pytest.mark.parametrize("script", ["build-debug-tool.ps1", "verify-debug-tool.ps1", "cut-release.ps1", "build-installer.ps1"])
def test_the_powershell_scripts_parse(script):
    cmd = ("$e=$null;$t=$null;[void][System.Management.Automation.Language.Parser]::ParseFile('%s',[ref]$t,[ref]$e);"
           "$e | ForEach-Object { $_.Message + ' @' + $_.Extent.StartLineNumber }" % str(ROOT / "deploy" / script))
    r = subprocess.run([PS, "-NoProfile", "-NonInteractive", "-Command", cmd], capture_output=True, text=True, timeout=60)
    assert r.stdout.strip() == "", r.stdout
