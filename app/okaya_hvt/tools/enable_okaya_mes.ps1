<#
.SYNOPSIS
  Adds the app-owned `okaya_mes` module (MES (Okaya table) page) to an INSTALLED station's live config.

.DESCRIPTION
  A frozen install never reconciles its live config with newer examples, so a module that did not exist when the
  station was first installed is "not licensed" and not loaded until two files are edited:
    <install>\config\app.json      + a modules[] entry  { id: okaya_mes, variant: default, config: {...} }
    <install>\config\license.json  + entitlements.modules.okaya_mes = true and entitlements.variants.okaya_mes = [default]
  This does exactly that, ADDITIVELY and idempotently (running it twice changes nothing the second time),
  after making a timestamped backup of both files. It never touches anything else.

  Close the station first (the files are read at start-up). Then start it: the sidebar shows "MES (Okaya table)".

  .\enable_okaya_mes.ps1                                  # default install folder
  .\enable_okaya_mes.ps1 -InstallDir "D:\Okaya\Station"   # another folder
  .\enable_okaya_mes.ps1 -WhatIf                          # show what would change, write nothing
#>
param(
  [string]$InstallDir = "C:\Okaya HVT Testbench\OkayaHVTTestbench",
  [switch]$WhatIf
)
$ErrorActionPreference = "Stop"
function Info($m) { Write-Host "[okaya_mes] $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "[okaya_mes] $m" -ForegroundColor Yellow }

$cfgDir = Join-Path $InstallDir "config"
$appPath = Join-Path $cfgDir "app.json"
$licPath = Join-Path $cfgDir "license.json"
foreach ($p in @($appPath, $licPath)) {
  if (-not (Test-Path -LiteralPath $p)) { throw "not found: $p  (is -InstallDir the folder that contains run.dist and config?)" }
}
$running = @(Get-CimInstance Win32_Process -Filter "Name='run.exe' OR Name='run_station.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($InstallDir, [StringComparison]::OrdinalIgnoreCase) })
if ($running.Count -gt 0) { Warn "the station looks RUNNING ($($running.Count) process(es)) - close it, then run this again so the change is picked up." }

function Read-Json($path) { Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json }
function Write-Json($obj, $path) {
  $text = ($obj | ConvertTo-Json -Depth 30)
  [System.IO.File]::WriteAllText($path, $text + "`n", (New-Object System.Text.UTF8Encoding($false)))   # UTF-8, no BOM
}

$changes = @()

# ---- app.json: modules[] ----------------------------------------------------------------------
$app = Read-Json $appPath
$mods = @($app.modules)
if (-not ($mods | Where-Object { $_.id -eq "okaya_mes" })) {
  $entry = [pscustomobject]@{ id = "okaya_mes"; variant = "default";
    config = [pscustomobject]@{ enabled = $false; station_name = "HV Testing" } }
  $out = New-Object System.Collections.ArrayList
  $placed = $false
  foreach ($m in $mods) {
    [void]$out.Add($m)
    if ($m.id -eq "mes") { [void]$out.Add($entry); $placed = $true }       # right after the framework mes module
  }
  if (-not $placed) { [void]$out.Add($entry) }
  $app.modules = $out.ToArray()
  $changes += "app.json: + module okaya_mes (default, OFF until you enable it on the page)"
} else { Info "app.json already lists okaya_mes" }

# ---- license.json: entitlements ---------------------------------------------------------------
$lic = Read-Json $licPath
if (-not $lic.entitlements) { throw "license.json has no 'entitlements' - not a license file this script understands" }
$ent = $lic.entitlements
if (-not $ent.modules) { $ent | Add-Member -NotePropertyName modules -NotePropertyValue ([pscustomobject]@{}) }
if (-not $ent.variants) { $ent | Add-Member -NotePropertyName variants -NotePropertyValue ([pscustomobject]@{}) }
if (-not ($ent.modules.PSObject.Properties.Name -contains "okaya_mes")) {
  $ent.modules | Add-Member -NotePropertyName okaya_mes -NotePropertyValue $true
  $changes += "license.json: + entitlements.modules.okaya_mes = true"
}
if (-not ($ent.variants.PSObject.Properties.Name -contains "okaya_mes")) {
  $ent.variants | Add-Member -NotePropertyName okaya_mes -NotePropertyValue @("default")
  $changes += "license.json: + entitlements.variants.okaya_mes = [default]"
}

if ($changes.Count -eq 0) { Info "nothing to do - the station is already set up for okaya_mes."; return }
$changes | ForEach-Object { Info $_ }
if ($WhatIf) { Warn "-WhatIf: nothing written."; return }

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
Copy-Item -LiteralPath $appPath -Destination "$appPath.bak-$stamp"
Copy-Item -LiteralPath $licPath -Destination "$licPath.bak-$stamp"
Write-Json $app $appPath
Write-Json $lic $licPath
Info "backups: app.json.bak-$stamp, license.json.bak-$stamp (same folder). Start the station: the sidebar now shows 'MES (Okaya table)'."
