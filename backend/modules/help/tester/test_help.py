"""help standalone tester — catalog + audience gating, no broker/db."""

import json

import pytest

from modules.help import catalog
from modules.help.variants.default import DefaultHelp


class _Core:
    pass


def _mod():
    return DefaultHelp.construct(_Core(), {})


def test_every_catalog_page_resolves_to_a_file():
    # guards typos / missing docs in the catalog
    missing = [p.id for p in catalog.PAGES if catalog.resolve(p) is None]
    assert missing == [], f"unresolved help pages: {missing}"


def test_index_audience_gating():
    mod = _mod()
    user = mod.index(include_dev=False)
    assert user and all(p["audience"] == "user" for s in user for p in s["pages"])
    full = mod.index(include_dev=True)
    audiences = {p["audience"] for s in full for p in s["pages"]}
    assert audiences == {"user", "dev"}


def test_page_gating():
    mod = _mod()
    assert mod.page("user-test-bench", include_dev=False)["title"] == "Test Bench"
    assert mod.page("dev-principles", include_dev=False) is None     # dev hidden
    assert mod.page("dev-principles", include_dev=True)["audience"] == "dev"
    assert mod.page("nope", include_dev=True) is None


def test_context_for_route():
    mod = _mod()
    assert mod.for_route("/runs", include_dev=False)["id"] == "user-test-bench"
    assert mod.for_route("/config/instruments", include_dev=False)["id"] == "user-instruments"
    assert mod.for_route("/nowhere", include_dev=False) is None


def test_search_respects_audience():
    mod = _mod()
    assert any(h["id"] == "user-recipes" for h in mod.search("recipe", include_dev=False))
    # a dev-only term must not leak to a user search
    dev_hits = mod.search("CoreServices", include_dev=False)
    assert all(h["audience"] == "user" for h in dev_hits)


# --- catalog integrity (drift gates) ---------------------------------------

def test_no_duplicate_page_ids():
    ids = [p.id for p in catalog.PAGES]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    assert dupes == [], f"duplicate help page ids: {dupes}"


def test_every_help_markdown_file_is_in_the_catalog():
    """Reverse of test_every_catalog_page_resolves_to_a_file: a doc dropped under docs/help/ that
    nobody registered is invisible to users — fail so it's either catalogued or moved."""
    listed = {(catalog.DOCS_ROOT / p.file).resolve() for p in catalog.PAGES}
    orphans = sorted(str(f.relative_to(catalog.DOCS_ROOT.resolve()))
                     for f in (catalog.DOCS_ROOT / "help").rglob("*.md")
                     if f.resolve() not in listed)
    assert orphans == [], f"help markdown not in catalog: {orphans}"


# --- frozen builds never expose developer docs ------------------------------

def test_frozen_build_hides_all_dev_pages(monkeypatch):
    monkeypatch.setattr(catalog, "is_frozen", lambda: True)
    mod = _mod()
    tree = mod.index(include_dev=True)                    # even a super_admin asking for dev
    assert {p["audience"] for s in tree for p in s["pages"]} == {"user"}
    assert mod.page("dev-principles", include_dev=True) is None
    assert mod.search("CoreServices", include_dev=True) == [] or all(
        h["audience"] == "user" for h in mod.search("CoreServices", include_dev=True))
    assert mod.facts(include_dev=True) is None


# --- shared asset library ---------------------------------------------------

