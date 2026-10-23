"""Air-gapped kits: files an engineer carries to a client PC that has no network path to the developer.

  collect kit   `collect.ps1` + README. Finds the install, makes the diagnostics zip (using `tmf-debug-tool.exe` if it sits
                beside it, else the app's own `run.exe --debug-export`, else a manual gather), and fills in the `system/*`
                facts itself for app builds older than v1.32 whose export lacks them. One zip out.
  script kit    the developer's own script wrapped with a runner that captures stdout/stderr/exit code/timing into
                `script/output.txt` + `script/result.json` and zips it. The engineer READS the script before running it -
                that reading is the human-in-the-loop for this mode.

`tmf_debug.bundle.analyze` ingests either result (the `script/` layout is its contract). Nothing here sends anything anywhere.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

INTERPRETERS = ("powershell", "cmd", "python")
_EXT = {"powershell": ".ps1", "cmd": ".cmd", "python": ".py"}

COLLECT_PS1 = r'''<#
  TMF diagnostics collector (for a PC with no network path to the developer).
  READ-ONLY: it never changes the app and never sends anything. It writes ONE zip - send that file to the developer.

  Usage:  powershell -ExecutionPolicy Bypass -File .\collect.ps1 [-StateDir <folder that contains run.dist>] [-OutDir <folder>] [-NoIntegrity]
#>
param([string]$StateDir = "", [string]$OutDir = "", [switch]$NoIntegrity)
$ErrorActionPreference = "Continue"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
if (-not $OutDir) { $OutDir = [Environment]::GetFolderPath("Desktop") }
if (-not (Test-Path $OutDir)) { $OutDir = (Get-Location).Path }
$zip = Join-Path $OutDir ("tmf-debug-" + $env:COMPUTERNAME + "-" + $stamp + ".zip")

function Find-Install {
    if ($StateDir) { return $StateDir }
    foreach ($p in (Get-Process -Name run -ErrorAction SilentlyContinue)) {
        $exe = $null
        try { $exe = $p.Path } catch { }
        if ($exe -and (Test-Path (Join-Path (Split-Path $exe) "RELEASE.json"))) { return (Split-Path (Split-Path $exe)) }
    }
    foreach ($c in @($PSScriptRoot, (Split-Path $PSScriptRoot), (Split-Path (Split-Path $PSScriptRoot)))) {
        if ($c -and (Test-Path (Join-Path $c "run.dist\RELEASE.json"))) { return $c }
    }
    return $null
}

function Add-ZipText([string]$ZipPath, [string]$Name, [string]$Text) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $z = [System.IO.Compression.ZipFile]::Open($ZipPath, "Update")
    try {
        if ($z.GetEntry($Name)) { return }
        $e = $z.CreateEntry($Name)
        $w = New-Object System.IO.StreamWriter($e.Open(), (New-Object System.Text.UTF8Encoding($false)))
        $w.Write($Text)
        $w.Dispose()
    } finally { $z.Dispose() }
}

function Has-ZipEntry([string]$ZipPath, [string]$Name) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $z = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)
    try { return [bool]$z.GetEntry($Name) } finally { $z.Dispose() }
}

$root = Find-Install
if (-not $root) {
    Write-Host "Could not find the app install. Re-run with:  -StateDir <the folder that contains run.dist>" -ForegroundColor Red
    exit 2
}
Write-Host "Install folder: $root"

$tool = Join-Path $PSScriptRoot "tmf-debug-tool.exe"
$run = Join-Path $root "run.dist\run.exe"
$flags = @()
if ($NoIntegrity) { $flags += "--no-integrity" }
if (Test-Path $tool) {
    Write-Host "Using tmf-debug-tool.exe"
    & $tool collect $zip --state-dir $root @flags
} elseif (Test-Path $run) {
    Write-Host "Using the app's own exporter (run.exe --debug-export)"
    & $run --debug-export $zip --state-dir $root @flags
} else {
    Write-Host "No exporter found - packing the raw files instead" -ForegroundColor Yellow
    $tmp = Join-Path $env:TEMP ("tmf-collect-" + $stamp)
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    foreach ($f in @("data\launcher.log", "run.dist\RELEASE.json")) {
        if (Test-Path (Join-Path $root $f)) { Copy-Item (Join-Path $root $f) $tmp -Force }
    }
    if (Test-Path (Join-Path $root "data\debug")) { Copy-Item (Join-Path $root "data\debug") (Join-Path $tmp "debug") -Recurse -Force }
    Compress-Archive -Path (Join-Path $tmp "*") -DestinationPath $zip -Force
    Remove-Item $tmp -Recurse -Force
}
if (-not (Test-Path $zip)) { Write-Host "The export did not produce a zip." -ForegroundColor Red; exit 3 }

# Builds older than v1.32 do not collect the system facts - gather them here (same file names/shape the analyser reads).
if (-not (Has-ZipEntry $zip "system/processes.json")) {
    $procs = @()
    foreach ($p in (Get-CimInstance Win32_Process | Where-Object { $_.Name -match "run|python|mosquitto|controller|LabVIEW|tmf" })) {
        $procs += @{ pid = $p.ProcessId; ppid = $p.ParentProcessId; name = $p.Name; exe = $p.ExecutablePath; cmdline = ("" + $p.CommandLine).Substring(0, [Math]::Min(400, ("" + $p.CommandLine).Length)) }
    }
    Add-ZipText $zip "system/processes.json" (@{ processes = $procs } | ConvertTo-Json -Depth 5 -Compress)
    $ports = @{}
    foreach ($port in 8000, 1883, 8001, 8010, 5173) {
        $c = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($c) {
            $pr = $procs | Where-Object { $_.pid -eq $c.OwningProcess } | Select-Object -First 1
            $ports["$port"] = @{ listening = $true; pid = $c.OwningProcess; name = $pr.name; cmdline = $pr.cmdline }
        } else { $ports["$port"] = @{ listening = $false } }
    }
    Add-ZipText $zip "system/ports.json" (@{ ports = $ports } | ConvertTo-Json -Depth 5 -Compress)
    $drv = @()
    try { $drv = @(Get-OdbcDriver | Where-Object { $_.Name -match "SQL Server" } | ForEach-Object { $_.Name }) } catch { }
    Add-ZipText $zip "system/odbc.json" (@{ drivers = $drv } | ConvertTo-Json -Compress)
    $health = @{ app_running = $false }
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8000/readyz" -TimeoutSec 3
        $health = @{ app_running = $true; readyz = @{ status = $r.StatusCode; body = ($r.Content | ConvertFrom-Json) } }
    } catch { $health.note = "could not reach http://127.0.0.1:8000/readyz: $($_.Exception.Message)" }
    Add-ZipText $zip "system/health.json" ($health | ConvertTo-Json -Depth 6 -Compress)
    Write-Host "Added system facts (older app build)."
}

Write-Host ""
Write-Host "DONE. Send this ONE file to the developer:" -ForegroundColor Green
Write-Host "  $zip"
'''

SCRIPT_RUNNER_PS1 = r'''<#
  TMF script runner. Runs the developer's script ONCE, captures what it prints, and writes ONE zip to send back.
  READ the script file first - this runs it with your Windows account's rights.

  Usage:  powershell -ExecutionPolicy Bypass -File .\run-script.ps1 [-OutDir <folder>] [-Python <path to python.exe>]
#>
param([string]$OutDir = "", [string]$Python = "")
$ErrorActionPreference = "Continue"
$meta = Get-Content (Join-Path $PSScriptRoot "kit.json") -Raw | ConvertFrom-Json
$script = Join-Path $PSScriptRoot $meta.script
if (-not $OutDir) { $OutDir = [Environment]::GetFolderPath("Desktop") }
if (-not (Test-Path $OutDir)) { $OutDir = (Get-Location).Path }
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$work = Join-Path $env:TEMP ("tmf-script-" + $stamp)
$sdir = Join-Path $work "script"
New-Item -ItemType Directory -Force -Path $sdir | Out-Null

$actual = (Get-FileHash $script -Algorithm SHA256).Hash.ToLower()
if ($actual -ne $meta.sha256) {
    Write-Host "The script file changed since the developer made this kit (sha256 mismatch). Not running it." -ForegroundColor Red
    exit 4
}
Write-Host "About to run: $($meta.script)  (sha256 $($actual.Substring(0,12))...)  interpreter: $($meta.interpreter)  timeout: $($meta.timeout_s)s"

function Q([string]$x) { if ($x -match "\s") { return '"' + $x + '"' } else { return $x } }
$exe = "powershell.exe"; $argv = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Q $script))
if ($meta.interpreter -eq "cmd") { $exe = "cmd.exe"; $argv = @("/c", ('"' + (Q $script) + '"')) }
if ($meta.interpreter -eq "python") {
    if (-not $Python) { $cmd = Get-Command python -ErrorAction SilentlyContinue; if ($cmd) { $Python = $cmd.Source } }
    if (-not $Python) { Write-Host "No python.exe found. Re-run with -Python <path>." -ForegroundColor Red; exit 5 }
    $exe = $Python; $argv = @((Q $script))
}
foreach ($a in $meta.args) { $argv += (Q ([string]$a)) }

$out = Join-Path $sdir "stdout.txt"; $err = Join-Path $sdir "stderr.txt"
$t0 = Get-Date
$p = Start-Process -FilePath $exe -ArgumentList $argv -WorkingDirectory $PSScriptRoot -NoNewWindow -PassThru -RedirectStandardOutput $out -RedirectStandardError $err
$null = $p.Handle      # keep the handle so ExitCode is populated
$timedOut = $false
if (-not $p.WaitForExit([int]$meta.timeout_s * 1000)) {
    $timedOut = $true
    & taskkill.exe /PID $p.Id /T /F | Out-Null
}
$elapsed = [Math]::Round(((Get-Date) - $t0).TotalSeconds, 2)
if (-not $timedOut) { $p.WaitForExit() }
$code = if ($timedOut) { -1 } else { $p.ExitCode }

$text = ""
if (Test-Path $out) { $text += "--- stdout ---`r`n" + (Get-Content $out -Raw) }
if ((Test-Path $err) -and (Get-Item $err).Length -gt 0) { $text += "`r`n--- stderr ---`r`n" + (Get-Content $err -Raw) }
if ($text.Length -gt 262144) { $text = $text.Substring($text.Length - 262144) }
[IO.File]::WriteAllText((Join-Path $sdir "output.txt"), $text, (New-Object System.Text.UTF8Encoding($false)))
Remove-Item $out, $err -Force -ErrorAction SilentlyContinue
Copy-Item $script $sdir -Force
$result = @{ exit_code = $code; timed_out = $timedOut; elapsed_s = $elapsed; script = $meta.script; sha256 = $actual;
             interpreter = $meta.interpreter; host = $env:COMPUTERNAME; user = $env:USERNAME; ran_at = $t0.ToString("s") }
[IO.File]::WriteAllText((Join-Path $sdir "result.json"), ($result | ConvertTo-Json -Compress), (New-Object System.Text.UTF8Encoding($false)))

$zip = Join-Path $OutDir ("tmf-script-" + $env:COMPUTERNAME + "-" + $stamp + ".zip")
Compress-Archive -Path $sdir -DestinationPath $zip -Force
Remove-Item $work -Recurse -Force
Write-Host ""
Write-Host "DONE (exit code $code, $elapsed s). Send this ONE file to the developer:" -ForegroundColor Green
Write-Host "  $zip"
'''

COLLECT_README = """TMF diagnostics collector
=========================

