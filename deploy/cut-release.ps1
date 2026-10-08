<#
cut-release.ps1 - the ONE file to build or release a Test & Measurement app.

  .\deploy\cut-release.ps1                 # build + publish a GitHub Release (default)
  .\deploy\cut-release.ps1 -BuildOnly      # build the artifacts only (no git, no publish)
  .\deploy\cut-release.ps1 -Slug <product> # override the auto-detected app slug
  .\deploy\cut-release.ps1 -BuildUpdatePackage  # ALSO build deploy\Output\<AppShort>-Update-<ver>.exe
                                                 # (an offline delivery tool for air-gapped fleets -
                                                 # docs/DEPLOY_STATION.md); off by default, since a
                                                 # networked fleet just uses the GitHub Release + the
                                                 # in-app Check/Download and never needs this.

This is the single entry point for the app-track build/release pipeline: it orchestrates
every step so you never invoke the sub-scripts directly - fetch-mosquitto.ps1,
backend/build_release.py, tools/ks_release_signer/sign_update.py and build-installer.ps1 are
all called from here. (A FRAMEWORK release is just a git tag - see docs/RELEASE_HOWTO.md; the
framework builds no binary. This script builds the APP-track binary artifacts.)

The output matches docs/templates/release.yml's GitHub-hosted job - a GitHub Release carrying
the same FOUR assets (<slug>-<ver>.ksupdate, <slug>-<ver>.zip, run_station.exe,
<AppShort>-Setup-<ver>.exe). Both binaries (run.exe and run_station.exe) are PyInstaller-frozen -
no compiler, no cache to warm (ADR 0003/0004). `-BuildOnly` stops after producing those artifacts
locally (no commit/tag/push, no gh release), for a quick local build or a dry build check.

Slug is auto-detected as the sole directory under app/ (pass -Slug to override / disambiguate),
so a fork runs it with no args. Every fork inherits this file unchanged - it is no longer a
rendered template.

Release gate (step 5b): the BUILT run.exe is booted on a first-boot (empty) state dir and probed -
metadata, forbidden GUI toolkits, every shipped module loaded, the app's API probes and real driver
calls through the built controller (docs/RELEASE_GATE.md). A failure stops the release before anything
is signed or published. Re-running after a failure RESUMES: a tag already at HEAD is reused, and an
existing GitHub Release for it gets its assets replaced - no version bump needed.

Prereqs on THIS machine (see CONTRIBUTING.md): Python 3.11/3.12 + `pip install -e "backend[dev,release]"`,
Node/npm, Inno Setup 6 (`winget install JRSoftware.InnoSetup`), and - for a real release (not
-BuildOnly) - `gh` authenticated with contents:write on origin. Optional Keystation signing:
set KS_INTERMEDIATE_SEED / KS_INTERMEDIATE_CERT in the environment (else the .ksupdate is
dev-signed / UNTRUSTED, same as release.yml with no secrets).

