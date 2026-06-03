# Vendor the Mosquitto broker runtime so the Tauri installer can bundle it
# (LABVIEW_BRIDGE.md §2 — one local broker per station, shipped with the app).
#
# Downloads the official Windows build, silent-installs to a temp dir, and copies
# the minimal runtime (mosquitto.exe + DLLs + helper clients) into
# deploy/vendor/mosquitto/win64/. The build then bundles that folder as a Tauri
# resource (see deploy/README.md). The vendor folder is gitignored; CI/build
# runs this script.
#
# Usage:  ./deploy/fetch-mosquitto.ps1 [-Version 2.0.22]

param(
    [string]$Version = "2.0.22"
)

$ErrorActionPreference = "Stop"
$dest = Join-Path $PSScriptRoot "vendor/mosquitto/win64"
$setup = Join-Path $env:TEMP "mosq-setup-$Version.exe"
$staging = Join-Path $env:TEMP "mosq-staging-$Version"
$url = "https://mosquitto.org/files/binary/win64/mosquitto-$Version-install-windows-x64.exe"

if (-not (Test-Path $setup)) {
    Write-Host "Downloading Mosquitto $Version ..."
    Invoke-WebRequest -Uri $url -OutFile $setup -UseBasicParsing -TimeoutSec 180
}

Write-Host "Silent-installing to staging ..."
if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }
New-Item -ItemType Directory -Force -Path $staging | Out-Null
Start-Process $setup -ArgumentList "/S", "/D=$staging" -Wait
Start-Sleep -Seconds 2

# Minimal runtime: the broker, its DLLs, and the pub/sub clients (handy for debug).
New-Item -ItemType Directory -Force -Path $dest | Out-Null
Get-ChildItem $dest | Remove-Item -Force -ErrorAction SilentlyContinue
$keep = @("mosquitto.exe", "mosquitto_pub.exe", "mosquitto_sub.exe")
Get-ChildItem $staging -Filter *.dll | Copy-Item -Destination $dest
foreach ($f in $keep) {
    Copy-Item (Join-Path $staging $f) -Destination $dest
}

# Ship the station broker config alongside the binary.
Copy-Item (Join-Path $PSScriptRoot "mosquitto.conf") -Destination $dest

Write-Host "Vendored Mosquitto runtime ->"
Get-ChildItem $dest | Select-Object -ExpandProperty Name
