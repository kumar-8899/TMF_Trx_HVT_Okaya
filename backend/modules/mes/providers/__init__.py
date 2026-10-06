"""MES provider factory — selects the transport from config (RECIPE/auth-style seam)."""

from __future__ import annotations

from modules.mes.providers.folder import FolderProvider


class ProviderError(Exception):
    """Unknown or not-yet-implemented MES provider."""


def make_provider(kind: str, config: dict, on_missing: str = "block", on_error: str = "block",
                  db_config: dict | None = None):
    if kind == "folder":
        return FolderProvider(config.get("folder", {}), on_missing=on_missing)
    if kind == "database":
        from modules.mes.providers.database import DatabaseProvider
        return DatabaseProvider(db_config if db_config is not None else config.get("database", {}),
                                on_missing=on_missing, on_error=on_error)
    if kind == "xml":
        raise ProviderError(f"MES provider '{kind}' is not implemented yet")
    raise ProviderError(f"unknown MES provider '{kind}'")
