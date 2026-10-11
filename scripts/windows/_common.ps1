# Shared helpers for the Pitwall Windows scripts. Dot-sourced by install.ps1, pitwall.ps1, service.ps1, firewall.ps1
# and smoke.ps1; not meant to be run on its own. Windows PowerShell 5.1 and PowerShell 7 compatible, ASCII only.
#
# Settings are resolved the way the server resolves them (pydantic-settings in src/pitwall/config.py): a PITWALL_<NAME>
# environment variable wins, then PITWALL_<NAME> in the repository's .env (the server runs with the repository as its
# working directory), then the default.

$PitwallScriptsDir = $PSScriptRoot

function Get-PitwallRoot {
    return (Split-Path -Parent (Split-Path -Parent $PitwallScriptsDir))
}

# ---------------------------------------------------------------------------------------------------- console output
function Write-Step([string]$Message) {
    Write-Host ''
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Info([string]$Message) {
    Write-Host "    $Message"
}

function Write-Good([string]$Message) {
    Write-Host "    OK: $Message" -ForegroundColor Green
}

function Write-Note([string]$Message) {
    Write-Host "    NOTE: $Message" -ForegroundColor Yellow
}

function Exit-WithError([string]$Message, [int]$Code = 1) {
    Write-Host ''
    Write-Host "ERROR: $Message" -ForegroundColor Red
    exit $Code
}

function Assert-Windows {
    if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
        Exit-WithError 'These scripts are for Windows. On macOS use the Makefile and scripts/pitwall-service.sh (README.md).'
    }
}

function Read-YesNo([string]$Question) {
    while ($true) {
        $answer = Read-Host "$Question [y/N]"
        if ($null -eq $answer) { return $false }
        $a = $answer.Trim().ToLowerInvariant()
        if ($a -eq 'y' -or $a -eq 'yes') { return $true }
        if ($a -eq '' -or $a -eq 'n' -or $a -eq 'no') { return $false }
    }
}

function Test-IsAdmin {
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object System.Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Test-EnvSet([string]$Name) {
    return -not [string]::IsNullOrEmpty([System.Environment]::GetEnvironmentVariable($Name))
}

# Run a native program, show its output, return its exit code. Windows PowerShell 5.1 turns a native program's stderr
# into errors when $ErrorActionPreference is 'Stop', so it is relaxed here (function scope only).
function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [string]$WorkingDirectory
    )
    $ErrorActionPreference = 'Continue'
    if ($WorkingDirectory) { Push-Location -LiteralPath $WorkingDirectory }
    try {
        & $FilePath @Arguments | Out-Host
        return [int]$LASTEXITCODE
    } finally {
        if ($WorkingDirectory) { Pop-Location }
    }
}

# ---------------------------------------------------------------------------------------------------- settings
function Get-DotEnvValue([string]$Name) {
    $path = Join-Path (Get-PitwallRoot) '.env'
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $null }
    $value = $null
    foreach ($line in (Get-Content -LiteralPath $path)) {
        $m = [regex]::Match($line, '^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$')
        if (-not $m.Success -or $m.Groups[1].Value -ne $Name) { continue }  # -ne ignores case, like the server
        $raw = $m.Groups[2].Value.Trim()
        if ($raw.Length -ge 2 -and ($raw.StartsWith('"') -or $raw.StartsWith("'"))) {
            $end = $raw.IndexOf($raw.Substring(0, 1), 1)
            if ($end -gt 0) { $raw = $raw.Substring(1, $end - 1) }
        } else {
            $hash = $raw.IndexOf(' #')
            if ($hash -ge 0) { $raw = $raw.Substring(0, $hash).Trim() }
        }
        $value = $raw
    }
    return $value
}

function Get-PitwallSetting([string]$Name, [string]$Default) {
    $envName = 'PITWALL_' + $Name.ToUpperInvariant()
    $value = [System.Environment]::GetEnvironmentVariable($envName)
    if ([string]::IsNullOrEmpty($value)) { $value = Get-DotEnvValue $envName }
    if ([string]::IsNullOrEmpty($value)) { $value = $Default }
    return $value
}

function Get-PitwallHttpPort {
    return [int](Get-PitwallSetting 'HTTP_PORT' '8770')
}

function Get-PitwallDataDir {
    $dir = Get-PitwallSetting 'DATA_DIR' 'data'
    if (-not [System.IO.Path]::IsPathRooted($dir)) { $dir = Join-Path (Get-PitwallRoot) $dir }
    return [System.IO.Path]::GetFullPath($dir)
}

function Get-PitwallExe {
    $exe = Join-Path (Get-PitwallRoot) '.venv\Scripts\pitwall.exe'
    if (Test-Path -LiteralPath $exe -PathType Leaf) { return $exe }
    return $null
}

function Get-PitwallPython {
    $py = Join-Path (Get-PitwallRoot) '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $py -PathType Leaf) { return $py }
    return $null
}

# ---------------------------------------------------------------------------------------------------- server state
function Get-PitwallHealth([int]$Port) {
    try {
        return Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop
    } catch {
        return $null
    }
}

# live | stale | no_data | down (like telemetry_status in scripts/pitwall-service.sh). "live" means a game is streaming
# right now: someone may be on track, and restarting would split their session in two.
function Get-TelemetryStatus([int]$Port) {
    $health = Get-PitwallHealth $Port
    if ($null -eq $health) { return 'down' }
    try { return [string]$health.connection.status } catch { return 'unknown' }
}

function Wait-PitwallHealthy([int]$Port, [int]$TimeoutSec = 60) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if ($null -ne (Get-PitwallHealth $Port)) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

# Processes of THIS installation: the server ('pitwall serve' run from this repository's .venv, including the cmd.exe
# that redirects its log) and the background supervisor (a PowerShell running scripts\windows\pitwall.ps1).
function Get-PitwallProcesses {
    $venv = Join-Path (Get-PitwallRoot) '.venv'
    $runner = Join-Path $PitwallScriptsDir 'pitwall.ps1'
    $found = @()
    foreach ($p in @(Get-CimInstance -ClassName Win32_Process -ErrorAction SilentlyContinue)) {
        $cmd = [string]$p.CommandLine
        if ($cmd -eq '' -or [int]$p.ProcessId -eq $PID) { continue }
        $role = $null
        if ($cmd.IndexOf($runner, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
            $role = 'supervisor'
        } elseif ($cmd.IndexOf($venv, [System.StringComparison]::OrdinalIgnoreCase) -ge 0 -and $cmd -match '\sserve(\s|"|$)') {
            $role = 'server'
        }
        if ($role) { $found += New-Object PSObject -Property @{ Id = [int]$p.ProcessId; Name = [string]$p.Name; Role = $role } }
    }
    return $found
}

# Supervisors first, so none of them starts the server again after it is stopped.
function Stop-PitwallProcesses {
    $procs = @(Get-PitwallProcesses)
    foreach ($role in @('supervisor', 'server')) {
        foreach ($p in $procs) {
            if ($p.Role -eq $role) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
        }
    }
    return $procs.Count
}
