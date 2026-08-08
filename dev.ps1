# Dev launcher: starts Mosquitto (:1883), the Python backend (:8000) and the Vite
# frontend (:5173) each in its own window, then opens the login page in the
# default browser once the frontend is serving. Run from anywhere:  .\dev.ps1
#
# The backend runs under launcher.py so the "Relaunch to apply" button in
# Settings works in dev (exit 42 -> restart). When app.json sets
# controller.kind = "python", the backend auto-starts the Python controller as a
# child on boot (Settings -> Station configuration), so this one window brings up
# backend + controller together; LabVIEW controllers run externally as before.
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
  "-NoExit", "-Command", "Set-Location '$root\backend'; python launcher.py"
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
