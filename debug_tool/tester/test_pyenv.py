"""debug_tool.pyenv - the interpreter a PC without Python gets. A real embeddable-style package is built from this PC's Python."""

import subprocess
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from debug_tool.pyenv import PythonEnv, PythonUnavailable, _probe
from debug_tool.scripts import ScriptRunner

WIN = sys.platform == "win32"


def _no_python(_name):
    return None


@pytest.fixture(scope="session")
def embed_zip(tmp_path_factory):
    """Mimic python.org's 'Windows embeddable package' from this PC's Python (see make_embed.py)."""
    if not WIN:
        pytest.skip("the embeddable package is Windows-only")
    from debug_tool.tester.make_embed import build_embeddable_like
    return build_embeddable_like(tmp_path_factory.mktemp("embed"), "python-embed-test.zip")


def make_env(tmp_path, embed_zip=None, **kw):
    tool = tmp_path / "tool"
    tool.mkdir(exist_ok=True)
    if embed_zip:
        (tool / embed_zip.name).write_bytes(embed_zip.read_bytes())
    return PythonEnv(tool, tmp_path / "data" / "python", which=kw.pop("which", _no_python), **kw)


def fake_wheel(path: Path, pkg="foo_pkg", value="42"):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(f"{pkg}/__init__.py", f"VALUE = {value}\n")
        z.writestr(f"{pkg}-1.0.dist-info/METADATA", f"Metadata-Version: 2.1\nName: {pkg}\nVersion: 1.0\n")


def test_first_use_extracts_the_bundled_interpreter_and_it_runs(tmp_path, embed_zip):
    env = make_env(tmp_path, embed_zip)
    st = env.status()
    assert st["can_extract"] and not st["extracted"] and st["will_use"].startswith("bundled")
    got = env.resolve()
    assert got["kind"] == "bundled" and Path(got["path"]).is_file() and got["version"].startswith(f"{sys.version_info.major}.{sys.version_info.minor}")
    assert any("extracted" in n for n in got["notes"])
    pth = next((tmp_path / "data" / "python").glob("python*._pth")).read_text()
    assert "Lib\\site-packages" in pth and "\nimport site" in pth and "#import site" not in pth
    assert env.status()["extracted"] and env.status()["will_use"] == "extracted"
    again = env.resolve()                                                  # second time: no re-extraction
    assert again["path"] == got["path"] and not any("extracted the bundled" in n for n in again["notes"])


def test_the_bundled_interpreter_is_isolated_from_the_hosts_packages(tmp_path, embed_zip):
    env = make_env(tmp_path, embed_zip)
    exe = env.resolve()["path"]
    r = subprocess.run([exe, "-I", "-c", "import sys, json; print(json.dumps(sys.path))"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    paths = r.stdout
    assert "site-packages" in paths and str(Path(sys.base_prefix) / "Lib") not in paths.replace("\\\\", "\\")


def test_wheelhouse_wheels_become_importable_offline_and_install_once(tmp_path, embed_zip):
    env = make_env(tmp_path, embed_zip)
    house = tmp_path / "tool" / "wheelhouse"
    house.mkdir()
    fake_wheel(house / "foo_pkg-1.0-py3-none-any.whl")
    got = env.resolve()
    assert any("foo_pkg" in n for n in got["notes"])
    r = subprocess.run([got["path"], "-I", "-c", "import foo_pkg; print(foo_pkg.VALUE)"], capture_output=True, text=True, timeout=60)
    assert r.stdout.strip() == "42", r.stderr
    assert env.install_wheelhouse() == []                                   # idempotent
    assert env.status()["installed_wheels"][0]["name"] == "foo_pkg-1.0-py3-none-any.whl"


@pytest.mark.asyncio
async def test_a_python_script_runs_on_the_bundled_interpreter_through_the_runner(tmp_path, embed_zip):
    env = make_env(tmp_path, embed_zip)
    runner = ScriptRunner(tmp_path / "scripts", env.resolve)
    res = await runner.run("python", "import sys\nprint('ran on', sys.version_info[0])")
    assert res["exit_code"] == 0 and "ran on 3" in res["stdout"] and res["python"]["kind"] == "bundled"


def test_falls_back_to_a_system_python_that_proves_it_runs(tmp_path):
    env = make_env(tmp_path, which=lambda n: sys.executable if n == "python" else None)
    got = env.resolve()
    assert got["kind"] == "system" and got["path"] == sys.executable


def test_the_windows_store_stub_is_not_mistaken_for_python(tmp_path):
    stub = SimpleNamespace(returncode=9009, stdout="", stderr="Python was not found; run without arguments to install from the Microsoft Store")
    env = make_env(tmp_path, which=lambda n: r"C:\Users\x\AppData\Local\Microsoft\WindowsApps\python.exe" if n == "python" else None,
                   run=lambda *a, **k: stub)
    with pytest.raises(PythonUnavailable) as e:
        env.resolve()
    assert "no usable Python" in str(e.value) and "python-embed" in str(e.value) and "not a python interpreter" in str(e.value)
    assert env.status()["system_python"] is None and env.status()["will_use"] == "none"


def test_too_old_python_is_refused():
    ok, info = _probe("py2", run=lambda *a, **k: SimpleNamespace(returncode=0, stdout="3.6.8\n", stderr=""))
    assert not ok and "too old" in info


def test_a_bad_bundle_is_reported_and_the_system_python_is_still_tried(tmp_path):
    bad = tmp_path / "tool" / "python-embed-bad.zip"
    bad.parent.mkdir()
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("readme.txt", "not python")
    env = PythonEnv(bad.parent, tmp_path / "data" / "py", which=lambda n: sys.executable if n == "python" else None)
    got = env.resolve()
    assert got["kind"] == "system" and any("did not contain python.exe" in n for n in got["notes"])


def test_an_archive_member_that_escapes_the_folder_is_refused(tmp_path):
    evil = tmp_path / "tool" / "python-embed-evil.zip"
    evil.parent.mkdir()
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("../../escaped.txt", "x")
    env = PythonEnv(evil.parent, tmp_path / "data" / "py", which=_no_python)
    with pytest.raises(PythonUnavailable):
        env.resolve()
    assert not (tmp_path / "escaped.txt").exists()


def test_nothing_available_says_how_to_fix_it(tmp_path):
    with pytest.raises(PythonUnavailable, match="python-embed"):
        make_env(tmp_path).resolve()
