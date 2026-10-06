<#
build-installer.ps1 - render deploy/installer.iss from installer.iss.template and compile it to
<AppShort>-Setup-<ver>.exe with Inno Setup (ISCC). Framework-owned + generic; every fork uses it
unchanged (parameterized by the app's product slug).

Prereqs on the BUILD machine (not the client):
  * a completed `python backend/build_release.py --track app --product <slug>` (so release-build\
    run.dist\* and release-build\run_station.exe exist).
  * Inno Setup 6 (`choco install innosetup -y`) - ISCC.exe on PATH or passed via -Iscc.
  * (optional, for a fully-offline installer) the OFFLINE WebView2 standalone runtime installer.
    Pass its path via -WebView2, or drop it at deploy\vendor\webview2\MicrosoftEdgeWebView2RuntimeInstallerX64.exe.
    Omitted -> the installer still builds but does NOT carry WebView2 (fine on Win11/current Win10,
    which ship it; a stripped machine then needs it installed once).

  .\deploy\build-installer.ps1 -Slug <product> [-Publisher <name>] [-AppShort <name>]
                               [-WebView2 <path>] [-Iscc <path-to-ISCC.exe>]
#>
param(
  [Parameter(Mandatory = $true)][string]$Slug,
  [string]$Publisher,
  [string]$AppShort,
  [string]$WebView2,
  [string]$Iscc
)

$ErrorActionPreference = "Stop"
function Info($m) { Write-Host "[installer] $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "[installer] $m" -ForegroundColor Yellow }

$repo = Split-Path -Parent $PSScriptRoot
$deploy = $PSScriptRoot
$template = Join-Path $deploy "installer.iss.template"
$rendered = Join-Path $deploy "installer.iss"
if (-not (Test-Path $template)) { throw "template not found: $template" }

# --- inputs: branding (app.json) + version (app/<slug>/VERSION) ------------------------------
$appJson = Join-Path $repo "backend\config\app.json"
if (-not (Test-Path $appJson)) { $appJson = Join-Path $repo "backend\config\app.example.json" }
$branding = (Get-Content $appJson -Raw | ConvertFrom-Json).branding
$appName = if ($branding.name) { $branding.name } else { $Slug }
if (-not $Publisher) { $Publisher = $appName }
if (-not $AppShort) {
  # a filesystem-safe short name: the branding name with non-alphanumerics stripped, or the slug.
  $AppShort = ($appName -replace '[^A-Za-z0-9]', '')
  if (-not $AppShort) { $AppShort = ($Slug -replace '[^A-Za-z0-9]', '') }
}

$verFile = Join-Path $repo "app\$Slug\VERSION"
if (-not (Test-Path $verFile)) { throw "no version file: app\$Slug\VERSION" }
$version = (Get-Content $verFile -Raw).Trim()

# stable per-app GUID so setup.exe UPGRADES in place (same AppId across versions). Rendered as
# {{<GUID>} - in the .iss, a leading `{{` is Inno's escape for a literal `{`, so AppId = {<GUID>}.
$md5 = [System.Security.Cryptography.MD5]::Create()
$hash = $md5.ComputeHash([System.Text.Encoding]::UTF8.GetBytes("tmf-station:$Slug"))
$guid = ([System.Guid]::new($hash)).ToString().ToUpper()
$appId = "{{$guid}"

# --- WebView2 (optional; fully-offline installer) --------------------------------------------
if (-not $WebView2) {
  $default = Join-Path $deploy "vendor\webview2\MicrosoftEdgeWebView2RuntimeInstallerX64.exe"
  if (Test-Path $default) { $WebView2 = $default }
}
if ($WebView2 -and -not (Test-Path $WebView2)) { throw "WebView2 installer not found: $WebView2" }
if ($WebView2) { Info "bundling offline WebView2: $WebView2" } else { Warn "no WebView2 bundled (OK on Win11/current Win10)" }

# --- verify the build artifacts exist AND are COMPLETE (not a stale/aborted run) --------------
# A build that fails mid-pipeline (e.g. build_run_station_exe hitting the pywebview plugin
# conflict, pre-fix) used to raise SystemExit BEFORE build_release.py reached the step that writes
# release-build\RELEASE.json and packages the artifact - leaving a run.dist on disk with NO
# RELEASE.json, or one left over from a PREVIOUS successful run. Checking only "does run.dist
# exist" let that ship: setup.exe installed fine, but the station's app_version() (reads
# run.dist\RELEASE.json) returned None forever, and "Check for updates" comparisons were
# meaningless from the very first boot. Refuse to package anything that isn't a complete,
# correctly-versioned build for THIS slug.
$dist = Join-Path $repo "release-build\run.dist"
$rsExe = Join-Path $repo "release-build\run_station.exe"
$releaseJson = Join-Path $repo "release-build\RELEASE.json"
if (-not (Test-Path $dist)) { throw "missing $dist - run build_release.py --track app first" }
if (-not (Test-Path $releaseJson)) {
  throw "missing $releaseJson`n`n" +
    "release-build is incomplete or stale - build_release.py --track app did not finish (it writes " +
    "RELEASE.json near the end, after run.dist + run_station.exe). Re-run:`n" +
    "    python backend\build_release.py --track app --product $Slug`n" +
    "and only run this script after it completes successfully."
}
$rel = Get-Content $releaseJson -Raw | ConvertFrom-Json
if ($rel.track -ne "app") {
  throw "release-build\RELEASE.json is track '$($rel.track)', not 'app' - re-run " +
    "'python backend\build_release.py --track app --product $Slug' (this looks like a stale " +
    "framework-track build left in release-build\)."
}
if ($rel.version -ne $version) {
  throw "release-build\RELEASE.json is version '$($rel.version)', but app\$Slug\VERSION says " +
    "'$version' - release-build is STALE (leftover from a previous build/version). Re-run " +
    "'python backend\build_release.py --track app --product $Slug' and only run this script " +
    "after it completes successfully; never package an old release-build\ against a bumped VERSION."
}
Info "release-build verified: track=app, version=$version (RELEASE.json matches app\$Slug\VERSION)"
if (-not (Test-Path $rsExe)) {
  throw "missing $rsExe`n`n" +
    "build_release.py --track app builds run_station.exe automatically, but is FAIL-SOFT: if the " +
    "PyInstaller build fails, or the exe fails its own runtime smoke test (couldn't reach " +
    "/healthz or never opened a window), it WARNS and removes/skips run_station.exe rather than " +
    "aborting the whole release (run.dist + the .zip/.ksupdate still get built - only the " +
    "offline setup.exe needs it).`n`n" +
    "Options:`n" +
    "  1. Check the build output above for the PyInstaller error, or the pywebview/WebView2 " +
    "runtime issue that failed the smoke test.`n" +
    "  2. Re-run 'pip install -e backend[release]' to make sure pywebview is installed, then " +
    "re-run build_release.py --track app.`n" +
    "  3. Skip the offline setup.exe for now and use deploy/install-station.ps1 (scriptable " +
    "fallback; needs Python + pip on the client) instead."
}

# --- render the template ---------------------------------------------------------------------
$wv2 = if ($WebView2) { $WebView2 } else { "" }
$map = @{
  "@@APP_NAME@@"       = $appName
  "@@APP_SHORT@@"      = $AppShort
  "@@APP_SLUG@@"       = $Slug
  "@@APP_VERSION@@"    = $version
  "@@PUBLISHER@@"      = $Publisher
  "@@APP_ID@@"         = $appId
  "@@WEBVIEW2_SETUP@@" = $wv2
}
$text = Get-Content $template -Raw
foreach ($k in $map.Keys) { $text = $text.Replace($k, $map[$k]) }
Set-Content -Path $rendered -Value $text -Encoding UTF8
Info "rendered $rendered  ($appName $version, publisher '$Publisher', short '$AppShort')"

# --- compile with ISCC -----------------------------------------------------------------------
if (-not $Iscc) {
  $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
  if ($cmd) { $Iscc = $cmd.Source }
  else {
    foreach ($c in @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe")) {
      if (Test-Path $c) { $Iscc = $c; break }
    }
  }
}
if (-not $Iscc) { throw "ISCC.exe not found - install Inno Setup 6 (choco install innosetup -y) or pass -Iscc" }

Info "compiling with $Iscc ..."
& $Iscc $rendered
if ($LASTEXITCODE -ne 0) { throw "ISCC failed (exit $LASTEXITCODE)" }

$out = Join-Path $deploy "Output\$AppShort-Setup-$version.exe"
if (Test-Path $out) { Info "built: $out" } else { Warn "ISCC finished but $out not found - check the [Setup] OutputDir." }
