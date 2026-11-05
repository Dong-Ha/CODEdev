# Run with: pwsh -NoProfile -File tests/test_wsl_port_forward.ps1
# Windows network commands are mocked: these tests never change the host network.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$source = Get-Content (Join-Path $PSScriptRoot '../scripts/wsl-port-forward.ps1') -Raw
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
$probe = $ast.Find({ param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Test-CodeDev'
}, $true)
$mockProbe = @'
function Test-CodeDev([string]$Address) {
    $global:fixture.Probes.Add($Address)
    if ($Address -eq $global:fixture.FailAddress) { throw 'simulated unreachable backend' }
}
'@
# Replace only the platform I/O probe, and drop the admin directive for this test.
$source = $source.Remove($probe.Extent.StartOffset, $probe.Extent.EndOffset - $probe.Extent.StartOffset).Insert($probe.Extent.StartOffset, $mockProbe)
$subject = [scriptblock]::Create(($source -replace '(?m)^#requires -RunAsAdministrator\r?\n', ''))

function Assert([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw "FAIL: $Message" }
}
function Reset-Fixture {
    $global:fixture = @{
        WindowsIp = '10.20.30.40'; WslIp = '172.20.10.2'; FailAddress = ''
        Existing = $false; Firewall = $null; Rule = $null
        NativeCalls = [System.Collections.Generic.List[string]]::new()
        Probes = [System.Collections.Generic.List[string]]::new()
        Services = [System.Collections.Generic.List[string]]::new()
    }
}
function global:Get-NetIPAddress { param($AddressFamily, $IPAddress, $ErrorAction)
    if ($IPAddress -eq $global:fixture.WindowsIp) { [pscustomobject]@{ IPAddress = $IPAddress } }
}
function global:wsl.exe { param([Parameter(ValueFromRemainingArguments = $true)][string[]]$NativeArgs)
    $global:LASTEXITCODE = 0
    '[{"prefsrc":"' + $global:fixture.WslIp + '"}]'
}
function global:netsh.exe { param([Parameter(ValueFromRemainingArguments = $true)][string[]]$NativeArgs)
    $line = $NativeArgs -join ' '
    $global:fixture.NativeCalls.Add($line)
    $global:LASTEXITCODE = 0
    if ($line -eq 'interface portproxy show v4tov4') {
        if ($global:fixture.Existing) { '10.20.30.40  8765  172.20.10.1  8765' }
    } elseif ($line -match 'portproxy (add|set) ') {
        $global:fixture.Existing = $true
    } elseif ($line -match 'portproxy delete ') {
        $global:fixture.Existing = $false
    }
}
function global:Start-Service { param($Name) $global:fixture.Services.Add($Name) }
function global:Get-NetFirewallRule { param($Name, $ErrorAction)
    if ($null -ne $global:fixture.Rule) { $global:fixture.Rule }
}
function global:New-NetFirewallRule {
    [CmdletBinding()]
    param($Name, $DisplayName, $Direction, $Action, $Enabled, $Protocol, $LocalAddress, $LocalPort, $RemoteAddress, $Profile)
    $global:fixture.Firewall = @{} + $PSBoundParameters
    $global:fixture.Rule = [pscustomobject]@{ Name = $Name }
}
function global:Set-NetFirewallRule {
    [CmdletBinding()]
    param($Name, $NewDisplayName, $Direction, $Action, $Enabled, $Protocol, $LocalAddress, $LocalPort, $RemoteAddress, $Profile)
    $global:fixture.Firewall = @{} + $PSBoundParameters
}
function global:Remove-NetFirewallRule {
    param([Parameter(ValueFromPipeline = $true)]$InputObject)
    process { $global:fixture.Rule = $null }
}

Reset-Fixture
& $subject -WindowsIp '10.20.30.40' -Distro Ubuntu
Assert ($fixture.Probes.Count -eq 2 -and $fixture.Probes[0] -eq '172.20.10.2' -and $fixture.Probes[1] -eq '10.20.30.40') 'Probe backend before Windows endpoint'
Assert ($fixture.NativeCalls[1] -eq 'interface portproxy add v4tov4 listenaddress=10.20.30.40 listenport=8765 connectaddress=172.20.10.2 connectport=8765') 'Forward specific Windows IP to selected WSL route source'
Assert ($fixture.Firewall.Profile -eq 'Any' -and $fixture.Firewall.RemoteAddress -eq 'Any') 'Domain and routed corporate subnets are allowed'
Assert ($fixture.Firewall.LocalAddress -eq '10.20.30.40' -and $fixture.Firewall.LocalPort -eq 8765 -and $fixture.Firewall.Protocol -eq 'TCP') 'Firewall is scoped to chosen endpoint'

$fixture.WslIp = '172.20.10.9'
& $subject -WindowsIp '10.20.30.40' -Distro Ubuntu
Assert ($fixture.NativeCalls[3] -match '^interface portproxy set .*connectaddress=172.20.10.9 ') 'Rerun updates an existing rule after WSL IP changes'

$before = $fixture.NativeCalls.Count
& $subject -WindowsIp '10.20.30.40' -Action Status
Assert ($fixture.NativeCalls.Count -eq $before + 1) 'Status performs no native mutation'

& $subject -WindowsIp '10.20.30.40' -Action Remove
Assert (-not $fixture.Existing -and $null -eq $fixture.Rule) 'Remove deletes endpoint and owned firewall rule'
Assert ($fixture.NativeCalls[$fixture.NativeCalls.Count - 1] -eq 'interface portproxy delete v4tov4 listenaddress=10.20.30.40 listenport=8765') 'Remove is scoped, never resets all forwarding'

Reset-Fixture
$fixture.FailAddress = $fixture.WslIp
$failed = $false
try { & $subject -WindowsIp '10.20.30.40' -Distro Ubuntu } catch { $failed = $_.Exception.Message -match 'WSL backend probe failed' }
Assert $failed 'Backend failure gives an actionable error'
Assert ($fixture.NativeCalls.Count -eq 0 -and $null -eq $fixture.Firewall -and $fixture.Services.Count -eq 0) 'Backend failure does not mutate Windows network'

Reset-Fixture
$failed = $false
try { & $subject -WindowsIp '10.20.30.40' -Distro Ubuntu -WslIp '10.20.30.40' } catch { $failed = $_.Exception.Message -match 'same IP' }
Assert ($failed -and $fixture.NativeCalls.Count -eq 0) 'Prevent mirrored-mode forwarding loops'

Reset-Fixture
$failed = $false
try { & $subject -WindowsIp '10.99.99.99' -Distro Ubuntu } catch { $failed = $_.Exception.Message -match 'not assigned' }
Assert ($failed -and $fixture.NativeCalls.Count -eq 0) 'Reject IPs not assigned to Windows'
Write-Host 'PASS: setup, corporate firewall scope, IP refresh, status, remove, backend failure, loop and address validation'
