#requires -Version 5.1
#requires -RunAsAdministrator
<#
.SYNOPSIS
Expose CODEdev in WSL2 NAT mode through a specific Windows IPv4 address.
.EXAMPLE
.\wsl-port-forward.ps1 -WindowsIp 10.20.30.40 -Distro Ubuntu
.EXAMPLE
.\wsl-port-forward.ps1 -WindowsIp 10.20.30.40 -Action Status
.EXAMPLE
.\wsl-port-forward.ps1 -WindowsIp 10.20.30.40 -Action Remove
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$WindowsIp,
    [string]$Distro,
    [ValidateRange(1, 65535)]
    [int]$Port = 8765,
    [ValidateSet('Setup', 'Status', 'Remove')]
    [string]$Action = 'Setup',
    [string]$WslIp
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-IPv4([string]$Value) {
    $parsed = $null
    if (-not [System.Net.IPAddress]::TryParse($Value, [ref]$parsed) -or
        $parsed.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork -or
        [System.Net.IPAddress]::IsLoopback($parsed) -or
        $parsed.Equals([System.Net.IPAddress]::Any) -or
        $parsed.Equals([System.Net.IPAddress]::Broadcast)) {
        throw "Expected a non-loopback IPv4 address, got: $Value"
    }
    return $parsed.IPAddressToString
}

function Test-CodeDev([string]$Address) {
    # Connect directly to WSL/Windows but preserve the browser's public Host.
    # Do not use the corporate HTTP proxy for either local connectivity probe.
    $request = [System.Net.HttpWebRequest]::Create("http://${Address}:$Port/api/bootstrap")
    $request.Host = "${WindowsIp}:$Port"
    $request.Proxy = $null
    $request.AllowAutoRedirect = $false
    $request.Timeout = 5000
    $request.ReadWriteTimeout = 5000
    $response = $null
    try {
        $response = $request.GetResponse()
        if ([int]$response.StatusCode -ne 200) {
            throw "Unexpected HTTP status: $([int]$response.StatusCode)"
        }
        # Bootstrap tokens are deliberately never printed.
    } finally {
        if ($null -ne $response) { $response.Dispose() }
        $request.Abort()
    }
}

$WindowsIp = Get-IPv4 $WindowsIp
$ruleName = "CODEdev-WSL-$WindowsIp-$Port"

if ($Action -eq 'Remove') {
    # Delete only this endpoint and this script's firewall rule.
    & netsh.exe interface portproxy delete v4tov4 "listenaddress=$WindowsIp" "listenport=$Port"
    if ($LASTEXITCODE -ne 0) {
        Write-Warning 'No matching portproxy was removed; check the netsh output above.'
    }
    Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    Write-Host "Removed CODEdev forwarding for ${WindowsIp}:$Port."
    return
}

if (-not (Get-NetIPAddress -AddressFamily IPv4 -IPAddress $WindowsIp -ErrorAction SilentlyContinue)) {
    throw "$WindowsIp is not assigned to this Windows machine. Use the LAN IPv4 shown by ipconfig."
}

if ($Action -eq 'Status') {
    & netsh.exe interface portproxy show v4tov4
    Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue |
        Format-Table Name, Enabled, Profile, Direction, Action
    try {
        Test-CodeDev $WindowsIp
        Write-Host "PASS: http://${WindowsIp}:$Port/api/bootstrap"
    } catch {
        throw "Windows endpoint probe failed: $($_.Exception.Message)"
    }
    Write-Host 'This checks the Windows host path. Test the URL on another corporate PC to check network/GPO access.'
    return
}

if ([string]::IsNullOrWhiteSpace($Distro)) {
    throw 'Setup requires -Distro with the distribution running CODEdev. Use wsl.exe -l -q to list distributions.'
}

if ([string]::IsNullOrWhiteSpace($WslIp)) {
    # Route source selects the actual adapter; hostname -I can return Docker/VPN IPs first.
    $routeJson = & wsl.exe --distribution $Distro --exec ip -j -4 route get $WindowsIp
    if ($LASTEXITCODE -ne 0) {
        throw 'Cannot query the WSL route. Check -Distro, or pass the correct NAT IPv4 with -WslIp.'
    }
    $routes = @((($routeJson -join "`n") | ConvertFrom-Json))
    if ($routes.Count -lt 1 -or -not $routes[0].PSObject.Properties['prefsrc']) {
        throw 'WSL route has no source IPv4. Pass the correct NAT IPv4 explicitly with -WslIp.'
    }
    $WslIp = [string]$routes[0].prefsrc
}
$WslIp = Get-IPv4 $WslIp
if ($WslIp -eq $WindowsIp) {
    throw 'WSL and Windows have the same IP; this script targets NAT mode. Do not create a portproxy loop in mirrored mode.'
}

Write-Host "Checking WSL backend: $WslIp`:$Port (Host: $WindowsIp`:$Port)"
try {
    Test-CodeDev $WslIp
} catch {
    throw "WSL backend probe failed: $($_.Exception.Message). In $Distro run: python3 app.py --host 0.0.0.0 --port $Port --allow-host $WindowsIp"
}

# Portproxy depends on IP Helper. Do not change the service's startup policy.
Start-Service -Name iphlpsvc

# Inspect only numeric data rows, independent of netsh's display language.
$existing = & netsh.exe interface portproxy show v4tov4
if ($LASTEXITCODE -ne 0) { throw 'Cannot read current portproxy rules.' }
$endpointPattern = '^\s*' + [regex]::Escape($WindowsIp) + '\s+' + $Port + '\s+'
$operation = 'add'
if ($existing | Where-Object { $_ -match $endpointPattern }) { $operation = 'set' }
& netsh.exe interface portproxy $operation v4tov4 "listenaddress=$WindowsIp" "listenport=$Port" "connectaddress=$WslIp" "connectport=$Port"
if ($LASTEXITCODE -ne 0) {
    throw 'netsh portproxy setup failed. Check administrator rights and the error above.'
}

# Corporate clients can be in another subnet or use a Domain/Public profile.
# Scope the rule to this one Windows IP and TCP port, not to a guessed subnet/profile.
$firewall = @{
    Name = $ruleName
    DisplayName = "CODEdev WSL ${WindowsIp}:$Port"
    Direction = 'Inbound'
    Action = 'Allow'
    Enabled = 'True'
    Protocol = 'TCP'
    LocalAddress = $WindowsIp
    LocalPort = $Port
    RemoteAddress = 'Any'
    Profile = 'Any'
}
if (Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue) {
    $firewall.NewDisplayName = $firewall.DisplayName
    $firewall.Remove('DisplayName')
    Set-NetFirewallRule @firewall | Out-Null
} else {
    New-NetFirewallRule @firewall | Out-Null
}

try {
    Test-CodeDev $WindowsIp
} catch {
    throw "Forwarding was configured, but the Windows endpoint probe failed: $($_.Exception.Message). Check port conflicts, IP Helper and effective Windows firewall/GPO policy. Settings remain available for Status/Remove."
}
Write-Host "PASS: Windows ${WindowsIp}:$Port -> WSL ${WslIp}:$Port -> CODEdev"
Write-Host "Open: http://${WindowsIp}:$Port"
Write-Host 'Rerun Setup after the WSL NAT IP changes. Verify this URL from another corporate PC as well.'
