# Dev launcher: starts Mosquitto (:1883), the Python backend (:8000) and the Vite
# frontend (:5173) each in its own window, then opens the login page in the
# default browser once the frontend is serving. Run from anywhere:  .\dev.ps1
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$frontendUrl = "http://localhost:5173"
$mosquitto = "D:\tools\mosquitto\mosquitto.exe"

# Broker first - skip if something is already listening on 1883 (or it's running).
$brokerUp = Test-NetConnection -ComputerName 127.0.0.1 -Port 1883 -InformationLevel Quiet -WarningAction SilentlyContinue
if ($brokerUp) {
  Write-Host "Mosquitto already running on :1883 - skipping."
} elseif (Test-Path $mosquitto) {
  Start-Process -FilePath $mosquitto -ArgumentList "-v"
} else {
  Write-Host "Mosquitto not found at $mosquitto - start the broker manually."
}

Start-Process powershell -ArgumentList @(
  "-NoExit", "-Command", "Set-Location '$root\backend'; python run.py"
)
Start-Process powershell -ArgumentList @(
  "-NoExit", "-Command", "Set-Location '$root\frontend'; npm run dev"
)

Write-Host "Waiting for the frontend on $frontendUrl ..."
for ($i = 0; $i -lt 60; $i++) {
  if ((Test-NetConnection -ComputerName 127.0.0.1 -Port 5173 -InformationLevel Quiet -WarningAction SilentlyContinue)) {
    Start-Process $frontendUrl   # default browser -> login page
    Write-Host "Opened $frontendUrl"
    return
  }
  Start-Sleep -Milliseconds 500
}
Write-Host "Frontend did not come up in time; open $frontendUrl manually."
