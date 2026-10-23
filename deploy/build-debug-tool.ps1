<#
.SYNOPSIS
  Build the TMF Debug Tool (repo-root debug_tool/) into release-build-tool\tmf-debug-tool-<version>.zip.
  Framework-owned. NOT part of cut-release.ps1's gate: the tool is released on its own tags (debug-tool-v<version>).

.DESCRIPTION
  Steps: freeze with PyInstaller (onedir) -> add COMPAT.json, the customer-IT note, the wheelhouse (framework support wheel +
  database drivers) and the bundled python.org embeddable interpreter -> sign (deploy\sign-binaries.ps1; unsigned is loudly
  reported) -> run the frozen selftest (deploy\verify-debug-tool.ps1) -> zip + SHA256SUMS.txt.

  Run it on an interactive desktop, like run_station.exe. Prereqs: Python 3.11/3.12 with `pip install -e "backend[dev,debug-tool]"`.

  The bundled interpreter (what lets a client PC with no Python run Python scripts):
    -EmbedZip <file>    the python.org "Windows embeddable package (64-bit)" zip, matching this Python's minor version
    -FetchEmbed         download that zip from python.org (needs internet; set TMF_EMBED_URL to override the URL)
    -EmbedSha256 <hex>  verify the zip against a hash you recorded (strongly recommended for releases)
    -NoEmbed            build without it (the tool then needs a system Python for Python scripts; selftest reports it)
  A release build SHOULD carry the genuine python.org package and a signature. The script prints the SHA-256 of what it bundled.

  Wheelhouse: the framework support wheel (core.services.dbconn) is always built; PyMySQL / pyodbc / SQLAlchemy wheels are
  downloaded with pip for the embeddable's Python (needs internet) unless -SkipWheelhouse.
