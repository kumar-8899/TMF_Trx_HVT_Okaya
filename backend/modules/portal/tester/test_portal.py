"""portal standalone tester (CORE.md §6.2): core + this one module, no broker."""

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport

import modules.portal  # noqa: F401 — import registers the module
from core.framework.contract import CoreServices
from core.framework.manifest import ManifestLoader
from core.framework.registry import default_registry
from core.services.auth_verify import AuthError, Principal, TokenVerifier
from core.services.db import Database
from core.services.diagnostics import Diagnostics
from modules.portal.search import SearchIndex, Doc
from modules.portal.variants.default import DefaultPortal


def make_pdf(text: str) -> bytes:
    """A tiny valid one-page PDF whose text layer is `text`."""
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 300] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
    ]
    stream = f"BT /F1 18 Tf 20 150 Td ({text}) Tj ET".encode()
    objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = b"%PDF-1.4\n"
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return out


_TOKENS = {
    "view": Principal("vera", role="operator", permissions=frozenset({"PORTAL.VIEW"})),
    "upload": Principal("ulla", role="engineer", permissions=frozenset({"PORTAL.VIEW", "PORTAL.UPLOAD"})),
    "manage": Principal("mara", role="admin",
                        permissions=frozenset({"PORTAL.VIEW", "PORTAL.UPLOAD", "PORTAL.MANAGE"})),
    "none": Principal("nobody", role="operator", permissions=frozenset()),
}


def _verify(token: str) -> Principal:
    if token in _TOKENS:
        return _TOKENS[token]
    raise AuthError("bad token")


def H(token: str, **extra) -> dict:
    return {"Authorization": f"Bearer {token}", **extra}


@pytest.fixture
async def ctx(tmp_path):
    db = Database(":memory:", station="st1", source_version="0.0.0")
    await db.connect()
    core = CoreServices(db=db, auth=TokenVerifier(),
                        diag=Diagnostics("st1", "0.0.0", sinks=[lambda e: None]), station="st1")
    core.auth.register(_verify)
    mod = DefaultPortal.construct(core, {"library": {"dir": str(tmp_path / "lib"), "max_upload_mb": 1}})
    await mod.init()
    app = FastAPI()
    app.state.auth = core.auth
    app.include_router(mod.router)
    client = httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t")
    yield client, mod, tmp_path
    await client.aclose()
    await db.close()


async def _upload(client, name="Tenma_72-13360_manual.pdf", text="Torque the terminal screw to 12 Nm",
                  token="upload", **params):
    return await client.post("/portal/library", params={"filename": name, **params},
                             content=make_pdf(text), headers=H(token, **{"Content-Type": "application/pdf"}))


# --- registration / manifest / lifecycle -------------------------------------------------------

def test_registered():
    rec = default_registry.get("portal")
    assert rec.variant_ids == ["default"]
    assert default_registry.variant("portal", "default") is DefaultPortal


def test_manifest_valid_and_bridge_free():
    m = ManifestLoader().load("portal")
    assert m.entitlement_key == "portal"
    assert "bridge" not in m.core_dependencies                     # no live MQTT (portal reasons over stored data)
    assert m.contributes.mqtt_subscriptions == []


async def test_lifecycle_and_health(ctx):
    _, mod, _ = ctx
    await mod.start()
    h = await mod.health()
    assert h.status.value == "ok" and "0 document" in h.detail
    await mod.stop()


# --- upload / list / view -----------------------------------------------------------------------

async def test_upload_list_and_view_round_trip(ctx):
    client, _, tmp = ctx
    r = await _upload(client, tags="Tenma, PSU ,tenma", description="Bench supply")
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["title"] == "Tenma 72-13360 manual" and doc["tags"] == ["tenma", "psu"]      # tidy + de-duped
    assert doc["uploaded_by"] == "ulla" and doc["source"] == "upload" and doc["searchable"] is True
    assert (tmp / "lib" / f"{doc['id']}.pdf").is_file()

    listed = (await client.get("/portal/library", headers=H("view"))).json()
    assert [d["id"] for d in listed] == [doc["id"]]

    f = await client.get(f"/portal/library/{doc['id']}/file", headers=H("view"))
    assert f.status_code == 200 and f.headers["content-type"] == "application/pdf"
    assert f.headers["content-disposition"].startswith("inline") and f.content.startswith(b"%PDF-")


async def test_upload_needs_the_upload_permission(ctx):
    client, _, _ = ctx
    assert (await _upload(client, token="view")).status_code == 403
    assert (await _upload(client, token="none")).status_code == 403
    r = await client.post("/portal/library", params={"filename": "x.pdf"}, content=b"%PDF-1.4")
    assert r.status_code == 401


async def test_only_pdfs_are_accepted(ctx):
    client, _, _ = ctx
    r = await client.post("/portal/library", params={"filename": "notes.pdf"}, content=b"just text",
                          headers=H("upload"))
    assert r.status_code == 415


async def test_size_limit_is_enforced_before_the_body_is_read(ctx):
    client, _, _ = ctx                                              # fixture limit: 1 MB
    big = b"%PDF-1.4\n" + b"0" * (1024 * 1024 + 10)
    r = await client.post("/portal/library", params={"filename": "big.pdf"}, content=big, headers=H("upload"))
    assert r.status_code == 413


async def test_duplicate_pdf_is_refused_and_names_the_existing_one(ctx):
    client, _, _ = ctx
    first = (await _upload(client)).json()
    r = await _upload(client, name="renamed copy.pdf")
    assert r.status_code == 409 and "already in the library" in r.json()["detail"]
    assert len((await client.get("/portal/library", headers=H("view"))).json()) == 1
    assert first["id"]