What this does: collects the app's recent diagnostics (flight-recorder files, error/action logs, launcher log, REDACTED
configuration, running processes, which program holds the broker port, installed ODBC drivers, app health, install
integrity) into ONE zip. It only reads; it changes nothing on this PC and sends nothing anywhere.

Steps
  1. Open PowerShell on the bench PC (as the same Windows user that runs the app).
  2. powershell -ExecutionPolicy Bypass -File .\\collect.ps1
     (if it cannot find the install:  -StateDir "D:\\path\\that\\contains\\run.dist")
  3. Send the ONE zip it prints at the end to the developer.

The zip can contain operator names and serial numbers. Passwords, tokens and database credentials are redacted. Delete the
zip after the case is closed; do not post it in public issue trackers.
"""

SCRIPT_README = """TMF script kit
==============

The developer wants to run ONE script on this PC to find a fault. The script is the file named below. READ IT FIRST: it runs
with your Windows account's rights. If you do not understand or do not agree with something in it, do not run it - tell the
developer.

Steps
  1. Open PowerShell in this folder.
  2. powershell -ExecutionPolicy Bypass -File .\\run-script.ps1     (python scripts: add  -Python "C:\\path\\to\\python.exe")
  3. Send the ONE zip it prints at the end to the developer.

It runs the script once (timeout and arguments are in kit.json), records what it prints and its exit code, and zips that.
Nothing is sent anywhere by this kit.
"""


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8"))      # PowerShell/cmd files: CRLF


def collect_kit(out_dir: Path | str) -> dict:
    out = Path(out_dir)
    _write(out / "collect.ps1", COLLECT_PS1)
    _write(out / "README.txt", COLLECT_README)
    return {"folder": str(out), "files": ["collect.ps1", "README.txt"],
            "next": "copy the folder to the client PC, run collect.ps1, bring back the ONE zip, then `tmf-debug-tool analyze <zip>`"}


def script_kit(script: str, interpreter: str, out_dir: Path | str, *, timeout_s: int = 60, args: list[str] | None = None,
               name: str | None = None) -> dict:
    if interpreter not in INTERPRETERS:
        raise ValueError(f"interpreter must be one of {INTERPRETERS}")
    if not script.strip():
        raise ValueError("the script is empty")
    timeout_s = max(1, min(int(timeout_s), 300))
    out = Path(out_dir)
    fname = (name or f"script-{time.strftime('%H%M%S')}") + _EXT[interpreter]
    if any(ch in fname for ch in '\\/:*?"<>|'):
        raise ValueError("script name contains characters Windows does not allow in file names")
    body = script.replace("\r\n", "\n").replace("\n", "\r\n")
    (out).mkdir(parents=True, exist_ok=True)
    (out / fname).write_bytes(body.encode("utf-8"))
    sha = hashlib.sha256((out / fname).read_bytes()).hexdigest()
    kit = {"script": fname, "interpreter": interpreter, "timeout_s": timeout_s, "args": list(args or []), "sha256": sha}
    (out / "kit.json").write_text(json.dumps(kit, indent=2), encoding="utf-8", newline="\n")
    _write(out / "run-script.ps1", SCRIPT_RUNNER_PS1)
    _write(out / "README.txt", SCRIPT_README + f"\nThe script: {fname}  (sha256 {sha})\n")
    return {"folder": str(out), "files": [fname, "kit.json", "run-script.ps1", "README.txt"], "sha256": sha,
            "next": "give the folder to the engineer, tell them to READ the script then run run-script.ps1, bring back the ONE zip, "
                    "then `tmf-debug-tool analyze <zip>`"}
