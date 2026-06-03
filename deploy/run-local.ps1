# Bring up the Phase-0 skeleton locally: broker + app + LabVIEW stub.
# Graphical-first demo (PRINCIPLES §6): watch tmf/# in MQTT Explorer.
#
# Usage:  ./deploy/run-local.ps1
#   - Broker (Mosquitto) and the Python app start in the background.
#   - The LabVIEW reference stub runs in THIS window; Ctrl-C it to simulate a
#     crash (LWT -> status offline -> /readyz not-ready), i.e. criterion #7.

param(
    [string]$Station = "st1",
    [int]$Port = 1883
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$backend = Join-Path $root "backend"

# Locate Mosquitto: prefer the vendored (bundled) broker, then PATH, then installs.
$vendored = Join-Path $PSScriptRoot "vendor/mosquitto/win64/mosquitto.exe"
$mosq = $null
if (Test-Path $vendored) {
    $mosq = $vendored
} else {
    $mosq = (Get-Command mosquitto -ErrorAction SilentlyContinue).Source
    if (-not $mosq) {
        foreach ($c in @("C:\Program Files\mosquitto\mosquitto.exe",
                         "C:\Program Files (x86)\mosquitto\mosquitto.exe")) {
            if (Test-Path $c) { $mosq = $c; break }
        }
    }
}
if (-not $mosq) {
    Write-Error "mosquitto not found. Run ./deploy/fetch-mosquitto.ps1 to vendor it."
    exit 1
}

$broker = $null
$app = $null
try {
    Write-Host "Starting broker ($mosq) ..."
    $broker = Start-Process $mosq -ArgumentList "-c", "$root/deploy/mosquitto.conf", "-v" `
        -PassThru -WindowStyle Minimized
    Start-Sleep -Seconds 1

    Write-Host "Starting Python app ..."
    $app = Start-Process powershell `
        -ArgumentList "-NoExit", "-Command", "Set-Location '$backend'; python run.py" -PassThru
    Start-Sleep -Seconds 2

    Write-Host ""
    Write-Host "  App:   http://127.0.0.1:8000/hello/ping   /readyz   /modules/status"
    Write-Host "  MQTT:  connect MQTT Explorer to 127.0.0.1:$Port  ->  watch tmf/#"
    Write-Host ""
    Write-Host "  Stub running below. Ctrl-C to simulate a LabVIEW crash (LWT -> offline)."
    Write-Host ""

    Set-Location $backend
    python -m tools.lv_stub --station $Station --host 127.0.0.1 --port $Port
}
finally {
    Write-Host "Stopping app + broker ..."
    if ($app)    { Stop-Process -Id $app.Id    -Force -ErrorAction SilentlyContinue }
    if ($broker) { Stop-Process -Id $broker.Id -Force -ErrorAction SilentlyContinue }
}
