[CmdletBinding()]
param(
    [string]$ToolRoot = (Join-Path $env:LOCALAPPDATA 'DesktopCompanionDev\pet-toolchain'),
    [string]$CandidateRoot = '',
    [switch]$NoCurrentPointer,
    [string]$LockPath = (Join-Path $PSScriptRoot '..\tools\pet-toolchain.lock.json'),
    [string]$RequirementsPath = (Join-Path $PSScriptRoot '..\requirements\pet-media.txt'),
    [Parameter(Mandatory)][string]$QtPython
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'pet_toolchain_common.ps1')


function Assert-RegularFile {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Path)

    $item = Get-Item -LiteralPath $Path -Force
    if ($item -is [System.IO.DirectoryInfo] -or
        ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Expected a regular file: $Path"
    }
    return $item
}


function Assert-RegularDirectoryAndAncestors {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Path)

    $full = [System.IO.Path]::GetFullPath($Path)
    $item = Get-Item -LiteralPath $full -Force
    if ($item -isnot [System.IO.DirectoryInfo] -or
        ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Expected a regular directory: $full"
    }
    $current = $item
    while ($null -ne $current) {
        if (($current.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Reparse point is not allowed in a verification-root ancestor: $($current.FullName)"
        }
        $current = $current.Parent
    }
    Assert-NoReparsePoints -Root $full
    return $full
}


function Assert-JsonElementNoDuplicateProperties {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][System.Text.Json.JsonElement]$Element,
        [Parameter(Mandatory)][string]$Context
    )

    if ($Element.ValueKind -eq [System.Text.Json.JsonValueKind]::Object) {
        $names = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
        foreach ($property in $Element.EnumerateObject()) {
            if (-not $names.Add($property.Name)) {
                throw "$Context contains a duplicate JSON property: $($property.Name)"
            }
            Assert-JsonElementNoDuplicateProperties -Element $property.Value -Context $Context
        }
        return
    }
    if ($Element.ValueKind -eq [System.Text.Json.JsonValueKind]::Array) {
        foreach ($value in $Element.EnumerateArray()) {
            Assert-JsonElementNoDuplicateProperties -Element $value -Context $Context
        }
        return
    }
    if ($Element.ValueKind -eq [System.Text.Json.JsonValueKind]::Number) {
        $number = 0.0
        if (-not $Element.TryGetDouble([ref]$number) -or [double]::IsNaN($number) -or [double]::IsInfinity($number)) {
            throw "$Context contains a non-finite JSON number"
        }
    }
}


function ConvertFrom-ExactlyOneJsonObject {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$StdOut,
        [Parameter(Mandatory)][string]$Context
    )

    if ($StdOut.Length -gt 0 -and $StdOut[0] -eq [char]0xFEFF) {
        throw "$Context stdout must not contain a UTF-8 byte-order mark"
    }
    $options = [System.Text.Json.JsonDocumentOptions]::new()
    $options.AllowTrailingCommas = $false
    $options.CommentHandling = [System.Text.Json.JsonCommentHandling]::Disallow
    $options.MaxDepth = 32
    try {
        $document = [System.Text.Json.JsonDocument]::Parse($StdOut, $options)
    }
    catch {
        throw "$Context stdout must be exactly one UTF-8 JSON object"
    }
    try {
        if ($document.RootElement.ValueKind -ne [System.Text.Json.JsonValueKind]::Object) {
            throw "$Context stdout must be exactly one UTF-8 JSON object"
        }
        Assert-JsonElementNoDuplicateProperties -Element $document.RootElement -Context $Context
        try {
            $value = $document.RootElement.GetRawText() | ConvertFrom-Json -Depth 32 -NoEnumerate
        }
        catch {
            throw "$Context stdout must be exactly one UTF-8 JSON object"
        }
        if ($null -eq $value -or $value -is [System.Array]) {
            throw "$Context stdout must be exactly one UTF-8 JSON object"
        }
        return $value
    }
    finally {
        $document.Dispose()
    }
}


function Read-StrictJsonFile {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Context
    )

    $item = Assert-RegularFile -Path $Path
    $bytes = [System.IO.File]::ReadAllBytes($item.FullName)
    if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
        throw "$Context must not contain a UTF-8 byte-order mark: $Path"
    }
    $encoding = [System.Text.UTF8Encoding]::new($false, $true)
    try {
        $text = $encoding.GetString($bytes)
    }
    catch {
        throw "$Context is not valid UTF-8: $Path"
    }
    return ConvertFrom-ExactlyOneJsonObject -StdOut $text -Context $Context
}


function Assert-JsonString {
    [CmdletBinding()]
    param([Parameter(Mandatory)]$Value, [Parameter(Mandatory)][string]$Context)

    if ($Value -isnot [string] -or [string]::IsNullOrWhiteSpace($Value)) {
        throw "$Context must be a nonempty JSON string"
    }
    return [string]$Value
}


function Assert-JsonBoolean {
    [CmdletBinding()]
    param([Parameter(Mandatory)]$Value, [Parameter(Mandatory)][string]$Context)

    if ($Value -isnot [bool]) {
        throw "$Context must be a JSON boolean"
    }
    return [bool]$Value
}


function Assert-JsonInteger {
    [CmdletBinding()]
    param([Parameter(Mandatory)]$Value, [Parameter(Mandatory)][string]$Context)

    if ($Value -isnot [byte] -and $Value -isnot [sbyte] -and $Value -isnot [int16] -and
        $Value -isnot [uint16] -and $Value -isnot [int32] -and $Value -isnot [uint32] -and
        $Value -isnot [int64] -and $Value -isnot [uint64]) {
        throw "$Context must be a JSON integer"
    }
    return [Int64]$Value
}


function Resolve-VerificationCandidate {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][string]$LockDigest,
        [AllowEmptyString()][string]$ConfiguredCandidateRoot,
        [Parameter(Mandatory)][bool]$SkipCurrentPointer
    )

    if (-not [string]::IsNullOrWhiteSpace($ConfiguredCandidateRoot)) {
        $candidateFull = [System.IO.Path]::GetFullPath($ConfiguredCandidateRoot)
        $relative = [System.IO.Path]::GetRelativePath($Root, $candidateFull)
        if ([System.IO.Path]::IsPathRooted($relative) -or $relative -eq '..' -or $relative.StartsWith('..\', [System.StringComparison]::Ordinal)) {
            throw 'Candidate path escapes tool root'
        }
        $candidate = Resolve-ContainedPath -Root $Root -RelativePath $relative
        $null = Assert-RegularDirectoryAndAncestors -Path $candidate
        return $candidate
    }
    if ($SkipCurrentPointer) {
        throw '-NoCurrentPointer requires -CandidateRoot'
    }
    $pointerPath = Resolve-ContainedPath -Root $Root -RelativePath 'current.json'
    $pointer = Read-StrictJsonFile -Path $pointerPath -Context 'current pointer'
    Assert-ExactObjectKeys -Object $pointer -Expected @('lockDigest', 'version') -Context 'current pointer'
    if ((Assert-JsonString -Value $pointer.lockDigest -Context 'current pointer lockDigest') -cne $LockDigest) {
        throw 'Current pointer lock digest does not match the lock'
    }
    $version = Assert-JsonString -Value $pointer.version -Context 'current pointer version'
    $normalisedVersion = $version.Replace('\', '/')
    $expectedVersion = "versions/$LockDigest"
    if ($normalisedVersion -cne $expectedVersion) {
        throw 'Current pointer version does not exactly match the locked version directory'
    }
    $candidate = Resolve-ContainedPath -Root $Root -RelativePath $version
    $null = Assert-RegularDirectoryAndAncestors -Path $candidate
    return $candidate
}


function Assert-AssetRecordMatchesLock {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][object]$Record,
        [Parameter(Mandatory)][object]$LockedAsset,
        [Parameter(Mandatory)][string]$Context
    )

    Assert-ExactObjectKeys -Object $Record -Expected @('sha256', 'size') -Context "$Context manifest record"
    if ((Assert-JsonString -Value $Record.sha256 -Context "$Context SHA-256") -cne [string]$LockedAsset.sha256 -or
        (Assert-JsonInteger -Value $Record.size -Context "$Context size") -ne [Int64]$LockedAsset.size) {
        throw "$Context manifest size or SHA-256 does not match the lock"
    }
}


