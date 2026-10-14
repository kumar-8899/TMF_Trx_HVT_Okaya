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

The Portal screen (`/portal`) is the **one user-facing documentation surface** (v1.31.0 merged the former separate
user "Help" page into it). Tabs:

| Tab | Content | Needs |
|---|---|---|
| **Manual** | the help viewer, user audience only, links stay in the portal (`/portal?tab=manual&page=<id>`) | `PORTAL.VIEW` |
| **Library** | searchable PDFs | `PORTAL.VIEW` |
| **Test Sequence** | what each step of *this product's* test does - **authored per application**, see below | `PORTAL.SEQUENCE` |

What remains of `/help`: the **F1 / "Help" drawer** (context help, any screen) whose "Open full help" now lands on the
Manual tab; the `/help` route itself for **Developer docs** (super_admin on a source checkout - a built station ships
no developer pages, so the nav entry never appears there); and a plain "Help" nav entry only for a role that has
`HELP.VIEW` but not `PORTAL.VIEW`. The backend `help` and `portal` modules stay separate (modules never depend on
each other); only the frontend composes them.

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
| `PORTAL.SEQUENCE` | see the **Test Sequence** tab | admin (+ super_admin via `PORTAL.*`) |
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

## Test Sequence tab - the framework ships the shell, each app authors the content

**Decision (v1.31.0):** the framework does **not** generate this tab from the live recipe. What a technician needs to
read (why a step exists, how it is wired, what a limit means) is product knowledge, and a timeline auto-built from
`steps[]` would drift from reality or read as noise. The framework provides: the tab, the `PORTAL.SEQUENCE`
permission, and two **screen-registry keys** (`frontend/src/app/registry.ts`):

| key | replaces | typical use |
|---|---|---|
| `portal-test-sequence` | only the Test Sequence tab body (framework default = a short "not published yet" placeholder) | **this is the one a fork overrides** |
| `portal` | the whole Portal screen | only if the app wants a different layout; you then own the tabs |

### How a forked app authors it (do this in the fork, after its tests exist)

Ask the fork's own Claude Code session: *"Create the Test Sequence portal tab for this app."* The workflow it
should follow:

1. **Read the sources of truth, do not invent**: `app/<slug>/recipes/*.json` (steps, params, limits),
   `app/<slug>/specs/<test>.md` (the per-test procedure specs), `app/<slug>/maps/<station>.json` (signals/units) and
   the step-type schemas (`app/<slug>/<slug>_steps/*/schema.json`).
2. **Write a view component** under `frontend/src/app/overrides/` (e.g. `portal_sequence/TestSequenceView.tsx`) and
   register it in a file that default-exports `{ key: "portal-test-sequence", component: TestSequenceView }`.
   The component takes no props. It may render static, hand-written content (recommended: one section per step -
   purpose, wiring/fixture notes, expected result, what a FAIL means) **or** fetch what it needs through the
   framework API client (`src/api`) - e.g. `GET /recipes/<id>` for live limits so numbers never go stale.
3. **Prefer data over prose duplication**: show limits and units from the recipe at render time; keep the explanation
   in the spec `.md` files (`TEST_SPECS.md`) and render or link them, so there is one source per fact.
4. **Never edit framework files** (`screens/Portal.tsx`, `App.tsx`, `Layout.tsx`): the override file is the whole
   change, which is what keeps `git merge upstream/<version>` clean (TEMPLATE.md section 1.3).
5. **Test it**: a vitest that renders the component with a mocked recipe, and register nothing else. Add
   `PORTAL.SEQUENCE` to the roles that should see it (default: admin, super_admin) via the permissions page.
6. **Mention it** in the app's `portal/*.md` or release notes so the operators know the tab exists.

`PORTAL.SEQUENCE` is a new permission: existing stations pick it up with
`python -m tools.config_doctor --apply` **and a re-login**.

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
