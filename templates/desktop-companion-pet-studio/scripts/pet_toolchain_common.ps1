Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Resolve-ContainedPath {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][string]$RelativePath
    )

    if ([string]::IsNullOrWhiteSpace($RelativePath) -or
        [System.IO.Path]::IsPathRooted($RelativePath) -or
        $RelativePath -match '^[A-Za-z]:') {
        throw "Path escapes tool root: $RelativePath"
    }

    $rootFull = [System.IO.Path]::GetFullPath($Root)
    $candidate = [System.IO.Path]::GetFullPath(
        [System.IO.Path]::Combine($rootFull, $RelativePath)
    )
    $rootPrefix = if ($rootFull.EndsWith('\')) { $rootFull } else { "$rootFull\" }

    if (-not $candidate.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Path escapes tool root: $RelativePath"
    }

    return $candidate
}

function Assert-SafeArchivePath {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$EntryName)

    if ([string]::IsNullOrWhiteSpace($EntryName) -or
        [System.IO.Path]::IsPathRooted($EntryName) -or
        $EntryName -match '^[A-Za-z]:' -or
        $EntryName.Contains(':')) {
        throw "Unsafe archive path: $EntryName"
    }

    $normalised = $EntryName -replace '/', '\'
    $withoutTrailingSeparators = $normalised.TrimEnd([char[]]'\/')
    if ([string]::IsNullOrWhiteSpace($withoutTrailingSeparators)) {
        throw "Unsafe archive path: $EntryName"
    }

    foreach ($segment in ($withoutTrailingSeparators -split '[\\/]')) {
        if ([string]::IsNullOrWhiteSpace($segment) -or
            $segment -eq '.' -or
            $segment -eq '..' -or
            $segment.EndsWith('.') -or
            $segment.EndsWith(' ') -or
            $segment.IndexOfAny([char[]]@('<', '>', '"', '|', '?', '*')) -ge 0 -or
            $segment -match '^(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$') {
            throw "Unsafe archive path: $EntryName"
        }
    }

    return $normalised
}

function Get-LockedVersionOutputMatch {
    [CmdletBinding()]
    param(
        [AllowNull()][string]$StdOut,
        [AllowNull()][string]$StdErr,
        [Parameter(Mandatory)][string]$VersionRegex,
        [Parameter(Mandatory)][string]$FailureMessage,
        [string]$EmptyMatchFailureMessage = ''
    )

    $combined = @([string]$StdOut, [string]$StdErr) -join "`n"
    $normalised = $combined -replace "`r`n", "`n"
    $normalised = $normalised -replace "`r", "`n"
    if ([string]::IsNullOrWhiteSpace($normalised)) {
        throw $FailureMessage
    }

    try {
        $expression = [System.Text.RegularExpressions.Regex]::new(
            $VersionRegex,
            [System.Text.RegularExpressions.RegexOptions]::Multiline
        )
    }
    catch {
        throw $FailureMessage
    }
    $match = $expression.Match($normalised)
    if (-not $match.Success) {
        throw $FailureMessage
    }
    $matchedVersion = $match.Value.Trim()
    if ([string]::IsNullOrWhiteSpace($matchedVersion)) {
        if ([string]::IsNullOrWhiteSpace($EmptyMatchFailureMessage)) {
            throw $FailureMessage
        }
        throw $EmptyMatchFailureMessage
    }
    return $matchedVersion
}

function Assert-NoReparsePoints {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Root)

    $rootFull = [System.IO.Path]::GetFullPath($Root)
    if (-not (Test-Path -LiteralPath $rootFull)) {
        throw "Path does not exist for reparse-point check: $rootFull"
    }

    $pending = [System.Collections.Generic.Queue[string]]::new()
    $pending.Enqueue($rootFull)
    while ($pending.Count -gt 0) {
        $current = $pending.Dequeue()
        $item = Get-Item -LiteralPath $current -Force
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Reparse point is not allowed in toolchain path: $current"
        }

        if ($item -is [System.IO.DirectoryInfo]) {
            foreach ($child in (Get-ChildItem -LiteralPath $current -Force)) {
                $relative = [System.IO.Path]::GetRelativePath($rootFull, $child.FullName)
                $null = Resolve-ContainedPath -Root $rootFull -RelativePath $relative
                $pending.Enqueue($child.FullName)
            }
        }
    }
}

function Assert-NumbaCachePathBudget {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$ToolRoot)

    $toolRootFull = [System.IO.Path]::GetFullPath($ToolRoot)
    $workspaceName = 'verify-' + ('0' * 32)
    $moduleName = 'foreground_7ae490adabd67a875187d1bac3e9724aa587038f'
    $temporaryName = 'estimate_foreground_ml._resize_nearest_multichannel-5.py312.1.nbc.tmp.' + ('0' * 16)
    $longestObservedTemporary = [System.IO.Path]::Combine(
        $toolRootFull,
        'verify',
        $workspaceName,
        'n',
        $moduleName,
        $temporaryName
    )
    if ($longestObservedTemporary.Length -gt 259) {
        throw "Tool root exceeds the locked Numba path budget: $toolRootFull"
    }
    return $longestObservedTemporary
}

function Assert-ContainedWritePath {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][string]$Path
    )

    $rootFull = [System.IO.Path]::GetFullPath($Root)
    $pathFull = [System.IO.Path]::GetFullPath($Path)
    $relative = [System.IO.Path]::GetRelativePath($rootFull, $pathFull)
    $verifiedPath = Resolve-ContainedPath -Root $rootFull -RelativePath $relative
    if (-not [string]::Equals($verifiedPath, $pathFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Write path escapes its staging root: $pathFull"
    }
    Assert-NoReparsePoints -Root $rootFull
    return $verifiedPath
}

