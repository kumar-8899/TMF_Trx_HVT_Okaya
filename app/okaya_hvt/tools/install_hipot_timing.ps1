<#
.SYNOPSIS
  Seeds the operator-editable hipot timing file into an INSTALLED station's live config.

.DESCRIPTION
  The hipot step's relay/HV settle times are read from <install>\config\hipot_timing.json — a plain
  file you hand-edit (NOT the UI, NOT a recipe, one global set for all models). It survives app
  updates (config/ is preserved). This copies the example into place with the measured/optimized
  values, WITHOUT overwriting a file you have already edited (idempotent). A missing file just means
  the app uses its built-in safe defaults (off_margin_s 4.0 / settle_off_s 2.0 / settle_s 1.0 /
  verify_settle_s 0.15 -> 0.3), so this is optional: you can also create the file by hand.

  Edit the file any time and re-run a test; the new values apply on the next run (no restart needed).

  .\install_hipot_timing.ps1                                  # default install folder
  .\install_hipot_timing.ps1 -InstallDir "D:\Okaya\Station"   # another folder
  .\install_hipot_timing.ps1 -Force                           # overwrite an existing file with the example
#>
param(
  [string]$InstallDir = "C:\Okaya HVT Testbench\OkayaHVTTestbench",
  [switch]$Force
)
$ErrorActionPreference = "Stop"
function Info($m) { Write-Host "[hipot_timing] $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "[hipot_timing] $m" -ForegroundColor Yellow }

$cfgDir = Join-Path $InstallDir "config"
if (-not (Test-Path -LiteralPath $cfgDir)) { throw "config folder not found: $cfgDir  (is -InstallDir the folder that contains run.dist and config?)" }
$dest = Join-Path $cfgDir "hipot_timing.json"
$example = Join-Path $PSScriptRoot "..\config\hipot_timing.example.json"
if (-not (Test-Path -LiteralPath $example)) { throw "example not found: $example" }

if ((Test-Path -LiteralPath $dest) -and -not $Force) {
  Warn "already present (left untouched): $dest  — edit it directly, or pass -Force to reset it to the example."
  return
}
Copy-Item -LiteralPath $example -Destination $dest -Force
Info "wrote $dest"
Info "edit it to tune the hipot timing; changes apply on the next run (no restart)."
