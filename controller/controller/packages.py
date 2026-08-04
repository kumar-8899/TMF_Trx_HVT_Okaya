"""App step-type packages (PYTHON_CONTROLLER.md §7.5, §16 C10).

A station runs the framework's 8 core step types PLUS **one** application package
(`inverter_eol_steps`, `motor_tester_steps`, …). Each is a separate versioned repo, CI-gated,
bundled at build — the same tracked path as instrument libraries, NOT a runtime plugin
drop-in. Loading is import-by-name: importing the package fires its `@register_step_type`
decorators into the one shared registry, so a new customer test ships without a framework
release (the C10 proof).

`validate_app_step_types` is the CI gate: every application step type must pass handler
conformance (§7.3) and declare a schema. CI runs it over a package before it is allowed to
ship; the controller also runs it at load and warns loudly on any violation."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

from controller import conformance
from controller.registry import STEP_REGISTRY


def load_step_type_packages(paths: list[str], packages: list[str], *, log=None) -> None:
    """Add package repos to sys.path (dev) and import each so its step types register.
    A bad package must not crash the controller — it is logged and skipped (the CI gate is
    where a broken package is meant to be caught, not the station)."""
    for p in paths or []:
        if Path(p).is_dir() and p not in sys.path:
            sys.path.insert(0, p)
    for pkg in packages or []:
        try:
            importlib.import_module(pkg)
            if log:
                log("info", f"step-type package loaded: {pkg}")
        except Exception as exc:  # noqa: BLE001 — a bad package must not stop the controller
            if log:
                log("error", f"step-type package import failed: {pkg}: {exc}")


def validate_app_step_types() -> list[str]:
    """The CI gate over application step types (core primitives are exempt — they are the
    framework's own, checked by the controller's suite). Each application step type must:
      - pass the §7.3 handler conformance rules, and
      - declare a schema (`schema_path`) so its recipe form validates.
    Returns a flat list of violations, empty == the gate passes."""
    errors: list[str] = []
    for st in sorted(STEP_REGISTRY.values(), key=lambda t: t.type_id):
        if st.kind != "application":
            continue
        for v in conformance.check_handler(st.handler_cls):
            errors.append(f"{st.type_id}: {v}")
        if not st.schema_path:
            errors.append(f"{st.type_id}: no schema_path — a step type ships its recipe schema (§7.6)")
    return errors