function Resolve-ManifestEntrypoint {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$CandidateRoot,
        [Parameter(Mandatory)]$Value,
        [Parameter(Mandatory)][string]$ExpectedRelativePath,
        [Parameter(Mandatory)][string]$Context
    )

    $entrypoint = Assert-JsonString -Value $Value -Context "$Context entrypoint"
    $resolved = Resolve-ContainedPath -Root $CandidateRoot -RelativePath $entrypoint
    if ($entrypoint.Replace('\', '/') -cne $ExpectedRelativePath) {
        throw "$Context entrypoint does not match the locked layout"
    }
    return $resolved
}


function Read-InstalledManifest {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$CandidateRoot,
        [Parameter(Mandatory)][object]$Lock,
        [Parameter(Mandatory)][string]$LockDigest
    )

    $installedPath = Resolve-ContainedPath -Root $CandidateRoot -RelativePath 'installed.json'
    $installed = Read-StrictJsonFile -Path $installedPath -Context 'installed manifest'
    Assert-ExactObjectKeys -Object $installed -Expected @('lockDigest', 'assets', 'python', 'entrypoints') -Context 'installed manifest'
    if ((Assert-JsonString -Value $installed.lockDigest -Context 'installed manifest lockDigest') -cne $LockDigest) {
        throw 'Installed manifest lock digest does not match the lock'
    }
    Assert-ExactObjectKeys -Object $installed.assets -Expected @('extractor', 'tools', 'models') -Context 'installed manifest assets'
    Assert-AssetRecordMatchesLock -Record $installed.assets.extractor -LockedAsset $Lock.extractor -Context 'extractor'
    Assert-ExactObjectKeys -Object $installed.assets.tools -Expected @('ffmpeg', 'imagemagick', 'libwebp', 'rife') -Context 'installed tool assets'
    foreach ($toolName in @('ffmpeg', 'imagemagick', 'libwebp', 'rife')) {
        Assert-AssetRecordMatchesLock -Record $installed.assets.tools.$toolName -LockedAsset $Lock.tools.$toolName -Context "tool $toolName"
    }
    Assert-ExactObjectKeys -Object $installed.assets.models -Expected @('isnet-anime', 'u2net_human_seg') -Context 'installed model assets'
    foreach ($modelName in @('isnet-anime', 'u2net_human_seg')) {
        Assert-AssetRecordMatchesLock -Record $installed.assets.models.$modelName -LockedAsset $Lock.models.$modelName -Context "model $modelName"
    }
    Assert-ExactObjectKeys -Object $installed.python -Expected @('interpreter', 'freeze', 'fileCount', 'treeSha256', 'runtimeVersion', 'runtimePublisher') -Context 'installed Python record'
    $null = Assert-JsonString -Value $installed.python.interpreter -Context 'installed Python interpreter'
    if ($installed.python.freeze -is [string] -or $installed.python.freeze -isnot [System.Array]) {
        throw 'Installed Python freeze must be a JSON array'
    }
    foreach ($freezeRecord in @($installed.python.freeze)) {
        $null = Assert-JsonString -Value $freezeRecord -Context 'installed Python freeze record'
    }
    if ((Assert-JsonInteger -Value $installed.python.fileCount -Context 'installed Python fileCount') -lt 1 -or
        (Assert-JsonString -Value $installed.python.treeSha256 -Context 'installed Python treeSha256') -notmatch '^[0-9a-f]{64}$' -or
        (Assert-JsonString -Value $installed.python.runtimeVersion -Context 'installed Python runtimeVersion') -notmatch '^Python 3\.12\.\d+$' -or
        [string]::IsNullOrWhiteSpace((Assert-JsonString -Value $installed.python.runtimePublisher -Context 'installed Python runtimePublisher'))) {
        throw 'Installed Python runtime record is malformed'
    }
    Assert-ExactObjectKeys -Object $installed.entrypoints -Expected @('tools', 'models') -Context 'installed entrypoints'
    Assert-ExactObjectKeys -Object $installed.entrypoints.tools -Expected @('ffmpeg', 'imagemagick', 'libwebp', 'rife') -Context 'installed tool entrypoints'
    Assert-ExactObjectKeys -Object $installed.entrypoints.models -Expected @('isnet-anime', 'u2net_human_seg') -Context 'installed model entrypoints'
    return $installed
}


function Assert-InstalledToolInventory {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$ToolRoot,
        [Parameter(Mandatory)][object]$Tool,
        [Parameter(Mandatory)][string]$Context
    )

    $toolRootFull = Assert-RegularDirectoryAndAncestors -Path $ToolRoot
    if ($Tool.installedFiles -isnot [System.Management.Automation.PSCustomObject]) {
        throw "$Context lock inventory is malformed"
    }
    $expected = [System.Collections.Generic.Dictionary[string, object]]::new([System.StringComparer]::Ordinal)
    foreach ($property in $Tool.installedFiles.PSObject.Properties) {
        $relative = [string]$property.Name
        $safe = (Assert-SafeArchivePath -EntryName $relative).Replace('\', '/')
        if ($relative -cne $safe -or -not $expected.TryAdd($relative, $property.Value)) {
            throw "$Context lock inventory contains an invalid path"
        }
        Assert-ExactObjectKeys -Object $property.Value -Expected @('size', 'sha256') -Context "$Context inventory $relative"
        $null = Assert-JsonInteger -Value $property.Value.size -Context "$Context inventory size"
        if ((Assert-JsonString -Value $property.Value.sha256 -Context "$Context inventory SHA-256") -notmatch '^[0-9a-f]{64}$') {
            throw "$Context lock inventory has an invalid SHA-256"
        }
    }
    $actual = [System.Collections.Generic.Dictionary[string, string]]::new([System.StringComparer]::Ordinal)
    foreach ($item in @(Get-ChildItem -LiteralPath $toolRootFull -Force -Recurse)) {
        if ($item -is [System.IO.DirectoryInfo]) {
            if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "$Context tool inventory contains a reparse-point directory"
            }
            continue
        }
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "$Context tool inventory contains a reparse-point file"
        }
        $relative = [System.IO.Path]::GetRelativePath($toolRootFull, $item.FullName).Replace('\', '/')
        $safe = (Assert-SafeArchivePath -EntryName $relative).Replace('\', '/')
        $null = Resolve-ContainedPath -Root $toolRootFull -RelativePath ($relative.Replace('/', '\'))
        if ($relative -cne $safe -or -not $actual.TryAdd($relative, $item.FullName)) {
            throw "$Context tool inventory contains an invalid file path"
        }
    }
    if ($actual.Count -ne $expected.Count) {
        throw "$Context tool inventory has unexpected or missing files"
    }
    foreach ($relative in $expected.Keys) {
        if (-not $actual.ContainsKey($relative)) {
            throw "$Context tool inventory is missing locked file: $relative"
        }
        $record = $expected[$relative]
        Assert-FileDigest -Path $actual[$relative] -ExpectedSize (Assert-JsonInteger -Value $record.size -Context "$Context inventory size") -ExpectedSha256 (Assert-JsonString -Value $record.sha256 -Context "$Context inventory SHA-256")
    }
    Assert-NoReparsePoints -Root $toolRootFull
}


function Assert-AuthenticodePolicy {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][object]$Policy,
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Context
    )

    if (-not [bool]$Policy.required) {
        return ''
    }
    $signature = Get-AuthenticodeSignature -FilePath $Path
    if ($signature.Status -ne 'Valid' -or $null -eq $signature.SignerCertificate) {
        throw "Authenticode validation failed for ${Context}: $Path"
    }
    $publisher = $signature.SignerCertificate.Subject
    if ($publisher -notin @($Policy.publishers)) {
        throw "Unexpected Authenticode publisher for ${Context}: $Path"
    }
    return $publisher
}


function Assert-VersionOutput {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string[]]$ArgumentList,
        [Parameter(Mandatory)][string]$VersionRegex,
        [Parameter(Mandatory)][string]$Context,
        [hashtable]$Environment = @{},
        [switch]$CleanEnvironment
    )

    $details = Invoke-CheckedProcess -FilePath $Path -ArgumentList $ArgumentList -TimeoutSeconds 60 -Environment $Environment -CleanEnvironment:$CleanEnvironment
    $failureMessage = "$Context did not report the locked version: $Path"
    return Get-LockedVersionOutputMatch -StdOut $details.StdOut -StdErr $details.StdErr -VersionRegex $VersionRegex -FailureMessage $failureMessage
}