# --- search -------------------------------------------------------------------------------------

async def test_search_finds_text_inside_the_pdf_and_in_the_title(ctx):
    client, _, _ = ctx
    await _upload(client, text="Replace fuse F3 before powering the unit", name="Bench_wiring.pdf")
    by_text = (await client.get("/portal/library/search", params={"q": "fuse F3"}, headers=H("view"))).json()
    assert by_text["hits"] and by_text["hits"][0]["title"] == "Bench wiring"
    assert "fuse" in by_text["hits"][0]["snippet"].lower()
    by_title = (await client.get("/portal/library/search", params={"q": "wiring"}, headers=H("view"))).json()
    assert by_title["hits"]
    none = (await client.get("/portal/library/search", params={"q": "zzzunknownzzz"}, headers=H("view"))).json()
    assert none["hits"] == []


@pytest.mark.parametrize("q", ['"unbalanced', "a AND", "NEAR(", "*", "'; DROP TABLE t; --", "   "])
async def test_hostile_search_text_never_breaks_the_index(ctx, q):
    client, _, _ = ctx
    await _upload(client)
    r = await client.get("/portal/library/search", params={"q": q}, headers=H("view"))
    assert r.status_code == 200


def test_substring_fallback_when_fts5_is_unavailable(monkeypatch):
    import sqlite3
    idx = SearchIndex()
    real = sqlite3.connect

    class NoFts(sqlite3.Connection):
        def execute(self, sql, *a):
            if "fts5" in sql.lower():
                raise sqlite3.OperationalError("no such module: fts5")
            return super().execute(sql, *a)
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: real(*a, factory=NoFts, **k))
    idx.rebuild([Doc("d1", "Wiring guide", "psu", "Connect the red lead to terminal 3")])
    assert idx.fts is False
    assert idx.query("red lead")[0]["id"] == "d1"


# --- edit / delete ------------------------------------------------------------------------------

async def test_update_details_and_delete_rules(ctx):
    client, _, tmp = ctx
    doc = (await _upload(client)).json()
    up = await client.patch(f"/portal/library/{doc['id']}", json={"title": "PSU manual", "tags": ["a", "A", "b"]},
                            headers=H("upload"))
    assert up.status_code == 200 and up.json()["title"] == "PSU manual" and up.json()["tags"] == ["a", "b"]
    assert (await client.patch(f"/portal/library/{doc['id']}", json={"title": "x"}, headers=H("view"))).status_code == 403

    assert (await client.delete(f"/portal/library/{doc['id']}", headers=H("upload"))).status_code == 403   # MANAGE only
    assert (await client.delete(f"/portal/library/{doc['id']}", headers=H("manage"))).status_code == 200
    assert not (tmp / "lib" / f"{doc['id']}.pdf").exists() and not (tmp / "lib" / f"{doc['id']}.txt").exists()
    assert (await client.get("/portal/library", headers=H("view"))).json() == []
    gone = (await client.get("/portal/library/search", params={"q": "torque"}, headers=H("view"))).json()
    assert gone["hits"] == []                                        # index forgot it
    assert (await client.delete(f"/portal/library/{doc['id']}", headers=H("manage"))).status_code == 404


async def test_library_survives_a_restart(ctx):
    client, mod, tmp = ctx
    doc = (await _upload(client, text="Calibration interval is twelve months")).json()
    # a fresh module instance over the same db + dir = a station restart
    again = DefaultPortal.construct(mod.core, {"library": {"dir": str(tmp / "lib"), "max_upload_mb": 1}})
    await again.init()
    assert [d["id"] for d in await again.library.list()] == [doc["id"]]
    assert again.library.search("calibration interval")


# --- bundled, read-only documents an app ships ---------------------------------------------------

async def test_bundled_app_documents_are_listed_searchable_viewable_but_read_only(ctx, monkeypatch):
    client, mod, tmp = ctx
    lib = tmp / "app" / "acme_eol" / "portal" / "library"
    lib.mkdir(parents=True)
    (lib / "Relay_board_drawing.pdf").write_bytes(make_pdf("Relay board K1 to K8 wiring"))
    monkeypatch.setenv("TMF_APP_DIR", str(tmp / "app"))
    mod.library._seeds = None                                       # rescan
    await mod.library.reindex()

    docs = (await client.get("/portal/library", headers=H("view"))).json()
    seed = next(d for d in docs if d["source"] == "bundled")
    assert seed["id"] == "seed-acme_eol-Relay_board_drawing" and seed["title"] == "Relay board drawing"
    assert (await client.get(f"/portal/library/{seed['id']}/file", headers=H("view"))).content.startswith(b"%PDF-")
    assert (await client.get("/portal/library/search", params={"q": "relay board"}, headers=H("view"))).json()["hits"]
    assert (await client.delete(f"/portal/library/{seed['id']}", headers=H("manage"))).status_code == 403
    assert (await client.patch(f"/portal/library/{seed['id']}", json={"title": "x"}, headers=H("upload"))).status_code == 403


async def test_save_to_downloads_for_the_native_window(ctx, monkeypatch):
    client, _, tmp = ctx
    home = tmp / "home"
    (home / "Downloads").mkdir(parents=True)
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: home))
    doc = (await _upload(client, name="Wiring drawing.pdf")).json()
    r = await client.get(f"/portal/library/{doc['id']}/file", params={"save": "true"}, headers=H("view"))
    out = r.json()
    assert out["saved"] is True and out["filename"].startswith("Wiring drawing-") and out["filename"].endswith(".pdf")
    assert (home / "Downloads" / out["filename"]).read_bytes().startswith(b"%PDF-")
