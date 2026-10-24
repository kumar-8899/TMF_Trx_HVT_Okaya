"""Build a python.org-embeddable-style package from THIS PC's Python (test/verification helper only).

Lets the tests and a local `deploy/build-debug-tool.ps1 -EmbedZip` run exercise the bundled-interpreter path without downloading
anything. A real release must bundle the genuine python.org package (the build script says so and records its SHA-256).
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

SKIP_DIRS = {"site-packages", "test", "tests", "idlelib", "tkinter", "turtledemo", "ensurepip", "lib2to3", "__pycache__", "venv",
             "pydoc_data", "distutils"}


def build_embeddable_like(out_dir: Path | str, name: str = "python-embed-local.zip") -> Path:
    if sys.platform != "win32":
        raise RuntimeError("the embeddable package is Windows-only")
    base = Path(sys.base_prefix)
    tag = f"{sys.version_info.major}{sys.version_info.minor}"
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stdlib = out_dir / f"python{tag}.zip"
    with zipfile.ZipFile(stdlib, "w", zipfile.ZIP_STORED) as z:
        for p in (base / "Lib").rglob("*.py"):
            rel = p.relative_to(base / "Lib")
            if not (set(rel.parts[:-1]) & SKIP_DIRS):
                z.write(p, rel.as_posix())
    out = out_dir / name
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as z:
        for fname in ("python.exe", "python3.dll", f"python{tag}.dll", "vcruntime140.dll", "vcruntime140_1.dll"):
            if (base / fname).is_file():
                z.write(base / fname, fname)
        for p in (base / "DLLs").iterdir():
            if p.suffix.lower() in (".pyd", ".dll"):
                z.write(p, p.name)
        z.write(stdlib, stdlib.name)
        z.writestr(f"python{tag}._pth", f"python{tag}.zip\n.\n\n# Uncomment to run site.main() automatically\n#import site\n")
    stdlib.unlink()
    return out


if __name__ == "__main__":
    print(build_embeddable_like(sys.argv[1] if len(sys.argv) > 1 else "."))
