"""Where things live, in a source checkout AND in a frozen (PyInstaller) build.

Why this exists (FRAMEWORK CR B5): `Path(__file__).parents[N]` is the idiom for "the repo root", and it is
right from source - but in a PyInstaller exe `__file__` is a virtual path inside the archive, so the same
expression lands one folder ABOVE the install and a map / config / driver tree silently loads as empty
(a warning at best). Framework modules and app modules must resolve locations through these helpers
instead of counting parents.

  bundle_root()   READ-ONLY shipped payload - the folder that holds `app/<name>/`, `instrument_libs/`,
                  `docs/`, `controller/`: frozen = `run.dist` (the swap unit), source = the repo root.
                  Overridable with `TMF_BUNDLE_DIR`.
  state_root()    MUTABLE state that survives an update swap - `config/`, `data/`: frozen = the external deploy
                  root (`TMF_STATE_DIR`), source = `backend/`.
  bundle_path()   `bundle_root() / rel`, for app-owned files shipped in the payload (e.g. a variable map).
  load_failed()   report a map / config that failed to load as an `error` (Health sees errors, not warnings).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_SOURCE_ROOT = Path(__file__).resolve().parents[2]      # backend/core/paths.py -> repo root (source only)


def is_frozen() -> bool:
    """True in a packaged build. PyInstaller sets `sys.frozen`; Nuitka injects `__compiled__` instead."""
    return bool(getattr(sys, "frozen", False)) or "__compiled__" in globals()


def bundle_root() -> Path:
    env = os.environ.get("TMF_BUNDLE_DIR")
    if env:
        return Path(env)
    return Path(sys.executable).resolve().parent if is_frozen() else _SOURCE_ROOT


def state_root() -> Path:
    from core.services.config import state_root as _state_root
    return _state_root()


def bundle_path(rel: str | Path) -> Path:
    p = Path(rel)
    return p if p.is_absolute() else bundle_root() / p


def load_failed(diag, subsystem: str, what: str, path: Path | str, exc: BaseException | None = None,
                **ctx) -> None:
    """A shipped map / config that could not be loaded is a FAULT, not a warning: the feature it
    feeds would run empty and look healthy. Logged at `error` with the path that was tried and
    whether it exists, so the frozen-vs-source path mistake is obvious from the log line."""
    p = Path(path)
    diag.error(subsystem, f"{what} failed to load",
               path=str(p), exists=p.exists(), frozen=is_frozen(), bundle_root=str(bundle_root()),
               error=f"{type(exc).__name__}: {exc}" if exc else None, **ctx)
