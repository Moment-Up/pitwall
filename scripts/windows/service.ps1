<#
.SYNOPSIS
    Run Pitwall in the background on Windows: a Task Scheduler task that starts it at logon (current user, no admin).

.DESCRIPTION
    install    register the "Pitwall" task (starts at logon with a hidden window, starts the server again if it
               exits) and start it now (-NoStart: register only)
    uninstall  stop Pitwall and remove the task
    start      start the task now
    stop       stop the task and the server
    restart    stop and start (after an update, for example)
    status     task state, server processes and health check
    logs       print the end of the server log and follow it (Ctrl+C stops following; -NoFollow just prints)

    stop, restart and uninstall refuse while telemetry is live (someone is driving: stopping would end their session
    and split it in two), exit code 3, unless -Force. The same rule as scripts/pitwall-service.sh on macOS.
    Stopping ends the server at once (Stop-Process; there is no clean shutdown like launchd's SIGTERM): the open
    capture loses its last unflushed packets, queued database writes are lost and the session is not closed.

    Log: %LOCALAPPDATA%\pitwall\logs\server.log. The server runs from this repository with its .env and data folder.

        powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\service.ps1 install

    At logon a PowerShell window may flash for a moment before it hides itself.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('install', 'uninstall', 'start', 'stop', 'restart', 'status', 'logs')]
    [string]$Action,
    [switch]$Force,
    [switch]$NoStart,
    [switch]$NoFollow,
    [int]$Lines = 100
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_common.ps1')
Assert-Windows

$TaskName = 'Pitwall'
$TaskPath = '\'
$root = Get-PitwallRoot
$port = Get-PitwallHttpPort
$logDir = Join-Path $env:LOCALAPPDATA 'pitwall\logs'
$logFile = Join-Path $logDir 'server.log'
$runner = Join-Path $PSScriptRoot 'pitwall.ps1'
# The task always uses Windows PowerShell 5.1, which every Windows 10/11 PC has.
$windowsPowerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$Run = 'powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\service.ps1'

function Get-PitwallTask {
    return Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -ErrorAction SilentlyContinue
}

function Assert-NotLive([string]$What) {
    if ($Force) { return }
    if ((Get-TelemetryStatus $port) -eq 'live') {
        Write-Host "Telemetry is LIVE (someone is driving): not going to $What. Try again after the session, or add -Force." -ForegroundColor Yellow
        exit 3
    }
}

function Stop-PitwallService {
    $task = Get-PitwallTask
    if ($null -ne $task -and [string]$task.State -eq 'Running') {
        Stop-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath
    }
    $stopped = Stop-PitwallProcesses
    $deadline = (Get-Date).AddSeconds(15)
    while ((Get-Date) -lt $deadline -and $null -ne (Get-PitwallHealth $port)) { Start-Sleep -Milliseconds 500 }
    if ($null -ne (Get-PitwallHealth $port)) {
        Write-Note "Something still answers on http://127.0.0.1:$port/ (a Pitwall started from another folder?)."
    } elseif ($stopped -gt 0) {
        Write-Good 'Pitwall stopped'
    }
}

function Start-PitwallService {
    if ($null -eq (Get-PitwallTask)) { Exit-WithError "The '$TaskName' task is not installed. Run: $Run install" }
    if ($null -ne (Get-PitwallHealth $port)) {
        Write-Good "Pitwall is already running: http://127.0.0.1:$port/"
        return
    }
    Start-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath
    # The first start after an install or update takes longer (Python compiles its modules; antivirus scans them).
    if (Wait-PitwallHealthy $port 90) {
        Write-Good "Pitwall is up: http://127.0.0.1:$port/"
    } else {
        Exit-WithError "Pitwall did not answer on http://127.0.0.1:$port/ within 90 s. Look at the log: $Run logs"
    }
}

