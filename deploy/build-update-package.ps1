<#
build-update-package.ps1 - build "<AppShort>-Update-<ver>.exe": a small Inno-based tool that
copies an already-signed update (full and/or app-payload scope - ADR
docs/decisions/0002-nuitka-compile-scope.md) onto an EXISTING install's fixed incoming-update
slots, so a site engineer no longer has to know where the .ksupdate/.zip files go or type two
paths into the Updates page - they run this .exe, then click "Scan for updates on this PC" in the
app (Config -> Updates). This tool never applies anything itself: verification/staging/rollback
all stay in the already-signed, already-tested station-side pipeline (core/services/updates.py) -
see update-package.iss.template's header for why that boundary matters.

Prereqs on the BUILD machine (not the client):
  * a COMPLETED `python backend/build_release.py --track app --product <slug>` (release-build\
    RELEASE.json with full_artifact_hash, and app_payload_artifact_hash when there is app-owned
    payload to patch).
  * Inno Setup 6 (`choco install innosetup -y` / `winget install JRSoftware.InnoSetup`).
  * Optional Keystation signing: set KS_INTERMEDIATE_SEED / KS_INTERMEDIATE_CERT in the
    environment (else both .ksupdate files are dev-signed / UNTRUSTED, same as cut-release.ps1
    with no secrets - installs only where a station's app.json has updates.allow_unverified=true).

  .\deploy\build-update-package.ps1 -Slug <product> [-Publisher <name>] [-AppShort <name>]
                                    [-SkipFull] [-Iscc <path-to-ISCC.exe>]

-SkipFull builds ONLY the app-payload-scope pair (skip when a release is a pure app-owned patch
and there is no reason to also carry the full artifact - smaller .exe). By default BOTH are
signed and bundled when RELEASE.json has an app_payload_artifact_hash; only "full" is bundled
when it doesn't (nothing app-owned changed - e.g. --track framework, or --compile-app-payload).
#>
param(
  [Parameter(Mandatory = $true)][string]$Slug,
  [string]$Publisher,
  [string]$AppShort,
  [switch]$SkipFull,
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

$hasAppPayload = [bool]($rel.app_payload_artifact_hash -and $rel.app_payload_artifact)
if (-not $hasAppPayload) {
  Warn "no app_payload_artifact_hash in RELEASE.json - this build has nothing app-owned to " +
    "patch separately (pure framework build, or --compile-app-payload) - bundling FULL only."
}
$buildFull = -not $SkipFull -or -not $hasAppPayload
if ($SkipFull -and -not $hasAppPayload) {
  Warn "-SkipFull was passed but there is no app-payload artifact to bundle instead - " +
    "bundling FULL anyway (an update package with nothing in it is useless)."
}

# --- stage + sign each requested scope into release-build\update-package\<scope>\ -------------
$stageRoot = Join-Path $repo "release-build\update-package"
if (Test-Path $stageRoot) { Remove-Item -Recurse -Force $stageRoot }
New-Item -ItemType Directory -Force $stageRoot | Out-Null

if (-not $env:KS_INTERMEDIATE_SEED) {
  Warn "KS_INTERMEDIATE_SEED not set - both pairs will be DEV-signed / UNTRUSTED (installs only " +
    "where the target station's app.json has updates.allow_unverified=true)."
}

function Sign-Scope([string]$scope, [string]$zipName) {
  $dir = Join-Path $stageRoot $scope
  New-Item -ItemType Directory -Force $dir | Out-Null
  $env:KS_TRACK = "app"
  $env:KS_ARTIFACT_SCOPE = $scope
  $ks = Join-Path $dir "update.ksupdate"
  python (Join-Path $repo "tools\ks_release_signer\sign_update.py") $releaseJson $ks
  if ($LASTEXITCODE) { throw "sign_update.py failed for scope=$scope" }
  Copy-Item (Join-Path $repo "release-build\$zipName") (Join-Path $dir "update.zip")
  Info "staged $scope -> $dir (from release-build\$zipName)"
}

if ($buildFull) { Sign-Scope "full" "$Slug-$version.zip" }
if ($hasAppPayload) { Sign-Scope "app-payload" $rel.app_payload_artifact }

# --- render the template + compile with ISCC --------------------------------------------------
$map = @{
  "@@APP_NAME@@"        = $appName
  "@@APP_SHORT@@"       = $AppShort
  "@@APP_VERSION@@"     = $version
  "@@PUBLISHER@@"       = $Publisher
  "@@HAS_FULL@@"        = if ($buildFull) { "1" } else { "0" }
  "@@HAS_APP_PAYLOAD@@" = if ($hasAppPayload) { "1" } else { "0" }
}
$text = Get-Content $template -Raw
foreach ($k in $map.Keys) { $text = $text.Replace($k, $map[$k]) }
Set-Content -Path $rendered -Value $text -Encoding UTF8
Info "rendered $rendered  (full=$($map['@@HAS_FULL@@']), app-payload=$($map['@@HAS_APP_PAYLOAD@@']))"

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
