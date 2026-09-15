# Dev launcher — a thin shim over the one entrypoint, station.py.
#
#   .\dev.ps1
#
# is exactly `python station.py --dev`: it starts Mosquitto (:1883), the supervised Python
# backend (:8000, controller auto-started when app.json controller.kind = "python"), and the
# Vite frontend (:5173) with HMR, then opens the app in a native window. All the logic lives
# in station.py (the single run entrypoint, source + frozen) — this file just forwards to it.
$ErrorActionPreference = "Stop"
python (Join-Path $PSScriptRoot "station.py") --dev @args
exit $LASTEXITCODE
