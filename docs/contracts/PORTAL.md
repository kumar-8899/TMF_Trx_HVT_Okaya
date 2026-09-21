# PORTAL.md — User Portal module (contract)

The customer-facing support surface that replaces the printed software manual. **Framework module `portal`**
(`backend/modules/portal/`, entitlement `portal`, variant `default`). Depends on core only (`db, diagnostics,
config, auth, web`) — **no `bridge`: the portal never touches MQTT**; it reasons over stored data.

## Composition (who serves what)

| Piece | Served by | Why there |
|---|---|---|
| **Manual** — framework user pages + an app's own `app/<name>/portal/*.md` + images | `help` module | it already owns the catalog, F1 context help and search; modules never depend on each other, so the portal UI *composes* it on the frontend |
| **Library** — searchable PDFs | `portal` module | new storage + upload + search |
| *(later)* Assistant, troubleshooting chats, case log, support bundle | `portal` module | same corpus (manual + library + known issues + diagnostics records) |

The Portal screen (`/portal`) has a **Manual** tab (the help viewer, user audience only, links stay in the portal)
and a **Library** tab.

## Library

**Storage (CORE.md §7).** PDF bytes live on disk under the *state root*, outside `run.dist`
(`data/portal/library/<id>.pdf`, extracted text in `<id>.txt`) so an in-app update never loses them; each document
is one `portal_document` record carrying the RAG envelope with a plain-language `summary`:

```jsonc
{ "title": "Tenma 72-13360 manual", "filename": "tenma.pdf", "bytes": 250000, "sha256": "…",
  "content_type": "application/pdf", "tags": ["tenma","psu"], "description": "", "uploaded_by": "ulla",
  "source": "upload", "pages": 42, "searchable": true }
```

**Bundled documents.** PDFs an app ships in `app/<name>/portal/library/*.pdf` appear as `source: "bundled"`, id
`seed-<app>-<stem>`; they are read-only (no edit/delete) and are copied into `run.dist/app/<name>/portal/` by the
build.

**Search.** `pypdf` extracts text (best effort: scans/encrypted files are stored and viewable but flagged
*not searchable*). An **in-memory SQLite FTS5** index (title, tags, body; bm25 ranking, snippets) is rebuilt from
the durable records at start-up and after every change — no extra tables in the station database. If FTS5 is
missing it degrades to a substring scan. User text is sanitised into a safe FTS query.

### Permissions

| Permission | Grants | Default roles |
|---|---|---|
| `PORTAL.VIEW` | open the portal, list/search/read documents | every role |
| `PORTAL.UPLOAD` | add PDFs, edit title/tags/description | admin, engineer |
| `PORTAL.MANAGE` | delete documents (later: review all chats) | admin |
| (`PORTAL.*`) | all of the above | super_admin |

Existing stations pick these up with `python -m tools.config_doctor --apply` **and a re-login**.

### REST

| Method & path | Needs | Notes |
|---|---|---|
| `GET /portal/library` | VIEW | all documents, sorted by title |
| `GET /portal/library/search?q=&limit=` | VIEW | `{query, fts, hits:[{id,title,snippet,score}]}` |
| `POST /portal/library?filename=&title=&tags=&description=` | UPLOAD | **raw body** `application/pdf` (no multipart dependency); 415 not a PDF · 413 over the limit (checked from `Content-Length` before reading) · 409 duplicate (sha256) |
| `GET /portal/library/{id}/file` | VIEW | inline PDF; `?save=true` writes to the PC's Downloads folder and returns `{saved, path}` (the native window can't blob-download) |
| `PATCH /portal/library/{id}` | UPLOAD | title / tags (≤12, lower-cased) / description; 403 for bundled |
| `DELETE /portal/library/{id}` | MANAGE | removes record, PDF and text sidecar; 403 for bundled |

Errors are `HTTPException` → RFC-7807 problem bodies.

### Viewing

The frontend fetches the PDF **with the bearer header**, makes a `blob:` URL and shows it in an `<iframe>`; the
WebView2/browser PDF viewer supplies navigation, zoom, search, print. (Verified in a real pywebview/WebView2
window — no `pdf.js` dependency.)

## Config (`app.json` → module `portal` → `config`)

```jsonc
{ "id": "portal", "variant": "default", "config": { "library": { "max_upload_mb": 50, "dir": "data/portal/library" } } }
```

## App-owned content (TEMPLATE.md §1)

`app/<name>/portal/` is **app-owned**: `*.md` pages (optional front matter `title, section, order, route`; default
section "This app"), `img/*` (referenced as `![alt](asset:app/<file>)`), `library/*.pdf`. Discovery is by
`core.services.docs_paths.app_portal_dirs()` (source: `app/*/portal`; frozen: `run.dist/app/*/portal`).

## Not in this release

The troubleshooting assistant (pluggable `none | anthropic | ollama`), chat log, save-as-case and support bundle
(plan: `docs/DEVELOPER_HUB.md` → User Portal roadmap).
