<#
.SYNOPSIS
  Release gate: start the BUILT run.exe the way a client's first boot would and fail unless it works.
  Run by cut-release.ps1 (step 5b) for EVERY app; can be run by hand after `build_release.py --track app`.

.DESCRIPTION
  Catches the bug class that source-mode tests cannot: shipped config drift, unlicensed modules,
  frozen-layout path bugs and missing package metadata. It
    1. checks the required package metadata (dist-info) is inside run.dist,
    2. starts run.dist\run.exe with an EMPTY state dir (so config/ is seeded from the shipped
       *.example.json, exactly like a fresh install) on a private port (TMF_PORT),
    3. requires EVERY module named in the shipped app config to be loaded (none skipped),
    4. runs the app's probes (app\<slug>\release-probes.json) against the live API.
  Exit 0 = pass. Any failure throws (non-zero) so cut-release.ps1 stops before signing/publishing.
#>
param(
  [string]$Slug,
  [string]$Dist = "release-build\run.dist",
  [int]$Port = 18765,
  [int]$BootTimeoutSec = 120,
  [switch]$SourceMode
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
if (-not $Slug) {   # same auto-detect as cut-release.ps1: the sole app under app/
  $apps = @(Get-ChildItem -Path (Join-Path $root "app") -Directory -ErrorAction SilentlyContinue |
    Where-Object { Test-Path (Join-Path $_.FullName "VERSION") })
  if ($apps.Count -eq 1) { $Slug = $apps[0].Name }
  else { throw "verify-build: pass -Slug <product> ($($apps.Count) apps with a VERSION file under app/)" }
}
if ($SourceMode) {
  $distPath = Join-Path $root "backend"
  $exe = (Get-Command python).Source
  $exeArgs = @("run.py")
} else {
  $distPath = (Resolve-Path $Dist).Path
  $exe = Join-Path $distPath "run.exe"
  $exeArgs = @()
  if (-not (Test-Path $exe)) { throw "verify-build: $exe not found - build first" }
}

$failures = New-Object System.Collections.Generic.List[string]
function Fail($m) { Write-Host "  FAIL  $m" -ForegroundColor Red; $failures.Add($m) }
function Pass($m) { Write-Host "  ok    $m" -ForegroundColor Green }

$probeFile = Join-Path $root "app\$Slug\release-probes.json"
$probes = $null
if (Test-Path $probeFile) { $probes = Get-Content $probeFile -Raw | ConvertFrom-Json }

# 1. package metadata that PyInstaller drops unless --copy-metadata
if ($probes -and $probes.required_metadata -and -not $SourceMode) {
  foreach ($pkg in $probes.required_metadata) {
    $norm = ($pkg -replace "-", "_")
    $hit = Get-ChildItem $distPath -Directory -Filter "*.dist-info" |
           Where-Object { $_.Name -imatch "^($([regex]::Escape($pkg))|$([regex]::Escape($norm)))-" }
    if ($hit) { Pass "metadata bundled: $pkg" } else { Fail "package metadata missing from run.dist: $pkg (add --copy-metadata)" }
  }
}

# Framework defaults (docs/RELEASE_GATE.md): GUI toolkits ship an OLD MSVCP140.dll that crashes native
# drivers (NI-DAQmx DAQmxCreateTask: access violation) in the frozen exe. Always forbidden, whatever the
# app's probes file says; the app can only ADD to the list (and to forbid_in_dist_root, which has no default
# because a legitimate dependency may ship some of those runtime DLLs - the app proves its own set).
$defaultForbid = @("PyQt5", "PyQt6", "PySide2", "PySide6", "matplotlib", "tkinter", "Qt5Core.dll")
if (-not $probes) { $probes = [pscustomobject]@{} }
$have = @(); if ($probes.PSObject.Properties.Name -contains "forbid_in_dist") { $have = @($probes.forbid_in_dist) }
$probes | Add-Member -NotePropertyName "forbid_in_dist" -NotePropertyValue @($have + $defaultForbid | Select-Object -Unique) -Force

# 1b. bundled GUI toolkits / runtimes that break native drivers (e.g. NI-DAQmx) in the frozen exe
if ($probes -and $probes.forbid_in_dist -and -not $SourceMode) {
  foreach ($name in $probes.forbid_in_dist) {
    $hit = Get-ChildItem $distPath -Recurse -Force -ErrorAction SilentlyContinue -Include $name, "$name.*" |
           Select-Object -First 1
    if (-not $hit) { $hit = Get-ChildItem $distPath -Directory -Filter $name -ErrorAction SilentlyContinue | Select-Object -First 1 }
    if ($hit) { Fail "forbidden item bundled in run.dist: $name  ($($hit.FullName))" } else { Pass "not bundled: $name" }
  }
}

if ($probes -and $probes.forbid_in_dist_root -and -not $SourceMode) {
  foreach ($name in $probes.forbid_in_dist_root) {
    if (Test-Path (Join-Path $distPath $name)) { Fail "run.dist root contains $name - it would shadow the system MSVC runtime for native drivers" }
    else { Pass "not in run.dist root: $name" }
  }
}

# 2. first-boot start on a private port with an empty state dir
$state = Join-Path ([IO.Path]::GetTempPath()) ("tmf-verify-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Path $state | Out-Null
if ($SourceMode) {
  # a frozen build ships app.release.json as its first-boot app config; mimic that for the dry run
  New-Item -ItemType Directory -Path (Join-Path $state "config") | Out-Null
  Copy-Item (Join-Path $root "backend\config\app.release.json") (Join-Path $state "config\app.json")
}
$env:TMF_STATE_DIR = $state
$env:TMF_PORT = "$Port"
$base = "http://127.0.0.1:$Port"
$proc = $null
try {
  Write-Host "  starting $exe on :$Port (state $state)"
  if ($exeArgs.Count -gt 0) { $proc = Start-Process -FilePath $exe -ArgumentList $exeArgs -WorkingDirectory $distPath -WindowStyle Hidden -PassThru }
  else { $proc = Start-Process -FilePath $exe -WorkingDirectory $distPath -WindowStyle Hidden -PassThru }
  $up = $false
  $deadline = (Get-Date).AddSeconds($BootTimeoutSec)
  while ((Get-Date) -lt $deadline) {
    if ($proc.HasExited) { break }
    try { Invoke-RestMethod "$base/healthz" -TimeoutSec 3 | Out-Null; $up = $true; break } catch { Start-Sleep -Milliseconds 700 }
  }
  if (-not $up) {
    Fail "backend did not answer /healthz within ${BootTimeoutSec}s (exited=$($proc.HasExited))"
  } else {
    Pass "backend booted from first-boot config"

    # 3. every module in the shipped config must be loaded
    $cfgPath = Join-Path $state "config\app.json"
    if (-not (Test-Path $cfgPath)) { Fail "first boot did not seed config\app.json" }
    else {
      $want = @((Get-Content $cfgPath -Raw | ConvertFrom-Json).modules | ForEach-Object { $_.id })
      $st = Invoke-RestMethod "$base/modules/status" -TimeoutSec 10
      foreach ($id in $want) {
        $m = $st.modules | Where-Object { $_.id -eq $id }
        if ($m -and $m.status -eq "loaded") { Pass "module loaded: $id" }
        elseif ($m) { Fail "module '$id' is $($m.status): $($m.reason)" }
        else { Fail "module '$id' is in the shipped app config but not registered/discovered" }
      }
    }

    # 4. app probes against the live API
    if ($probes -and $probes.probes) {
      $token = $null
      try {
        $login = Invoke-RestMethod "$base/auth/login" -Method Post -ContentType "application/json" `
          -Body '{"username":"admin","credential":{"password":"admin"}}' -TimeoutSec 10
        $token = $login.token
        if (-not $token) { $token = $login.access_token }
      } catch { Fail "login as the seeded admin failed: $($_.Exception.Message)" }
      foreach ($p in $probes.probes) {
        $h = @{}
        if ($p.auth -and $token) { $h["Authorization"] = "Bearer $token" }
        try {
          $r = Invoke-RestMethod ($base + $p.path) -Headers $h -TimeoutSec 15
          $n = if ($r -is [array]) { $r.Count } elseif ($r -and $r.PSObject.Properties.Name -contains "items") { @($r.items).Count }
               elseif ($r) { @($r.PSObject.Properties).Count } else { 0 }
          if ($n -ge [int]$p.min_items) { Pass "probe $($p.path): $n item(s)" }
          else { Fail "probe $($p.path): $n item(s), expected >= $($p.min_items)" }
        } catch { Fail "probe $($p.path): $($_.Exception.Message)" }
      }
    }
  }
} finally {
  if ($proc) { & taskkill /PID $proc.Id /T /F 2>$null | Out-Null }
  Remove-Item Env:\TMF_PORT -ErrorAction SilentlyContinue
  Remove-Item Env:\TMF_STATE_DIR -ErrorAction SilentlyContinue
  Start-Sleep -Milliseconds 500
  Remove-Item $state -Recurse -Force -ErrorAction SilentlyContinue
}

# 5. controller probes: real driver calls through the built exe's controller (native-DLL bugs)
if ($probes -and $probes.controller_probes -and -not $SourceMode) {
  $out = & python (Join-Path $PSScriptRoot "verify_controller_probe.py") $distPath $probeFile 2>&1
  foreach ($l in $out) { Write-Host "  $l" }
  if ($LASTEXITCODE -eq 1) { Fail "controller probe failed (see lines above)" }
  elseif ($LASTEXITCODE -ne 0) { Fail "controller probe could not run (exit $LASTEXITCODE)" }
  elseif ($out -match "^SKIP") { Write-Host "  note: a controller probe was SKIPPED (device absent on this PC) - hardware path NOT verified" -ForegroundColor Yellow }
}

if ($failures.Count -gt 0) {
  Write-Host ""
  throw ("verify-build FAILED (" + $failures.Count + "): " + ($failures -join " | "))
}
Write-Host "verify-build: all checks passed" -ForegroundColor Green
