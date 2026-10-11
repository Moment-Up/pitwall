<#
.SYNOPSIS
    Install Pitwall on Windows: prerequisites, Python packages, dashboard build and data folder.

.DESCRIPTION
    Run it from the repository folder (or anywhere: it finds the repository from its own location):

        powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\install.ps1

    Prerequisites: git (recommended, for updates), uv (installs Python 3.12 and Pitwall's packages) and Node.js 20.19+
    or 22.12+ (LTS recommended; builds the dashboard). Missing ones can be installed with winget after a y/N prompt.
    Nothing here needs administrator rights, except that the Git and Node.js installers install for all users and
    Windows asks for permission (UAC) while they run.

    Dashboard: the React dashboard (web-react) uses licensed HeroUI Pro components, which only install fully with a
    HeroUI Pro login (npx heroui-pro@latest login) or HEROUI_AUTH_TOKEN. Without either, npm ci still succeeds but the
    build then fails with "Can't resolve '@heroui-pro/react/...'". So 'auto' builds it only when HEROUI_AUTH_TOKEN
    is set (-Dashboard react: when this PC has a HeroUI Pro login). Otherwise the Svelte dashboard (web) is built; the
    server serves it automatically whenever web-react\dist does not exist.

    Data folder: created with private permissions (this account, SYSTEM and Administrators only), because it holds the
    access token and any API keys and a folder outside the user profile (C:\pitwall, another drive) would otherwise
    inherit read access for every account on the PC.

    Release folder (pitwall-<version>.zip unzipped, docs\install.md "Install from a release"; it has RELEASE.txt and
    no .git): the React dashboard comes prebuilt in web-react\dist, so it is used as it is - never rebuilt and never
    deleted - and neither Node.js, npm nor a HeroUI Pro licence is needed (-Dashboard auto or react). git is not
    needed either: updates are new release zips. -Dashboard svelte still builds web\dist with Node.js.

    Running it again is safe: it updates the packages and rebuilds the dashboard (in a git checkout).

.PARAMETER NonInteractive
    Never prompt and never install anything: fail with a clear message when a prerequisite is missing (CI).

.PARAMETER Dashboard
    auto (default): React when HEROUI_AUTH_TOKEN is set, otherwise Svelte. react (needs a HeroUI Pro login or
    HEROUI_AUTH_TOKEN) | svelte | none. In a release folder, auto and react use the prebuilt React dashboard.
#>
[CmdletBinding()]
param(
    [switch]$NonInteractive,
    [ValidateSet('auto', 'react', 'svelte', 'none')]
    [string]$Dashboard = 'auto'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_common.ps1')
Assert-Windows

$root = Get-PitwallRoot
# Vite 7 (web) and Vite 8 (web-react) need Node.js ^20.19 or >= 22.12 (no 21.x); web-react's "engines" asks >= 22.12.
$NodeNeed = '20.19+ (20.x) or 22.12+'
$ReactNode = [version]'22.12.0'
$Run = 'powershell -NoProfile -ExecutionPolicy Bypass -File'

# A release folder (an unzipped pitwall-<version>.zip) has RELEASE.txt and is not a git checkout.
$hasReleaseTxt = Test-Path -LiteralPath (Join-Path $root 'RELEASE.txt') -PathType Leaf
$isGitCheckout = Test-Path -LiteralPath (Join-Path $root '.git')
$IsRelease = $hasReleaseTxt -and (-not $isGitCheckout)

# web-react\dist\index.html built for "/" (npm run build:root): scripts from /assets/, nothing from /next/.
function Test-PrebuiltReactDashboard {
    $index = Join-Path $root 'web-react\dist\index.html'
    if (-not (Test-Path -LiteralPath $index -PathType Leaf)) { return $false }
    $html = [System.IO.File]::ReadAllText($index)
    return (($html -match 'src="/assets/') -and ($html -notmatch '"/next/'))
}

# A release folder's prebuilt React dashboard is used as it is (never rebuilt or deleted): no Node.js needed.
$UsePrebuilt = $false
if ($IsRelease -and ($Dashboard -eq 'auto' -or $Dashboard -eq 'react')) {
    $UsePrebuilt = Test-PrebuiltReactDashboard
}

function Get-ToolVersionText([string]$Command) {
    $ErrorActionPreference = 'Continue'
    $out = & $Command --version
    if ($LASTEXITCODE -ne 0 -or $null -eq $out) { return '' }
    return ([string](@($out)[0])).Trim()
}

function Test-NodeSupported($Version) {
    if ($null -eq $Version) { return $false }
    return (($Version -ge [version]'20.19.0' -and $Version -lt [version]'21.0.0') -or $Version -ge [version]'22.12.0')
}

function Get-NodeVersion {
    if (-not (Get-Command node -ErrorAction SilentlyContinue)) { return $null }
    $text = (Get-ToolVersionText 'node').TrimStart('v')
    $parsed = $null
    if ([version]::TryParse($text, [ref]$parsed)) { return $parsed }
    return $null
}

# winget installers change the user/machine PATH, not this window's: add the new entries to this session.
function Update-SessionPath {
    $current = @($env:Path -split ';' | Where-Object { $_ })
    foreach ($scope in @('Machine', 'User')) {
        $value = [System.Environment]::GetEnvironmentVariable('Path', $scope)
        if (-not $value) { continue }
        foreach ($entry in ($value -split ';')) {
            $expanded = [System.Environment]::ExpandEnvironmentVariables($entry)
            if ($expanded -and ($current -notcontains $expanded)) { $current += $expanded }
        }
    }
    $env:Path = $current -join ';'
}

# Offer to install a missing prerequisite with winget. Returns $true when winget ran.
function Install-Prerequisite([string]$Name, [string]$WingetId, [switch]$AllUsers) {
    if ($NonInteractive) { return $false }
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Write-Note "winget (App Installer) is not available, so $Name cannot be installed from here."
        return $false
    }
    if ($AllUsers) { Write-Info "The $Name installer installs for all users: Windows will ask for administrator permission." }
    if (-not (Read-YesNo "Install $Name now with winget (winget install --id $WingetId -e)?")) { return $false }
    $code = Invoke-Native -FilePath 'winget' -Arguments @('install', '--id', $WingetId, '-e', '--source', 'winget')
    if ($code -ne 0) { Write-Note "winget exited with code $code." }
    Update-SessionPath
    return $true
}

$kind = 'repository'
if ($IsRelease) { $kind = 'release folder' }
Write-Host "Pitwall installer for Windows - ${kind}: $root - PowerShell $($PSVersionTable.PSVersion)"

# ------------------------------------------------------------------------------------------------ prerequisites
Write-Step 'Checking prerequisites'

if (Get-Command git -ErrorAction SilentlyContinue) {
    Write-Good (Get-ToolVersionText 'git')
} elseif ($IsRelease) {
    Write-Info 'git: not needed in a release folder (to update, download the new release).'
} else {
    Write-Note 'git is not installed. Pitwall runs without it, but you need it to update (git pull).'
    $null = Install-Prerequisite 'Git' 'Git.Git' -AllUsers
    if (Get-Command git -ErrorAction SilentlyContinue) {
        Write-Good (Get-ToolVersionText 'git')
    } else {
        Write-Note 'Continuing without git. Get it later from https://git-scm.com/download/win'
    }
}

$uvUrl = 'https://docs.astral.sh/uv/getting-started/installation/'
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Note 'uv is not installed (it installs Python 3.12 and the packages Pitwall needs).'
    $ran = Install-Prerequisite 'uv' 'astral-sh.uv'
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        if ($ran) { Exit-WithError 'uv was installed, but this window cannot see it yet. Open a new PowerShell window and run this script again.' }
        Exit-WithError "uv is required. Install it from $uvUrl (or: winget install --id astral-sh.uv -e), then run this script again."
    }
}
Write-Good (Get-ToolVersionText 'uv')