function Assert-FileDigest {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][Int64]$ExpectedSize,
        [Parameter(Mandatory)][string]$ExpectedSha256
    )

    if ($ExpectedSize -lt 0 -or $ExpectedSha256 -notmatch '^[0-9a-f]{64}$') {
        throw "Invalid expected file digest for: $Path"
    }

    $item = Get-Item -LiteralPath $Path -Force
    if ($item -is [System.IO.DirectoryInfo] -or
        ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Expected regular file: $Path"
    }
    if ($item.Length -ne $ExpectedSize) {
        throw "File size mismatch for ${Path}: expected $ExpectedSize, got $($item.Length)"
    }

    $actual = (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -cne $ExpectedSha256.ToLowerInvariant()) {
        throw "SHA-256 mismatch for $Path"
    }
}

function Get-LockDigest {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$LockPath,
        [Parameter(Mandatory)][string]$RequirementsPath
    )

    $lockBytes = [System.IO.File]::ReadAllBytes([System.IO.Path]::GetFullPath($LockPath))
    $requirementsBytes = [System.IO.File]::ReadAllBytes(
        [System.IO.Path]::GetFullPath($RequirementsPath)
    )
    $combined = [byte[]]::new($lockBytes.Length + $requirementsBytes.Length)
    [System.Buffer]::BlockCopy($lockBytes, 0, $combined, 0, $lockBytes.Length)
    [System.Buffer]::BlockCopy(
        $requirementsBytes,
        0,
        $combined,
        $lockBytes.Length,
        $requirementsBytes.Length
    )

    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([System.BitConverter]::ToString($sha.ComputeHash($combined))).Replace('-', '').ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

function Assert-ExactObjectKeys {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][object]$Object,
        [Parameter(Mandatory)][string[]]$Expected,
        [Parameter(Mandatory)][string]$Context
    )

    $actual = @($Object.PSObject.Properties.Name)
    $missing = @($Expected | Where-Object { $_ -notin $actual })
    $unexpected = @($actual | Where-Object { $_ -notin $Expected })
    if ($missing.Count -gt 0 -or $unexpected.Count -gt 0 -or $actual.Count -ne $Expected.Count) {
        throw "Invalid keys for $Context; missing: $($missing -join ', '); unexpected: $($unexpected -join ', ')"
    }
}

function Assert-HttpsUri {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Value,
        [Parameter(Mandatory)][string]$Context
    )

    $uri = $null
    if (-not [System.Uri]::TryCreate($Value, [System.UriKind]::Absolute, [ref]$uri) -or
        $uri.Scheme -cne 'https' -or
        [string]::IsNullOrWhiteSpace($uri.Host)) {
        throw "Invalid HTTPS URI for $Context"
    }
}

function Assert-LockAsset {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][object]$Asset,
        [Parameter(Mandatory)][string]$Context,
        [switch]$RequireVersionRegex,
        [switch]$RequireAuthenticode
    )

    foreach ($property in @('version', 'sourcePage', 'url', 'size', 'sha256', 'entrypoint')) {
        if ($null -eq $Asset.PSObject.Properties[$property]) {
            throw "Missing $property for $Context"
        }
    }
    if ([string]::IsNullOrWhiteSpace([string]$Asset.version)) {
        throw "Invalid version for $Context"
    }
    Assert-HttpsUri -Value ([string]$Asset.sourcePage) -Context "$Context source page"
    Assert-HttpsUri -Value ([string]$Asset.url) -Context "$Context download"
    if (($Asset.size -isnot [Int64] -and $Asset.size -isnot [Int32]) -or [Int64]$Asset.size -le 0) {
        throw "Invalid size for $Context"
    }
    if ([string]$Asset.sha256 -notmatch '^[0-9a-f]{64}$') {
        throw "Invalid SHA-256 for $Context"
    }
    $null = Assert-SafeArchivePath -EntryName ([string]$Asset.entrypoint)

    if ($RequireVersionRegex) {
        if ($null -eq $Asset.PSObject.Properties['versionRegex'] -or
            [string]::IsNullOrWhiteSpace([string]$Asset.versionRegex)) {
            throw "Missing versionRegex for $Context"
        }
        try {
            $null = [System.Text.RegularExpressions.Regex]::new([string]$Asset.versionRegex)
        }
        catch {
            throw "Invalid versionRegex for $Context"
        }
    }

    if ($RequireAuthenticode) {
        if ($null -eq $Asset.PSObject.Properties['authenticode']) {
            throw "Missing authenticode metadata for $Context"
        }
        Assert-ExactObjectKeys -Object $Asset.authenticode -Expected @('required', 'publishers') -Context "$Context authenticode"
        if ($Asset.authenticode.required -isnot [bool]) {
            throw "Invalid authenticode requirement for $Context"
        }
        $publishers = @($Asset.authenticode.publishers)
        foreach ($publisher in $publishers) {
            if ([string]::IsNullOrWhiteSpace([string]$publisher)) {
                throw "Invalid authenticode publisher for $Context"
            }
        }
        if ($Asset.authenticode.required -and $publishers.Count -eq 0) {
            throw "Missing authenticode publisher for $Context"
        }
    }
}

