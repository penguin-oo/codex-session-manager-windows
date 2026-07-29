[CmdletBinding()]
param(
    [ValidateSet("Install", "Inspect", "Uninstall")]
    [string] $Mode = "Install",
    [string] $SourceHandler,
    [string] $InstallRoot,
    [switch] $DryRun,
    [string] $DryRunRegistryStateJson
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)

$registryKey = "HKCU\Software\Classes\codex-location"
$registrySubKey = "Software\Classes\codex-location"
$registryProviderPath = "Registry::HKEY_CURRENT_USER\Software\Classes\codex-location"
$description = "URL:codex-location Protocol"
$ownerName = "Codex Location Owner"
$ownerValue = "codex-session-manager-windows/v1"
$stringValueKind = [int] [Microsoft.Win32.RegistryValueKind]::String

function Write-CompactJson {
    param(
        [Parameter(Mandatory = $true)]
        [object] $Value
    )

    [Console]::Out.WriteLine(($Value | ConvertTo-Json -Compress -Depth 12))
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

function Resolve-TrustedLocalPath {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Value,
        [Parameter(Mandatory = $true)]
        [string] $Label,
        [switch] $RequireFile
    )

    if ([string]::IsNullOrWhiteSpace($Value) -or
        $Value.IndexOf([char]0x25) -ge 0 -or
        $Value.IndexOf([char]0x22) -ge 0) {
        throw "$Label must be a trusted local fixed-drive path."
    }
    foreach ($character in $Value.ToCharArray()) {
        if ([char]::IsControl($character)) {
            throw "$Label must be a trusted local fixed-drive path."
        }
    }
    if ($Value -notmatch "^[A-Za-z]:[\\/]") {
        throw "$Label must be a trusted local fixed-drive path."
    }

    $fullPath = [IO.Path]::GetFullPath($Value)
    if ($fullPath -notmatch "^[A-Za-z]:\\" -or
        $fullPath.StartsWith("\\", [StringComparison]::Ordinal) -or
        $fullPath.Substring(2).IndexOf([char]0x3A) -ge 0) {
        throw "$Label must be a trusted local fixed-drive path."
    }

    $driveRoot = [IO.Path]::GetPathRoot($fullPath)
    $drive = [IO.DriveInfo]::new($driveRoot)
    if ($drive.DriveType -ne [IO.DriveType]::Fixed) {
        throw "$Label must be a trusted local fixed-drive path."
    }
    if ($RequireFile -and -not [IO.File]::Exists($fullPath)) {
        throw "$Label must be an existing trusted local file."
    }

    $currentPath = $fullPath
    while (-not [string]::IsNullOrEmpty($currentPath)) {
        if ([IO.File]::Exists($currentPath) -or
            [IO.Directory]::Exists($currentPath)) {
            $attributes = [IO.File]::GetAttributes($currentPath)
            if (($attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "$Label cannot contain a reparse point."
            }
        }

        $parent = [IO.Directory]::GetParent($currentPath)
        if ($null -eq $parent) {
            break
        }
        $currentPath = $parent.FullName
    }

    return $fullPath
}

function Get-RegistryTree {
    param(
        [Parameter(Mandatory = $true)]
        [Microsoft.Win32.RegistryKey] $Key
    )

    [object[]] $values = @(
        foreach ($name in $Key.GetValueNames()) {
            [ordered] @{
                name = $name
                type = [int] $Key.GetValueKind($name)
                data = $Key.GetValue(
                    $name,
                    $null,
                    [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames
                )
            }
        }
    )
    [object[]] $subkeys = @(
        foreach ($name in $Key.GetSubKeyNames()) {
            $child = $Key.OpenSubKey($name, $false)
            if ($null -eq $child) {
                throw "The codex-location registration changed during inspection."
            }
            try {
                $childTree = Get-RegistryTree -Key $child
            }
            finally {
                $child.Close()
            }
            [ordered] @{
                name = $name
                values = $childTree.values
                subkeys = $childTree.subkeys
            }
        }
    )
    return [ordered] @{
        values = $values
        subkeys = $subkeys
    }
}

function Get-ActualRegistrationState {
    $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey(
        $registrySubKey,
        $false
    )
    if ($null -eq $key) {
        return [ordered] @{
            exists = $false
            tree = $null
        }
    }
    try {
        $tree = Get-RegistryTree -Key $key
    }
    finally {
        $key.Close()
    }
    return [ordered] @{
        exists = $true
        tree = $tree
    }
}

function Get-ExpectedRegistrationTree {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Command
    )

    $commandNode = [ordered] @{
        name = "command"
        values = @(
            [ordered] @{
                name = ""
                type = $stringValueKind
                data = $Command
            }
        )
        subkeys = @()
    }
    $openNode = [ordered] @{
        name = "open"
        values = @()
        subkeys = @($commandNode)
    }
    $shellNode = [ordered] @{
        name = "shell"
        values = @()
        subkeys = @($openNode)
    }
    return [ordered] @{
        values = @(
            [ordered] @{
                name = ""
                type = $stringValueKind
                data = $description
            },
            [ordered] @{
                name = "URL Protocol"
                type = $stringValueKind
                data = ""
            },
            [ordered] @{
                name = $ownerName
                type = $stringValueKind
                data = $ownerValue
            }
        )
        subkeys = @($shellNode)
    }
}

function Test-RegistryTreeExact {
    param(
        [Parameter(Mandatory = $true)]
        [object] $Actual,
        [Parameter(Mandatory = $true)]
        [object] $Expected
    )

    try {
        [object[]] $actualValues = @($Actual.values)
        [object[]] $expectedValues = @($Expected.values)
        [object[]] $actualSubkeys = @($Actual.subkeys)
        [object[]] $expectedSubkeys = @($Expected.subkeys)
    }
    catch {
        return $false
    }
    if ($actualValues.Count -ne $expectedValues.Count -or
        $actualSubkeys.Count -ne $expectedSubkeys.Count) {
        return $false
    }

    foreach ($expectedValue in $expectedValues) {
        [object[]] $matches = @(
            $actualValues | Where-Object {
                [string]::Equals(
                    [string] $_.name,
                    [string] $expectedValue.name,
                    [StringComparison]::Ordinal
                )
            }
        )
        if ($matches.Count -ne 1) {
            return $false
        }
        $actualValue = $matches[0]
        if ([int] $actualValue.type -ne [int] $expectedValue.type -or
            -not ($actualValue.data -is [string]) -or
            -not [string]::Equals(
                [string] $actualValue.data,
                [string] $expectedValue.data,
                [StringComparison]::Ordinal
            )) {
            return $false
        }
    }

    foreach ($expectedSubkey in $expectedSubkeys) {
        [object[]] $matches = @(
            $actualSubkeys | Where-Object {
                [string]::Equals(
                    [string] $_.name,
                    [string] $expectedSubkey.name,
                    [StringComparison]::Ordinal
                )
            }
        )
        if ($matches.Count -ne 1) {
            return $false
        }
        $childIsExact = Test-RegistryTreeExact `
            -Actual $matches[0] `
            -Expected $expectedSubkey
        if (-not $childIsExact) {
            return $false
        }
    }
    return $true
}

function Test-RegistrationOwned {
    param(
        [Parameter(Mandatory = $true)]
        [object] $Registration,
        [Parameter(Mandatory = $true)]
        [object] $ExpectedTree
    )

    try {
        if (-not [bool] $Registration.exists -or
            $null -eq $Registration.tree) {
            return $false
        }
    }
    catch {
        return $false
    }
    return Test-RegistryTreeExact `
        -Actual $Registration.tree `
        -Expected $ExpectedTree
}

function New-CodexLocationRegistration {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Command
    )

    $rootCreated = $false
    try {
        $protocolKey = $null
        try {
            $protocolKey = New-Item -Path $registryProviderPath
            $rootCreated = $true
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
            $protocolKey.SetValue(
                $ownerName,
                $ownerValue,
                [Microsoft.Win32.RegistryValueKind]::String
            )
        }
        finally {
            if ($null -ne $protocolKey) {
                $protocolKey.Close()
            }
        }

        New-Item -Path ([string]::Concat($registryProviderPath, "\shell")) |
            Out-Null
        New-Item -Path ([string]::Concat($registryProviderPath, "\shell\open")) |
            Out-Null
        $commandKey = $null
        try {
            $commandKey = New-Item -Path (
                [string]::Concat($registryProviderPath, "\shell\open\command")
            )
            $commandKey.SetValue(
                $null,
                $Command,
                [Microsoft.Win32.RegistryValueKind]::String
            )
        }
        finally {
            if ($null -ne $commandKey) {
                $commandKey.Close()
            }
        }
    }
    catch {
        $failure = $_
        if ($rootCreated -and
            (Test-Path -LiteralPath $registryProviderPath)) {
            Remove-Item `
                -LiteralPath $registryProviderPath `
                -Recurse `
                -Force
        }
        throw $failure
    }
}

function Invoke-CodexHandlerFileTransaction {
    param(
        [Parameter(Mandatory = $true)]
        [string] $SourceHandlerPath,
        [Parameter(Mandatory = $true)]
        [string] $HandlerPath,
        [scriptblock] $CommitAction
    )

    $handlerDirectory = [IO.Path]::GetDirectoryName($HandlerPath)
    $transactionId = [Guid]::NewGuid().ToString("N")
    $temporaryPath = [IO.Path]::Combine(
        $handlerDirectory,
        [string]::Concat(
            ".codex-location-handler.",
            $transactionId,
            ".tmp"
        )
    )
    $backupPath = [IO.Path]::Combine(
        $handlerDirectory,
        [string]::Concat(
            ".codex-location-handler.",
            $transactionId,
            ".bak"
        )
    )
    $rollbackDiscardPath = [IO.Path]::Combine(
        $handlerDirectory,
        [string]::Concat(
            ".codex-location-handler.",
            $transactionId,
            ".rollback"
        )
    )
    $handlerExisted = [IO.File]::Exists($HandlerPath)
    $handlerCommitted = $false
    $transactionCommitted = $false
    $rollbackCompleted = $false

    try {
        [IO.File]::Copy($SourceHandlerPath, $temporaryPath, $false)
        if ($handlerExisted) {
            [IO.File]::Replace(
                $temporaryPath,
                $HandlerPath,
                $backupPath,
                $true
            )
        }
        else {
            [IO.File]::Move($temporaryPath, $HandlerPath)
        }
        $handlerCommitted = $true

        if ($null -ne $CommitAction) {
            & $CommitAction
        }
        $transactionCommitted = $true
    }
    catch {
        $failure = $_
        if (-not $transactionCommitted -and $handlerCommitted) {
            if ($handlerExisted) {
                if (-not [IO.File]::Exists($backupPath)) {
                    throw "Handler update failed and its backup is unavailable."
                }
                if ([IO.File]::Exists($HandlerPath)) {
                    [IO.File]::Replace(
                        $backupPath,
                        $HandlerPath,
                        $rollbackDiscardPath,
                        $true
                    )
                }
                else {
                    [IO.File]::Move($backupPath, $HandlerPath)
                }
            }
            elseif ([IO.File]::Exists($HandlerPath)) {
                [IO.File]::Delete($HandlerPath)
            }
        }
        $rollbackCompleted = $true
        throw $failure
    }
    finally {
        try {
            if ([IO.File]::Exists($temporaryPath)) {
                [IO.File]::Delete($temporaryPath)
            }
        }
        catch {
        }
        if ($transactionCommitted -or $rollbackCompleted) {
            foreach ($cleanupPath in @($backupPath, $rollbackDiscardPath)) {
                try {
                    if ([IO.File]::Exists($cleanupPath)) {
                        [IO.File]::Delete($cleanupPath)
                    }
                }
                catch {
                }
            }
        }
    }
}

if ($MyInvocation.InvocationName -eq ".") {
    return
}

$hasDryRunRegistryState = $PSBoundParameters.ContainsKey(
    "DryRunRegistryStateJson"
)
if (-not $DryRun -and $hasDryRunRegistryState) {
    Exit-InstallerError -Message "Dry-run registry state requires -DryRun."
}

try {
    if ([string]::IsNullOrWhiteSpace($env:USERPROFILE)) {
        throw "USERPROFILE is not available."
    }

    $defaultInstallRoot = Resolve-TrustedLocalPath `
        -Value ([IO.Path]::Combine($env:USERPROFILE, ".codex", "bin")) `
        -Label "InstallRoot"
    if ([string]::IsNullOrWhiteSpace($InstallRoot)) {
        $installRootPath = $defaultInstallRoot
    }
    else {
        $installRootPath = Resolve-TrustedLocalPath `
            -Value $InstallRoot `
            -Label "InstallRoot"
    }
    if ($Mode -eq "Install" -and
        -not $DryRun -and
        -not [string]::Equals(
            $installRootPath,
            $defaultInstallRoot,
            [StringComparison]::OrdinalIgnoreCase
        )) {
        throw "A custom InstallRoot requires -DryRun."
    }

    $handlerPath = Resolve-TrustedLocalPath `
        -Value ([IO.Path]::Combine(
            $installRootPath,
            "codex-location-handler.ps1"
        )) `
        -Label "InstallRoot"

    if ([string]::IsNullOrWhiteSpace($SourceHandler)) {
        $SourceHandler = [IO.Path]::Combine(
            $PSScriptRoot,
            "codex-location-handler.ps1"
        )
    }
    if ($Mode -eq "Install") {
        $sourceHandlerPath = Resolve-TrustedLocalPath `
            -Value $SourceHandler `
            -Label "SourceHandler" `
            -RequireFile
        if ([string]::Equals(
            $sourceHandlerPath,
            $handlerPath,
            [StringComparison]::OrdinalIgnoreCase
        )) {
            throw "SourceHandler and installed handler must be different files."
        }
    }
    else {
        $sourceHandlerPath = $null
    }

    $powershellPath = [IO.Path]::Combine($PSHOME, "powershell.exe")
    if (-not [IO.File]::Exists($powershellPath)) {
        throw "Windows PowerShell is not available."
    }
    $expectedCommand = [string]::Concat(
        [char]0x22,
        $powershellPath,
        [char]0x22,
        " -NoProfile -NonInteractive -WindowStyle Hidden ",
        "-ExecutionPolicy Bypass -File ",
        [char]0x22,
        $handlerPath,
        [char]0x22,
        " -Uri ",
        [char]0x22,
        "%1",
        [char]0x22
    )
    $expectedTree = Get-ExpectedRegistrationTree -Command $expectedCommand

    if ($hasDryRunRegistryState) {
        try {
            $registration = $DryRunRegistryStateJson | ConvertFrom-Json
        }
        catch {
            throw "Dry-run registry state is invalid."
        }
    }
    else {
        $registration = Get-ActualRegistrationState
    }
    $owned = Test-RegistrationOwned `
        -Registration $registration `
        -ExpectedTree $expectedTree

    if ($Mode -eq "Inspect") {
        $result = [ordered] @{
            mode = "Inspect"
            registryKey = $registryKey
            exists = [bool] $registration.exists
            owned = $owned
        }
        Write-CompactJson -Value $result
        exit 0
    }

    if ($Mode -eq "Uninstall") {
        $plan = [ordered] @{
            mode = "Uninstall"
            dryRun = [bool] $DryRun
            registryKey = $registryKey
            handler = $handlerPath
            command = $expectedCommand
            exists = [bool] $registration.exists
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
            Remove-Item `
                -LiteralPath $registryProviderPath `
                -Recurse `
                -Force
        }
        exit 0
    }

    if ([bool] $registration.exists) {
        if ($owned) {
            $registrationAction = "preserve"
        }
        else {
            $registrationAction = "reject"
        }
    }
    else {
        $registrationAction = "create"
    }
    $plan = [ordered] @{
        mode = "Install"
        dryRun = [bool] $DryRun
        sourceHandler = $sourceHandlerPath
        handler = $handlerPath
        registryKey = $registryKey
        command = $expectedCommand
        description = $description
        urlProtocol = ""
        ownerName = $ownerName
        ownerValue = $ownerValue
        exists = [bool] $registration.exists
        owned = $owned
        registrationAction = $registrationAction
        fileTransaction = [ordered] @{
            temporarySibling = $true
            atomicReplacement = $true
            rollbackOnFailure = $true
        }
    }

    if ($registrationAction -eq "reject") {
        Write-CompactJson -Value $plan
        Exit-InstallerError `
            -Message "An existing codex-location registration is not owned by this installer." `
            -ExitCode 2
    }
    if ($DryRun) {
        Write-CompactJson -Value $plan
        exit 0
    }

    [IO.Directory]::CreateDirectory($installRootPath) | Out-Null
    if ($registrationAction -eq "create") {
        $commitAction = {
            New-CodexLocationRegistration -Command $expectedCommand
        }
    }
    else {
        $commitAction = $null
    }
    Invoke-CodexHandlerFileTransaction `
        -SourceHandlerPath $sourceHandlerPath `
        -HandlerPath $handlerPath `
        -CommitAction $commitAction

    Write-CompactJson -Value $plan
    exit 0
}
catch {
    Exit-InstallerError -Message $_.Exception.Message
}