$nodeVersion = $null
if ($UsePrebuilt) {
    Write-Info 'Node.js: not needed (this release folder has the dashboard prebuilt).'
} elseif ($Dashboard -ne 'none') {
    if ($IsRelease -and ($Dashboard -eq 'auto' -or $Dashboard -eq 'react')) {
        Write-Note "This release folder has no prebuilt dashboard built for / (web-react\dist\index.html): it has to be built, which needs Node.js."
    }
    $nodeVersion = Get-NodeVersion
    if (-not (Test-NodeSupported $nodeVersion)) {
        if ($null -eq $nodeVersion) {
            Write-Note 'Node.js is not installed (it builds the dashboard).'
        } else {
            Write-Note "Node.js $nodeVersion cannot build the dashboard: it needs Node.js $NodeNeed."
        }
        $ran = Install-Prerequisite 'Node.js LTS' 'OpenJS.NodeJS.LTS' -AllUsers
        $nodeVersion = Get-NodeVersion
        if (-not (Test-NodeSupported $nodeVersion)) {
            if ($ran) { Exit-WithError 'Node.js was installed, but this window cannot see it yet. Open a new PowerShell window and run this script again.' }
            Exit-WithError ("Node.js $NodeNeed is required to build the dashboard. Install the LTS version from " +
                'https://nodejs.org/en/download (or: winget install --id OpenJS.NodeJS.LTS -e), then run this script ' +
                'again. To install without a dashboard: -Dashboard none')
        }
    }
    if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
        Exit-WithError 'npm was not found next to Node.js. Reinstall Node.js from https://nodejs.org/en/download.'
    }
    Write-Good "Node.js $nodeVersion"
}

