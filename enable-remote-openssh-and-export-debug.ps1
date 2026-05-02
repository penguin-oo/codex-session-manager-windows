param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Write-Section {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Title,
        [Parameter(Mandatory = $true)]
        [string]$Content,
        [Parameter(Mandatory = $true)]
        [string]$Path
    )
    Add-Content -LiteralPath $Path -Value ("=== {0} ===" -f $Title)
    Add-Content -LiteralPath $Path -Value $Content
    Add-Content -LiteralPath $Path -Value ""
}

function Get-CommandOutput {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$ScriptBlock
    )
    try {
        return (& $ScriptBlock | Out-String).TrimEnd()
    } catch {
        return ("ERROR: {0}" -f $_.Exception.Message)
    }
}

if (-not (Test-IsAdministrator)) {
    throw "Run this script as Administrator. The .cmd wrapper should prompt for elevation automatically."
}

$repoRoot = $PSScriptRoot
$headPath = Join-Path $repoRoot "remote-head.txt"
$settingsOutPath = Join-Path $repoRoot "remote-token_pool_settings.json"
$runtimeOutPath = Join-Path $repoRoot "remote-runtime.txt"
$codexHome = Join-Path $env:USERPROFILE ".codex"
$settingsPath = Join-Path $codexHome "token_pool_settings.json"

$sshCapability = Get-WindowsCapability -Online | Where-Object { $_.Name -like "OpenSSH.Server*" } | Select-Object -First 1
if (-not $sshCapability) {
    throw "OpenSSH.Server capability was not found on this Windows installation."
}
if ($sshCapability.State -ne "Installed") {
    Add-WindowsCapability -Online -Name $sshCapability.Name | Out-Null
}

Set-Service -Name sshd -StartupType Automatic
if ((Get-Service -Name sshd).Status -ne "Running") {
    Start-Service -Name sshd
}

$sshFirewallRule = Get-NetFirewallRule -Name "OpenSSH-Server-In-TCP" -ErrorAction SilentlyContinue
if ($null -ne $sshFirewallRule) {
    Enable-NetFirewallRule -Name "OpenSSH-Server-In-TCP" | Out-Null
} else {
    New-NetFirewallRule `
        -Name "OpenSSH-Server-In-TCP" `
        -DisplayName "OpenSSH Server (sshd)" `
        -Enabled True `
        -Direction Inbound `
        -Protocol TCP `
        -Action Allow `
        -LocalPort 22 | Out-Null
}

$gitHead = Get-CommandOutput {
    git -C $repoRoot rev-parse HEAD 2>$null
}
Set-Content -LiteralPath $headPath -Value $gitHead -Encoding UTF8

if (Test-Path -LiteralPath $settingsPath) {
    Copy-Item -LiteralPath $settingsPath -Destination $settingsOutPath -Force
} else {
    Set-Content -LiteralPath $settingsOutPath -Value "NO_TOKEN_POOL_SETTINGS" -Encoding UTF8
}

Set-Content -LiteralPath $runtimeOutPath -Value @(
    "Generated: $(Get-Date -Format s)"
    "ComputerName: $env:COMPUTERNAME"
    "UserProfile: $env:USERPROFILE"
    "RepoRoot: $repoRoot"
    "OpenSSHCapability: $($sshCapability.Name)"
    "OpenSSHCapabilityState: $((Get-WindowsCapability -Online | Where-Object { $_.Name -eq $sshCapability.Name } | Select-Object -First 1).State)"
    "sshdStatus: $((Get-Service -Name sshd).Status)"
    "sshdStartType: $((Get-Service -Name sshd).StartType)"
    ""
) -Encoding UTF8

Write-Section -Title "Git" -Path $runtimeOutPath -Content (Get-CommandOutput {
    git -C $repoRoot status --short
    git -C $repoRoot branch --show-current
    git -C $repoRoot rev-parse HEAD
})

Write-Section -Title "Tailscale Status" -Path $runtimeOutPath -Content (Get-CommandOutput {
    tailscale status
})

Write-Section -Title "Tailscale IP" -Path $runtimeOutPath -Content (Get-CommandOutput {
    tailscale ip -4
})

Write-Section -Title "Port 22 Listeners" -Path $runtimeOutPath -Content (Get-CommandOutput {
    Get-NetTCPConnection -LocalPort 22 -State Listen | Select-Object LocalAddress, LocalPort, OwningProcess
})

Write-Section -Title "Relevant Processes" -Path $runtimeOutPath -Content (Get-CommandOutput {
    Get-CimInstance Win32_Process |
        Where-Object {
            $_.Name -match "sshd|python|powershell|codex-session-manager" -or
            $_.CommandLine -match "app\\.py|mobile_portal|run-mobile|codex-session-manager|sshd"
        } |
        Select-Object ProcessId, Name, CommandLine
})

Write-Host ""
Write-Host "Done."
Write-Host "Generated files:"
Write-Host "  $headPath"
Write-Host "  $settingsOutPath"
Write-Host "  $runtimeOutPath"
Write-Host ""
Write-Host "You can now tell Codex to inspect the shared folder."
