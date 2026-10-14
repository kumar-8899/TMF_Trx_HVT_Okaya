"""Calibration service for the variables module (docs/contracts/CALIBRATION.md).

Composes the pure helpers in `core.services.calibration` with the module's engine and the
bridge: list calibratable signals, capture a raw reading, drive an analog output by raw value,
fit + persist an overlay, and hot-reload it into BOTH read paths (the backend engine and — via
the `calibration.reload` bridge op — the supervised Python controller). No relaunch."""

from __future__ import annotations

import json
from pathlib import Path

from core.services import calibration as cal


class CalibrationUnavailable(Exception):
    """The operation cannot run now (controller busy / bridge offline). The overlay is already
    saved when this is raised from `apply`, and takes effect on the next controller start."""


class CalibrationService:
    def __init__(self, module, data_dir: Path | None = None) -> None:
        self._m = module
        self._data_dir = Path(data_dir) if data_dir else None

    # -- plumbing ----------------------------------------------------------------------------

    @property
    def data_dir(self) -> Path:
        if self._data_dir is None:
            from core.app import DEFAULT_DB_PATH       # lazy: core.app imports modules
            self._data_dir = DEFAULT_DB_PATH.parent
        return self._data_dir

    def _station(self, station: str | None) -> str:
        return self._m._resolve_station(station)

    def _overlay_file(self, st: str) -> Path:
        return cal.overlay_path(self.data_dir, st)

    def _shipped(self, st: str) -> dict | None:
        """The shipped controller map's signals for `st` (python controller), else None."""
        idx = cal.read_index(self.data_dir).get(st)
        if not idx:
            return None
        try:
            return json.loads(Path(idx["shipped"]).read_text(encoding="utf-8")).get("signals") or {}
        except Exception:  # noqa: BLE001 — listing degrades to the engine map
            return None

    def _base_signals(self, st: str) -> dict:
        """Factory signals: the shipped map (python controller) over the backend engine map."""
        base = dict(self._m.engine.map_for(st))
        base.update(self._shipped(st) or {})
        return base

    def load_overlays(self) -> None:
        """Start-up: hand each station's overlay to the engine. A bad file is a loud error and the
        station runs on its factory scale — never silently uncalibrated AND unreported."""
        for st in self._m._stations:
            try:
                self._m.engine.set_overlay(st, cal.read_overlay(self._overlay_file(st)))
            except cal.CalibrationError as exc:
                self._m.core.diag.error("variables", "calibration overlay ignored — factory scale "
                                        "in use", station=st, error=str(exc))
                self._m.engine.set_overlay(st, {})

    # -- queries -----------------------------------------------------------------------------

    def list_signals(self, station: str | None) -> list[dict]:
        st = self._station(station)
        overlay = cal.read_overlay(self._overlay_file(st)) if self._overlay_file(st).exists() else {}
        out = []
        for name, v in sorted(self._base_signals(st).items()):
            if v.get("calibratable") is False or not (v.get("read") or v.get("write")):
                continue
            ov = (overlay.get("signals") or {}).get(name)
            out.append({
                "name": name, "station": st, "units": v.get("units"),
                "readable": bool(v.get("read")), "writable": bool(v.get("write")),
                "factory": {"gain": float((v.get("scale") or {}).get("gain", 1.0)),
                            "offset": float((v.get("scale") or {}).get("offset", 0.0))},
                "calibration": ov,
            })
        return out

    def _factory_scale(self, st: str, name: str) -> tuple[float, float]:
        v = self._base_signals(st).get(name)
        if v is None:
            raise KeyError(name)
        s = v.get("scale") or {}
        return float(s.get("gain", 1.0)), float(s.get("offset", 0.0))

    def _current_scale(self, st: str, name: str) -> tuple[float, float]:
        ov = (cal.read_overlay(self._overlay_file(st)).get("signals") or {}).get(name)
        if ov:
            eff = cal.overlay_calibration({name: {"scale": {}}}, {"signals": {name: ov}})[name]
            if eff.get("calibrated"):
                return eff["scale"]["gain"], eff["scale"]["offset"]
        return self._factory_scale(st, name)

    # -- hardware ---------------------------------------------------------------------------

    async def _request(self, op: str, args: dict, st: str) -> dict:
        bridge = self._m.core.bridge
        if bridge is None:
            raise CalibrationUnavailable("bridge not connected")
        try:
            return await bridge.request(op, args, station=st)
        except Exception as exc:  # noqa: BLE001
            raise CalibrationUnavailable(f"{op} failed: {exc}") from exc

    async def read_raw(self, name: str, station: str | None) -> dict:
        """Current UNSCALED reading of an analog input (what a reference meter is compared to)."""
        st = self._station(station)
        if self._m.core.controller_kind == "python":
            r = await self._request("variable.read", {"name": name}, st)
            if not r.get("ok", True) or "result" not in r:
                raise CalibrationUnavailable(str((r.get("error") or {}).get("message", r)))
            res = r["result"]
        else:
            res = await self._m.engine.read(name, st)
        return {"name": name, "station": st, "raw": res["raw"], "scaled": res["value"],
                "units": res.get("units")}

    async def drive_raw(self, name: str, raw: float, station: str | None) -> dict:
        """Command an analog output so the instrument receives exactly `raw` (the engineering
        value is derived through the CURRENT scale), for comparing against a reference meter."""
        st = self._station(station)
        gain, offset = self._current_scale(st, name)
        value = raw * gain + offset
        if self._m.core.controller_kind == "python":
            r = await self._request("variable.write", {"name": name, "value": value}, st)
            if not r.get("ok", True):
                raise CalibrationUnavailable(str((r.get("error") or {}).get("message", r)))
        else:
            await self._m.engine.write(name, value, st)
        return {"name": name, "station": st, "raw": raw, "commanded": value}

    # -- apply / reset ----------------------------------------------------------------------

    async def apply(self, name: str, points: list[dict], station: str | None, by: str | None) -> dict:
        st = self._station(station)
        self._factory_scale(st, name)                        # unknown signal -> KeyError
        fit = cal.fit_linear(points)
        ovp = self._overlay_file(st)
        overlay = cal.set_signal(cal.read_overlay(ovp), name, fit, points=points, by=by)
        cal.write_overlay(ovp, overlay)
        self._m.core.diag.info("variables", "calibration applied", station=st, signal=name,
                               gain=fit["gain"], offset=fit["offset"], n=fit["n"],
                               max_error=fit["max_error"], by=by)
        return await self._propagate(st, overlay, {"signal": name, **fit})

    async def reset(self, name: str, station: str | None, by: str | None) -> dict:
        st = self._station(station)
        ovp = self._overlay_file(st)
        overlay = cal.clear_signal(cal.read_overlay(ovp), name)
        cal.write_overlay(ovp, overlay)
        self._m.core.diag.info("variables", "calibration reset", station=st, signal=name, by=by)
        return await self._propagate(st, overlay, {"signal": name, "reset": True})

    async def _propagate(self, st: str, overlay: dict, result: dict) -> dict:
        self._m.engine.set_overlay(st, overlay)              # backend read path: immediate
        result["controller"] = "not-applicable"
        if self._m.core.controller_kind != "python":
            return result
        idx = cal.read_index(self.data_dir).get(st)
        if not idx:                                          # no baked map (controller not supervised)
            result["controller"] = "no-map"
            return result
        cal.bake_effective_map(Path(idx["shipped"]), Path(idx["overlay"]), Path(idx["effective"]),
                               log=lambda lvl, msg, **f: getattr(self._m.core.diag, lvl)(
                                   "variables", msg, **f))
        try:
            r = await self._request("calibration.reload", {}, st)
        except CalibrationUnavailable as exc:
            result["controller"] = "pending"
            result["detail"] = f"saved; the controller will pick it up on its next start ({exc})"
            return result
        if r.get("ok", True) and "error" not in r:
            result["controller"] = "reloaded"
        else:
            result["controller"] = "pending"
            result["detail"] = ((r.get("error") or {}).get("message")
                                or "controller refused the reload") + " — saved, applies after the run"
        return result
