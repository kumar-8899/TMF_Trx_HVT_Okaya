<#
build-update-package.ps1 - build "<AppShort>-Update-<ver>.exe": a small Inno-based tool that
copies an already-signed update onto an EXISTING install's fixed incoming-update slot, so a site
engineer no longer has to know where the .ksupdate/.zip files go or type two paths into the
Updates page - they run this .exe, then click "Scan for updates on this PC" in the app (Config ->
Updates). This tool never applies anything itself: verification/staging/rollback all stay in the
already-signed, already-tested station-side pipeline (core/services/updates.py) - see
update-package.iss.template's header for why that boundary matters.

Prereqs on the BUILD machine (not the client):
  * a COMPLETED `python backend/build_release.py --track app --product <slug>` (release-build\
    RELEASE.json with full_artifact_hash).
  * Inno Setup 6 (`choco install innosetup -y` / `winget install JRSoftware.InnoSetup`).
  * Optional Keystation signing: set KS_INTERMEDIATE_SEED / KS_INTERMEDIATE_CERT in the
    environment (else the .ksupdate is dev-signed / UNTRUSTED, same as cut-release.ps1 with no
    secrets - installs only where a station's app.json has updates.allow_unverified=true).

  .\deploy\build-update-package.ps1 -Slug <product> [-Publisher <name>] [-AppShort <name>]
                                    [-Iscc <path-to-ISCC.exe>]
#>
param(
  [Parameter(Mandatory = $true)][string]$Slug,
  [string]$Publisher,
  [string]$AppShort,
  [string]$Iscc
)

$ErrorActionPreference = "Stop"
function Info($m) { Write-Host "[update-package] $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "[update-package] $m" -ForegroundColor Yellow }

$repo = Split-Path -Parent $PSScriptRoot
$deploy = $PSScriptRoot
$template = Join-Path $deploy "update-package.iss.template"
$rendered = Join-Path $deploy "update-package.iss"
if (-not (Test-Path $template)) { throw "template not found: $template" }

# --- inputs: branding (app.json) + version (app/<slug>/VERSION) - SAME derivation as
# build-installer.ps1, so this tool's DefaultDirName matches where the main installer put the app.
$appJson = Join-Path $repo "backend\config\app.json"
if (-not (Test-Path $appJson)) { $appJson = Join-Path $repo "backend\config\app.example.json" }
$branding = (Get-Content $appJson -Raw | ConvertFrom-Json).branding
$appName = if ($branding.name) { $branding.name } else { $Slug }
if (-not $Publisher) { $Publisher = $appName }
if (-not $AppShort) {
  $AppShort = ($appName -replace '[^A-Za-z0-9]', '')
  if (-not $AppShort) { $AppShort = ($Slug -replace '[^A-Za-z0-9]', '') }
}

$verFile = Join-Path $repo "app\$Slug\VERSION"
if (-not (Test-Path $verFile)) { throw "no version file: app\$Slug\VERSION" }
$version = (Get-Content $verFile -Raw).Trim()

# --- verify the build artifacts exist AND are COMPLETE for THIS slug/version (same staleness
# guard as build-installer.ps1 - a stale/aborted release-build must not get silently repackaged).
$releaseJson = Join-Path $repo "release-build\RELEASE.json"
if (-not (Test-Path $releaseJson)) {
  throw "missing $releaseJson - run 'python backend\build_release.py --track app --product $Slug' first."
}
$rel = Get-Content $releaseJson -Raw | ConvertFrom-Json
if ($rel.track -ne "app") { throw "release-build\RELEASE.json is track '$($rel.track)', not 'app'." }
if ($rel.version -ne $version) {
  throw "release-build\RELEASE.json is version '$($rel.version)', but app\$Slug\VERSION says " +
    "'$version' - release-build is STALE. Re-run build_release.py first."
}
if (-not $rel.full_artifact_hash) { throw "RELEASE.json has no full_artifact_hash - incomplete build." }
Info "release-build verified: track=app, version=$version"

# --- stage + sign into release-build\update-package\ -------------------------------------------
$stageRoot = Join-Path $repo "release-build\update-package"
if (Test-Path $stageRoot) { Remove-Item -Recurse -Force $stageRoot }
New-Item -ItemType Directory -Force $stageRoot | Out-Null

if (-not $env:KS_INTERMEDIATE_SEED) {
  Warn "KS_INTERMEDIATE_SEED not set - the pair will be DEV-signed / UNTRUSTED (installs only " +
    "where the target station's app.json has updates.allow_unverified=true)."
}

$env:KS_TRACK = "app"
$ks = Join-Path $stageRoot "update.ksupdate"
python (Join-Path $repo "tools\ks_release_signer\sign_update.py") $releaseJson $ks
if ($LASTEXITCODE) { throw "sign_update.py failed" }
Copy-Item (Join-Path $repo "release-build\$Slug-$version.zip") (Join-Path $stageRoot "update.zip")
Info "staged -> $stageRoot (from release-build\$Slug-$version.zip)"

# --- render the template + compile with ISCC --------------------------------------------------
$map = @{
  "@@APP_NAME@@"    = $appName
  "@@APP_SHORT@@"   = $AppShort
  "@@APP_VERSION@@" = $version
  "@@PUBLISHER@@"   = $Publisher
}
$text = Get-Content $template -Raw
foreach ($k in $map.Keys) { $text = $text.Replace($k, $map[$k]) }
Set-Content -Path $rendered -Value $text -Encoding UTF8
Info "rendered $rendered"

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

$out = Join-Path $deploy "Output\$AppShort-Update-$version.exe"
if (Test-Path $out) { Info "built: $out" } else { Warn "ISCC finished but $out not found - check the [Setup] OutputDir." }