function Assert-LockInstalledFiles {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][object]$InstalledFiles,
        [Parameter(Mandatory)][string]$Context,
        [Parameter(Mandatory)][string]$Entrypoint,
        [string]$ProbeEntrypoint = ''
    )

    if ($InstalledFiles -isnot [System.Management.Automation.PSCustomObject]) {
        throw "Installed file inventory must be a non-empty object for $Context"
    }
    $properties = @($InstalledFiles.PSObject.Properties)
    if ($properties.Count -eq 0) {
        throw "Installed file inventory must not be empty for $Context"
    }

    $paths = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::OrdinalIgnoreCase
    )
    foreach ($property in $properties) {
        $relativePath = [string]$property.Name
        if ([string]::IsNullOrWhiteSpace($relativePath) -or $relativePath.Contains('\')) {
            throw "Installed file inventory path must use forward slashes for ${Context}: $relativePath"
        }
        $safePath = Assert-SafeArchivePath -EntryName $relativePath
        if ($relativePath.EndsWith('/') -or $safePath.Replace('\', '/') -cne $relativePath) {
            throw "Unsafe installed file inventory path for ${Context}: $relativePath"
        }
        if (-not $paths.Add($relativePath)) {
            throw "Installed file inventory contains a case-insensitive duplicate path for ${Context}: $relativePath"
        }

        $record = $property.Value
        if ($record -isnot [System.Management.Automation.PSCustomObject]) {
            throw "Installed file inventory record must be an object for ${Context}: $relativePath"
        }
        Assert-ExactObjectKeys -Object $record -Expected @('size', 'sha256') `
            -Context "installed file record $Context/$relativePath"
        if (($record.size -isnot [Int64] -and $record.size -isnot [Int32]) -or
            [Int64]$record.size -le 0) {
            throw "Invalid installed file size for ${Context}: $relativePath"
        }
        if ([string]$record.sha256 -notmatch '^[0-9a-f]{64}$') {
            throw "Invalid installed file SHA-256 for ${Context}: $relativePath"
        }
    }

    if (-not $paths.Contains($Entrypoint)) {
        throw "Entrypoint must be listed in installedFiles for ${Context}: $Entrypoint"
    }
    if (-not [string]::IsNullOrWhiteSpace($ProbeEntrypoint) -and
        -not $paths.Contains($ProbeEntrypoint)) {
        throw "Probe entrypoint must be listed in installedFiles for ${Context}: $ProbeEntrypoint"
    }
}

function Assert-PythonRuntimePolicy {
    [CmdletBinding()]
    param([Parameter(Mandatory)][object]$Runtime)

    if ($Runtime -isnot [System.Management.Automation.PSCustomObject]) {
        throw 'Python runtime policy must be an object'
    }
    Assert-ExactObjectKeys -Object $Runtime -Expected @('executable', 'versionRegex', 'authenticode') `
        -Context 'python runtime'

    $executable = [string]$Runtime.executable
    $safeExecutable = Assert-SafeArchivePath -EntryName $executable
    if ([string]::IsNullOrWhiteSpace($executable) -or
        $executable.Contains('/') -or
        $executable.Contains('\') -or
        [System.IO.Path]::GetFileName($executable) -cne $executable -or
        $safeExecutable -cne $executable) {
        throw 'Python runtime executable must be a safe filename'
    }
    if ([string]::IsNullOrWhiteSpace([string]$Runtime.versionRegex)) {
        throw 'Invalid Python runtime versionRegex'
    }
    try {
        $null = [System.Text.RegularExpressions.Regex]::new([string]$Runtime.versionRegex)
    }
    catch {
        throw 'Invalid Python runtime versionRegex'
    }

    $authenticode = $Runtime.authenticode
    if ($authenticode -isnot [System.Management.Automation.PSCustomObject]) {
        throw 'Python runtime authenticode policy must be an object'
    }
    Assert-ExactObjectKeys -Object $authenticode -Expected @('required', 'publishers') `
        -Context 'python runtime authenticode'
    if ($authenticode.required -isnot [bool]) {
        throw 'Invalid Python runtime authenticode requirement'
    }
    if ($authenticode.publishers -isnot [System.Array]) {
        throw 'Invalid Python runtime authenticode publishers'
    }
    $publishers = @($authenticode.publishers)
    foreach ($publisher in $publishers) {
        if ([string]::IsNullOrWhiteSpace([string]$publisher)) {
            throw 'Invalid Python runtime authenticode publisher'
        }
    }
    if ($authenticode.required -and $publishers.Count -eq 0) {
        throw 'Missing Python runtime authenticode publisher'
    }
}

function Read-PetToolchainLock {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$LockPath)

    $lockFull = [System.IO.Path]::GetFullPath($LockPath)
    $encoding = [System.Text.UTF8Encoding]::new($false, $true)
    try {
        $json = $encoding.GetString([System.IO.File]::ReadAllBytes($lockFull))
    }
    catch {
        throw "Lock file is not valid UTF-8: $lockFull"
    }
    if ($json.Length -gt 0 -and $json[0] -eq [char]0xFEFF) {
        throw "Lock file must be UTF-8 without a byte-order mark: $lockFull"
    }
    try {
        $lock = $json | ConvertFrom-Json -Depth 32
    }
    catch {
        throw "Lock file is not valid JSON: $lockFull"
    }
    if ($null -eq $lock) {
        throw "Lock file is empty: $lockFull"
    }

    Assert-ExactObjectKeys -Object $lock -Expected @(
        'schemaVersion', 'platform', 'python', 'pythonRuntime', 'extractor', 'tools', 'models'
    ) -Context 'lock'
    if ($lock.schemaVersion -ne 1 -or $lock.platform -cne 'windows-x64' -or $lock.python -cne '3.12') {
        throw 'Unsupported pet toolchain lock schema or platform'
    }
    Assert-PythonRuntimePolicy -Runtime $lock.pythonRuntime

    Assert-ExactObjectKeys -Object $lock.extractor -Expected @(
        'version', 'sourcePage', 'url', 'size', 'sha256', 'entrypoint', 'versionRegex', 'authenticode'
    ) -Context 'extractor'
    Assert-LockAsset -Asset $lock.extractor -Context 'extractor' -RequireVersionRegex -RequireAuthenticode

    Assert-ExactObjectKeys -Object $lock.tools -Expected @('ffmpeg', 'imagemagick', 'libwebp') -Context 'tools'
    foreach ($toolName in @('ffmpeg', 'imagemagick', 'libwebp')) {
        $tool = $lock.tools.$toolName
        $expectedKeys = @(
            'version', 'sourcePage', 'url', 'size', 'sha256', 'entrypoint', 'versionRegex', 'authenticode',
            'installedFiles'
        )
        if ($toolName -ceq 'ffmpeg') {
            $expectedKeys += 'probeEntrypoint'
        }
        Assert-ExactObjectKeys -Object $tool -Expected $expectedKeys -Context "tool $toolName"
        Assert-LockAsset -Asset $tool -Context "tool $toolName" -RequireVersionRegex -RequireAuthenticode
        if ($toolName -ceq 'ffmpeg') {
            $null = Assert-SafeArchivePath -EntryName ([string]$tool.probeEntrypoint)
        }
        $probeEntrypoint = if ($toolName -ceq 'ffmpeg') {
            [string]$tool.probeEntrypoint
        }
        else {
            ''
        }
        Assert-LockInstalledFiles -InstalledFiles $tool.installedFiles -Context "tool $toolName" `
            -Entrypoint ([string]$tool.entrypoint) -ProbeEntrypoint $probeEntrypoint
    }

    Assert-ExactObjectKeys -Object $lock.models -Expected @('isnet-anime', 'u2net_human_seg') -Context 'models'
    foreach ($modelName in @('isnet-anime', 'u2net_human_seg')) {
        $model = $lock.models.$modelName
        Assert-ExactObjectKeys -Object $model -Expected @(
            'version', 'sourcePage', 'url', 'size', 'sha256', 'entrypoint', 'modelName'
        ) -Context "model $modelName"
        Assert-LockAsset -Asset $model -Context "model $modelName"
        if ([string]::IsNullOrWhiteSpace([string]$model.modelName)) {
            throw "Invalid model name for $modelName"
        }
        if (-not ([string]$model.entrypoint).StartsWith('models/', [System.StringComparison]::Ordinal)) {
            throw "Model entrypoint must remain below models: $modelName"
        }
    }

    return $lock
}

function Invoke-CheckedProcess {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [string[]]$ArgumentList = @(),
        [ValidateRange(1, 2147483)][int]$TimeoutSeconds = 300,
        [int[]]$ExpectedExitCode = @(0),
        [string]$WorkingDirectory = '',
        [hashtable]$Environment = @{},
        [switch]$CleanEnvironment
    )

    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    if ($CleanEnvironment) {
        if (-not [System.IO.Path]::IsPathRooted($FilePath)) {
            throw 'Clean checked process requires an absolute executable path'
        }
        $executableItem = Get-Item -LiteralPath ([System.IO.Path]::GetFullPath($FilePath)) -Force
        if ($executableItem -is [System.IO.DirectoryInfo] -or
            ($executableItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Clean checked process requires a regular executable file: $FilePath"
        }
        $startInfo.FileName = $executableItem.FullName
    }
    elseif ([System.IO.Path]::IsPathRooted($FilePath)) {
        $startInfo.FileName = [System.IO.Path]::GetFullPath($FilePath)
    }
    else {
        $startInfo.FileName = $FilePath
    }
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.CreateNoWindow = $true
    if (-not [string]::IsNullOrWhiteSpace($WorkingDirectory)) {
        $startInfo.WorkingDirectory = [System.IO.Path]::GetFullPath($WorkingDirectory)
    }
    if ($startInfo.PSObject.Properties.Name -notcontains 'Environment') {
        throw 'This PowerShell runtime does not support checked process environments'
    }
    if ($CleanEnvironment) {
        $startInfo.Environment.Clear()
        foreach ($name in @(
                'SystemRoot',
                'WINDIR',
                'ComSpec',
                'TEMP',
                'TMP',
                'PROCESSOR_ARCHITECTURE',
                'PROCESSOR_ARCHITEW6432',
                'ProgramW6432'
            )) {
            $value = [System.Environment]::GetEnvironmentVariable(
                $name,
                [System.EnvironmentVariableTarget]::Process
            )
            if (-not [string]::IsNullOrWhiteSpace($value)) {
                $startInfo.Environment[$name] = $value
            }
        }
    }
    foreach ($pair in $Environment.GetEnumerator()) {
        $name = [string]$pair.Key
        $value = [string]$pair.Value
        if ([string]::IsNullOrWhiteSpace($name) -or
            $name.IndexOf([char]0) -ge 0 -or
            $name.Contains('=') -or
            $value.IndexOf([char]0) -ge 0) {
            throw 'Invalid checked process environment entry'
        }
        $startInfo.Environment[$name] = $value
    }
    if ($startInfo.PSObject.Properties.Name -notcontains 'ArgumentList') {
        throw 'This PowerShell runtime does not support checked process argument vectors'
    }
    foreach ($argument in $ArgumentList) {
        $null = $startInfo.ArgumentList.Add([string]$argument)
    }

    $process = [System.Diagnostics.Process]::new()
    try {
        $process.StartInfo = $startInfo
        if (-not $process.Start()) {
            throw "Could not start process: $FilePath"
        }
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
            try {
                $process.Kill($true)
            }
            catch {
                # The process may have exited while the timeout branch was entered.
            }
            if (-not $process.WaitForExit(5000)) {
                throw "Timed-out process tree did not terminate within the bounded cleanup window: $FilePath"
            }
            if (-not $stdoutTask.Wait(5000) -or -not $stderrTask.Wait(5000)) {
                throw "Timed-out process output drain did not complete within the bounded cleanup window: $FilePath"
            }
            throw "Process timed out after $TimeoutSeconds seconds: $FilePath"
        }
        if (-not $stdoutTask.Wait(5000) -or -not $stderrTask.Wait(5000)) {
            throw "Process output drain did not complete within the bounded cleanup window: $FilePath"
        }
        $stdout = $stdoutTask.GetAwaiter().GetResult()
        $stderr = $stderrTask.GetAwaiter().GetResult()
        if ($process.ExitCode -notin $ExpectedExitCode) {
            throw "Process failed with exit code $($process.ExitCode): $FilePath`n$stdout`n$stderr"
        }
        return [pscustomobject]@{
            ExitCode = $process.ExitCode
            StdOut = $stdout
            StdErr = $stderr
        }
    }
    finally {
        $process.Dispose()
    }
}

function Get-DeterministicTreeInventory {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Root)

    $rootFull = [System.IO.Path]::GetFullPath($Root)
    if (-not (Test-Path -LiteralPath $rootFull -PathType Container)) {
        throw "Tree inventory root does not exist: $rootFull"
    }
    Assert-NoReparsePoints -Root $rootFull
    $records = [System.Collections.Generic.Dictionary[string, object]]::new(
        [System.StringComparer]::Ordinal
    )
    $paths = [System.Collections.Generic.List[string]]::new()
    foreach ($item in @(Get-ChildItem -LiteralPath $rootFull -Force -Recurse)) {
        if ($item -is [System.IO.DirectoryInfo]) {
            continue
        }
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Reparse point is not allowed in tree inventory: $($item.FullName)"
        }
        $relativePath = [System.IO.Path]::GetRelativePath($rootFull, $item.FullName).Replace('\', '/')
        $normalisedPath = (Assert-SafeArchivePath -EntryName $relativePath).Replace('\', '/')
        if ($relativePath -cne $normalisedPath) {
            throw "Unsafe tree inventory path: $relativePath"
        }
        $null = Resolve-ContainedPath -Root $rootFull -RelativePath ($relativePath -replace '/', '\')
        if (-not $records.TryAdd($relativePath, [pscustomobject]@{
                    Size = [Int64]$item.Length
                    Sha256 = (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
                })) {
            throw "Duplicate tree inventory path: $relativePath"
        }
        $paths.Add($relativePath)
    }

    $paths.Sort([System.StringComparer]::Ordinal)
    $encoding = [System.Text.UTF8Encoding]::new($false)
    $hasher = [System.Security.Cryptography.IncrementalHash]::CreateHash(
        [System.Security.Cryptography.HashAlgorithmName]::SHA256
    )
    try {
        foreach ($relativePath in $paths) {
            $record = $records[$relativePath]
            $canonicalRecord = $relativePath + [char]0 +
                ([string]::Format([System.Globalization.CultureInfo]::InvariantCulture, '{0}', [Int64]$record.Size)) +
                [char]0 + $record.Sha256 + "`n"
            $hasher.AppendData($encoding.GetBytes($canonicalRecord))
        }
        $treeSha256 = ([System.BitConverter]::ToString($hasher.GetHashAndReset())).Replace('-', '').ToLowerInvariant()
    }
    finally {
        $hasher.Dispose()
    }
    Assert-NoReparsePoints -Root $rootFull
    return [pscustomobject]@{
        fileCount = [Int64]$paths.Count
        treeSha256 = $treeSha256
    }
}

function ConvertFrom-SevenZipTechnicalListing {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Output)

    $afterSeparator = $false
    $separatorCount = 0
    $records = [System.Collections.Generic.List[hashtable]]::new()
    $current = @{}
    if ($Output -match "`r(?!`n)") {
        throw 'Structured archive listing contains an ambiguous control character'
    }
    foreach ($line in ($Output -split "`r?`n")) {
        if ($line -match '[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]') {
            throw 'Structured archive listing contains an ambiguous control character'
        }
        if ($line -eq '----------') {
            $separatorCount++
            if ($separatorCount -ne 1) {
                throw 'Archive listing contains more than one structured entry separator'
            }
            $afterSeparator = $true
            $current = @{}
            continue
        }
        if (-not $afterSeparator) {
            continue
        }
        if ([string]::IsNullOrWhiteSpace($line)) {
            if ($current.Count -gt 0) {
                if (-not $current.ContainsKey('Path')) {
                    throw 'Structured archive listing record did not contain a path'
                }
                $linkMetadata = @($current.Keys | Where-Object { $_ -match '(?i)(symbolic|hard|reparse|link)' })
                if ($linkMetadata.Count -gt 0 -or
                    ($current.ContainsKey('Attributes') -and $current['Attributes'] -match '(?i)(^|[\s,])L([\s,]|$)')) {
                    throw "Unsafe archive link metadata: $($current['Path'])"
                }
                $null = Assert-SafeArchivePath -EntryName ([string]$current['Path'])
                $records.Add($current)
                $current = @{}
            }
            continue
        }
        $match = [System.Text.RegularExpressions.Regex]::Match($line, '^(?<key>[^=]+) =(?<value>.*)$')
        if (-not $match.Success) {
            throw "Unrecognised structured archive-listing line: $line"
        }
        $key = $match.Groups['key'].Value.Trim()
        if ([string]::IsNullOrWhiteSpace($key) -or $current.ContainsKey($key)) {
            throw 'Invalid structured archive-listing record'
        }
        $current[$key] = $match.Groups['value'].Value.TrimStart()
    }
    if ($current.Count -gt 0) {
        if (-not $current.ContainsKey('Path')) {
            throw 'Structured archive listing record did not contain a path'
        }
        $linkMetadata = @($current.Keys | Where-Object { $_ -match '(?i)(symbolic|hard|reparse|link)' })
        if ($linkMetadata.Count -gt 0 -or
            ($current.ContainsKey('Attributes') -and $current['Attributes'] -match '(?i)(^|[\s,])L([\s,]|$)')) {
            throw "Unsafe archive link metadata: $($current['Path'])"
        }
        $null = Assert-SafeArchivePath -EntryName ([string]$current['Path'])
        $records.Add($current)
    }
    if ($separatorCount -ne 1) {
        throw 'Archive listing did not contain a structured entry separator'
    }
    return $records
}

function Assert-SafeZipEntryMetadata {
    [CmdletBinding()]
    param([Parameter(Mandatory)][System.IO.Compression.ZipArchiveEntry]$Entry)

    $externalAttributes = [Int64]$Entry.ExternalAttributes
    $unixMode = ($externalAttributes -shr 16) -band 0xFFFF
    $unixType = $unixMode -band 0xF000
    $dosAttributes = $externalAttributes -band 0xFFFF
    if ($unixType -eq 0xA000 -or
        ($dosAttributes -band [Int64][System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Unsafe archive link metadata: $($Entry.FullName)"
    }
}

function Assert-SafeArchiveEntries {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$ArchivePath,
        [ValidateSet('Zip', 'SevenZip')][string]$ArchiveType,
        [string]$SevenZipPath = ''
    )

    $archiveFull = [System.IO.Path]::GetFullPath($ArchivePath)
    $archiveItem = Get-Item -LiteralPath $archiveFull -Force
    if ($archiveItem -is [System.IO.DirectoryInfo] -or
        ($archiveItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Expected regular archive file: $archiveFull"
    }

    if ([string]::IsNullOrWhiteSpace($ArchiveType)) {
        $ArchiveType = switch ([System.IO.Path]::GetExtension($archiveFull).ToLowerInvariant()) {
            '.zip' { 'Zip' }
            '.7z' { 'SevenZip' }
            default { throw "Unsupported archive type: $archiveFull" }
        }
    }

    if ($ArchiveType -ceq 'Zip') {
        $archive = [System.IO.Compression.ZipFile]::OpenRead($archiveFull)
        try {
            foreach ($entry in $archive.Entries) {
                $null = Assert-SafeArchivePath -EntryName $entry.FullName
                Assert-SafeZipEntryMetadata -Entry $entry
            }
        }
        finally {
            $archive.Dispose()
        }
        return
    }

    if ([string]::IsNullOrWhiteSpace($SevenZipPath)) {
        throw 'A verified standalone extractor path is required for a 7z archive'
    }
    $extractorFull = [System.IO.Path]::GetFullPath($SevenZipPath)
    $extractorItem = Get-Item -LiteralPath $extractorFull -Force
    if ($extractorItem -is [System.IO.DirectoryInfo] -or
        ($extractorItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Expected verified regular extractor file: $extractorFull"
    }

    $listing = Invoke-CheckedProcess -FilePath $extractorFull -ArgumentList @('l', '-slt', '--', $archiveFull)
    foreach ($record in (ConvertFrom-SevenZipTechnicalListing -Output $listing.StdOut)) {
        if (-not $record.ContainsKey('Path')) {
            throw 'Structured archive listing record did not contain a path'
        }
        $linkMetadata = @($record.Keys | Where-Object { $_ -match '(?i)(symbolic|hard|reparse|link)' })
        if ($linkMetadata.Count -gt 0 -or
            ($record.ContainsKey('Attributes') -and $record['Attributes'] -match '(?i)(^|[\s,])L([\s,]|$)')) {
            throw "Unsafe archive link metadata: $($record['Path'])"
        }
        $null = Assert-SafeArchivePath -EntryName ([string]$record['Path'])
    }
}

function Expand-SafeZipArchive {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$ArchivePath,
        [Parameter(Mandatory)][string]$DestinationRoot
    )

    $archiveFull = [System.IO.Path]::GetFullPath($ArchivePath)
    $destinationFull = [System.IO.Path]::GetFullPath($DestinationRoot)
    [System.IO.Directory]::CreateDirectory($destinationFull) | Out-Null
    Assert-NoReparsePoints -Root $destinationFull
    Assert-SafeArchiveEntries -ArchivePath $archiveFull -ArchiveType Zip

    $archive = [System.IO.Compression.ZipFile]::OpenRead($archiveFull)
    try {
        foreach ($entry in $archive.Entries) {
            $normalised = Assert-SafeArchivePath -EntryName $entry.FullName
            Assert-SafeZipEntryMetadata -Entry $entry
            $relative = $normalised -replace '/', '\'
            $target = Resolve-ContainedPath -Root $destinationFull -RelativePath $relative
            $isDirectory = $entry.FullName.EndsWith('/') -or $entry.FullName.EndsWith('\')
            if ($isDirectory) {
                $target = Assert-ContainedWritePath -Root $destinationFull -Path $target
                [System.IO.Directory]::CreateDirectory($target) | Out-Null
                Assert-NoReparsePoints -Root $destinationFull
                continue
            }

            $parent = Split-Path -Parent $target
            $target = Assert-ContainedWritePath -Root $destinationFull -Path $target
            [System.IO.Directory]::CreateDirectory($parent) | Out-Null
            $target = Assert-ContainedWritePath -Root $destinationFull -Path $target
            $source = $entry.Open()
            try {
                $destination = [System.IO.File]::Open(
                    $target,
                    [System.IO.FileMode]::CreateNew,
                    [System.IO.FileAccess]::Write,
                    [System.IO.FileShare]::None
                )
                try {
                    $source.CopyTo($destination)
                }
                finally {
                    $destination.Dispose()
                }
            }
            finally {
                $source.Dispose()
            }
        }
    }
    finally {
        $archive.Dispose()
    }
    Assert-NoReparsePoints -Root $destinationFull
}

function Expand-SafeSevenZipArchive {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$ArchivePath,
        [Parameter(Mandatory)][string]$SevenZipPath,
        [Parameter(Mandatory)][string]$DestinationRoot
    )

    $archiveFull = [System.IO.Path]::GetFullPath($ArchivePath)
    $extractorFull = [System.IO.Path]::GetFullPath($SevenZipPath)
    $destinationFull = [System.IO.Path]::GetFullPath($DestinationRoot)
    [System.IO.Directory]::CreateDirectory($destinationFull) | Out-Null
    Assert-NoReparsePoints -Root $destinationFull
    Assert-SafeArchiveEntries -ArchivePath $archiveFull -ArchiveType SevenZip -SevenZipPath $extractorFull
    $null = Invoke-CheckedProcess -FilePath $extractorFull -ArgumentList @(
        'x', '-y', ("-o{0}" -f $destinationFull), '--', $archiveFull
    )
    Assert-NoReparsePoints -Root $destinationFull
}

function Get-PetToolchainCachePath {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$DownloadsRoot,
        [Parameter(Mandatory)][object]$Asset
    )

    if ([string]$Asset.sha256 -notmatch '^[0-9a-f]{64}$') {
        throw 'Asset lacks a valid SHA-256 cache key'
    }
    $uri = [System.Uri]$Asset.url
    if (-not $uri.IsAbsoluteUri -or $uri.Scheme -cne 'https') {
        throw 'Asset lacks a valid HTTPS URL'
    }
    $assetName = [System.IO.Path]::GetFileName($uri.AbsolutePath)
    if ([string]::IsNullOrWhiteSpace($assetName) -or
        $assetName -ne [System.IO.Path]::GetFileName($assetName)) {
        throw 'Asset URL does not name a safe file'
    }
    return Resolve-ContainedPath -Root $DownloadsRoot -RelativePath "$(($Asset.sha256).ToLowerInvariant())-$assetName"
}

function Resolve-ExplicitHttpsRedirect {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$InitialUri,
        [Parameter(Mandatory)][scriptblock]$Request,
        [ValidateRange(0, 10)][int]$MaximumRedirects = 5
    )

    $original = [System.Uri]$InitialUri
    if (-not $original.IsAbsoluteUri -or $original.Scheme -cne 'https') {
        throw 'Locked download URL must be HTTPS'
    }
    $current = $original
    for ($redirectCount = 0; $redirectCount -le $MaximumRedirects; $redirectCount++) {
        if ($current.Scheme -cne 'https') {
            throw "Download redirect must remain HTTPS: $current"
        }
        $response = & $Request $current
        if ($response -isnot [System.Net.Http.HttpResponseMessage]) {
            throw 'Explicit download request returned an invalid HTTP response'
        }
        $status = [int]$response.StatusCode
        if ($status -notin @(301, 302, 303, 307, 308)) {
            return [pscustomobject]@{
                OriginalUri = $original
                FinalUri = $current
                Response = $response
            }
        }
        try {
            $location = $response.Headers.Location
            if ($redirectCount -eq $MaximumRedirects -or $null -eq $location -or
                [string]::IsNullOrWhiteSpace($location.OriginalString)) {
                throw "Download redirect limit or location failure for: $current"
            }
            try {
                $next = [System.Uri]::new($current, $location)
            }
            catch {
                throw "Download redirect location is invalid for: $current"
            }
            if ($next.Scheme -cne 'https') {
                throw "Download redirect must remain HTTPS: $next"
            }
        }
        finally {
            $response.Dispose()
        }
        $current = $next
    }
    throw 'Download redirect loop ended unexpectedly'
}

function Invoke-ExplicitHttpsDownload {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Uri,
        [Parameter(Mandatory)][string]$OutFile,
        [System.Net.Http.HttpMessageHandler]$HttpMessageHandler
    )

    $handler = $HttpMessageHandler
    $ownsHandler = $null -eq $handler
    if ($ownsHandler) {
        $handler = [System.Net.Http.HttpClientHandler]::new()
        $handler.AllowAutoRedirect = $false
    }
    $client = [System.Net.Http.HttpClient]::new($handler, $false)
    try {
        $request = {
            param([System.Uri]$RequestUri)
            $message = [System.Net.Http.HttpRequestMessage]::new(
                [System.Net.Http.HttpMethod]::Get,
                $RequestUri
            )
            try {
                return $client.SendAsync(
                    $message,
                    [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead
                ).GetAwaiter().GetResult()
            }
            finally {
                $message.Dispose()
            }
        }.GetNewClosure()
        $resolved = Resolve-ExplicitHttpsRedirect -InitialUri $Uri -Request $request
        $response = $resolved.Response
        try {
            if (-not $response.IsSuccessStatusCode) {
                throw "Locked download failed with HTTP status $([int]$response.StatusCode): $($resolved.FinalUri)"
            }
            $source = $response.Content.ReadAsStream()
            try {
                $destination = [System.IO.File]::Open(
                    $OutFile,
                    [System.IO.FileMode]::Truncate,
                    [System.IO.FileAccess]::Write,
                    [System.IO.FileShare]::None
                )
                try {
                    $source.CopyTo($destination)
                    $destination.Flush($true)
                }
                finally {
                    $destination.Dispose()
                }
            }
            finally {
                $source.Dispose()
            }
        }
        finally {
            $response.Dispose()
        }
    }
    finally {
        $client.Dispose()
        if ($ownsHandler) {
            $handler.Dispose()
        }
    }
}

function Enter-PetToolchainCacheLock {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$DownloadsRoot,
        [Parameter(Mandatory)][string]$CachePath,
        [ValidateRange(1, 600)][int]$TimeoutSeconds = 120
    )

    $lockPath = Resolve-ContainedPath -Root $DownloadsRoot -RelativePath "$(Split-Path -Leaf $CachePath).lock"
    $deadline = [System.DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ($true) {
        try {
            $stream = [System.IO.File]::Open(
                $lockPath,
                [System.IO.FileMode]::OpenOrCreate,
                [System.IO.FileAccess]::ReadWrite,
                [System.IO.FileShare]::None
            )
            $item = Get-Item -LiteralPath $lockPath -Force
            if ($item -is [System.IO.DirectoryInfo] -or
                ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                $stream.Dispose()
                throw "Unsafe cache lock path: $lockPath"
            }
            return $stream
        }
        catch [System.IO.IOException] {
            if ([System.DateTime]::UtcNow -ge $deadline) {
                throw "Timed out waiting for cache lock: $lockPath"
            }
            Start-Sleep -Milliseconds 100
        }
    }
}

function Assert-OpenFileDigest {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][System.IO.FileStream]$Stream,
        [Parameter(Mandatory)][Int64]$ExpectedSize,
        [Parameter(Mandatory)][string]$ExpectedSha256
    )

    if ($Stream.Length -ne $ExpectedSize) {
        throw "File size mismatch for held asset: expected $ExpectedSize, got $($Stream.Length)"
    }
    $Stream.Position = 0
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $actual = ([System.BitConverter]::ToString($sha.ComputeHash($Stream))).Replace('-', '').ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
        $Stream.Position = 0
    }
    if ($actual -cne $ExpectedSha256.ToLowerInvariant()) {
        throw 'SHA-256 mismatch for held asset'
    }
}

