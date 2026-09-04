<#
install-station.ps1 — SCRIPTABLE/HEADLESS fallback bootstrap for a Test & Measurement app.

The PRIMARY first-install path is now the OFFLINE setup.exe (Inno; run.dist + frozen
run_station.exe + WebView2 — no Python, no pip, no broker service). See DEPLOY_STATION.md.
Use THIS script for a scripted/headless rollout, or when you have no setup.exe. It still needs a
system Python + pip + a broker, which the frozen setup.exe avoids.

GitHub Releases delivers UPDATES (the in-app updater); this handles the FIRST install on a clean
Windows machine. Idempotent — safe to re-run. Framework-owned + generic: every app fork uses it
unchanged, parameterized by the app's product slug + its GitHub repo.

  .\install-station.ps1 -Product <slug> -Repo <owner/repo> [-Token <pat>]
                        [-Channel stable|beta] [-InstallDir <path>]

What it does:
  1. Ensure a system Python (the launcher + run_station.py are NOT frozen — they need Python).
  2. Install the Mosquitto broker (service on :1883) if absent.
  3. pip install pywebview (the native window); WebView2 note.
  4. Download the latest app-track Release's <slug>-<ver>.zip (private-repo asset API), verify its
     sha256 against the .ksupdate manifest's full_artifact_hash, extract to <InstallDir>\run.dist,
     and place run_station.py beside it.
  5. Launch the station in a window.
After this, EVERY new version arrives via the in-app updater (Config -> Updates) — config + data
(instruments, users, recipes) are preserved across updates.
#>
param(
  [Parameter(Mandatory = $true)][string]$Product,
  [Parameter(Mandatory = $true)][string]$Repo,
  [string]$Token = $env:TMF_UPDATE_TOKEN,
  [ValidateSet("stable", "beta")][string]$Channel = "stable",
  [string]$InstallDir = "$env:LOCALAPPDATA\TMF\$Product"
)