#>
param(
  [string]$EmbedZip,
  [switch]$FetchEmbed,
  [string]$EmbedSha256,
  [switch]$NoEmbed,
  [switch]$SkipWheelhouse,
  [switch]$SkipVerify,
  [string]$Python = "python"
)
$ErrorActionPreference = "Stop"
function Info($m) { Write-Host "[debug-tool] $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "[debug-tool] $m" -ForegroundColor Yellow }
function Run($exe, [string[]]$argv) {
  & $exe @argv
  if ($LASTEXITCODE -ne 0) { throw "$exe $($argv -join ' ') failed (exit $LASTEXITCODE)" }
}

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$version = (Get-Content (Join-Path $root "debug_tool\VERSION") -Raw).Trim()
$compat = Get-Content (Join-Path $root "debug_tool\COMPAT.json") -Raw | ConvertFrom-Json
if ($compat.tool_version -ne $version) { throw "debug_tool\COMPAT.json tool_version '$($compat.tool_version)' does not match debug_tool\VERSION '$version'" }

$out = Join-Path $root "release-build-tool"
$stage = Join-Path $out "tmf-debug-tool"
$work = Join-Path $out "build"
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
if (Test-Path $work) { Remove-Item $work -Recurse -Force }
New-Item -ItemType Directory -Force $out | Out-Null

# --- 1. freeze --------------------------------------------------------------------------------
Info "freezing debug_tool $version with PyInstaller (onedir)"
$pi = @(
  "-m", "PyInstaller", "--onedir", "--noconfirm", "--clean", "--console",
  "--name", "tmf-debug-tool", "--distpath", $out, "--workpath", $work, "--specpath", $work,
  "--paths", $root, "--paths", (Join-Path $root "backend"),
  "--collect-submodules=debug_tool", "--collect-submodules=debug_server", "--collect-submodules=tmf_debug",
  "--collect-submodules=uvicorn", "--collect-submodules=mcp.server", "--collect-submodules=mcp.client",
  "--collect-submodules=mcp.shared", "--hidden-import=mcp.types", "--exclude-module=mcp.cli", "--exclude-module=typer",
  "--collect-submodules=anyio",
  "--collect-submodules=aiomqtt", "--collect-submodules=starlette", "--collect-submodules=fastapi",
  # pywebview probes every GUI backend with a try/except import, so static analysis would drag in Qt/GTK/Cocoa/CEF: keep only the
  # Windows ones (same set as backend/build_release.py _WEBVIEW_NOFOLLOW for run_station.exe). Its bundled JS stays in.
  "--collect-data=webview", "--copy-metadata=mcp",
  "--exclude-module=webview.platforms.android", "--exclude-module=webview.platforms.cocoa", "--exclude-module=webview.platforms.gtk",
  "--exclude-module=webview.platforms.qt", "--exclude-module=webview.platforms.mshtml", "--exclude-module=webview.platforms.edgehtml",
  "--exclude-module=webview.platforms.cef", "--exclude-module=PyQt5", "--exclude-module=PyQt6", "--exclude-module=PySide2",
  "--exclude-module=PySide6", "--exclude-module=qtpy", "--exclude-module=gi",
  "--hidden-import=core.services.config", "--hidden-import=core.paths", "--hidden-import=core",
  "--add-data", ((Join-Path $root "debug_tool\ui") + ";debug_tool\ui"),
  "--add-data", ((Join-Path $root "debug_tool\VERSION") + ";debug_tool"),
  "--add-data", ((Join-Path $root "debug_tool\COMPAT.json") + ";debug_tool"),
  "--exclude-module=tkinter", "--exclude-module=matplotlib", "--exclude-module=numpy",
  (Join-Path $root "debug_tool\__main__.py")
)
Run $Python $pi
$exe = Join-Path $stage "tmf-debug-tool.exe"
if (-not (Test-Path $exe)) { throw "PyInstaller reported success but $exe was not produced" }

# --- 2. payload beside the exe ------------------------------------------------------------------
Copy-Item (Join-Path $root "debug_tool\COMPAT.json") $stage
Copy-Item (Join-Path $PSScriptRoot "debug-tool-README-FIRST.txt") (Join-Path $stage "README-FIRST.txt")
Set-Content -Path (Join-Path $stage "VERSION.txt") -Value $version -Encoding ASCII

# bundled interpreter
$embedName = $null
if ($NoEmbed) {
  Warn "no bundled interpreter (-NoEmbed): Python scripts will need a Python on the client PC"
} else {
  if (-not $EmbedZip -and $FetchEmbed) {
    $pyVer = (& $Python -c "import platform;print(platform.python_version())").Trim()
    $url = if ($env:TMF_EMBED_URL) { $env:TMF_EMBED_URL } else { "https://www.python.org/ftp/python/$pyVer/python-$pyVer-embed-amd64.zip" }
    $EmbedZip = Join-Path $work "python-embed-download.zip"
    Info "downloading $url"
    Invoke-WebRequest -Uri $url -OutFile $EmbedZip
  }
  if (-not $EmbedZip) { throw "no interpreter to bundle: pass -EmbedZip <python-x.y.z-embed-amd64.zip>, -FetchEmbed, or -NoEmbed" }
  if (-not (Test-Path $EmbedZip)) { throw "embeddable zip not found: $EmbedZip" }
  $sha = (Get-FileHash $EmbedZip -Algorithm SHA256).Hash.ToLower()
  if ($EmbedSha256 -and ($sha -ne $EmbedSha256.ToLower())) { throw "embeddable zip SHA-256 mismatch: got $sha, expected $EmbedSha256" }
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  $zf = [System.IO.Compression.ZipFile]::OpenRead((Resolve-Path $EmbedZip).Path)
  try {
    $dll = $zf.Entries | Where-Object { $_.Name -match '^python3\d+\.dll$' } | Select-Object -First 1
    if (-not $dll -or -not ($zf.Entries | Where-Object { $_.FullName -eq "python.exe" })) { throw "$EmbedZip is not a python.org embeddable package (no python.exe / python3xx.dll at its root)" }
    $embedMinor = $dll.Name -replace '^python3(\d+)\.dll$', '3.$1'
  } finally { $zf.Dispose() }
  $embedName = "python-embed-$embedMinor.zip"
  Copy-Item $EmbedZip (Join-Path $stage $embedName)
  Info "bundled interpreter: $embedName  sha256 $sha"
  if (-not $EmbedSha256) { Warn "record this SHA-256 and pass it as -EmbedSha256 on future builds so a swapped download is caught" }
}

# wheelhouse
$house = Join-Path $stage "wheelhouse"
New-Item -ItemType Directory -Force $house | Out-Null
Run $Python @((Join-Path $root "tools\debug_tool_support_wheel.py"), $house)
if ($SkipWheelhouse) {
  Warn "wheelhouse limited to the framework support wheel (-SkipWheelhouse): scripts will not find SQLAlchemy / PyMySQL / pyodbc"
} elseif ($embedMinor) {
  Info "downloading database-driver wheels for Python $embedMinor (win_amd64)"
  $abi = "cp3" + $embedMinor.Split(".")[1]
  Run $Python @("-m", "pip", "download", "--only-binary=:all:", "--platform", "win_amd64", "--python-version", $embedMinor, "--implementation", "cp",
                "--abi", $abi, "-d", $house, "SQLAlchemy>=2.0", "PyMySQL>=1.1", "pyodbc>=5.0")
} else {
  Warn "no embeddable interpreter, so the driver wheels were not fetched (a system Python needs its own packages)"
}

# --- 3. sign ------------------------------------------------------------------------------------
& (Join-Path $PSScriptRoot "sign-binaries.ps1") -Paths $exe
if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) { throw "signing failed (exit $LASTEXITCODE)" }

# --- 4. verify the FROZEN tool, then package ---------------------------------------------------------
if ($SkipVerify) { Warn "verification skipped (-SkipVerify) - do not publish this build" }
else {
  $verifyArgs = @{ Dist = $stage }
  if ($embedName) { $verifyArgs["RequirePython"] = $true }
  & (Join-Path $PSScriptRoot "verify-debug-tool.ps1") @verifyArgs
  if ($LASTEXITCODE -ne 0) { throw "verify-debug-tool failed - not packaging" }
}
$zip = Join-Path $out "tmf-debug-tool-$version.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path $stage -DestinationPath $zip -CompressionLevel Optimal
$zsha = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
Set-Content -Path (Join-Path $out "SHA256SUMS.txt") -Value "$zsha  tmf-debug-tool-$version.zip" -Encoding ASCII
Info "built $zip  ($([math]::Round((Get-Item $zip).Length / 1MB, 1)) MB)  sha256 $zsha"
Info "publish as release tag debug-tool-v$version with the zip + SHA256SUMS.txt (a manual step: this build is outside the app gate)"