function Open-VerifiedAsset {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][object]$Asset,
        [Parameter(Mandatory)][string]$DownloadsRoot
    )

    $path = Get-VerifiedDownload -Asset $Asset -DownloadsRoot $DownloadsRoot
    $path = Assert-ContainedWritePath -Root $DownloadsRoot -Path $path
    $stream = [System.IO.File]::Open(
        $path,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read,
        [System.IO.FileShare]::Read
    )
    try {
        Assert-OpenFileDigest -Stream $stream -ExpectedSize ([Int64]$Asset.size) -ExpectedSha256 ([string]$Asset.sha256)
        return [pscustomobject]@{
            Path = $path
            Stream = $stream
        }
    }
    catch {
        $stream.Dispose()
        throw
    }
}

function Remove-VerifiedRegularFile {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][string]$Path
    )

    $rootFull = [System.IO.Path]::GetFullPath($Root)
    $pathFull = [System.IO.Path]::GetFullPath($Path)
    $relative = [System.IO.Path]::GetRelativePath($rootFull, $pathFull)
    $verifiedPath = Resolve-ContainedPath -Root $rootFull -RelativePath $relative
    if ($verifiedPath -cne $pathFull) {
        throw "Refusing to remove an unresolved cache file: $pathFull"
    }
    $item = Get-Item -LiteralPath $verifiedPath -Force
    if ($item -is [System.IO.DirectoryInfo] -or
        ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Refusing to remove a non-regular cache file: $verifiedPath"
    }
    [System.IO.File]::Delete($verifiedPath)
}

