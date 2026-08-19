[CmdletBinding()]
param(
    [string]$ToolRoot = (Join-Path $env:LOCALAPPDATA 'DesktopCompanionDev\pet-toolchain'),
    [string]$LockPath = (Join-Path $PSScriptRoot '..\tools\pet-toolchain.lock.json'),
    [string]$RequirementsPath = (Join-Path $PSScriptRoot '..\requirements\pet-media.txt'),
    [string]$WheelCache = '',
    [Parameter(Mandatory)][string]$QtPython
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'pet_toolchain_common.ps1')

function Get-ComparablePath {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Path)

    $full = [System.IO.Path]::GetFullPath($Path)
    $root = [System.IO.Path]::GetPathRoot($full)
    $current = $root
    $relative = $full.Substring($root.Length)
    foreach ($segment in ($relative -split '[\\/]')) {
        if ([string]::IsNullOrEmpty($segment)) {
            continue
        }
        $next = [System.IO.Path]::Combine($current, $segment)
        if (-not (Test-Path -LiteralPath $next)) {
            $current = $next
            continue
        }
        $item = Get-Item -LiteralPath $next -Force
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            $target = $item.ResolveLinkTarget($true)
            if ($null -eq $target) {
                throw "Could not resolve reparse point for path comparison: $next"
            }
            $current = $target.FullName
        }
        else {
            $current = $item.FullName
        }
    }
    if ($current.Length -gt $root.Length) {
        $current = $current.TrimEnd([char[]]'\\/')
    }
    return $current
}

function Test-SamePath {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Left,
        [Parameter(Mandatory)][string]$Right
    )

    return [string]::Equals(
        (Get-ComparablePath -Path $Left),
        (Get-ComparablePath -Path $Right),
        [System.StringComparison]::OrdinalIgnoreCase
    )
}

function Test-PathOverlap {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Left,
        [Parameter(Mandatory)][string]$Right
    )

    $leftPath = Get-ComparablePath -Path $Left
    $rightPath = Get-ComparablePath -Path $Right
    if ([string]::Equals($leftPath, $rightPath, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $true
    }
    $leftPrefix = if ($leftPath.EndsWith('\')) { $leftPath } else { "$leftPath\" }
    $rightPrefix = if ($rightPath.EndsWith('\')) { $rightPath } else { "$rightPath\" }
    return $leftPath.StartsWith($rightPrefix, [System.StringComparison]::OrdinalIgnoreCase) -or
        $rightPath.StartsWith($leftPrefix, [System.StringComparison]::OrdinalIgnoreCase)
}

function Assert-ToolRootAncestorsHaveNoReparsePoints {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Path)

    $probe = [System.IO.Path]::GetFullPath($Path)
    while (-not (Test-Path -LiteralPath $probe)) {
        $parent = [System.IO.Directory]::GetParent($probe)
        if ($null -eq $parent) {
            throw "Could not find an existing ancestor for tool root: $Path"
        }
        $probe = $parent.FullName
    }
    while ($true) {
        $item = Get-Item -LiteralPath $probe -Force
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Tool root has a reparse-point ancestor: $probe"
        }
        $parent = [System.IO.Directory]::GetParent($probe)
        if ($null -eq $parent) {
            return
        }
        $probe = $parent.FullName
    }
}

function Assert-SafeToolRoot {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Candidate,
        [Parameter(Mandatory)][string]$RepositoryRoot
    )

    $candidateFull = [System.IO.Path]::GetFullPath($Candidate)
    Assert-ToolRootAncestorsHaveNoReparsePoints -Path $candidateFull
    $exactForbidden = @(
        [System.IO.Path]::GetPathRoot($candidateFull),
        $env:USERPROFILE,
        $env:LOCALAPPDATA
    )
    foreach ($forbiddenPath in $exactForbidden) {
        if (-not [string]::IsNullOrWhiteSpace($forbiddenPath) -and
            (Test-SamePath -Left $candidateFull -Right $forbiddenPath)) {
            throw "Refusing unsafe tool root: $candidateFull"
        }
    }
    $installationRoot = Join-Path $env:LOCALAPPDATA 'Programs\DesktopCompanion'
    $protectedRoots = @(
        $RepositoryRoot,
        (Join-Path $RepositoryRoot '.venv'),
        $installationRoot,
        (Join-Path $installationRoot 'resources\pets'),
        (Join-Path $env:APPDATA 'DesktopCompanion\pets')
    )
    foreach ($protectedRoot in $protectedRoots) {
        if (-not [string]::IsNullOrWhiteSpace($protectedRoot) -and
            (Test-PathOverlap -Left $candidateFull -Right $protectedRoot)) {
            throw "Refusing unsafe tool root: $candidateFull"
        }
    }
    return $candidateFull
}

function Assert-RegularFile {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Path)

    $item = Get-Item -LiteralPath $Path -Force
    if ($item -is [System.IO.DirectoryInfo] -or
        ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Expected regular file: $Path"
    }
    return $item
}