@pytest.fixture
def assets_root(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    (docs / "help").mkdir(parents=True)
    (docs / "assets" / "screens").mkdir(parents=True)
    (docs / "assets" / "screens" / "dash.png").write_bytes(b"\x89PNG-dash")
    (docs / "assets" / "screens" / "internal.png").write_bytes(b"\x89PNG-internal")
    (docs / "assets" / "secret.txt").write_text("nope")
    (tmp_path / "frontend" / "src").mkdir(parents=True)
    src = tmp_path / "frontend" / "src" / "Dash.tsx"
    src.write_text("v1\r\nline\r\n")                       # CRLF: hash must be line-ending stable
    (docs / "assets" / "manifest.json").write_text(json.dumps({
        "schema_version": 1,
        "images": [
            {"id": "dashboard", "file": "screens/dash.png", "alt": "Dashboard", "audience": "both",
             "framework_version": "1.23.0", "source": "frontend/src/Dash.tsx",
             "source_hash": catalog.source_hash(src)},
            {"id": "internal", "file": "screens/internal.png", "alt": "Internal", "audience": "dev",
             "framework_version": "1.23.0"},
            {"id": "escape", "file": "../../secret.txt", "alt": "x", "audience": "both"},
        ]}))
    monkeypatch.setattr(catalog, "DOCS_ROOT", docs)
    return docs, src


def test_asset_served_by_manifest_id(assets_root):
    mod = _mod()
    got = mod.asset("dashboard", include_dev=False)
    assert got == (b"\x89PNG-dash", "image/png")


def test_dev_only_asset_hidden_from_users(assets_root):
    mod = _mod()
    assert mod.asset("internal", include_dev=False) is None
    assert mod.asset("internal", include_dev=True) is not None


def test_asset_unknown_id_and_traversal_rejected(assets_root):
    mod = _mod()
    assert mod.asset("nope", include_dev=True) is None
    assert mod.asset("escape", include_dev=True) is None            # manifest entry escaping assets/
    assert mod.asset("../assets/secret.txt", include_dev=True) is None


def test_frozen_build_serves_no_dev_assets(assets_root, monkeypatch):
    monkeypatch.setattr(catalog, "is_frozen", lambda: True)
    assert _mod().asset("internal", include_dev=True) is None


def test_asset_list_reports_capture_version_and_staleness(assets_root):
    _, src = assets_root
    mod = _mod()
    by_id = {a["id"]: a for a in mod.assets(include_dev=False)}
    assert set(by_id) == {"dashboard"}                               # dev + escaping entries filtered
    assert by_id["dashboard"]["framework_version"] == "1.23.0"
    assert by_id["dashboard"]["stale"] is False
    src.write_text("v2 — screen changed\n")
    assert {a["id"]: a for a in mod.assets(include_dev=False)}["dashboard"]["stale"] is True


# --- generated facts --------------------------------------------------------

def test_facts_served_to_dev_only(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    (docs / "help").mkdir(parents=True)
    (docs / "generated").mkdir()
    (docs / "generated" / "facts.json").write_text(json.dumps({"framework": {"version": "9.9.9"}}))
    monkeypatch.setattr(catalog, "DOCS_ROOT", docs)
    mod = _mod()
    assert mod.facts(include_dev=True)["framework"]["version"] == "9.9.9"
    assert mod.facts(include_dev=False) is None


# --- help pages only reference things that exist (drift gates) --------------

def _all_help_markdown():
    return [(p, catalog.read(p) or "") for p in catalog.PAGES]


def test_every_asset_reference_exists_in_the_manifest():
    import re
    ids = {e["id"] for e in catalog._manifest()}
    missing = sorted({(p.id, m) for p, md in _all_help_markdown()
                      for m in re.findall(r"\(asset:([\w.-]+)\)", md) if m not in ids})
    assert missing == [], f"help pages reference assets not in docs/assets/manifest.json: {missing}"


def test_every_tmf_directive_names_a_registered_widget():
    """```tmf:<name>``` blocks resolve through the frontend widget registry; a typo would render an
    error box for readers, so catch it here (registry = registerWidget("name", …) calls)."""
    import re
    from pathlib import Path
    widgets_dir = Path(catalog.DOCS_ROOT).parent / "frontend" / "src" / "components" / "help" / "widgets"
    if not widgets_dir.is_dir():
        pytest.skip("frontend sources not present (built station)")
    registered = {m for f in widgets_dir.glob("*.ts*")
                  for m in re.findall(r'registerWidget\(\s*"([\w-]+)"', f.read_text(encoding="utf-8"))}
    used = {(p.id, m) for p, md in _all_help_markdown() for m in re.findall(r"```tmf:([\w-]+)", md)}
    unknown = sorted(u for u in used if u[1] not in registered)
    assert unknown == [], f"unknown tmf widgets: {unknown} (registered: {sorted(registered)})"


def test_every_help_link_targets_a_real_page():
    import re
    ids = {p.id for p in catalog.PAGES}
    bad = sorted({(p.id, m) for p, md in _all_help_markdown()
                  for m in re.findall(r"\(help:([\w-]+)(?:#[\w-]*)?\)", md) if m not in ids})
    assert bad == [], f"help: links to unknown pages: {bad}"


# --- app-owned manual pages: app/<name>/portal/*.md ("This app") -------------

@pytest.fixture
def app_portal(tmp_path, monkeypatch):
    portal = tmp_path / "app" / "acme_eol" / "portal"
    (portal / "img").mkdir(parents=True)
    (portal / "wiring.md").write_text(
        "---\ntitle: Wiring the bench\nsection: Bench setup\norder: 2\nroute: /runs\n---\n"
        "# Wiring\n\nConnect the PSU.\n\n![diagram](asset:app/wiring.png)\n", encoding="utf-8")
    (portal / "intro.md").write_text("# Intro\n\nNo front matter here.\n", encoding="utf-8")
    (portal / "img" / "wiring.png").write_bytes(b"\x89PNG-app")
    (portal / "img" / "notes.txt").write_text("not an image")
    (tmp_path / "secret.png").write_bytes(b"\x89PNG-secret")
    monkeypatch.setenv("TMF_APP_DIR", str(tmp_path / "app"))
    return portal


def test_app_pages_are_discovered_for_every_user(app_portal):
    mod = _mod()
    tree = mod.index(include_dev=False)
    sec = {s["section"]: s for s in tree}
    assert "Bench setup" in sec and "This app" in sec                  # front-matter section + default
    titles = {p["id"]: p["title"] for s in tree for p in s["pages"]}
    assert titles["app-acme_eol-wiring"] == "Wiring the bench"
    assert titles["app-acme_eol-intro"] == "intro"                      # no front matter -> file stem


def test_app_page_serves_body_without_front_matter(app_portal):
    doc = _mod().page("app-acme_eol-wiring", include_dev=False)
    assert doc["markdown"].startswith("# Wiring")
    assert "order: 2" not in doc["markdown"] and doc["audience"] == "user"


def test_app_page_route_feeds_context_help(app_portal):
    assert _mod().for_route("/runs", include_dev=False)["id"] in ("user-test-bench", "app-acme_eol-wiring")


def test_app_pages_survive_a_frozen_build_which_hides_only_developer_content(app_portal, monkeypatch):
    monkeypatch.setattr(catalog, "is_frozen", lambda: True)
    assert _mod().page("app-acme_eol-wiring", include_dev=True) is not None


def test_app_page_is_searchable(app_portal):
    assert any(h["id"] == "app-acme_eol-wiring" for h in _mod().search("Connect the PSU", include_dev=False))


def test_app_asset_served_from_the_portal_img_folder_only(app_portal):
    mod = _mod()
    assert mod.app_asset("wiring.png") == (b"\x89PNG-app", "image/png")
    assert mod.app_asset("notes.txt") is None                           # not an image extension
    assert mod.app_asset("../../../secret.png") is None                 # traversal
    assert mod.app_asset("missing.png") is None


def test_no_app_payload_means_no_app_section(tmp_path, monkeypatch):
    monkeypatch.setenv("TMF_APP_DIR", str(tmp_path / "absent"))
    assert all(s["section"] != "This app" for s in _mod().index(include_dev=False))
