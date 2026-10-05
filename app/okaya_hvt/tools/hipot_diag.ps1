<#
hipot_diag.ps1 - run on the CLIENT PC to find out why the UT5320R+ hipot will not connect.
Windows PowerShell 5.1, no Python / VISA tools needed. ASCII only on purpose (PS 5.1 reads
BOM-less files as ANSI).

BEFORE RUNNING: fully close the Okaya HVT app (run_station.exe, run.exe), NI MAX / VISA test
panels and any other software that talks to the hipot - it accepts ONE TCP client at a time.

  powershell -ExecutionPolicy Bypass -File .\hipot_diag.ps1
  optional: -Resource "TCPIP0::192.168.30.36::502::SOCKET"  -RunExe "C:\...\run.dist\run.exe"

Everything is written to hipot_diag.txt on the Desktop - send that file back.
It only ever sends *IDN? and the same DISP:PAGE TEST the app itself sends on connect.
#>
param(
    [string]$Resource = "TCPIP0::192.168.30.36::502::SOCKET",
    [string]$RunExe,
    [string]$ExpectedMac = "1E-30-6C-A2-45-5E",   # the BENCH hipot's MAC (seen from the dev PC, 2026-10-05)
    [string]$OutFile = (Join-Path ([Environment]::GetFolderPath("Desktop")) "hipot_diag.txt")
)
$ErrorActionPreference = "Continue"
Start-Transcript -Path $OutFile -Force | Out-Null
function Section($t) { "`n=== $t ===" }   # NOT named H: that is PowerShell's built-in alias for Get-History

$ip = $null; $port = $null
if ($Resource -match '^TCPIP\d*::([^:]+)::(\d+)::SOCKET$') { $ip = $Matches[1]; $port = [int]$Matches[2] }
else { "NOTE: '$Resource' is not a TCPIP...::SOCKET resource - network tests (3) are skipped." }

Section "1. Environment"
"Time                          : $(Get-Date)"
"User / PC / PowerShell        : $env:USERNAME / $env:COMPUTERNAME / $($PSVersionTable.PSVersion)"
"Resource under test           : $Resource"
"PYVISA_LIBRARY (machine)      : [$([Environment]::GetEnvironmentVariable('PYVISA_LIBRARY','Machine'))]"
"PYVISA_LIBRARY (user)         : [$([Environment]::GetEnvironmentVariable('PYVISA_LIBRARY','User'))]"
"PYVISA_LIBRARY (this session) : [$env:PYVISA_LIBRARY]"
$running = @(Get-Process -Name run_station, run, mosquitto, NIMax -ErrorAction SilentlyContinue)
if ($running.Count) {
    "WARNING - these are still running; close them (they may hold the hipot's single TCP session,"
    "and an app started BEFORE 'setx' or restarted with the in-app Relaunch keeps its OLD environment):"
    ($running | Format-Table Id, ProcessName, StartTime -AutoSize | Out-String).TrimEnd()
} else { "No app / NI MAX processes running (good)." }

Section "2. NI-VISA on this PC"
foreach ($f in "visa32.dll", "visa64.dll") {
    $p = Join-Path $env:windir "System32\$f"
    if (Test-Path $p) { "{0,-10}: {1}" -f $f, (Get-Item $p).VersionInfo.FileVersion } else { "{0,-10}: not found" -f $f }
}
$keys = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*', 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
$ni = Get-ItemProperty $keys -ErrorAction SilentlyContinue |
    Where-Object { $_.DisplayName -match 'NI-VISA|VISA Runtime|ENET|Passport' } |
    Select-Object -ExpandProperty DisplayName | Sort-Object -Unique
if ($ni) { "Installed VISA components:"; $ni | ForEach-Object { "  $_" } } else { "No NI-VISA entries in Programs and Features." }

if ($ip) {
    Section "3. Network path to ${ip}:${port}  (VISA not involved)"
    "Local IPv4 addresses:"
    Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike '169.254*' -and $_.IPAddress -ne '127.0.0.1' } |
        ForEach-Object { "  $($_.IPAddress)/$($_.PrefixLength)  ($($_.InterfaceAlias))" }
    $t = Test-NetConnection -ComputerName $ip -Port $port -WarningAction SilentlyContinue
    "Ping succeeded     : $($t.PingSucceeded)"
    "TCP $port reachable : $($t.TcpTestSucceeded)"
    "Used interface     : $($t.InterfaceAlias)   source $($t.SourceAddress.IPAddress)"
    $nb = Get-NetNeighbor -IPAddress $ip -ErrorAction SilentlyContinue |
        Where-Object { $_.LinkLayerAddress -and $_.LinkLayerAddress -ne '00-00-00-00-00-00' } | Select-Object -First 1
    if ($nb) {
        $mac = $nb.LinkLayerAddress.ToUpper()
        if (($mac -replace '[-:]', '') -eq ($ExpectedMac.ToUpper() -replace '[-:]', '')) { $cmp = "MATCHES the bench hipot ($ExpectedMac)" }
        else { $cmp = "DIFFERENT from the bench hipot ($ExpectedMac) - another device may own this IP" }
        "MAC at that IP     : $mac  -> $cmp"
    } else { "MAC at that IP     : none in the ARP cache (nothing answers ARP - wrong IP / subnet / cable?)" }
    "(Reference: the BENCH hipot does NOT answer ping but accepts TCP 502. A ping reply here is itself suspicious.)"
    $sess = @(Get-NetTCPConnection -RemoteAddress $ip -ErrorAction SilentlyContinue)
    if ($sess.Count) {
        "Existing TCP sessions from THIS PC to the hipot:"
        $sess | ForEach-Object {
            $pr = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue
            "  $($_.State)  local port $($_.LocalPort)  owner: $($pr.ProcessName) (PID $($_.OwningProcess))"
        }
    } else { "No existing TCP sessions from this PC to the hipot." }

    $c = New-Object Net.Sockets.TcpClient
    try { $ok = $c.ConnectAsync($ip, $port).Wait(3000) } catch { $ok = $false }
    if (-not $ok -or -not $c.Connected) {
        "Raw socket   : CANNOT connect to ${ip}:${port} (refused / timed out / blocked / port held by another client)."
    } else {
        $s = $c.GetStream(); $s.ReadTimeout = 3000
        $b = [Text.Encoding]::ASCII.GetBytes("*IDN?`n"); $s.Write($b, 0, $b.Length)
        $buf = New-Object byte[] 256
        try { $n = $s.Read($buf, 0, 256); "Raw socket   : *IDN? -> " + [Text.Encoding]::ASCII.GetString($buf, 0, $n).Trim() }
        catch { "Raw socket   : connected but NO reply to *IDN? within 3 s." }
    }
    $c.Close()
}