function Assert-RifeInterface {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$UsageRegex
    )

    $details = Invoke-CheckedProcess -FilePath $Path -ArgumentList @('-h') -TimeoutSeconds 60 -ExpectedExitCode @(-1)
    return Get-LockedVersionOutputMatch -StdOut $details.StdOut -StdErr $details.StdErr -VersionRegex $UsageRegex -FailureMessage "RIFE did not report the locked command interface: $Path"
}


function Assert-PythonRuntime {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$CandidateRoot,
        [Parameter(Mandatory)][object]$InstalledPython,
        [Parameter(Mandatory)][object]$RuntimePolicy
    )

    Assert-PythonRuntimePolicy -Runtime $RuntimePolicy
    $pythonPath = Resolve-ManifestEntrypoint -CandidateRoot $CandidateRoot -Value $InstalledPython.interpreter -ExpectedRelativePath 'python/Scripts/python.exe' -Context 'Python'
    $null = Assert-RegularFile -Path $pythonPath
    $pythonRoot = Resolve-ContainedPath -Root $CandidateRoot -RelativePath 'python'
    $inventory = Get-DeterministicTreeInventory -Root $pythonRoot
    if ([Int64]$inventory.fileCount -ne (Assert-JsonInteger -Value $InstalledPython.fileCount -Context 'installed Python fileCount') -or
        [string]$inventory.treeSha256 -cne (Assert-JsonString -Value $InstalledPython.treeSha256 -Context 'installed Python treeSha256')) {
        throw 'Candidate Python tree inventory does not match installed manifest'
    }
    $publisher = Assert-AuthenticodePolicy -Policy $RuntimePolicy.authenticode -Path $pythonPath -Context 'Python runtime'
    $versionInfo = (Get-Item -LiteralPath $pythonPath -Force).VersionInfo
    if ([string]$versionInfo.FileVersion -notmatch '(?<!\d)3\.12\.\d+' -or [string]$versionInfo.ProductVersion -notmatch '(?<!\d)3\.12\.\d+') {
        throw 'Candidate Python FileVersion/ProductVersion is not Python 3.12'
    }
    if ($publisher -cne (Assert-JsonString -Value $InstalledPython.runtimePublisher -Context 'installed Python runtimePublisher')) {
        throw 'Candidate Python runtime publisher does not match installed manifest'
    }
    return [pscustomobject]@{ PythonPath = $pythonPath; PythonRoot = $pythonRoot; Inventory = $inventory }
}


function Assert-PythonEnvironment {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$PythonPath,
        [Parameter(Mandatory)][object[]]$ExpectedFreeze,
        [Parameter(Mandatory)][string]$RuntimeVersion,
        [Parameter(Mandatory)][string]$VersionRegex
    )

    $environment = @{ PYTHONDONTWRITEBYTECODE = '1' }
    $actualVersion = Assert-VersionOutput -Path $PythonPath -ArgumentList @('-I', '-B', '--version') -VersionRegex $VersionRegex -Context 'Python runtime' -Environment $environment -CleanEnvironment
    if ($actualVersion -cne $RuntimeVersion) {
        throw 'Candidate Python runtime version does not match installed manifest'
    }
    $freeze = Invoke-CheckedProcess -FilePath $PythonPath -ArgumentList @('-I', '-B', '-m', 'pip', '--isolated', 'freeze', '--all') -TimeoutSeconds 120 -Environment $environment -CleanEnvironment
    $actual = @($freeze.StdOut -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    $expected = @($ExpectedFreeze | ForEach-Object { [string]$_ })
    if ($actual.Count -ne $expected.Count) {
        throw 'Candidate Python package freeze does not match installed manifest'
    }
    for ($index = 0; $index -lt $actual.Count; $index++) {
        if ($actual[$index] -cne $expected[$index]) {
            throw 'Candidate Python package freeze does not match installed manifest'
        }
    }
}


function New-VerificationWorkspace {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Root)

    $verifyRoot = Resolve-ContainedPath -Root $Root -RelativePath 'verify'
    $verifyRootCreated = $false
    if (Test-Path -LiteralPath $verifyRoot) {
        $null = Assert-RegularDirectoryAndAncestors -Path $verifyRoot
    }
    else {
        $verifyRoot = Assert-ContainedWritePath -Root $Root -Path $verifyRoot
        [System.IO.Directory]::CreateDirectory($verifyRoot) | Out-Null
        $verifyRootCreated = $true
    }
    $workspace = Resolve-ContainedPath -Root $verifyRoot -RelativePath "verify-$([Guid]::NewGuid().ToString('N'))"
    $workspace = Assert-ContainedWritePath -Root $verifyRoot -Path $workspace
    [System.IO.Directory]::CreateDirectory($workspace) | Out-Null
    $mediaWorkspace = Resolve-ContainedPath -Root $workspace -RelativePath "media-$([Guid]::NewGuid().ToString('N'))"
    if (Test-Path -LiteralPath $mediaWorkspace) {
        throw "Verification media workspace unexpectedly exists: $mediaWorkspace"
    }
    return [pscustomobject]@{ VerifyRoot = $verifyRoot; Workspace = $workspace; MediaWorkspace = $mediaWorkspace; VerifyRootCreated = $verifyRootCreated }
}


