"""help standalone tester — catalog + audience gating, no broker/db."""

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
