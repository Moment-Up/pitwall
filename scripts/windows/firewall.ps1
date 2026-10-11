<#
.SYNOPSIS
    Windows Firewall rules so your console, phone and tablet can reach Pitwall on this PC (add/remove need admin).

.DESCRIPTION
    add     allow inbound TCP to the dashboard port and UDP to the game telemetry ports
    remove  delete every Pitwall rule
    status  show the Pitwall rules, the network profile and anything that would block Pitwall (no admin needed)

    The rules only apply on networks Windows treats as Private (your home network) and only accept devices on the
    same local subnet: nothing is opened on Public networks or to the internet. Running add again is safe (each rule
    is replaced, never duplicated). Run it again after you switch on another game on the dashboard's Connect page.

    In PowerShell opened with "Run as administrator", in the repository folder:

        powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\firewall.ps1 add
        powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\firewall.ps1 add -Games all
        powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\firewall.ps1 add -Games f1,gt7
        powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\firewall.ps1 status

.PARAMETER Games
    enabled (default): the games switched on in Pitwall's settings (F1 is always on); all: every game Pitwall can
    listen for; or a list of: f1 (UDP 20777), gt7 (33740), forza (5301), record (7576, raw capture of another game).
    Assetto Corsa needs no inbound rule: Pitwall connects to the game itself. Ports changed on the Connect page or
    in .env are used.

.PARAMETER UdpPort
    Extra UDP ports to open, e.g. -UdpPort 20778.

.PARAMETER HttpPort
    Dashboard port (default: PITWALL_HTTP_PORT or 8770).
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('add', 'remove', 'status')]
    [string]$Action,
    [string[]]$Games = @('enabled'),
    [string[]]$UdpPort = @(),
    [int]$HttpPort = 0
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_common.ps1')
Assert-Windows

$Group = 'Pitwall'
$RuleProfile = 'Private'
# Defaults from src/pitwall/integrations.py (SPECS) and config.py, used when Pitwall's own settings cannot be read.
$Known = [ordered]@{
    f1     = @{ Name = 'EA SPORTS F1 25'; Port = 20777 }
    gt7    = @{ Name = 'Gran Turismo 7'; Port = 33740 }
    forza  = @{ Name = 'Forza Motorsport / Forza Horizon (Data Out)'; Port = 5301 }
    record = @{ Name = 'Record another game (raw packets, no analysis)'; Port = 7576 }
}
$Run = 'powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\firewall.ps1'

if ($HttpPort -le 0) { $HttpPort = Get-PitwallHttpPort }

# "-Games f1,gt7" arrives as one string through powershell -File: split it here.
$tokens = @()
foreach ($g in $Games) { $tokens += @(([string]$g).ToLowerInvariant() -split '[,;\s]+' | Where-Object { $_ }) }
$allowed = @('enabled', 'all') + @($Known.Keys)
foreach ($t in $tokens) {
    if ($allowed -notcontains $t) { Exit-WithError "Unknown game '$t'. Use enabled, all, or: $(@($Known.Keys) -join ', ')" }
}
$extraPorts = @()
foreach ($u in $UdpPort) {
    foreach ($part in @(([string]$u) -split '[,;\s]+' | Where-Object { $_ })) {
        $n = 0
        if (-not [int]::TryParse($part, [ref]$n) -or $n -lt 1 -or $n -gt 65535) { Exit-WithError "Not a UDP port: '$part'" }
        $extraPorts += $n
    }
}

