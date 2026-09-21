"""core/services/docs_paths.py — where docs and app-owned portal content live (source vs frozen)."""

from pathlib import Path

from core.services import docs_paths


def test_docs_root_env_override_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("TMF_DOCS_DIR", str(tmp_path))
    assert docs_paths.resolve_docs_root() == tmp_path


def test_docs_root_in_a_source_checkout_is_the_repo_docs():
    root = docs_paths.resolve_docs_root()
    assert (root / "help").is_dir()


def _app(tmp_path: Path, name: str, with_portal: bool = True) -> Path:
    d = tmp_path / "app" / name
    d.mkdir(parents=True)
    if with_portal:
        (d / "portal").mkdir()
    return d


def test_app_portal_dirs_finds_each_apps_portal_folder(tmp_path, monkeypatch):
    _app(tmp_path, "acme_eol")
    _app(tmp_path, "other")
    _app(tmp_path, "no_portal", with_portal=False)
    monkeypatch.setenv("TMF_APP_DIR", str(tmp_path / "app"))
    found = docs_paths.app_portal_dirs()
    assert [p.parent.name for p in found] == ["acme_eol", "other"]      # sorted, only apps that have one


def test_app_portal_dirs_empty_when_no_app_payload(tmp_path, monkeypatch):
    monkeypatch.setenv("TMF_APP_DIR", str(tmp_path / "absent"))
    assert docs_paths.app_portal_dirs() == []
