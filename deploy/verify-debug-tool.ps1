<#
.SYNOPSIS
  Gate for the BUILT Debug Tool: run the frozen tmf-debug-tool.exe's own `selftest` and check the package layout.
  Called by build-debug-tool.ps1; can be run by hand against an unzipped release (and on a client PC as a readiness check).

.DESCRIPTION
  The selftest starts the tool on a private port against a throwaway fake install and drives it like Claude Code and the operator
  would: sharing off by default, token, MCP handshake, passive tool, an action that blocks until approved, deny, timeout,
  PowerShell and Python scripts after approval, bundle + analyze, Stop. Exit 0 = pass.
#>
param(
  [string]$Dist = "release-build-tool\tmf-debug-tool",
  [switch]$RequirePython,
  [switch]$RequireSigned,
  [int]$TimeoutSec = 240
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$dist = (Resolve-Path $Dist).Path
$exe = Join-Path $dist "tmf-debug-tool.exe"
$failures = New-Object System.Collections.Generic.List[string]
function Fail($m) { Write-Host "  FAIL  $m" -ForegroundColor Red; $failures.Add($m) }
function Pass($m) { Write-Host "  ok    $m" -ForegroundColor Green }

if (-not (Test-Path $exe)) { throw "verify-debug-tool: $exe not found - build first" }

# layout
foreach ($f in @("COMPAT.json", "README-FIRST.txt", "VERSION.txt")) {
  if (Test-Path (Join-Path $dist $f)) { Pass "$f present" } else { Fail "$f missing from the package" }
}
$wh = Join-Path $dist "wheelhouse"
if (Get-ChildItem $wh -Filter "tmf_support-*.whl" -ErrorAction SilentlyContinue) { Pass "wheelhouse carries the framework support wheel" } else { Fail "wheelhouse\tmf_support-*.whl missing" }
$embed = Get-ChildItem $dist -Filter "python-embed*.zip" -ErrorAction SilentlyContinue
if ($embed) { Pass "bundled interpreter: $($embed[0].Name)" } elseif ($RequirePython) { Fail "no python-embed*.zip in the package" } else { Write-Host "  note  no bundled interpreter (Python scripts need a system Python)" -ForegroundColor Yellow }

# version agrees with COMPAT.json and the source of truth
$ver = (Get-Content (Join-Path $dist "VERSION.txt") -Raw).Trim()
$compat = Get-Content (Join-Path $dist "COMPAT.json") -Raw | ConvertFrom-Json
if ($compat.tool_version -eq $ver) { Pass "COMPAT.json tool_version = $ver" } else { Fail "COMPAT.json tool_version '$($compat.tool_version)' != VERSION '$ver'" }
$reported = (& $exe --version) -join " "
if ($reported -match [regex]::Escape($ver)) { Pass "exe reports '$reported'" } else { Fail "exe reports '$reported', expected version $ver" }

# signature
$sig = Get-AuthenticodeSignature $exe
if ($sig.Status -eq "Valid") { Pass "signed: $($sig.SignerCertificate.Subject)" }
elseif ($RequireSigned) { Fail "exe is not validly signed ($($sig.Status))" }
else { Write-Host "  note  UNSIGNED ($($sig.Status)) - Windows Smart App Control may block it on a client PC" -ForegroundColor Yellow }

# the selftest itself (the frozen exe drives everything above the layout checks)
$selfArgs = @("selftest", "--json")
if ($RequirePython) { $selfArgs += "--require-python" }
$tmpOut = Join-Path $env:TEMP ("tmf-selftest-" + [guid]::NewGuid().ToString("N") + ".json")
$p = Start-Process -FilePath $exe -ArgumentList $selfArgs -NoNewWindow -PassThru -RedirectStandardOutput $tmpOut -RedirectStandardError ($tmpOut + ".err")
if (-not $p.WaitForExit($TimeoutSec * 1000)) { & taskkill.exe /PID $p.Id /T /F | Out-Null; Fail "selftest did not finish in $TimeoutSec s" }
else {
  $raw = Get-Content $tmpOut -Raw -ErrorAction SilentlyContinue
  try { $res = $raw | ConvertFrom-Json } catch { $res = $null }
  if (-not $res) { Fail "selftest produced no JSON: $raw $(Get-Content ($tmpOut + '.err') -Raw -ErrorAction SilentlyContinue)" }
  else {
    foreach ($s in $res.steps) {
      $line = "{0,-26} {1}" -f $s.name, $s.detail
      if ($s.status -eq "fail") { Fail $line } elseif ($s.status -eq "pass") { Pass $line } else { Write-Host "  $($s.status.PadRight(5)) $line" -ForegroundColor DarkGray }
    }
    if (-not $res.ok) { Fail "selftest reported failures" }
  }
}
Remove-Item $tmpOut, ($tmpOut + ".err") -Force -ErrorAction SilentlyContinue

if ($failures.Count -gt 0) { Write-Host "`nverify-debug-tool: $($failures.Count) failure(s)" -ForegroundColor Red; exit 1 }
Write-Host "`nverify-debug-tool: PASS ($ver)" -ForegroundColor Green
exit 0
