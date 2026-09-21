"""Portal router. PORTAL.VIEW reads/searches, PORTAL.UPLOAD adds + edits documents, PORTAL.MANAGE deletes.

Upload is a RAW body (`POST /portal/library?filename=…`, Content-Type application/pdf) rather than
multipart: no extra frozen dependency, and the size limit is enforced from Content-Length BEFORE the
body is read. Failures are HTTPException → RFC-7807 problem bodies (the web service's handlers)."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from core.services.auth_verify import Principal
from core.services.downloads import save_to_downloads
from core.services.security import require_permission
from modules.portal.library import LibraryError

_VIEW = Depends(require_permission("PORTAL.VIEW"))


def _fail(e: LibraryError) -> HTTPException:
    return HTTPException(status_code=e.status, detail=e.message)


def build_router(module) -> APIRouter:
    router = APIRouter(tags=["portal"])
    lib = module.library

    @router.get("/portal/library", dependencies=[_VIEW])
    async def list_documents() -> list[dict]:
        return await lib.list()

    @router.get("/portal/library/search", dependencies=[_VIEW])
    async def search(q: str = "", limit: int = 20) -> dict:
        """Full-text hits over library PDFs (title, tags, extracted text)."""
        return {"query": q, "fts": lib.index.fts, "hits": lib.search(q, max(1, min(limit, 50)))}

    @router.post("/portal/library")
    async def upload(request: Request, filename: str, title: str = "", tags: str = "", description: str = "",
                     principal: Principal = Depends(require_permission("PORTAL.UPLOAD"))) -> dict:
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > lib.max_bytes:
            raise HTTPException(status_code=413,
                                detail=f"File is larger than the {lib.max_bytes // (1024 * 1024)} MB limit.")
        body = await request.body()
        try:
            return await lib.add(filename, body, user=principal.subject, title=title or None,
                                 tags=tags, description=description)
        except LibraryError as e:
            raise _fail(e) from e

    @router.get("/portal/library/{doc_id}/file", dependencies=[_VIEW], response_model=None)
    async def file(doc_id: str, save: bool = False) -> Response | dict:
        got = await lib.file_bytes(doc_id)
        if got is None:
            raise HTTPException(status_code=404, detail="No such document.")
        data, filename = got
        if save:   # native window: save to the PC's Downloads and tell the user where
            return save_to_downloads(data, filename)
        return Response(content=data, media_type="application/pdf", headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(filename)}",
            "Cache-Control": "private, no-cache"})

    @router.patch("/portal/library/{doc_id}")
    async def update(doc_id: str, body: dict,
                     _: Principal = Depends(require_permission("PORTAL.UPLOAD"))) -> dict:
        try:
            return await lib.update(doc_id, title=body.get("title"), tags=body.get("tags"),
                                    description=body.get("description"))
        except LibraryError as e:
            raise _fail(e) from e

    @router.delete("/portal/library/{doc_id}")
    async def delete(doc_id: str, _: Principal = Depends(require_permission("PORTAL.MANAGE"))) -> dict:
        try:
            await lib.delete(doc_id)
        except LibraryError as e:
            raise _fail(e) from e
        return {"deleted": doc_id}

    return router
