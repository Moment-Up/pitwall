<#
.SYNOPSIS
    End-to-end check of a Windows install, no game needed.

.DESCRIPTION
    Starts a temporary Pitwall server through scripts\windows\pitwall.ps1 on spare ports bound to 127.0.0.1, with a new
    temporary data folder and the LLM off, then:
      1. checks that the dashboard is served,
      2. streams the recorded F1 25 capture in tests\fixtures\recorded (a real PS5 race excerpt) to it over UDP with
         'pitwall send' and checks that a session with laps was stored,
      3. streams a SYNTHETIC capture ('pitwall simulate') and checks that its laps were stored and analysed (the lap
         processor's count must grow by 3 or more; -SkipSynthetic skips this step, so analysis is not checked),
      4. checks that the server reported no database or analysis errors,
    and stops the server. Your data, a running Pitwall and the firewall are not touched.

    The synthetic stream only proves that the pipeline runs on this PC: it says nothing about game compatibility.

        powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\smoke.ps1

    Exit code 0 when everything passed, 1 otherwise (the server log is printed on failure).
#>
[CmdletBinding()]
param(
    [int]$HttpPort = 8779,
    [int]$UdpPort = 20779,
    [double]$Speed = 20,
    [int]$TimeoutSec = 90,
    [switch]$SkipSynthetic,
    [switch]$RequireDashboard,
    [switch]$KeepData
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_common.ps1')
Assert-Windows

$root = Get-PitwallRoot
$exe = Get-PitwallExe
if (-not $exe) { Exit-WithError "Pitwall is not installed in $root. Run scripts\windows\install.ps1 first." }
if ($null -ne (Get-PitwallHealth $HttpPort)) { Exit-WithError "Port $HttpPort is already in use: pick another with -HttpPort." }

$work = Join-Path ([System.IO.Path]::GetTempPath()) ('pitwall-smoke-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
$dataDir = Join-Path $work 'data'
$log = Join-Path $work 'server.log'
$base = "http://127.0.0.1:$HttpPort"
$speedText = $Speed.ToString([System.Globalization.CultureInfo]::InvariantCulture)
$recorded = Join-Path $root 'tests\fixtures\recorded\f1_25_2025_ps5_austria_race-excerpt.pwcap'
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null

function Start-SmokeServer {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = (Get-Process -Id $PID).Path  # the PowerShell running this script (5.1 or 7)
    $psi.Arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}" -LogFile "{1}"' -f (Join-Path $PSScriptRoot 'pitwall.ps1'), $log
    $psi.WorkingDirectory = $root
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $vars = @{
        PITWALL_DATA_DIR      = $dataDir
        PITWALL_HTTP_HOST     = '127.0.0.1'
        PITWALL_HTTP_PORT     = [string]$HttpPort
        PITWALL_UDP_BIND      = '127.0.0.1'
        PITWALL_F1_UDP_PORT   = [string]$UdpPort
        PITWALL_LLM_ENABLED   = 'false'
        PITWALL_GT7_ENABLED   = 'false'
        PITWALL_FORZA_ENABLED = 'false'
    }
    foreach ($name in $vars.Keys) { $psi.EnvironmentVariables[$name] = $vars[$name] }  # the child only
    return [System.Diagnostics.Process]::Start($psi)
}

function Stop-SmokeServer($Process) {
    if ($null -eq $Process) { return }
    $ErrorActionPreference = 'Continue'
    if (-not $Process.HasExited) {
        # The whole tree: PowerShell -> cmd.exe -> pitwall.exe -> python.exe
        & taskkill.exe /PID $Process.Id /T /F 2>&1 | Out-Null
        $null = $Process.WaitForExit(15000)
    }
    # Belt and braces: a Python still listening on the smoke test's HTTP port (only ours can: the port was free).
    try {
        foreach ($c in @(Get-NetTCPConnection -LocalPort $HttpPort -State Listen -ErrorAction Stop)) {
            $p = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
            if ($null -ne $p -and [string]$p.ProcessName -match 'python|pitwall') { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
        }
    } catch { }
}

function Get-Sessions {
    try {
        $rows = Invoke-RestMethod -Uri "$base/api/sessions" -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
    } catch {
        return
    }
    if ($null -eq $rows) { return }
    foreach ($r in @($rows | ForEach-Object { $_ })) {
        if ($null -ne $r) { $r }
    }
}

function Wait-Session([scriptblock]$Match, [int]$Seconds = 45) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        foreach ($s in @(Get-Sessions)) {
            if (& $Match $s) { return $s }
        }
        Start-Sleep -Milliseconds 500
    }
    return $null
}

function Send-Capture([string]$Path) {
    $code = Invoke-Native -FilePath $exe -Arguments @('send', $Path, '--host', '127.0.0.1', '--port', [string]$UdpPort, '--speed', $speedText)
    if ($code -ne 0) { throw "pitwall send failed (exit code $code)" }
}

$server = $null
$failed = $true
try {
    Write-Step "Starting a temporary Pitwall server: $base, UDP 127.0.0.1:$UdpPort, data $dataDir"
    $server = Start-SmokeServer
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ($null -eq (Get-PitwallHealth $HttpPort)) {
        if ($server.HasExited) { throw "the server exited during start-up (exit code $($server.ExitCode))" }
        if ((Get-Date) -gt $deadline) { throw "the server did not answer on $base/api/health within $TimeoutSec s" }
        Start-Sleep -Milliseconds 500
    }
    Write-Good 'server is up'

    Write-Step 'Dashboard'
    $page = Invoke-WebRequest -Uri "$base/" -UseBasicParsing -TimeoutSec 15
    $html = [string]$page.Content
    if ($html -match 'has not been built') {
        if ($RequireDashboard) { throw 'GET / says the dashboard has not been built' }
        Write-Note 'the dashboard has not been built (install.ps1 builds it); the API works without it'
    } elseif ([int]$page.StatusCode -eq 200 -and $html -match '<script') {
        Write-Good "GET / serves the dashboard ($($html.Length) characters)"
    } else {
        throw "GET / returned HTTP $($page.StatusCode) without a dashboard page"
    }

    if (Test-Path -LiteralPath $recorded) {
        Write-Step "Streaming the recorded F1 25 capture (PS5, Austria race excerpt) over UDP at ${speedText}x"
        Send-Capture $recorded
        $s = Wait-Session { param($r) (-not [bool]$r.synthetic) -and [string]$r.track_id -eq 'f1:17' -and [int]$r.lap_count -ge 1 }
        if ($null -eq $s) { throw 'no session with laps was stored for the recorded capture' }
        Write-Good ('session {0}: {1} {2} at {3}, {4} laps' -f $s.id, $s.game, $s.session_type, $s.track_name, $s.lap_count)
    } else {
        Write-Note "recorded capture not found ($recorded): skipped"
    }

    if (-not $SkipSynthetic) {
        Write-Step 'Streaming a SYNTHETIC capture (pitwall simulate) to exercise lap analysis'
        $synthetic = Join-Path $work 'synthetic.pwcap'
        $code = Invoke-Native -FilePath $exe -Arguments @('simulate', '--out', $synthetic) -WorkingDirectory $work
        if ($code -ne 0) { throw "pitwall simulate failed (exit code $code)" }
        # Laps of the recorded capture do not count: the synthetic laps must be analysed too. Wait until the lap
        # processor has finished the recorded laps (its count stays the same for 3 s) before taking the baseline.
        $before = -1
        $steady = 0
        $deadline = (Get-Date).AddSeconds(30)
        while ($steady -lt 6 -and (Get-Date) -lt $deadline) {
            $h = Get-PitwallHealth $HttpPort
            $now = -1
            if ($null -ne $h) { $now = [int]$h.laps_processed }
            if ($now -eq $before) { $steady++ } else { $steady = 0; $before = $now }
            Start-Sleep -Milliseconds 500
        }
        if ($before -lt 0) { throw 'the server stopped answering' }
        Send-Capture $synthetic
        $s = Wait-Session { param($r) [bool]$r.synthetic -and [int]$r.lap_count -ge 3 }
        if ($null -eq $s) { throw 'no synthetic session with 3 or more laps was stored' }
        Write-Good ('SYNTHETIC session {0}: {1} laps ({2} clean)' -f $s.id, $s.lap_count, $s.clean_lap_count)
        $want = $before + 3
        $deadline = (Get-Date).AddSeconds(45)
        $processed = $before
        while ((Get-Date) -lt $deadline) {
            $h = Get-PitwallHealth $HttpPort
            if ($null -ne $h) { $processed = [int]$h.laps_processed }
            if ($processed -ge $want) { break }
            Start-Sleep -Milliseconds 500
        }
        if ($processed -lt $want) { throw "the lap processor analysed $($processed - $before) synthetic laps, expected 3 or more" }
        Write-Good "lap analysis ran: $($processed - $before) synthetic laps processed ($processed in all)"
    }

    Write-Step 'Server health'
    $h = Get-PitwallHealth $HttpPort
    if ($null -eq $h) { throw 'the server stopped answering' }
    if ([int]$h.db_writer_errors -ne 0 -or [int]$h.analysis_errors -ne 0) {
        throw "the server reported errors: db_writer_errors=$($h.db_writer_errors) analysis_errors=$($h.analysis_errors)"
    }
    Write-Good "no database or analysis errors; telemetry $($h.connection.status), $($h.connection.packets) packets received"
    $failed = $false
} catch {
    Write-Host ''
    Write-Host "SMOKE TEST FAILED: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host ($_.InvocationInfo.PositionMessage)
    if ($_.ScriptStackTrace) { Write-Host $_.ScriptStackTrace }
} finally {
    Stop-SmokeServer $server
    if ($failed -and (Test-Path -LiteralPath $log)) {
        Write-Host ''
        Write-Host "---- last 150 lines of $log ----"
        Get-Content -LiteralPath $log -Tail 150 -Encoding UTF8 | Out-Host
    }
    if ($failed -or $KeepData) {
        Write-Info "kept $work"
    } else {
        for ($i = 0; $i -lt 10 -and (Test-Path -LiteralPath $work); $i++) {
            Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
            if (Test-Path -LiteralPath $work) { Start-Sleep -Milliseconds 500 }
        }
    }
}

if ($failed) { exit 1 }
if ($SkipSynthetic) {
    Write-Step 'PASS: Pitwall started, served the dashboard and stored laps from UDP telemetry on this PC (lap analysis not checked: -SkipSynthetic).'
} else {
    Write-Step 'PASS: Pitwall started, served the dashboard, stored and analysed laps from UDP telemetry on this PC.'
}
exit 0
