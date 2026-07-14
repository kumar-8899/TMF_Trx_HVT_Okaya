"""Help content catalog — the whitelist of doc pages the help module serves.

Two audiences: `user` (all signed-in users) and `dev` (super_admin only). Pages
map to markdown files under the repo `docs/` tree. Serving is **whitelist-only**
(id -> known file) so there is no arbitrary file read / path traversal. Dev pages
surface the existing design docs as-is; user pages + a few dev guides are authored
under docs/help/.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# repo_root/docs  (catalog.py = backend/modules/help/catalog.py)
DOCS_ROOT = Path(__file__).resolve().parents[3] / "docs"


@dataclass(frozen=True)
class Page:
    id: str
    title: str
    audience: str          # "user" | "dev"
    section: str           # sidebar grouping
    file: str              # path relative to DOCS_ROOT
    route: str | None = None   # app route this page documents (context-aware help)


PAGES: list[Page] = [
    # ---------- USER ----------
    Page("user-getting-started", "Getting started", "user", "Getting started", "help/user/getting-started.md", "/"),
    Page("user-dashboard", "Dashboard", "user", "Getting started", "help/user/dashboard.md", "/"),
    Page("user-test-bench", "Test Bench", "user", "Operations", "help/user/test-bench.md", "/runs"),
    Page("user-recipes", "Recipes", "user", "Operations", "help/user/recipes.md", "/recipes"),
    Page("user-reports", "Reports", "user", "Operations", "help/user/reports.md", "/reports"),
    Page("user-analytics", "Analytics", "user", "Operations", "help/user/analytics.md", "/analytics"),
    Page("user-daq", "DAQ", "user", "Operations", "help/user/daq.md", "/daq"),
    Page("user-health", "Production Readiness", "user", "Health & maintenance", "help/user/health.md", "/health"),
    Page("user-maintenance", "Maintenance Console", "user", "Health & maintenance", "help/user/maintenance.md", "/maintenance"),
    Page("user-instrument-test", "Instrument Test Bench", "user", "Health & maintenance", "help/user/instrument-test.md", "/instruments/test"),
    Page("user-instruments", "Instruments", "user", "Configuration", "help/user/instruments.md", "/config/instruments"),
    Page("user-shift", "Shifts", "user", "Configuration", "help/user/shift.md", "/config/shift"),
    Page("user-mes", "MES interlock", "user", "Configuration", "help/user/mes.md", "/config/mes"),
    Page("user-users", "Users", "user", "Administration", "help/user/users.md", "/users"),
    Page("user-permissions", "Permissions", "user", "Administration", "help/user/permissions.md", "/permissions"),
    Page("user-settings", "Settings", "user", "Administration", "help/user/settings.md", "/settings"),
    Page("user-troubleshooting", "Troubleshooting", "user", "Help", "help/user/troubleshooting.md"),
    Page("user-glossary", "Glossary", "user", "Help", "help/user/glossary.md"),

    # ---------- DEV (super_admin) ----------
    Page("dev-principles", "Principles", "dev", "Overview", "PRINCIPLES.md"),
    Page("dev-architecture", "Architecture", "dev", "Overview", "ARCHITECTURE.md"),
    Page("dev-template", "Application template", "dev", "Overview", "TEMPLATE.md"),
    Page("dev-app-repo", "Building an app repo", "dev", "Overview", "APP_REPO.md"),
    Page("dev-module-framework", "Module framework", "dev", "Overview", "help/dev/module-framework.md"),
    Page("dev-core-services", "Core services", "dev", "Overview", "help/dev/core-services.md"),
    Page("dev-extending", "Extension how-tos", "dev", "Overview", "help/dev/extending.md"),
    Page("dev-workflow", "Dev workflow", "dev", "Overview", "help/dev/workflow.md"),
    Page("dev-instrument-library", "Instrument library", "dev", "Overview", "help/dev/instrument-library.md"),
    Page("dev-core", "CORE contract", "dev", "Contracts", "CORE.md"),
    Page("dev-step-types", "Step types", "dev", "Contracts", "contracts/STEP_TYPES.md"),
    Page("dev-recipe", "Recipe", "dev", "Contracts", "contracts/RECIPE.md"),
    Page("dev-runs", "Runs", "dev", "Contracts", "contracts/runs.md"),
    Page("dev-daq", "DAQ", "dev", "Contracts", "contracts/daq.md"),
    Page("dev-report", "Logs", "dev", "Contracts", "contracts/LOGS.md"),
    Page("dev-auth", "Auth & permissions", "dev", "Contracts", "contracts/auth.md"),
    Page("dev-health-check", "Health checks", "dev", "Contracts", "contracts/HEALTH_CHECK.md"),
    Page("dev-mes", "MES", "dev", "Contracts", "contracts/MES.md"),
    Page("dev-config", "Config", "dev", "Contracts", "contracts/CONFIG.md"),
    Page("dev-instrument-library-contract", "Instrument library contract", "dev", "Contracts", "INSTRUMENT_LIBRARY.md"),
    Page("dev-frontend", "Frontend", "dev", "Frontend", "FRONTEND.md"),
    Page("dev-labview-bridge", "LabVIEW bridge", "dev", "Bus & LabVIEW", "LABVIEW_BRIDGE.md"),
    Page("dev-mqtt-messages", "MQTT message reference", "dev", "Bus & LabVIEW", "MQTT_MESSAGES.md"),
    Page("dev-diag-emit", "LabVIEW diag-emit", "dev", "Bus & LabVIEW", "LABVIEW_DIAG_EMIT.md"),
    Page("dev-debug-server", "Debug Server", "dev", "Bus & LabVIEW", "DEBUG_SERVER.md"),
    Page("dev-report-store", "Report DB store", "dev", "Contracts", "REPORT_STORE.md"),
    Page("dev-secure-distribution", "Secure distribution", "dev", "Overview", "SECURE_DISTRIBUTION.md"),
    Page("dev-release-howto", "Cutting a release", "dev", "Overview", "RELEASE_HOWTO.md"),
]

_BY_ID = {p.id: p for p in PAGES}


def get(page_id: str) -> Page | None:
    return _BY_ID.get(page_id)


def resolve(page: Page) -> Path | None:
    """Resolve a page's file under DOCS_ROOT, guarding against traversal."""
    path = (DOCS_ROOT / page.file).resolve()
    if DOCS_ROOT.resolve() not in path.parents:
        return None
    return path if path.is_file() else None


def read(page: Page) -> str | None:
    path = resolve(page)
    if path is None:
        return None
    return path.read_text(encoding="utf-8")