IMPORTANT - a fork that publishes here MUST retarget its own .github/workflows/release.yml from
`on: push: tags: ["app-v*"]` to `on: workflow_dispatch:`, or pushing the tag here ALSO fires the
GitHub-hosted build and you pay for both. That edit is app-owned (the fork's release.yml copy).
#>
param(
  [string]$Slug,
  [switch]$BuildOnly,
  [string]$Iscc,
  [switch]$SkipTests,
  [switch]$AllowDirty,
  [switch]$DryRun,
  [switch]$BuildUpdatePackage
)

$ErrorActionPreference = "Stop"
function Info($m) { Write-Host "[cut-release] $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "[cut-release] $m" -ForegroundColor Yellow }
function Step($m) { Write-Host "`n=== $m ===" -ForegroundColor Green }

$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

# --- app slug: auto-detect the sole app under app/, or take -Slug ------------------------------
if (-not $Slug) {
  $apps = @(Get-ChildItem -Path (Join-Path $repo "app") -Directory -ErrorAction SilentlyContinue |
    Where-Object { Test-Path (Join-Path $_.FullName "VERSION") })
  if ($apps.Count -eq 1) { $Slug = $apps[0].Name; Info "app slug (auto-detected): $Slug" }
  elseif ($apps.Count -eq 0) { throw "no app with a VERSION file under app/ - pass -Slug <product>." }
  else { throw "multiple apps under app/ ($($apps.Name -join ', ')) - pass -Slug <product> to pick one." }
}

# --- 0. Preflight: fail in seconds, not after a 7-minute build ---------------------------------
# build_release.py's run_station.exe smoke test boots the app on :8000 and REFUSES to pass when
# anything already answers there (a running station would answer the probe instead of the new exe).
function Test-PortFree([int]$Port) {
  $c = New-Object System.Net.Sockets.TcpClient
  try { $iar = $c.BeginConnect("127.0.0.1", $Port, $null, $null); return -not ($iar.AsyncWaitHandle.WaitOne(500) -and $c.Connected) }
  catch { return $true } finally { $c.Close() }
}
if (-not (Test-PortFree 8000)) {
  throw "preflight: something is already listening on 127.0.0.1:8000 (a running station?). Stop it first - the run_station.exe smoke test needs the port free."
}
$mosq = Join-Path $PSScriptRoot "vendor/mosquitto/win64/mosquitto.exe"
if (Test-Path $mosq) { Info "preflight: vendored Mosquitto present - fetch step will be skipped" }
else { Warn "preflight: no vendored Mosquitto - step 3 will download it (needs a UAC click on an interactive desktop); pre-stage deploy/vendor/mosquitto/win64 to run unattended." }

$verFile = Join-Path $repo "app/$Slug/VERSION"
if (-not (Test-Path $verFile)) { throw "no version file: app/$Slug/VERSION" }
$new = (Get-Content $verFile -Raw).Trim()
if ($new -notmatch '^\d+\.\d+\.\d+$') { throw "app/$Slug/VERSION is '$new' - expected x.y.z" }
$tag = "app-v$new"
$mode = if ($BuildOnly) { "BUILD-ONLY (no git/publish)" } else { "RELEASE" }
Info "mode: $mode   slug: $Slug   version: $new"

# --- 1. Version-collision guard (release only) ------------------------------------------------
# tag==VERSION passes trivially even for a version REGRESSION. Compare against the highest
# already-published app-v* tag and demand strictly greater, so a stale checkout can't publish
# backwards. Skipped for -BuildOnly (nothing is published).
$tagExists = $false
if (-not $BuildOnly) {
  Step "1/10  version-collision guard"
  git fetch --tags origin --quiet
  # A tag already AT HEAD means "resume": a previous run got past the tag push and failed later (build,
  # gate, publish). That is not a collision - only a tag elsewhere is.
  if (git tag -l $tag) {
    $tagSha = git rev-list -n 1 $tag
    $headSha = git rev-parse HEAD
    if ($tagSha -ne $headSha) { throw "tag $tag already exists and points at $tagSha, not HEAD ($headSha). Delete it or bump VERSION." }
    Warn "tag $tag already exists at HEAD - RESUME mode (skipping the commit/tag/push; an existing release is updated in place)"
    $tagExists = $true
  }
  $published = @(git tag -l "app-v*" | ForEach-Object { $_ -replace '^app-v', '' } |
    Where-Object { $_ -as [version] -and ($_ -ne $new -or -not $tagExists) } | Sort-Object { [version]$_ })
  $latest = if ($published) { $published[-1] } else { $null }
  if ($latest) {
    if ([version]$new -le [version]$latest) {
      throw "app/$Slug/VERSION is $new, but $tag would not be newer than the latest published tag app-v$latest. Bump the VERSION file."
    }
    Info "latest published: app-v$latest  ->  new: $tag  (OK, strictly greater)"
  } else {
    Info "no earlier app-v* tags published - $tag is the first"
  }

  $dirty = @(git status --porcelain | Where-Object { $_ -notmatch 'CHANGELOG\.md$|app/' + [regex]::Escape($Slug) + '/VERSION$' })
  if ($dirty -and -not $AllowDirty) {
    throw "working tree has changes outside CHANGELOG.md / app/$Slug/VERSION:`n$($dirty -join "`n")`nCommit or stash them, or pass -AllowDirty."
  }
}

# --- 2. Test locally (same commands as release.yml's Test step) -------------------------------
Step "2/10  test (backend pytest + frontend vitest/build)"
if ($SkipTests) { Warn "skipped (-SkipTests)" }
else {
  Push-Location backend; python -m pytest -q; if ($LASTEXITCODE) { Pop-Location; throw "backend pytest failed" }; Pop-Location
  Push-Location frontend
  npx vitest run; if ($LASTEXITCODE) { Pop-Location; throw "frontend vitest failed" }
  npm run build;  if ($LASTEXITCODE) { Pop-Location; throw "frontend build failed" }
  Pop-Location
}

# --- 3. Vendor Mosquitto (internal step) -----------------------------------------------------
Step "3/10  vendor Mosquitto"
& (Join-Path $PSScriptRoot "fetch-mosquitto.ps1")

# --- 4. Commit the bump, push, then tag+push (release only; the tag push IS the collision lock)
if (-not $BuildOnly) {
  Step "4/10  commit + push + tag"
  if ($DryRun) {
    Warn "DRY RUN - would: commit CHANGELOG.md/app/$Slug/VERSION if changed, git push origin HEAD, git tag $tag, git push origin $tag"
  } elseif (-not $tagExists) {
    $bump = @(git status --porcelain -- CHANGELOG.md "app/$Slug/VERSION")
    if ($bump) {
      git add CHANGELOG.md "app/$Slug/VERSION"
      git commit -m "release: $tag"
    }
    git push origin HEAD; if ($LASTEXITCODE) { throw "git push origin HEAD failed" }
    git tag $tag
    # If a racing developer already pushed this tag, THIS push is rejected here - before the
    # 30-45 min build below, not after.
    git push origin $tag
    if ($LASTEXITCODE) { git tag -d $tag; throw "git push origin $tag rejected - someone else published $tag first. Bump VERSION and retry." }
  }
} else {
  Step "4/10  commit + push + tag  (skipped: -BuildOnly)"
}

# --- 5. Build (internal step) ------------------------------------------------------------------
Step "5/10  build (PyInstaller)"
python backend/build_release.py --track app --product $Slug
$rc = $LASTEXITCODE
$runStationOk = $true
if ($rc -eq 3) {
  Warn "build_release.py exit 3 - run.dist + .zip/.ksupdate built, but run_station.exe did not (fail-soft). Continuing WITHOUT run_station.exe / setup.exe (the in-app updater does not need them)."
  $runStationOk = $false
} elseif ($rc -ne 0) {
  throw "build_release.py failed (exit $rc)"
}

# --- 5b. Release gate: boot the BUILT exe on first-boot config and probe it ---------------------
# Fails the release before anything is signed or published (config drift, unlicensed module,
# frozen-path bug, missing package metadata, a native driver that crashes only in the frozen exe).
Step "5b/10  verify built app (deploy/verify-build.ps1)"
& (Join-Path $PSScriptRoot "verify-build.ps1") -Slug $Slug
if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) { throw "verify-build failed (exit $LASTEXITCODE)" }

# --- 6. Sign the .ksupdate (internal step; KS_INTERMEDIATE_* from the env if present) ---------
Step "6/10  sign .ksupdate"
$env:KS_TRACK = "app"
if (-not $env:KS_INTERMEDIATE_SEED) {
  Warn "KS_INTERMEDIATE_SEED not set - DEV-signing an UNTRUSTED .ksupdate (installs only where updates.allow_unverified=true)."
}
python tools/ks_release_signer/sign_update.py "release-build/RELEASE.json" "release-build/$Slug-$new.ksupdate"
if ($LASTEXITCODE) { throw "sign_update.py failed." }

# --- 7. WebView2 offline runtime - cache locally once, reuse --------------------------------
Step "7/10  WebView2 offline runtime (cached)"
$wv2 = Join-Path $PSScriptRoot "vendor/webview2/MicrosoftEdgeWebView2RuntimeInstallerX64.exe"
if ($runStationOk -and -not (Test-Path $wv2)) {
  New-Item -ItemType Directory -Force (Split-Path $wv2) | Out-Null
  Info "fetching the Evergreen Standalone Installer (x64) once -> $wv2"
  Invoke-WebRequest -Uri "https://go.microsoft.com/fwlink/?linkid=2124701" -OutFile $wv2
} elseif ($runStationOk) { Info "reusing cached $wv2" }

# --- 8. Offline installer (setup.exe) (internal step) --------------------------------------
Step "8/10  build setup.exe"
if ($runStationOk) {
  $isccArg = @{}; if ($Iscc) { $isccArg["Iscc"] = $Iscc }
  & (Join-Path $PSScriptRoot "build-installer.ps1") -Slug $Slug @isccArg
} else { Warn "skipped (no run_station.exe this build)" }

# --- 8b. Offline UPDATE delivery package (optional; air-gapped fleets) ------------------------
if ($BuildUpdatePackage) {
  Step "8b/10  build update package (-BuildUpdatePackage)"
  $isccArg = @{}; if ($Iscc) { $isccArg["Iscc"] = $Iscc }
  & (Join-Path $PSScriptRoot "build-update-package.ps1") -Slug $Slug @isccArg
} else {
  Step "8b/10  build update package  (skipped: pass -BuildUpdatePackage for an air-gapped fleet)"
}

# --- BuildOnly stops here: the artifacts are on disk, nothing is published --------------------
if ($BuildOnly) {
  Step "done (build-only)"
  Info "artifacts:"
  Info "  release-build\run.dist\            (the swap unit)"
  Info "  release-build\$Slug-$new.zip       (+ .ksupdate)"
  if ($runStationOk) {
    Info "  release-build\run_station.exe"
    Info "  deploy\Output\*-Setup-$new.exe    (offline installer)"
  }
  if ($BuildUpdatePackage) {
    Info "  deploy\Output\*-Update-$new.exe   (offline update delivery - Config -> Updates -> Scan)"
  }
  Info "Skipped: git commit/tag/push and the GitHub Release (that's the default mode, without -BuildOnly)."
  return
}

# --- 9. Release notes from CHANGELOG (PowerShell port of release.yml's awk) -------------------
Step "9/10  release notes"
$notes = New-Object System.Collections.Generic.List[string]
$inblk = $false
foreach ($line in Get-Content "CHANGELOG.md" -Encoding UTF8) {   # PS 5.1 would read it as ANSI -> mojibake
  if ($line -match '^## ') {
    $tok = ($line -split '\s+')[1]
    $inblk = ($tok -eq "v$new" -or $tok -eq $new)
  }
  if ($inblk) { $notes.Add($line) }
}
if ($notes.Count -eq 0) { $notes.Add("Release $new") }
# UTF-8 WITHOUT a BOM: PS 5.1's Set-Content -Encoding UTF8 writes a BOM, and gh then shows it (and mangles
# non-ASCII such as the em dash) in the release notes.
[System.IO.File]::WriteAllText((Join-Path $repo "release-notes.md"), ($notes -join "`n") + "`n", (New-Object System.Text.UTF8Encoding($false)))

# --- 10. Publish the GitHub Release (same 4 assets as release.yml) ---------------------------
Step "10/10  publish GitHub Release"
$appJson = Join-Path $repo "backend/config/app.json"
if (-not (Test-Path $appJson)) { $appJson = Join-Path $repo "backend/config/app.example.json" }
$name = (Get-Content $appJson -Raw | ConvertFrom-Json).branding.name
$short = ($name -replace '[^A-Za-z0-9]', ''); if (-not $short) { $short = ($Slug -replace '[^A-Za-z0-9]', '') }
$assets = @("release-build/$Slug-$new.ksupdate", "release-build/$Slug-$new.zip")
if ($runStationOk) {
  $assets += "release-build/run_station.exe"
  $assets += "deploy/Output/$short-Setup-$new.exe"
} else {
  Warn "publishing WITHOUT run_station.exe / setup.exe - first-install stays on deploy/install-station.ps1 until a rebuild fixes it."
}
if ($BuildUpdatePackage) {
  # A 5th, OPTIONAL asset: the offline update-delivery tool. Published here too so an admin on a
  # NETWORKED machine can fetch it from the release and carry it to the air-gapped bench (same
  # reasoning as publishing the offline setup.exe) - it is never itself downloaded BY an
  # air-gapped station.
  $assets += "deploy/Output/$short-Update-$new.exe"
}
foreach ($a in $assets) { if (-not (Test-Path $a)) { throw "missing release asset: $a" } }
if ($DryRun) {
  Warn "DRY RUN - would: gh release create $tag --title $tag --notes-file release-notes.md $($assets -join ' ')"
} else {
  $prevEap = $ErrorActionPreference; $ErrorActionPreference = "Continue"   # PS 5.1: native stderr must not throw
  gh release view $tag 2>&1 | Out-Null
  $releaseExists = ($LASTEXITCODE -eq 0)
  $ErrorActionPreference = $prevEap
  if ($releaseExists) {
    # resume: the release exists from an earlier, interrupted run - replace its assets + notes in place
    Warn "release $tag already exists - updating its assets and notes (resume)"
    gh release upload $tag @assets --clobber
    if ($LASTEXITCODE) { throw "gh release upload failed" }
    gh release edit $tag --notes-file "release-notes.md"
    if ($LASTEXITCODE) { throw "gh release edit failed" }
    Info "updated $tag with $($assets.Count) assets"
  } else {
    gh release create $tag --title $tag --notes-file "release-notes.md" @assets
    if ($LASTEXITCODE) { throw "gh release create failed" }
    Info "released $tag with $($assets.Count) assets"
  }
}
