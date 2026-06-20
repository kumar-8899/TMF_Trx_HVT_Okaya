"""MES provider factory — selects the transport from config (RECIPE/auth-style seam)."""

from __future__ import annotations

from modules.mes.providers.folder import FolderProvider


class ProviderError(Exception):
    """Unknown or not-yet-implemented MES provider."""


def make_provider(kind: str, config: dict, on_missing: str = "block"):
    if kind == "folder":
        return FolderProvider(config.get("folder", {}), on_missing=on_missing)
    if kind in ("database", "xml"):
        raise ProviderError(f"MES provider '{kind}' is not implemented yet (phase 2)")
    raise ProviderError(f"unknown MES provider '{kind}'")
