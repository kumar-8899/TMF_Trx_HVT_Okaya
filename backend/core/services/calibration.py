"""Calibration overlay (docs/contracts/CALIBRATION.md).

A calibration is a per-station *overlay* on the variable map's static `scale`: the shipped map
(`app/<slug>/maps/<station>.json`) is never edited; an operator-captured `{gain, offset}` per
signal lives in the state dir and is baked into an *effective* map that the controller reads.
Pure functions + small atomic file helpers; no imports from other framework services so the
supervisor, the variables module and the tests all share ONE implementation."""

from __future__ import annotations

import copy
import json
import os
import time
from pathlib import Path

SCHEMA_VERSION = 1
INDEX_NAME = "index.json"


class CalibrationError(Exception):
    """A calibration that cannot be fitted or stored (bad points, degenerate span, bad file)."""


# -- overlay application (precedence: overlay > map scale) -----------------------------------

def _finite(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and abs(v) != float("inf") else None


def overlay_calibration(signals: dict, overlay: dict | None) -> dict:
    """Return a NEW signals dict with the overlay's gain/offset replacing each matching signal's
    `scale`. Unknown signals, entries missing a finite gain or offset, and extra keys are ignored;
    the input is never mutated. A gain of 0 is rejected (the inverse scale would divide by it)."""
    out = copy.deepcopy(signals or {})
    for name, cal in ((overlay or {}).get("signals") or {}).items():
        sig = out.get(name)
        if sig is None or not isinstance(cal, dict):
            continue
        gain, offset = _finite(cal.get("gain")), _finite(cal.get("offset"))
        if gain is None or offset is None or gain == 0:
            continue
        sig["scale"] = {"gain": gain, "offset": offset}
        sig["calibrated"] = True
    return out


def apply_to_map(vmap: dict, overlay: dict | None) -> dict:
    """`overlay_calibration` for a whole controller map (`{signals, actions, ...}`)."""
    out = copy.deepcopy(vmap or {})
    out["signals"] = overlay_calibration(out.get("signals") or {}, overlay)
    return out


# -- fitting ----------------------------------------------------------------------------------

def fit_linear(points: list[dict]) -> dict:
    """Least-squares `reference = gain * raw + offset` over `[{raw, reference}]` (>= 2 points,
    >= 2 distinct raw values). Returns `{gain, offset, n, max_error}`; `max_error` is the largest
    absolute residual in the reference's unit so the UI can show the fit quality before applying."""
    pts = []
    for p in points or []:
        r, t = _finite((p or {}).get("raw")), _finite((p or {}).get("reference"))
        if r is None or t is None:
            raise CalibrationError("every calibration point needs a finite 'raw' and 'reference'")
        pts.append((r, t))
    if len(pts) < 2:
        raise CalibrationError("at least 2 calibration points are required")
    n = len(pts)
    mx = sum(r for r, _ in pts) / n
    my = sum(t for _, t in pts) / n
    sxx = sum((r - mx) ** 2 for r, _ in pts)
    if sxx == 0:
        raise CalibrationError("calibration points must cover at least 2 distinct raw values")
    gain = sum((r - mx) * (t - my) for r, t in pts) / sxx
    if gain == 0:
        raise CalibrationError("fitted gain is 0 — the reference did not change with the raw value")
    offset = my - gain * mx
    return {"gain": gain, "offset": offset, "n": n,
            "max_error": max(abs(gain * r + offset - t) for r, t in pts)}


# -- overlay file I/O -------------------------------------------------------------------------

def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def read_overlay(path: Path) -> dict:
    """The overlay at `path`; an absent file is a fresh bench (empty overlay). A present-but-bad
    file raises `CalibrationError` so the caller can degrade LOUDLY instead of silently
    uncalibrating a station."""
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "signals": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise CalibrationError(f"calibration overlay unreadable ({path}): {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("signals", {}), dict):
        raise CalibrationError(f"calibration overlay malformed ({path}): expected {{signals:{{...}}}}")
    data.setdefault("schema_version", SCHEMA_VERSION)
    data.setdefault("signals", {})
    return data


def write_overlay(path: Path, overlay: dict) -> None:
    overlay = dict(overlay)
    overlay["schema_version"] = SCHEMA_VERSION
    _atomic_write(path, overlay)


def set_signal(overlay: dict, name: str, fit: dict, *, points: list[dict], by: str | None) -> dict:
    """Record a fitted calibration for one signal (keeps the capture points for audit)."""
    out = {"schema_version": SCHEMA_VERSION, "signals": dict(overlay.get("signals") or {})}
    out["signals"][name] = {"gain": fit["gain"], "offset": fit["offset"], "n": fit["n"],
                            "max_error": fit["max_error"], "points": points,
                            "updated_ts": time.time(), "by": by}
    return out


def clear_signal(overlay: dict, name: str) -> dict:
    out = {"schema_version": SCHEMA_VERSION, "signals": dict(overlay.get("signals") or {})}
    out["signals"].pop(name, None)
    return out


# -- effective-map baking (supervisor + variables module) -------------------------------------

def calibration_dir(data_dir: Path) -> Path:
    return Path(data_dir) / "calibration"


def overlay_path(data_dir: Path, station: str) -> Path:
    return calibration_dir(data_dir) / f"{station}.json"


def maps_dir(data_dir: Path) -> Path:
    return Path(data_dir) / "controller.maps"


def effective_path(data_dir: Path, station: str) -> Path:
    return maps_dir(data_dir) / f"{station}.json"


def bake_effective_map(shipped: Path, overlay_file: Path, out: Path, *, log=None) -> dict:
    """Write `out` = shipped map + overlay; return `{signals_calibrated, degraded}`.

    Degrades LOUDLY, never silently: a bad overlay logs an error and the *shipped* map is baked
    unchanged (station keeps running on its factory scale). A missing/bad shipped map raises —
    there is nothing to fall back to."""
    log = log or (lambda level, msg, **f: None)
    base = json.loads(shipped.read_text(encoding="utf-8"))
    degraded = False
    try:
        overlay = read_overlay(overlay_file)
    except CalibrationError as exc:
        log("error", "calibration overlay ignored — running on the shipped map scale",
            error=str(exc), overlay=str(overlay_file))
        overlay, degraded = {"signals": {}}, True
    eff = apply_to_map(base, overlay)
    _atomic_write(out, eff)
    n = sum(1 for s in (eff.get("signals") or {}).values() if s.get("calibrated"))
    return {"signals_calibrated": n, "degraded": degraded}


def read_index(data_dir: Path) -> dict:
    """`{station: {shipped, effective, overlay}}` written by the supervisor — the file contract
    the variables module uses to find the maps without depending on the supervisor."""
    p = maps_dir(data_dir) / INDEX_NAME
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("stations", {}) or {}
    except Exception:  # noqa: BLE001
        return {}


def write_index(data_dir: Path, stations: dict) -> None:
    _atomic_write(maps_dir(data_dir) / INDEX_NAME, {"schema_version": SCHEMA_VERSION,
                                                      "stations": stations})
