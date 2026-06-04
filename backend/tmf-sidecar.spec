# PyInstaller spec for the TMF Python sidecar (one-file).
#
# Modules are discovered dynamically at runtime (core.framework.registry.discover),
# so static analysis cannot see them. We therefore:
#   - collect every submodule of `core` and `modules` as hidden imports,
#   - collect argon2 (C-extension) fully,
#   - bundle the JSON the loaders read from the filesystem (manifests, schemas,
#     example configs) at their package-relative paths.
#
# Build:  pyinstaller tmf-sidecar.spec

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

root = Path(SPECPATH)

hiddenimports = collect_submodules("core") + collect_submodules("modules")

argon2_datas, argon2_binaries, argon2_hidden = collect_all("argon2")
hiddenimports += argon2_hidden

# JSON read at runtime by ManifestLoader / ConfigService, kept at the same
# package-relative paths the loaders compute from __file__.
datas = list(argon2_datas)
for pattern in (
    "modules/**/manifest.json",
    "modules/**/schemas/*.json",
    "core/schemas/*.json",
    "config/*.example.json",
):
    for path in root.glob(pattern):
        datas.append((str(path), str(path.parent.relative_to(root))))

a = Analysis(
    ["run.py"],
    pathex=[str(root)],
    binaries=list(argon2_binaries),
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="tmf-sidecar",
    debug=False,
    strip=False,
    upx=False,
    console=True,
)