if (-not $RunExe) {
    $cand = @()
    $cand += Get-Process -Name run_station -ErrorAction SilentlyContinue | ForEach-Object { Join-Path (Split-Path $_.Path) 'run.dist\run.exe' }
    $cand += Get-Process -Name run -ErrorAction SilentlyContinue | ForEach-Object { $_.Path }
    Get-ChildItem C:\ -Directory -ErrorAction SilentlyContinue | ForEach-Object {
        Get-ChildItem $_.FullName -Directory -ErrorAction SilentlyContinue | ForEach-Object { $cand += (Join-Path $_.FullName 'run.dist\run.exe') }
    }
    $RunExe = $cand | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
}

function Test-Backend($title, $lib) {
    Section $title
    if ($lib) { $env:PYVISA_LIBRARY = $lib } else { Remove-Item Env:PYVISA_LIBRARY -ErrorAction SilentlyContinue }
    $cfg = [ordered]@{
        schema_version = 1; broker = @{ host = "127.0.0.1"; port = 9 }
        step_type_packages = @("okaya_hvt_steps"); library_packages = @("instrument_libs")
        stations = @(@{ station = "st1" })
        instruments = @(@{ id = "hipot"; library = "ut5320r"; stations = @("st1"); simulated = $false
                           params = @{ resource = $Resource; timeout_ms = 4000 } })
        simulation = $false
    }
    $cfgPath = Join-Path $env:TEMP "hipot_diag_cfg.json"
    $o = Join-Path $env:TEMP "hipot_diag_out.txt"; $e = Join-Path $env:TEMP "hipot_diag_err.txt"
    ($cfg | ConvertTo-Json -Depth 8) | Set-Content -Path $cfgPath -Encoding ASCII
    $p = Start-Process -FilePath $RunExe -ArgumentList @('--controller', ('"{0}"' -f $cfgPath)) `
        -RedirectStandardOutput $o -RedirectStandardError $e -PassThru -WindowStyle Hidden
    if (-not $p.WaitForExit(20000)) { Stop-Process -Id $p.Id -Force }
    $out = @(Get-Content $o -ErrorAction SilentlyContinue)
    if ($out -match 'instruments:') { $out | Where-Object { $_ -match 'instrument|hipot|VISA|error|warning' } }
    else {
        "Controller did not reach its instruments line - raw output tail:"
        $out | Select-Object -Last 15
        Get-Content $e -ErrorAction SilentlyContinue | Select-Object -Last 15
    }
    Remove-Item $cfgPath, $o, $e -ErrorAction SilentlyContinue
}

if ($RunExe -and (Test-Path $RunExe)) {
    "`nUsing run.exe: $RunExe"
    $saved = $env:PYVISA_LIBRARY
    Test-Backend "4. Real controller, NI-VISA backend (PYVISA_LIBRARY cleared)" $null
    Test-Backend "5. Real controller, pure-Python backend (PYVISA_LIBRARY=@py)" "@py"
    $env:PYVISA_LIBRARY = $saved
} else {
    Section "4/5. Real controller test"
    "run.exe not found automatically - re-run with:  -RunExe ""C:\<install dir>\run.dist\run.exe"""
}

Section "How to read this"
"* 3: 'TCP reachable : False' or raw socket cannot connect -> NETWORK / firewall / device already has a client. Not a VISA problem."
"* 3: 'MAC ... DIFFERENT' (esp. ping works but TCP closed) -> a different device owns this IP: check the hipot's own LAN"
"  settings (IP, subnet, port, LAN enabled) on its front panel, and look for an IP conflict on the client network."
"* 3 OK (raw *IDN? answers) but 4 says 'disconnected' -> NI-VISA on this PC is the problem."
"* 5 says 'connected' -> pure-Python backend works: set PYVISA_LIBRARY=@py (machine level) and FULLY restart the app"
"  (exit run_station.exe from the tray/Task Manager, then start it fresh - the in-app Relaunch keeps the old environment)."
"* 4 and 5 both 'connected' but the app still shows the hipot offline -> resource string / Simulated toggle on"
"  Config -> Instruments, or the app was not fully restarted."
Stop-Transcript | Out-Null