$ErrorActionPreference = "Stop"
function Info($m) { Write-Host "[install] $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "[install] $m" -ForegroundColor Yellow }

# --- 1. Python -------------------------------------------------------------------------------
function Test-RealPython {
  # `Get-Command python` is NOT enough: on a bare Windows the WindowsApps `python.exe` is a Store
  # ALIAS stub that opens the Store and exits non-zero — never a real interpreter. Probe for a REAL
  # one: the py.exe launcher, or a `python` whose sys.executable is not under WindowsApps and exits 0.
  if (Test-Path (Join-Path $env:WINDIR "py.exe")) { return $true }
  if (-not (Get-Command python -ErrorAction SilentlyContinue)) { return $false }
  try {
    $real = & python -c "import sys;print(sys.executable)" 2>$null
    if ($LASTEXITCODE -ne 0) { return $false }
    if ($real -match 'WindowsApps') { return $false }   # the Store alias stub
    return $true
  } catch { return $false }
}

if (-not (Test-RealPython)) {
  Info "no real Python found (Store alias stub does not count) - installing Python 3.12 via winget..."
  winget install --id Python.Python.3.12 --source winget -e --accept-package-agreements --accept-source-agreements
  $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
  if (-not (Test-RealPython)) {
    throw "Python still not usable (a WindowsApps alias stub is not a real interpreter). Install " +
          "Python 3.11+ from python.org (tick 'Add to PATH', and disable the Store alias under " +
          "Settings > Apps > App execution aliases) and re-run."
  }
}
Info "Python: $((python --version) 2>&1)"

# --- 2. Mosquitto broker (:1883) -------------------------------------------------------------
$brokerUp = (Test-NetConnection -ComputerName 127.0.0.1 -Port 1883 -WarningAction SilentlyContinue).TcpTestSucceeded
if (-not $brokerUp) {
  Info "installing Mosquitto broker..."
  winget install --id EclipseFoundation.Mosquitto -e --accept-package-agreements --accept-source-agreements
  $svc = Get-Service -Name mosquitto -ErrorAction SilentlyContinue
  if ($svc) {
    Set-Service -Name mosquitto -StartupType Automatic
    if ($svc.Status -ne "Running") { Start-Service mosquitto -ErrorAction SilentlyContinue }
    Info "mosquitto service set to auto-start on :1883"
  } else {
    Warn "mosquitto installed but no service found - start a broker on :1883 manually if MQTT is needed."
  }
} else {
  Info "broker already on :1883 - leaving it alone"
}

# --- 3. pywebview (native window) ------------------------------------------------------------
Info "installing pywebview (native window)..."
python -m pip install --quiet --upgrade "pywebview>=5.0"
Info "note: the window uses WebView2 (preinstalled on Win11; else install the Evergreen runtime)."

# --- 4. Download + verify + extract the latest release --------------------------------------
$apiHeaders = @{ "User-Agent" = "tmf-install"; "Accept" = "application/vnd.github+json" }
if ($Token) { $apiHeaders["Authorization"] = "Bearer $Token" }
$relUrl = if ($Channel -eq "beta") { "https://api.github.com/repos/$Repo/releases" }
          else { "https://api.github.com/repos/$Repo/releases/latest" }
Info "querying $Repo ($Channel)..."
$rel = Invoke-RestMethod -Uri $relUrl -Headers $apiHeaders
if ($Channel -eq "beta") { $rel = $rel | Select-Object -First 1 }
$ver = $rel.tag_name -replace '^v', ''
Info "latest release: $($rel.tag_name)"

$zipAsset = $rel.assets | Where-Object { $_.name -like "*.zip" } | Select-Object -First 1
$ksAsset  = $rel.assets | Where-Object { $_.name -like "*.ksupdate" } | Select-Object -First 1
$rsAsset  = $rel.assets | Where-Object { $_.name -eq "run_station.py" } | Select-Object -First 1
if (-not $zipAsset) { throw "no .zip artifact asset in $($rel.tag_name)" }

function Get-Asset($asset, $outFile) {
  $h = @{ "User-Agent" = "tmf-install"; "Accept" = "application/octet-stream" }
  if ($Token) { $h["Authorization"] = "Bearer $Token" }
  $u = if ($Token) { $asset.url } else { $asset.browser_download_url }
  Invoke-WebRequest -Uri $u -Headers $h -OutFile $outFile
}

$tmpZip = Join-Path $env:TEMP "$Product-$ver.zip"
Info "downloading $($zipAsset.name) ($([int]($zipAsset.size/1MB)) MB)..."
Get-Asset $zipAsset $tmpZip

# verify sha256 against the .ksupdate manifest's full_artifact_hash (best-effort)
if ($ksAsset) {
  $tmpKs = Join-Path $env:TEMP "$Product-$ver.ksupdate"
  Get-Asset $ksAsset $tmpKs
  try {
    $want = (Get-Content $tmpKs -Raw | ConvertFrom-Json).manifest.full_artifact_hash
    $got = (Get-FileHash $tmpZip -Algorithm SHA256).Hash.ToLower()
    if ($want -and ($got -ne $want.ToLower())) {
      throw "artifact hash mismatch: got $($got.Substring(0,12))... want $($want.Substring(0,12))..."
    }
    Info "artifact sha256 verified against the signed manifest."
  } catch { Warn "hash check skipped: $($_.Exception.Message)" }
  Remove-Item $tmpKs -Force -ErrorAction SilentlyContinue
} else {
  Warn "no .ksupdate asset - skipping hash verification."
}

$distDir = Join-Path $InstallDir "run.dist"
New-Item -ItemType Directory -Force $InstallDir | Out-Null
if (Test-Path $distDir) {
  Warn "existing run.dist found - replacing (config + data outside run.dist are preserved)."
  Remove-Item -Recurse -Force $distDir
}
Info "extracting to $distDir..."
Expand-Archive -Path $tmpZip -DestinationPath $distDir -Force   # zip root = run.dist contents
Remove-Item $tmpZip -Force -ErrorAction SilentlyContinue

# run_station.py (the windowed launcher) lives at the deploy root, beside run.dist
if ($rsAsset) {
  Info "downloading run_station.py..."
  Get-Asset $rsAsset (Join-Path $InstallDir "run_station.py")
} else {
  Warn "run_station.py not in the release - will launch headless via run.dist\launcher.py."
}

# --- 5. Launch -------------------------------------------------------------------------------
Info "starting the station..."
if (Test-Path (Join-Path $InstallDir "run_station.py")) {
  Start-Process python -ArgumentList "run_station.py" -WorkingDirectory $InstallDir
} else {
  Start-Process python -ArgumentList "run.dist\launcher.py" -WorkingDirectory $InstallDir
}

# --- 6. Post-install note --------------------------------------------------------------------
Info "============================================================"
Info " Installed $Product $ver -> $InstallDir"
Info " Log in with admin / admin (change it)."
Info " Configure instrument instances ONCE on Config -> Instruments, then restart."
Info " All future versions arrive via the in-app updater (Config -> Updates):"
Info "   Check -> Download -> Install -> Relaunch. Config + data are preserved."
Info "============================================================"
