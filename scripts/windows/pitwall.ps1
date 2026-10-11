<#
.SYNOPSIS
    Run the Pitwall server (dashboard + game telemetry listener) in this window. Ctrl+C stops it.

.DESCRIPTION
    Runs .venv\Scripts\pitwall.exe serve with the repository as the working directory, so the repository's .env is
    read and the data folder is <repository>\data unless PITWALL_DATA_DIR says otherwise. Install first with
    scripts\windows\install.ps1.

        powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\pitwall.ps1
        powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\pitwall.ps1 -Port 8780 -Verbose

    -Verbose turns on debug logging in the server.

.PARAMETER Port
    HTTP port of the dashboard (default: PITWALL_HTTP_PORT or 8770).

.PARAMETER NoUdp
    Do not listen for game telemetry (dashboard and API only).

.PARAMETER LogFile
    Append the server's output to this file instead of showing it (service.ps1 and smoke.ps1 use this). The window
    stays empty; the server runs without a console window of its own.

.PARAMETER KeepAlive
    With -LogFile: start the server again 10 s after it exits (service.ps1 uses this, like launchd KeepAlive on macOS).
#>
[CmdletBinding()]
param(
    [int]$Port = 0,
    [switch]$NoUdp,
    [string]$LogFile,
    [switch]$KeepAlive
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_common.ps1')
Assert-Windows

$root = Get-PitwallRoot
$exe = Get-PitwallExe
if (-not $exe) {
    Exit-WithError "Pitwall is not installed in $root (no .venv\Scripts\pitwall.exe). Run: powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\install.ps1"
}

$httpPort = Get-PitwallHttpPort
$serveArgs = @('serve')
if ($Port -gt 0) {
    $httpPort = $Port
    $serveArgs += @('--port', [string]$Port)
}
if ($NoUdp) { $serveArgs += '--no-udp' }
if ($PSBoundParameters.ContainsKey('Verbose')) { $serveArgs += '--verbose' }

# Unbuffered output so the log is current (as the macOS launchd agent does), and UTF-8 output: redirected to a file,
# Python would otherwise write the ANSI code page (cp1252) while Write-Log and 'service.ps1 logs' use UTF-8.
# PYTHONIOENCODING only changes stdout/stderr (the console ignores it: Python writes Unicode to a console directly),
# unlike PYTHONUTF8, which also changes how files are opened. Nothing else differs from 'uv run pitwall serve'.
$pythonEnv = @{ PYTHONUNBUFFERED = '1'; PYTHONIOENCODING = 'utf-8:replace' }

$busyMessage = "Something already answers on http://127.0.0.1:$httpPort/ - probably Pitwall itself (the background " +
    'service? scripts\windows\service.ps1 status). Stop it first, or use another -Port.'

# ------------------------------------------------------------------------------------------------ foreground
if (-not $LogFile) {
    if ($null -ne (Get-PitwallHealth $httpPort)) { Exit-WithError $busyMessage }
    $saved = @{}
    foreach ($name in $pythonEnv.Keys) {
        $saved[$name] = [System.Environment]::GetEnvironmentVariable($name)
        [System.Environment]::SetEnvironmentVariable($name, $pythonEnv[$name])
    }
    $code = 0
    Write-Host "Starting Pitwall from $root (Ctrl+C stops it)"
    Push-Location -LiteralPath $root
    try {
        & $exe @serveArgs
        $code = $LASTEXITCODE
    } finally {
        Pop-Location
        foreach ($name in $saved.Keys) { [System.Environment]::SetEnvironmentVariable($name, $saved[$name]) }
    }
    exit $code
}

# ------------------------------------------------------------------------------------------------ background (-LogFile)
$LogFile = [System.IO.Path]::GetFullPath($LogFile)
$logDir = Split-Path -Parent $LogFile
if ($logDir) { New-Item -ItemType Directory -Force -Path $logDir | Out-Null }

function Write-Log([string]$Message) {
    try {
        Add-Content -LiteralPath $LogFile -Value ('---- {0} {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message) -Encoding UTF8
    } catch { }
}

function Move-LogIfLarge([long]$MaxBytes) {
    try {
        $item = Get-Item -LiteralPath $LogFile -ErrorAction Stop
        if ($item.Length -gt $MaxBytes) { Move-Item -LiteralPath $LogFile -Destination ($LogFile + '.1') -Force -ErrorAction Stop }
    } catch { }
}

# cmd.exe appends stdout and stderr to the log (/s: strip the outer quotes, keep the quoted paths).
$cmdArgs = '/d /s /c ""{0}" {1} >> "{2}" 2>&1"' -f $exe, ($serveArgs -join ' '), $LogFile
$code = 0
while ($true) {
    Move-LogIfLarge (10 * 1024 * 1024)
    if ($null -ne (Get-PitwallHealth $httpPort)) {
        Write-Log $busyMessage
        if (-not $KeepAlive) { exit 1 }
        Start-Sleep -Seconds 30
        continue
    }
    Write-Log "starting: pitwall $($serveArgs -join ' ') in $root"
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $env:ComSpec
    $psi.Arguments = $cmdArgs
    $psi.WorkingDirectory = $root
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    foreach ($name in $pythonEnv.Keys) { $psi.EnvironmentVariables[$name] = $pythonEnv[$name] }
    $proc = [System.Diagnostics.Process]::Start($psi)
    $proc.WaitForExit()
    $code = $proc.ExitCode
    Write-Log "pitwall exited with code $code"
    if (-not $KeepAlive) { break }
    Start-Sleep -Seconds 10
}
exit $code