# ------------------------------------------------------------------------------------------------ Python
# Windows cannot replace files a running program uses (.venv\Scripts\pitwall.exe), so a running server is stopped first.
$running = @(Get-PitwallProcesses)
$stoppedServer = $false
if ($running.Count -gt 0) {
    if ((Get-TelemetryStatus (Get-PitwallHttpPort)) -eq 'live') {
        Exit-WithError 'Pitwall is running and telemetry is LIVE (someone is driving). Run this again when the session is over.' 3
    }
    if ($NonInteractive) {
        Write-Note 'Pitwall is running from this folder and telemetry is not live: stopping it so its files can be updated.'
    } elseif (-not (Read-YesNo 'Pitwall is running from this folder. Stop it so its files can be updated?')) {
        Exit-WithError 'Stop Pitwall first (Ctrl+C in its window, or: scripts\windows\service.ps1 stop), then run this again.'
    }
    $null = Stop-PitwallProcesses
    Start-Sleep -Seconds 2
    $stoppedServer = $true
}

Write-Step 'Installing Python 3.12 and the Python packages (uv sync --all-extras)'
$code = Invoke-Native -FilePath 'uv' -Arguments @('sync', '--all-extras') -WorkingDirectory $root
if ($code -ne 0) { Exit-WithError "uv sync failed (exit code $code): see the messages above." }
$exe = Get-PitwallExe
$py = Get-PitwallPython
if (-not $exe -or -not $py) { Exit-WithError "uv sync finished, but $root\.venv\Scripts\pitwall.exe is missing." }
$code = Invoke-Native -FilePath $py -WorkingDirectory $root -Arguments @(
    '-c', 'import pitwall.api.app, pitwall.core.runtime; print(''the server modules import'')')
if ($code -ne 0) { Exit-WithError 'Pitwall is installed but its server does not start on this PC (import error above).' }
Write-Good "$exe"

# ------------------------------------------------------------------------------------------------ dashboard
function Invoke-DashboardBuild([string]$Folder, [string]$Script) {
    $dir = Join-Path $root $Folder
    $c = Invoke-Native -FilePath 'npm.cmd' -Arguments @('ci', '--no-audit', '--no-fund') -WorkingDirectory $dir
    if ($c -eq 0) { $c = Invoke-Native -FilePath 'npm.cmd' -Arguments @('run', $Script) -WorkingDirectory $dir }
    return ($c -eq 0)
}

$mode = $Dashboard
if ($UsePrebuilt) {
    $mode = 'prebuilt'
    Write-Step 'Dashboard: prebuilt in this release (web-react\dist)'
    Write-Good "React dashboard built for /: $root\web-react\dist (used as it is, not rebuilt)"
    if ($Dashboard -eq 'react') { Write-Info '-Dashboard react: a release folder keeps its prebuilt dashboard; it is not rebuilt here.' }
} elseif ($mode -eq 'auto') {
    if (Test-EnvSet 'HEROUI_AUTH_TOKEN') { $mode = 'react' } else { $mode = 'svelte' }
}

if ($mode -eq 'react') {
    Write-Step 'Building the React dashboard (web-react: npm ci, npm run build:root)'
    Write-Info 'npm ci installs the licensed HeroUI Pro components with your HeroUI Pro login or HEROUI_AUTH_TOKEN.'
    if ($nodeVersion -lt $ReactNode) { Write-Note "web-react asks for Node.js $ReactNode or newer; this PC has $nodeVersion." }
    if (Invoke-DashboardBuild 'web-react' 'build:root') {
        Write-Good "React dashboard built: $root\web-react\dist"
    } elseif ($Dashboard -eq 'react') {
        Exit-WithError ('The React dashboard build failed (see npm above). Without a valid HeroUI Pro login or ' +
            "HEROUI_AUTH_TOKEN, npm ci looks fine but the build cannot resolve '@heroui-pro/react/...'. Use -Dashboard svelte.")
    } else {
        Write-Note 'The React dashboard build failed (no valid HeroUI Pro login or token?). Building the Svelte dashboard instead.'
        $mode = 'svelte'
    }
}

