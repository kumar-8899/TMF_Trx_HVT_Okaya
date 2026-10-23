<#
.SYNOPSIS
  Optional Authenticode signing of the release binaries (run.exe, run_station.exe, mosquitto.exe,
  setup.exe). Framework-owned, generic. NEVER touches a machine's security settings.

.DESCRIPTION
  Why: Windows 11 "Smart App Control" (and SmartScreen) block unsigned executables from an unknown
  publisher, with no per-app allow-list. A signed build from a trusted certificate is the supported
  way through (docs/SECURE_DISTRIBUTION.md section 9). Signing is OPTIONAL: with no certificate
  configured this script prints a clear "UNSIGNED" warning and exits 0, so unsigned lab builds keep
  working. With -Required (or TMF_SIGN_REQUIRED=1) a missing certificate is a hard failure.

  Configuration is by ENVIRONMENT ONLY (secrets never go on a command line or in the repo). Pick ONE:
    PFX file          TMF_SIGN_PFX=<path.pfx>   TMF_SIGN_PFX_PASSWORD=<password>
    Cert-store cert   TMF_SIGN_THUMBPRINT=<SHA1 thumbprint of a cert in CurrentUser\My / LocalMachine\My>
    Trusted Signing   TMF_SIGN_TRUSTED_DLIB=<Azure.CodeSigning.Dlib.dll>
                      TMF_SIGN_TRUSTED_METADATA=<metadata.json>   (Microsoft Trusted Signing)
  Optional: TMF_SIGN_TIMESTAMP (RFC 3161 URL, default http://timestamp.digicert.com),
            TMF_SIGNTOOL (path to signtool.exe; otherwise PATH, then the Windows 10/11 SDK).

  Signed files are verified (signtool verify /pa) before the script returns. A file that is missing
  is skipped with a note; a file that fails to sign or verify fails the script.

.EXAMPLE
  $env:TMF_SIGN_PFX = "D:\keys\acme.pfx"; $env:TMF_SIGN_PFX_PASSWORD = "..."
  .\deploy\sign-binaries.ps1 -Paths release-build\run.dist\run.exe, release-build\run_station.exe
#>
param(
  [Parameter(Mandatory = $true)][string[]]$Paths,
  [switch]$Required
)
$ErrorActionPreference = "Stop"
function Info($m) { Write-Host "[sign] $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "[sign] $m" -ForegroundColor Yellow }

if ($env:TMF_SIGN_REQUIRED -eq "1") { $Required = $true }

$mode = $null
if ($env:TMF_SIGN_PFX) { $mode = "pfx" }
elseif ($env:TMF_SIGN_THUMBPRINT) { $mode = "store" }
elseif ($env:TMF_SIGN_TRUSTED_DLIB -and $env:TMF_SIGN_TRUSTED_METADATA) { $mode = "trusted" }

$files = @($Paths | Where-Object { $_ } | ForEach-Object {
  if (Test-Path $_) { (Resolve-Path $_).Path } else { Warn "not found, skipped: $_"; $null }
} | Where-Object { $_ })

if (-not $mode) {
  $msg = "no signing certificate configured (set TMF_SIGN_PFX / TMF_SIGN_THUMBPRINT / TMF_SIGN_TRUSTED_*) - " +
         "$($files.Count) binary(ies) left UNSIGNED. Windows 11 Smart App Control may block them on a client PC; " +
         "see docs/SECURE_DISTRIBUTION.md section 9."
  if ($Required) { throw "signing is REQUIRED but $msg" }
  Warn "UNSIGNED: $msg"
  exit 0
}
if ($files.Count -eq 0) { Warn "nothing to sign"; exit 0 }

function Find-SignTool {
  if ($env:TMF_SIGNTOOL -and (Test-Path $env:TMF_SIGNTOOL)) { return $env:TMF_SIGNTOOL }
  $cmd = Get-Command signtool.exe -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  $kits = @("${env:ProgramFiles(x86)}\Windows Kits\10\bin", "$env:ProgramFiles\Windows Kits\10\bin") |
          Where-Object { $_ -and (Test-Path $_) }
  foreach ($k in $kits) {
    $hit = Get-ChildItem $k -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
           Where-Object { $_.FullName -match "\\x64\\" } | Sort-Object FullName -Descending | Select-Object -First 1
    if ($hit) { return $hit.FullName }
  }
  return $null
}
$signtool = Find-SignTool
if (-not $signtool) { throw "signtool.exe not found - install the Windows SDK (signing tools) or set TMF_SIGNTOOL" }

$ts = if ($env:TMF_SIGN_TIMESTAMP) { $env:TMF_SIGN_TIMESTAMP } else { "http://timestamp.digicert.com" }
$base = @("sign", "/fd", "sha256")
switch ($mode) {
  "pfx"     { $base += @("/f", $env:TMF_SIGN_PFX); if ($env:TMF_SIGN_PFX_PASSWORD) { $base += @("/p", $env:TMF_SIGN_PFX_PASSWORD) } }
  "store"   { $base += @("/sha1", $env:TMF_SIGN_THUMBPRINT) }
  "trusted" { $base += @("/dlib", $env:TMF_SIGN_TRUSTED_DLIB, "/dmdf", $env:TMF_SIGN_TRUSTED_METADATA) }
}
$base += @("/tr", $ts, "/td", "sha256")

Info "signing $($files.Count) file(s) with $mode certificate via $signtool"
foreach ($f in $files) {
  & $signtool @base $f
  if ($LASTEXITCODE -ne 0) { throw "signtool sign failed for $f (exit $LASTEXITCODE)" }
  & $signtool verify /pa /q $f
  if ($LASTEXITCODE -ne 0) { throw "signature on $f did not verify (exit $LASTEXITCODE) - is the certificate chain trusted on this PC?" }
  Info "signed + verified: $f"
}