# Pitwall's own view of the integrations (environment, .env, data\settings.json), or $null if it cannot be read.
function Get-ConfiguredGames {
    $py = Get-PitwallPython
    if (-not $py) { return $null }
    $ErrorActionPreference = 'Continue'
    Push-Location -LiteralPath (Get-PitwallRoot)
    try {
        $out = & $py -B (Join-Path $PSScriptRoot 'game_ports.py') 2>$null  # -B: no .pyc files (may run as admin)
        $code = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($code -ne 0 -or $null -eq $out) { return $null }
    try {
        $rows = @(($out | Out-String) | ConvertFrom-Json | ForEach-Object { $_ })
    } catch {
        return $null
    }
    return New-Object PSObject -Property @{ Rows = $rows }
}

# UDP port -> names of the games using it
function Get-WantedUdpPorts {
    $configured = Get-ConfiguredGames
    if ($null -eq $configured -and $tokens -contains 'enabled') {
        Write-Note ("Could not read Pitwall's game settings (installed? see install.ps1), so only F1 counts as enabled. " +
            'Name the games with -Games f1,gt7 or use -Games all.')
    }
    $wanted = @{}
    foreach ($key in @($Known.Keys)) {
        $name = $Known[$key].Name
        $port = [int]$Known[$key].Port
        $enabled = ($key -eq 'f1')
        if ($null -ne $configured) {
            $row = @($configured.Rows | Where-Object { $_.key -eq $key }) | Select-Object -First 1
            if ($null -ne $row) {
                $name = [string]$row.name
                $port = [int]$row.port
                $enabled = [bool]$row.enabled
            }
        } elseif ($key -eq 'f1') {
            $port = [int](Get-PitwallSetting 'F1_UDP_PORT' '20777')
        }
        $take = ($tokens -contains 'all') -or ($tokens -contains $key) -or (($tokens -contains 'enabled') -and $enabled)
        if ($take) {
            if (-not $wanted.ContainsKey($port)) { $wanted[$port] = @() }
            $wanted[$port] += $name
        }
    }
    foreach ($p in $extraPorts) {
        if (-not $wanted.ContainsKey($p)) { $wanted[$p] = @('extra port') }
    }
    return $wanted
}

function Get-PitwallRules {
    try {
        $rules = @(Get-NetFirewallRule -Group $Group -ErrorAction Stop)
    } catch {
        if ([string]$_.CategoryInfo.Category -ne 'ObjectNotFound') {
            Write-Note "Could not read the firewall rules ($($_.Exception.Message)). Try PowerShell as administrator."
        }
        $rules = @()
    }
    return @($rules | Where-Object { $_.Name -like 'Pitwall-*' })
}

function Assert-Admin {
    if (-not (Test-IsAdmin)) {
        Exit-WithError ("Changing firewall rules needs administrator rights. Open PowerShell with 'Run as administrator', " +
            "go to $(Get-PitwallRoot) and run:  $Run $Action")
    }
}

# Display names "Pitwall HTTP <port>" / "Pitwall UDP <port>" are what 'pitwall doctor' looks for
# (firewall_rule_names in src/pitwall/doctor.py); the rule's Name is its unique id.
function Set-PitwallRule([string]$Protocol, [int]$Port, [string]$What) {
    $ruleName = "Pitwall-$Protocol-$Port"
    $label = 'UDP'
    if ($Protocol -eq 'TCP') { $label = 'HTTP' }
    $display = "Pitwall $label $Port"
    # Always by exact name: never call Remove-NetFirewallRule without a filter.
    if ($null -ne (Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue)) { Remove-NetFirewallRule -Name $ruleName }
    $null = New-NetFirewallRule -Name $ruleName -DisplayName $display -Group $Group -Direction Inbound -Action Allow `
        -Protocol $Protocol -LocalPort $Port -RemoteAddress LocalSubnet -Profile $RuleProfile -Enabled True `
        -Description "Pitwall $What. Added by scripts\windows\firewall.ps1: devices on the local subnet, Private networks only."
    Write-Good "$display ($What) - inbound from the local subnet, Private networks"
}

function Show-FirewallStatus([hashtable]$Wanted) {
    Write-Step 'Pitwall firewall rules'
    $rules = @(Get-PitwallRules)
    if ($rules.Count -eq 0) { Write-Info 'none' }
    foreach ($r in $rules) {
        $pf = $r | Get-NetFirewallPortFilter
        $af = $r | Get-NetFirewallAddressFilter
        Write-Info ('{0}  enabled={1} profile={2} {3} {4} from {5} - {6}' -f $r.DisplayName, $r.Enabled, $r.Profile,
            $pf.Protocol, (@($pf.LocalPort) -join ','), (@($af.RemoteAddress) -join ','), $r.Description)
    }
    $names = @($rules | ForEach-Object { $_.Name })
    $missing = @()
    if ($names -notcontains "Pitwall-TCP-$HttpPort") { $missing += "TCP $HttpPort (dashboard)" }
    foreach ($p in @($Wanted.Keys | Sort-Object)) {
        if ($names -notcontains "Pitwall-UDP-$p") { $missing += "UDP $p ($(@($Wanted[$p]) -join ', '))" }
    }
    if ($missing.Count -gt 0) { Write-Note "Not opened yet: $($missing -join '; '). Run (as administrator): $Run add" }

    Write-Step 'Network profile (the rules apply to Private networks only)'
    try {
        foreach ($c in @(Get-NetConnectionProfile -ErrorAction Stop)) {
            $line = "'{0}' on {1}: {2}" -f $c.Name, $c.InterfaceAlias, $c.NetworkCategory
            if ([string]$c.NetworkCategory -eq 'Public') {
                Write-Note ("$line. If this is your home network, make it Private: Settings > Network & internet > " +
                    'your connection > Network profile type > Private.')
            } else {
                Write-Info $line
            }
        }
    } catch {
        Write-Note 'Could not read the network profile.'
    }

    # Cancelling Windows' "allow access?" prompt for Python creates inbound BLOCK rules, and block rules beat allow rules.
    # Only rules that apply on Private networks matter: allowing Python on Private networks only also creates a block
    # rule for the Public profile, which is harmless (and wanted) - it is not reported.
    try {
        $blocks = @(Get-NetFirewallRule -Direction Inbound -Action Block -Enabled True -ErrorAction Stop | Where-Object {
                [string]$_.Profile -match 'Private|Any'
            } | Where-Object {
                $app = $_ | Get-NetFirewallApplicationFilter
                [string]$app.Program -match 'python|pitwall'
            })
    } catch {
        $blocks = @()
    }
    foreach ($b in $blocks) {
        $program = [string]($b | Get-NetFirewallApplicationFilter).Program
        $text = "Inbound BLOCK rule '{0}' ({1}) blocks {2}. Block rules win over allow rules: disable or delete it in " +
            "'Windows Defender Firewall with Advanced Security' > Inbound Rules."
        Write-Note ($text -f $b.DisplayName, $b.Profile, $program)
    }
}

switch ($Action) {
    'add' {
        Assert-Admin
        $wanted = Get-WantedUdpPorts
        Write-Step "Adding inbound rules (group '$Group')"
        Set-PitwallRule 'TCP' $HttpPort 'dashboard'
        foreach ($p in @($wanted.Keys | Sort-Object)) {
            Set-PitwallRule 'UDP' $p ('telemetry: ' + (@($wanted[$p]) -join ', '))
        }
        Show-FirewallStatus $wanted
    }
    'remove' {
        Assert-Admin
        $rules = @(Get-PitwallRules)
        foreach ($r in $rules) {
            Remove-NetFirewallRule -Name $r.Name
            Write-Good "removed $($r.DisplayName)"
        }
        if ($rules.Count -eq 0) { Write-Info 'No Pitwall firewall rules to remove.' }
    }
    'status' {
        Show-FirewallStatus (Get-WantedUdpPorts)
    }
}
exit 0
