<#
.SYNOPSIS
    Pitwall one-line installer for Windows (Windows PowerShell 5.1 and PowerShell 7).

.DESCRIPTION
    In PowerShell (not as administrator):

        irm https://github.com/Moment-Up/pitwall/releases/latest/download/install.ps1 | iex

    It installs the latest release into %LOCALAPPDATA%\Pitwall\pitwall-<version>\: it checks the zip's SHA-256 and
    every path in it, installs Python 3.12 and Pitwall's packages with uv (and offers to install uv), then hands
    over to the new version's `pitwall install-finish`, which keeps your sessions in %LOCALAPPDATA%\Pitwall\data
    (private to your account), backs up the database, carries your .env forward and, if you want, starts Pitwall in
    the background at logon. Running it again is safe.

    Options with iex: set them first, e.g. $env:PITWALL_INSTALL_YES='1' (also _VERSION, _HOME, _SERVICE=yes|no,
    _WAIT_IDLE, _PRE='1', _FROM_ZIP). Or run it as a script block:

        & ([scriptblock]::Create((irm https://github.com/Moment-Up/pitwall/releases/latest/download/install.ps1))) -Yes

    Exit codes: 0 ok | 1 error | 2 usage or unsupported | 3 telemetry live (someone is driving) | 4 needs you
    | 5 download verification failed. Run through iex it never closes your window: it reports the code instead.

    SHA-256 from the same release proves the download arrived complete and unchanged, not who made it.
    Guide: docs/install.md, "Install with one command". ASCII only (Windows PowerShell 5.1 reads files without a BOM
    in the ANSI code page).
#>
[CmdletBinding()]
param(
    [switch]$Yes,
    [string]$Version = '',
    [string]$InstallHome = '',
    [ValidateSet('ask', 'yes', 'no')]
    [string]$Service = 'ask',
    [string]$FromZip = '',
    [int]$WaitIdle = 0,
    [switch]$Pre
)

function Install-Pitwall {
    param($Opt)
    Set-StrictMode -Version Latest
    $ErrorActionPreference = 'Stop'

    $Repo = 'Moment-Up/pitwall'
    $TagPattern = '^v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z][0-9A-Za-z.-]*)?$'
    $MinCore = [version]'0.2.0'
    $MinFreeBytes = 2GB

    function Stop-Install([int]$Code, [string]$Message) {
        $script:PwExitCode = $Code
        throw "PITWALL-INSTALL: $Message"
    }
    function Say([string]$Message) { Write-Host $Message }

    # A property of an object from JSON, or $null (Set-StrictMode refuses missing properties).
    function Get-Prop($Object, [string]$Name) {
        if ($null -eq $Object) { return $null }
        $p = $Object.PSObject.Properties[$Name]
        if ($null -eq $p) { return $null }
        return $p.Value
    }

    function Test-Tag([string]$Tag) {
        return ($Tag -cmatch $TagPattern) -and ($Tag -notmatch '[\r\n]')
    }

    # SemVer 2.0: -1, 0 or 1. A pre-release sorts below its release; numeric identifiers compare as numbers.
    function Compare-Tag([string]$A, [string]$B) {
        $a1 = $A.TrimStart('v'); $b1 = $B.TrimStart('v')
        $pa = $a1.IndexOf('-'); $pb = $b1.IndexOf('-')
        $ca = if ($pa -ge 0) { $a1.Substring(0, $pa) } else { $a1 }
        $cb = if ($pb -ge 0) { $b1.Substring(0, $pb) } else { $b1 }
        $ra = if ($pa -ge 0) { $a1.Substring($pa + 1) } else { '' }
        $rb = if ($pb -ge 0) { $b1.Substring($pb + 1) } else { '' }
        $c = ([version]$ca).CompareTo([version]$cb)
        if ($c -ne 0) { return [math]::Sign($c) }
        if ($ra -eq '' -and $rb -eq '') { return 0 }
        if ($ra -eq '') { return 1 }
        if ($rb -eq '') { return -1 }
        $x = $ra.Split('.'); $y = $rb.Split('.')
        for ($i = 0; $i -lt [math]::Min($x.Length, $y.Length); $i++) {
            $nx = $x[$i] -match '^[0-9]+$'; $ny = $y[$i] -match '^[0-9]+$'
            if ($nx -and $ny) { $c = ([decimal]$x[$i]).CompareTo([decimal]$y[$i]) }
            elseif ($nx) { $c = -1 }
            elseif ($ny) { $c = 1 }
            else { $c = [string]::CompareOrdinal($x[$i], $y[$i]) }
            if ($c -ne 0) { return [math]::Sign($c) }
        }
        return [math]::Sign($x.Length - $y.Length)
    }

    # SHA-256 with .NET, not Get-FileHash: Windows PowerShell 5.1 started from PowerShell 7 inherits a PSModulePath
    # that can hide Get-FileHash (a script function that has to be loaded from a module), and .NET is always there.
    function Get-Sha256([string]$Path) {
        $hasher = [Security.Cryptography.SHA256]::Create()
        $stream = [IO.File]::OpenRead($Path)
        try {
            $bytes = $hasher.ComputeHash($stream)
        } finally {
            $stream.Dispose()
            $hasher.Dispose()
        }
        return ([BitConverter]::ToString($bytes) -replace '-', '').ToLowerInvariant()
    }

    function Get-CheckedBase([string]$Name, [string]$Url) {
        if ($Url -match '^https://[^\s/]+') { return $Url.TrimEnd('/') }
        if ($Url -match '^http://(127\.[0-9]+\.[0-9]+\.[0-9]+|localhost|\[::1\])(:[0-9]+)?(/\S*)?$') { return $Url.TrimEnd('/') }
        Stop-Install 2 "$Name must be an https:// URL (or http:// on this computer, for tests)"
    }

    function Test-Interactive {
        try {
            return [Environment]::UserInteractive -and -not [Console]::IsInputRedirected
        } catch {
            return $false
        }
    }

    # 0 yes, 1 no, 2 no terminal to ask in
    function Read-Answer([string]$Question) {
        if ($Opt.Yes) { return 0 }
        if (-not (Test-Interactive)) { return 2 }
        $answer = Read-Host "$Question [y/N]"
        if ($null -ne $answer -and @('y', 'yes') -contains $answer.Trim().ToLowerInvariant()) { return 0 }
        return 1
    }

    function Invoke-Quiet([string]$FilePath, [string[]]$Arguments, [string]$WorkingDirectory) {
        $ErrorActionPreference = 'Continue'
        Push-Location -LiteralPath $WorkingDirectory
        try {
            & $FilePath @Arguments | Out-Host
            return [int]$LASTEXITCODE
        } finally {
            Pop-Location
        }
    }

    function Get-Health([int]$Port) {
        try {
            return Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 2 -UseBasicParsing
        } catch {
            return $null
        }
    }

    function Test-Live([int]$Port) {
        $h = Get-Health $Port
        if ($null -eq $h) { return $false }
        try { return ([string]$h.connection.status -eq 'live') } catch { return $false }
    }

    function Get-DotEnvValue([string]$Path, [string]$Name) {
        if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
        $value = $null
        foreach ($line in [IO.File]::ReadAllLines($Path)) {
            $m = [regex]::Match($line, '^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$')
            if (-not $m.Success -or $m.Groups[1].Value -ne $Name) { continue }
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

    function Update-SessionPath {
        $current = @($env:Path -split ';' | Where-Object { $_ })
        foreach ($scope in @('Machine', 'User')) {
            $value = [Environment]::GetEnvironmentVariable('Path', $scope)
            if (-not $value) { continue }
            foreach ($entry in ($value -split ';')) {
                $expanded = [Environment]::ExpandEnvironmentVariables($entry)
                if ($expanded -and ($current -notcontains $expanded)) { $current += $expanded }
            }
        }
        $env:Path = $current -join ';'
    }

    function Find-Uv {
        $cmd = Get-Command uv -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($cmd) { return $cmd.Path }
        $candidates = @(
            (Join-Path $env:USERPROFILE '.local\bin\uv.exe'),
            (Join-Path $env:USERPROFILE '.cargo\bin\uv.exe')
        )
        if ($env:LOCALAPPDATA) { $candidates += (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links\uv.exe') }
        foreach ($c in $candidates) { if (Test-Path -LiteralPath $c -PathType Leaf) { return $c } }
        return $null
    }

    # ------------------------------------------------------------------------------------------ 1. platform
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
        Stop-Install 2 'install.ps1 is for Windows. On macOS and Linux use install.sh (docs/install.md).'
    }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $isAdmin = (New-Object Security.Principal.WindowsPrincipal($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if ($isAdmin) {
        Say 'NOTE: this window runs as administrator. Pitwall should be installed and run as yourself: open a normal PowerShell window if you can.'
    }
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    } catch {
        Say 'NOTE: could not enable TLS 1.2 for this window.'
    }
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem

    $apiBase = 'https://api.github.com'
    if ($env:PITWALL_RELEASES_API) { $apiBase = Get-CheckedBase 'PITWALL_RELEASES_API' $env:PITWALL_RELEASES_API }
    $downloadBase = "https://github.com/$Repo/releases/download"
    if ($env:PITWALL_RELEASES_DOWNLOAD) { $downloadBase = Get-CheckedBase 'PITWALL_RELEASES_DOWNLOAD' $env:PITWALL_RELEASES_DOWNLOAD }
    # Windows PowerShell 5.1 refuses User-Agent (and may refuse Accept) in -Headers: -UserAgent instead.
    $headers = @{ 'X-GitHub-Api-Version' = '2022-11-28' }
    $userAgent = 'pitwall-install.ps1'

    # ------------------------------------------------------------------------------------------ home
    $homeDir = $Opt.InstallHome
    if (-not $homeDir) { $homeDir = Join-Path $env:LOCALAPPDATA 'Pitwall' }
    $homeDir = [IO.Path]::GetFullPath($homeDir).TrimEnd('\')

    # ------------------------------------------------------------------------------------------ 3. target
    $tag = $null
    $fromZip = $Opt.FromZip
    if ($fromZip) {
        if (-not (Test-Path -LiteralPath $fromZip -PathType Leaf)) { Stop-Install 2 "-FromZip: $fromZip not found" }
        $fromZip = (Resolve-Path -LiteralPath $fromZip).Path
        $name = [IO.Path]::GetFileName($fromZip)
        $t = $name
        if ($t.StartsWith('pitwall-')) { $t = $t.Substring(8) }
        if ($t.EndsWith('.zip')) { $t = $t.Substring(0, $t.Length - 4) }
        if (-not (Test-Tag $t)) { Stop-Install 2 '-FromZip: the file must be named pitwall-<version>.zip' }
        if ($Opt.Version -and $Opt.Version -ne $t) { Stop-Install 2 "-Version $($Opt.Version) does not match $name" }
        $tag = $t
    } elseif ($Opt.Version) {
        if (-not (Test-Tag $Opt.Version)) { Stop-Install 2 '-Version must look like v1.2.3 or v1.2.3-rc.1' }
        $tag = $Opt.Version
    } else {
        Say 'Looking for the latest Pitwall release...'
        # Assigned, not wrapped in @(): Windows PowerShell 5.1 returns a JSON array as one object, which a variable
        # holds as the array itself (PowerShell 7 returns the items); foreach then walks the releases in both.
        $releases = $null
        $fetched = $false
        try {
            $releases = Invoke-RestMethod -Uri "$apiBase/repos/$Repo/releases?per_page=20" -Headers $headers -UserAgent $userAgent -TimeoutSec 60 -UseBasicParsing
            $fetched = $true
        } catch {
            $fetched = $false
        }
        if ($fetched) {
            $best = $null
            foreach ($r in $releases) {
                $t = [string](Get-Prop $r 'tag_name')
                if (-not (Test-Tag $t)) { continue }
                if (Get-Prop $r 'draft') { continue }
                if (((Get-Prop $r 'prerelease') -or $t.Contains('-')) -and -not $Opt.Pre) { continue }
                $assetNames = @(@(Get-Prop $r 'assets') | ForEach-Object { [string](Get-Prop $_ 'name') })
                if (($assetNames -notcontains "pitwall-$t.zip") -or ($assetNames -notcontains "pitwall-$t.zip.sha256")) { continue }
                if ($null -eq $best -or (Compare-Tag $t $best) -gt 0) { $best = $t }
            }
            if ($null -eq $best) { Stop-Install 1 'no published release has a pitwall-<version>.zip yet (try again in a few minutes)' }
            $tag = $best
        } elseif (-not $env:PITWALL_RELEASES_API -and -not $Opt.Pre) {
            # GitHub's API can refuse (rate limit): the releases page redirects /latest to /tag/<version>.
            try {
                $req = [Net.HttpWebRequest]::Create("https://github.com/$Repo/releases/latest")
                $req.AllowAutoRedirect = $false
                $req.UserAgent = $userAgent
                $req.Timeout = 10000
                $resp = $req.GetResponse()
                $loc = [string]$resp.Headers['Location']
                $resp.Close()
                $i = $loc.LastIndexOf('/tag/')
                if ($i -ge 0) { $tag = $loc.Substring($i + 5) }
            } catch {
                $tag = $null
            }
        }
        if (-not $tag) { Stop-Install 1 'could not reach GitHub to find the latest release (check the network, or pass -Version v1.2.3)' }
    }
    if (-not (Test-Tag $tag)) { Stop-Install 1 'could not work out the latest release from GitHub''s answer' }
    Say "Pitwall $tag -> $homeDir"

    # ------------------------------------------------------------------------------------------ 4. minimum, disk
    if (-not $fromZip) {
        $core = $tag.TrimStart('v').Split('-')[0]
        if ([version]$core -lt $MinCore) {
            Stop-Install 2 "$tag is older than the one-line installer (v$MinCore): install $tag by hand: docs/install.md, 'Install from a release'"
        }
    }
    $vdir = Join-Path $homeDir "pitwall-$tag"
    $ready = Join-Path $vdir '.pitwall-ready'
    if (-not (Test-Path -LiteralPath $ready -PathType Leaf)) {
        try {
            $drive = New-Object IO.DriveInfo([IO.Path]::GetPathRoot($homeDir))
            if ($drive.AvailableFreeSpace -lt $MinFreeBytes) { Stop-Install 4 "less than 2 GB free on $($drive.Name): free some space and run this again" }
        } catch {
            if ([string]$_.Exception.Message -like 'PITWALL-INSTALL:*') { throw }
            Say "NOTE: could not read the free space of $homeDir"
        }
    }

    # ------------------------------------------------------------------------------------------ 5. live
    $port = 8770
    $portText = $env:PITWALL_HTTP_PORT
    if (-not $portText) {
        $installJson = Join-Path $homeDir 'install.json'
        if (Test-Path -LiteralPath $installJson -PathType Leaf) {
            try {
                $state = [IO.File]::ReadAllText($installJson) | ConvertFrom-Json
                $cur = [string]$state.current
                if (Test-Tag $cur) { $portText = Get-DotEnvValue (Join-Path $homeDir "pitwall-$cur\.env") 'PITWALL_HTTP_PORT' }
            } catch {
                $portText = $null
            }
        }
    }
    if ($portText -match '^[0-9]{1,5}$') { $port = [int]$portText }
    if (Test-Live $port) {
        if ($Opt.WaitIdle -le 0) {
            Stop-Install 3 "telemetry is live on http://127.0.0.1:$port/ (someone is driving): not installing now. Run this again between sessions, or set PITWALL_INSTALL_WAIT_IDLE=120 to wait up to 2 hours."
        }
        Say "Telemetry is live: waiting up to $($Opt.WaitIdle) min for the session to end..."
        $deadline = (Get-Date).AddMinutes($Opt.WaitIdle)
        $quiet = 0
        while ($quiet -lt 3) {
            if ((Get-Date) -gt $deadline) { Stop-Install 3 "still live after $($Opt.WaitIdle) min: not installing" }
            if (Test-Live $port) { $quiet = 0 } else { $quiet++ }
            if ($quiet -lt 3) { Start-Sleep -Seconds 5 }
        }
    }

    # ------------------------------------------------------------------------------------------ 6. uv
    $uv = Find-Uv
    if (-not $uv) {
        $rc = Read-Answer 'uv (it installs Python 3.12 and Pitwall''s packages) is not installed. Install it now?'
        if ($rc -eq 2) { Stop-Install 4 'uv is not installed and there is no terminal to ask: set $env:PITWALL_INSTALL_YES=''1'', or install uv first (winget install --id astral-sh.uv -e)' }
        if ($rc -ne 0) { Stop-Install 4 'uv is needed: install it (winget install --id astral-sh.uv -e), then run this again' }
        $winget = Get-Command winget -CommandType Application -ErrorAction SilentlyContinue
        if ($winget -and -not $Opt.Yes -and -not $env:PITWALL_INSTALL_UV_URL) {
            Say 'Installing uv with winget (winget install --id astral-sh.uv -e)...'
            $null = Invoke-Quiet 'winget' @('install', '--id', 'astral-sh.uv', '-e', '--source', 'winget') $env:TEMP
        } else {
            $uvUrl = 'https://astral.sh/uv/install.ps1'
            if ($env:PITWALL_INSTALL_UV_URL) { $uvUrl = Get-CheckedBase 'PITWALL_INSTALL_UV_URL' $env:PITWALL_INSTALL_UV_URL }
            Say "Installing uv from $uvUrl ..."
            $oldNoModify = $env:UV_NO_MODIFY_PATH
            $env:UV_NO_MODIFY_PATH = '1'  # no PATH changes; Pitwall calls uv by its full path
            try {
                # In a child Windows PowerShell: an `exit` in the uv installer can never close this window.
                $code = Invoke-Quiet 'powershell' @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', "irm '$uvUrl' | iex") $env:TEMP
                if ($code -ne 0) { Say "NOTE: the uv installer exited with code $code." }
            } finally {
                $env:UV_NO_MODIFY_PATH = $oldNoModify
            }
        }
        Update-SessionPath
        $uv = Find-Uv
        if (-not $uv) { Stop-Install 1 'uv was installed, but this window cannot find it: open a new PowerShell window and run this again' }
    }
    Say "uv: $uv"

    # ------------------------------------------------------------------------------------------ 7. lock
    New-Item -ItemType Directory -Force -Path $homeDir | Out-Null
    $lock = Join-Path $homeDir '.install.lock'
    $script:PwLock = $null
    try {
        New-Item -ItemType Directory -Path $lock -ErrorAction Stop | Out-Null
    } catch {
        $age = (Get-Date) - (Get-Item -LiteralPath $lock).LastWriteTime
        if ($age.TotalHours -lt 2) {
            Stop-Install 4 "another Pitwall install or update is running ($lock exists). If none is, delete that folder and run this again."
        }
        Remove-Item -LiteralPath $lock -Recurse -Force
        New-Item -ItemType Directory -Path $lock -ErrorAction Stop | Out-Null
    }
    $script:PwLock = $lock
    [IO.File]::WriteAllText((Join-Path $lock 'owner'), "install.ps1 $PID`n")

    # ------------------------------------------------------------------------------------------ 8. stage
    $digest = $null
    $staging = $null
    $downloads = $null
    try {
        if (Test-Path -LiteralPath $ready -PathType Leaf) {
            Say "pitwall-$tag is already installed in $homeDir (skipping the download)."
        } else {
            foreach ($old in @(Get-ChildItem -LiteralPath $homeDir -Directory -Filter '.staging-*' -Force -ErrorAction SilentlyContinue)) {
                $hasData = (Test-Path -LiteralPath (Join-Path $old.FullName 'data')) -or @(Get-ChildItem -LiteralPath $old.FullName -Directory -Force | Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'data') }).Count -gt 0
                if (-not $hasData) { Remove-Item -LiteralPath $old.FullName -Recurse -Force }
            }
            if (-not (Test-Path -LiteralPath $vdir)) {
                $zipName = "pitwall-$tag.zip"
                if ($fromZip) {
                    $zip = $fromZip
                    $sha = "$fromZip.sha256"
                } else {
                    $downloads = Join-Path $homeDir 'downloads'
                    New-Item -ItemType Directory -Force -Path $downloads | Out-Null
                    $zip = Join-Path $downloads $zipName
                    $sha = "$zip.sha256"
                    $oldProgress = $ProgressPreference
                    $ProgressPreference = 'SilentlyContinue'
                    try {
                        Say "Downloading $zipName..."
                        Invoke-WebRequest -Uri "$downloadBase/$tag/$zipName.sha256" -OutFile $sha -UseBasicParsing -UserAgent $userAgent
                        Invoke-WebRequest -Uri "$downloadBase/$tag/$zipName" -OutFile $zip -UseBasicParsing -UserAgent $userAgent
                    } catch {
                        Stop-Install 1 "could not download $zipName ($($_.Exception.Message))"
                    } finally {
                        $ProgressPreference = $oldProgress
                    }
                }
                Say 'Checking SHA-256...'
                if (-not (Test-Path -LiteralPath $sha -PathType Leaf)) { Stop-Install 5 "$zipName.sha256 is missing: it must be next to the zip" }
                $parts = @(([IO.File]::ReadAllText($sha)).Trim() -split '\s+')
                if ($parts.Count -ne 2 -or $parts[1].TrimStart('*') -ne $zipName -or $parts[0].Length -ne 64) {
                    Stop-Install 5 "$zipName.sha256 does not name $zipName`: refusing to install it"
                }
                $digest = Get-Sha256 $zip
                if ($digest -ne $parts[0].ToLowerInvariant()) {
                    Stop-Install 5 "SHA-256 mismatch for $zipName`: the download is damaged or is not the release"
                }
                Say 'Checking SHA-256... OK'
                $prefix = "pitwall-$tag/"
                $archive = [IO.Compression.ZipFile]::OpenRead($zip)
                try {
                    $seen = @{}
                    if ($archive.Entries.Count -eq 0) { Stop-Install 5 "$zipName is empty" }
                    foreach ($e in $archive.Entries) {
                        $n = [string]$e.FullName
                        if ($n.StartsWith('/') -or $n.Contains('\') -or $n -match '^[A-Za-z]:') { Stop-Install 5 "unsafe path in the zip (absolute): $n" }
                        if (@($n.Split('/')) -contains '..') { Stop-Install 5 "unsafe path in the zip (..): $n" }
                        if (-not $n.StartsWith($prefix, [StringComparison]::Ordinal)) { Stop-Install 5 "unexpected path in the zip (not under $prefix): $n" }
                        if ($e.PSObject.Properties.Name -contains 'ExternalAttributes') {
                            if (((([int64]$e.ExternalAttributes) -shr 16) -band 0xF000) -eq 0xA000) { Stop-Install 5 "the zip holds a symbolic link: $n" }
                        }
                        $key = $n.TrimEnd('/')
                        if ($seen.ContainsKey($key)) { Stop-Install 5 "duplicate entry in the zip: $n" }
                        $seen[$key] = $true
                    }
                } finally {
                    $archive.Dispose()
                }
                Say 'Unpacking...'
                $staging = Join-Path $homeDir ".staging-$tag-$PID"
                if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
                New-Item -ItemType Directory -Path $staging | Out-Null
                [IO.Compression.ZipFile]::ExtractToDirectory($zip, $staging)
                $unpacked = Join-Path $staging "pitwall-$tag"
                if (-not (Test-Path -LiteralPath (Join-Path $unpacked 'src\pitwall\install\activate.py') -PathType Leaf)) {
                    Stop-Install 2 "$zipName is older than the one-line installer: install it by hand (docs/install.md)"
                }
                if (Test-Path -LiteralPath $vdir) { Stop-Install 1 "$vdir appeared while unpacking: not replacing it" }
                [IO.Directory]::Move($unpacked, $vdir)
                Remove-Item -LiteralPath $staging -Recurse -Force
                $staging = $null
                if ($downloads) {
                    Remove-Item -LiteralPath $zip, $sha -Force -ErrorAction SilentlyContinue
                    if (@(Get-ChildItem -LiteralPath $downloads -Force).Count -eq 0) { Remove-Item -LiteralPath $downloads -Force }
                    $downloads = $null
                }
            } else {
                Say "Resuming the unfinished install in $vdir"
            }

            # ---------------------------------------------------------------------------------- 9. uv sync
            Say "Installing Python and Pitwall's packages (uv sync)..."
            $oldVenv = $env:VIRTUAL_ENV
            $oldProjectEnv = $env:UV_PROJECT_ENVIRONMENT
            Remove-Item Env:VIRTUAL_ENV -ErrorAction SilentlyContinue
            Remove-Item Env:UV_PROJECT_ENVIRONMENT -ErrorAction SilentlyContinue
            try {
                $code = Invoke-Quiet $uv @('sync', '--locked', '--all-extras') $vdir
            } finally {
                if ($null -ne $oldVenv) { $env:VIRTUAL_ENV = $oldVenv }
                if ($null -ne $oldProjectEnv) { $env:UV_PROJECT_ENVIRONMENT = $oldProjectEnv }
            }
            if ($code -ne 0) { Stop-Install 1 "uv sync failed in $vdir (exit code $code, see above). Run this installer again to resume." }
            $py = Join-Path $vdir '.venv\Scripts\python.exe'
            $code = Invoke-Quiet $py @('-c', 'import pitwall.api.app, pitwall.core.runtime') $vdir
            if ($code -ne 0) { Stop-Install 1 "Pitwall is installed in $vdir, but its server does not start on this PC (import error above)" }
            $digestJson = 'null'
            if ($digest) { $digestJson = '"' + $digest + '"' }
            $unix = [int64]([DateTimeOffset]::UtcNow.ToUnixTimeSeconds())
            [IO.File]::WriteAllText($ready, ('{{"tag": "{0}", "sha256": {1}, "unix": {2}}}' -f $tag, $digestJson, $unix) + "`n")
            Say "Installing Python and Pitwall's packages (uv sync)... done"
        }
    } finally {
        if ($staging -and (Test-Path -LiteralPath $staging)) { Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue }
        if ($downloads -and (Test-Path -LiteralPath $downloads)) {
            # our own download: a failed or damaged one is never kept
            Remove-Item -LiteralPath (Join-Path $downloads "pitwall-$tag.zip"), (Join-Path $downloads "pitwall-$tag.zip.sha256") -Force -ErrorAction SilentlyContinue
            if (@(Get-ChildItem -LiteralPath $downloads -Force).Count -eq 0) { Remove-Item -LiteralPath $downloads -Force -ErrorAction SilentlyContinue }
        }
        if ($script:PwLock -and (Test-Path -LiteralPath $script:PwLock)) { Remove-Item -LiteralPath $script:PwLock -Recurse -Force -ErrorAction SilentlyContinue }
        $script:PwLock = $null
    }

    # ------------------------------------------------------------------------------------------ 10. hand over
    $finishArgs = @('install-finish', '--home', $homeDir, '--version-dir', $vdir, '--installer', 'install.ps1')
    if ($Opt.Yes) { $finishArgs += '--yes' }
    if ($Opt.Service -eq 'yes' -or $Opt.Service -eq 'no') { $finishArgs += @('--service', $Opt.Service) }
    if ($Opt.WaitIdle -gt 0) { $finishArgs += @('--wait-idle', [string]$Opt.WaitIdle) }
    $exe = Join-Path $vdir '.venv\Scripts\pitwall.exe'
    # Started directly on this console (not through the pipeline), so its questions are visible and answerable.
    # Paths never end in a backslash here, so plain double quotes are enough for the Windows argument rules.
    $psi = New-Object Diagnostics.ProcessStartInfo
    $psi.FileName = $exe
    $psi.Arguments = (($finishArgs | ForEach-Object { '"' + [string]$_ + '"' }) -join ' ')
    $psi.WorkingDirectory = $vdir
    $psi.UseShellExecute = $false
    $proc = [Diagnostics.Process]::Start($psi)
    $proc.WaitForExit()
    $code = [int]$proc.ExitCode
    $script:PwExitCode = $code
    return $code
}

# ---------------------------------------------------------------------------------------------- entry point
$pwOptions = @{
    Yes         = [bool]$Yes
    Version     = $Version
    InstallHome = $InstallHome
    Service     = $Service
    FromZip     = $FromZip
    WaitIdle    = $WaitIdle
    Pre         = [bool]$Pre
}
if (-not $pwOptions.Yes -and @('1', 'yes', 'true') -contains [string]$env:PITWALL_INSTALL_YES) { $pwOptions.Yes = $true }
if (-not $pwOptions.Version -and $env:PITWALL_INSTALL_VERSION) { $pwOptions.Version = $env:PITWALL_INSTALL_VERSION }
if (-not $pwOptions.InstallHome -and $env:PITWALL_INSTALL_HOME) { $pwOptions.InstallHome = $env:PITWALL_INSTALL_HOME }
if ($pwOptions.Service -eq 'ask' -and @('yes', 'no') -contains [string]$env:PITWALL_INSTALL_SERVICE) { $pwOptions.Service = [string]$env:PITWALL_INSTALL_SERVICE }
if (-not $pwOptions.FromZip -and $env:PITWALL_INSTALL_FROM_ZIP) { $pwOptions.FromZip = $env:PITWALL_INSTALL_FROM_ZIP }
if ($pwOptions.WaitIdle -le 0 -and [string]$env:PITWALL_INSTALL_WAIT_IDLE -match '^[0-9]+$') { $pwOptions.WaitIdle = [int]$env:PITWALL_INSTALL_WAIT_IDLE }
if (-not $pwOptions.Pre -and @('1', 'yes', 'true') -contains [string]$env:PITWALL_INSTALL_PRE) { $pwOptions.Pre = $true }

$script:PwExitCode = 1
$pwCode = 1
try {
    $pwCode = [int](Install-Pitwall $pwOptions | Select-Object -Last 1)
} catch {
    $pwMessage = [string]$_.Exception.Message
    if ($pwMessage.StartsWith('PITWALL-INSTALL: ')) {
        Write-Host ''
        Write-Host ('ERROR: ' + $pwMessage.Substring(17)) -ForegroundColor Red
        $pwCode = [int]$script:PwExitCode
    } else {
        Write-Host ''
        Write-Host "ERROR: $pwMessage" -ForegroundColor Red
        $pwCode = 1
    }
}
$global:LASTEXITCODE = $pwCode
if ($PSCommandPath) {
    exit $pwCode  # run with -File: the exit code is the result
} elseif ($pwCode -ne 0) {
    Write-Host "Pitwall installer stopped with exit code $pwCode (see the message above)." -ForegroundColor Yellow
}