if ($mode -eq 'svelte') {
    Write-Step 'Building the Svelte dashboard (web: npm ci, npm run build)'
    if ($Dashboard -ne 'svelte') {
        Write-Info 'HEROUI_AUTH_TOKEN is not set (or the React build failed), so this builds the Svelte dashboard.'
        Write-Info 'The React dashboard (web-react) needs a HeroUI Pro licence: its components only install with a'
        Write-Info 'HeroUI Pro login or HEROUI_AUTH_TOKEN (then run this script with -Dashboard react). Pitwall serves'
        Write-Info 'web\dist whenever web-react\dist has not been built.'
    }
    if (-not (Invoke-DashboardBuild 'web' 'build')) { Exit-WithError 'The Svelte dashboard build failed: see the npm messages above.' }
    Write-Good "Svelte dashboard built: $root\web\dist"
    if ($IsRelease -and (Test-Path -LiteralPath (Join-Path $root 'web-react\dist\index.html'))) {
        Write-Note "This release's prebuilt React dashboard (web-react\dist) is served instead of the Svelte one."
    } elseif (Test-Path -LiteralPath (Join-Path $root 'web-react\dist\index.html')) {
        Write-Note 'web-react\dist from an earlier build exists and is served instead. Delete that folder to use the Svelte dashboard.'
    }
}

if ($mode -eq 'none') {
    if ($IsRelease -and (Test-PrebuiltReactDashboard)) {
        Write-Note "Dashboard not rebuilt (-Dashboard none): this release's prebuilt web-react\dist is served."
    } else {
        Write-Note 'Dashboard not built (-Dashboard none): the API runs; the dashboard page says it is not built.'
    }
}

# ------------------------------------------------------------------------------------------------ data folder
Write-Step 'Data folder'
$dataDir = Get-PitwallDataDir
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
Write-Good "$dataDir (sessions database, captures, settings). To move it: PITWALL_DATA_DIR=<folder> in $root\.env"
# The folder holds the access token and secrets.json (API keys); Windows has no file modes, so its ACL is what keeps
# them private. Outside the user profile it would inherit "Authenticated Users: Modify" / "Users: Read" from the drive
# root. Well-known SIDs keep this independent of the Windows display language; children inherit the new ACL.
$me = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$code = Invoke-Native -FilePath 'icacls.exe' -Arguments @($dataDir, '/inheritance:r', '/grant:r',
    "*$($me.User.Value):(OI)(CI)F", '*S-1-5-18:(OI)(CI)F', '*S-1-5-32-544:(OI)(CI)F', '/Q')
if ($code -eq 0) {
    Write-Good "data folder is private to $($me.Name) (plus SYSTEM and Administrators)"
    if (Test-IsAdmin) { Write-Note "This window runs as administrator: run Pitwall as $($me.Name) too, or it cannot use its data folder." }
} else {
    Write-Note "Could not make $dataDir private (icacls exit code $code): other accounts on this PC may read it. 'uv run pitwall doctor' shows the command."
}

# ------------------------------------------------------------------------------------------------ next steps
$port = Get-PitwallHttpPort
$udp = Get-PitwallSetting 'F1_UDP_PORT' '20777'
$updateHint = 'git pull, then run this installer again.'
if ($IsRelease) { $updateHint = 'download the new release and follow docs\install.md, "From one release to the next".' }
Write-Step "Pitwall is installed. Next steps (run them in the $kind):"
Write-Host @"

  1. Start Pitwall (Ctrl+C stops it):
       $Run scripts\windows\pitwall.ps1
     If Windows asks whether Python may communicate on networks: tick Private networks only and click Allow
     access. Do not click Cancel (that creates firewall rules that block Pitwall).
  2. Dashboard on this PC:  http://127.0.0.1:$port/
  3. Phone or tablet on the same network: print the LAN link with its access token:
       uv run pitwall token
  4. Let the console and your devices reach this PC (once, in PowerShell opened with 'Run as administrator'):
       $Run scripts\windows\firewall.ps1 add
  5. In the game's telemetry settings send UDP to this PC's IP address, port $udp (F1). The dashboard's
     Setup > Connect page lists the settings for each game.
  6. Optional - start Pitwall in the background at every logon (no administrator needed):
       $Run scripts\windows\service.ps1 install

  Check the setup (firewall, ports, voice, AI) with a fix for each problem:  uv run pitwall doctor
  Check this install end to end without a game:  $Run scripts\windows\smoke.ps1
  Updating later: $updateHint
  Status: Windows support is new. The windows CI job tests it on GitHub's windows-latest runner; it is not yet
  validated live with a game on a Windows PC. Spoken questions on the radio need macOS (speech recognition);
  doctor shows the voice options on this PC.
"@
if ($stoppedServer) {
    Write-Note "The running Pitwall server was stopped for the update. Background service? Start it again with: $Run scripts\windows\service.ps1 start"
}
exit 0
