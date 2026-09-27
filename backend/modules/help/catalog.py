"""Help content catalog — the whitelist of doc pages the help module serves.

Two audiences: `user` (all signed-in users) and `dev` (super_admin only). Pages
map to markdown files under the repo `docs/` tree. Serving is **whitelist-only**
(id -> known file) so there is no arbitrary file read / path traversal. Dev pages
surface the existing design docs as-is; user pages + a few dev guides are authored
under docs/help/.

**Developer content never ships to a client station.** The frozen build copies only the user
allowlist (build_release.copy_docs_frontend_dll) AND `is_frozen()` hides every dev page/asset/fact
here, so a super_admin on a built station sees the user manual only (defence in depth).

Shared asset library: `docs/assets/manifest.json` lists screenshots/diagrams by id with an
`audience` (user | dev | both). Only manifest entries are ever served (never a raw path).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.services.docs_paths import app_portal_dirs, resolve_docs_root

DOCS_ROOT = resolve_docs_root()

APP_SECTION = "This app"          # default sidebar group for app-owned pages (app/<name>/portal/*.md)


def is_frozen() -> bool:
    """True in a Nuitka/PyInstaller-built station (developer docs are hidden there)."""
    import sys
    return "__compiled__" in globals() or bool(getattr(sys, "frozen", False))


@dataclass(frozen=True)
class Page:
    id: str
    title: str
    audience: str          # "user" | "dev"
    section: str           # sidebar grouping
    file: str              # path relative to DOCS_ROOT (framework pages) — or absolute for app pages
    route: str | None = None   # app route this page documents (context-aware help)
    app_root: str | None = None   # set for app-owned pages: the app/<name>/portal dir the file must sit in


PAGES: list[Page] = [
    # ---------- USER ----------
    Page("user-getting-started", "Getting started", "user", "Getting started", "help/user/getting-started.md", "/"),
    Page("user-dashboard", "Dashboard", "user", "Getting started", "help/user/dashboard.md", "/"),
    Page("user-test-bench", "Test Bench", "user", "Operations", "help/user/test-bench.md", "/runs"),
    Page("user-recipes", "Recipes", "user", "Operations", "help/user/recipes.md", "/recipes"),
    Page("user-reports", "Reports", "user", "Operations", "help/user/reports.md", "/reports"),
    Page("user-analytics", "Analytics", "user", "Operations", "help/user/analytics.md", "/analytics"),
    Page("user-health", "Production Readiness", "user", "Health & maintenance", "help/user/health.md", "/health"),
    Page("user-maintenance", "Maintenance Console", "user", "Health & maintenance", "help/user/maintenance.md", "/maintenance"),
    Page("user-branding", "App identity", "user", "Configuration", "help/user/branding.md", "/config/branding"),
    Page("user-instruments", "Instruments", "user", "Configuration", "help/user/instruments.md", "/config/instruments"),
    Page("user-variable-map", "Variable Map", "user", "Configuration", "help/user/variable-map.md", "/config/variables"),
    Page("user-shift", "Shifts", "user", "Configuration", "help/user/shift.md", "/config/shift"),
    Page("user-barcode", "Barcode", "user", "Configuration", "help/user/barcode.md", "/config/barcode"),
    Page("user-mes", "MES interlock", "user", "Configuration", "help/user/mes.md", "/config/mes"),
    Page("user-users", "Users", "user", "Administration", "help/user/users.md", "/users"),
    Page("user-permissions", "Permissions", "user", "Administration", "help/user/permissions.md", "/permissions"),
    Page("user-settings", "Settings", "user", "Administration", "help/user/settings.md", "/settings"),
    Page("user-portal", "User Portal", "user", "Help", "help/user/portal.md", "/portal"),
    Page("user-troubleshooting", "Troubleshooting", "user", "Help", "help/user/troubleshooting.md"),
    Page("user-glossary", "Glossary", "user", "Help", "help/user/glossary.md"),

    # ---------- DEV (super_admin; source checkout only — never in a built station) ----------
    Page("dev-guide-start", "Developer Hub", "dev", "Start here", "help/dev/guide/start-here.md"),
    Page("dev-guide-first-app", "Your first app in 30 minutes", "dev", "Start here", "help/dev/guide/first-app.md"),
    Page("dev-guide-which-skill", "Which skill do I use?", "dev", "Start here", "help/dev/guide/which-skill.md"),
    Page("dev-onboarding", "Onboarding: install & set up", "dev", "Start here", "DEVELOPER_ONBOARDING.md"),
    Page("dev-guide-mental-model", "Mental model", "dev", "Concepts", "help/dev/guide/mental-model.md"),
    Page("dev-guide-principles", "Principles — what they mean for you", "dev", "Concepts", "help/dev/guide/principles.md"),
    Page("dev-guide-ownership", "Ownership boundary", "dev", "Concepts", "help/dev/guide/ownership.md"),
    Page("dev-guide-building-blocks", "Building blocks", "dev", "Concepts", "help/dev/guide/building-blocks.md"),
    Page("dev-principles", "Principles (full document)", "dev", "Concepts", "PRINCIPLES.md"),
    Page("dev-architecture", "Architecture", "dev", "Concepts", "ARCHITECTURE.md"),
    Page("dev-template", "Application template & ownership boundary", "dev", "Concepts", "TEMPLATE.md"),
    Page("dev-module-framework", "Module framework", "dev", "Concepts", "help/dev/module-framework.md"),
    Page("dev-core-services", "Core services", "dev", "Concepts", "help/dev/core-services.md"),
    Page("dev-python-controller", "Python controller", "dev", "Concepts", "PYTHON_CONTROLLER.md"),
    Page("dev-multi-station", "Multi-station & stations", "dev", "Concepts", "MULTI_STATION.md"),
    Page("dev-instrument-library", "Instrument library", "dev", "Concepts", "help/dev/instrument-library.md"),
    Page("dev-guide-facts", "Facts & figures (generated)", "dev", "Reference", "help/dev/guide/facts.md"),
    Page("dev-guide-screens", "Screens tour", "dev", "Reference", "help/dev/guide/screens-tour.md"),
    Page("dev-guide-contracts-map", "I want to… → read this", "dev", "Reference", "help/dev/guide/contracts-map.md"),
    Page("dev-hub-contract", "How the Developer Hub works", "dev", "Reference", "DEVELOPER_HUB.md"),
    Page("dev-guide-glossary", "Developer glossary", "dev", "Reference", "help/dev/guide/glossary.md"),
    Page("dev-guide-whats-new", "What's new & upgrading", "dev", "Stay current", "help/dev/guide/whats-new.md"),
    Page("dev-guide-gotchas", "Gotchas & FAQ", "dev", "Stay current", "help/dev/guide/gotchas.md"),
    Page("dev-workflow", "Dev workflow", "dev", "How-to", "help/dev/workflow.md"),
    Page("dev-extending", "Extension how-tos", "dev", "How-to", "help/dev/extending.md"),
    Page("dev-running", "Running the app", "dev", "How-to", "RUNNING.md"),
    Page("dev-app-repo", "Building an app repo", "dev", "How-to", "APP_REPO.md"),
    Page("dev-system-blueprint", "System Blueprint", "dev", "How-to", "SYSTEM_BLUEPRINT.md"),
    Page("dev-test-specs", "Test procedure specs", "dev", "How-to", "TEST_SPECS.md"),
    Page("dev-deploy-station", "Deploying to a station", "dev", "How-to", "DEPLOY_STATION.md"),
    Page("dev-release-howto", "Cutting a release", "dev", "How-to", "RELEASE_HOWTO.md"),
    Page("dev-updates", "Updates, rollback & AMC", "dev", "How-to", "UPDATES.md"),
    Page("dev-secure-distribution", "Secure distribution", "dev", "How-to", "SECURE_DISTRIBUTION.md"),
    Page("dev-remote-debug", "Remote debugging", "dev", "How-to", "REMOTE_DEBUG.md"),
    Page("dev-core", "CORE contract", "dev", "Contracts", "CORE.md"),
    Page("dev-step-types", "Step types", "dev", "Contracts", "contracts/STEP_TYPES.md"),
    Page("dev-recipe", "Recipe", "dev", "Contracts", "contracts/RECIPE.md"),
    Page("dev-runs", "Runs", "dev", "Contracts", "contracts/runs.md"),
    Page("dev-report", "Logs", "dev", "Contracts", "contracts/LOGS.md"),
    Page("dev-auth", "Auth & permissions", "dev", "Contracts", "contracts/auth.md"),
    Page("dev-health-check", "Health checks", "dev", "Contracts", "contracts/HEALTH_CHECK.md"),
    Page("dev-mes", "MES", "dev", "Contracts", "contracts/MES.md"),
    Page("dev-portal", "User Portal", "dev", "Contracts", "contracts/PORTAL.md"),
    Page("dev-config", "Config", "dev", "Contracts", "contracts/CONFIG.md"),
    Page("dev-instrument-library-contract", "Instrument library contract", "dev", "Contracts", "INSTRUMENT_LIBRARY.md"),
    Page("dev-report-store", "Report DB store", "dev", "Contracts", "REPORT_STORE.md"),
    Page("dev-frontend", "Frontend", "dev", "Contracts", "FRONTEND.md"),
    Page("dev-labview-bridge", "LabVIEW bridge", "dev", "Bus & LabVIEW", "LABVIEW_BRIDGE.md"),
    Page("dev-mqtt-messages", "MQTT message reference", "dev", "Bus & LabVIEW", "MQTT_MESSAGES.md"),
    Page("dev-diag-emit", "LabVIEW diag-emit", "dev", "Bus & LabVIEW", "LABVIEW_DIAG_EMIT.md"),
    Page("dev-debug-server", "Debug Server", "dev", "Bus & LabVIEW", "DEBUG_SERVER.md"),
]

_BY_ID = {p.id: p for p in PAGES}


# ---------------------------------------------------------------------------------------------
# App-owned pages: app/<name>/portal/*.md  (TEMPLATE.md §1 — an app documents ITS bench without
# touching framework docs). Optional front matter: title, section, order, route.
# ---------------------------------------------------------------------------------------------

def _front_matter(text: str) -> tuple[dict, str]:
    """Split a leading `---` block of `key: value` lines from the markdown body."""
    text = text.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end < 0:
        return {}, text
    meta = {}
    for line in text[4:end].split("\n"):
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip().lower()] = v.strip()
    return meta, text[end + 4:].lstrip("\n")


def app_pages() -> list[Page]:
    """Discovered fresh on each call (a handful of small files) so a page dropped into the app payload
    shows up without a restart. Always audience `user` — it ships in a built station."""
    found: list[tuple[int, str, Page]] = []
    for portal in app_portal_dirs():
        app_name = portal.parent.name
        for f in sorted(portal.glob("*.md")):
            meta, _ = _front_matter(f.read_text(encoding="utf-8"))
            try:
                order = int(meta.get("order", 100))
            except ValueError:
                order = 100
            title = meta.get("title") or f.stem
            found.append((order, title.lower(), Page(
                f"app-{app_name}-{f.stem}", title, "user", meta.get("section") or APP_SECTION,
                str(f.resolve()), meta.get("route") or None, str(portal))))
    return [p for _, _, p in sorted(found, key=lambda t: (t[0], t[1]))]


def all_pages() -> list[Page]:
    return PAGES + app_pages()


def get(page_id: str) -> Page | None:
    return _BY_ID.get(page_id) or next((p for p in app_pages() if p.id == page_id), None)


def resolve(page: Page) -> Path | None:
    """Resolve a page's file, guarding against traversal: framework pages must sit under DOCS_ROOT,
    app pages under their own app/<name>/portal directory."""
    if page.app_root:
        base = Path(page.app_root).resolve()
        path = Path(page.file).resolve()
    else:
        base = DOCS_ROOT.resolve()
        path = (DOCS_ROOT / page.file).resolve()
    if base not in path.parents:
        return None
    return path if path.is_file() else None


def read(page: Page) -> str | None:
    path = resolve(page)
    if path is None:
        return None
    text = path.read_text(encoding="utf-8")
    return _front_matter(text)[1] if page.app_root else text


_IMG_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".webp": "image/webp", ".svg": "image/svg+xml"}


def get_app_asset(name: str) -> tuple[bytes, str] | None:
    """An image under app/<name>/portal/img/ (`![x](asset:app/<name>)` in an app page). Extension
    whitelist + traversal guard; the first app that has the file wins."""
    for portal in app_portal_dirs():
        root = (portal / "img").resolve()
        path = (root / name).resolve()
        if root in path.parents and path.suffix.lower() in _IMG_EXT and path.is_file():
            return path.read_bytes(), _IMG_EXT[path.suffix.lower()]
    return None


# ---------------------------------------------------------------------------------------------
# Shared asset library (screenshots + diagrams) and generated facts
# ---------------------------------------------------------------------------------------------

ASSET_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
              ".webp": "image/webp", ".svg": "image/svg+xml"}


def dev_visible(include_dev: bool) -> bool:
    """Developer content is visible only to a HELP.DEV caller on a NON-frozen (source) install."""
    return include_dev and not is_frozen()


def source_hash(path: Path) -> str:
    """Stable content hash of a source file (line endings normalised so Windows/Linux agree)."""
    import hashlib
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()[:16]


def _manifest() -> list[dict]:
    import json
    f = DOCS_ROOT / "assets" / "manifest.json"
    if not f.is_file():
        return []
    try:
        return list(json.loads(f.read_text(encoding="utf-8")).get("images", []))
    except (OSError, ValueError):
        return []


def _asset_file(entry: dict) -> Path | None:
    """The image file for a manifest entry, only if it sits INSIDE docs/assets with an image
    extension — a manifest can never be used to read an arbitrary file."""
    root = (DOCS_ROOT / "assets").resolve()
    path = (root / str(entry.get("file", ""))).resolve()
    if root not in path.parents or path.suffix.lower() not in ASSET_MIME or not path.is_file():
        return None
    return path


def _entry_visible(entry: dict, include_dev: bool) -> bool:
    return entry.get("audience", "both") != "dev" or dev_visible(include_dev)


def asset_entries(include_dev: bool) -> list[dict]:
    return [e for e in _manifest() if _entry_visible(e, include_dev) and _asset_file(e) is not None]


def get_asset(asset_id: str, include_dev: bool) -> tuple[bytes, str] | None:
    for e in asset_entries(include_dev):
        if e.get("id") == asset_id:
            path = _asset_file(e)
            return path.read_bytes(), ASSET_MIME[path.suffix.lower()]
    return None


def asset_info(entry: dict) -> dict:
    """Public description of an image: enough for the UI to caption it and warn when the screen it
    shows has changed since capture (only computable in a source checkout — frozen has no sources)."""
    stale = False
    src, want = entry.get("source"), entry.get("source_hash")
    if src and want:
        f = DOCS_ROOT.parent / src
        if f.is_file():
            stale = source_hash(f) != want
    return {"id": entry.get("id"), "alt": entry.get("alt", ""), "audience": entry.get("audience", "both"),
            "framework_version": entry.get("framework_version"), "route": entry.get("route"),
            "stale": stale}


def facts() -> dict | None:
    """docs/generated/facts.json (built by tools/gen_devguide.py). Dev-only, source-only."""
    import json
    f = DOCS_ROOT / "generated" / "facts.json"
    if not f.is_file():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
