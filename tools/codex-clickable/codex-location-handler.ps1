param(
    [Parameter(Mandatory = $true)]
    [string] $Uri,
    [switch] $DryRun
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)

function Exit-InvalidRequest {
    [Console]::Error.WriteLine("Invalid codex-location request.")
    exit 1
}

if ([string]::IsNullOrWhiteSpace($Uri) -or
    -not $Uri.StartsWith("codex-location:", [StringComparison]::Ordinal)) {
    Exit-InvalidRequest
}

# Reject malformed percent escapes before System.Uri can canonicalize them.
for ($index = 0; $index -lt $Uri.Length; $index++) {
    if ($Uri[$index] -ne [char]0x25) {
        continue
    }

    if ($index + 2 -ge $Uri.Length -or
        -not [Uri]::IsHexDigit($Uri[$index + 1]) -or
        -not [Uri]::IsHexDigit($Uri[$index + 2])) {
        Exit-InvalidRequest
    }
    $index += 2
}

try {
    $parsedUri = $null
    if (-not [Uri]::TryCreate($Uri, [UriKind]::Absolute, [ref] $parsedUri)) {
        Exit-InvalidRequest
    }

    if ($parsedUri.Scheme -cne "codex-location" -or
        -not [string]::IsNullOrEmpty($parsedUri.Host) -or
        -not [string]::IsNullOrEmpty($parsedUri.UserInfo) -or
        -not [string]::IsNullOrEmpty($parsedUri.Query) -or
        -not [string]::IsNullOrEmpty($parsedUri.Fragment)) {
        Exit-InvalidRequest
    }

    $uriSuffix = $parsedUri.OriginalString.Substring("codex-location:".Length)
    if ($uriSuffix.StartsWith("///", [StringComparison]::Ordinal)) {
        $escapedPath = $uriSuffix.Substring(2)
    }
    elseif ($uriSuffix.StartsWith("/", [StringComparison]::Ordinal) -and
        -not $uriSuffix.StartsWith("//", [StringComparison]::Ordinal)) {
        $escapedPath = $uriSuffix
    }
    else {
        Exit-InvalidRequest
    }

    $decodedPath = [Uri]::UnescapeDataString($escapedPath)
    if ($decodedPath -cnotmatch "^/[A-Za-z]:/" -or
        $decodedPath.IndexOf([char]0x5C) -ge 0 -or
        $decodedPath.Substring(3).IndexOf([char]0x3A) -ge 0) {
        Exit-InvalidRequest
    }

    $forbiddenCharacters = [char[]] @(
        [char]0x21, # !
        [char]0x22, # double quote
        [char]0x23, # #
        [char]0x24, # $
        [char]0x25, # %
        [char]0x26, # &
        [char]0x27, # single quote
        [char]0x3B, # ;
        [char]0x3C, # <
        [char]0x3E, # >
        [char]0x40, # @
        [char]0x5E, # ^
        [char]0x60, # backtick
        [char]0x7B, # {
        [char]0x7C, # |
        [char]0x7D, # }
        [char]0xFFFD
    )
    if ($decodedPath.IndexOfAny($forbiddenCharacters) -ge 0) {
        Exit-InvalidRequest
    }

    foreach ($character in $decodedPath.ToCharArray()) {
        if ([char]::IsControl($character)) {
            Exit-InvalidRequest
        }
    }

    $localPath = $decodedPath.Substring(1).Replace([char]0x2F, [char]0x5C)
    $fullPath = [IO.Path]::GetFullPath($localPath)
    if ($fullPath -cnotmatch "^[A-Za-z]:\\" -or
        $fullPath.StartsWith("\\", [StringComparison]::Ordinal) -or
        $fullPath.Substring(2).IndexOf([char]0x3A) -ge 0) {
        Exit-InvalidRequest
    }

    if ([IO.File]::Exists($fullPath)) {
        $action = "select-file"
        $targetPath = $fullPath
    }
    elseif ([IO.Directory]::Exists($fullPath)) {
        $action = "open-directory"
        $targetPath = $fullPath
    }
    else {
        $parentPath = [IO.Path]::GetDirectoryName($fullPath)
        if ([string]::IsNullOrEmpty($parentPath) -or
            -not [IO.Directory]::Exists($parentPath)) {
            Exit-InvalidRequest
        }
        $action = "open-parent"
        $targetPath = $parentPath
    }

    $windowsDirectory = [Environment]::GetFolderPath(
        [Environment+SpecialFolder]::Windows
    )
    $explorerPath = [IO.Path]::Combine($windowsDirectory, "explorer.exe")
    if (-not [IO.File]::Exists($explorerPath)) {
        Exit-InvalidRequest
    }

    if ($action -eq "select-file") {
        [string[]] $explorerArguments = @(('/select,"{0}"' -f $targetPath))
    }
    else {
        [string[]] $explorerArguments = @(('"{0}"' -f $targetPath))
    }

    if ($DryRun) {
        $result = [ordered] @{
            action = $action
            path = $targetPath
            executable = $explorerPath
            arguments = $explorerArguments
        }
        [Console]::Out.WriteLine(($result | ConvertTo-Json -Compress))
        exit 0
    }

    Start-Process -FilePath $explorerPath -ArgumentList $explorerArguments | Out-Null
}
catch {
    Exit-InvalidRequest
}