function Assert-InstalledToolInventory {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$ToolRoot,
        [Parameter(Mandatory)][string]$ToolKey,
        [Parameter(Mandatory)][object]$ToolLock
    )

    $rootFull = [System.IO.Path]::GetFullPath($ToolRoot)
    if (-not (Test-Path -LiteralPath $rootFull -PathType Container)) {
        throw "Tool inventory root is missing for ${ToolKey}: $rootFull"
    }
    if ($null -eq $ToolLock.PSObject.Properties['installedFiles']) {
        throw "Tool inventory is missing from the locked tool record: $ToolKey"
    }
    $inventory = $ToolLock.installedFiles
    if ($inventory -isnot [System.Management.Automation.PSCustomObject]) {
        throw "Tool inventory is invalid for $ToolKey"
    }

    Assert-NoReparsePoints -Root $rootFull
    $expected = [System.Collections.Generic.Dictionary[string, object]]::new(
        [System.StringComparer]::OrdinalIgnoreCase
    )
    foreach ($property in @($inventory.PSObject.Properties)) {
        $relativePath = [string]$property.Name
        $normalisedPath = Assert-SafeArchivePath -EntryName $relativePath
        if ($relativePath.Contains('\') -or $normalisedPath.Replace('\', '/') -cne $relativePath) {
            throw "Tool inventory contains an unsafe relative path for ${ToolKey}: $relativePath"
        }
        if (-not $expected.TryAdd($relativePath, $property.Value)) {
            throw "Tool inventory contains a duplicate relative path for ${ToolKey}: $relativePath"
        }
    }

    $actual = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::OrdinalIgnoreCase
    )
    foreach ($item in @(Get-ChildItem -LiteralPath $rootFull -Force -Recurse)) {
        $relativePath = [System.IO.Path]::GetRelativePath($rootFull, $item.FullName).Replace('\', '/')
        $null = Resolve-ContainedPath -Root $rootFull -RelativePath ($relativePath -replace '/', '\')
        if ($item -is [System.IO.DirectoryInfo]) {
            continue
        }
        $null = Assert-RegularFile -Path $item.FullName
        if (-not $actual.Add($relativePath)) {
            throw "Tool inventory contains duplicate extracted files for ${ToolKey}: $relativePath"
        }
    }

    $missing = @($expected.Keys | Where-Object { -not $actual.Contains($_) } | Sort-Object)
    $unexpected = @($actual | Where-Object { -not $expected.ContainsKey($_) } | Sort-Object)
    if ($missing.Count -gt 0 -or $unexpected.Count -gt 0) {
        throw "Tool inventory mismatch for $ToolKey; missing: $($missing -join ', '); unexpected: $($unexpected -join ', ')"
    }
    foreach ($relativePath in @($expected.Keys)) {
        $record = $expected[$relativePath]
        $filePath = Resolve-ContainedPath -Root $rootFull -RelativePath ($relativePath -replace '/', '\')
        $null = Assert-RegularFile -Path $filePath
        try {
            Assert-FileDigest -Path $filePath -ExpectedSize ([Int64]$record.size) `
                -ExpectedSha256 ([string]$record.sha256)
        }
        catch {
            throw "Tool inventory digest mismatch for ${ToolKey}: $relativePath"
        }
    }
    Assert-NoReparsePoints -Root $rootFull
}

function Remove-ProvenContainedDirectory {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][string]$DirectoryPath
    )

    if (-not (Test-Path -LiteralPath $DirectoryPath)) {
        return
    }
    $rootFull = [System.IO.Path]::GetFullPath($Root)
    $directoryFull = [System.IO.Path]::GetFullPath($DirectoryPath)
    $relative = [System.IO.Path]::GetRelativePath($rootFull, $directoryFull)
    $verified = Resolve-ContainedPath -Root $rootFull -RelativePath $relative
    if (-not (Test-SamePath -Left $verified -Right $directoryFull)) {
        throw "Refusing to remove unresolved directory: $directoryFull"
    }
    $item = Get-Item -LiteralPath $verified -Force
    if ($item -isnot [System.IO.DirectoryInfo] -or
        ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Refusing to remove non-directory path: $verified"
    }
    Assert-NoReparsePoints -Root $verified
    Remove-Item -LiteralPath $verified -Recurse -Force
}

function Test-CurrentToolchainDigest {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][string]$LockDigest
    )

    $pointerPath = Resolve-ContainedPath -Root $Root -RelativePath 'current.json'
    if (-not (Test-Path -LiteralPath $pointerPath)) {
        return $false
    }
    $pointerItem = Assert-RegularFile -Path $pointerPath
    try {
        $pointer = [System.IO.File]::ReadAllText($pointerItem.FullName, [System.Text.UTF8Encoding]::new($false, $true)) |
            ConvertFrom-Json -Depth 8
    }
    catch {
        return $false
    }
    if ($null -eq $pointer -or
        @($pointer.PSObject.Properties.Name).Count -ne 2 -or
        $null -eq $pointer.PSObject.Properties['lockDigest'] -or
        $null -eq $pointer.PSObject.Properties['version'] -or
        $pointer.lockDigest -cne $LockDigest) {
        return $false
    }

    try {
        $versionPath = Resolve-ContainedPath -Root $Root -RelativePath ([string]$pointer.version)
        $expectedVersionPath = Resolve-ContainedPath -Root $Root -RelativePath "versions\$LockDigest"
        if (-not (Test-SamePath -Left $versionPath -Right $expectedVersionPath) -or
            -not (Test-Path -LiteralPath $versionPath)) {
            return $false
        }
        Assert-NoReparsePoints -Root $versionPath
        $installedPath = Resolve-ContainedPath -Root $versionPath -RelativePath 'installed.json'
        $installedItem = Assert-RegularFile -Path $installedPath
        $installed = [System.IO.File]::ReadAllText($installedItem.FullName, [System.Text.UTF8Encoding]::new($false, $true)) |
            ConvertFrom-Json -Depth 16
        return $null -ne $installed -and $installed.lockDigest -ceq $LockDigest
    }
    catch {
        return $false
    }
}

function Assert-AuthenticodeAsset {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][object]$Asset,
        [Parameter(Mandatory)][string]$Path,
        [switch]$PassThru
    )

    if (-not $Asset.authenticode.required) {
        if ($PassThru) {
            return ''
        }
        return
    }
    $signature = Get-AuthenticodeSignature -FilePath $Path
    if ($signature.Status -ne 'Valid' -or $null -eq $signature.SignerCertificate) {
        throw "Authenticode validation failed for: $Path"
    }
    if ($signature.SignerCertificate.Subject -notin @($Asset.authenticode.publishers)) {
        throw "Unexpected Authenticode publisher for: $Path"
    }
    if ($PassThru) {
        return [string]$signature.SignerCertificate.Subject
    }
}

function Get-IsolatedPythonEnvironment {
    [CmdletBinding()]
    param()

    # PIP_CONFIG_FILE=NUL disables pip configuration discovery on Windows.  The
    # clean process mode supplies only Windows runtime variables before these
    # explicit Python/pip overrides are applied.
    return @{
        PYTHONDONTWRITEBYTECODE = '1'
        PYTHONNOUSERSITE = '1'
        PIP_CONFIG_FILE = 'NUL'
        PIP_DISABLE_PIP_VERSION_CHECK = '1'
        PIP_NO_INPUT = '1'
        PIP_NO_CACHE_DIR = '1'
    }
}

function Resolve-TrustedPythonLauncher {
    [CmdletBinding()]
    param([Parameter(Mandatory)][object]$PythonRuntime)

    $candidates = @(Get-Command -Name 'py.exe' -CommandType Application -All -ErrorAction Stop)
    foreach ($candidate in $candidates) {
        $candidatePath = [string]$candidate.Source
        if ([string]::IsNullOrWhiteSpace($candidatePath)) {
            $candidatePath = [string]$candidate.Path
        }
        if ([string]::IsNullOrWhiteSpace($candidatePath) -or
            -not [System.IO.Path]::IsPathRooted($candidatePath)) {
            continue
        }
        try {
            $item = Assert-RegularFile -Path ([System.IO.Path]::GetFullPath($candidatePath))
            $resolvedPath = Get-ComparablePath -Path $item.FullName
            if (-not [string]::Equals($resolvedPath, $item.FullName, [System.StringComparison]::OrdinalIgnoreCase)) {
                throw "Python launcher has a reparse-point ancestor: $($item.FullName)"
            }
            Assert-AuthenticodeAsset -Asset $PythonRuntime -Path $item.FullName
            return $item.FullName
        }
        catch {
            # A PATH-preceding attacker-controlled launcher must never be used;
            # continue only to a separately resolved, signature-validated one.
            continue
        }
    }
    throw 'Could not resolve a trusted absolute Python launcher'
}

function Assert-TrustedBasePythonRuntime {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$LauncherPath,
        [Parameter(Mandatory)][object]$PythonRuntime
    )

    $details = Invoke-CheckedProcess -FilePath $LauncherPath `
        -ArgumentList @('-3.12', '-I', '--version') -TimeoutSeconds 30 `
        -CleanEnvironment -Environment (Get-IsolatedPythonEnvironment)
    $failureMessage = "Trusted Python launcher did not select the locked Python runtime: $LauncherPath"
    $null = Get-LockedVersionOutputMatch -StdOut $details.StdOut -StdErr $details.StdErr `
        -VersionRegex ([string]$PythonRuntime.versionRegex) -FailureMessage $failureMessage
}

function Assert-ExtractorVersion {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$ExtractorPath,
        [Parameter(Mandatory)][object]$ExtractorLock
    )

    $details = Invoke-CheckedProcess -FilePath $ExtractorPath -ArgumentList @('i') -TimeoutSeconds 30
    $failureMessage = "Verified extractor did not report the locked version: $ExtractorPath"
    $null = Get-LockedVersionOutputMatch -StdOut $details.StdOut -StdErr $details.StdErr `
        -VersionRegex ([string]$ExtractorLock.versionRegex) -FailureMessage $failureMessage
}

function Move-FlattenedTool {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$StagingRoot,
        [Parameter(Mandatory)][string]$RawRoot,
        [Parameter(Mandatory)][string]$ToolKey,
        [Parameter(Mandatory)][object]$ToolLock
    )

    Assert-NoReparsePoints -Root $RawRoot
    $children = @(Get-ChildItem -LiteralPath $RawRoot -Force)
    $sourceRoot = $RawRoot
    if ($children.Count -eq 1 -and $children[0] -is [System.IO.DirectoryInfo]) {
        $sourceRoot = $children[0].FullName
    }
    $destinationRoot = Resolve-ContainedPath -Root $StagingRoot -RelativePath "tools\$ToolKey"
    [System.IO.Directory]::CreateDirectory($destinationRoot) | Out-Null
    foreach ($child in @(Get-ChildItem -LiteralPath $sourceRoot -Force)) {
        if (($child.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Archive extraction contains a reparse point: $($child.FullName)"
        }
        $destination = Resolve-ContainedPath -Root $destinationRoot -RelativePath $child.Name
        if (Test-Path -LiteralPath $destination) {
            throw "Archive extraction duplicates a tool path: $destination"
        }
        Move-Item -LiteralPath $child.FullName -Destination $destination
    }
    Assert-NoReparsePoints -Root $destinationRoot
    Assert-InstalledToolInventory -ToolRoot $destinationRoot -ToolKey $ToolKey -ToolLock $ToolLock
    $entrypoint = Resolve-ContainedPath -Root $destinationRoot -RelativePath (($ToolLock.entrypoint) -replace '/', '\\')
    if (-not (Test-Path -LiteralPath $entrypoint -PathType Leaf)) {
        throw "Tool entrypoint is missing after extraction: $ToolKey"
    }
    Assert-AuthenticodeAsset -Asset $ToolLock -Path $entrypoint
    Remove-ProvenContainedDirectory -Root $StagingRoot -DirectoryPath $RawRoot
    return $entrypoint
}

function Install-LockedTool {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$StagingRoot,
        [Parameter(Mandatory)][string]$DownloadsRoot,
        [Parameter(Mandatory)][string]$ToolKey,
        [Parameter(Mandatory)][object]$ToolLock,
        [Parameter(Mandatory)][string]$ExtractorPath
    )

    $archive = Open-VerifiedAsset -Asset $ToolLock -DownloadsRoot $DownloadsRoot
    try {
        $rawRoot = Resolve-ContainedPath -Root $StagingRoot -RelativePath "extract-$ToolKey"
        [System.IO.Directory]::CreateDirectory($rawRoot) | Out-Null
        Assert-NoReparsePoints -Root $StagingRoot
        switch ([System.IO.Path]::GetExtension($archive.Path).ToLowerInvariant()) {
            '.zip' {
                Expand-SafeZipArchive -ArchivePath $archive.Path -DestinationRoot $rawRoot
                break
            }
            '.7z' {
                Expand-SafeSevenZipArchive -ArchivePath $archive.Path -SevenZipPath $ExtractorPath -DestinationRoot $rawRoot
                break
            }
            default {
                throw "Unsupported locked archive type: $($archive.Path)"
            }
        }
        return Move-FlattenedTool -StagingRoot $StagingRoot -RawRoot $rawRoot -ToolKey $ToolKey -ToolLock $ToolLock
    }
    finally {
        $archive.Stream.Dispose()
    }
}

function Test-Python312FileVersion {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Version)

    return -not [string]::IsNullOrWhiteSpace($Version) -and
        [System.Text.RegularExpressions.Regex]::IsMatch($Version, '(?<![0-9])3\.12(?:\.[0-9]+)*(?![0-9])')
}

function Assert-LockedPythonRuntime {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$PythonRoot,
        [Parameter(Mandatory)][object]$PythonRuntime
    )

    $pythonRootFull = [System.IO.Path]::GetFullPath($PythonRoot)
    if (-not (Test-Path -LiteralPath $pythonRootFull -PathType Container)) {
        throw "Python virtual environment does not exist: $pythonRootFull"
    }
    Assert-NoReparsePoints -Root $pythonRootFull
    $candidate = Resolve-ContainedPath -Root $pythonRootFull -RelativePath (
        Join-Path 'Scripts' ([string]$PythonRuntime.executable)
    )
    $candidateItem = Assert-RegularFile -Path $candidate
    Assert-NoReparsePoints -Root $pythonRootFull

    # Do not start the candidate interpreter until its executable trust boundary is checked.
    $publisher = Assert-AuthenticodeAsset -Asset $PythonRuntime -Path $candidateItem.FullName -PassThru
    $versionInfo = [System.Diagnostics.FileVersionInfo]::GetVersionInfo($candidateItem.FullName)
    foreach ($propertyName in @('FileVersion', 'ProductVersion')) {
        $versionValue = [string]$versionInfo.$propertyName
        if (-not (Test-Python312FileVersion -Version $versionValue)) {
            throw "Python runtime $propertyName is not a supported Python 3.12 version: $versionValue"
        }
    }

    Assert-NoReparsePoints -Root $pythonRootFull
    $details = Invoke-CheckedProcess -FilePath $candidateItem.FullName -ArgumentList @('-I', '--version') `
        -TimeoutSeconds 30 -CleanEnvironment -Environment (Get-IsolatedPythonEnvironment)
    $runtimeFailureMessage = "Verified Python runtime did not report the locked version: $($candidateItem.FullName)"
    $emptyVersionFailureMessage = "Verified Python runtime did not report a version line: $($candidateItem.FullName)"
    $runtimeVersion = Get-LockedVersionOutputMatch -StdOut $details.StdOut -StdErr $details.StdErr `
        -VersionRegex ([string]$PythonRuntime.versionRegex) -FailureMessage $runtimeFailureMessage `
        -EmptyMatchFailureMessage $emptyVersionFailureMessage
    Assert-NoReparsePoints -Root $pythonRootFull
    return [pscustomobject]@{
        Interpreter = $candidateItem.FullName
        RuntimeVersion = $runtimeVersion
        RuntimePublisher = [string]$publisher
    }
}

function Remove-PythonBytecodeArtifacts {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$PythonRoot)

    $pythonRootFull = [System.IO.Path]::GetFullPath($PythonRoot)
    if (-not (Test-Path -LiteralPath $pythonRootFull -PathType Container)) {
        throw "Python virtual environment does not exist: $pythonRootFull"
    }
    Assert-NoReparsePoints -Root $pythonRootFull
    $bytecodePaths = [System.Collections.Generic.List[string]]::new()
    $cacheDirectories = [System.Collections.Generic.List[string]]::new()
    foreach ($item in @(Get-ChildItem -LiteralPath $pythonRootFull -Force -Recurse)) {
        $relativePath = [System.IO.Path]::GetRelativePath($pythonRootFull, $item.FullName)
        $verifiedPath = Resolve-ContainedPath -Root $pythonRootFull -RelativePath $relativePath
        if (-not [string]::Equals($verifiedPath, $item.FullName, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Python bytecode path escapes its environment: $($item.FullName)"
        }
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Python bytecode cleanup found a reparse point: $($item.FullName)"
        }
        if ($item -is [System.IO.DirectoryInfo]) {
            if ($item.Name -ceq '__pycache__') {
                $cacheDirectories.Add($verifiedPath)
            }
            continue
        }
        if ($item.Extension -ceq '.pyc') {
            $null = Assert-RegularFile -Path $verifiedPath
            $bytecodePaths.Add($verifiedPath)
        }
    }
    foreach ($bytecodePath in $bytecodePaths) {
        Assert-NoReparsePoints -Root $pythonRootFull
        if (Test-Path -LiteralPath $bytecodePath -PathType Leaf) {
            Remove-VerifiedRegularFile -Root $pythonRootFull -Path $bytecodePath
        }
    }
    foreach ($cacheDirectory in @($cacheDirectories | Sort-Object { $_.Length } -Descending)) {
        Assert-NoReparsePoints -Root $pythonRootFull
        if (-not (Test-Path -LiteralPath $cacheDirectory -PathType Container)) {
            continue
        }
        $cacheItem = Get-Item -LiteralPath $cacheDirectory -Force
        if ($cacheItem -isnot [System.IO.DirectoryInfo] -or
            ($cacheItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Python bytecode cache is not a regular directory: $cacheDirectory"
        }
        $enumerator = [System.IO.Directory]::EnumerateFileSystemEntries($cacheItem.FullName).GetEnumerator()
        try {
            $isEmpty = -not $enumerator.MoveNext()
        }
        finally {
            $enumerator.Dispose()
        }
        if ($isEmpty) {
            [System.IO.Directory]::Delete($cacheItem.FullName, $false)
        }
    }
    Assert-NoReparsePoints -Root $pythonRootFull
}

function Install-LockedPython {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$StagingRoot,
        [Parameter(Mandatory)][string]$RequirementsPath,
        [AllowEmptyString()][string]$WheelCache = '',
        [Parameter(Mandatory)][object]$PythonRuntime
    )

    $pythonRoot = Resolve-ContainedPath -Root $StagingRoot -RelativePath 'python'
    $launcherPath = Resolve-TrustedPythonLauncher -PythonRuntime $PythonRuntime
    Assert-TrustedBasePythonRuntime -LauncherPath $launcherPath -PythonRuntime $PythonRuntime
    $null = Invoke-CheckedProcess -FilePath $launcherPath `
        -ArgumentList @('-3.12', '-I', '-m', 'venv', $pythonRoot) -TimeoutSeconds 120 `
        -CleanEnvironment -Environment (Get-IsolatedPythonEnvironment)
    $runtime = Assert-LockedPythonRuntime -PythonRoot $pythonRoot -PythonRuntime $PythonRuntime
    $python = $runtime.Interpreter
    $checkedPythonEnvironment = Get-IsolatedPythonEnvironment
    $installArguments = @(
        '-I', '-m', 'pip', '--isolated', 'install', '--require-hashes', '--only-binary=:all:',
        '--no-cache-dir', '--no-compile', '--disable-pip-version-check', '--no-input'
    )
    if ([string]::IsNullOrWhiteSpace($WheelCache)) {
        $installArguments += @('-r', $RequirementsPath)
    }
    else {
        $cacheFull = [System.IO.Path]::GetFullPath($WheelCache)
        if (-not (Test-Path -LiteralPath $cacheFull -PathType Container)) {
            throw "Wheel cache does not exist: $cacheFull"
        }
        Assert-NoReparsePoints -Root $cacheFull
        $installArguments += @('--no-index', '--find-links', $cacheFull, '-r', $RequirementsPath)
    }
    $null = Invoke-CheckedProcess -FilePath $python -ArgumentList $installArguments -TimeoutSeconds 1800 `
        -CleanEnvironment -Environment $checkedPythonEnvironment
    # Remove only individually proven regular bytecode files before the final Python command.
    Remove-PythonBytecodeArtifacts -PythonRoot $pythonRoot
    $freeze = Invoke-CheckedProcess -FilePath $python `
        -ArgumentList @('-I', '-m', 'pip', '--isolated', 'freeze', '--all', '--disable-pip-version-check', '--no-input') `
        -TimeoutSeconds 120 -CleanEnvironment -Environment $checkedPythonEnvironment
    Assert-NoReparsePoints -Root $pythonRoot
    $inventory = Get-DeterministicTreeInventory -Root $pythonRoot
    return [pscustomobject]@{
        Interpreter = $python
        Freeze = @($freeze.StdOut -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
        fileCount = [Int64]$inventory.fileCount
        treeSha256 = [string]$inventory.treeSha256
        RuntimeVersion = [string]$runtime.RuntimeVersion
        RuntimePublisher = [string]$runtime.RuntimePublisher
    }
}

function Copy-LockedModels {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$StagingRoot,
        [Parameter(Mandatory)][string]$DownloadsRoot,
        [Parameter(Mandatory)][object]$Models
    )

    $modelsRoot = Resolve-ContainedPath -Root $StagingRoot -RelativePath 'models'
    [System.IO.Directory]::CreateDirectory($modelsRoot) | Out-Null
    $relativeEntrypoints = [ordered]@{}
    foreach ($modelKey in @('isnet-anime', 'u2net_human_seg')) {
        $modelLock = $Models.$modelKey
        $downloaded = Open-VerifiedAsset -Asset $modelLock -DownloadsRoot $DownloadsRoot
        try {
            $normalisedEntrypoint = ([string]$modelLock.entrypoint) -replace '/', '\\'
            $fileName = [System.IO.Path]::GetFileName($normalisedEntrypoint)
            $target = Resolve-ContainedPath -Root $modelsRoot -RelativePath $fileName
            $target = Assert-ContainedWritePath -Root $modelsRoot -Path $target
            $destination = [System.IO.File]::Open(
                $target,
                [System.IO.FileMode]::CreateNew,
                [System.IO.FileAccess]::Write,
                [System.IO.FileShare]::None
            )
            try {
                $downloaded.Stream.CopyTo($destination)
                $destination.Flush($true)
            }
            finally {
                $destination.Dispose()
            }
            Assert-FileDigest -Path $target -ExpectedSize ([Int64]$modelLock.size) -ExpectedSha256 ([string]$modelLock.sha256)
            $relativeEntrypoints[$modelKey] = "models/$fileName"
        }
        finally {
            $downloaded.Stream.Dispose()
        }
    }
    Assert-NoReparsePoints -Root $modelsRoot
    return $relativeEntrypoints
}

function Write-Utf8FileAndFlush {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Text,
        [System.IO.FileStream]$Stream = $null
    )

    $fullPath = Assert-ContainedWritePath -Root $Root -Path $Path
    $bytes = [System.Text.UTF8Encoding]::new($false).GetBytes($Text)
    $ownsStream = $null -eq $Stream
    if ($ownsStream) {
        $Stream = [System.IO.File]::Open(
            $fullPath,
            [System.IO.FileMode]::CreateNew,
            [System.IO.FileAccess]::Write,
            [System.IO.FileShare]::None
        )
    }
    try {
        $Stream.Write($bytes, 0, $bytes.Length)
        $Stream.Flush($true)
    }
    finally {
        if ($ownsStream) {
            $Stream.Dispose()
        }
    }
}

function Get-PetToolchainPublishMutexName {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Root)

    $canonicalRoot = (Get-ComparablePath -Path $Root).ToLowerInvariant()
    $bytes = [System.Text.UTF8Encoding]::new($false).GetBytes($canonicalRoot)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $digest = ([System.BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
    }
    return "Local\DesktopCompanion.PetToolchain.Publish.$digest"
}

function Enter-PetToolchainPublishMutex {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Root,
        [ValidateRange(1, 600)][int]$TimeoutSeconds = 120
    )

    $mutex = [System.Threading.Mutex]::new($false, (Get-PetToolchainPublishMutexName -Root $Root))
    try {
        $acquired = $false
        try {
            $acquired = $mutex.WaitOne([System.TimeSpan]::FromSeconds($TimeoutSeconds))
        }
        catch [System.Threading.AbandonedMutexException] {
            $acquired = $true
            Write-Warning 'Recovered an abandoned pet-toolchain publication mutex.'
        }
        if (-not $acquired) {
            throw 'Timed out waiting for the pet-toolchain publication mutex.'
        }
        return $mutex
    }
    catch {
        $mutex.Dispose()
        throw
    }
}

function Assert-PublishableToolchainVersion {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][string]$LockDigest
    )

    $rootFull = [System.IO.Path]::GetFullPath($Root)
    Assert-NoReparsePoints -Root $rootFull
    $versionPath = Resolve-ContainedPath -Root $rootFull -RelativePath "versions\$LockDigest"
    if (-not (Test-Path -LiteralPath $versionPath -PathType Container)) {
        throw "Refusing to publish a missing version directory: $versionPath"
    }
    Assert-NoReparsePoints -Root $versionPath
    $relativeVersion = [System.IO.Path]::GetRelativePath($rootFull, $versionPath).Replace('\', '/')
    $expectedRelativeVersion = "versions/$LockDigest"
    if ($relativeVersion -cne $expectedRelativeVersion) {
        throw "Refusing to publish an unresolved version path: $versionPath"
    }
    $installedPath = Resolve-ContainedPath -Root $versionPath -RelativePath 'installed.json'
    $installedItem = Assert-RegularFile -Path $installedPath
    try {
        $installed = [System.IO.File]::ReadAllText($installedItem.FullName, [System.Text.UTF8Encoding]::new($false, $true)) |
            ConvertFrom-Json -Depth 16
    }
    catch {
        throw "Refusing to publish an unreadable installed manifest: $installedPath"
    }
    if ($null -eq $installed -or $null -eq $installed.PSObject.Properties['lockDigest'] -or
        $installed.lockDigest -cne $LockDigest) {
        throw "Refusing to publish a version with a mismatched installed manifest: $versionPath"
    }
    return [pscustomobject]@{
        VersionPath = $versionPath
        Pointer = [ordered]@{
            lockDigest = $LockDigest
            version = $expectedRelativeVersion
        }
    }
}

function Write-CurrentPointerAtomically {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][string]$LockDigest,
        [Parameter(Mandatory)][string]$TemporaryPath
    )

    $rootFull = [System.IO.Path]::GetFullPath($Root)
    $pointerPath = Resolve-ContainedPath -Root $rootFull -RelativePath 'current.json'
    $temporaryFull = Assert-ContainedWritePath -Root $rootFull -Path $TemporaryPath
    if ([System.IO.Path]::GetFileName($temporaryFull) -notmatch '^current\.json\.tmp\.[0-9a-f]{32}$') {
        throw "Refusing an invalid pointer temporary path: $temporaryFull"
    }

    $mutex = $null
    $temporaryOwned = $false
    try {
        $mutex = Enter-PetToolchainPublishMutex -Root $rootFull
        $publication = Assert-PublishableToolchainVersion -Root $rootFull -LockDigest $LockDigest
        $reservation = [System.IO.File]::Open(
            $temporaryFull,
            [System.IO.FileMode]::CreateNew,
            [System.IO.FileAccess]::Write,
            [System.IO.FileShare]::None
        )
        $temporaryOwned = $true
        try {
            Write-Utf8FileAndFlush -Root $rootFull -Path $temporaryFull -Text ($publication.Pointer | ConvertTo-Json -Depth 4) -Stream $reservation
        }
        finally {
            $reservation.Dispose()
        }

        $publication = Assert-PublishableToolchainVersion -Root $rootFull -LockDigest $LockDigest
        if (Test-Path -LiteralPath $pointerPath) {
            $null = Assert-RegularFile -Path $pointerPath
            [System.IO.File]::Move($temporaryFull, $pointerPath, $true)
        }
        else {
            [System.IO.File]::Move($temporaryFull, $pointerPath)
        }
        $temporaryOwned = $false
    }
    catch {
        if ($temporaryOwned -and (Test-Path -LiteralPath $temporaryFull)) {
            Remove-VerifiedRegularFile -Root $rootFull -Path $temporaryFull
        }
        throw
    }
    finally {
        if ($null -ne $mutex) {
            try {
                $mutex.ReleaseMutex()
            }
            catch {
                Write-Warning 'Could not release the pet-toolchain publication mutex after publication handling.'
            }
            finally {
                try {
                    $mutex.Dispose()
                }
                catch {
                    Write-Warning 'Could not dispose the pet-toolchain publication mutex after publication handling.'
                }
            }
        }
    }
}

function Invoke-ToolchainVerification {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$VerifierPath,
        [Parameter(Mandatory)][string]$ToolRoot,
        [Parameter(Mandatory)][string]$CandidateRoot,
        [Parameter(Mandatory)][string]$QtPython
    )

    $canonicalToolRoot = Get-ComparablePath -Path $ToolRoot
    $null = Assert-NumbaCachePathBudget -ToolRoot $canonicalToolRoot
    $hostName = if (Test-Path -LiteralPath (Join-Path $PSHOME 'pwsh.exe') -PathType Leaf) {
        'pwsh.exe'
    }
    else {
        'powershell.exe'
    }
    $hostPath = Join-Path $PSHOME $hostName
    if (-not (Test-Path -LiteralPath $hostPath -PathType Leaf)) {
        throw 'Could not locate the current PowerShell host for verification'
    }
    $null = Invoke-CheckedProcess -FilePath $hostPath -ArgumentList @(
        '-NoLogo', '-NoProfile', '-NonInteractive', '-File', $VerifierPath,
        '-ToolRoot', $canonicalToolRoot, '-CandidateRoot', $CandidateRoot,
        '-NoCurrentPointer', '-QtPython', $QtPython
    ) -TimeoutSeconds 1800
}

function Invoke-PetToolchainSetup {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$ToolRoot,
        [Parameter(Mandatory)][string]$LockPath,
        [Parameter(Mandatory)][string]$RequirementsPath,
        [Parameter(Mandatory)][string]$QtPython,
        [string]$WheelCache = '',
        [string]$VerifierPath = (Join-Path $PSScriptRoot 'verify_pet_toolchain.ps1')
    )

    $repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
    if (-not (Test-Path -LiteralPath $VerifierPath -PathType Leaf)) {
        throw "Verification script is unavailable; refusing to create or publish a toolchain: $VerifierPath"
    }

    $toolRootFull = Assert-SafeToolRoot -Candidate $ToolRoot -RepositoryRoot $repositoryRoot
    $lockFull = [System.IO.Path]::GetFullPath($LockPath)
    $requirementsFull = [System.IO.Path]::GetFullPath($RequirementsPath)
    $lock = Read-PetToolchainLock -LockPath $lockFull
    $lockDigest = Get-LockDigest -LockPath $lockFull -RequirementsPath $requirementsFull

    [System.IO.Directory]::CreateDirectory($toolRootFull) | Out-Null
    Assert-NoReparsePoints -Root $toolRootFull
    if (Test-CurrentToolchainDigest -Root $toolRootFull -LockDigest $lockDigest) {
        Write-Output "Pet toolchain $lockDigest is already current."
        return
    }

    $stagingPath = ''
    $unpublishedVersionPath = ''
    $versionOwned = $false
    $pointerTemporaryPath = ''
    $pointerPublished = $false
    try {
        $downloadsRoot = Resolve-ContainedPath -Root $toolRootFull -RelativePath 'downloads'
        [System.IO.Directory]::CreateDirectory($downloadsRoot) | Out-Null
        Assert-NoReparsePoints -Root $downloadsRoot

        $stagingName = "staging-$([System.Guid]::NewGuid().ToString('N'))"
        $stagingPath = Resolve-ContainedPath -Root $toolRootFull -RelativePath $stagingName
        [System.IO.Directory]::CreateDirectory($stagingPath) | Out-Null
        Assert-NoReparsePoints -Root $stagingPath

        $extractor = Open-VerifiedAsset -Asset $lock.extractor -DownloadsRoot $downloadsRoot
        try {
            Assert-ExtractorVersion -ExtractorPath $extractor.Path -ExtractorLock $lock.extractor

            $toolEntrypoints = [ordered]@{}
            foreach ($toolKey in @('ffmpeg', 'imagemagick', 'libwebp')) {
                $entrypoint = Install-LockedTool -StagingRoot $stagingPath -DownloadsRoot $downloadsRoot -ToolKey $toolKey -ToolLock $lock.tools.$toolKey -ExtractorPath $extractor.Path
                $toolEntrypoints[$toolKey] = [System.IO.Path]::GetRelativePath($stagingPath, $entrypoint).Replace('\', '/')
            }
        }
        finally {
            $extractor.Stream.Dispose()
        }
        $python = Install-LockedPython -StagingRoot $stagingPath -RequirementsPath $requirementsFull `
            -WheelCache $WheelCache -PythonRuntime $lock.pythonRuntime
        $modelEntrypoints = Copy-LockedModels -StagingRoot $stagingPath -DownloadsRoot $downloadsRoot -Models $lock.models

        $installedManifest = [ordered]@{
            lockDigest = $lockDigest
            assets = [ordered]@{
                extractor = [ordered]@{ sha256 = $lock.extractor.sha256; size = $lock.extractor.size }
                tools = [ordered]@{}
                models = [ordered]@{}
            }
            python = [ordered]@{
                interpreter = 'python/Scripts/python.exe'
                freeze = @($python.Freeze)
                fileCount = [Int64]$python.fileCount
                treeSha256 = [string]$python.treeSha256
                runtimeVersion = [string]$python.RuntimeVersion
                runtimePublisher = [string]$python.RuntimePublisher
            }
            entrypoints = [ordered]@{
                tools = $toolEntrypoints
                models = $modelEntrypoints
            }
        }
        foreach ($toolKey in @('ffmpeg', 'imagemagick', 'libwebp')) {
            $installedManifest.assets.tools[$toolKey] = [ordered]@{
                sha256 = $lock.tools.$toolKey.sha256
                size = $lock.tools.$toolKey.size
            }
        }
        foreach ($modelKey in @('isnet-anime', 'u2net_human_seg')) {
            $installedManifest.assets.models[$modelKey] = [ordered]@{
                sha256 = $lock.models.$modelKey.sha256
                size = $lock.models.$modelKey.size
            }
        }
        $installedPath = Resolve-ContainedPath -Root $stagingPath -RelativePath 'installed.json'
        Write-Utf8FileAndFlush -Root $stagingPath -Path $installedPath -Text ($installedManifest | ConvertTo-Json -Depth 16)
        Assert-NoReparsePoints -Root $stagingPath

        Invoke-ToolchainVerification -VerifierPath $VerifierPath -ToolRoot $toolRootFull `
            -CandidateRoot $stagingPath -QtPython $QtPython

        $versionsRoot = Resolve-ContainedPath -Root $toolRootFull -RelativePath 'versions'
        [System.IO.Directory]::CreateDirectory($versionsRoot) | Out-Null
        Assert-NoReparsePoints -Root $versionsRoot
        $versionDestinationPath = Resolve-ContainedPath -Root $toolRootFull -RelativePath "versions\$lockDigest"
        if (Test-Path -LiteralPath $versionDestinationPath) {
            throw "Refusing to replace an existing version directory: $versionDestinationPath"
        }
        try {
            [System.IO.Directory]::Move($stagingPath, $versionDestinationPath)
            $versionOwned = $true
            $unpublishedVersionPath = $versionDestinationPath
            $stagingPath = ''
        }
        catch {
            if (Test-Path -LiteralPath $versionDestinationPath) {
                throw "Version destination was claimed by another invocation: $versionDestinationPath"
            }
            throw
        }
        Assert-NoReparsePoints -Root $unpublishedVersionPath
        Invoke-ToolchainVerification -VerifierPath $VerifierPath -ToolRoot $toolRootFull `
            -CandidateRoot $unpublishedVersionPath -QtPython $QtPython

        $pointerTemporaryPath = Resolve-ContainedPath -Root $toolRootFull -RelativePath "current.json.tmp.$([System.Guid]::NewGuid().ToString('N'))"
        Write-CurrentPointerAtomically -Root $toolRootFull -LockDigest $lockDigest -TemporaryPath $pointerTemporaryPath
        $pointerPublished = $true
        $pointerTemporaryPath = ''
        $unpublishedVersionPath = ''
        $versionOwned = $false
        Write-Output "Installed and published pet toolchain $lockDigest."
    }
    catch {
        $failure = $_
        $cleanupCandidates = @($stagingPath)
        if ($versionOwned -and -not $pointerPublished) {
            $cleanupCandidates += $unpublishedVersionPath
        }
        foreach ($candidate in $cleanupCandidates) {
            if ([string]::IsNullOrWhiteSpace($candidate)) {
                continue
            }
            try {
                Remove-ProvenContainedDirectory -Root $toolRootFull -DirectoryPath $candidate
            }
            catch {
                Write-Warning "Preserved unresolved failed-install directory: $candidate"
            }
        }
        throw $failure
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    Invoke-PetToolchainSetup -ToolRoot $ToolRoot -LockPath $LockPath -RequirementsPath $RequirementsPath `
        -WheelCache $WheelCache -QtPython $QtPython
}
