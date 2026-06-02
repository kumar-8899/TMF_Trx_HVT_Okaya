"""Module/variant registry + autodiscovery (CORE.md §2.1).

The driver-registry pattern, generalised. Decorators self-register modules and
their variants. Duplicate ids fail loudly; unknown ids raise, never return null.
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass, field
from typing import Any


class RegistryError(Exception):
    """Duplicate registration or lookup of an unknown id."""


@dataclass
class ModuleRecord:
    module_id: str
    contract: Any
    contract_version: int
    display_name: str
    cls: type
    variants: dict[str, type] = field(default_factory=dict)

    @property
    def contract_id(self) -> str:
        # One module provides one contract, identified by its id (CORE.md §6.3).
        return self.module_id

    @property
    def variant_ids(self) -> list[str]:
        return list(self.variants)


class Registry:
    def __init__(self) -> None:
        self._modules: dict[str, ModuleRecord] = {}

    def register_module(
        self,
        module_id: str,
        contract: Any,
        contract_version: int = 1,
        display_name: str = "",
    ):
        def deco(cls: type) -> type:
            if module_id in self._modules:
                raise RegistryError(f"module '{module_id}' already registered")
            self._modules[module_id] = ModuleRecord(
                module_id=module_id,
                contract=contract,
                contract_version=contract_version,
                display_name=display_name or module_id,
                cls=cls,
            )
            return cls

        return deco

    def register_variant(self, module_id: str, variant_id: str, display_name: str = ""):
        def deco(cls: type) -> type:
            rec = self._modules.get(module_id)
            if rec is None:
                raise RegistryError(
                    f"variant '{variant_id}' registered before module '{module_id}'"
                )
            if variant_id in rec.variants:
                raise RegistryError(f"duplicate variant ({module_id}, {variant_id})")
            rec.variants[variant_id] = cls
            return cls

        return deco

    def get(self, module_id: str) -> ModuleRecord:
        rec = self._modules.get(module_id)
        if rec is None:
            raise RegistryError(f"unknown module '{module_id}'")
        return rec

    def variant(self, module_id: str, variant_id: str) -> type:
        rec = self.get(module_id)
        cls = rec.variants.get(variant_id)
        if cls is None:
            raise RegistryError(f"unknown variant ({module_id}, {variant_id})")
        return cls

    def all(self) -> dict[str, ModuleRecord]:
        return dict(self._modules)

    def clear(self) -> None:
        self._modules.clear()


# Default registry the autodiscovery decorators populate.
default_registry = Registry()


def register_module(module_id: str, contract: Any, contract_version: int = 1, display_name: str = ""):
    return default_registry.register_module(module_id, contract, contract_version, display_name)


def register_variant(module_id: str, variant_id: str, display_name: str = ""):
    return default_registry.register_variant(module_id, variant_id, display_name)


def discover(packages: tuple[str, ...] = ("modules",)) -> list[str]:
    """Import every sub-package so the @register decorators fire (CORE.md §2.1)."""
    imported: list[str] = []
    for pkg_name in packages:
        try:
            pkg = importlib.import_module(pkg_name)
        except ModuleNotFoundError:
            continue
        for info in pkgutil.iter_modules(pkg.__path__):
            importlib.import_module(f"{pkg_name}.{info.name}")
            imported.append(f"{pkg_name}.{info.name}")
    return imported
