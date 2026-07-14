# new_app.ps1 - interactive customer-application scaffolder (secure distribution P-b2).
#
# Prompts for the app details, clones the framework at a release TAG, wires the git
# remotes (framework = upstream, app = origin), and generates the app-owned files via
# tools/new_app.py (which enables every framework module + a prefixed app module).
# It does NOT push or set secrets - follow the generated APP_SETUP.md for that.
#
# Run:  tools\new_app.bat   (or right-click new_app.ps1 -> Run with PowerShell)

$ErrorActionPreference = "Stop"

function Ask($label, $default) {
    if ($default) { $p = Read-Host "$label [$default]" } else { $p = Read-Host $label }
    if (-not $p -and $default) { return $default }
    if (-not $p) { throw "'$label' is required" }
    return $p
}

try {
    $fwRoot = Split-Path $PSScriptRoot -Parent      # framework repo root (tools/ is under it)

    Write-Host "== Scaffold a customer application from a framework release ==" -ForegroundColor Cyan

    $defaultRemote = ""
    try { $defaultRemote = (git -C $fwRoot remote get-url origin).Trim() } catch {}

    $remote   = Ask "Framework git remote" $defaultRemote
    $tag      = Ask "Framework release tag to fork (e.g. v1.1.0)" ""
    $customer = Ask "Customer / app display name (e.g. Acme EOL)" ""
    $slug     = Ask "Keystation product slug (e.g. exeliq.acme_eol)" ""
    $appRepo  = Ask "App GitHub repo owner/name (e.g. exeliq/app-acme-eol)" ""
    $outDir   = Ask "Output directory for the new app (e.g. ..\App_Acme_EOL)" ""

    if (Test-Path $outDir) { throw "$outDir already exists - choose an empty path" }

    Write-Host "`n[1/3] Cloning framework $tag ..." -ForegroundColor Yellow
    git clone --branch $tag $remote $outDir
    if ($LASTEXITCODE -ne 0) { throw "git clone failed (bad remote or tag?)" }

    Write-Host "[2/3] Wiring remotes (upstream = framework, origin = app) ..." -ForegroundColor Yellow
    Push-Location $outDir
    try {
        git switch -c main | Out-Null               # app's main starts at the tag
        git remote rename origin upstream
        git remote add origin "https://github.com/$appRepo.git"
    } finally { Pop-Location }

    Write-Host "[3/4] Generating app-owned files ..." -ForegroundColor Yellow
    python "$fwRoot\tools\new_app.py" --slug $slug --customer $customer `
        --framework-tag $tag --app-repo $appRepo --out $outDir
    if ($LASTEXITCODE -ne 0) { throw "new_app.py failed" }

    # A clone is SOURCE only - node_modules / the venv are gitignored, so the app
    # can't run until deps are installed (else: "'vite' is not recognized").
    $install = Ask "Install dependencies now so the app runs (npm + pip)? (Y/n)" "Y"
    if ($install -match '^(y|yes)?$') {
        Write-Host "[4/4] Installing dependencies (this takes a minute) ..." -ForegroundColor Yellow
        Push-Location "$outDir\backend"
        try {
            if (Test-Path "instrumentlib") { pip install -e instrumentlib }
            pip install -e ".[dev]"
        } finally { Pop-Location }
        Push-Location "$outDir\frontend"
        try { npm install } finally { Pop-Location }
        if ($LASTEXITCODE -ne 0) { Write-Host "  (npm/pip reported an error - re-run the install manually)" -ForegroundColor Red }
    } else {
        Write-Host "[4/4] Skipped installs. Before running: (backend) pip install -e .[dev]  (frontend) npm install" -ForegroundColor DarkYellow
    }

    Write-Host "`nDone." -ForegroundColor Green
    Write-Host "  Run it:"
    Write-Host "    cd $outDir; .\dev.ps1            # broker + backend + frontend"
    Write-Host "  Ship it (see APP_SETUP.md - secrets + register product):"
    Write-Host "    git add -A; git commit -m 'scaffold $slug from $tag'; git push -u origin main"
    Write-Host "    git tag v1.0.0; git push origin v1.0.0   # app CI builds + signs + publishes"
}
catch {
    Write-Host "`nERROR: $($_.Exception.Message)" -ForegroundColor Red
}
finally {
    Read-Host "`nPress Enter to close"
}
