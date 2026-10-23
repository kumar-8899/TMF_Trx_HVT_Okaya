"""A Python interpreter for custom scripts on a client PC that has none (docs/DEBUG_TOOL.md D4).

The frozen app ships only `run.exe`, so the tool brings its own: the python.org *embeddable* CPython (about 10 MB) rides in the
tool's release zip as `python-embed*.zip` and is unzipped on first use - no installer, no admin rights, no PATH change, works
air-gapped. Resolution order for `interpreter: python`:

  1. the interpreter this tool already extracted (`<install_dir>/python.exe`)
  2. extract the bundled embeddable zip (and apply any offline `wheelhouse/*.whl`)
  3. a system Python found on PATH - but only after it proves it runs (the Windows Store `python.exe` stub does not)
  4. nothing: a structured error that says how to fix it (never a silent fallback)

The embeddable's `._pth` file locks `sys.path`; extraction patches it so `Lib/site-packages` (where the build puts
`core.services.dbconn`, pymysql, pyodbc, sqlalchemy and any wheelhouse wheels) is importable. Pure-Python wheels are installed by
unzipping them - the embeddable has no pip, and an air-gapped PC has no index anyway.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Callable

MIN_VERSION = (3, 8)


class PythonUnavailable(Exception):
    pass


def _probe(exe: str | Path, *, run: Callable = subprocess.run) -> tuple[bool, str]:
    """True only if `exe` really runs Python >= MIN_VERSION (isolated mode, so no user site-packages interfere)."""
    try:
        r = run([str(exe), "-I", "-c", "import sys;print('%d.%d.%d' % sys.version_info[:3])"], capture_output=True, text=True,
                timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as exc:                                                     # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    out = (r.stdout or "").strip()
    try:
        ver = tuple(int(x) for x in out.split("."))
    except ValueError:
        return False, f"not a python interpreter (printed {out[:80]!r}{(' / ' + (r.stderr or '').strip()[:80]) if r.stderr else ''})"
    if r.returncode != 0 or ver[:2] < MIN_VERSION:
        return False, f"python {out} is too old (need >= {MIN_VERSION[0]}.{MIN_VERSION[1]})"
    return True, out


def _safe_extract(zf: zipfile.ZipFile, dest: Path) -> list[str]:
    root = dest.resolve()
    names = []
    for info in zf.infolist():
        target = (dest / info.filename).resolve()
        if root != target and root not in target.parents:
            raise PythonUnavailable(f"refusing an archive member that escapes the folder: {info.filename!r}")
        names.append(info.filename)
    zf.extractall(dest)
    return names


class PythonEnv:
    def __init__(self, tool_dir: Path | None, install_dir: Path, *, wheelhouses: list[Path] | None = None,
                 which: Callable[[str], str | None] = shutil.which, run: Callable = subprocess.run) -> None:
        self.tool_dir = Path(tool_dir) if tool_dir else None
        self.install_dir = Path(install_dir)
        self.wheelhouses = [Path(w) for w in (wheelhouses if wheelhouses is not None else
                                              ([self.tool_dir / "wheelhouse"] if self.tool_dir else []))]
        self._which, self._run = which, run

    # ------------------------------------------------------------------ discovery
    def bundled_zip(self) -> Path | None:
        if not self.tool_dir or not self.tool_dir.is_dir():
            return None
        found = sorted(self.tool_dir.glob("python-embed*.zip")) or sorted((self.tool_dir / "python").glob("python-embed*.zip"))
        return found[-1] if found else None

    @property
    def extracted_exe(self) -> Path:
        return self.install_dir / "python.exe"

    def _system_exe(self) -> Path | None:
        for name in ("python", "python3", "py"):
            p = self._which(name)
            if p and name != "py":
                return Path(p)
        return None

    def status(self) -> dict:
        ex = self.extracted_exe.is_file()
        z = self.bundled_zip()
        sysexe = self._system_exe()
        sys_ok, sys_info = _probe(sysexe, run=self._run) if sysexe else (False, "no python on PATH")
        return {"extracted": ex, "extracted_path": str(self.extracted_exe) if ex else None,
                "bundled_zip": str(z) if z else None, "can_extract": bool(z),
                "system_python": str(sysexe) if sys_ok else None, "system_python_note": None if sys_ok else sys_info,
                "wheelhouses": [str(w) for w in self.wheelhouses if w.is_dir()],
                "installed_wheels": self._installed().get("wheels", []),
                "will_use": "extracted" if ex else "bundled (extracts on first use)" if z else "system" if sys_ok else "none"}

    # ------------------------------------------------------------------ extraction
    def _site_packages(self) -> Path:
        return self.install_dir / "Lib" / "site-packages"

    def _installed(self) -> dict:
        p = self.install_dir / "installed-wheels.json"
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def extract(self) -> Path:
        z = self.bundled_zip()
        if z is None:
            raise PythonUnavailable("no bundled interpreter (python-embed*.zip) next to the tool")
        self.install_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(z) as zf:
            _safe_extract(zf, self.install_dir)
        if not self.extracted_exe.is_file():
            raise PythonUnavailable(f"{z.name} did not contain python.exe - it is not a python.org embeddable package")
        self._patch_pth()
        self._site_packages().mkdir(parents=True, exist_ok=True)
        return self.extracted_exe

    def _patch_pth(self) -> None:
        for pth in self.install_dir.glob("python*._pth"):
            lines = pth.read_text(encoding="utf-8").splitlines()
            out, have_sp, have_site = [], False, False
            for ln in lines:
                s = ln.strip()
                if s.replace("/", "\\").lower() == "lib\\site-packages":
                    have_sp = True
                if s.lstrip("#").strip() == "import site":
                    ln, have_site = "import site", True
                out.append(ln)
            if not have_sp:
                out.insert(next((i for i, ln in enumerate(out) if ln.strip() == "."), len(out)) + 1, "Lib\\site-packages")
            if not have_site:
                out.append("import site")
            pth.write_text("\n".join(out) + "\n", encoding="utf-8")

    def install_wheelhouse(self) -> list[str]:
        """Unzip every `*.whl` of the wheelhouses into site-packages (pure-Python wheels). Idempotent; returns names added now."""
        done = self._installed()
        have = {w["file"]: w for w in done.get("wheels", [])}
        added: list[str] = []
        sp = self._site_packages()
        sp.mkdir(parents=True, exist_ok=True)
        for house in self.wheelhouses:
            if not house.is_dir():
                continue
            for whl in sorted(house.glob("*.whl")):
                key = f"{whl.name}:{whl.stat().st_size}"
                if key in have:
                    continue
                with zipfile.ZipFile(whl) as zf:
                    _safe_extract(zf, sp)
                have[key] = {"file": key, "name": whl.name}
                added.append(whl.name)
        if added:
            (self.install_dir / "installed-wheels.json").write_text(json.dumps({"wheels": list(have.values())}, indent=2), encoding="utf-8")
        return added

    # ------------------------------------------------------------------ resolve
    def resolve(self) -> dict:
        """-> {kind, path, version, notes}. Raises PythonUnavailable with the fix when nothing works."""
        notes: list[str] = []
        if self.extracted_exe.is_file():
            ok, info = _probe(self.extracted_exe, run=self._run)
            if ok:
                return self._ready("bundled", self.extracted_exe, info, notes)
            notes.append(f"previously extracted interpreter does not run ({info}); re-extracting")
        if self.bundled_zip() is not None:
            try:
                exe = self.extract()
                ok, info = _probe(exe, run=self._run)
                if ok:
                    notes.append("extracted the bundled interpreter on first use")
                    return self._ready("bundled", exe, info, notes)
                notes.append(f"the bundled interpreter was extracted but does not run: {info}")
            except (PythonUnavailable, OSError, zipfile.BadZipFile) as exc:
                notes.append(f"could not extract the bundled interpreter: {exc}")
        sysexe = self._system_exe()
        if sysexe:
            ok, info = _probe(sysexe, run=self._run)
            if ok:
                return {"kind": "system", "path": str(sysexe), "version": info, "notes": notes + ["using the Python found on PATH"]}
            notes.append(f"python on PATH is not usable: {info}")
        raise PythonUnavailable("no usable Python on this PC and no bundled interpreter. " + " | ".join(notes) +
                                " - put python-embed*.zip (python.org 'Windows embeddable package') next to the tool, or install Python.")

    def _ready(self, kind: str, exe: Path, version: str, notes: list[str]) -> dict:
        try:
            added = self.install_wheelhouse()
            if added:
                notes.append("installed from the wheelhouse: " + ", ".join(added))
        except (OSError, zipfile.BadZipFile, PythonUnavailable) as exc:
            notes.append(f"wheelhouse install failed: {exc}")
        return {"kind": kind, "path": str(exe), "version": version, "notes": notes}