function Install-PitwallService {
    if (-not (Get-PitwallExe)) {
        Exit-WithError "Pitwall is not installed in $root. Run: powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\install.ps1"
    }
    Assert-NotLive 'replace the running Pitwall'
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    # A server started by hand would hold the ports (the macOS script stops it the same way).
    Stop-PitwallService
    if ($null -ne (Get-PitwallTask)) { Unregister-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -Confirm:$false }

    $user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}" -LogFile "{1}" -KeepAlive' -f $runner, $logFile
    $taskAction = New-ScheduledTaskAction -Execute $windowsPowerShell -Argument $arguments -WorkingDirectory $root
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
    # No 72-hour limit, keep running on battery, normal priority (Task Scheduler's default 7 is below normal), one
    # instance. pitwall.ps1 -KeepAlive restarts the server itself; RestartCount covers PowerShell failing to start.
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([System.TimeSpan]::Zero) -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -Priority 4 -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 1)
    try {
        $null = Register-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -Action $taskAction -Trigger $trigger `
            -Principal $principal -Settings $settings `
            -Description "Pitwall sim racing coach: runs $runner at logon. Manage with scripts\windows\service.ps1."
    } catch {
        Exit-WithError ("Windows did not let this account register the task: $($_.Exception.Message) " +
            'Some managed PCs block this; try PowerShell opened with Run as administrator, or start Pitwall by hand ' +
            'with scripts\windows\pitwall.ps1.')
    }
    Write-Good "Task '$TaskName' registered for $user (starts at logon). Log: $logFile"
    if ($NoStart) {
        Write-Info "Not started (-NoStart). Start it with: $Run start"
    } else {
        Start-PitwallService
    }
}

function Show-Status {
    $task = Get-PitwallTask
    if ($null -ne $task) {
        $info = Get-ScheduledTaskInfo -TaskName $TaskName -TaskPath $TaskPath
        Write-Host ('task:       {0} ({1}); last run {2}, last result 0x{3:X}' -f $TaskName, $task.State, $info.LastRunTime, $info.LastTaskResult)
    } else {
        Write-Host "task:       not installed ($Run install)"
    }
    $procs = @(Get-PitwallProcesses)
    if ($procs.Count -gt 0) {
        Write-Host ('processes:  {0}' -f (($procs | ForEach-Object { '{0} {1} ({2})' -f $_.Name, $_.Id, $_.Role }) -join ', '))
    } else {
        Write-Host 'processes:  none from this folder'
    }
    $health = Get-PitwallHealth $port
    if ($null -ne $health) {
        Write-Host "health:     OK on http://127.0.0.1:$port/ - telemetry: $(Get-TelemetryStatus $port)"
    } else {
        Write-Host "health:     not responding on http://127.0.0.1:$port/"
    }
    Write-Host "log:        $logFile"
}

switch ($Action) {
    'install' {
        Install-PitwallService
    }
    'uninstall' {
        if ($null -eq (Get-PitwallTask)) {
            Write-Info "The '$TaskName' task is not installed."
        } else {
            Assert-NotLive 'stop Pitwall'
            Stop-PitwallService
            Unregister-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -Confirm:$false
            Write-Good "Task '$TaskName' removed (the data folder and the log are kept)."
        }
    }
    'start' {
        Start-PitwallService
    }
    'stop' {
        Assert-NotLive 'stop Pitwall'
        Stop-PitwallService
    }
    'restart' {
        if ($null -eq (Get-PitwallTask)) { Exit-WithError "The '$TaskName' task is not installed. Run: $Run install" }
        Assert-NotLive 'restart Pitwall'
        Stop-PitwallService
        Start-PitwallService
    }
    'status' {
        Show-Status
    }
    'logs' {
        if (-not (Test-Path -LiteralPath $logFile)) { Exit-WithError "No log yet: $logFile (the task has not run)." }
        if ($NoFollow) {
            Get-Content -LiteralPath $logFile -Tail $Lines -Encoding UTF8
        } else {
            Write-Host "$logFile (Ctrl+C stops following)"
            Get-Content -LiteralPath $logFile -Tail $Lines -Encoding UTF8 -Wait
        }
    }
}
exit 0
