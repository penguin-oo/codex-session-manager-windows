[CmdletBinding()]
param(
    [ValidateSet("Install", "Inspect", "Uninstall")]
    [string] $Mode = "Install",
    [string] $SourceHandler,
    [string] $InstallRoot,
    [switch] $DryRun,
    [switch] $DryRunRegistryKeyAbsent,
    [string] $DryRunCurrentCommand
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)

$registryKey = "HKCU\Software\Classes\codex-location"
$registryProviderPath = "Registry::HKEY_CURRENT_USER\Software\Classes\codex-location"
$commandRegistryProviderPath = [string]::Concat(
    $registryProviderPath,
    "\shell\open\command"
)
$description = "URL:codex-location Protocol"

function Write-CompactJson {
    param(
        [Parameter(Mandatory = $true)]
        [object] $Value
    )

    [Console]::Out.WriteLine(($Value | ConvertTo-Json -Compress -Depth 4))
}

function Exit-InstallerError {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Message,
        [int] $ExitCode = 1
    )

    [Console]::Error.WriteLine($Message)
    exit $ExitCode
}

$hasDryRunCurrentCommand = $PSBoundParameters.ContainsKey(
    "DryRunCurrentCommand"
)
if (-not $DryRun -and
    ($DryRunRegistryKeyAbsent -or $hasDryRunCurrentCommand)) {
    Exit-InstallerError -Message "Dry-run registry state requires -DryRun."
}
if ($DryRunRegistryKeyAbsent -and $hasDryRunCurrentCommand) {
    Exit-InstallerError -Message "Dry-run registry state is ambiguous."
}

try {
    if ([string]::IsNullOrWhiteSpace($SourceHandler)) {
        $SourceHandler = [IO.Path]::Combine(
            $PSScriptRoot,
            "codex-location-handler.ps1"
        )
    }
    if ([string]::IsNullOrWhiteSpace($InstallRoot)) {
        if ([string]::IsNullOrWhiteSpace($env:USERPROFILE)) {
            throw "USERPROFILE is not available."
        }
        $InstallRoot = [IO.Path]::Combine(
            $env:USERPROFILE,
            ".codex",
            "bin"
        )
    }

    $sourceHandlerPath = [IO.Path]::GetFullPath($SourceHandler)
    $installRootPath = [IO.Path]::GetFullPath($InstallRoot)
    $handlerPath = [IO.Path]::Combine(
        $installRootPath,
        "codex-location-handler.ps1"
    )
    if ($handlerPath.IndexOf([char]0x22) -ge 0) {
        throw "The handler path is invalid."
    }

    $expectedCommand = [string]::Concat(
        "powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden ",
        "-ExecutionPolicy Bypass -File ",
        [char]0x22,
        $handlerPath,
        [char]0x22,
        " -Uri ",
        [char]0x22,
        "%1",
        [char]0x22
    )

    function Get-RegistrationState {
        if ($DryRunRegistryKeyAbsent) {
            return @{
                Exists = $false
                Command = $null
            }
        }
        if ($hasDryRunCurrentCommand) {
            return @{
                Exists = $true
                Command = $DryRunCurrentCommand
            }
        }
        if (-not (Test-Path -LiteralPath $registryProviderPath)) {
            return @{
                Exists = $false
                Command = $null
            }
        }

        $currentCommand = $null
        if (Test-Path -LiteralPath $commandRegistryProviderPath) {
            $commandKey = Get-Item -LiteralPath $commandRegistryProviderPath
            $currentCommand = $commandKey.GetValue(
                $null,
                $null,
                [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames
            )
        }
        return @{
            Exists = $true
            Command = $currentCommand
        }
    }

    if ($Mode -eq "Install") {
        $plan = [ordered] @{
            mode = "Install"
            dryRun = [bool] $DryRun
            sourceHandler = $sourceHandlerPath
            handler = $handlerPath
            registryKey = $registryKey
            command = $expectedCommand
            description = $description
            urlProtocol = ""
        }

        if (-not $DryRun) {
            if (-not [IO.File]::Exists($sourceHandlerPath)) {
                throw "The source handler does not exist."
            }

            [IO.Directory]::CreateDirectory($installRootPath) | Out-Null
            Copy-Item `
                -LiteralPath $sourceHandlerPath `
                -Destination $handlerPath `
                -Force

            $protocolKey = New-Item -Path $registryProviderPath -Force
            $protocolKey.SetValue(
                $null,
                $description,
                [Microsoft.Win32.RegistryValueKind]::String
            )
            $protocolKey.SetValue(
                "URL Protocol",
                "",
                [Microsoft.Win32.RegistryValueKind]::String
            )

            $commandKey = New-Item -Path $commandRegistryProviderPath -Force
            $commandKey.SetValue(
                $null,
                $expectedCommand,
                [Microsoft.Win32.RegistryValueKind]::String
            )
        }

        Write-CompactJson -Value $plan
        exit 0
    }

    $registration = Get-RegistrationState
    $owned = $false
    if ($registration.Exists -and $null -ne $registration.Command) {
        $owned = [string]::Equals(
            [string] $registration.Command,
            $expectedCommand,
            [StringComparison]::Ordinal
        )
    }

    if ($Mode -eq "Inspect") {
        $result = [ordered] @{
            mode = "Inspect"
            registryKey = $registryKey
            exists = [bool] $registration.Exists
            owned = $owned
        }
        Write-CompactJson -Value $result
        exit 0
    }

    $plan = [ordered] @{
        mode = "Uninstall"
        dryRun = [bool] $DryRun
        registryKey = $registryKey
        handler = $handlerPath
        command = $expectedCommand
        exists = [bool] $registration.Exists
        owned = $owned
        removeRegistryKey = $owned
    }
    Write-CompactJson -Value $plan

    if (-not $owned) {
        Exit-InstallerError `
            -Message "The codex-location registration is not owned by this installer." `
            -ExitCode 2
    }
    if (-not $DryRun) {
        Remove-Item -LiteralPath $registryProviderPath -Recurse -Force
    }
    exit 0
}
catch {
    Exit-InstallerError -Message "The codex-location installer failed."
}
