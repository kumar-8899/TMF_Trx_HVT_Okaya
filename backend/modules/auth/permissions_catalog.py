"""Permission catalog — the granular action list the roles UI renders (auth.md).

The single source of the concrete `DOMAIN.ACTION` permissions in the system, with
human labels + the business action each gates. Roles hold a subset (or a
`DOMAIN.*` wildcard); the matrix UI toggles these concrete keys. Keep in sync as
modules add gated routes.
"""

from __future__ import annotations

# (key, domain, label, description) — display order within a domain is list order.
_CATALOG: list[tuple[str, str, str, str]] = [
    ("AUTH.MANAGE_USERS",   "Auth",        "Manage users",        "Create/edit users, roles, lock, reset passwords."),
    ("AUTH.MANAGE_ROLES",   "Auth",        "Manage permissions",  "Edit the role → permission matrix (super_admin)."),
    ("TEST.RUN",            "Testing",     "Run tests",           "Start/abort runs from the test bench."),
    ("RECIPE.VIEW",         "Recipe",      "View recipes",        "Browse recipes + versions."),
    ("RECIPE.EDIT",         "Recipe",      "Edit recipes",        "Create/edit/duplicate/deprecate recipes."),
    ("REPORT.VIEW",         "Report",      "View reports",        "Open run reports + analytics."),
    ("REPORT.EXPORT",       "Report",      "Export reports",      "Export report data."),
    ("HEALTH.VIEW",         "Health",      "View health",         "Read checks, runs, trends, known issues."),
    ("HEALTH.RUN",          "Health",      "Run health checks",   "Run non-disruptive checks + schedule."),
    ("HEALTH.MAINTENANCE",  "Health",      "Maintenance mode",    "Disruptive checks + enter/exit maintenance."),
    ("MAINTENANCE.CALIBRATE", "Maintenance", "Calibrate",         "Calibration actions."),
    ("CONFIG.VIEW",         "Config",      "View config",         "Read instruments/transports, test connection."),
    ("CONFIG.EDIT",         "Config",      "Edit config",         "Create/update/delete instruments + config."),
    ("DIAGNOSTICS.VIEW",    "Diagnostics", "View diagnostics",    "Live event tail + logs + readiness."),
    ("DIAGNOSTICS.PURGE",   "Diagnostics", "Purge logs",          "Delete action/error log records older than a cutoff (Logs page)."),
    ("HELP.VIEW",           "Help",        "View user docs",      "Open the in-app user documentation."),
    ("HELP.DEV",            "Help",        "View developer docs", "Open the developer documentation (super_admin)."),
    ("SYSTEM.RESET_DATA",   "System",      "Reset data",          "Purge runs/reports/logs/recipes/users (super_admin)."),
    ("SYSTEM.SETTINGS",     "System",      "Station settings",    "MES + station settings (super_admin)."),
]

PERMISSIONS: list[dict] = [
    {"key": k, "domain": d, "label": l, "description": desc} for (k, d, l, desc) in _CATALOG
]
KEYS: frozenset[str] = frozenset(p["key"] for p in PERMISSIONS)