function Get-VerifiedDownload {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][object]$Asset,
        [Parameter(Mandatory)][string]$DownloadsRoot
    )

    $downloadsFull = [System.IO.Path]::GetFullPath($DownloadsRoot)
    [System.IO.Directory]::CreateDirectory($downloadsFull) | Out-Null
    Assert-NoReparsePoints -Root $downloadsFull
    $cachePath = Get-PetToolchainCachePath -DownloadsRoot $downloadsFull -Asset $Asset
    $cacheLock = Enter-PetToolchainCacheLock -DownloadsRoot $downloadsFull -CachePath $cachePath
    try {
        if (Test-Path -LiteralPath $cachePath) {
            try {
                Assert-FileDigest -Path $cachePath -ExpectedSize ([Int64]$Asset.size) -ExpectedSha256 ([string]$Asset.sha256)
                return $cachePath
            }
            catch {
                Remove-VerifiedRegularFile -Root $downloadsFull -Path $cachePath
            }
        }

        $partialPath = ''
        for ($attempt = 0; $attempt -lt 10; $attempt++) {
            $candidate = Resolve-ContainedPath -Root $downloadsFull -RelativePath "$(Split-Path -Leaf $cachePath).partial.$([System.Guid]::NewGuid().ToString('N'))"
            try {
                $candidate = Assert-ContainedWritePath -Root $downloadsFull -Path $candidate
                $reservation = [System.IO.File]::Open(
                    $candidate,
                    [System.IO.FileMode]::CreateNew,
                    [System.IO.FileAccess]::Write,
                    [System.IO.FileShare]::None
                )
                $reservation.Dispose()
                $partialPath = $candidate
                break
            }
            catch [System.IO.IOException] {
                continue
            }
        }
        if ([string]::IsNullOrWhiteSpace($partialPath)) {
            throw "Could not reserve a unique download partial path for: $cachePath"
        }
        try {
            Invoke-ExplicitHttpsDownload -Uri ([string]$Asset.url) -OutFile $partialPath
            Assert-FileDigest -Path $partialPath -ExpectedSize ([Int64]$Asset.size) -ExpectedSha256 ([string]$Asset.sha256)
            [System.IO.File]::Move($partialPath, $cachePath)
            return $cachePath
        }
        finally {
            if (Test-Path -LiteralPath $partialPath) {
                Remove-VerifiedRegularFile -Root $downloadsFull -Path $partialPath
            }
        }
    }
    finally {
        $cacheLock.Dispose()
    }
}