function Initialize-OwnedNumbaCacheDeletionType {
    if ($null -ne ('DesktopCompanionPetToolchain.OwnedNumbaCacheDeletionPlan' -as [type])) {
        return
    }
    Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text.RegularExpressions;
using Microsoft.Win32.SafeHandles;

namespace DesktopCompanionPetToolchain
{
    public sealed class OwnedNumbaCacheDeletionPlan : IDisposable
    {
        private const uint DELETE = 0x00010000;
        private const uint FILE_READ_ATTRIBUTES = 0x00000080;
        private const uint FILE_SHARE_READ = 0x00000001;
        private const uint FILE_SHARE_WRITE = 0x00000002;
        private const uint FILE_SHARE_DELETE = 0x00000004;
        private const uint OPEN_EXISTING = 3;
        private const uint FILE_ATTRIBUTE_DIRECTORY = 0x00000010;
        private const uint FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400;
        private const uint FILE_FLAG_BACKUP_SEMANTICS = 0x02000000;
        private const uint FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000;
        private const int FILE_DISPOSITION_INFO_CLASS = 4;
        private const uint OBJ_CASE_INSENSITIVE = 0x00000040;
        private const uint FILE_DIRECTORY_FILE = 0x00000001;
        private const uint FILE_NON_DIRECTORY_FILE = 0x00000040;
        private const uint NT_FILE_OPEN_REPARSE_POINT = 0x00200000;

        private static readonly Regex ModulePattern = new Regex(
            @"^[A-Za-z_][A-Za-z0-9_]*_[0-9a-f]{40}$",
            RegexOptions.CultureInvariant);
        private static readonly Regex FilePattern = new Regex(
            @"^[A-Za-z0-9_][A-Za-z0-9_.-]*\.(?:nbi|nbc)$",
            RegexOptions.CultureInvariant);
        private static readonly Regex MediaDirectoryPattern = new Regex(
            @"^media-[0-9a-f]{32}$",
            RegexOptions.CultureInvariant);
        private static readonly Regex MediaTemporaryPattern = new Regex(
            @"^result\.json\.tmp-[0-9a-f]{32}$",
            RegexOptions.CultureInvariant);
        private static readonly HashSet<string> MediaFileNames = new HashSet<string>(
            new[]
            {
                "source.png",
                "cutout-isnet-anime.png",
                "cutout-u2net_human_seg.png",
                "cutout-isnet-anime.webp",
                "preview.webp",
                "result.json",
                "preview-input-01.png",
                "preview-input-02.png",
                "preview-input-03.png",
                "preview-input-04.png",
                "preview-extract-01.png",
                "preview-extract-02.png",
                "preview-extract-03.png",
                "preview-extract-04.png",
                "rife-first.png",
                "rife-second.png",
                "rife-mid.png"
            },
            StringComparer.Ordinal);

        [StructLayout(LayoutKind.Sequential)]
        private struct BY_HANDLE_FILE_INFORMATION
        {
            public uint FileAttributes;
            public System.Runtime.InteropServices.ComTypes.FILETIME CreationTime;
            public System.Runtime.InteropServices.ComTypes.FILETIME LastAccessTime;
            public System.Runtime.InteropServices.ComTypes.FILETIME LastWriteTime;
            public uint VolumeSerialNumber;
            public uint FileSizeHigh;
            public uint FileSizeLow;
            public uint NumberOfLinks;
            public uint FileIndexHigh;
            public uint FileIndexLow;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct FILE_DISPOSITION_INFO
        {
            [MarshalAs(UnmanagedType.Bool)]
            public bool DeleteFile;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct UNICODE_STRING
        {
            public ushort Length;
            public ushort MaximumLength;
            public IntPtr Buffer;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct OBJECT_ATTRIBUTES
        {
            public int Length;
            public IntPtr RootDirectory;
            public IntPtr ObjectName;
            public uint Attributes;
            public IntPtr SecurityDescriptor;
            public IntPtr SecurityQualityOfService;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct IO_STATUS_BLOCK
        {
            public IntPtr Status;
            public UIntPtr Information;
        }

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern SafeFileHandle CreateFileW(
            string fileName,
            uint desiredAccess,
            uint shareMode,
            IntPtr securityAttributes,
            uint creationDisposition,
            uint flagsAndAttributes,
            IntPtr templateFile);

        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool GetFileInformationByHandle(
            SafeFileHandle file,
            out BY_HANDLE_FILE_INFORMATION information);

        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool SetFileInformationByHandle(
            SafeFileHandle file,
            int informationClass,
            ref FILE_DISPOSITION_INFO information,
            uint bufferSize);

        [DllImport("ntdll.dll")]
        private static extern int NtOpenFile(
            out SafeFileHandle fileHandle,
            uint desiredAccess,
            ref OBJECT_ATTRIBUTES objectAttributes,
            out IO_STATUS_BLOCK ioStatusBlock,
            uint shareAccess,
            uint openOptions);

        [DllImport("ntdll.dll")]
        private static extern uint RtlNtStatusToDosError(int status);

        private sealed class HeldEntry : IDisposable
        {
            public readonly string Path;
            public readonly SafeFileHandle Handle;
            private bool disposed;

            public HeldEntry(string path, SafeFileHandle handle)
            {
                Path = path;
                Handle = handle;
            }

            public void Dispose()
            {
                if (disposed) return;
                disposed = true;
                Handle.Dispose();
            }
        }

        private sealed class HeldModule
        {
            public readonly HeldEntry Directory;
            public readonly List<HeldEntry> Files;
            public readonly string[] Snapshot;

            public HeldModule(HeldEntry directory, List<HeldEntry> files, string[] snapshot)
            {
                Directory = directory;
                Files = files;
                Snapshot = snapshot;
            }
        }

        private readonly HeldEntry workspace;
        private readonly List<HeldEntry> ancestors;
        private readonly string[] workspaceSnapshot;
        private readonly HeldEntry media;
        private readonly List<HeldEntry> mediaFiles;
        private readonly string[] mediaSnapshot;
        private readonly HeldEntry root;
        private readonly List<HeldModule> modules;
        private readonly string[] rootSnapshot;
        private bool disposed;
        private bool deleted;
        private bool workspaceDeleted;

        private OwnedNumbaCacheDeletionPlan(
            List<HeldEntry> ancestors,
            HeldEntry workspace,
            string[] workspaceSnapshot,
            HeldEntry media,
            List<HeldEntry> mediaFiles,
            string[] mediaSnapshot,
            HeldEntry root,
            List<HeldModule> modules,
            string[] rootSnapshot)
        {
            this.ancestors = ancestors;
            this.workspace = workspace;
            this.workspaceSnapshot = workspaceSnapshot;
            this.media = media;
            this.mediaFiles = mediaFiles;
            this.mediaSnapshot = mediaSnapshot;
            this.root = root;
            this.modules = modules;
            this.rootSnapshot = rootSnapshot;
        }

        public static OwnedNumbaCacheDeletionPlan Prepare(
            string workspaceRoot,
            string cacheName,
            string mediaName)
        {
            if (!String.Equals(cacheName, "n", StringComparison.Ordinal))
                throw new InvalidOperationException("Refusing to prepare an unexpected Numba cache name");
            if (!String.IsNullOrEmpty(mediaName) && !MediaDirectoryPattern.IsMatch(mediaName))
                throw new InvalidOperationException("Refusing to prepare an unexpected media workspace name");

            string workspacePath = Path.GetFullPath(workspaceRoot);
            string rootPath = Path.GetFullPath(Path.Combine(workspacePath, cacheName));
            if (!String.Equals(Path.GetDirectoryName(rootPath), workspacePath, StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("Refusing to prepare a Numba cache outside its workspace");

            List<HeldEntry> heldAncestors = null;
            HeldEntry heldWorkspace = null;
            HeldEntry heldMedia = null;
            var heldMediaFiles = new List<HeldEntry>();
            HeldEntry heldRoot = null;
            var heldModules = new List<HeldModule>();
            try
            {
                List<HeldEntry> workspaceChain = OpenAnchoredDirectoryChain(workspacePath);
                heldWorkspace = workspaceChain[workspaceChain.Count - 1];
                workspaceChain.RemoveAt(workspaceChain.Count - 1);
                heldAncestors = workspaceChain;
                string[] workspaceEntries = Snapshot(workspacePath);
                var expectedWorkspaceEntries = new HashSet<string>(StringComparer.Ordinal);
                bool hasCache = workspaceEntries.Contains(cacheName, StringComparer.Ordinal);
                if (hasCache) expectedWorkspaceEntries.Add(cacheName);
                if (!String.IsNullOrEmpty(mediaName))
                {
                    if (!workspaceEntries.Contains(mediaName, StringComparer.Ordinal))
                        throw new InvalidOperationException("Media workspace changed before validated cleanup: " + mediaName);
                    expectedWorkspaceEntries.Add(mediaName);
                }
                if (!workspaceEntries.SequenceEqual(
                    expectedWorkspaceEntries.OrderBy(name => name, StringComparer.Ordinal),
                    StringComparer.Ordinal))
                    throw new InvalidOperationException("Refusing to remove a verification workspace with unknown entries");

                string[] heldMediaSnapshot = Array.Empty<string>();
                if (!String.IsNullOrEmpty(mediaName))
                {
                    string mediaPath = DirectChild(workspacePath, mediaName);
                    heldMedia = OpenRelativeExpected(heldWorkspace, mediaName, mediaPath, true, true);
                    heldMediaSnapshot = Snapshot(mediaPath);
                    foreach (string fileName in heldMediaSnapshot)
                    {
                        if (!MediaFileNames.Contains(fileName) && !MediaTemporaryPattern.IsMatch(fileName))
                            throw new InvalidOperationException("Refusing to remove an unknown media output: " + fileName);
                        string filePath = DirectChild(mediaPath, fileName);
                        heldMediaFiles.Add(OpenRelativeExpected(heldMedia, fileName, filePath, false, true));
                    }
                    EnsureSnapshot(mediaPath, heldMediaSnapshot);
                }

                string[] rootEntries = Array.Empty<string>();
                if (hasCache)
                {
                    heldRoot = OpenRelativeExpected(heldWorkspace, cacheName, rootPath, true, true);
                    rootEntries = Snapshot(rootPath);
                    foreach (string entryName in rootEntries)
                    {
                        if (!ModulePattern.IsMatch(entryName))
                            throw new InvalidOperationException("Refusing to remove an unknown Numba cache directory: n/" + entryName);
                        string modulePath = DirectChild(rootPath, entryName);
                        HeldEntry heldModule = OpenRelativeExpected(heldRoot, entryName, modulePath, true, true);
                        var heldFiles = new List<HeldEntry>();
                        try
                        {
                            string[] moduleEntries = Snapshot(modulePath);
                            foreach (string fileName in moduleEntries)
                            {
                                if (!FilePattern.IsMatch(fileName))
                                    throw new InvalidOperationException("Refusing to remove an unknown Numba cache output: n/" + entryName + "/" + fileName);
                                string filePath = DirectChild(modulePath, fileName);
                                heldFiles.Add(OpenRelativeExpected(heldModule, fileName, filePath, false, true));
                            }
                            EnsureSnapshot(modulePath, moduleEntries);
                            heldModules.Add(new HeldModule(heldModule, heldFiles, moduleEntries));
                            heldModule = null;
                            heldFiles = null;
                        }
                        finally
                        {
                            if (heldFiles != null)
                                foreach (HeldEntry file in heldFiles) file.Dispose();
                            if (heldModule != null) heldModule.Dispose();
                        }
                    }
                    EnsureSnapshot(rootPath, rootEntries);
                }
                EnsureSnapshot(workspacePath, workspaceEntries);
                return new OwnedNumbaCacheDeletionPlan(
                    heldAncestors,
                    heldWorkspace,
                    workspaceEntries,
                    heldMedia,
                    heldMediaFiles,
                    heldMediaSnapshot,
                    heldRoot,
                    heldModules,
                    rootEntries);
            }
            catch
            {
                foreach (HeldModule module in heldModules)
                {
                    foreach (HeldEntry file in module.Files) file.Dispose();
                    module.Directory.Dispose();
                }
                if (heldRoot != null) heldRoot.Dispose();
                foreach (HeldEntry file in heldMediaFiles) file.Dispose();
                if (heldMedia != null) heldMedia.Dispose();
                if (heldWorkspace != null) heldWorkspace.Dispose();
                if (heldAncestors != null)
                    for (int index = heldAncestors.Count - 1; index >= 0; index--) heldAncestors[index].Dispose();
                throw;
            }
        }

        public void Delete(Action afterValidationBeforeDelete)
        {
            if (disposed) throw new ObjectDisposedException(GetType().FullName);
            if (deleted) throw new InvalidOperationException("Numba cache deletion plan was already used");
            ValidateUnchanged();
            if (afterValidationBeforeDelete != null) afterValidationBeforeDelete();
            ValidateUnchanged();

            if (media != null)
            {
                foreach (HeldEntry file in mediaFiles)
                {
                    MarkForDeletion(file);
                    file.Dispose();
                }
                EnsureSnapshot(media.Path, Array.Empty<string>());
                MarkForDeletion(media);
                media.Dispose();
            }
            foreach (HeldModule module in modules)
            {
                foreach (HeldEntry file in module.Files)
                {
                    MarkForDeletion(file);
                    file.Dispose();
                }
                EnsureSnapshot(module.Directory.Path, Array.Empty<string>());
                MarkForDeletion(module.Directory);
                module.Directory.Dispose();
            }
            if (root != null)
            {
                EnsureSnapshot(root.Path, Array.Empty<string>());
                MarkForDeletion(root);
                root.Dispose();
            }
            deleted = true;
        }

        public void DeleteWorkspaceIfEmpty()
        {
            if (disposed) throw new ObjectDisposedException(GetType().FullName);
            if (!deleted) throw new InvalidOperationException("Numba cache must be deleted before its workspace");
            if (workspaceDeleted) throw new InvalidOperationException("Verification workspace deletion was already used");
            EnsureSnapshot(workspace.Path, Array.Empty<string>());
            MarkForDeletion(workspace);
            workspace.Dispose();
            workspaceDeleted = true;
        }

        private void ValidateUnchanged()
        {
            EnsureSnapshot(workspace.Path, workspaceSnapshot);
            if (media != null) EnsureSnapshot(media.Path, mediaSnapshot);
            if (root != null) EnsureSnapshot(root.Path, rootSnapshot);
            foreach (HeldModule module in modules)
                EnsureSnapshot(module.Directory.Path, module.Snapshot);
        }

        private static List<HeldEntry> OpenAnchoredDirectoryChain(string path)
        {
            string fullPath = Path.GetFullPath(path);
            string volumeRoot = Path.GetPathRoot(fullPath);
            if (String.IsNullOrEmpty(volumeRoot))
                throw new InvalidOperationException("Numba cache workspace has no filesystem root");

            var chain = new List<HeldEntry>();
            HeldEntry volume = OpenAbsoluteExpected(volumeRoot, true, false, true);
            chain.Add(volume);
            string currentPath = volumeRoot;
            string relative = Path.GetRelativePath(volumeRoot, fullPath);
            string[] components = relative.Split(
                new[] { Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar },
                StringSplitOptions.RemoveEmptyEntries);
            try
            {
                for (int index = 0; index < components.Length; index++)
                {
                    string component = components[index];
                    currentPath = DirectChild(currentPath, component);
                    bool requestDelete = index == components.Length - 1;
                    chain.Add(OpenRelativeExpected(chain[chain.Count - 1], component, currentPath, true, requestDelete));
                }
                if (chain.Count < 2)
                    throw new InvalidOperationException("Refusing to use a filesystem root as a Numba cache workspace");
                return chain;
            }
            catch
            {
                for (int index = chain.Count - 1; index >= 0; index--) chain[index].Dispose();
                throw;
            }
        }

        private static HeldEntry OpenAbsoluteExpected(
            string path,
            bool expectDirectory,
            bool requestDelete,
            bool allowDeleteSharing)
        {
            uint access = FILE_READ_ATTRIBUTES | (requestDelete ? DELETE : 0u);
            uint sharing = FILE_SHARE_READ | FILE_SHARE_WRITE | (allowDeleteSharing ? FILE_SHARE_DELETE : 0u);
            SafeFileHandle handle = CreateFileW(
                path,
                access,
                sharing,
                IntPtr.Zero,
                OPEN_EXISTING,
                FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT,
                IntPtr.Zero);
            if (handle.IsInvalid)
            {
                int error = Marshal.GetLastWin32Error();
                handle.Dispose();
                throw new Win32Exception(error, "Could not hold validated Numba cache identity: " + path);
            }
            return ValidateOpenedHandle(path, handle, expectDirectory);
        }

        private static HeldEntry OpenRelativeExpected(
            HeldEntry parent,
            string name,
            string displayPath,
            bool expectDirectory,
            bool requestDelete)
        {
            if (String.IsNullOrEmpty(name) || name == "." || name == ".." ||
                name.IndexOf(Path.DirectorySeparatorChar) >= 0 || name.IndexOf(Path.AltDirectorySeparatorChar) >= 0)
                throw new InvalidOperationException("Numba cache relative component was invalid: " + name);

            IntPtr nameBuffer = IntPtr.Zero;
            IntPtr unicodePointer = IntPtr.Zero;
            SafeFileHandle handle = null;
            try
            {
                nameBuffer = Marshal.StringToHGlobalUni(name);
                var unicode = new UNICODE_STRING
                {
                    Length = checked((ushort)(name.Length * 2)),
                    MaximumLength = checked((ushort)((name.Length + 1) * 2)),
                    Buffer = nameBuffer
                };
                unicodePointer = Marshal.AllocHGlobal(Marshal.SizeOf<UNICODE_STRING>());
                Marshal.StructureToPtr(unicode, unicodePointer, false);
                var attributes = new OBJECT_ATTRIBUTES
                {
                    Length = Marshal.SizeOf<OBJECT_ATTRIBUTES>(),
                    RootDirectory = parent.Handle.DangerousGetHandle(),
                    ObjectName = unicodePointer,
                    Attributes = OBJ_CASE_INSENSITIVE,
                    SecurityDescriptor = IntPtr.Zero,
                    SecurityQualityOfService = IntPtr.Zero
                };
                IO_STATUS_BLOCK ioStatus;
                uint access = FILE_READ_ATTRIBUTES | (requestDelete ? DELETE : 0u);
                uint options = NT_FILE_OPEN_REPARSE_POINT |
                    (expectDirectory ? FILE_DIRECTORY_FILE : FILE_NON_DIRECTORY_FILE);
                int status = NtOpenFile(
                    out handle,
                    access,
                    ref attributes,
                    out ioStatus,
                    FILE_SHARE_READ | FILE_SHARE_WRITE,
                    options);
                if (status < 0)
                {
                    uint error = RtlNtStatusToDosError(status);
                    if (handle != null) handle.Dispose();
                    throw new Win32Exception(unchecked((int)error), "Could not open anchored Numba cache identity: " + displayPath);
                }
                return ValidateOpenedHandle(displayPath, handle, expectDirectory);
            }
            catch
            {
                if (handle != null) handle.Dispose();
                throw;
            }
            finally
            {
                if (unicodePointer != IntPtr.Zero) Marshal.FreeHGlobal(unicodePointer);
                if (nameBuffer != IntPtr.Zero) Marshal.FreeHGlobal(nameBuffer);
            }
        }

        private static HeldEntry ValidateOpenedHandle(string path, SafeFileHandle handle, bool expectDirectory)
        {
            try
            {
                BY_HANDLE_FILE_INFORMATION information;
                if (!GetFileInformationByHandle(handle, out information))
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "Could not inspect validated Numba cache identity: " + path);
                bool isDirectory = (information.FileAttributes & FILE_ATTRIBUTE_DIRECTORY) != 0;
                bool isReparse = (information.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0;
                if (isReparse)
                    throw new InvalidOperationException("Refusing to remove a reparse-point Numba cache entry: " + path);
                if (isDirectory != expectDirectory)
                    throw new InvalidOperationException("Refusing to remove a Numba cache entry of the wrong type: " + path);
                return new HeldEntry(path, handle);
            }
            catch
            {
                handle.Dispose();
                throw;
            }
        }

        private static string DirectChild(string parent, string name)
        {
            string child = Path.GetFullPath(Path.Combine(parent, name));
            if (!String.Equals(Path.GetDirectoryName(child), parent, StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("Numba cache entry escaped its validated parent");
            return child;
        }

        private static string[] Snapshot(string directory)
        {
            return Directory.EnumerateFileSystemEntries(directory)
                .Select(Path.GetFileName)
                .OrderBy(name => name, StringComparer.Ordinal)
                .ToArray();
        }

        private static void EnsureSnapshot(string directory, string[] expected)
        {
            string[] actual = Snapshot(directory);
            if (!actual.SequenceEqual(expected, StringComparer.Ordinal))
                throw new InvalidOperationException("Numba cache changed during validated cleanup: " + directory);
        }

        private static void MarkForDeletion(HeldEntry entry)
        {
            var information = new FILE_DISPOSITION_INFO { DeleteFile = true };
            uint size = (uint)Marshal.SizeOf<FILE_DISPOSITION_INFO>();
            if (!SetFileInformationByHandle(entry.Handle, FILE_DISPOSITION_INFO_CLASS, ref information, size))
                throw new Win32Exception(Marshal.GetLastWin32Error(), "Could not delete validated Numba cache identity: " + entry.Path);
        }

        public void Dispose()
        {
            if (disposed) return;
            disposed = true;
            foreach (HeldModule module in modules)
            {
                foreach (HeldEntry file in module.Files) file.Dispose();
                module.Directory.Dispose();
            }
            if (root != null) root.Dispose();
            foreach (HeldEntry file in mediaFiles) file.Dispose();
            if (media != null) media.Dispose();
            workspace.Dispose();
            for (int index = ancestors.Count - 1; index >= 0; index--) ancestors[index].Dispose();
        }
    }
}
'@
}


function New-OwnedNumbaCacheDeletionPlan {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$WorkspaceRoot,
        [Action]$AfterPathValidationForTest = $null
    )

    $workspaceFull = Assert-RegularDirectoryAndAncestors -Path ([System.IO.Path]::GetFullPath($WorkspaceRoot))
    $numbaCandidate = Join-Path $workspaceFull 'n'
    if (-not (Test-Path -LiteralPath $numbaCandidate)) { return $null }
    if ($null -ne $AfterPathValidationForTest) { $AfterPathValidationForTest.Invoke() }
    Initialize-OwnedNumbaCacheDeletionType
    return [DesktopCompanionPetToolchain.OwnedNumbaCacheDeletionPlan]::Prepare($workspaceFull, 'n', '')
}


function New-OwnedVerificationCleanupPlan {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$WorkspaceRoot,
        [Parameter(Mandatory)][string]$MediaWorkspace
    )

    $workspaceFull = Assert-RegularDirectoryAndAncestors -Path ([System.IO.Path]::GetFullPath($WorkspaceRoot))
    $mediaName = ''
    if (Test-Path -LiteralPath $MediaWorkspace) {
        $mediaFull = Resolve-ContainedPath -Root $workspaceFull -RelativePath ([System.IO.Path]::GetRelativePath($workspaceFull, $MediaWorkspace))
        if (-not [string]::Equals(
                [System.IO.Path]::GetDirectoryName($mediaFull),
                $workspaceFull,
                [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove a media workspace that is not a direct child: $mediaFull"
        }
        $mediaName = [System.IO.Path]::GetFileName($mediaFull)
        if ($mediaName -notmatch '^media-[0-9a-f]{32}$') {
            throw "Refusing to remove an unresolved media workspace: $mediaFull"
        }
    }
    Initialize-OwnedNumbaCacheDeletionType
    return [DesktopCompanionPetToolchain.OwnedNumbaCacheDeletionPlan]::Prepare($workspaceFull, 'n', $mediaName)
}


function Remove-VerificationWorkspace {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$VerifyRoot,
        [Parameter(Mandatory)][string]$Workspace,
        [Parameter(Mandatory)][string]$MediaWorkspace
    )

    if (-not (Test-Path -LiteralPath $Workspace)) {
        return
    }
    $workspaceFull = Resolve-ContainedPath -Root $VerifyRoot -RelativePath ([System.IO.Path]::GetRelativePath($VerifyRoot, $Workspace))
    if ([System.IO.Path]::GetFileName($workspaceFull) -notmatch '^verify-[0-9a-f]{32}$') {
        throw "Refusing to remove an unresolved verification workspace: $workspaceFull"
    }
    $cleanupPlan = New-OwnedVerificationCleanupPlan -WorkspaceRoot $workspaceFull -MediaWorkspace $MediaWorkspace
    try {
        $cleanupPlan.Delete($null)
        $cleanupPlan.DeleteWorkspaceIfEmpty()
    }
    finally {
        $cleanupPlan.Dispose()
    }
}


function Remove-OwnedNumbaCache {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$WorkspaceRoot)

    $plan = New-OwnedNumbaCacheDeletionPlan -WorkspaceRoot $WorkspaceRoot
    if ($null -eq $plan) { return }
    try {
        $plan.Delete($null)
    }
    finally {
        $plan.Dispose()
    }
}


function Remove-EmptyVerificationRoot {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Root, [Parameter(Mandatory)][string]$VerifyRoot)

    if (-not (Test-Path -LiteralPath $VerifyRoot)) { return }
    $verified = Resolve-ContainedPath -Root $Root -RelativePath ([System.IO.Path]::GetRelativePath($Root, $VerifyRoot))
    if ([System.IO.Path]::GetFileName($verified) -cne 'verify') {
        throw "Refusing to remove an unresolved verification root: $verified"
    }
    $null = Assert-RegularDirectoryAndAncestors -Path $verified
    if (@(Get-ChildItem -LiteralPath $verified -Force).Count -ne 0) {
        throw "Verification root was expected to be empty: $verified"
    }
    [System.IO.Directory]::Delete($verified, $false)
}


function Assert-MediaResult {
    [CmdletBinding()]
    param([Parameter(Mandatory)][object]$Result, [Parameter(Mandatory)][string]$Workspace)

    Assert-ExactObjectKeys -Object $Result -Expected @('schemaVersion', 'tools', 'source', 'models', 'webp', 'preview', 'interpolation') -Context 'media result'
    if ((Assert-JsonInteger -Value $Result.schemaVersion -Context 'media schemaVersion') -ne 1) { throw 'Media result schema version is unsupported' }
    Assert-ExactObjectKeys -Object $Result.tools -Expected @('ffmpeg', 'ffprobe', 'magick', 'cwebp') -Context 'media tools'
    foreach ($name in @('ffmpeg', 'ffprobe', 'magick', 'cwebp')) { $null = Assert-JsonString -Value $Result.tools.$name -Context "media $name version" }
    Assert-ExactObjectKeys -Object $Result.source -Expected @('width', 'height', 'opencvBounds') -Context 'media source result'
    if ((Assert-JsonInteger -Value $Result.source.width -Context 'media source width') -ne 256 -or (Assert-JsonInteger -Value $Result.source.height -Context 'media source height') -ne 256 -or @($Result.source.opencvBounds).Count -ne 4) { throw 'Media source result has unexpected dimensions or OpenCV bounds' }
    foreach ($bound in @($Result.source.opencvBounds)) { if ((Assert-JsonInteger -Value $bound -Context 'media OpenCV bound') -lt 0) { throw 'Media OpenCV bounds are invalid' } }
    Assert-ExactObjectKeys -Object $Result.models -Expected @('isnet-anime', 'u2net_human_seg') -Context 'media model results'
    $minimumAlphaPixels = [Int64][Math]::Ceiling(256 * 256 * 0.05)
    foreach ($modelName in @('isnet-anime', 'u2net_human_seg')) {
        $modelResult = $Result.models.$modelName
        Assert-ExactObjectKeys -Object $modelResult -Expected @('relativePath', 'alpha') -Context "media $modelName result"
        $cutoutPath = Resolve-ContainedPath -Root $Workspace -RelativePath (Assert-JsonString -Value $modelResult.relativePath -Context "media $modelName relative path")
        $null = Assert-RegularFile -Path $cutoutPath
        Assert-ExactObjectKeys -Object $modelResult.alpha -Expected @('minimum', 'maximum', 'transparentPixels', 'opaquePixels') -Context "media $modelName alpha"
        if ((Assert-JsonInteger -Value $modelResult.alpha.minimum -Context 'media alpha minimum') -ne 0 -or (Assert-JsonInteger -Value $modelResult.alpha.maximum -Context 'media alpha maximum') -ne 255 -or (Assert-JsonInteger -Value $modelResult.alpha.transparentPixels -Context 'media transparent pixels') -lt $minimumAlphaPixels -or (Assert-JsonInteger -Value $modelResult.alpha.opaquePixels -Context 'media opaque pixels') -lt $minimumAlphaPixels) { throw "Media $modelName alpha result is not meaningfully transparent and opaque" }
    }
    Assert-ExactObjectKeys -Object $Result.webp -Expected @('relativePath', 'width', 'height', 'hasAlpha', 'alphaMin', 'alphaMax') -Context 'media WebP result'
    $webpPath = Resolve-ContainedPath -Root $Workspace -RelativePath (Assert-JsonString -Value $Result.webp.relativePath -Context 'media WebP relative path')
    $null = Assert-RegularFile -Path $webpPath
    if ((Assert-JsonInteger -Value $Result.webp.width -Context 'media WebP width') -ne 256 -or (Assert-JsonInteger -Value $Result.webp.height -Context 'media WebP height') -ne 256 -or -not (Assert-JsonBoolean -Value $Result.webp.hasAlpha -Context 'media WebP alpha') -or (Assert-JsonInteger -Value $Result.webp.alphaMin -Context 'media WebP alpha minimum') -ne 0 -or (Assert-JsonInteger -Value $Result.webp.alphaMax -Context 'media WebP alpha maximum') -ne 255) { throw 'Media WebP result does not contain expected transparent dimensions' }
    Assert-ExactObjectKeys -Object $Result.preview -Expected @('frames', 'durationSeconds') -Context 'media preview result'
    if ((Assert-JsonInteger -Value $Result.preview.frames -Context 'media preview frames') -ne 4 -or $Result.preview.durationSeconds -isnot [double] -and $Result.preview.durationSeconds -isnot [decimal] -and $Result.preview.durationSeconds -isnot [int64] -or [double]$Result.preview.durationSeconds -lt 0.25 -or [double]$Result.preview.durationSeconds -gt 0.55) { throw 'Media preview result is invalid' }
    Assert-ExactObjectKeys -Object $Result.interpolation -Expected @('relativePath', 'width', 'height', 'distinctFromInputs') -Context 'media interpolation result'
    $interpolationPath = Resolve-ContainedPath -Root $Workspace -RelativePath (Assert-JsonString -Value $Result.interpolation.relativePath -Context 'media interpolation relative path')
    $null = Assert-RegularFile -Path $interpolationPath
    if ((Assert-JsonInteger -Value $Result.interpolation.width -Context 'media interpolation width') -ne 64 -or
        (Assert-JsonInteger -Value $Result.interpolation.height -Context 'media interpolation height') -ne 64 -or
        -not (Assert-JsonBoolean -Value $Result.interpolation.distinctFromInputs -Context 'media interpolation distinctness')) {
        throw 'Media RIFE interpolation result is invalid'
    }
    return $webpPath
}


function Invoke-MediaVerificationProcess {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$PythonPath,
        [Parameter(Mandatory)][string]$MediaScript,
        [Parameter(Mandatory)][string]$ModelsRoot,
        [Parameter(Mandatory)][System.Collections.IDictionary]$ToolPaths,
        [Parameter(Mandatory)][string]$FfprobePath,
        [Parameter(Mandatory)][string]$RifeModelPath,
        [Parameter(Mandatory)][string]$WorkspaceRoot,
        [Parameter(Mandatory)][string]$WorkDir,
        [Parameter(Mandatory)][string]$ResultJson
    )

    $workspaceFull = [System.IO.Path]::GetFullPath($WorkspaceRoot)
    $workRelative = [System.IO.Path]::GetRelativePath($workspaceFull, $WorkDir)
    $workFull = Resolve-ContainedPath -Root $workspaceFull -RelativePath $workRelative
    if ((Split-Path -Parent $workFull) -cne $workspaceFull) {
        throw 'Media work directory must be directly inside its verification workspace'
    }
    $numbaCache = Resolve-ContainedPath -Root $workspaceFull -RelativePath 'n'
    if (Test-Path -LiteralPath $numbaCache) {
        throw "Numba cache directory unexpectedly exists: $numbaCache"
    }
    return Invoke-CheckedProcess -FilePath $PythonPath -ArgumentList @(
        '-I',
        '-B',
        $MediaScript,
        '--models-root', $ModelsRoot,
        '--ffmpeg', $ToolPaths.ffmpeg,
        '--ffprobe', $FfprobePath,
        '--magick', $ToolPaths.imagemagick,
        '--cwebp', $ToolPaths.libwebp,
        '--rife', $ToolPaths.rife,
        '--rife-model', $RifeModelPath,
        '--work-dir', $WorkDir,
        '--result-json', $ResultJson,
        '--numba-cache-dir', $numbaCache
    ) -TimeoutSeconds 900 -CleanEnvironment -Environment @{
        NUMBA_CACHE_DIR = $numbaCache
        PYTHONDONTWRITEBYTECODE = '1'
        PYTHONNOUSERSITE = '1'
    }
}


function Invoke-QtVerificationProcess {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$PythonPath,
        [Parameter(Mandatory)][string]$QtScript,
        [Parameter(Mandatory)][string]$WebpPath
    )

    return Invoke-CheckedProcess -FilePath $PythonPath -ArgumentList @('-I', '-B', $QtScript, $WebpPath) `
        -TimeoutSeconds 60 -CleanEnvironment -Environment @{ PATH = '' }
}


function Invoke-PetToolchainVerification {
    [CmdletBinding()]
    param()

    $workspaceInfo = $null
    $toolRootFull = ''
    try {
        $toolRootFull = [System.IO.Path]::GetFullPath($ToolRoot)
        if (-not [string]::IsNullOrWhiteSpace($CandidateRoot)) {
            $candidateFull = [System.IO.Path]::GetFullPath($CandidateRoot)
            $candidateRelative = [System.IO.Path]::GetRelativePath($toolRootFull, $candidateFull)
            if ([System.IO.Path]::IsPathRooted($candidateRelative) -or $candidateRelative -eq '..' -or $candidateRelative.StartsWith('..\', [System.StringComparison]::Ordinal)) {
                throw 'Candidate path escapes tool root'
            }
        }
        $toolRootFull = Assert-RegularDirectoryAndAncestors -Path $toolRootFull
        $lockFull = [System.IO.Path]::GetFullPath($LockPath)
        $requirementsFull = [System.IO.Path]::GetFullPath($RequirementsPath)
        $lock = Read-PetToolchainLock -LockPath $lockFull
        $lockDigest = Get-LockDigest -LockPath $lockFull -RequirementsPath $requirementsFull
        Write-Output 'Gate: lock schema and digest passed.'
        $candidate = Resolve-VerificationCandidate -Root $toolRootFull -LockDigest $lockDigest -ConfiguredCandidateRoot $CandidateRoot -SkipCurrentPointer $NoCurrentPointer.IsPresent
        $installed = Read-InstalledManifest -CandidateRoot $candidate -Lock $lock -LockDigest $lockDigest
        $toolPaths = [ordered]@{
            ffmpeg = Resolve-ManifestEntrypoint -CandidateRoot $candidate -Value $installed.entrypoints.tools.ffmpeg -ExpectedRelativePath ('tools/ffmpeg/' + ([string]$lock.tools.ffmpeg.entrypoint).Replace('\', '/')) -Context 'FFmpeg'
            imagemagick = Resolve-ManifestEntrypoint -CandidateRoot $candidate -Value $installed.entrypoints.tools.imagemagick -ExpectedRelativePath ('tools/imagemagick/' + ([string]$lock.tools.imagemagick.entrypoint).Replace('\', '/')) -Context 'ImageMagick'
            libwebp = Resolve-ManifestEntrypoint -CandidateRoot $candidate -Value $installed.entrypoints.tools.libwebp -ExpectedRelativePath ('tools/libwebp/' + ([string]$lock.tools.libwebp.entrypoint).Replace('\', '/')) -Context 'libwebp'
            rife = Resolve-ManifestEntrypoint -CandidateRoot $candidate -Value $installed.entrypoints.tools.rife -ExpectedRelativePath ('tools/rife/' + ([string]$lock.tools.rife.entrypoint).Replace('\', '/')) -Context 'RIFE'
        }
        $ffprobePath = Resolve-ContainedPath -Root $candidate -RelativePath ('tools\ffmpeg\' + ([string]$lock.tools.ffmpeg.probeEntrypoint).Replace('/', '\'))
        $rifeToolRoot = Resolve-ContainedPath -Root $candidate -RelativePath 'tools\rife'
        $rifeModelPath = Resolve-ContainedPath -Root $rifeToolRoot -RelativePath ([string]$lock.tools.rife.modelDirectory)
        $null = Assert-RegularDirectoryAndAncestors -Path $rifeModelPath
        $modelPaths = [ordered]@{}
        foreach ($modelName in @('isnet-anime', 'u2net_human_seg')) { $modelPaths[$modelName] = Resolve-ManifestEntrypoint -CandidateRoot $candidate -Value $installed.entrypoints.models.$modelName -ExpectedRelativePath ([string]$lock.models.$modelName.entrypoint) -Context "model $modelName" }
        foreach ($toolName in @('ffmpeg', 'imagemagick', 'libwebp', 'rife')) { Assert-InstalledToolInventory -ToolRoot (Resolve-ContainedPath -Root $candidate -RelativePath "tools\$toolName") -Tool $lock.tools.$toolName -Context $toolName }
        foreach ($modelName in @('isnet-anime', 'u2net_human_seg')) { Assert-FileDigest -Path $modelPaths[$modelName] -ExpectedSize ([Int64]$lock.models.$modelName.size) -ExpectedSha256 ([string]$lock.models.$modelName.sha256) }
        $pythonRuntime = Assert-PythonRuntime -CandidateRoot $candidate -InstalledPython $installed.python -RuntimePolicy $lock.pythonRuntime
        $null = Assert-AuthenticodePolicy -Policy $lock.tools.imagemagick.authenticode -Path $toolPaths.imagemagick -Context 'ImageMagick'
        Write-Output 'Gate: installed inventories, models, and Python runtime passed.'
        Assert-VersionOutput -Path $toolPaths.ffmpeg -ArgumentList @('-version') -VersionRegex ([string]$lock.tools.ffmpeg.versionRegex) -Context 'FFmpeg'
        $ffprobeRegex = "^ffprobe version $([System.Text.RegularExpressions.Regex]::Escape([string]$lock.tools.ffmpeg.version))(?:[-\s]|$)"
        Assert-VersionOutput -Path $ffprobePath -ArgumentList @('-version') -VersionRegex $ffprobeRegex -Context 'ffprobe'
        Assert-VersionOutput -Path $toolPaths.imagemagick -ArgumentList @('-version') -VersionRegex ([string]$lock.tools.imagemagick.versionRegex) -Context 'ImageMagick'
        Assert-VersionOutput -Path $toolPaths.libwebp -ArgumentList @('-version') -VersionRegex ([string]$lock.tools.libwebp.versionRegex) -Context 'libwebp'
        Assert-RifeInterface -Path $toolPaths.rife -UsageRegex ([string]$lock.tools.rife.usageRegex)
        Assert-PythonEnvironment -PythonPath $pythonRuntime.PythonPath -ExpectedFreeze @($installed.python.freeze) -RuntimeVersion ([string]$installed.python.runtimeVersion) -VersionRegex ([string]$lock.pythonRuntime.versionRegex)
        Write-Output 'Gate: tool versions, publisher policy, and Python environment passed.'
        $null = Assert-NumbaCachePathBudget -ToolRoot $toolRootFull
        $workspaceInfo = New-VerificationWorkspace -Root $toolRootFull
        $mediaScript = (Assert-RegularFile -Path (Join-Path $PSScriptRoot '..\tools\verify_pet_media.py')).FullName
        $qtScript = (Assert-RegularFile -Path (Join-Path $PSScriptRoot '..\tools\verify_qt_webp.py')).FullName
        $mediaResultPath = Resolve-ContainedPath -Root $workspaceInfo.MediaWorkspace -RelativePath 'result.json'
        $mediaProcess = Invoke-MediaVerificationProcess -PythonPath $pythonRuntime.PythonPath -MediaScript $mediaScript -ModelsRoot (Resolve-ContainedPath -Root $candidate -RelativePath 'models') -ToolPaths $toolPaths -FfprobePath $ffprobePath -RifeModelPath $rifeModelPath -WorkspaceRoot $workspaceInfo.Workspace -WorkDir $workspaceInfo.MediaWorkspace -ResultJson $mediaResultPath
        $mediaStdOut = ConvertFrom-ExactlyOneJsonObject -StdOut $mediaProcess.StdOut -Context 'media helper'
        $mediaFile = Read-StrictJsonFile -Path $mediaResultPath -Context 'media result file'
        if (($mediaStdOut | ConvertTo-Json -Depth 32 -Compress) -cne ($mediaFile | ConvertTo-Json -Depth 32 -Compress)) { throw 'Media helper stdout does not match its atomically written result file' }
        $webpPath = Assert-MediaResult -Result $mediaFile -Workspace $workspaceInfo.MediaWorkspace
        $afterMediaInventory = Get-DeterministicTreeInventory -Root $pythonRuntime.PythonRoot
        if ([Int64]$afterMediaInventory.fileCount -ne [Int64]$pythonRuntime.Inventory.fileCount -or [string]$afterMediaInventory.treeSha256 -cne [string]$pythonRuntime.Inventory.treeSha256) { throw 'Candidate Python tree changed during media verification' }
        Write-Output 'Gate: media smoke helper passed.'
        $qtPythonPath = (Assert-RegularFile -Path $QtPython).FullName
        $qtProcess = Invoke-QtVerificationProcess -PythonPath $qtPythonPath -QtScript $qtScript -WebpPath $webpPath
        $qtResult = ConvertFrom-ExactlyOneJsonObject -StdOut $qtProcess.StdOut -Context 'Qt WebP helper'
        Assert-ExactObjectKeys -Object $qtResult -Expected @('ok', 'width', 'height', 'hasAlpha', 'alphaMin', 'alphaMax') -Context 'Qt WebP result'
        if (-not (Assert-JsonBoolean -Value $qtResult.ok -Context 'Qt ok') -or -not (Assert-JsonBoolean -Value $qtResult.hasAlpha -Context 'Qt alpha') -or (Assert-JsonInteger -Value $qtResult.width -Context 'Qt width') -ne (Assert-JsonInteger -Value $mediaFile.webp.width -Context 'media width') -or (Assert-JsonInteger -Value $qtResult.height -Context 'Qt height') -ne (Assert-JsonInteger -Value $mediaFile.webp.height -Context 'media height') -or (Assert-JsonInteger -Value $qtResult.alphaMin -Context 'Qt alpha minimum') -ne 0 -or (Assert-JsonInteger -Value $qtResult.alphaMax -Context 'Qt alpha maximum') -ne 255) { throw 'Qt WebP result does not match the media helper dimensions or alpha' }
        Write-Output 'Gate: Qt WebP oracle agrees with Pillow alpha and dimensions.'
    }
    finally {
        if ($null -ne $workspaceInfo) {
            Remove-VerificationWorkspace -VerifyRoot $workspaceInfo.VerifyRoot -Workspace $workspaceInfo.Workspace -MediaWorkspace $workspaceInfo.MediaWorkspace
            if ([bool]$workspaceInfo.VerifyRootCreated) { Remove-EmptyVerificationRoot -Root $toolRootFull -VerifyRoot $workspaceInfo.VerifyRoot }
        }
    }
    Write-Output 'PET TOOLCHAIN VERIFIED'
}


if ($MyInvocation.InvocationName -ne '.') {
    Invoke-PetToolchainVerification
}
