"""The portal library: PDFs (hardware manuals, wiring drawings…) users upload, plus read-only ones an
app ships in `app/<name>/portal/library/`.

Storage split (CORE.md §7): the PDF bytes live on disk under the state root — OUTSIDE `run.dist`, so an
in-app update never loses them — and each document is one `portal_document` record carrying the RAG
envelope with a plain-language summary. Extracted text sits in a `<id>.txt` sidecar and feeds the
in-memory search index (search.py). Deleting a document removes all three."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from core.services.config import resolve_state_path
from core.services.docs_paths import app_portal_dirs
from modules.portal.pdftext import extract_text
from modules.portal.search import Doc, SearchIndex

RECORD = "portal_document"
_MAX_TAGS = 12
_MAX_TAG_LEN = 32


class LibraryError(Exception):
    """A user-facing failure with the HTTP status the API should answer with."""

    def __init__(self, status: int, message: str, **extra) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.extra = extra


def _clean_tags(tags) -> list[str]:
    if isinstance(tags, str):
        tags = tags.split(",")
    out: list[str] = []
    for t in tags or []:
        t = re.sub(r"\s+", " ", str(t)).strip().lower()[:_MAX_TAG_LEN]
        if t and t not in out:
            out.append(t)
    return out[:_MAX_TAGS]


def _title_from(filename: str) -> str:
    stem = re.sub(r"\.pdf$", "", Path(filename).name, flags=re.I)
    return re.sub(r"[_\s]+", " ", stem).strip() or "Untitled document"


def _view(rec: dict) -> dict:
    d = rec["data"]
    return {"id": rec["id"], "title": d["title"], "filename": d.get("filename", ""), "bytes": d.get("bytes", 0),
            "sha256": d.get("sha256", ""), "tags": d.get("tags", []), "description": d.get("description", ""),
            "uploaded_by": d.get("uploaded_by"), "ts": rec.get("ts"), "source": d.get("source", "upload"),
            "pages": d.get("pages"), "searchable": bool(d.get("searchable"))}


class Library:
    def __init__(self, core, config: dict) -> None:
        self.core = core
        cfg = (config or {}).get("library", {}) or {}
        self.max_bytes = int(cfg.get("max_upload_mb", 50)) * 1024 * 1024
        self.dir: Path = resolve_state_path(cfg.get("dir", "data/portal/library"))
        self.index = SearchIndex()
        self._seeds: dict[str, dict] | None = None      # id -> {view, path, text}

    # --- bundled, read-only documents shipped with the app ----------------------------------------

    def _load_seeds(self) -> dict[str, dict]:
        if self._seeds is None:
            seeds: dict[str, dict] = {}
            for portal in app_portal_dirs():
                lib = portal / "library"
                for f in sorted(lib.glob("*.pdf")) if lib.is_dir() else []:
                    data = f.read_bytes()
                    text, pages = extract_text(data)
                    sid = f"seed-{portal.parent.name}-{f.stem}"
                    seeds[sid] = {"path": f, "text": text, "view": {
                        "id": sid, "title": _title_from(f.name), "filename": f.name, "bytes": len(data),
                        "sha256": hashlib.sha256(data).hexdigest(), "tags": ["bundled"], "description": "",
                        "uploaded_by": None, "ts": f.stat().st_mtime, "source": "bundled",
                        "pages": pages, "searchable": bool(text)}}
            self._seeds = seeds
        return self._seeds

    # --- reads --------------------------------------------------------------------------------------

    async def _records(self) -> list[dict]:
        return await self.core.db.repo.query(RECORD)

    async def list(self) -> list[dict]:
        docs = [_view(r) for r in await self._records()] + [s["view"] for s in self._load_seeds().values()]
        return sorted(docs, key=lambda d: d["title"].lower())

    async def get(self, doc_id: str) -> dict | None:
        rec = await self.core.db.repo.get(RECORD, doc_id)
        if rec:
            return _view(rec)
        seed = self._load_seeds().get(doc_id)
        return seed["view"] if seed else None

    async def file_bytes(self, doc_id: str) -> tuple[bytes, str] | None:
        seed = self._load_seeds().get(doc_id)
        if seed:
            return seed["path"].read_bytes(), seed["view"]["filename"]
        rec = await self.core.db.repo.get(RECORD, doc_id)
        path = self.dir / f"{doc_id}.pdf"
        if not rec or not path.is_file():
            return None
        return path.read_bytes(), rec["data"].get("filename", f"{doc_id}.pdf")

    # --- writes -------------------------------------------------------------------------------------

    async def add(self, filename: str, data: bytes, *, user: str | None, title: str | None = None,
                  tags=None, description: str = "") -> dict:
        if not data.startswith(b"%PDF-"):
            raise LibraryError(415, "Only PDF files can be added (the file does not start with a PDF header).")
        if len(data) > self.max_bytes:
            raise LibraryError(413, f"File is larger than the {self.max_bytes // (1024 * 1024)} MB limit.")
        sha = hashlib.sha256(data).hexdigest()
        for r in await self._records():
            if r["data"].get("sha256") == sha:
                raise LibraryError(409, f"This PDF is already in the library as '{r['data']['title']}'.",
                                   existing_id=r["id"])
        import uuid
        doc_id = f"doc-{uuid.uuid4().hex[:12]}"
        text, pages = extract_text(data)
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / f"{doc_id}.pdf").write_bytes(data)
        if text:
            (self.dir / f"{doc_id}.txt").write_text(text, encoding="utf-8")
        title = (title or "").strip() or _title_from(filename)
        payload = {"title": title, "filename": Path(filename).name or f"{doc_id}.pdf", "bytes": len(data),
                   "sha256": sha, "content_type": "application/pdf", "tags": _clean_tags(tags),
                   "description": (description or "").strip(), "uploaded_by": user, "source": "upload",
                   "pages": pages, "searchable": bool(text)}
        await self.core.db.repo.put(
            RECORD, payload, id=doc_id,
            summary=f"PDF '{title}' ({payload['filename']}, {len(data)} bytes) added to the portal library"
                    + (f" by {user}" if user else ""))
        await self.reindex()
        return _view(await self.core.db.repo.get(RECORD, doc_id))

    async def update(self, doc_id: str, *, title=None, tags=None, description=None) -> dict:
        rec = await self.core.db.repo.get(RECORD, doc_id)
        if rec is None:
            if doc_id in self._load_seeds():
                raise LibraryError(403, "Bundled documents are read-only.")
            raise LibraryError(404, "No such document.")
        d = dict(rec["data"])
        if title is not None and title.strip():
            d["title"] = title.strip()
        if tags is not None:
            d["tags"] = _clean_tags(tags)
        if description is not None:
            d["description"] = description.strip()
        await self.core.db.repo.put(RECORD, d, id=doc_id,
                                    summary=f"PDF '{d['title']}' details updated in the portal library")
        await self.reindex()
        return _view(await self.core.db.repo.get(RECORD, doc_id))

    async def delete(self, doc_id: str) -> None:
        if doc_id in self._load_seeds():
            raise LibraryError(403, "Bundled documents are read-only.")
        if await self.core.db.repo.get(RECORD, doc_id) is None:
            raise LibraryError(404, "No such document.")
        await self.core.db.repo.delete_id(RECORD, doc_id)
        for ext in (".pdf", ".txt"):
            (self.dir / f"{doc_id}{ext}").unlink(missing_ok=True)
        await self.reindex()

    # --- search -------------------------------------------------------------------------------------

    async def reindex(self) -> None:
        docs: list[Doc] = []
        for r in await self._records():
            txt = self.dir / f"{r['id']}.txt"
            text = txt.read_text(encoding="utf-8") if txt.is_file() else ""
            d = r["data"]
            docs.append(Doc(r["id"], d["title"], " ".join(d.get("tags", [])), text + "\n" + d.get("description", "")))
        for sid, s in self._load_seeds().items():
            docs.append(Doc(sid, s["view"]["title"], "bundled", s["text"]))
        self.index.rebuild(docs)

    def search(self, q: str, limit: int = 20) -> list[dict]:
        return self.index.query(q, limit)
