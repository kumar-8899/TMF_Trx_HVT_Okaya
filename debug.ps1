# Debug Server launcher: starts the standalone MQTT debug sidecar (DEBUG_SERVER.md)
# and opens its UI. The sidecar only subscribes the station bus - it needs the
# broker (:1883) running; the core (:8000) is needed only for token validation
# (use -NoAuth to skip it). Run from anywhere:  .\debug.ps1   [-NoAuth] [-Port 8001]
param(
  [int]$Port      = 8001,
  [string]$Broker = "127.0.0.1:1883",
  [string]$Core   = "http://127.0.0.1:8000",
  [string]$Station = "",            # blank = read from backend/config/app.json
  [switch]$NoAuth                    # dev: skip core /auth/me token check
)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$ui = "http://127.0.0.1:$Port"
$brokerHost, $brokerPort = $Broker.Split(":")

# Broker must be up - the sidecar captures from it.
if (-not (Test-NetConnection -ComputerName $brokerHost -Port ([int]$brokerPort) -InformationLevel Quiet -WarningAction SilentlyContinue)) {
  Write-Host "WARNING: no broker on $Broker - the timeline will be empty until it is up." -ForegroundColor Yellow
}

# Set the env the sidecar reads (DebugConfig.from_env). Start-Process inherits
# this process's environment, so the child window picks these up - no inline glue.
$env:TMF_DEBUG_PORT  = "$Port"
$env:TMF_BROKER_HOST = $brokerHost
$env:TMF_BROKER_PORT = "$brokerPort"
$env:TMF_CORE_URL    = $Core
if ($Station) { $env:TMF_STATION = $Station } else { Remove-Item Env:\TMF_STATION -ErrorAction SilentlyContinue }
if ($NoAuth)  { $env:TMF_DEBUG_NO_AUTH = "1" } else { Remove-Item Env:\TMF_DEBUG_NO_AUTH -ErrorAction SilentlyContinue }

Write-Host "Debug Server -> $ui   (broker $Broker, auth $(if ($NoAuth) {'OFF'} else {'on'}))"
Start-Process powershell -ArgumentList @(
  "-NoExit", "-Command", "Set-Location '$root\backend'; python run_debug_server.py"
)

# Open the UI once the sidecar is serving.
Write-Host "Waiting for the Debug Server on $ui ..."
for ($i = 0; $i -lt 40; $i++) {
  if (Test-NetConnection -ComputerName 127.0.0.1 -Port $Port -InformationLevel Quiet -WarningAction SilentlyContinue) {
    Start-Process $ui
    Write-Host "Opened $ui  -  paste your core bearer token (or use -NoAuth)."
    return
  }
  Start-Sleep -Milliseconds 500
}
Write-Host "Debug Server did not come up in time; check the new window for errors."
