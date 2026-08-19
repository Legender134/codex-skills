from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import tomllib
from urllib.parse import urlparse
import zipfile

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECT_CONFIG = REPO_ROOT / ".codex" / "config.toml"
LOCK_PATH = REPO_ROOT / "tools" / "pet-toolchain.lock.json"
MEDIA_INPUT = REPO_ROOT / "requirements" / "pet-media.in"
MEDIA_LOCK = REPO_ROOT / "requirements" / "pet-media.txt"
COMMON_SCRIPT = REPO_ROOT / "scripts" / "pet_toolchain_common.ps1"
SETUP_SCRIPT = REPO_ROOT / "scripts" / "setup_pet_toolchain.ps1"
VERIFY_SCRIPT = REPO_ROOT / "scripts" / "verify_pet_toolchain.ps1"
MEDIA_VERIFY = REPO_ROOT / "tools" / "verify_pet_media.py"
QT_VERIFY = REPO_ROOT / "tools" / "verify_qt_webp.py"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
TINY_EXTRACTOR_PAYLOAD = b"tiny-locked-extractor\n"
WINDOWS_ABSOLUTE = re.compile(r"(?i)^[a-z]:[\\/]")
PINNED_REQUIREMENT = re.compile(
    r"^[^\s#][^\s]*==[^\s\\]+(?:\s*;[^\n]*)?\s*\\?$"
)
SHA256_HASH_OPTION = re.compile(r"^\s+--hash=sha256:[0-9a-f]{64}(?:\s*\\)?\s*$")


@pytest.fixture
def short_local_tmp_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        pytest.skip("Windows short-path cleanup contract requires LOCALAPPDATA")
    path = Path(tempfile.mkdtemp(prefix="ptc-", dir=local_app_data))
    try:
        yield path
    finally:
        shutil.rmtree(path)


def load_project_config() -> dict[str, object]:
    with PROJECT_CONFIG.open("rb") as stream:
        return tomllib.load(stream)


def iter_values(value: object):
    if isinstance(value, dict):
        for nested in value.values():
            yield from iter_values(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from iter_values(nested)
    else:
        yield value


def pinned_requirement_blocks(locked: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] | None = None

    for line in locked.splitlines():
        if PINNED_REQUIREMENT.fullmatch(line):
            if current is not None:
                blocks.append(current)
            current = [line]
        elif current is not None and line[:1].isspace():
            current.append(line)
        elif line.strip() and not line.lstrip().startswith("#"):
            if current is not None:
                blocks.append(current)
            current = None

    if current is not None:
        blocks.append(current)

    return blocks


def powershell() -> str:
    executable = shutil.which("pwsh.exe") or shutil.which("powershell.exe")
    if executable is None:
        raise AssertionError("PowerShell is required")
    return executable


def powershell_literal(value: Path | str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def run_common_script(
    command: str, *, environment: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    script = (
        "$ErrorActionPreference = 'Stop'; "
        f". {powershell_literal(COMMON_SCRIPT)}; "
        f"{command}"
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    child_environment = os.environ.copy()
    if environment is not None:
        child_environment.update(environment)
    return subprocess.run(
        [
            powershell(),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            encoded,
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=30,
        check=False,
        env=child_environment,
    )


def run_setup_script(command: str) -> subprocess.CompletedProcess[str]:
    script = "$ErrorActionPreference = 'Stop'; " + command
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return subprocess.run(
        [
            powershell(),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            encoded,
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=30,
        check=False,
    )


def test_project_codex_config_has_exact_pet_routing() -> None:
    config = load_project_config()

    assert config == {
        "model": "gpt-5.6-sol",
        "model_reasoning_effort": "xhigh",
        "features": {"multi_agent": True},
        "agents": {
            "enabled": True,
            "max_concurrent_threads_per_session": 1,
            "default_subagent_model": "gpt-5.6-terra",
            "default_subagent_reasoning_effort": "max",
            "interrupt_message": True,
        },
    }


def test_project_codex_config_contains_no_machine_or_security_override() -> None:
    config = load_project_config()
    forbidden_keys = {
        "approval_policy",
        "sandbox_mode",
        "projects",
        "mcp_servers",
        "plugins",
        "notify",
        "shell_environment_policy",
    }

    assert forbidden_keys.isdisjoint(config)
    for value in iter_values(config):
        if isinstance(value, str):
            assert not WINDOWS_ABSOLUTE.match(value)
            assert "admin" not in value.casefold()
            assert not PureWindowsPath(value).is_absolute()


def test_pet_toolchain_lock_has_exact_assets() -> None:
    manifest = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    manifest_without_task2_extensions = json.loads(json.dumps(manifest))
    del manifest_without_task2_extensions["pythonRuntime"]
    for tool_name in ("ffmpeg", "imagemagick", "libwebp"):
        del manifest_without_task2_extensions["tools"][tool_name]["installedFiles"]

    assert manifest["schemaVersion"] == 1
    assert manifest["platform"] == "windows-x64"
    assert set(manifest["tools"]) == {"ffmpeg", "imagemagick", "libwebp"}
    assert set(manifest["models"]) == {"isnet-anime", "u2net_human_seg"}
    assert manifest["tools"]["ffmpeg"]["version"] == "9.0.1"
    assert manifest["tools"]["imagemagick"]["version"] == "7.1.2-29"
    assert manifest["tools"]["libwebp"]["version"] == "1.6.0"

    for group in ("tools", "models"):
        for item in manifest[group].values():
            assert item["url"].startswith("https://")
            assert item["size"] > 0
            assert SHA256.fullmatch(item["sha256"])
            assert not WINDOWS_ABSOLUTE.match(item["entrypoint"])
            assert ".." not in PureWindowsPath(item["entrypoint"]).parts

    assert manifest_without_task2_extensions == {
        "schemaVersion": 1,
        "platform": "windows-x64",
        "python": "3.12",
        "extractor": {
            "version": "26.02",
            "sourcePage": "https://www.7-zip.org/download.html",
            "url": "https://github.com/ip7z/7zip/releases/download/26.02/7zr.exe",
            "size": 602112,
            "sha256": "56b8cc9f4971cef253644fafe54063ed7fdca551d4dee0f8c6baa81b855acd72",
            "entrypoint": "7zr.exe",
            "versionRegex": r"^7-Zip \(r\) 26\.02 \(x86\) : Igor Pavlov : Public domain : 2026-06-25$",
            "authenticode": {"required": False, "publishers": []},
        },
        "tools": {
            "ffmpeg": {
                "version": "9.0.1",
                "sourcePage": "https://www.gyan.dev/ffmpeg/builds/",
                "url": "https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-9.0.1-essentials_build.7z",
                "size": 34372199,
                "sha256": "49a73bdf0850092a252ac4641d922f3048d63ed113e196cc65ce1e4f7fb33e85",
                "entrypoint": "bin/ffmpeg.exe",
                "versionRegex": r"^ffmpeg version 9\.0\.1(?:[-\s]|$)",
                "authenticode": {"required": False, "publishers": []},
                "probeEntrypoint": "bin/ffprobe.exe",
            },
            "imagemagick": {
                "version": "7.1.2-29",
                "sourcePage": "https://imagemagick.org/download/",
                "url": "https://github.com/ImageMagick/ImageMagick/releases/download/7.1.2-29/ImageMagick-7.1.2-29-portable-Q16-x64.7z",
                "size": 11682401,
                "sha256": "4715072c158c46bbdc3e6971817e92ed43fca7c93142cad142ee42c603baaac1",
                "entrypoint": "magick.exe",
                "versionRegex": r"^Version: ImageMagick 7\.1\.2-29 Q16 x64\b",
                "authenticode": {
                    "required": True,
                    "publishers": [
                        "CN=ImageMagick Studio LLC, O=ImageMagick Studio LLC, L=Landenberg, S=Pennsylvania, C=US"
                    ],
                },
            },
            "libwebp": {
                "version": "1.6.0",
                "sourcePage": "https://developers.google.com/speed/webp/download",
                "url": "https://storage.googleapis.com/downloads.webmproject.org/releases/webp/libwebp-1.6.0-windows-x64.zip",
                "size": 4106264,
                "sha256": "48886f506b21f62e4661f0f4cbfca19800897c385128e8902542d29a950c93f1",
                "entrypoint": "bin/cwebp.exe",
                "versionRegex": r"^1\.6\.0(?:\s|$)",
                "authenticode": {"required": False, "publishers": []},
            },
        },
        "models": {
            "isnet-anime": {
                "version": "rembg-v0.0.0",
                "sourcePage": "https://github.com/danielgatis/rembg/releases/tag/v0.0.0",
                "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/isnet-anime.onnx",
                "size": 176069933,
                "sha256": "f15622d853e8260172812b657053460e20806f04b9e05147d49af7bed31a6e99",
                "entrypoint": "models/isnet-anime.onnx",
                "modelName": "isnet-anime",
            },
            "u2net_human_seg": {
                "version": "rembg-v0.0.0",
                "sourcePage": "https://github.com/danielgatis/rembg/releases/tag/v0.0.0",
                "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net_human_seg.onnx",
                "size": 175997641,
                "sha256": "01eb6a29a5c4d8edb30b56adad9bb3a2a0535338e480724a213e0acfd2d1c73c",
                "entrypoint": "models/u2net_human_seg.onnx",
                "modelName": "u2net_human_seg",
            },
        },
    }


def test_pet_toolchain_lock_requires_safe_extractor_bootstrap() -> None:
    manifest = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    extractor = manifest["extractor"]

    assert set(extractor) == {
        "version",
        "sourcePage",
        "url",
        "size",
        "sha256",
        "entrypoint",
        "versionRegex",
        "authenticode",
    }
    assert extractor["version"] == "26.02"
    assert extractor["sourcePage"] == "https://www.7-zip.org/download.html"
    assert (
        extractor["url"]
        == "https://github.com/ip7z/7zip/releases/download/26.02/7zr.exe"
    )
    assert extractor["size"] > 0
    assert SHA256.fullmatch(extractor["sha256"])
    assert extractor["entrypoint"] == "7zr.exe"
    assert not WINDOWS_ABSOLUTE.match(extractor["entrypoint"])
    assert ".." not in PureWindowsPath(extractor["entrypoint"]).parts
    assert re.fullmatch(
        extractor["versionRegex"],
        "7-Zip (r) 26.02 (x86) : Igor Pavlov : Public domain : 2026-06-25",
    )
    assert extractor["authenticode"] == {"required": False, "publishers": []}


def test_pet_toolchain_lock_requires_trusted_python_runtime() -> None:
    manifest = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    runtime = manifest["pythonRuntime"]

    assert runtime == {
        "executable": "python.exe",
        "versionRegex": r"^Python 3\.12\.\d+$",
        "authenticode": {
            "required": True,
            "publishers": [
                "CN=Python Software Foundation, O=Python Software Foundation, L=Beaverton, S=Oregon, C=US"
            ],
        },
    }
    assert not WINDOWS_ABSOLUTE.match(runtime["executable"])
    assert not PureWindowsPath(runtime["executable"]).is_absolute()
    assert ".." not in PureWindowsPath(runtime["executable"]).parts
    for value in iter_values(runtime):
        if isinstance(value, str):
            assert "admin" not in value.casefold()
            assert not WINDOWS_ABSOLUTE.match(value)
            assert not PureWindowsPath(value).is_absolute()


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("missing", "missing: pythonruntime"),
        ("keys", "invalid keys for python runtime"),
        ("executable", "python runtime executable must be a safe filename"),
        ("regex", "invalid python runtime versionregex"),
        ("authenticode", "invalid keys for python runtime authenticode"),
        ("auth_required", "invalid python runtime authenticode requirement"),
        ("auth_publishers", "missing python runtime authenticode publisher"),
    ],
)
def test_common_script_rejects_invalid_python_runtime_policy(
    tmp_path: Path, case: str, expected: str
) -> None:
    manifest = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    runtime = manifest["pythonRuntime"]
    if case == "missing":
        del manifest["pythonRuntime"]
    elif case == "keys":
        runtime["unexpected"] = True
    elif case == "executable":
        runtime["executable"] = "Scripts/python.exe"
    elif case == "regex":
        runtime["versionRegex"] = "(unclosed"
    elif case == "authenticode":
        runtime["authenticode"]["unexpected"] = True
    elif case == "auth_required":
        runtime["authenticode"]["required"] = "true"
    elif case == "auth_publishers":
        runtime["authenticode"]["publishers"] = []
    else:
        raise AssertionError(f"Unexpected test case: {case}")

    lock_path = tmp_path / f"invalid-python-runtime-{case}.lock.json"
    lock_path.write_text(json.dumps(manifest), encoding="utf-8")
    result = run_common_script(
        "Read-PetToolchainLock "
        f"-LockPath {powershell_literal(lock_path)} | Out-Null"
    )

    assert result.returncode != 0
    assert expected in (result.stdout + result.stderr).casefold()


def expected_tree_inventory(files: dict[str, bytes]) -> dict[str, object]:
    digest = hashlib.sha256()
    for relative_path in sorted(files):
        content = files[relative_path]
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(len(content)).encode("ascii"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(content).hexdigest().encode("ascii"))
        digest.update(b"\n")
    return {"fileCount": len(files), "treeSha256": digest.hexdigest()}


def test_common_script_reports_a_deterministic_regular_file_tree_inventory(
    tmp_path: Path,
) -> None:
    files = {
        "z-last.txt": b"last",
        "nested/a-first.bin": b"first",
        "nested/deeper/third.dat": b"third",
    }
    for relative_path, content in files.items():
        target = tmp_path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    result = run_common_script(
        "Get-DeterministicTreeInventory "
        f"-Root {powershell_literal(tmp_path)} | ConvertTo-Json -Compress"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == expected_tree_inventory(files)


def test_common_tree_inventory_rejects_a_reparse_point(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    command = (
        "New-Item -ItemType Junction "
        f"-Path {powershell_literal(root / 'linked')} -Target {powershell_literal(outside)} | Out-Null; "
        "$failure = $null; try { Get-DeterministicTreeInventory "
        f"-Root {powershell_literal(root)} | Out-Null }} catch {{ $failure = $_ }}; "
        "if ($null -eq $failure -or $failure.Exception.Message -notmatch 'reparse') { "
        "throw 'tree inventory accepted a reparse point' }; "
        "'tree-reparse-rejected'"
    )

    result = run_common_script(command)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "tree-reparse-rejected"


def test_common_checked_process_supports_an_explicit_environment() -> None:
    command = (
        "$hostPath = Join-Path $PSHOME 'pwsh.exe'; "
        "if (-not (Test-Path -LiteralPath $hostPath -PathType Leaf)) { "
        "$hostPath = Join-Path $PSHOME 'powershell.exe' }; "
        "$details = Invoke-CheckedProcess -FilePath $hostPath "
        "-ArgumentList @('-NoLogo', '-NoProfile', '-NonInteractive', '-Command', '$env:PET_TOOLCHAIN_ENV_TEST') "
        "-Environment @{ PET_TOOLCHAIN_ENV_TEST = 'isolated-value' }; "
        "if ($details.StdOut.Trim() -cne 'isolated-value') { throw 'checked process did not receive its environment' }; "
        "'checked-process-environment-passed'"
    )

    result = run_common_script(command)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "checked-process-environment-passed"


def test_common_clean_process_environment_blocks_python_and_pip_parent_injection(
    tmp_path: Path,
) -> None:
    attacker_site = tmp_path / "attacker-site"
    marker = tmp_path / "sitecustomize-ran.txt"
    outside = tmp_path / "outside-pip-target"
    attacker_config = tmp_path / "attacker-pip.ini"
    attacker_site.mkdir()
    attacker_config.write_text("[global]\ntarget = ignored\n", encoding="utf-8")
    (attacker_site / "sitecustomize.py").write_text(
        "import os\nfrom pathlib import Path\nPath(os.environ['PET_MARKER']).write_text('injected')\n",
        encoding="utf-8",
    )
    python_code = (
        "import json, os; "
        "print(json.dumps({name: os.environ.get(name) for name in "
        "('PYTHONPATH', 'PIP_TARGET', 'PIP_CONFIG_FILE', 'PATH', 'SystemRoot', 'TEMP')}))"
    )
    command = (
        f"$python = {powershell_literal(Path(sys.executable))}; "
        "$details = Invoke-CheckedProcess -FilePath $python "
        f"-ArgumentList @('-c', {powershell_literal(python_code)}) -CleanEnvironment "
        f"-Environment @{{ PET_MARKER = {powershell_literal(marker)} }}; "
        "$state = $details.StdOut | ConvertFrom-Json; "
        "if ($null -ne $state.PYTHONPATH -or $null -ne $state.PIP_TARGET -or $null -ne $state.PIP_CONFIG_FILE -or $null -ne $state.PATH) { "
        "throw 'clean process inherited Python or pip injection' }; "
        "if ([string]::IsNullOrWhiteSpace($state.SystemRoot) -or [string]::IsNullOrWhiteSpace($state.TEMP)) { "
        "throw 'clean process lost required Windows environment variables' }; "
        "$pip = Invoke-CheckedProcess -FilePath $python "
        "-ArgumentList @('-I', '-m', 'pip', '--isolated', 'config', 'debug') -CleanEnvironment "
        "-Environment @{ PIP_CONFIG_FILE = 'NUL'; PYTHONDONTWRITEBYTECODE = '1'; PYTHONNOUSERSITE = '1' }; "
        f"if ($pip.StdOut.Contains({powershell_literal(str(attacker_config))}) -or $pip.StdOut.Contains({powershell_literal(str(outside))})) {{ "
        "throw 'isolated pip read attacker configuration' }; "
        "'clean-python-environment-passed'"
    )

    result = run_common_script(
        command,
        environment={
            "PYTHONPATH": str(attacker_site),
            "PIP_TARGET": str(outside),
            "PIP_CONFIG_FILE": str(attacker_config),
        },
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "clean-python-environment-passed"
    assert not marker.exists()
    assert not outside.exists()


@pytest.mark.parametrize(
    ("stdout", "stderr"),
    [
        ("7-Zip (r) 26.02 (x86) : Igor Pavlov : Public domain : 2026-06-25\n", ""),
        ("\r\n7-Zip (r) 26.02 (x86) : Igor Pavlov : Public domain : 2026-06-25\r\n", ""),
        ("", "7-Zip (r) 26.02 (x86) : Igor Pavlov : Public domain : 2026-06-25\r"),
    ],
)
def test_common_version_match_normalizes_all_windows_newline_forms(
    stdout: str, stderr: str
) -> None:
    result = run_common_script(
        "$matched = Get-LockedVersionOutputMatch "
        "-StdOut " + powershell_literal(stdout) + " -StdErr " + powershell_literal(stderr) + " "
        "-VersionRegex '^7-Zip \\(r\\) 26\\.02 \\(x86\\) : Igor Pavlov : Public domain : 2026-06-25$' "
        "-FailureMessage 'locked version was not reported'; "
        "if ($matched -cne '7-Zip (r) 26.02 (x86) : Igor Pavlov : Public domain : 2026-06-25') { "
        "throw ('normalized match changed: ' + $matched) }; "
        "'normalized-version-match-passed'"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "normalized-version-match-passed"


def test_common_version_match_rejects_empty_and_nonmatching_output() -> None:
    result = run_common_script(
        "$emptyFailure = $null; try { Get-LockedVersionOutputMatch -StdOut $null -StdErr $null "
        "-VersionRegex '^Python 3\\.12\\.\\d+$' -FailureMessage 'empty locked version' | Out-Null } "
        "catch { $emptyFailure = $_ }; "
        "if ($null -eq $emptyFailure -or $emptyFailure.Exception.Message -cne 'empty locked version') { "
        "throw 'empty version output was accepted' }; "
        "$mismatchFailure = $null; try { Get-LockedVersionOutputMatch -StdOut 'Python 3.11.9' -StdErr '' "
        "-VersionRegex '^Python 3\\.12\\.\\d+$' -FailureMessage 'mismatched locked version' | Out-Null } "
        "catch { $mismatchFailure = $_ }; "
        "if ($null -eq $mismatchFailure -or $mismatchFailure.Exception.Message -cne 'mismatched locked version') { "
        "throw 'nonmatching version output was accepted' }; "
        "'empty-and-nonmatching-version-rejected'"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "empty-and-nonmatching-version-rejected"


def test_setup_accepts_locked_extractor_version_with_crlf_output() -> None:
    result = run_setup_script(
        ". "
        f"{powershell_literal(SETUP_SCRIPT)} "
        f"-QtPython {powershell_literal(Path(sys.executable))}; "
        "$lock = Read-PetToolchainLock "
        f"-LockPath {powershell_literal(LOCK_PATH)}; "
        "function Invoke-CheckedProcess { param($FilePath, [string[]]$ArgumentList, [int]$TimeoutSeconds) "
        "return [pscustomobject]@{ ExitCode = 0; "
        "StdOut = \"`r`n7-Zip (r) 26.02 (x86) : Igor Pavlov : Public domain : 2026-06-25`r`n\"; StdErr = '' } }; "
        "Assert-ExtractorVersion -ExtractorPath 'C:\\locked\\7zr.exe' -ExtractorLock $lock.extractor; "
        "'crlf-extractor-version-accepted'"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "crlf-extractor-version-accepted"


def test_setup_accepts_lone_cr_from_python_version_gates() -> None:
    python_root = Path(sys.executable).resolve().parent.parent
    result = run_setup_script(
        ". "
        f"{powershell_literal(SETUP_SCRIPT)} "
        f"-QtPython {powershell_literal(Path(sys.executable))}; "
        "$lock = Read-PetToolchainLock "
        f"-LockPath {powershell_literal(LOCK_PATH)}; "
        "function Invoke-CheckedProcess { param($FilePath, [string[]]$ArgumentList, [int]$TimeoutSeconds, [hashtable]$Environment, [switch]$CleanEnvironment) "
        "return [pscustomobject]@{ ExitCode = 0; StdOut = ''; StdErr = \"Python 3.12.10`r\" } }; "
        "Assert-TrustedBasePythonRuntime -LauncherPath 'C:\\trusted\\py.exe' -PythonRuntime $lock.pythonRuntime; "
        "$runtime = Assert-LockedPythonRuntime "
        f"-PythonRoot {powershell_literal(python_root)} -PythonRuntime $lock.pythonRuntime; "
        "if ($runtime.RuntimeVersion -cne 'Python 3.12.10') { throw 'candidate version was not trimmed' }; "
        "'lone-cr-python-version-accepted'"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "lone-cr-python-version-accepted"


def test_setup_runs_candidate_python_isolated_in_a_clean_environment() -> None:
    python_root = Path(sys.executable).resolve().parent.parent
    result = run_setup_script(
        ". "
        f"{powershell_literal(SETUP_SCRIPT)} "
        f"-QtPython {powershell_literal(Path(sys.executable))}; "
        "$lock = Read-PetToolchainLock "
        f"-LockPath {powershell_literal(LOCK_PATH)}; "
        "function Invoke-CheckedProcess { param($FilePath, [string[]]$ArgumentList, [int]$TimeoutSeconds, [hashtable]$Environment, [switch]$CleanEnvironment) "
        "if (-not $CleanEnvironment) { throw 'candidate Python did not use clean process environment' }; "
        "if (@($ArgumentList | Where-Object { $_ -ceq '-I' }).Count -ne 1 -or $ArgumentList[-1] -cne '--version') { "
        "throw 'candidate Python did not use isolated version probe' }; "
        "if ($Environment.PYTHONDONTWRITEBYTECODE -cne '1' -or $Environment.PYTHONNOUSERSITE -cne '1') { "
        "throw 'candidate Python environment was not hardened' }; "
        "return [pscustomobject]@{ ExitCode = 0; StdOut = 'Python 3.12.10'; StdErr = '' } }; "
        "$runtime = Assert-LockedPythonRuntime "
        f"-PythonRoot {powershell_literal(python_root)} -PythonRuntime $lock.pythonRuntime; "
        "if ($runtime.RuntimeVersion -cne 'Python 3.12.10') { throw 'candidate Python result changed' }; "
        "'candidate-python-clean-and-isolated'"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "candidate-python-clean-and-isolated"


def test_setup_uses_a_signed_absolute_python_launcher_despite_attacker_path(
    tmp_path: Path,
) -> None:
    attacker = tmp_path / "attacker-bin"
    attacker.mkdir()
    fake_launcher = attacker / "py.exe"
    fake_launcher.write_bytes(b"not-a-signed-python-launcher")
    result = run_setup_script(
        ". "
        f"{powershell_literal(SETUP_SCRIPT)} "
        f"-QtPython {powershell_literal(Path(sys.executable))}; "
        "$lock = Read-PetToolchainLock "
        f"-LockPath {powershell_literal(LOCK_PATH)}; "
        f"$env:PATH = {powershell_literal(str(attacker))} + ';' + $env:PATH; "
        "$pathCandidates = @(Get-Command -Name 'py.exe' -CommandType Application -All); "
        f"if (@($pathCandidates | Where-Object {{ $_.Source -ieq {powershell_literal(fake_launcher)} }}).Count -ne 1) {{ "
        "throw 'attacker launcher was not discoverable through PATH' }; "
        "$launcher = Resolve-TrustedPythonLauncher -PythonRuntime $lock.pythonRuntime; "
        "if (-not [System.IO.Path]::IsPathRooted($launcher)) { throw 'Python launcher was not made absolute' }; "
        f"if ($launcher -ieq {powershell_literal(fake_launcher)}) {{ throw 'attacker py.exe won PATH resolution' }}; "
        "$item = Get-Item -LiteralPath $launcher -Force; "
        "if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'launcher reparse point was accepted' }; "
        "'trusted-absolute-python-launcher'"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "trusted-absolute-python-launcher"


def test_setup_pip_harness_uses_clean_isolated_no_target_installation(
    tmp_path: Path,
) -> None:
    staging_root = tmp_path / "staging"
    python_root = staging_root / "python"
    candidate = python_root / "Scripts" / "python.exe"
    candidate.parent.mkdir(parents=True)
    shutil.copy2(Path(sys.executable).resolve(), candidate)
    wheel_cache = tmp_path / "wheel-cache"
    wheel_cache.mkdir()
    outside = tmp_path / "outside-target"
    attacker_config = tmp_path / "attacker-pip.ini"
    attacker_config.write_text("[global]\ntarget = ignored\n", encoding="utf-8")
    result = run_setup_script(
        ". "
        f"{powershell_literal(SETUP_SCRIPT)} "
        f"-QtPython {powershell_literal(Path(sys.executable))}; "
        "$lock = Read-PetToolchainLock "
        f"-LockPath {powershell_literal(LOCK_PATH)}; "
        f"$env:PIP_TARGET = {powershell_literal(outside)}; "
        f"$env:PIP_CONFIG_FILE = {powershell_literal(attacker_config)}; "
        "$script:seen = @(); "
        "function Invoke-CheckedProcess { param($FilePath, [string[]]$ArgumentList, [int]$TimeoutSeconds, [hashtable]$Environment, [switch]$CleanEnvironment) "
        "if (-not $CleanEnvironment) { throw 'Python stage inherited its parent environment' }; "
        "$script:seen += [pscustomobject]@{ FilePath = $FilePath; Arguments = @($ArgumentList); Environment = $Environment }; "
        "if ($ArgumentList -contains 'install') { "
        "foreach ($required in @('-I', '-m', 'pip', '--isolated', '--require-hashes', '--only-binary=:all:', '--no-cache-dir', '--no-compile', '--disable-pip-version-check', '--no-input')) { "
        "if ($ArgumentList -notcontains $required) { throw ('missing isolated pip argument: ' + $required) } }; "
        "if ($ArgumentList -notcontains '--no-index' -or $ArgumentList -notcontains '--find-links') { throw 'nonempty wheel cache did not use the offline pip branch' }; "
        "if ($Environment.ContainsKey('PIP_TARGET') -or $Environment.PIP_CONFIG_FILE -cne 'NUL') { throw 'attacker pip environment survived' }; "
        "return [pscustomobject]@{ ExitCode = 0; StdOut = ''; StdErr = '' } }; "
        "if ($ArgumentList -contains 'freeze') { "
        "if ($ArgumentList -notcontains '-I' -or $ArgumentList -notcontains '--isolated') { throw 'freeze was not isolated' }; "
        "return [pscustomobject]@{ ExitCode = 0; StdOut = 'example==1'; StdErr = '' } }; "
        "return [pscustomobject]@{ ExitCode = 0; StdOut = 'Python 3.12.10'; StdErr = '' } }; "
        "$installed = Install-LockedPython "
        f"-StagingRoot {powershell_literal(staging_root)} -RequirementsPath {powershell_literal(MEDIA_LOCK)} "
        f"-WheelCache {powershell_literal(wheel_cache)} -PythonRuntime $lock.pythonRuntime; "
        "if ($installed.Freeze.Count -ne 1 -or $installed.Freeze[0] -cne 'example==1') { throw 'pip freeze result changed' }; "
        "if (@($script:seen | Where-Object { -not [System.IO.Path]::IsPathRooted($_.FilePath) }).Count -ne 0) { throw 'Python executable was not absolute' }; "
        "'isolated-pip-harness-passed'"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "isolated-pip-harness-passed"
    assert not outside.exists()


@pytest.mark.parametrize(
    ("wheel_cache_argument", "case"),
    [("", "omitted"), ("-WheelCache ''", "empty")],
)
def test_setup_python_install_accepts_empty_wheel_cache_for_online_branch(
    tmp_path: Path, wheel_cache_argument: str, case: str
) -> None:
    staging_root = tmp_path / "staging"
    candidate = staging_root / "python" / "Scripts" / "python.exe"
    candidate.parent.mkdir(parents=True)
    shutil.copy2(Path(sys.executable).resolve(), candidate)
    install_call = (
        "Install-LockedPython "
        f"-StagingRoot {powershell_literal(staging_root)} "
        f"-RequirementsPath {powershell_literal(MEDIA_LOCK)} "
        f"{wheel_cache_argument} -PythonRuntime $lock.pythonRuntime"
    )
    result = run_setup_script(
        ". "
        f"{powershell_literal(SETUP_SCRIPT)} "
        f"-QtPython {powershell_literal(Path(sys.executable))}; "
        "$lock = Read-PetToolchainLock "
        f"-LockPath {powershell_literal(LOCK_PATH)}; "
        "$script:onlineInstallCount = 0; "
        "function Invoke-CheckedProcess { param($FilePath, [string[]]$ArgumentList, [int]$TimeoutSeconds, [hashtable]$Environment, [switch]$CleanEnvironment) "
        "if (-not $CleanEnvironment) { throw 'Python stage did not use clean environment' }; "
        "if ($ArgumentList -contains 'install') { "
        "$script:onlineInstallCount++; "
        "foreach ($required in @('-I', '-m', 'pip', '--isolated', '--require-hashes', '--only-binary=:all:', '--no-cache-dir', '--no-compile', '--disable-pip-version-check', '--no-input', '-r')) { "
        "if ($ArgumentList -notcontains $required) { throw ('missing online pip argument: ' + $required) } }; "
        "if ($ArgumentList -contains '--no-index' -or $ArgumentList -contains '--find-links') { throw 'empty wheel cache selected offline pip branch' }; "
        "return [pscustomobject]@{ ExitCode = 0; StdOut = ''; StdErr = '' } }; "
        "if ($ArgumentList -contains 'freeze') { return [pscustomobject]@{ ExitCode = 0; StdOut = 'example==1'; StdErr = '' } }; "
        "return [pscustomobject]@{ ExitCode = 0; StdOut = 'Python 3.12.10'; StdErr = '' } }; "
        "$installed = "
        + install_call
        + "; if ($script:onlineInstallCount -ne 1 -or $installed.Freeze[0] -cne 'example==1') { throw 'online Python installation did not complete through the intended branch' }; "
        f"'empty-wheel-cache-{case}-accepted'"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == f"empty-wheel-cache-{case}-accepted"


def test_setup_wheel_cache_interfaces_share_an_empty_default() -> None:
    source = SETUP_SCRIPT.read_text(encoding="utf-8")
    function_start = source.index("function Install-LockedPython")
    function_end = source.index("\nfunction ", function_start + 1)
    internal_signature = source[function_start:function_end]

    assert re.search(r"\[string\]\$WheelCache\s*=\s*''", source)
    assert "[AllowEmptyString()][string]$WheelCache = ''" in internal_signature
    assert "[Parameter(Mandatory)][string]$WheelCache" not in internal_signature


@pytest.mark.parametrize("signature_case", ["unsigned", "replaced"])
def test_setup_rejects_untrusted_candidate_python_before_execution(
    tmp_path: Path, signature_case: str
) -> None:
    python_root = tmp_path / "python"
    candidate = python_root / "Scripts" / "python.exe"
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(b"not-a-python-runtime")
    status = "NotSigned" if signature_case == "unsigned" else "Valid"
    subject = (
        ""
        if signature_case == "unsigned"
        else "CN=Unexpected Publisher, O=Unexpected Publisher, C=US"
    )
    command = (
        ". "
        f"{powershell_literal(SETUP_SCRIPT)} "
        f"-QtPython {powershell_literal(Path(sys.executable))}; "
        "$runtime = [pscustomobject]@{ executable = 'python.exe'; "
        "versionRegex = '^Python 3\\.12\\.\\d+$'; "
        "authenticode = [pscustomobject]@{ required = $true; publishers = @("
        "'CN=Python Software Foundation, O=Python Software Foundation, L=Beaverton, S=Oregon, C=US') } }; "
        f"$script:signatureStatus = '{status}'; $script:signatureSubject = '{subject}'; "
        "$script:processExecuted = $false; "
        "function Get-AuthenticodeSignature { param($FilePath) "
        "$certificate = if ([string]::IsNullOrWhiteSpace($script:signatureSubject)) { $null } "
        "else { [pscustomobject]@{ Subject = $script:signatureSubject } }; "
        "return [pscustomobject]@{ Status = $script:signatureStatus; SignerCertificate = $certificate } }; "
        "function Invoke-CheckedProcess { $script:processExecuted = $true; throw 'candidate process executed' }; "
        "$failure = $null; try { Assert-LockedPythonRuntime "
        f"-PythonRoot {powershell_literal(python_root)} -PythonRuntime $runtime | Out-Null }} catch {{ $failure = $_ }}; "
        "if ($null -eq $failure -or $failure.Exception.Message -notmatch 'Authenticode|publisher') { "
        "throw 'untrusted Python runtime was not rejected at the signature boundary' }; "
        "if ($script:processExecuted) { throw 'untrusted candidate Python executed' }; "
        "'untrusted-python-stopped-before-execution'"
    )

    result = run_setup_script(command)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "untrusted-python-stopped-before-execution"


def test_setup_accepts_the_signed_worktree_python_runtime_read_only() -> None:
    python_root = Path(sys.executable).resolve().parent.parent
    result = run_setup_script(
        ". "
        f"{powershell_literal(SETUP_SCRIPT)} "
        f"-QtPython {powershell_literal(Path(sys.executable))}; "
        "$lock = Read-PetToolchainLock "
        f"-LockPath {powershell_literal(LOCK_PATH)}; "
        "$runtime = Assert-LockedPythonRuntime "
        f"-PythonRoot {powershell_literal(python_root)} -PythonRuntime $lock.pythonRuntime; "
        "if ($runtime.RuntimePublisher -notmatch 'Python Software Foundation') { throw 'signed runtime publisher was not retained' }; "
        "if ($runtime.RuntimeVersion -notmatch '^Python 3\\.12\\.') { throw 'signed runtime version was not retained' }; "
        "'signed-python-runtime-accepted'"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "signed-python-runtime-accepted"


def test_setup_removes_seeded_python_bytecode_with_only_contained_nonrecursive_deletes(
    tmp_path: Path,
) -> None:
    python_root = tmp_path / "python"
    bytecode = python_root / "Lib" / "site-packages" / "__pycache__" / "seed.pyc"
    empty_cache = python_root / "Lib" / "empty" / "__pycache__"
    retained_cache = python_root / "Lib" / "retained" / "__pycache__"
    bytecode.parent.mkdir(parents=True)
    empty_cache.mkdir(parents=True)
    retained_cache.mkdir(parents=True)
    bytecode.write_bytes(b"seed-bytecode")
    (retained_cache / "keep.txt").write_bytes(b"not-bytecode")
    command = (
        ". "
        f"{powershell_literal(SETUP_SCRIPT)} "
        f"-QtPython {powershell_literal(Path(sys.executable))}; "
        "$script:recursiveDeleteUsed = $false; "
        "function Remove-Item { $script:recursiveDeleteUsed = $true; throw 'recursive deletion is forbidden' }; "
        "Remove-PythonBytecodeArtifacts "
        f"-PythonRoot {powershell_literal(python_root)}; "
        f"if (Test-Path -LiteralPath {powershell_literal(bytecode)}) {{ throw 'seeded pyc remained' }}; "
        f"if (Test-Path -LiteralPath {powershell_literal(empty_cache)}) {{ throw 'empty cache remained' }}; "
        f"if (-not (Test-Path -LiteralPath {powershell_literal(retained_cache / 'keep.txt')})) {{ throw 'nonempty cache was removed' }}; "
        "if ($script:recursiveDeleteUsed) { throw 'cleanup used Remove-Item' }; "
        "'python-bytecode-cleanup-passed'"
    )

    result = run_setup_script(command)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "python-bytecode-cleanup-passed"


def canonical_installed_files_sha256(installed_files: dict[str, object]) -> str:
    payload = json.dumps(
        installed_files,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def test_pet_toolchain_lock_has_complete_installed_file_inventories() -> None:
    manifest = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    expected_counts = {
        "ffmpeg": 45,
        "imagemagick": 23,
        "libwebp": 26,
    }
    expected_inventory_digests = {
        "ffmpeg": "d93a17adef4d9e7311c65d87035338259db0cc0301448e02264eaefb01cbd262",
        "imagemagick": "ba50cc8d4518892351a3f1cda9fe5db2c8e5c09be4def7c0236ff6a212c12074",
        "libwebp": "daf4d6dee7e40ed80e8c0507317e570cb9bc07455b9f39ac415a1641c7e28ee1",
    }
    expected_critical_files = {
        "ffmpeg": {
            "bin/ffmpeg.exe": {
                "size": 102856192,
                "sha256": "72a489eccd008c2ec2c0a5856c5c75bc3d8bbfa90166c4566865c246445e6aa3",
            },
            "bin/ffprobe.exe": {
                "size": 102652416,
                "sha256": "19202b23c0043f15ad1b7bce2344f406fd52bd6efd8f995ce02e7392a1cec52f",
            },
        },
        "imagemagick": {
            "magick.exe": {
                "size": 31153328,
                "sha256": "7e93f2c502c888569e2cf27e049e39d204a8bbd36a958419af7fce5450776f41",
            },
            "policy.xml": {
                "size": 8836,
                "sha256": "caa8dab971a9eafc2a592d5803595827dec0b99d8bf34c1e9b1c993fe69d7048",
            },
        },
        "libwebp": {
            "bin/cwebp.exe": {
                "size": 753664,
                "sha256": "6a2f5cb5dce71366353ab1d9caf9c636e039f25703acfce1c148eed346f2f72a",
            },
            "bin/freeglut.dll": {
                "size": 229376,
                "sha256": "cf62555f14d64fac1d650e1a24c86465b70ca410c3d6942fce2e6f25672490c7",
            },
        },
    }

    for tool_name in ("ffmpeg", "imagemagick", "libwebp"):
        tool = manifest["tools"][tool_name]
        installed_files = tool["installedFiles"]

        assert installed_files
        assert len(installed_files) == expected_counts[tool_name]
        assert (
            canonical_installed_files_sha256(installed_files)
            == expected_inventory_digests[tool_name]
        )
        assert len(installed_files) == len(
            {path.casefold() for path in installed_files}
        )
        for relative_path, record in installed_files.items():
            assert "\\" not in relative_path
            assert not relative_path.startswith("/")
            assert not PureWindowsPath(relative_path).drive
            assert all(part not in {"", ".", ".."} for part in relative_path.split("/"))
            assert set(record) == {"size", "sha256"}
            assert record["size"] > 0
            assert SHA256.fullmatch(record["sha256"])

        assert tool["entrypoint"] in installed_files
        if "probeEntrypoint" in tool:
            assert tool["probeEntrypoint"] in installed_files
        assert {
            path: installed_files[path]
            for path in expected_critical_files[tool_name]
        } == expected_critical_files[tool_name]


def test_media_requirements_are_directly_pinned_and_fully_hashed() -> None:
    direct = MEDIA_INPUT.read_text(encoding="utf-8").splitlines()
    assert direct == [
        "rembg==2.0.77",
        "onnxruntime==1.27.0",
        "Pillow==12.3.0",
        "numpy==2.4.6",
        "opencv-python-headless==4.13.0.92",
    ]

    locked = MEDIA_LOCK.read_text(encoding="utf-8")
    for requirement in direct:
        assert requirement.casefold() in locked.casefold()
    assert "--hash=sha256:" in locked
    assert "--only-binary" not in locked

    blocks = pinned_requirement_blocks(locked)
    assert blocks
    for block in blocks:
        requirement = block[0].rstrip(" \\")
        assert any(SHA256_HASH_OPTION.fullmatch(line) for line in block), (
            f"Missing SHA-256 hash for requirement block {requirement!r}"
        )


def test_media_requirements_reject_an_unhashed_transitive_block(monkeypatch) -> None:
    incomplete_lock = """\
rembg==2.0.77 \\
    --hash=sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
onnxruntime==1.27.0 \\
    --hash=sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
Pillow==12.3.0 \\
    --hash=sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
numpy==2.4.6 \\
    --hash=sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
opencv-python-headless==4.13.0.92 \\
    --hash=sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
transitive-package==1.2.3
    # via rembg
"""
    original_read_text = Path.read_text

    def fake_read_text(path: Path, *args: object, **kwargs: object) -> str:
        if path == MEDIA_LOCK:
            return incomplete_lock
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fake_read_text)

    with pytest.raises(
        AssertionError,
        match=r"Missing SHA-256 hash for requirement block 'transitive-package==1\.2\.3'",
    ):
        test_media_requirements_are_directly_pinned_and_fully_hashed()


def test_setup_scripts_have_no_machine_wide_mutation_or_archive_fallback() -> None:
    common_source = COMMON_SCRIPT.read_text(encoding="utf-8").casefold()
    setup_source = SETUP_SCRIPT.read_text(encoding="utf-8").casefold()
    source = common_source + "\n" + setup_source

    forbidden = (
        "setenvironmentvariable",
        "setx ",
        "new-itemproperty",
        "set-itemproperty",
        "program files",
        "\\.venv",
        "tar.exe",
        "7z.exe",
    )
    assert all(token not in source for token in forbidden)
    assert "open-verifiedasset -asset $lock.extractor" in setup_source


@pytest.mark.parametrize("relative_path", ["..\\escape", "C:\\escape", "\\escape"])
def test_common_script_rejects_paths_outside_the_containing_root(
    tmp_path: Path, relative_path: str
) -> None:
    result = run_common_script(
        "Resolve-ContainedPath "
        f"-Root {powershell_literal(tmp_path)} "
        f"-RelativePath {powershell_literal(relative_path)}"
    )

    assert result.returncode != 0
    assert "escapes tool root" in (result.stdout + result.stderr).casefold()


def test_common_script_rejects_zip_path_escape_before_extraction(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "path-escape.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../outside.txt", "not extracted")

    result = run_common_script(
        "Assert-SafeArchiveEntries "
        f"-ArchivePath {powershell_literal(archive_path)} -ArchiveType Zip"
    )

    assert result.returncode != 0
    assert "unsafe archive path" in (result.stdout + result.stderr).casefold()
    assert not (tmp_path.parent / "outside.txt").exists()


def test_common_script_rejects_zip_alternate_data_stream_name(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "alternate-data-stream.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("safe.txt:metadata", "not extracted")

    result = run_common_script(
        "Assert-SafeArchiveEntries "
        f"-ArchivePath {powershell_literal(archive_path)} -ArchiveType Zip"
    )

    assert result.returncode != 0
    assert "unsafe archive path" in (result.stdout + result.stderr).casefold()


def test_common_script_rejects_zip_windows_device_name(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "device-name.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("CON", "not extracted")

    result = run_common_script(
        "Assert-SafeArchiveEntries "
        f"-ArchivePath {powershell_literal(archive_path)} -ArchiveType Zip"
    )

    assert result.returncode != 0
    assert "unsafe archive path" in (result.stdout + result.stderr).casefold()


def test_common_script_rejects_symbolic_link_zip_entry_before_extraction(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "symlink.zip"
    link_entry = zipfile.ZipInfo("link")
    link_entry.create_system = 3
    link_entry.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(link_entry, "target")

    result = run_common_script(
        "Assert-SafeArchiveEntries "
        f"-ArchivePath {powershell_literal(archive_path)} -ArchiveType Zip"
    )

    assert result.returncode != 0
    assert "unsafe archive link metadata" in (result.stdout + result.stderr).casefold()


def test_common_script_requires_the_locked_extractor_record(tmp_path: Path) -> None:
    manifest = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    del manifest["extractor"]
    lock_path = tmp_path / "missing-extractor.lock.json"
    lock_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = run_common_script(
        "Read-PetToolchainLock "
        f"-LockPath {powershell_literal(lock_path)} | Out-Null"
    )

    assert result.returncode != 0
    assert "extractor" in (result.stdout + result.stderr).casefold()


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("missing", "missing: installedfiles"),
        ("empty", "installed file inventory must not be empty"),
        ("backslash", "must use forward slashes"),
        ("entrypoint", "entrypoint must be listed in installedfiles"),
        ("probe_entrypoint", "probe entrypoint must be listed in installedfiles"),
        ("record_keys", "invalid keys for installed file"),
        ("record_size", "invalid installed file size"),
    ],
)
def test_common_script_rejects_invalid_tool_installed_file_inventory(
    tmp_path: Path, case: str, expected: str
) -> None:
    manifest = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    tool = manifest["tools"]["ffmpeg"]
    installed_files = tool["installedFiles"]

    if case == "missing":
        del tool["installedFiles"]
    elif case == "empty":
        tool["installedFiles"] = {}
    elif case == "backslash":
        record = installed_files.pop("bin/ffmpeg.exe")
        installed_files["bin\\ffmpeg.exe"] = record
    elif case == "entrypoint":
        del installed_files[tool["entrypoint"]]
    elif case == "probe_entrypoint":
        del installed_files[tool["probeEntrypoint"]]
    elif case == "record_keys":
        installed_files["bin/ffmpeg.exe"]["unexpected"] = True
    elif case == "record_size":
        installed_files["bin/ffmpeg.exe"]["size"] = 0
    else:
        raise AssertionError(f"Unexpected test case: {case}")

    lock_path = tmp_path / f"invalid-installed-files-{case}.lock.json"
    lock_path.write_text(json.dumps(manifest), encoding="utf-8")
    result = run_common_script(
        "Read-PetToolchainLock "
        f"-LockPath {powershell_literal(lock_path)} | Out-Null"
    )

    assert result.returncode != 0
    assert expected in (result.stdout + result.stderr).casefold()


def test_common_script_derives_content_addressed_cache_path_for_locked_extractor(
    tmp_path: Path,
) -> None:
    manifest = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    expected = tmp_path / f"{manifest['extractor']['sha256']}-7zr.exe"
    result = run_common_script(
        "$lock = Read-PetToolchainLock "
        f"-LockPath {powershell_literal(LOCK_PATH)}; "
        "Get-PetToolchainCachePath "
        f"-DownloadsRoot {powershell_literal(tmp_path)} -Asset $lock.extractor"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip().casefold() == str(expected).casefold()


def test_setup_accepts_immutable_real_cached_locked_extractor() -> None:
    manifest = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    extractor = manifest["extractor"]
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        pytest.skip("portable environment lacks LOCALAPPDATA for cached extractor fixture")

    url_basename = PurePosixPath(urlparse(extractor["url"]).path).name
    assert url_basename
    default_tool_root = Path(local_app_data) / "DesktopCompanionDev" / "pet-toolchain"
    cache_path = (
        default_tool_root
        / "downloads"
        / f"{extractor['sha256']}-{url_basename}"
    )
    if not cache_path.exists():
        pytest.skip("portable environment lacks the exact locked cached extractor fixture")

    reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    def assert_cache_path_is_regular_and_reparse_free() -> None:
        current = cache_path
        while True:
            entry = current.lstat()
            assert not (getattr(entry, "st_file_attributes", 0) & reparse_point), (
                f"cached extractor path contains reparse point: {current}"
            )
            if current == cache_path:
                assert stat.S_ISREG(entry.st_mode), "cached extractor is not a regular file"
            else:
                assert stat.S_ISDIR(entry.st_mode), (
                    f"cached extractor ancestor is not a directory: {current}"
                )
            if current.parent == current:
                break
            current = current.parent

    assert_cache_path_is_regular_and_reparse_free()

    before = cache_path.stat()
    before_hash = hashlib.sha256(cache_path.read_bytes()).hexdigest()
    assert before.st_size == extractor["size"]
    assert before_hash == extractor["sha256"]

    result = run_setup_script(
        ". "
        f"{powershell_literal(SETUP_SCRIPT)} "
        f"-QtPython {powershell_literal(Path(sys.executable))}; "
        "$lock = Read-PetToolchainLock "
        f"-LockPath {powershell_literal(LOCK_PATH)}; "
        f"Assert-ExtractorVersion -ExtractorPath {powershell_literal(cache_path)} "
        "-ExtractorLock $lock.extractor; "
        "'real-cached-extractor-accepted'"
    )

    assert_cache_path_is_regular_and_reparse_free()
    after = cache_path.stat()
    after_hash = hashlib.sha256(cache_path.read_bytes()).hexdigest()
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "real-cached-extractor-accepted"
    assert after.st_size == before.st_size == extractor["size"]
    assert after_hash == before_hash == extractor["sha256"]
    assert after.st_mtime_ns == before.st_mtime_ns


@pytest.mark.parametrize("tamper", ["missing", "extra", "changed", "dll_replaced"])
def test_setup_rejects_tampered_flattened_tool_inventory_before_process_execution(
    tmp_path: Path, tamper: str
) -> None:
    tool_root = tmp_path / "tool"
    bin_root = tool_root / "bin"
    bin_root.mkdir(parents=True)
    expected_executable = b"tool"
    expected_dll = b"dll!"
    (bin_root / "tool.exe").write_bytes(
        b"toOl" if tamper == "changed" else expected_executable
    )
    if tamper != "missing":
        (bin_root / "library.dll").write_bytes(
            b"dLl!" if tamper == "dll_replaced" else expected_dll
        )
    if tamper == "extra":
        (tool_root / "unlocked.txt").write_bytes(b"extra")

    executable_sha = hashlib.sha256(expected_executable).hexdigest()
    dll_sha = hashlib.sha256(expected_dll).hexdigest()
    command = (
        ". "
        f"{powershell_literal(SETUP_SCRIPT)} "
        f"-QtPython {powershell_literal(Path(sys.executable))}; "
        "$script:processExecuted = $false; "
        "function Invoke-CheckedProcess { $script:processExecuted = $true; "
        "throw 'unexpected external process' }; "
        "$tool = [pscustomobject]@{ installedFiles = [pscustomobject]@{ "
        f"'bin/tool.exe' = [pscustomobject]@{{ size = 4; sha256 = '{executable_sha}' }}; "
        f"'bin/library.dll' = [pscustomobject]@{{ size = 4; sha256 = '{dll_sha}' }} "
        "} }; "
        "$failure = $null; try { Assert-InstalledToolInventory "
        f"-ToolRoot {powershell_literal(tool_root)} -ToolKey 'test-tool' -ToolLock $tool }} "
        "catch { $failure = $_ }; "
        "if ($null -eq $failure -or $failure.Exception.Message -notmatch 'Tool inventory') { "
        "throw 'tampered inventory was accepted or failed at the wrong boundary' }; "
        "if ($script:processExecuted) { throw 'inventory check executed a process' }; "
        "'tampered-inventory-rejected'"
    )

    result = run_setup_script(command)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "tampered-inventory-rejected"


def test_setup_rejects_tampered_dll_before_authenticode_or_tool_execution(
    tmp_path: Path,
) -> None:
    staging_root = tmp_path / "staging"
    raw_root = staging_root / "extract-test-tool" / "portable"
    raw_bin = raw_root / "bin"
    raw_bin.mkdir(parents=True)
    expected_executable = b"tool"
    expected_dll = b"dll!"
    (raw_bin / "tool.exe").write_bytes(expected_executable)
    (raw_bin / "library.dll").write_bytes(b"dLl!")
    executable_sha = hashlib.sha256(expected_executable).hexdigest()
    dll_sha = hashlib.sha256(expected_dll).hexdigest()
    command = (
        ". "
        f"{powershell_literal(SETUP_SCRIPT)} "
        f"-QtPython {powershell_literal(Path(sys.executable))}; "
        "$script:authenticodeReached = $false; "
        "function Assert-AuthenticodeAsset { $script:authenticodeReached = $true; "
        "throw 'tool trust check was reached' }; "
        "$tool = [pscustomobject]@{ entrypoint = 'bin/tool.exe'; "
        "authenticode = [pscustomobject]@{ required = $false; publishers = @() }; "
        "installedFiles = [pscustomobject]@{ "
        f"'bin/tool.exe' = [pscustomobject]@{{ size = 4; sha256 = '{executable_sha}' }}; "
        f"'bin/library.dll' = [pscustomobject]@{{ size = 4; sha256 = '{dll_sha}' }} "
        "} }; "
        "$failure = $null; try { Move-FlattenedTool "
        f"-StagingRoot {powershell_literal(staging_root)} "
        f"-RawRoot {powershell_literal(staging_root / 'extract-test-tool')} "
        "-ToolKey 'test-tool' -ToolLock $tool | Out-Null } catch { $failure = $_ }; "
        "if ($null -eq $failure -or $failure.Exception.Message -notmatch 'Tool inventory') { "
        "throw 'tampered DLL was accepted or failed after the inventory boundary' }; "
        "if ($script:authenticodeReached) { throw 'tool trust check ran after tampered DLL' }; "
        "'tampered-dll-stopped-before-execution'"
    )

    result = run_setup_script(command)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "tampered-dll-stopped-before-execution"


def test_setup_refuses_to_publish_or_create_a_tool_root_without_verifier(
    tmp_path: Path,
) -> None:
    tool_root = tmp_path / "tool-root"
    unavailable_verifier = tmp_path / "missing-verifier.ps1"
    result = run_setup_script(
        ". "
        f"{powershell_literal(SETUP_SCRIPT)} "
        f"-QtPython {powershell_literal(Path(sys.executable))}; "
        "function Invoke-WebRequest { throw 'network sentinel was called' }; "
        "Invoke-PetToolchainSetup "
        f"-ToolRoot {powershell_literal(tool_root)} "
        f"-LockPath {powershell_literal(LOCK_PATH)} "
        f"-RequirementsPath {powershell_literal(MEDIA_LOCK)} "
        f"-QtPython {powershell_literal(Path(sys.executable))} "
        f"-VerifierPath {powershell_literal(unavailable_verifier)}"
    )

    assert result.returncode != 0
    assert "verification script is unavailable" in (result.stdout + result.stderr).casefold()
    assert not tool_root.exists()


def test_setup_library_can_be_dot_sourced_without_running_the_installer() -> None:
    result = run_setup_script(
        ". "
        f"{powershell_literal(SETUP_SCRIPT)} "
        f"-QtPython {powershell_literal(Path(sys.executable))}; "
        "'setup-library-loaded'"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "setup-library-loaded"


def write_tiny_model_lock_fixture(tmp_path: Path) -> tuple[Path, dict[str, bytes]]:
    payloads = {
        "isnet-anime": b"tiny-isnet-anime-model\n",
        "u2net_human_seg": b"tiny-u2net-human-seg-model\n",
    }
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    lock["extractor"]["size"] = len(TINY_EXTRACTOR_PAYLOAD)
    lock["extractor"]["sha256"] = hashlib.sha256(TINY_EXTRACTOR_PAYLOAD).hexdigest()
    for model_key, payload in payloads.items():
        lock["models"][model_key]["size"] = len(payload)
        lock["models"][model_key]["sha256"] = hashlib.sha256(payload).hexdigest()

    lock_path = tmp_path / "tiny-models.lock.json"
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    return lock_path, payloads


def tiny_lock_download_stub(lock_path: Path, model_payloads: dict[str, bytes]) -> str:
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    payloads_by_asset = [(lock["extractor"], TINY_EXTRACTOR_PAYLOAD)] + [
        (lock["models"][model_key], model_payloads[model_key])
        for model_key in ("isnet-anime", "u2net_human_seg")
    ]
    cases = []
    for index, (asset, payload) in enumerate(payloads_by_asset):
        keyword = "if" if index == 0 else "elseif"
        encoded_payload = base64.b64encode(payload).decode("ascii")
        cases.append(
            f"{keyword} ($Uri -ceq {powershell_literal(asset['url'])}) {{ "
            f"[System.Convert]::FromBase64String('{encoded_payload}') }}"
        )

    return (
        "function Invoke-ExplicitHttpsDownload { param($Uri, $OutFile) "
        "$bytes = "
        + " ".join(cases)
        + " else { throw ('unexpected offline download: ' + $Uri) }; "
        "[System.IO.File]::WriteAllBytes($OutFile, $bytes) }; "
    )


def test_setup_copies_two_lock_valid_tiny_models_with_real_digest_gate(
    tmp_path: Path,
) -> None:
    lock_path, payloads = write_tiny_model_lock_fixture(tmp_path)
    staging_root = tmp_path / "staging"
    downloads_root = tmp_path / "downloads"

    result = run_setup_script(
        ". "
        f"{powershell_literal(SETUP_SCRIPT)} "
        f"-QtPython {powershell_literal(Path(sys.executable))}; "
        f"$stagingRoot = {powershell_literal(staging_root)}; "
        f"$downloadsRoot = {powershell_literal(downloads_root)}; "
        f"$lockPath = {powershell_literal(lock_path)}; "
        "[System.IO.Directory]::CreateDirectory($stagingRoot) | Out-Null; "
        "[System.IO.Directory]::CreateDirectory($downloadsRoot) | Out-Null; "
        "function Invoke-WebRequest { throw 'network sentinel was called' }; "
        f"{tiny_lock_download_stub(lock_path, payloads)}"
        "$lock = Read-PetToolchainLock -LockPath $lockPath; "
        "$entrypoints = Copy-LockedModels -StagingRoot $stagingRoot "
        "-DownloadsRoot $downloadsRoot -Models $lock.models; "
        "if (@($entrypoints.Keys).Count -ne 2) { throw 'model entrypoint count was wrong' }; "
        "if ($entrypoints['isnet-anime'] -cne 'models/isnet-anime.onnx') { "
        "throw 'isnet model entrypoint was wrong' }; "
        "if ($entrypoints['u2net_human_seg'] -cne 'models/u2net_human_seg.onnx') { "
        "throw 'u2net model entrypoint was wrong' }; "
        "'locked-model-copy-complete'"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "locked-model-copy-complete"
    expected_files = {
        "isnet-anime.onnx": payloads["isnet-anime"],
        "u2net_human_seg.onnx": payloads["u2net_human_seg"],
    }
    models_root = staging_root / "models"
    assert {
        path.relative_to(models_root).as_posix()
        for path in models_root.rglob("*")
        if path.is_file()
    } == set(expected_files)
    for file_name, payload in expected_files.items():
        copied = models_root / file_name
        assert copied.read_bytes() == payload
        assert copied.stat().st_size == len(payload)
        assert hashlib.sha256(copied.read_bytes()).hexdigest() == hashlib.sha256(
            payload
        ).hexdigest()


def test_setup_model_copy_does_not_reintroduce_ambiguous_getfilename_replace_call() -> None:
    source = SETUP_SCRIPT.read_text(encoding="utf-8")
    copy_function = source.split("function Copy-LockedModels {", 1)[1].split(
        "function Write-Utf8FileAndFlush {", 1
    )[0]
    ambiguous_call = re.compile(
        r"\[System\.IO\.Path\]::GetFileName\(\s*(?:\(\s*)*\[string\]"
        r"\s*\$modelLock\.entrypoint\s*(?:\)\s*)*-replace\s*[^,\r\n]+,"
    )

    assert re.search(
        r"\$normalisedEntrypoint\s*=\s*\(\s*\[string\]"
        r"\s*\$modelLock\.entrypoint\s*\)\s*-replace\b",
        copy_function,
    ) is not None
    assert re.search(
        r"\[System\.IO\.Path\]::GetFileName\(\s*\$normalisedEntrypoint\s*\)",
        copy_function,
    ) is not None
    for legacy_variant in (
        "[System.IO.Path]::GetFileName(([string]$modelLock.entrypoint) -replace '/', '\\\\')",
        '[System.IO.Path]::GetFileName( ( [string] $modelLock.entrypoint ) -replace "/", "\\\\" )',
    ):
        assert ambiguous_call.search(legacy_variant) is not None
    assert ambiguous_call.search(copy_function) is None


def offline_production_wiring_harness(
    *, tool_root: Path, lock_path: Path, model_payloads: dict[str, bytes]
) -> str:
    return (
        ". "
        f"{powershell_literal(SETUP_SCRIPT)} "
        f"-QtPython {powershell_literal(Path(sys.executable))}; "
        f"$root = {powershell_literal(tool_root)}; "
        f"$lockPath = {powershell_literal(lock_path)}; "
        f"$requirementsPath = {powershell_literal(MEDIA_LOCK)}; "
        "$script:expectedRoot = [System.IO.Path]::GetFullPath($root); "
        "$script:verificationCalls = @(); "
        "$qtPython = Join-Path (Split-Path -Parent $root) 'offline-qt-python.exe'; "
        "[System.IO.File]::WriteAllText($qtPython, 'offline Qt Python'); "
        "$verifier = Join-Path (Split-Path -Parent $root) 'offline-verifier.ps1'; "
        "[System.IO.File]::WriteAllText($verifier, ''); "
        "function Invoke-WebRequest { throw 'network sentinel was called' }; "
        f"{tiny_lock_download_stub(lock_path, model_payloads)}"
        "function Assert-ExtractorVersion { param($ExtractorPath, $ExtractorLock) }; "
        "function Install-LockedTool { param($StagingRoot, $DownloadsRoot, $ToolKey, $ToolLock, $ExtractorPath) "
        "$toolRoot = Join-Path $StagingRoot ('tools\\' + $ToolKey); "
        "[System.IO.Directory]::CreateDirectory($toolRoot) | Out-Null; "
        "$relative = if ($ToolKey -ceq 'imagemagick') { 'magick.exe' } "
        "elseif ($ToolKey -ceq 'ffmpeg') { 'bin\\ffmpeg.exe' } else { 'bin\\cwebp.exe' }; "
        "$entry = Join-Path $toolRoot $relative; "
        "[System.IO.Directory]::CreateDirectory((Split-Path -Parent $entry)) | Out-Null; "
        "[System.IO.File]::WriteAllText($entry, $ToolKey); return $entry }; "
        "function Install-LockedPython { param($StagingRoot, $RequirementsPath, $WheelCache, $PythonRuntime) "
        "return [pscustomobject]@{ Interpreter = (Join-Path $StagingRoot 'python\\Scripts\\python.exe'); "
        "Freeze = @('example==1'); fileCount = 42; treeSha256 = ('a' * 64); "
        "RuntimeVersion = 'Python 3.12.10'; RuntimePublisher = 'CN=Python Software Foundation, "
        "O=Python Software Foundation, L=Beaverton, S=Oregon, C=US' } }; "
        "function Invoke-CheckedProcess { param( "
        "[Parameter(Mandatory)][string]$FilePath, [string[]]$ArgumentList = @(), "
        "[int]$TimeoutSeconds, [int[]]$ExpectedExitCode = @(0), [string]$WorkingDirectory = '', "
        "[hashtable]$Environment = @{}, [switch]$CleanEnvironment) "
        "if ($TimeoutSeconds -ne 1800) { throw 'verifier timeout was not preserved' }; "
        "if ($CleanEnvironment) { throw 'verifier unexpectedly requested a clean process environment' }; "
        "$fileIndex = [array]::IndexOf([string[]]$ArgumentList, '-File'); "
        "$toolRootIndex = [array]::IndexOf([string[]]$ArgumentList, '-ToolRoot'); "
        "$candidateIndex = [array]::IndexOf([string[]]$ArgumentList, '-CandidateRoot'); "
        "if ($fileIndex -lt 0 -or $toolRootIndex -lt 0 -or $candidateIndex -lt 0) { "
        "throw 'verification invocation omitted a required boundary argument' }; "
        "if ($ArgumentList[$fileIndex + 1] -cne $verifier) { throw 'wrong verifier path' }; "
        "if ($ArgumentList[$toolRootIndex + 1] -cne $script:expectedRoot) { "
        "throw 'verifier did not receive the canonical ToolRoot' }; "
        "if ($ArgumentList -notcontains '-NoCurrentPointer') { throw 'verifier read the current pointer' }; "
        "$script:verificationCalls += [pscustomobject]@{ "
        "ToolRoot = [string]$ArgumentList[$toolRootIndex + 1]; "
        "CandidateRoot = [string]$ArgumentList[$candidateIndex + 1] }; "
        "return [pscustomobject]@{ ExitCode = 0; StdOut = ''; StdErr = '' } }; "
        "$digest = Get-LockDigest -LockPath $lockPath -RequirementsPath $requirementsPath; "
        "$versionPath = Join-Path $root ('versions\\' + $digest); "
        "Invoke-PetToolchainSetup -ToolRoot $root -LockPath $lockPath "
        "-RequirementsPath $requirementsPath -QtPython $qtPython -VerifierPath $verifier; "
        "if (@($script:verificationCalls).Count -ne 2) { throw 'verifier was not called twice' }; "
        "$firstCandidate = [System.IO.Path]::GetFullPath([string]$script:verificationCalls[0].CandidateRoot); "
        "$secondCandidate = [System.IO.Path]::GetFullPath([string]$script:verificationCalls[1].CandidateRoot); "
        "if ((Split-Path -Parent $firstCandidate) -cne $script:expectedRoot -or "
        "[System.IO.Path]::GetFileName($firstCandidate) -notlike 'staging-*') { "
        "throw 'first verifier candidate was not the staging root' }; "
        "if ($secondCandidate -cne [System.IO.Path]::GetFullPath($versionPath)) { "
        "throw 'second verifier candidate was not the published version root' }; "
        "if (@($script:verificationCalls | Where-Object { $_.ToolRoot -cne $script:expectedRoot }).Count -ne 0) { "
        "throw 'verifier ToolRoot changed between boundaries' }; "
        "'offline-production-wiring-complete'"
    )


def test_setup_offline_production_wiring_copies_models_and_publishes_atomically(
    short_local_tmp_path: Path,
) -> None:
    lock_path, payloads = write_tiny_model_lock_fixture(short_local_tmp_path)
    tool_root = short_local_tmp_path / "offline-tool-root"

    result = run_setup_script(
        offline_production_wiring_harness(
            tool_root=tool_root, lock_path=lock_path, model_payloads=payloads
        )
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip().endswith("offline-production-wiring-complete")
    digest = hashlib.sha256(lock_path.read_bytes() + MEDIA_LOCK.read_bytes()).hexdigest()
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    expected_cache_files = {
        f"{asset['sha256']}-{PurePosixPath(urlparse(asset['url']).path).name}"
        for asset in (lock["extractor"], *lock["models"].values())
    }
    downloads_root = tool_root / "downloads"
    assert {
        path.name
        for path in downloads_root.iterdir()
        if path.is_file() and not path.name.endswith(".lock")
    } == expected_cache_files
    partial_download = re.compile(r"\.partial\.[0-9a-f]{32}$")
    assert not [
        path.relative_to(tool_root).as_posix()
        for path in tool_root.rglob("*")
        if partial_download.search(path.name)
    ]
    version_root = tool_root / "versions" / digest
    manifest = json.loads((version_root / "installed.json").read_text(encoding="utf-8"))
    expected_model_records = {
        model_key: {
            "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        for model_key, payload in payloads.items()
    }
    assert manifest["assets"]["models"] == expected_model_records
    assert manifest["entrypoints"]["models"] == {
        "isnet-anime": "models/isnet-anime.onnx",
        "u2net_human_seg": "models/u2net_human_seg.onnx",
    }
    expected_files = {
        "isnet-anime.onnx": payloads["isnet-anime"],
        "u2net_human_seg.onnx": payloads["u2net_human_seg"],
    }
    models_root = version_root / "models"
    assert {
        path.relative_to(models_root).as_posix()
        for path in models_root.rglob("*")
        if path.is_file()
    } == set(expected_files)
    for file_name, payload in expected_files.items():
        copied = models_root / file_name
        assert copied.read_bytes() == payload
        assert copied.stat().st_size == len(payload)
        assert hashlib.sha256(copied.read_bytes()).hexdigest() == hashlib.sha256(
            payload
        ).hexdigest()

    pointer = json.loads((tool_root / "current.json").read_text(encoding="utf-8"))
    assert pointer == {"lockDigest": digest, "version": f"versions/{digest}"}
    assert (tool_root / pointer["version"]).is_dir()
    residue = [
        path.relative_to(tool_root).as_posix()
        for path in tool_root.rglob("*")
        if path.name == "verify"
        or path.name.startswith("staging-")
        or path.name.startswith("verification")
        or partial_download.search(path.name)
        or path.name.startswith("current.json.tmp")
    ]
    assert not residue


def test_setup_accepts_a_genuinely_disjoint_tool_root(tmp_path: Path) -> None:
    candidate = tmp_path / "disjoint-tool-root"
    result = run_setup_script(
        ". "
        f"{powershell_literal(SETUP_SCRIPT)} "
        f"-QtPython {powershell_literal(Path(sys.executable))}; "
        "Assert-SafeToolRoot "
        f"-Candidate {powershell_literal(candidate)} "
        f"-RepositoryRoot {powershell_literal(REPO_ROOT)}"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip().casefold() == str(candidate).casefold()


def test_setup_rejects_tool_root_overlapping_protected_roots() -> None:
    command = (
        ". "
        f"{powershell_literal(SETUP_SCRIPT)} "
        f"-QtPython {powershell_literal(Path(sys.executable))}; "
        f"$repo = {powershell_literal(REPO_ROOT)}; "
        "$install = Join-Path $env:LOCALAPPDATA 'Programs\\DesktopCompanion'; "
        "$pets = Join-Path $env:APPDATA 'DesktopCompanion\\pets'; "
        "$candidates = @("
        "(Split-Path -Parent $repo), $repo, (Join-Path $repo 'nested'), "
        "(Join-Path $repo '.venv'), (Join-Path $repo '.venv\\nested'), "
        "(Split-Path -Parent $install), $install, (Join-Path $install 'resources\\pets'), "
        "(Join-Path $install 'resources\\pets\\nested'), (Split-Path -Parent $pets), "
        "$pets, (Join-Path $pets 'nested')"
        "); "
        "foreach ($candidate in $candidates) { "
        "try { Assert-SafeToolRoot -Candidate $candidate -RepositoryRoot $repo | Out-Null; "
        "throw ('accepted protected root: ' + $candidate) } "
        "catch { if ($_.Exception.Message -like 'accepted protected root:*') { throw }; "
        "if ($_.Exception.Message -notlike 'Refusing unsafe tool root:*') { throw } } }; "
        "'protected-roots-rejected'"
    )
    result = run_setup_script(command)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "protected-roots-rejected"


def powershell_utf8_literal(value: str) -> str:
    encoded = base64.b64encode(value.encode("utf-8")).decode("ascii")
    return (
        "([System.Text.Encoding]::UTF8.GetString("
        f"[System.Convert]::FromBase64String('{encoded}')))"
    )


def test_seven_zip_listing_rejects_a_second_separator() -> None:
    listing = """\
Path = locked.7z
Type = 7z
----------
Path = safe.txt
Size = 1

----------
Path = replacement.txt
Size = 1
"""
    result = run_common_script(
        "ConvertFrom-SevenZipTechnicalListing "
        f"-Output {powershell_utf8_literal(listing)} | Out-Null"
    )

    assert result.returncode != 0
    assert "separator" in (result.stdout + result.stderr).casefold()


def test_seven_zip_listing_rejects_a_bare_carriage_return_path_injection() -> None:
    listing = """\
Path = locked.7z
Type = 7z
----------
Path = safe.txt\rPath = replacement.txt
Size = 1
"""
    result = run_common_script(
        "ConvertFrom-SevenZipTechnicalListing "
        f"-Output {powershell_utf8_literal(listing)} | Out-Null"
    )

    assert result.returncode != 0
    assert "control" in (result.stdout + result.stderr).casefold()


def test_seven_zip_listing_rejects_a_duplicate_path_newline_injection() -> None:
    listing = """\
Path = locked.7z
Type = 7z
----------
Path = safe.txt
Path = replacement.txt
Size = 1
"""
    result = run_common_script(
        "ConvertFrom-SevenZipTechnicalListing "
        f"-Output {powershell_utf8_literal(listing)} | Out-Null"
    )

    assert result.returncode != 0
    assert "invalid structured" in (result.stdout + result.stderr).casefold()


def test_seven_zip_listing_excludes_the_archive_header_from_entries() -> None:
    listing = """\
Path = locked.7z
Type = 7z
Physical Size = 1
----------
Path = safe.txt
Size = 1
"""
    result = run_common_script(
        "$records = @(ConvertFrom-SevenZipTechnicalListing "
        f"-Output {powershell_utf8_literal(listing)}); "
        "$records | ConvertTo-Json -Compress"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {"Path": "safe.txt", "Size": "1"}


def test_fake_7zr_listing_never_treats_the_archive_header_as_an_entry(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "locked.7z"
    extractor = tmp_path / "fake-7zr.cmd"
    archive.write_bytes(b"not parsed by the fake extractor")
    extractor.write_text(
        "@echo off\r\n"
        "echo Path = C:\\locked.7z\r\n"
        "echo Type = 7z\r\n"
        "echo ----------\r\n"
        "echo Path = safe.txt\r\n"
        "echo Size = 1\r\n"
        "exit /b 0\r\n",
        encoding="utf-8",
    )
    result = run_common_script(
        "Assert-SafeArchiveEntries "
        f"-ArchivePath {powershell_literal(archive)} -ArchiveType SevenZip "
        f"-SevenZipPath {powershell_literal(extractor)}"
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_fake_7zr_listing_rejects_a_second_entry_separator(tmp_path: Path) -> None:
    archive = tmp_path / "locked.7z"
    extractor = tmp_path / "fake-7zr.cmd"
    archive.write_bytes(b"not parsed by the fake extractor")
    extractor.write_text(
        "@echo off\r\n"
        "echo Path = locked.7z\r\n"
        "echo Type = 7z\r\n"
        "echo ----------\r\n"
        "echo Path = safe.txt\r\n"
        "echo Size = 1\r\n"
        "echo ----------\r\n"
        "echo Path = replacement.txt\r\n"
        "exit /b 0\r\n",
        encoding="utf-8",
    )
    result = run_common_script(
        "Assert-SafeArchiveEntries "
        f"-ArchivePath {powershell_literal(archive)} -ArchiveType SevenZip "
        f"-SevenZipPath {powershell_literal(extractor)}"
    )

    assert result.returncode != 0
    assert "separator" in (result.stdout + result.stderr).casefold()


def version_ownership_harness(tool_root: Path, mode: str) -> str:
    return (
        ". "
        f"{powershell_literal(SETUP_SCRIPT)} "
        f"-QtPython {powershell_literal(Path(sys.executable))}; "
        f"$root = {powershell_literal(tool_root)}; "
        f"$lockPath = {powershell_literal(LOCK_PATH)}; "
        f"$requirementsPath = {powershell_literal(MEDIA_LOCK)}; "
        "$script:fakeAsset = Join-Path (Split-Path -Parent $root) 'fake-asset.bin'; "
        "[System.IO.File]::WriteAllText($script:fakeAsset, 'asset'); "
        "$verifier = Join-Path (Split-Path -Parent $root) 'fake-verifier.ps1'; "
        "[System.IO.File]::WriteAllText($verifier, ''); "
        "$digest = Get-LockDigest -LockPath $lockPath -RequirementsPath $requirementsPath; "
        "$script:versionPath = Join-Path $root ('versions\\' + $digest); "
        f"$script:mode = '{mode}'; $script:verificationCount = 0; "
        "if ($script:mode -eq 'existing') { "
        "[System.IO.Directory]::CreateDirectory($script:versionPath) | Out-Null; "
        "[System.IO.File]::WriteAllText((Join-Path $script:versionPath 'sentinel.txt'), 'preserve') }; "
        "function Assert-FileDigest { param($Path, $ExpectedSize, $ExpectedSha256) }; "
        "function Open-VerifiedAsset { param($Asset, $DownloadsRoot) "
        "$stream = [System.IO.File]::Open($script:fakeAsset, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::Read); "
        "return [pscustomobject]@{ Path = $script:fakeAsset; Stream = $stream } }; "
        "function Assert-ExtractorVersion { param($ExtractorPath, $ExtractorLock) }; "
        "function Install-LockedTool { param($StagingRoot, $DownloadsRoot, $ToolKey, $ToolLock, $ExtractorPath) "
        "$root = Join-Path $StagingRoot ('tools\\' + $ToolKey); "
        "[System.IO.Directory]::CreateDirectory($root) | Out-Null; "
        "$relative = if ($ToolKey -eq 'imagemagick') { 'magick.exe' } elseif ($ToolKey -eq 'ffmpeg') { 'bin\\ffmpeg.exe' } else { 'bin\\cwebp.exe' }; "
        "$entry = Join-Path $root $relative; [System.IO.Directory]::CreateDirectory((Split-Path -Parent $entry)) | Out-Null; "
        "[System.IO.File]::WriteAllText($entry, $ToolKey); return $entry }; "
        "function Install-LockedPython { param($StagingRoot, $RequirementsPath, $WheelCache, $PythonRuntime) "
        "return [pscustomobject]@{ Interpreter = (Join-Path $StagingRoot 'python\\Scripts\\python.exe'); Freeze = @('example==1'); fileCount = 42; treeSha256 = ('a' * 64); RuntimeVersion = 'Python 3.12.10'; RuntimePublisher = 'CN=Python Software Foundation, O=Python Software Foundation, L=Beaverton, S=Oregon, C=US' } }; "
        "function Copy-LockedModels { param($StagingRoot, $DownloadsRoot, $Models) "
        "return [ordered]@{ 'isnet-anime' = 'models/isnet-anime.onnx'; 'u2net_human_seg' = 'models/u2net_human_seg.onnx' } }; "
        "function Invoke-ToolchainVerification { param($VerifierPath, $ToolRoot, $CandidateRoot, $QtPython) "
        "if ($script:mode -eq 'competing' -and $script:verificationCount -eq 0) { "
        "[System.IO.Directory]::CreateDirectory($script:versionPath) | Out-Null; "
        "[System.IO.File]::WriteAllText((Join-Path $script:versionPath 'sentinel.txt'), 'preserve') }; "
        "$script:verificationCount++ }; "
        "$failure = $null; try { Invoke-PetToolchainSetup -ToolRoot $root -LockPath $lockPath -RequirementsPath $requirementsPath -QtPython $script:fakeAsset -VerifierPath $verifier } catch { $failure = $_ }; "
        "if ($null -eq $failure) { throw 'expected version publication to fail' }; "
        "if ($failure.Exception.Message -notmatch 'version') { throw $failure }; "
        "if (-not (Test-Path -LiteralPath (Join-Path $script:versionPath 'sentinel.txt'))) { throw 'existing version was removed' }; "
        "'version-owner-preserved'"
    )


@pytest.mark.parametrize("mode", ["existing", "competing"])
def test_setup_preserves_a_version_not_owned_by_this_invocation(
    tmp_path: Path, mode: str
) -> None:
    result = run_setup_script(version_ownership_harness(tmp_path / "tool-root", mode))

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "version-owner-preserved"


def test_explicit_https_redirect_rejects_a_downgrade_without_network() -> None:
    result = run_common_script(
        "$redirect = [System.Net.Http.HttpResponseMessage]::new([System.Net.HttpStatusCode]::Redirect); "
        "$redirect.Headers.Location = [System.Uri]'http://example.invalid/asset.bin'; "
        "$request = { param($uri) return $redirect }; "
        "try { Resolve-ExplicitHttpsRedirect -InitialUri 'https://example.invalid/asset.bin' -Request $request | Out-Null } "
        "finally { $redirect.Dispose() }"
    )

    assert result.returncode != 0
    assert "must remain https" in (result.stdout + result.stderr).casefold()


def test_explicit_https_redirect_reads_real_headers_location_and_disposes_redirect(
    tmp_path: Path,
) -> None:
    result = run_common_script(
        "$redirect = [System.Net.Http.HttpResponseMessage]::new([System.Net.HttpStatusCode]::Found); "
        "$redirect.Content = [System.Net.Http.StringContent]::new('redirect-body'); "
        "$redirect.Headers.Location = [System.Uri]'https://example.invalid/releases/final.bin'; "
        "$final = [System.Net.Http.HttpResponseMessage]::new([System.Net.HttpStatusCode]::OK); "
        "$request = { param($uri) if ($uri.AbsoluteUri -ceq 'https://example.invalid/start.bin') { return $redirect }; return $final }; "
        "try { $resolved = Resolve-ExplicitHttpsRedirect -InitialUri 'https://example.invalid/start.bin' -Request $request; "
        "if ($resolved.FinalUri.AbsoluteUri -cne 'https://example.invalid/releases/final.bin') { throw 'absolute header location was not consumed' }; "
        "$disposed = $false; try { $redirect.Content.ReadAsStringAsync().GetAwaiter().GetResult() | Out-Null } "
        "catch [System.ObjectDisposedException] { $disposed = $true }; "
        "if (-not $disposed) { throw 'redirect response was not disposed' }; "
        "'real-header-redirect-passed' } finally { $final.Dispose() }"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "real-header-redirect-passed"


def test_explicit_https_redirect_resolves_relative_real_headers_location() -> None:
    result = run_common_script(
        "$redirect = [System.Net.Http.HttpResponseMessage]::new([System.Net.HttpStatusCode]::TemporaryRedirect); "
        "$redirect.Headers.Location = [System.Uri]::new('../objects/final.bin', [System.UriKind]::Relative); "
        "$final = [System.Net.Http.HttpResponseMessage]::new([System.Net.HttpStatusCode]::OK); "
        "$request = { param($uri) if ($uri.AbsoluteUri -ceq 'https://example.invalid/releases/current.bin') { return $redirect }; return $final }; "
        "try { $resolved = Resolve-ExplicitHttpsRedirect -InitialUri 'https://example.invalid/releases/current.bin' -Request $request; "
        "if ($resolved.FinalUri.AbsoluteUri -cne 'https://example.invalid/objects/final.bin') { throw 'relative header location was not resolved against current URI' }; "
        "'relative-header-redirect-passed' } finally { $final.Dispose() }"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "relative-header-redirect-passed"


def test_explicit_https_redirect_rejects_real_headers_missing_location_and_bounds_chain() -> None:
    result = run_common_script(
        "$missing = [System.Net.Http.HttpResponseMessage]::new([System.Net.HttpStatusCode]::Found); "
        "$requestMissing = { param($uri) return $missing }; "
        "$missingFailure = $null; try { Resolve-ExplicitHttpsRedirect -InitialUri 'https://example.invalid/start.bin' -Request $requestMissing | Out-Null } catch { $missingFailure = $_ }; "
        "if ($null -eq $missingFailure -or $missingFailure.Exception.Message -notmatch 'location failure') { throw 'missing Headers.Location was accepted' }; "
        "$script:redirectRequests = 0; "
        "$requestLoop = { param($uri) $script:redirectRequests++; $response = [System.Net.Http.HttpResponseMessage]::new([System.Net.HttpStatusCode]::Found); $response.Headers.Location = [System.Uri]'https://example.invalid/again.bin'; return $response }; "
        "$loopFailure = $null; try { Resolve-ExplicitHttpsRedirect -InitialUri 'https://example.invalid/start.bin' -Request $requestLoop -MaximumRedirects 1 | Out-Null } catch { $loopFailure = $_ }; "
        "if ($null -eq $loopFailure -or $loopFailure.Exception.Message -notmatch 'redirect limit') { throw 'redirect chain was not bounded' }; "
        "if ($script:redirectRequests -ne 2) { throw 'redirect bound made an unexpected number of requests' }; "
        "'missing-and-bounded-real-headers-rejected'"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "missing-and-bounded-real-headers-rejected"


def test_explicit_https_download_consumes_real_headers_location_with_fake_handler(
    tmp_path: Path,
) -> None:
    out_file = tmp_path / "partial.bin"
    out_file.write_bytes(b"placeholder")
    handler_source = """
using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;

public sealed class PetToolchainRedirectHandler : HttpMessageHandler
{
    public readonly List<string> Requests = new List<string>();
    private int _count;

    protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        Requests.Add(request.RequestUri.AbsoluteUri);
        if (_count++ == 0)
        {
            var redirect = new HttpResponseMessage(HttpStatusCode.Found);
            redirect.Headers.Location = new Uri("../objects/final.bin", UriKind.Relative);
            return Task.FromResult(redirect);
        }
        var final = new HttpResponseMessage(HttpStatusCode.OK);
        final.Content = new ByteArrayContent(new byte[] { 108, 111, 99, 107, 101, 100 });
        return Task.FromResult(final);
    }
}
"""
    command = (
        f"Add-Type -TypeDefinition {powershell_literal(handler_source)}; "
        "$handler = [PetToolchainRedirectHandler]::new(); "
        "try { Invoke-ExplicitHttpsDownload -Uri 'https://example.invalid/releases/start.bin' "
        f"-OutFile {powershell_literal(out_file)} -HttpMessageHandler $handler; "
        f"$bytes = [System.IO.File]::ReadAllBytes({powershell_literal(out_file)}); "
        "if ([System.Text.Encoding]::ASCII.GetString($bytes) -cne 'locked') { throw 'download did not write final response bytes' }; "
        "if ($handler.Requests.Count -ne 2 -or $handler.Requests[1] -cne 'https://example.invalid/objects/final.bin') { "
        "throw 'production download did not consume Headers.Location' }; "
        "'fake-handler-redirect-download-passed' } finally { $handler.Dispose() }"
    )

    result = run_common_script(command)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "fake-handler-redirect-download-passed"


def test_verified_asset_handle_blocks_replacement_after_hash_validation(
    tmp_path: Path,
) -> None:
    content = b"verified cache bytes"
    digest = hashlib.sha256(content).hexdigest()
    cache_path = tmp_path / f"{digest}-asset.bin"
    cache_path.write_bytes(content)
    command = (
        "$asset = [pscustomobject]@{ "
        "url = 'https://example.invalid/asset.bin'; "
        f"size = {len(content)}; sha256 = '{digest}' }}; "
        "$held = Open-VerifiedAsset -Asset $asset "
        f"-DownloadsRoot {powershell_literal(tmp_path)}; "
        "try { $blocked = $false; "
        "try { $writer = [System.IO.File]::Open($held.Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None); $writer.Dispose() } "
        "catch [System.IO.IOException] { $blocked = $true }; "
        "if (-not $blocked) { throw 'replacement unexpectedly opened' }; "
        "if ($held.Stream.ReadByte() -ne [byte][char]'v') { throw 'unexpected held bytes' } } "
        "finally { $held.Stream.Dispose() }; "
        "'verified-asset-locked'"
    )
    result = run_common_script(command)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "verified-asset-locked"
    assert cache_path.read_bytes() == content


def test_cache_lock_serializes_same_digest_across_powershell_processes(
    tmp_path: Path,
) -> None:
    downloads = tmp_path / "downloads"
    cache_path = downloads / ("a" * 64 + "-asset.bin")
    holder_ready = tmp_path / "holder-ready"
    release_holder = tmp_path / "release-holder"
    acquired = tmp_path / "waiter-acquired"
    holder = tmp_path / "hold-cache-lock.ps1"
    waiter = tmp_path / "wait-cache-lock.ps1"
    holder.write_text(
        "$ErrorActionPreference = 'Stop'; "
        f". {powershell_literal(COMMON_SCRIPT)}; "
        f"[System.IO.Directory]::CreateDirectory({powershell_literal(downloads)}) | Out-Null; "
        "$lock = Enter-PetToolchainCacheLock "
        f"-DownloadsRoot {powershell_literal(downloads)} -CachePath {powershell_literal(cache_path)}; "
        f"[System.IO.File]::WriteAllText({powershell_literal(holder_ready)}, 'ready'); "
        f"while (-not (Test-Path -LiteralPath {powershell_literal(release_holder)})) {{ "
        "Start-Sleep -Milliseconds 50 }; $lock.Dispose()",
        encoding="utf-8",
    )
    waiter.write_text(
        "$ErrorActionPreference = 'Stop'; "
        f". {powershell_literal(COMMON_SCRIPT)}; "
        "$lock = Enter-PetToolchainCacheLock "
        f"-DownloadsRoot {powershell_literal(downloads)} -CachePath {powershell_literal(cache_path)}; "
        f"[System.IO.File]::WriteAllText({powershell_literal(acquired)}, 'acquired'); $lock.Dispose()",
        encoding="utf-8",
    )
    holder_process = subprocess.Popen(
        [powershell(), "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(holder)],
        cwd=REPO_ROOT,
        text=True,
    )
    waiter_process: subprocess.Popen[str] | None = None
    try:
        deadline = time.monotonic() + 5
        while not holder_ready.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert holder_ready.exists(), "cache-lock holder did not start"

        waiter_process = subprocess.Popen(
            [powershell(), "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(waiter)],
            cwd=REPO_ROOT,
            text=True,
        )
        time.sleep(0.4)
        assert not acquired.exists(), "same-digest cache lock was not exclusive"

        release_holder.write_text("release", encoding="utf-8")
        assert holder_process.wait(timeout=10) == 0
        assert waiter_process.wait(timeout=10) == 0
    finally:
        if holder_process.poll() is None:
            holder_process.kill()
            holder_process.wait(timeout=5)
        if waiter_process is not None and waiter_process.poll() is None:
            waiter_process.kill()
            waiter_process.wait(timeout=5)

    assert acquired.read_text(encoding="utf-8") == "acquired"


def test_corrupt_cache_hit_is_rehashed_and_replaced_before_consumption(
    tmp_path: Path,
) -> None:
    content = b"fresh locked bytes"
    digest = hashlib.sha256(content).hexdigest()
    cache_path = tmp_path / f"{digest}-asset.bin"
    cache_path.write_bytes(b"corrupt cache hit")
    content_literal = base64.b64encode(content).decode("ascii")
    command = (
        "$asset = [pscustomobject]@{ "
        "url = 'https://example.invalid/asset.bin'; "
        f"size = {len(content)}; sha256 = '{digest}' }}; "
        "function Invoke-ExplicitHttpsDownload { param($Uri, $OutFile) "
        "[System.IO.File]::WriteAllBytes($OutFile, "
        f"[System.Convert]::FromBase64String('{content_literal}')) }}; "
        "$path = Get-VerifiedDownload -Asset $asset "
        f"-DownloadsRoot {powershell_literal(tmp_path)}; "
        f"if ($path -ne {powershell_literal(cache_path)}) {{ throw 'cache path changed' }}; "
        "Assert-FileDigest -Path $path "
        f"-ExpectedSize {len(content)} -ExpectedSha256 '{digest}'; "
        "'cache-rehashed-before-consumption'"
    )

    result = run_common_script(command)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "cache-rehashed-before-consumption"
    assert cache_path.read_bytes() == content


def test_checked_process_timeout_terminates_the_entire_process_tree(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "child-survived-timeout.txt"
    child_script = tmp_path / "child.ps1"
    parent_script = tmp_path / "parent.ps1"
    child_script.write_text(
        "Start-Sleep -Seconds 3; "
        f"[System.IO.File]::WriteAllText({powershell_literal(marker)}, 'survived')",
        encoding="utf-8",
    )
    parent_script.write_text(
        "$hostPath = Join-Path $PSHOME 'pwsh.exe'; "
        "if (-not (Test-Path -LiteralPath $hostPath)) { "
        "$hostPath = Join-Path $PSHOME 'powershell.exe' }; "
        "$child = Start-Process -FilePath $hostPath "
        "-ArgumentList @('-NoLogo', '-NoProfile', '-NonInteractive', '-File', "
        f"{powershell_literal(child_script)}) -PassThru; "
        "Wait-Process -Id $child.Id",
        encoding="utf-8",
    )
    command = (
        "$hostPath = Join-Path $PSHOME 'pwsh.exe'; "
        "if (-not (Test-Path -LiteralPath $hostPath)) { "
        "$hostPath = Join-Path $PSHOME 'powershell.exe' }; "
        "$failure = $null; try { Invoke-CheckedProcess -FilePath $hostPath "
        "-ArgumentList @('-NoLogo', '-NoProfile', '-NonInteractive', '-File', "
        f"{powershell_literal(parent_script)}) -TimeoutSeconds 1 | Out-Null; "
        "throw 'timeout was not reported' } catch { $failure = $_ }; "
        "if ($failure.Exception.Message -notmatch 'timed out') { throw $failure }; "
        "Start-Sleep -Seconds 4; "
        f"if (Test-Path -LiteralPath {powershell_literal(marker)}) {{ "
        "throw 'child survived timeout' }; 'process-tree-terminated'"
    )

    result = run_common_script(command)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "process-tree-terminated"


def test_write_path_check_rejects_a_reparse_parent_before_any_file_write(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    reparse_parent = tmp_path / "reparse-parent"
    command = (
        f"[System.IO.Directory]::CreateDirectory({powershell_literal(outside)}) | Out-Null; "
        "New-Item -ItemType Junction "
        f"-Path {powershell_literal(reparse_parent)} -Target {powershell_literal(outside)} | Out-Null; "
        "$failure = $null; try { Assert-ContainedWritePath "
        f"-Root {powershell_literal(reparse_parent)} "
        f"-Path {powershell_literal(reparse_parent / 'would-escape.txt')} | Out-Null }} "
        "catch { $failure = $_ }; "
        "if ($null -eq $failure -or $failure.Exception.Message -notmatch 'reparse') { "
        "throw 'reparse parent was accepted' }; "
        f"if (Test-Path -LiteralPath {powershell_literal(outside / 'would-escape.txt')}) {{ "
        "throw 'write reached the reparse target' }; 'reparse-parent-rejected'"
    )

    result = run_common_script(command)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "reparse-parent-rejected"


def publication_harness(
    tool_root: Path, pointer_failure: bool, assert_verifier_tool_root: bool = False
) -> str:
    failure_override = (
        "function Write-CurrentPointerAtomically { param($Root, $LockDigest, $TemporaryPath) "
        "throw 'forced pointer failure' }; "
        if pointer_failure
        else ""
    )
    expected = "pointer-failure-contained" if pointer_failure else "published-forward-slashes"
    return (
        ". "
        f"{powershell_literal(SETUP_SCRIPT)} "
        f"-QtPython {powershell_literal(Path(sys.executable))}; "
        f"$root = {powershell_literal(tool_root)}; "
        f"$lockPath = {powershell_literal(LOCK_PATH)}; "
        f"$requirementsPath = {powershell_literal(MEDIA_LOCK)}; "
        f"$script:assertVerifierToolRoot = ${str(assert_verifier_tool_root).lower()}; "
        "$script:verifiedToolRoots = @(); "
        "$script:fakeAsset = Join-Path (Split-Path -Parent $root) 'publish-asset.bin'; "
        "[System.IO.File]::WriteAllText($script:fakeAsset, 'asset'); "
        "$verifier = Join-Path (Split-Path -Parent $root) 'publish-verifier.ps1'; "
        "[System.IO.File]::WriteAllText($verifier, ''); "
        "$digest = Get-LockDigest -LockPath $lockPath -RequirementsPath $requirementsPath; "
        "$versionPath = Join-Path $root ('versions\\' + $digest); "
        "function Open-VerifiedAsset { param($Asset, $DownloadsRoot) "
        "$stream = [System.IO.File]::Open($script:fakeAsset, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::Read); "
        "return [pscustomobject]@{ Path = $script:fakeAsset; Stream = $stream } }; "
        "function Assert-ExtractorVersion { param($ExtractorPath, $ExtractorLock) }; "
        "function Install-LockedTool { param($StagingRoot, $DownloadsRoot, $ToolKey, $ToolLock, $ExtractorPath) "
        "$toolRoot = Join-Path $StagingRoot ('tools\\' + $ToolKey); "
        "[System.IO.Directory]::CreateDirectory($toolRoot) | Out-Null; "
        "$relative = if ($ToolKey -eq 'imagemagick') { 'magick.exe' } elseif ($ToolKey -eq 'ffmpeg') { 'bin\\ffmpeg.exe' } else { 'bin\\cwebp.exe' }; "
        "$entry = Join-Path $toolRoot $relative; "
        "[System.IO.Directory]::CreateDirectory((Split-Path -Parent $entry)) | Out-Null; "
        "[System.IO.File]::WriteAllText($entry, $ToolKey); return $entry }; "
        "function Install-LockedPython { param($StagingRoot, $RequirementsPath, $WheelCache, $PythonRuntime) "
        "return [pscustomobject]@{ Interpreter = (Join-Path $StagingRoot 'python\\Scripts\\python.exe'); Freeze = @('example==1'); fileCount = 42; treeSha256 = ('a' * 64); RuntimeVersion = 'Python 3.12.10'; RuntimePublisher = 'CN=Python Software Foundation, O=Python Software Foundation, L=Beaverton, S=Oregon, C=US' } }; "
        "function Copy-LockedModels { param($StagingRoot, $DownloadsRoot, $Models) "
        "return [ordered]@{ 'isnet-anime' = 'models/isnet-anime.onnx'; 'u2net_human_seg' = 'models/u2net_human_seg.onnx' } }; "
        "function Invoke-ToolchainVerification { param($VerifierPath, $ToolRoot, $CandidateRoot, $QtPython) "
        "if ($script:assertVerifierToolRoot -and [string]::IsNullOrWhiteSpace($ToolRoot)) { "
        "throw 'verifier did not receive ToolRoot' }; "
        "$script:verifiedToolRoots += $ToolRoot }; "
        f"{failure_override}"
        "$failure = $null; try { Invoke-PetToolchainSetup -ToolRoot $root -LockPath $lockPath -RequirementsPath $requirementsPath -QtPython $script:fakeAsset -VerifierPath $verifier } catch { $failure = $_ }; "
        + (
            "if ($null -eq $failure -or $failure.Exception.Message -notmatch 'pointer failure') { throw 'pointer failure was not reported' }; "
            "if (Test-Path -LiteralPath (Join-Path $root 'current.json')) { throw 'pointer was published after failure' }; "
            "if (Test-Path -LiteralPath $versionPath) { throw 'owned unpublished version was retained' }; "
            f"'{expected}'"
            if pointer_failure
            else "if ($null -ne $failure) { throw $failure }; "
            "$manifest = Get-Content -Raw -LiteralPath (Join-Path $versionPath 'installed.json') | ConvertFrom-Json -Depth 16; "
            "foreach ($toolKey in @('ffmpeg', 'imagemagick', 'libwebp')) { "
            "$keys = @($manifest.assets.tools.$toolKey.PSObject.Properties.Name | Sort-Object); "
            "if (($keys -join ',') -cne 'sha256,size') { throw 'installed manifest tool schema changed' } }; "
            "$pythonKeys = @($manifest.python.PSObject.Properties.Name | Sort-Object); "
            "if (($pythonKeys -join ',') -cne 'fileCount,freeze,interpreter,runtimePublisher,runtimeVersion,treeSha256') { throw 'installed manifest Python schema was not migrated' }; "
            "if ($manifest.python.fileCount -ne 42 -or $manifest.python.treeSha256 -cne ('a' * 64)) { throw 'installed manifest Python inventory was not retained' }; "
            "if ($manifest.python.runtimeVersion -cne 'Python 3.12.10' -or $manifest.python.runtimePublisher -notmatch 'Python Software Foundation') { throw 'installed manifest Python runtime diagnostics were not retained' }; "
            "if ($manifest.entrypoints.tools.ffmpeg -ne 'tools/ffmpeg/bin/ffmpeg.exe') { throw 'installed path did not use forward slashes' }; "
            "if ($manifest.entrypoints.tools.ffmpeg.Contains('\\')) { throw 'installed path retains a backslash' }; "
            "if ($script:assertVerifierToolRoot) { "
            "if (@($script:verifiedToolRoots).Count -ne 2) { throw 'verifier was not called twice' }; "
            "$expectedRoot = [System.IO.Path]::GetFullPath($root); "
            "if (@($script:verifiedToolRoots | Where-Object { $_ -cne $expectedRoot }).Count -ne 0) { "
            "throw 'verifier received a non-canonical ToolRoot' } }; "
            "if (-not (Test-Path -LiteralPath (Join-Path $root 'current.json'))) { throw 'pointer was not published' }; "
            f"'{expected}'"
        )
    )


def test_successful_publication_writes_forward_slash_entrypoints(tmp_path: Path) -> None:
    result = run_setup_script(publication_harness(tmp_path / "tool-root", False))

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip().endswith("published-forward-slashes")


def test_setup_forwards_canonical_tool_root_to_both_verifier_invocations(
    tmp_path: Path,
) -> None:
    result = run_setup_script(
        publication_harness(
            tmp_path / "tool-root", False, assert_verifier_tool_root=True
        )
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip().endswith("published-forward-slashes")


def test_pointer_failure_never_publishes_and_removes_only_owned_version(tmp_path: Path) -> None:
    result = run_setup_script(publication_harness(tmp_path / "tool-root", True))

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "pointer-failure-contained"


def concurrent_publication_script(
    *,
    tool_root: Path,
    lock_path: Path,
    label: str,
    ready_path: Path,
    release_path: Path,
    hold_pointer_write: bool,
) -> str:
    return (
        "$ErrorActionPreference = 'Stop'; "
        ". "
        f"{powershell_literal(SETUP_SCRIPT)} "
        f"-QtPython {powershell_literal(Path(sys.executable))}; "
        f"$root = {powershell_literal(tool_root)}; "
        f"$lockPath = {powershell_literal(lock_path)}; "
        f"$requirementsPath = {powershell_literal(MEDIA_LOCK)}; "
        f"$script:readyPath = {powershell_literal(ready_path)}; "
        f"$script:releasePath = {powershell_literal(release_path)}; "
        f"$script:holdPointerWrite = ${str(hold_pointer_write).lower()}; "
        f"$script:fakeAsset = Join-Path (Split-Path -Parent $root) 'concurrent-{label}-asset.bin'; "
        "[System.IO.File]::WriteAllText($script:fakeAsset, 'asset'); "
        f"$verifier = Join-Path (Split-Path -Parent $root) 'concurrent-{label}-verifier.ps1'; "
        "[System.IO.File]::WriteAllText($verifier, ''); "
        "function Open-VerifiedAsset { param($Asset, $DownloadsRoot) "
        "$stream = [System.IO.File]::Open($script:fakeAsset, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::Read); "
        "return [pscustomobject]@{ Path = $script:fakeAsset; Stream = $stream } }; "
        "function Assert-ExtractorVersion { param($ExtractorPath, $ExtractorLock) }; "
        "function Install-LockedTool { param($StagingRoot, $DownloadsRoot, $ToolKey, $ToolLock, $ExtractorPath) "
        "$toolRoot = Join-Path $StagingRoot ('tools\\' + $ToolKey); "
        "[System.IO.Directory]::CreateDirectory($toolRoot) | Out-Null; "
        "$relative = if ($ToolKey -eq 'imagemagick') { 'magick.exe' } elseif ($ToolKey -eq 'ffmpeg') { 'bin\\ffmpeg.exe' } else { 'bin\\cwebp.exe' }; "
        "$entry = Join-Path $toolRoot $relative; "
        "[System.IO.Directory]::CreateDirectory((Split-Path -Parent $entry)) | Out-Null; "
        "[System.IO.File]::WriteAllText($entry, $ToolKey); return $entry }; "
        "function Install-LockedPython { param($StagingRoot, $RequirementsPath, $WheelCache, $PythonRuntime) "
        "return [pscustomobject]@{ Interpreter = (Join-Path $StagingRoot 'python\\Scripts\\python.exe'); Freeze = @('example==1'); fileCount = 42; treeSha256 = ('a' * 64); RuntimeVersion = 'Python 3.12.10'; RuntimePublisher = 'CN=Python Software Foundation, O=Python Software Foundation, L=Beaverton, S=Oregon, C=US' } }; "
        "function Copy-LockedModels { param($StagingRoot, $DownloadsRoot, $Models) "
        "return [ordered]@{ 'isnet-anime' = 'models/isnet-anime.onnx'; 'u2net_human_seg' = 'models/u2net_human_seg.onnx' } }; "
        "function Invoke-ToolchainVerification { param($VerifierPath, $ToolRoot, $CandidateRoot, $QtPython) }; "
        "function Write-Utf8FileAndFlush { param($Root, $Path, $Text, $Stream) "
        "$bytes = [System.Text.UTF8Encoding]::new($false).GetBytes($Text); "
        "$ownedStream = $null -eq $Stream; if ($ownedStream) { $Stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None) }; "
        "try { $Stream.Write($bytes, 0, $bytes.Length); $Stream.Flush($true) } finally { if ($ownedStream) { $Stream.Dispose() } }; "
        "if ($script:holdPointerWrite -and [System.IO.Path]::GetFileName($Path).StartsWith('current.json.tmp')) { "
        "[System.IO.File]::WriteAllText($script:readyPath, 'ready'); "
        "$deadline = [System.DateTime]::UtcNow.AddSeconds(10); "
        "while (-not (Test-Path -LiteralPath $script:releasePath) -and [System.DateTime]::UtcNow -lt $deadline) { Start-Sleep -Milliseconds 25 }; "
        "if (-not (Test-Path -LiteralPath $script:releasePath)) { throw 'concurrent publication release did not arrive' } } }; "
        "Invoke-PetToolchainSetup -ToolRoot $root -LockPath $lockPath -RequirementsPath $requirementsPath "
        "-QtPython $script:fakeAsset -VerifierPath $verifier; "
        f"'concurrent-{label}-published'"
    )


def test_two_different_digests_publish_without_cross_deleting_pointer_state(
    tmp_path: Path,
) -> None:
    tool_root = tmp_path / "tool-root"
    lock_a = tmp_path / "lock-a.json"
    lock_b = tmp_path / "lock-b.json"
    lock_a.write_bytes(LOCK_PATH.read_bytes())
    lock_b.write_bytes(b"\n" + LOCK_PATH.read_bytes())
    digest_a = hashlib.sha256(lock_a.read_bytes() + MEDIA_LOCK.read_bytes()).hexdigest()
    digest_b = hashlib.sha256(lock_b.read_bytes() + MEDIA_LOCK.read_bytes()).hexdigest()
    ready_path = tmp_path / "first-pointer-temp-created"
    release_path = tmp_path / "release-first-pointer-publish"
    first_script = tmp_path / "first-publish.ps1"
    second_script = tmp_path / "second-publish.ps1"
    first_script.write_text(
        concurrent_publication_script(
            tool_root=tool_root,
            lock_path=lock_a,
            label="first",
            ready_path=ready_path,
            release_path=release_path,
            hold_pointer_write=True,
        ),
        encoding="utf-8",
    )
    second_script.write_text(
        concurrent_publication_script(
            tool_root=tool_root,
            lock_path=lock_b,
            label="second",
            ready_path=ready_path,
            release_path=release_path,
            hold_pointer_write=False,
        ),
        encoding="utf-8",
    )
    first_process = subprocess.Popen(
        [powershell(), "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(first_script)],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    second_process: subprocess.Popen[str] | None = None
    try:
        deadline = time.monotonic() + 10
        while not ready_path.exists() and time.monotonic() < deadline:
            time.sleep(0.025)
        assert ready_path.exists(), "first publication did not hold its temporary pointer"

        second_process = subprocess.Popen(
            [powershell(), "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(second_script)],
            cwd=REPO_ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        time.sleep(1)
        release_path.write_text("release", encoding="utf-8")
        first_stdout, first_stderr = first_process.communicate(timeout=20)
        second_stdout, second_stderr = second_process.communicate(timeout=20)
    finally:
        if first_process.poll() is None:
            first_process.kill()
            first_process.wait(timeout=5)
        if second_process is not None and second_process.poll() is None:
            second_process.kill()
            second_process.wait(timeout=5)

    assert first_process.returncode == 0, first_stdout + first_stderr
    assert second_process is not None
    assert second_process.returncode == 0, second_stdout + second_stderr
    current = json.loads((tool_root / "current.json").read_text(encoding="utf-8"))
    assert current["lockDigest"] in {digest_a, digest_b}
    assert current["version"] == f"versions/{current['lockDigest']}"
    assert (tool_root / current["version"] / "installed.json").is_file()
    for digest in (digest_a, digest_b):
        manifest_path = tool_root / "versions" / digest / "installed.json"
        assert json.loads(manifest_path.read_text(encoding="utf-8"))["lockDigest"] == digest
    assert not list(tool_root.glob("current.json.tmp"))
    assert not list(tool_root.glob("current.json.tmp.*"))


def foreign_pointer_tmp_failure_harness(tool_root: Path, lock_path: Path) -> str:
    return (
        ". "
        f"{powershell_literal(SETUP_SCRIPT)} "
        f"-QtPython {powershell_literal(Path(sys.executable))}; "
        f"$root = {powershell_literal(tool_root)}; "
        f"$lockPath = {powershell_literal(lock_path)}; "
        f"$requirementsPath = {powershell_literal(MEDIA_LOCK)}; "
        "$script:fakeAsset = Join-Path (Split-Path -Parent $root) 'foreign-temp-asset.bin'; "
        "[System.IO.File]::WriteAllText($script:fakeAsset, 'asset'); "
        "$verifier = Join-Path (Split-Path -Parent $root) 'foreign-temp-verifier.ps1'; "
        "[System.IO.File]::WriteAllText($verifier, ''); "
        "$digest = Get-LockDigest -LockPath $lockPath -RequirementsPath $requirementsPath; "
        "$versionPath = Join-Path $root ('versions\\' + $digest); "
        "$oldVersion = Join-Path $root 'versions\\old-complete-version'; "
        "[System.IO.Directory]::CreateDirectory($oldVersion) | Out-Null; "
        "[System.IO.File]::WriteAllText((Join-Path $oldVersion 'installed.json'), '{\"lockDigest\":\"old-complete-version\"}'); "
        "$oldPointer = '{\"lockDigest\":\"old-complete-version\",\"version\":\"versions/old-complete-version\"}'; "
        "[System.IO.File]::WriteAllText((Join-Path $root 'current.json'), $oldPointer); "
        "[System.IO.File]::WriteAllText((Join-Path $root 'current.json.tmp'), 'foreign-temp'); "
        "function Open-VerifiedAsset { param($Asset, $DownloadsRoot) "
        "$stream = [System.IO.File]::Open($script:fakeAsset, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::Read); "
        "return [pscustomobject]@{ Path = $script:fakeAsset; Stream = $stream } }; "
        "function Assert-ExtractorVersion { param($ExtractorPath, $ExtractorLock) }; "
        "function Install-LockedTool { param($StagingRoot, $DownloadsRoot, $ToolKey, $ToolLock, $ExtractorPath) "
        "$toolRoot = Join-Path $StagingRoot ('tools\\' + $ToolKey); "
        "[System.IO.Directory]::CreateDirectory($toolRoot) | Out-Null; "
        "$relative = if ($ToolKey -eq 'imagemagick') { 'magick.exe' } elseif ($ToolKey -eq 'ffmpeg') { 'bin\\ffmpeg.exe' } else { 'bin\\cwebp.exe' }; "
        "$entry = Join-Path $toolRoot $relative; "
        "[System.IO.Directory]::CreateDirectory((Split-Path -Parent $entry)) | Out-Null; "
        "[System.IO.File]::WriteAllText($entry, $ToolKey); return $entry }; "
        "function Install-LockedPython { param($StagingRoot, $RequirementsPath, $WheelCache, $PythonRuntime) "
        "return [pscustomobject]@{ Interpreter = (Join-Path $StagingRoot 'python\\Scripts\\python.exe'); Freeze = @('example==1'); fileCount = 42; treeSha256 = ('a' * 64); RuntimeVersion = 'Python 3.12.10'; RuntimePublisher = 'CN=Python Software Foundation, O=Python Software Foundation, L=Beaverton, S=Oregon, C=US' } }; "
        "function Copy-LockedModels { param($StagingRoot, $DownloadsRoot, $Models) "
        "return [ordered]@{ 'isnet-anime' = 'models/isnet-anime.onnx'; 'u2net_human_seg' = 'models/u2net_human_seg.onnx' } }; "
        "function Invoke-ToolchainVerification { param($VerifierPath, $ToolRoot, $CandidateRoot, $QtPython) }; "
        "function Write-Utf8FileAndFlush { param($Root, $Path, $Text, $Stream) "
        "$bytes = [System.Text.UTF8Encoding]::new($false).GetBytes($Text); "
        "$ownedStream = $null -eq $Stream; if ($ownedStream) { $Stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None) }; "
        "try { $Stream.Write($bytes, 0, $bytes.Length); $Stream.Flush($true) } finally { if ($ownedStream) { $Stream.Dispose() } }; "
        "if ([System.IO.Path]::GetFileName($Path).StartsWith('current.json.tmp')) { throw 'forced pointer write failure' } }; "
        "$failure = $null; try { Invoke-PetToolchainSetup -ToolRoot $root -LockPath $lockPath -RequirementsPath $requirementsPath -QtPython $script:fakeAsset -VerifierPath $verifier } catch { $failure = $_ }; "
        "if ($null -eq $failure -or $failure.Exception.Message -notmatch 'forced pointer write failure') { throw 'pointer failure was not reported' }; "
        "if ((Get-Content -Raw -LiteralPath (Join-Path $root 'current.json')) -cne $oldPointer) { throw 'existing pointer changed' }; "
        "if (-not (Test-Path -LiteralPath (Join-Path $oldVersion 'installed.json'))) { throw 'existing version was removed' }; "
        "if ((Get-Content -Raw -LiteralPath (Join-Path $root 'current.json.tmp')) -cne 'foreign-temp') { throw 'foreign pointer temporary file was changed' }; "
        "if (Test-Path -LiteralPath $versionPath) { throw 'failed invocation retained its owned version' }; "
        "if (@(Get-ChildItem -LiteralPath $root -Filter 'current.json.tmp*' -Force | Where-Object { $_.Name -ne 'current.json.tmp' }).Count -ne 0) { throw 'failed invocation retained a unique pointer temporary file' }; "
        "'foreign-temp-preserved'"
    )


def test_publish_failure_removes_only_its_unique_tmp_and_owned_version(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / "failure-lock.json"
    lock_path.write_bytes(b"\n" + LOCK_PATH.read_bytes())
    result = run_setup_script(
        foreign_pointer_tmp_failure_harness(tmp_path / "tool-root", lock_path)
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "foreign-temp-preserved"


def publish_mutex_holder_script(
    *, root: Path, ready_path: Path, release_path: Path, abandon: bool
) -> str:
    tail = "exit 0" if abandon else (
        "try { while (-not (Test-Path -LiteralPath $releasePath)) { Start-Sleep -Milliseconds 25 } } "
        "finally { $mutex.ReleaseMutex(); $mutex.Dispose() }"
    )
    return (
        "$ErrorActionPreference = 'Stop'; "
        ". "
        f"{powershell_literal(SETUP_SCRIPT)} "
        f"-QtPython {powershell_literal(Path(sys.executable))}; "
        f"$root = {powershell_literal(root)}; "
        f"$readyPath = {powershell_literal(ready_path)}; "
        f"$releasePath = {powershell_literal(release_path)}; "
        "$mutex = Enter-PetToolchainPublishMutex -Root $root -TimeoutSeconds 5; "
        "[System.IO.File]::WriteAllText($readyPath, 'ready'); "
        f"{tail}"
    )


def test_publish_mutex_hides_tool_root_and_times_out_for_another_process(
    tmp_path: Path,
) -> None:
    root = tmp_path / "tool-root"
    ready_path = tmp_path / "mutex-ready"
    release_path = tmp_path / "mutex-release"
    holder = tmp_path / "hold-publish-mutex.ps1"
    holder.write_text(
        publish_mutex_holder_script(
            root=root,
            ready_path=ready_path,
            release_path=release_path,
            abandon=False,
        ),
        encoding="utf-8",
    )
    process = subprocess.Popen(
        [powershell(), "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(holder)],
        cwd=REPO_ROOT,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not ready_path.exists() and time.monotonic() < deadline:
            time.sleep(0.025)
        assert ready_path.exists(), "mutex holder did not start"
        result = run_setup_script(
            ". "
            f"{powershell_literal(SETUP_SCRIPT)} "
            f"-QtPython {powershell_literal(Path(sys.executable))}; "
            f"$root = {powershell_literal(root)}; "
            "$name = Get-PetToolchainPublishMutexName -Root $root; "
            "if ($name.Contains($root)) { throw 'mutex name leaked the tool root' }; "
            "$failure = $null; try { $mutex = Enter-PetToolchainPublishMutex -Root $root -TimeoutSeconds 1; "
            "try { throw 'mutex unexpectedly acquired' } finally { $mutex.ReleaseMutex(); $mutex.Dispose() } } "
            "catch { $failure = $_ }; "
            "if ($null -eq $failure -or $failure.Exception.Message -notmatch 'Timed out waiting') { throw $failure }; "
            "'publish-mutex-timeout-observed'"
        )
    finally:
        release_path.write_text("release", encoding="utf-8")
        if process.poll() is None:
            assert process.wait(timeout=10) == 0

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "publish-mutex-timeout-observed"


def test_publish_mutex_recovers_an_abandoned_owner(tmp_path: Path) -> None:
    root = tmp_path / "tool-root"
    ready_path = tmp_path / "abandoned-mutex-ready"
    holder = tmp_path / "abandon-publish-mutex.ps1"
    holder.write_text(
        publish_mutex_holder_script(
            root=root,
            ready_path=ready_path,
            release_path=tmp_path / "unused-release",
            abandon=True,
        ),
        encoding="utf-8",
    )
    process = subprocess.Popen(
        [powershell(), "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(holder)],
        cwd=REPO_ROOT,
        text=True,
    )
    assert process.wait(timeout=10) == 0
    assert ready_path.exists(), "abandoned mutex holder did not acquire the mutex"

    result = run_setup_script(
        ". "
        f"{powershell_literal(SETUP_SCRIPT)} "
        f"-QtPython {powershell_literal(Path(sys.executable))}; "
        "$mutex = Enter-PetToolchainPublishMutex "
        f"-Root {powershell_literal(root)} -TimeoutSeconds 2; "
        "try { 'abandoned-publish-mutex-recovered' } finally { $mutex.ReleaseMutex(); $mutex.Dispose() }"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "abandoned-publish-mutex-recovered" in result.stdout
    assert "abandoned" in (result.stdout + result.stderr).casefold()


def test_actual_pointer_publication_preserves_an_unrelated_fixed_tmp(
    tmp_path: Path,
) -> None:
    root = tmp_path / "tool-root"
    digest = "a" * 64
    temporary = root / f"current.json.tmp.{'b' * 32}"
    command = (
        ". "
        f"{powershell_literal(SETUP_SCRIPT)} "
        f"-QtPython {powershell_literal(Path(sys.executable))}; "
        f"$root = {powershell_literal(root)}; "
        f"$digest = '{digest}'; "
        "$version = Join-Path $root ('versions\\' + $digest); "
        "[System.IO.Directory]::CreateDirectory($version) | Out-Null; "
        "[System.IO.File]::WriteAllText((Join-Path $version 'installed.json'), ('{\"lockDigest\":\"' + $digest + '\"}')); "
        "[System.IO.File]::WriteAllText((Join-Path $root 'current.json.tmp'), 'foreign-temp'); "
        "Write-CurrentPointerAtomically -Root $root -LockDigest $digest "
        f"-TemporaryPath {powershell_literal(temporary)}; "
        "$pointer = Get-Content -Raw -LiteralPath (Join-Path $root 'current.json') | ConvertFrom-Json; "
        "if ($pointer.lockDigest -cne $digest -or $pointer.version -cne ('versions/' + $digest)) { throw 'pointer mismatch' }; "
        "if ((Get-Content -Raw -LiteralPath (Join-Path $root 'current.json.tmp')) -cne 'foreign-temp') { throw 'foreign fixed tmp changed' }; "
        f"if (Test-Path -LiteralPath {powershell_literal(temporary)}) {{ throw 'owned unique tmp remained' }}; "
        "'actual-pointer-published'"
    )

    result = run_setup_script(command)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "actual-pointer-published"


def qt_python_for_toolchain_contract() -> Path | None:
    candidates = (
        Path(sys.executable).resolve(),
        Path(
            r"C:\path\to\PySide6\python.exe"
        ),
    )
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def run_qt_webp_probe(
    interpreter: Path, image_path: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(interpreter), str(QT_VERIFY), str(image_path)],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=30,
        check=False,
    )


def test_verifier_is_read_only_by_contract() -> None:
    source = VERIFY_SCRIPT.read_text(encoding="utf-8").casefold()
    forbidden = (
        "invoke-webrequest",
        "pip install",
        "new-itemproperty",
        "set-itemproperty",
        "setenvironmentvariable",
        "current.json.tmp",
    )

    assert all(token not in source for token in forbidden)
    assert "pet toolchain verified" in source


def test_qt_probe_keeps_one_json_object_on_missing_webp(tmp_path: Path) -> None:
    interpreter = qt_python_for_toolchain_contract()
    if interpreter is None:
        pytest.skip("A PySide6-capable project interpreter is required")

    probe = run_qt_webp_probe(interpreter, tmp_path / "missing.webp")

    assert probe.returncode != 0
    assert len(probe.stdout.splitlines()) == 1
    assert json.loads(probe.stdout) == {
        "ok": False,
        "width": 0,
        "height": 0,
        "hasAlpha": False,
        "alphaMin": None,
        "alphaMax": None,
    }


def test_qt_probe_reports_real_transparent_webp_dimensions(tmp_path: Path) -> None:
    from PIL import Image

    interpreter = qt_python_for_toolchain_contract()
    if interpreter is None:
        pytest.skip("A PySide6-capable project interpreter is required")
    image_path = tmp_path / "transparent.webp"
    image = Image.new("RGBA", (7, 5), (16, 32, 64, 0))
    image.putpixel((3, 2), (240, 80, 20, 255))
    image.save(image_path, format="WEBP", lossless=True, exact=True)

    probe = run_qt_webp_probe(interpreter, image_path)

    assert probe.returncode == 0, probe.stdout + probe.stderr
    assert len(probe.stdout.splitlines()) == 1
    assert json.loads(probe.stdout) == {
        "ok": True,
        "width": 7,
        "height": 5,
        "hasAlpha": True,
        "alphaMin": 0,
        "alphaMax": 255,
    }


def test_qt_probe_rejects_a_webp_without_fully_transparent_pixels(tmp_path: Path) -> None:
    interpreter = qt_python_for_toolchain_contract()
    if interpreter is None:
        pytest.skip("A PySide6-capable project interpreter is required")
    image_path = tmp_path / "opaque.webp"
    created = subprocess.run(
        [
            str(interpreter),
            "-c",
            (
                "from PySide6.QtGui import QImage; import sys; "
                "image = QImage(7, 5, QImage.Format.Format_RGBA8888); "
                "image.fill(0xFF402010); "
                "raise SystemExit(0 if image.save(sys.argv[1], 'WEBP') else 1)"
            ),
            str(image_path),
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert created.returncode == 0, created.stdout + created.stderr

    probe = run_qt_webp_probe(interpreter, image_path)

    assert probe.returncode != 0
    assert len(probe.stdout.splitlines()) == 1
    assert json.loads(probe.stdout) == {
        "ok": True,
        "width": 7,
        "height": 5,
        "hasAlpha": True,
        "alphaMin": 255,
        "alphaMax": 255,
    }


def media_smoke_arguments(
    *,
    models_root: Path,
    ffmpeg: Path,
    ffprobe: Path,
    magick: Path,
    cwebp: Path,
    work_dir: Path,
    result_json: Path,
    numba_cache_dir: Path | None = None,
) -> list[str]:
    arguments = [
        "--models-root",
        str(models_root),
        "--ffmpeg",
        str(ffmpeg),
        "--ffprobe",
        str(ffprobe),
        "--magick",
        str(magick),
        "--cwebp",
        str(cwebp),
        "--work-dir",
        str(work_dir),
        "--result-json",
        str(result_json),
    ]
    if numba_cache_dir is not None:
        arguments.extend(["--numba-cache-dir", str(numba_cache_dir)])
    return arguments


def load_media_smoke_module() -> object:
    spec = importlib.util.spec_from_file_location("pet_media_smoke_contract", MEDIA_VERIFY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


def prepare_media_smoke_paths(tmp_path: Path) -> dict[str, Path]:
    models_root = tmp_path / "models"
    work_dir = tmp_path / "work"
    models_root.mkdir()
    for model_name in ("isnet-anime", "u2net_human_seg"):
        (models_root / f"{model_name}.onnx").write_bytes(b"fake-model")
    paths = {
        "models_root": models_root,
        "work_dir": work_dir,
        "result_json": work_dir / "result.json",
    }
    for tool_name in ("ffmpeg", "ffprobe", "magick", "cwebp"):
        tool_path = tmp_path / f"{tool_name}.exe"
        tool_path.write_bytes(b"fake-tool")
        paths[tool_name] = tool_path
    return paths


def configure_fake_media_runtime(
    module: object,
    monkeypatch: pytest.MonkeyPatch,
    command_log: list[list[str]],
    *,
    fail_cwebp: bool = False,
    one_frame_preview: bool = False,
    opaque_cutouts: bool = False,
    soft_cutouts: bool = False,
    include_ffprobe_format_duration: bool = True,
    duplicate_ffprobe_stream: bool = False,
    expected_numba_cache: Path | None = None,
    ffprobe_timestamps: tuple[str, ...] = (
        "0.000000",
        "0.100000",
        "0.200000",
        "0.300000",
    ),
) -> list[tuple[str, str]]:
    from PIL import Image, ImageDraw

    rembg_calls: list[tuple[str, str]] = []

    class FakeCv2:
        IMREAD_UNCHANGED = -1

        def imread(self, path: str, mode: int) -> object:
            assert Path(path).is_file()
            assert mode == self.IMREAD_UNCHANGED
            return type("FakeImage", (), {"shape": (256, 256, 4)})()

        @staticmethod
        def split(image: object) -> tuple[object, object, object, object]:
            assert image is not None
            return object(), object(), object(), object()

        @staticmethod
        def findNonZero(alpha: object) -> object:
            assert alpha is not None
            return object()

        @staticmethod
        def boundingRect(points: object) -> tuple[int, int, int, int]:
            assert points is not None
            return (0, 0, 256, 256)

    def fake_new_session(model_name: str) -> str:
        if expected_numba_cache is not None:
            assert os.environ.get("NUMBA_CACHE_DIR") == str(expected_numba_cache)
        rembg_calls.append(("new_session", model_name))
        return model_name

    def fake_remove(image: object, *, session: str) -> object:
        rembg_calls.append(("remove", session))
        output = image.copy()
        alpha = Image.new("L", output.size, 255 if opaque_cutouts else (15 if soft_cutouts else 0))
        if not opaque_cutouts:
            ImageDraw.Draw(alpha).ellipse((48, 24, 208, 240), fill=180 if soft_cutouts else 255)
        output.putalpha(alpha)
        return output

    def fake_run(
        arguments: list[str], *args: object, **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        command_log.append(arguments)
        executable = Path(arguments[0]).name.casefold()
        if executable == "cwebp.exe" and fail_cwebp:
            return subprocess.CompletedProcess(arguments, 7, "", "forced cwebp failure")
        if len(arguments) == 2 and arguments[1] == "-version":
            versions = {
                "ffmpeg.exe": "ffmpeg version 9.0.1",
                "ffprobe.exe": "ffprobe version 9.0.1",
                "magick.exe": "Version: ImageMagick 7.1.2-29 Q16 x64",
                "cwebp.exe": "1.6.0",
            }
            return subprocess.CompletedProcess(arguments, 0, versions[executable], "")
        if executable == "magick.exe":
            assert arguments[1:4] == [
                "identify",
                "-format",
                "%w|%h|%[channels]|%[opaque]",
            ]
            return subprocess.CompletedProcess(
                arguments, 0, "256|256|srgba 4.0|False", ""
            )
        if executable == "cwebp.exe":
            source = Path(arguments[arguments.index("-exact") + 1])
            destination = Path(arguments[arguments.index("-o") + 1])
            with Image.open(source) as cutout:
                cutout.save(destination, format="WEBP", lossless=True, exact=True)
            return subprocess.CompletedProcess(arguments, 0, "", "")
        if executable == "ffmpeg.exe":
            source = Path(arguments[arguments.index("-i") + 1])
            destination = Path(arguments[-1])
            if "-framerate" in arguments:
                frames = []
                for frame_number in range(1, 5):
                    with Image.open(Path(str(source).replace("%02d", f"{frame_number:02d}"))) as frame:
                        frames.append(frame.convert("RGBA"))
                if one_frame_preview:
                    frames = frames[:1]
                frames[0].save(
                    destination,
                    format="WEBP",
                    lossless=True,
                    exact=True,
                    save_all=True,
                    append_images=frames[1:],
                    duration=100,
                    loop=0,
                )
            else:
                with Image.open(source) as preview:
                    for frame_number in range(1, 5):
                        extracted = preview.convert("RGBA")
                        extracted.putpixel((frame_number - 1, 0), (frame_number * 40, 0, 0, 255))
                        extracted.save(
                            Path(str(destination).replace("%02d", f"{frame_number:02d}")),
                            format="PNG",
                        )
            return subprocess.CompletedProcess(arguments, 0, "", "")
        if executable == "ffprobe.exe":
            timestamps = ffprobe_timestamps[:1] if one_frame_preview else ffprobe_timestamps
            format_payload = {}
            if include_ffprobe_format_duration:
                format_payload["duration"] = "0.1" if one_frame_preview else "0.4"
            stream_payload = {
                "codec_type": "video",
                "width": 256,
                "height": 256,
                "nb_read_frames": "1" if one_frame_preview else "4",
            }
            payload = {
                "programs": [],
                "stream_groups": [],
                "frames": [
                    {"best_effort_timestamp_time": timestamp}
                    for timestamp in timestamps
                ],
                "streams": [stream_payload, *([stream_payload.copy()] if duplicate_ffprobe_stream else [])],
                "format": format_payload,
            }
            return subprocess.CompletedProcess(arguments, 0, json.dumps(payload), "")
        raise AssertionError(f"Unexpected external command: {arguments!r}")

    def fake_load_dependencies() -> tuple[object, object, object, object, object]:
        if expected_numba_cache is not None:
            assert os.environ.get("NUMBA_CACHE_DIR") == str(expected_numba_cache)
        return Image, ImageDraw, FakeCv2(), fake_new_session, fake_remove

    monkeypatch.setattr(module, "load_dependencies", fake_load_dependencies)
    monkeypatch.setattr(module, "run_external", fake_run)
    return rembg_calls


def test_verify_identify_accepts_locked_srgba_output_and_uses_delimited_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_media_smoke_module()
    magick = tmp_path / "locked-magick.exe"
    cutout = tmp_path / "cutout.png"
    observed: dict[str, object] = {}

    class IdentifyProcess:
        returncode = 0

        @staticmethod
        def communicate(*, timeout: int) -> tuple[str, str]:
            assert timeout == module.COMMAND_TIMEOUT_SECONDS
            return "256|256|srgba 4.0|False", ""

    def fake_popen(arguments: list[str], **kwargs: object) -> IdentifyProcess:
        observed["arguments"] = arguments
        observed["kwargs"] = kwargs
        return IdentifyProcess()

    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)

    module.verify_identify(magick, cutout)

    assert observed["arguments"] == [
        str(magick),
        "identify",
        "-format",
        "%w|%h|%[channels]|%[opaque]",
        str(cutout),
    ]
    assert observed["kwargs"] == {
        "shell": False,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    }


@pytest.mark.parametrize(
    "stdout",
    [
        "256|256|rgba 4.0|false",
        "256|256|srgba 4.0|false",
        "256|256|graya 2.0|false",
        "256|256|cmyka 5.0|false",
        " 256 | 256 | srgba 4.0 | FALSE \n",
    ],
    ids=("rgba", "locked-srgba", "graya", "cmyka", "padded-locked-srgba"),
)
def test_verify_identify_accepts_vetted_alpha_channel_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stdout: str
) -> None:
    module = load_media_smoke_module()

    def fake_run(arguments: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(arguments, 0, stdout, "")

    monkeypatch.setattr(module, "run_external", fake_run)

    module.verify_identify(tmp_path / "locked-magick.exe", tmp_path / "cutout.png")


def test_verify_identify_rejects_gray_channels_without_alpha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_media_smoke_module()

    def fake_run(arguments: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(arguments, 0, "256|256|gray 1.0|False", "")

    monkeypatch.setattr(module, "run_external", fake_run)

    with pytest.raises(module.VerificationError, match="preserve cutout alpha"):
        module.verify_identify(tmp_path / "locked-magick.exe", tmp_path / "cutout.png")


@pytest.mark.parametrize(
    "stdout",
    [
        "255|256|srgba 4.0|False",
        "256|255|srgba 4.0|False",
        "256|256|srgb 3.0|False",
        "256|256|srgba 4.0|True",
        "256|256|srgba 4.0",
        "256|256|srgba 4.0|False|unexpected",
        "256||srgba 4.0|False",
        "",
    ],
    ids=(
        "wrong-width",
        "wrong-height",
        "missing-alpha",
        "opaque",
        "missing-field",
        "extra-field",
        "empty-field",
        "empty-output",
    ),
)
def test_verify_identify_rejects_invalid_delimited_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stdout: str
) -> None:
    module = load_media_smoke_module()

    def fake_run(arguments: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(arguments, 0, stdout, "")

    monkeypatch.setattr(module, "run_external", fake_run)

    with pytest.raises(module.VerificationError):
        module.verify_identify(tmp_path / "locked-magick.exe", tmp_path / "cutout.png")


def test_media_source_is_an_opaque_high_contrast_portrait_on_a_near_white_background() -> None:
    from PIL import Image, ImageDraw

    module = load_media_smoke_module()

    source = module.make_source_image(Image, ImageDraw)

    assert source.mode == "RGBA"
    assert source.size == (module.IMAGE_SIZE, module.IMAGE_SIZE)
    assert source.getchannel("A").getextrema() == (255, 255)
    assert all(channel >= 235 for channel in source.getpixel((0, 0))[:3])
    assert min(source.getpixel((128, 35))[:3]) <= 64


def test_raw_model_alpha_rejects_an_isnet_like_low_confidence_mask_from_the_legacy_transparent_source() -> None:
    from PIL import Image, ImageDraw

    module = load_media_smoke_module()
    legacy_source = Image.new("RGBA", (module.IMAGE_SIZE, module.IMAGE_SIZE), (30, 42, 84, 0))
    legacy_draw = ImageDraw.Draw(legacy_source)
    legacy_draw.ellipse((44, 24, 212, 236), fill=(250, 210, 158, 255))
    legacy_cutout = legacy_source.copy()
    low_confidence_alpha = Image.new("L", legacy_cutout.size, 0)
    ImageDraw.Draw(low_confidence_alpha).ellipse((44, 24, 212, 236), fill=55)
    legacy_cutout.putalpha(low_confidence_alpha)

    with pytest.raises(module.VerificationError, match="high-alpha foreground"):
        module.validate_and_normalize_model_alpha(legacy_cutout)


def test_raw_model_alpha_normalizes_a_soft_meaningful_mask_to_exact_binary_endpoints() -> None:
    from PIL import Image

    module = load_media_smoke_module()
    soft_cutout = Image.new(
        "RGBA", (module.IMAGE_SIZE, module.IMAGE_SIZE), (236, 126, 154, 255)
    )
    soft_alpha = Image.new("L", soft_cutout.size, 128)
    for pixel_index in range(3277):
        soft_alpha.putpixel(
            (pixel_index % module.IMAGE_SIZE, pixel_index // module.IMAGE_SIZE), 16
        )
    soft_cutout.putalpha(soft_alpha)

    normalized, summary = module.validate_and_normalize_model_alpha(soft_cutout)
    repeated, repeated_summary = module.validate_and_normalize_model_alpha(soft_cutout)

    assert normalized.tobytes() == repeated.tobytes()
    assert summary == repeated_summary == {
        "minimum": 0,
        "maximum": 255,
        "transparentPixels": 3277,
        "opaquePixels": 62259,
    }
    assert module.alpha_summary(normalized) == summary
    assert normalized.getchannel("A").getextrema() == (0, 255)


@pytest.mark.parametrize(
    ("starting_alpha", "replacement_count", "replacement_alpha", "expected_error"),
    [
        (255, 0, 0, "low-alpha background"),
        (0, 0, 0, "high-alpha foreground"),
        (255, 3276, 0, "low-alpha background"),
        (0, 3276, 128, "high-alpha foreground"),
        (55, 0, 0, "low-alpha background"),
    ],
    ids=(
        "fully-opaque",
        "fully-transparent",
        "insufficient-background",
        "insufficient-foreground",
        "low-confidence",
    ),
)
def test_raw_model_alpha_rejects_unusable_masks(
    starting_alpha: int,
    replacement_count: int,
    replacement_alpha: int,
    expected_error: str,
) -> None:
    from PIL import Image

    module = load_media_smoke_module()
    cutout = Image.new("RGBA", (module.IMAGE_SIZE, module.IMAGE_SIZE), (236, 126, 154, 255))
    alpha = Image.new("L", cutout.size, starting_alpha)
    for pixel_index in range(replacement_count):
        alpha.putpixel(
            (pixel_index % module.IMAGE_SIZE, pixel_index // module.IMAGE_SIZE),
            replacement_alpha,
        )
    cutout.putalpha(alpha)

    with pytest.raises(module.VerificationError, match=expected_error):
        module.validate_and_normalize_model_alpha(cutout)


def test_raw_model_alpha_requires_an_alpha_channel() -> None:
    from PIL import Image

    module = load_media_smoke_module()

    with pytest.raises(module.VerificationError, match="alpha channel"):
        module.validate_and_normalize_model_alpha(
            Image.new("RGB", (module.IMAGE_SIZE, module.IMAGE_SIZE), (236, 126, 154))
        )


def test_media_helper_rejects_result_path_outside_work_dir(tmp_path: Path) -> None:
    paths = prepare_media_smoke_paths(tmp_path)
    outside_result = tmp_path / "outside-result.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(MEDIA_VERIFY),
            *media_smoke_arguments(
                models_root=paths["models_root"],
                ffmpeg=paths["ffmpeg"],
                ffprobe=paths["ffprobe"],
                magick=paths["magick"],
                cwebp=paths["cwebp"],
                work_dir=paths["work_dir"],
                result_json=outside_result,
            ),
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode != 0
    assert "result" in completed.stderr.casefold()
    assert not outside_result.exists()
    assert not paths["work_dir"].exists()


def test_media_helper_requires_a_new_private_work_directory(tmp_path: Path) -> None:
    paths = prepare_media_smoke_paths(tmp_path)
    paths["work_dir"].mkdir()

    completed = subprocess.run(
        [
            sys.executable,
            str(MEDIA_VERIFY),
            *media_smoke_arguments(
                models_root=paths["models_root"],
                ffmpeg=paths["ffmpeg"],
                ffprobe=paths["ffprobe"],
                magick=paths["magick"],
                cwebp=paths["cwebp"],
                work_dir=paths["work_dir"],
                result_json=paths["result_json"],
            ),
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode != 0
    assert "must not already exist" in completed.stderr.casefold()
    assert not list(paths["work_dir"].iterdir())


def create_windows_junction(link: Path, target: Path) -> None:
    created = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert created.returncode == 0, created.stdout + created.stderr
    assert link.exists() and link.is_dir()


def test_media_helper_rejects_a_junction_ancestor_before_creating_the_child(tmp_path: Path) -> None:
    paths = prepare_media_smoke_paths(tmp_path)
    target_parent = tmp_path / "junction-target"
    target_parent.mkdir()
    junction_parent = tmp_path / "junction-parent"
    work_dir = junction_parent / "must-not-be-created"
    result_json = work_dir / "result.json"
    create_windows_junction(junction_parent, target_parent)
    try:
        completed = subprocess.run(
            [
                sys.executable,
                str(MEDIA_VERIFY),
                *media_smoke_arguments(
                    models_root=paths["models_root"],
                    ffmpeg=paths["ffmpeg"],
                    ffprobe=paths["ffprobe"],
                    magick=paths["magick"],
                    cwebp=paths["cwebp"],
                    work_dir=work_dir,
                    result_json=result_json,
                ),
            ],
            cwd=REPO_ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=30,
            check=False,
        )

        assert completed.returncode != 0
        assert "reparse" in completed.stderr.casefold()
        assert not (target_parent / work_dir.name).exists()
        assert not (target_parent / work_dir.name / "result.json").exists()
    finally:
        if (target_parent / work_dir.name).exists():
            shutil.rmtree(target_parent / work_dir.name)
        if junction_parent.exists():
            os.rmdir(junction_parent)


def test_media_helper_rejects_a_preplaced_work_directory_symlink(tmp_path: Path) -> None:
    paths = prepare_media_smoke_paths(tmp_path)
    outside_directory = tmp_path / "outside"
    outside_directory.mkdir()
    try:
        paths["work_dir"].symlink_to(outside_directory, target_is_directory=True)
    except OSError as error:
        try:
            create_windows_junction(paths["work_dir"], outside_directory)
        except AssertionError as junction_error:
            raise AssertionError(
                f"Directory symlink and junction both unavailable: {error}; {junction_error}"
            ) from junction_error

    completed = subprocess.run(
        [
            sys.executable,
            str(MEDIA_VERIFY),
            *media_smoke_arguments(
                models_root=paths["models_root"],
                ffmpeg=paths["ffmpeg"],
                ffprobe=paths["ffprobe"],
                magick=paths["magick"],
                cwebp=paths["cwebp"],
                work_dir=paths["work_dir"],
                result_json=paths["result_json"],
            ),
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode != 0
    assert not list(outside_directory.iterdir())


def test_media_helper_runs_each_model_with_fake_tools_and_writes_json_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from PIL import Image

    module = load_media_smoke_module()
    paths = prepare_media_smoke_paths(tmp_path)
    command_log: list[list[str]] = []
    rembg_calls = configure_fake_media_runtime(
        module, monkeypatch, command_log, soft_cutouts=True
    )
    monkeypatch.delenv("U2NET_HOME", raising=False)

    exit_code = module.main(
        media_smoke_arguments(
            models_root=paths["models_root"],
            ffmpeg=paths["ffmpeg"],
            ffprobe=paths["ffprobe"],
            magick=paths["magick"],
            cwebp=paths["cwebp"],
            work_dir=paths["work_dir"],
            result_json=paths["result_json"],
        )
    )

    assert exit_code == 0
    stdout_lines = capsys.readouterr().out.splitlines()
    assert len(stdout_lines) == 1
    assert rembg_calls == [
        ("new_session", "isnet-anime"),
        ("remove", "isnet-anime"),
        ("new_session", "u2net_human_seg"),
        ("remove", "u2net_human_seg"),
    ]
    assert os.environ["U2NET_HOME"] == str(paths["models_root"])
    payload = json.loads(paths["result_json"].read_text(encoding="utf-8"))
    assert set(payload) == {"schemaVersion", "tools", "source", "models", "webp", "preview"}
    assert payload["schemaVersion"] == 1
    assert set(payload["tools"]) == {"ffmpeg", "ffprobe", "magick", "cwebp"}
    assert payload["source"] == {
        "width": 256,
        "height": 256,
        "opencvBounds": [0, 0, 256, 256],
    }
    assert set(payload["models"]) == set(module.MODEL_NAMES)
    for model_name in module.MODEL_NAMES:
        assert set(payload["models"][model_name]) == {"relativePath", "alpha"}
        assert payload["models"][model_name]["alpha"] == {
            "minimum": 0,
            "maximum": 255,
            "transparentPixels": 38119,
            "opaquePixels": 27417,
        }
    assert payload["webp"] == {
        "relativePath": "cutout-isnet-anime.webp",
        "width": 256,
        "height": 256,
        "hasAlpha": True,
        "alphaMin": 0,
        "alphaMax": 255,
    }
    assert payload["preview"] == {"frames": 4, "durationSeconds": 0.4}
    assert json.loads(stdout_lines[0])["webp"] == payload["webp"]
    for model_name in module.MODEL_NAMES:
        with Image.open(paths["work_dir"] / f"cutout-{model_name}.png") as persisted_cutout:
            assert module.alpha_summary(persisted_cutout.convert("RGBA")) == payload["models"][model_name]["alpha"]
    with Image.open(paths["work_dir"] / payload["webp"]["relativePath"]) as persisted_webp:
        assert module.alpha_summary(persisted_webp.convert("RGBA")) == payload["models"]["isnet-anime"]["alpha"]
    with Image.open(paths["work_dir"] / "preview.webp") as persisted_preview:
        assert persisted_preview.n_frames == 4
        for frame_number in range(persisted_preview.n_frames):
            persisted_preview.seek(frame_number)
            preview_alpha = module.alpha_summary(persisted_preview.copy().convert("RGBA"))
            assert preview_alpha["minimum"] == 0
            assert preview_alpha["maximum"] == 255
    assert any(command[0] == str(paths["magick"]) for command in command_log)
    assert any("-lossless" in command for command in command_log)
    assert any(command[0] == str(paths["ffprobe"]) for command in command_log)
    assert not list(paths["work_dir"].glob("*.tmp-*"))


def test_media_helper_accepts_locked_ffprobe_webp_timestamps_without_format_duration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_media_smoke_module()
    paths = prepare_media_smoke_paths(tmp_path)
    command_log: list[list[str]] = []
    configure_fake_media_runtime(
        module,
        monkeypatch,
        command_log,
        include_ffprobe_format_duration=False,
    )

    exit_code = module.main(
        media_smoke_arguments(
            models_root=paths["models_root"],
            ffmpeg=paths["ffmpeg"],
            ffprobe=paths["ffprobe"],
            magick=paths["magick"],
            cwebp=paths["cwebp"],
            work_dir=paths["work_dir"],
            result_json=paths["result_json"],
        )
    )

    assert exit_code == 0
    payload = json.loads(paths["result_json"].read_text(encoding="utf-8"))
    assert payload["preview"] == {"frames": 4, "durationSeconds": 0.4}
    ffprobe_command = next(
        command for command in command_log if Path(command[0]).name.casefold() == "ffprobe.exe"
    )
    assert ffprobe_command == [
        str(paths["ffprobe"]),
        "-v",
        "error",
        "-count_frames",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_type,width,height,nb_read_frames:frame=best_effort_timestamp_time",
        "-of",
        "json",
        str(paths["work_dir"] / "preview.webp"),
    ]


def test_media_helper_redirects_inherited_numba_cache_into_private_work_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_media_smoke_module()
    paths = prepare_media_smoke_paths(tmp_path)
    outside_cache = tmp_path / "outside-numba-cache"
    command_log: list[list[str]] = []
    monkeypatch.setenv("NUMBA_CACHE_DIR", str(outside_cache))
    configure_fake_media_runtime(
        module,
        monkeypatch,
        command_log,
        expected_numba_cache=paths["work_dir"] / "numba-cache",
    )

    exit_code = module.main(
        media_smoke_arguments(
            models_root=paths["models_root"],
            ffmpeg=paths["ffmpeg"],
            ffprobe=paths["ffprobe"],
            magick=paths["magick"],
            cwebp=paths["cwebp"],
            work_dir=paths["work_dir"],
            result_json=paths["result_json"],
        )
    )

    assert exit_code == 0
    assert os.environ["NUMBA_CACHE_DIR"] == str(paths["work_dir"] / "numba-cache")
    assert not outside_cache.exists()


def test_media_helper_uses_an_explicit_contained_sibling_numba_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_media_smoke_module()
    paths = prepare_media_smoke_paths(tmp_path)
    sibling_cache = tmp_path / "n"
    command_log: list[list[str]] = []
    configure_fake_media_runtime(
        module,
        monkeypatch,
        command_log,
        expected_numba_cache=sibling_cache,
    )

    exit_code = module.main(
        media_smoke_arguments(
            models_root=paths["models_root"],
            ffmpeg=paths["ffmpeg"],
            ffprobe=paths["ffprobe"],
            magick=paths["magick"],
            cwebp=paths["cwebp"],
            work_dir=paths["work_dir"],
            result_json=paths["result_json"],
            numba_cache_dir=sibling_cache,
        )
    )

    assert exit_code == 0
    assert os.environ["NUMBA_CACHE_DIR"] == str(sibling_cache)


def test_media_helper_rejects_an_explicit_numba_cache_outside_the_owned_workspace(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = load_media_smoke_module()
    paths = prepare_media_smoke_paths(tmp_path)
    outside_cache = tmp_path.parent / "outside-numba-cache"

    exit_code = module.main(
        media_smoke_arguments(
            models_root=paths["models_root"],
            ffmpeg=paths["ffmpeg"],
            ffprobe=paths["ffprobe"],
            magick=paths["magick"],
            cwebp=paths["cwebp"],
            work_dir=paths["work_dir"],
            result_json=paths["result_json"],
            numba_cache_dir=outside_cache,
        )
    )

    assert exit_code == 1
    assert "owned workspace sibling" in capsys.readouterr().err
    assert not outside_cache.exists()


def test_media_helper_rejects_a_preexisting_explicit_numba_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = load_media_smoke_module()
    paths = prepare_media_smoke_paths(tmp_path)
    sibling_cache = tmp_path / "n"
    sibling_cache.mkdir()
    sentinel = sibling_cache / "foreign.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    configure_fake_media_runtime(module, monkeypatch, [])

    exit_code = module.main(
        media_smoke_arguments(
            models_root=paths["models_root"],
            ffmpeg=paths["ffmpeg"],
            ffprobe=paths["ffprobe"],
            magick=paths["magick"],
            cwebp=paths["cwebp"],
            work_dir=paths["work_dir"],
            result_json=paths["result_json"],
            numba_cache_dir=sibling_cache,
        )
    )

    assert exit_code == 1
    assert "must be new" in capsys.readouterr().err
    assert sentinel.read_text(encoding="utf-8") == "preserve"


def test_sibling_numba_cache_keeps_observed_locked_temporary_paths_below_max_path() -> None:
    short_tool_root = Path("C:/generic/desktop-companion/DCPR-00000000")
    default_tool_root = (
        Path(os.environ["LOCALAPPDATA"])
        / "DesktopCompanionDev"
        / "pet-toolchain"
    )
    short_workspace = short_tool_root / "verify" / f"verify-{'0' * 32}"
    default_workspace = default_tool_root / "verify" / f"verify-{'0' * 32}"
    observed_longest_relative = Path(
        "foreground_7ae490adabd67a875187d1bac3e9724aa587038f"
    ) / "estimate_foreground_ml._resize_nearest_multichannel-5.py312.1.nbc"
    short_sibling_temporary = (
        str(short_workspace / "n" / observed_longest_relative)
        + f".tmp.{'0' * 16}"
    )
    default_sibling_temporary = (
        str(default_workspace / "n" / observed_longest_relative)
        + f".tmp.{'0' * 16}"
    )
    former_nested_temporary = (
        str(
            short_workspace
            / f"media-{'0' * 32}"
            / "numba-cache"
            / observed_longest_relative
        )
        + f".tmp.{'0' * 16}"
    )

    assert len(short_sibling_temporary) == 230
    assert len(former_nested_temporary) == 279
    assert len(short_sibling_temporary) < len(default_sibling_temporary) < 260
    assert 260 < len(former_nested_temporary)


def test_numba_cache_path_budget_accepts_259_and_rejects_260_characters() -> None:
    accepted_root = "C:\\" + ("a" * 68)
    rejected_root = "C:\\" + ("a" * 69)
    default_root = str(
        Path(os.environ["LOCALAPPDATA"])
        / "DesktopCompanionDev"
        / "pet-toolchain"
    )
    default_expected_length = len(
        str(
            Path(default_root)
            / "verify"
            / f"verify-{'0' * 32}"
            / "n"
            / "foreground_7ae490adabd67a875187d1bac3e9724aa587038f"
            / "estimate_foreground_ml._resize_nearest_multichannel-5.py312.1.nbc.tmp.0000000000000000"
        )
    )
    assert default_expected_length < 260
    command = (
        "$ErrorActionPreference = 'Stop'; "
        f". {powershell_literal(COMMON_SCRIPT)}; "
        f"$accepted = Assert-NumbaCachePathBudget -ToolRoot {powershell_literal(accepted_root)}; "
        "if ($accepted.Length -ne 259) { throw '259-character boundary was not accepted' }; "
        f"$default = Assert-NumbaCachePathBudget -ToolRoot {powershell_literal(default_root)}; "
        f"if ($default.Length -ne {default_expected_length}) {{ throw 'default root did not retain its path margin' }}; "
        "$failure = $null; try { "
        f"Assert-NumbaCachePathBudget -ToolRoot {powershell_literal(rejected_root)} | Out-Null "
        "} catch { $failure = $_ }; "
        "if ($null -eq $failure -or $failure.Exception.Message -notmatch 'path budget') { throw '260-character boundary was not rejected' }; "
        "'numba-path-budget-passed'"
    )
    result = run_setup_script(command)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "numba-path-budget-passed"
    setup_text = SETUP_SCRIPT.read_text(encoding="utf-8")
    verifier_text = VERIFY_SCRIPT.read_text(encoding="utf-8")
    assert "Assert-NumbaCachePathBudget -ToolRoot $canonicalToolRoot" in setup_text
    assert "Assert-NumbaCachePathBudget -ToolRoot $toolRootFull" in verifier_text


def test_verifier_starts_python_stages_isolated_with_clean_environments(
    tmp_path: Path,
) -> None:
    attacker_site = tmp_path / "attacker-site"
    attacker_site.mkdir()
    attacker_marker = tmp_path / "sitecustomize-ran.txt"
    outside_cache = tmp_path / "outside-numba-cache"
    media_workspace = tmp_path / "verify" / "media-0123456789abcdef0123456789abcdef"
    media_workspace.mkdir(parents=True)
    result_json = media_workspace / "result.json"
    probe_script = tmp_path / "media-probe.py"
    (attacker_site / "sitecustomize.py").write_text(
        "import os\n"
        "from pathlib import Path\n"
        "Path(os.environ['PET_MARKER']).write_text('startup injection ran')\n"
        "Path(os.environ['NUMBA_CACHE_DIR']).mkdir(parents=True, exist_ok=True)\n",
        encoding="utf-8",
    )
    probe_script.write_text(
        "import json, os, sys\n"
        "print(json.dumps({\n"
        "    'numba_cache': os.environ.get('NUMBA_CACHE_DIR'),\n"
        "    'pythonpath': os.environ.get('PYTHONPATH'),\n"
        "    'isolated': sys.flags.isolated,\n"
        "    'dont_write_bytecode': sys.dont_write_bytecode,\n"
        "    'argv': sys.argv[1:],\n"
        "}))\n",
        encoding="utf-8",
    )
    expected_cache = media_workspace.parent / "n"

    command = (
        "$ErrorActionPreference = 'Stop'; "
        f". {powershell_literal(VERIFY_SCRIPT)} -QtPython {powershell_literal(Path(sys.executable))}; "
        f"$env:PYTHONPATH = {powershell_literal(attacker_site)}; "
        f"$env:PET_MARKER = {powershell_literal(attacker_marker)}; "
        f"$env:NUMBA_CACHE_DIR = {powershell_literal(outside_cache)}; "
        "$tools = [ordered]@{ ffmpeg = 'C:\\locked\\ffmpeg.exe'; imagemagick = 'C:\\locked\\magick.exe'; libwebp = 'C:\\locked\\cwebp.exe' }; "
        "$details = Invoke-MediaVerificationProcess "
        f"-PythonPath {powershell_literal(Path(sys.executable))} "
        f"-MediaScript {powershell_literal(probe_script)} "
        "-ModelsRoot 'C:\\locked\\models' -ToolPaths $tools -FfprobePath 'C:\\locked\\ffprobe.exe' "
        f"-WorkspaceRoot {powershell_literal(media_workspace.parent)} -WorkDir {powershell_literal(media_workspace)} -ResultJson {powershell_literal(result_json)}; "
        "$state = $details.StdOut | ConvertFrom-Json; "
        f"if ($state.numba_cache -cne {powershell_literal(expected_cache)}) {{ throw 'private Numba cache was not injected before startup' }}; "
        "if ($null -ne $state.pythonpath) { throw 'media Python inherited PYTHONPATH' }; "
        "if ([int]$state.isolated -ne 1 -or -not [bool]$state.dont_write_bytecode) { throw 'media Python flags were not isolated and bytecode-free' }; "
        "$cacheArgument = [array]::IndexOf([string[]]$state.argv, '--numba-cache-dir'); "
        f"if ($cacheArgument -lt 0 -or $state.argv[$cacheArgument + 1] -cne {powershell_literal(expected_cache)}) {{ throw 'media Python omitted the explicit sibling cache argument' }}; "
        "'isolated-media-python-passed'"
    )
    result = run_setup_script(command)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "isolated-media-python-passed"
    assert not attacker_marker.exists()
    assert not outside_cache.exists()

    flag_code = (
        "import json, sys; "
        "print(json.dumps({'ignore_environment': sys.flags.ignore_environment, "
        "'dont_write_bytecode': sys.dont_write_bytecode}))"
    )
    flag_probe = run_common_script(
        "$ErrorActionPreference = 'Stop'; "
        f". {powershell_literal(VERIFY_SCRIPT)} -QtPython {powershell_literal(Path(sys.executable))}; "
        "$details = Invoke-CheckedProcess "
        f"-FilePath {powershell_literal(Path(sys.executable))} "
        f"-ArgumentList @('-I', '-B', '-c', {powershell_literal(flag_code)}) "
        "-TimeoutSeconds 60 -Environment @{ PYTHONDONTWRITEBYTECODE = '1' } -CleanEnvironment; "
        "$details.StdOut",
        environment={
            "PYTHONPATH": str(attacker_site),
            "PYTHONDONTWRITEBYTECODE": "0",
        },
    )

    assert flag_probe.returncode == 0, flag_probe.stdout + flag_probe.stderr
    assert json.loads(flag_probe.stdout) == {
        "ignore_environment": 1,
        "dont_write_bytecode": True,
    }

    freeze_probe = run_common_script(
        "$ErrorActionPreference = 'Stop'; "
        f". {powershell_literal(VERIFY_SCRIPT)} -QtPython {powershell_literal(Path(sys.executable))}; "
        f"$expectedPython = {powershell_literal(Path(sys.executable))}; "
        f"$expectedQtScript = {powershell_literal(tmp_path / 'verify-qt.py')}; "
        f"$expectedWebp = {powershell_literal(tmp_path / 'preview.webp')}; "
        "$script:freezeSeen = $false; "
        "$script:qtSeen = $false; "
        "function Invoke-CheckedProcess { "
        "param($FilePath, [string[]]$ArgumentList, [int]$TimeoutSeconds, [hashtable]$Environment = @{}, [switch]$CleanEnvironment); "
        "if ($FilePath -cne $expectedPython -or -not [System.IO.Path]::IsPathRooted($FilePath)) { throw 'verifier did not use the absolute supplied Python' }; "
        "if (-not $CleanEnvironment) { throw 'verifier Python stage was not clean' }; "
        "if ($ArgumentList -contains 'freeze') { "
        "$expectedArguments = @('-I', '-B', '-m', 'pip', '--isolated', 'freeze', '--all'); "
        "if (($ArgumentList -join [char]0) -cne ($expectedArguments -join [char]0)) { throw 'candidate freeze was not Python/pip isolated and bytecode-free' }; "
        "if ($TimeoutSeconds -ne 120) { throw 'candidate freeze timeout changed' }; "
        "if ($Environment.PYTHONDONTWRITEBYTECODE -cne '1' -or $Environment.Count -ne 1) { throw 'candidate freeze safe environment changed' }; "
        "$script:freezeSeen = $true; "
        "return [pscustomobject]@{ ExitCode = 0; StdOut = 'example==1'; StdErr = '' } }; "
        "if ($ArgumentList -contains $expectedQtScript) { "
        "$expectedArguments = @('-I', '-B', $expectedQtScript, $expectedWebp); "
        "if (($ArgumentList -join [char]0) -cne ($expectedArguments -join [char]0)) { throw 'Qt Python was not isolated and bytecode-free' }; "
        "if ($TimeoutSeconds -ne 60 -or $Environment.Count -ne 0) { throw 'Qt Python process contract changed' }; "
        "$script:qtSeen = $true; "
        "return [pscustomobject]@{ ExitCode = 0; StdOut = '{\"ok\":true}'; StdErr = '' } }; "
        "$expectedArguments = @('-I', '-B', '--version'); "
        "if (($ArgumentList -join [char]0) -cne ($expectedArguments -join [char]0)) { throw 'candidate version probe was not Python isolated and bytecode-free' }; "
        "if ($TimeoutSeconds -ne 60 -or $Environment.PYTHONDONTWRITEBYTECODE -cne '1' -or $Environment.Count -ne 1) { throw 'candidate version process contract changed' }; "
        "return [pscustomobject]@{ ExitCode = 0; StdOut = 'Python 3.12.10'; StdErr = '' } "
        "}; "
        "Assert-PythonEnvironment -PythonPath $expectedPython -ExpectedFreeze @('example==1') "
        "-RuntimeVersion 'Python 3.12.10' -VersionRegex '^Python 3\\.12\\.\\d+$'; "
        "if (-not $script:freezeSeen) { throw 'candidate freeze probe was skipped' }; "
        "$qt = Invoke-QtVerificationProcess -PythonPath $expectedPython -QtScript $expectedQtScript -WebpPath $expectedWebp; "
        "if (-not $script:qtSeen -or $qt.StdOut -cne '{\"ok\":true}') { throw 'Qt Python result contract changed' }; "
        "'isolated-verifier-python-stages-passed'",
        environment={
            "PYTHONPATH": str(attacker_site),
            "PIP_TARGET": str(tmp_path / "outside-pip-target"),
            "PIP_CONFIG_FILE": str(tmp_path / "attacker-pip.ini"),
        },
    )

    assert freeze_probe.returncode == 0, freeze_probe.stdout + freeze_probe.stderr
    assert freeze_probe.stdout.strip() == "isolated-verifier-python-stages-passed"


@pytest.mark.parametrize(
    ("ffprobe_timestamps", "expected_duration"),
    [
        (("0.000000", "0.075000", "0.150000", "0.225000"), 0.325),
        (("0.000000", "0.110000", "0.220000", "0.330000"), 0.43),
        (("0.000000", "0.125000", "0.250000", "0.375000"), 0.475),
    ],
)
def test_media_helper_accepts_symmetric_ffprobe_timing_tolerance_boundaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ffprobe_timestamps: tuple[str, ...],
    expected_duration: float,
) -> None:
    module = load_media_smoke_module()
    paths = prepare_media_smoke_paths(tmp_path)
    command_log: list[list[str]] = []
    configure_fake_media_runtime(
        module,
        monkeypatch,
        command_log,
        include_ffprobe_format_duration=False,
        ffprobe_timestamps=ffprobe_timestamps,
    )

    exit_code = module.main(
        media_smoke_arguments(
            models_root=paths["models_root"],
            ffmpeg=paths["ffmpeg"],
            ffprobe=paths["ffprobe"],
            magick=paths["magick"],
            cwebp=paths["cwebp"],
            work_dir=paths["work_dir"],
            result_json=paths["result_json"],
        )
    )

    assert exit_code == 0
    payload = json.loads(paths["result_json"].read_text(encoding="utf-8"))
    assert payload["preview"] == {
        "frames": 4,
        "durationSeconds": expected_duration,
    }


def test_media_helper_rejects_irregular_ffprobe_timestamps_even_with_legacy_duration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_media_smoke_module()
    paths = prepare_media_smoke_paths(tmp_path)
    command_log: list[list[str]] = []
    configure_fake_media_runtime(
        module,
        monkeypatch,
        command_log,
        ffprobe_timestamps=("0.000000", "0.050000", "0.200000", "0.300000"),
    )

    exit_code = module.main(
        media_smoke_arguments(
            models_root=paths["models_root"],
            ffmpeg=paths["ffmpeg"],
            ffprobe=paths["ffprobe"],
            magick=paths["magick"],
            cwebp=paths["cwebp"],
            work_dir=paths["work_dir"],
            result_json=paths["result_json"],
        )
    )

    assert exit_code != 0
    assert not paths["result_json"].exists()


def test_media_helper_rejects_duplicate_matching_ffprobe_streams(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_media_smoke_module()
    paths = prepare_media_smoke_paths(tmp_path)
    command_log: list[list[str]] = []
    configure_fake_media_runtime(
        module,
        monkeypatch,
        command_log,
        duplicate_ffprobe_stream=True,
    )

    exit_code = module.main(
        media_smoke_arguments(
            models_root=paths["models_root"],
            ffmpeg=paths["ffmpeg"],
            ffprobe=paths["ffprobe"],
            magick=paths["magick"],
            cwebp=paths["cwebp"],
            work_dir=paths["work_dir"],
            result_json=paths["result_json"],
        )
    )

    assert exit_code != 0
    assert not paths["result_json"].exists()


def test_media_helper_rejects_a_one_frame_preview(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_media_smoke_module()
    paths = prepare_media_smoke_paths(tmp_path)
    command_log: list[list[str]] = []
    configure_fake_media_runtime(module, monkeypatch, command_log, one_frame_preview=True)

    exit_code = module.main(
        media_smoke_arguments(
            models_root=paths["models_root"],
            ffmpeg=paths["ffmpeg"],
            ffprobe=paths["ffprobe"],
            magick=paths["magick"],
            cwebp=paths["cwebp"],
            work_dir=paths["work_dir"],
            result_json=paths["result_json"],
        )
    )

    assert exit_code != 0
    assert not paths["result_json"].exists()


def test_media_helper_rejects_cutouts_without_meaningful_transparency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_media_smoke_module()
    paths = prepare_media_smoke_paths(tmp_path)
    command_log: list[list[str]] = []
    configure_fake_media_runtime(module, monkeypatch, command_log, opaque_cutouts=True)

    exit_code = module.main(
        media_smoke_arguments(
            models_root=paths["models_root"],
            ffmpeg=paths["ffmpeg"],
            ffprobe=paths["ffprobe"],
            magick=paths["magick"],
            cwebp=paths["cwebp"],
            work_dir=paths["work_dir"],
            result_json=paths["result_json"],
        )
    )

    assert exit_code != 0
    assert not paths["result_json"].exists()


def test_media_helper_wraps_subprocess_timeouts_without_a_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_media_smoke_module()

    class TimedOutProcess:
        pid = 12345
        returncode = 0

        def communicate(self, *, timeout: int) -> tuple[str, str]:
            raise subprocess.TimeoutExpired(
                ["fake-tool"], timeout, output="x" * 4096, stderr="y" * 4096
            )

    monkeypatch.setattr(module.subprocess, "Popen", lambda *args, **kwargs: TimedOutProcess())
    monkeypatch.setattr(module, "terminate_process_tree", lambda process: None)

    with pytest.raises(module.VerificationError, match="timed out") as failure:
        module.run_external(["fake-tool"])

    assert "Traceback" not in str(failure.value)
    assert len(str(failure.value)) < 1024


def test_media_helper_does_not_publish_result_after_a_fake_tool_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_media_smoke_module()
    paths = prepare_media_smoke_paths(tmp_path)
    command_log: list[list[str]] = []
    configure_fake_media_runtime(module, monkeypatch, command_log, fail_cwebp=True)

    exit_code = module.main(
        media_smoke_arguments(
            models_root=paths["models_root"],
            ffmpeg=paths["ffmpeg"],
            ffprobe=paths["ffprobe"],
            magick=paths["magick"],
            cwebp=paths["cwebp"],
            work_dir=paths["work_dir"],
            result_json=paths["result_json"],
        )
    )

    assert exit_code != 0
    assert not paths["result_json"].exists()
    assert any(command[0] == str(paths["cwebp"]) for command in command_log)


def run_installed_toolchain_verifier(
    *, tool_root: Path, candidate_root: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            powershell(),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(VERIFY_SCRIPT),
            "-ToolRoot",
            str(tool_root),
            "-CandidateRoot",
            str(candidate_root),
            "-NoCurrentPointer",
            "-QtPython",
            str(sys.executable),
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=30,
        check=False,
    )


def test_verifier_rejects_an_outside_candidate_without_reading_current(
    tmp_path: Path,
) -> None:
    tool_root = tmp_path / "tool-root"
    outside_candidate = tmp_path / "outside-candidate"
    tool_root.mkdir()
    outside_candidate.mkdir()
    current_path = tool_root / "current.json"
    original_pointer = b"not-json-and-not-to-be-read"
    current_path.write_bytes(original_pointer)

    completed = run_installed_toolchain_verifier(
        tool_root=tool_root, candidate_root=outside_candidate
    )

    assert completed.returncode != 0
    assert "candidate" in (completed.stdout + completed.stderr).casefold()
    assert current_path.read_bytes() == original_pointer
    assert sorted(path.name for path in tool_root.iterdir()) == ["current.json"]


def verifier_manifest(lock_digest: str) -> dict[str, object]:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    return {
        "lockDigest": lock_digest,
        "assets": {
            "extractor": {
                "sha256": lock["extractor"]["sha256"],
                "size": lock["extractor"]["size"],
            },
            "tools": {
                tool_name: {
                    "sha256": lock["tools"][tool_name]["sha256"],
                    "size": lock["tools"][tool_name]["size"],
                }
                for tool_name in ("ffmpeg", "imagemagick", "libwebp")
            },
            "models": {
                model_name: {
                    "sha256": lock["models"][model_name]["sha256"],
                    "size": lock["models"][model_name]["size"],
                }
                for model_name in ("isnet-anime", "u2net_human_seg")
            },
        },
        "python": {
            "interpreter": "python/Scripts/python.exe",
            "freeze": [],
            "fileCount": 1,
            "treeSha256": "0" * 64,
            "runtimeVersion": "Python 3.12.10",
            "runtimePublisher": "CN=Python Software Foundation, O=Python Software Foundation, L=Beaverton, S=Oregon, C=US",
        },
        "entrypoints": {
            "tools": {
                "ffmpeg": "tools/ffmpeg/bin/ffmpeg.exe",
                "imagemagick": "tools/imagemagick/magick.exe",
                "libwebp": "tools/libwebp/bin/cwebp.exe",
            },
            "models": {
                model_name: lock["models"][model_name]["entrypoint"]
                for model_name in ("isnet-anime", "u2net_human_seg")
            },
        },
    }


def test_verifier_rejects_absolute_manifest_entrypoints_without_workspace_write(
    tmp_path: Path,
) -> None:
    tool_root = tmp_path / "tool-root"
    candidate_root = tool_root / "staging-candidate"
    candidate_root.mkdir(parents=True)
    lock_digest = hashlib.sha256(LOCK_PATH.read_bytes() + MEDIA_LOCK.read_bytes()).hexdigest()
    manifest = verifier_manifest(lock_digest)
    manifest["entrypoints"]["tools"]["ffmpeg"] = str(tmp_path / "outside.exe")
    installed_path = candidate_root / "installed.json"
    installed_path.write_text(json.dumps(manifest), encoding="utf-8")
    before_paths = sorted(
        path.relative_to(tool_root).as_posix() for path in tool_root.rglob("*")
    )
    before_bytes = installed_path.read_bytes()

    completed = run_installed_toolchain_verifier(
        tool_root=tool_root, candidate_root=candidate_root
    )

    assert completed.returncode != 0
    assert "path escapes tool root" in (completed.stdout + completed.stderr).casefold()
    assert installed_path.read_bytes() == before_bytes
    assert sorted(
        path.relative_to(tool_root).as_posix() for path in tool_root.rglob("*")
    ) == before_paths


@pytest.mark.parametrize(
    "payload",
    (
        "\ufeff{\"ok\":true}",
        "{\"ok\":true} trailing-log",
        "{\"ok\":true,\"ok\":false}",
        "{/*comment*/\"ok\":true}",
        "{\"ok\":NaN}",
        "{\"ok\":Infinity}",
    ),
)
def test_verifier_rejects_noncanonical_single_json_object(payload: str) -> None:
    result = run_setup_script(
        "$ErrorActionPreference = 'Stop'; "
        f". {powershell_literal(VERIFY_SCRIPT)} -QtPython {powershell_literal(Path(sys.executable))}; "
        f"$payload = {powershell_literal(payload)}; "
        "$failure = $null; try { ConvertFrom-ExactlyOneJsonObject -StdOut $payload -Context 'test JSON' } catch { $failure = $_ }; "
        "if ($null -eq $failure) { throw 'noncanonical JSON was accepted' }; "
        "'noncanonical-json-rejected'"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "noncanonical-json-rejected"


@pytest.mark.parametrize(
    ("context", "stdout", "stderr", "version_regex", "expected_match", "clean_environment"),
    [
        (
            "FFmpeg",
            "ffmpeg version 9.0.1\r\n",
            "",
            r"^ffmpeg version 9\.0\.1$",
            "ffmpeg version 9.0.1",
            False,
        ),
        (
            "ffprobe",
            "",
            "ffprobe version 9.0.1\r",
            r"^ffprobe version 9\.0\.1$",
            "ffprobe version 9.0.1",
            False,
        ),
        (
            "ImageMagick",
            "\r\nImageMagick 7.1.2-29\r\n",
            "",
            r"^ImageMagick 7\.1\.2-29$",
            "ImageMagick 7.1.2-29",
            False,
        ),
        (
            "cwebp",
            "",
            "cwebp 1.6.0\r",
            r"^cwebp 1\.6\.0$",
            "cwebp 1.6.0",
            False,
        ),
        (
            "Python runtime",
            "Python 3.12.10\r\n",
            "",
            r"^Python 3\.12\.\d+$",
            "Python 3.12.10",
            True,
        ),
    ],
)
def test_verifier_version_gate_normalizes_crlf_and_lone_cr_and_returns_match(
    context: str,
    stdout: str,
    stderr: str,
    version_regex: str,
    expected_match: str,
    clean_environment: bool,
) -> None:
    clean_argument = " -CleanEnvironment" if clean_environment else ""
    result = run_setup_script(
        "$ErrorActionPreference = 'Stop'; "
        f". {powershell_literal(VERIFY_SCRIPT)} -QtPython {powershell_literal(Path(sys.executable))}; "
        f"$expectedClean = {'$true' if clean_environment else '$false'}; "
        "function Invoke-CheckedProcess { "
        "param($FilePath, [string[]]$ArgumentList, [int]$TimeoutSeconds, [hashtable]$Environment, [switch]$CleanEnvironment); "
        "if ($CleanEnvironment.IsPresent -ne $expectedClean) { throw 'clean environment was not preserved' }; "
        f"return [pscustomobject]@{{ ExitCode = 0; StdOut = {powershell_literal(stdout)}; StdErr = {powershell_literal(stderr)} }} "
        "}; "
        "$matched = Assert-VersionOutput "
        "-Path 'C:\\locked\\tool.exe' -ArgumentList @('--version') "
        f"-VersionRegex {powershell_literal(version_regex)} -Context {powershell_literal(context)}{clean_argument}; "
        f"if ($matched -cne {powershell_literal(expected_match)}) {{ throw ('unexpected matched version: ' + $matched) }}; "
        "'verifier-version-output-normalized'"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "verifier-version-output-normalized"


def test_verifier_version_gate_keeps_contextual_mismatch_error() -> None:
    result = run_setup_script(
        "$ErrorActionPreference = 'Stop'; "
        f". {powershell_literal(VERIFY_SCRIPT)} -QtPython {powershell_literal(Path(sys.executable))}; "
        "function Invoke-CheckedProcess { "
        "param($FilePath, [string[]]$ArgumentList, [int]$TimeoutSeconds, [hashtable]$Environment, [switch]$CleanEnvironment); "
        "return [pscustomobject]@{ ExitCode = 0; StdOut = 'ffmpeg version 8.9.0'; StdErr = '' } "
        "}; "
        "$failure = $null; try { Assert-VersionOutput -Path 'C:\\locked\\ffmpeg.exe' -ArgumentList @('-version') "
        "-VersionRegex '^ffmpeg version 9\\.0\\.1$' -Context 'FFmpeg' | Out-Null } catch { $failure = $_ }; "
        "if ($null -eq $failure -or $failure.Exception.Message -cne 'FFmpeg did not report the locked version: C:\\locked\\ffmpeg.exe') { "
        "throw 'version mismatch lost its contextual error' }; "
        "'verifier-version-mismatch-rejected'"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "verifier-version-mismatch-rejected"


def test_verifier_requires_an_exact_tool_inventory_before_execution(tmp_path: Path) -> None:
    tool_directory = tmp_path / "candidate" / "tools" / "ffmpeg"
    tool_directory.mkdir(parents=True)
    expected_file = tool_directory / "bin" / "ffmpeg.exe"
    expected_file.parent.mkdir()
    expected_file.write_bytes(b"expected tool bytes")
    (tool_directory / "unexpected.txt").write_text("unexpected", encoding="utf-8")
    sha256 = hashlib.sha256(expected_file.read_bytes()).hexdigest()
    inventory_json = json.dumps(
        {"installedFiles": {"bin/ffmpeg.exe": {"size": expected_file.stat().st_size, "sha256": sha256}}}
    )

    result = run_setup_script(
        "$ErrorActionPreference = 'Stop'; "
        f". {powershell_literal(VERIFY_SCRIPT)} -QtPython {powershell_literal(Path(sys.executable))}; "
        f"$tool = {powershell_literal(inventory_json)} | ConvertFrom-Json; "
        f"$root = {powershell_literal(tool_directory)}; "
        "$failure = $null; try { Assert-InstalledToolInventory -ToolRoot $root -Tool $tool -Context 'FFmpeg' } catch { $failure = $_ }; "
        "if ($null -eq $failure -or $failure.Exception.Message -notmatch 'unexpected') { throw 'unlocked file was accepted' }; "
        "'inventory-rejected-before-execution'"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "inventory-rejected-before-execution"


def test_verifier_uses_an_alternate_tool_root_only_when_explicitly_passed(tmp_path: Path) -> None:
    alternate_root = tmp_path / "alternate-root"
    candidate_root = alternate_root / "staging-0123456789abcdef0123456789abcdef"
    candidate_root.mkdir(parents=True)
    implicit = subprocess.run(
        [
            powershell(), "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(VERIFY_SCRIPT),
            "-CandidateRoot", str(candidate_root), "-NoCurrentPointer", "-QtPython", str(sys.executable),
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=30,
        check=False,
    )
    explicit = run_installed_toolchain_verifier(tool_root=alternate_root, candidate_root=candidate_root)

    assert implicit.returncode != 0
    assert "candidate path escapes tool root" in (implicit.stdout + implicit.stderr).casefold()
    assert explicit.returncode != 0
    assert "candidate path escapes tool root" not in (explicit.stdout + explicit.stderr).casefold()


def test_verifier_rejects_a_current_pointer_for_a_different_digest_before_candidate_execution(
    tmp_path: Path,
) -> None:
    tool_root = tmp_path / "tool-root"
    actual_digest = hashlib.sha256(LOCK_PATH.read_bytes() + MEDIA_LOCK.read_bytes()).hexdigest()
    wrong_digest = "0" * 64
    candidate = tool_root / "versions" / wrong_digest
    candidate.mkdir(parents=True)
    current_path = tool_root / "current.json"
    current_path.write_text(
        json.dumps({"lockDigest": actual_digest, "version": f"versions/{wrong_digest}"}),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            powershell(),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(VERIFY_SCRIPT),
            "-ToolRoot",
            str(tool_root),
            "-QtPython",
            str(sys.executable),
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode != 0
    assert "current pointer version" in (completed.stdout + completed.stderr).casefold()
    assert not (candidate / "installed.json").exists()
    assert current_path.read_bytes() == json.dumps(
        {"lockDigest": actual_digest, "version": f"versions/{wrong_digest}"}
    ).encode("utf-8")


def test_verifier_cleanup_stops_on_a_locked_owned_output_without_touching_siblings(
    tmp_path: Path,
) -> None:
    tool_root = tmp_path / "tool-root"
    verify_root = tool_root / "verify"
    workspace = verify_root / "verify-0123456789abcdef0123456789abcdef"
    media_workspace = workspace / "media-0123456789abcdef0123456789abcdef"
    media_workspace.mkdir(parents=True)
    locked_result = media_workspace / "result.json"
    locked_result.write_text("locked", encoding="utf-8")
    sibling = verify_root / "foreign-sibling.txt"
    sibling.write_text("preserve", encoding="utf-8")
    result = run_setup_script(
        "$ErrorActionPreference = 'Stop'; "
        f". {powershell_literal(VERIFY_SCRIPT)} -QtPython {powershell_literal(Path(sys.executable))}; "
        f"$verify = {powershell_literal(verify_root)}; "
        f"$workspace = {powershell_literal(workspace)}; "
        f"$media = {powershell_literal(media_workspace)}; "
        f"$locked = {powershell_literal(locked_result)}; "
        "$handle = [System.IO.File]::Open($locked, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::None); "
        "try { $failure = $null; try { Remove-VerificationWorkspace -VerifyRoot $verify -Workspace $workspace -MediaWorkspace $media } catch { $failure = $_ }; "
        "if ($null -eq $failure) { throw 'locked cleanup unexpectedly succeeded' }; "
        "if (-not (Test-Path -LiteralPath $workspace)) { throw 'locked cleanup deleted its workspace' }; "
        "'locked-cleanup-blocked' } finally { $handle.Dispose() }"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "locked-cleanup-blocked"
    assert sibling.read_text(encoding="utf-8") == "preserve"


def test_verifier_cleanup_rejects_an_unknown_empty_directory_without_touching_siblings(
    tmp_path: Path,
) -> None:
    tool_root = tmp_path / "tool-root"
    verify_root = tool_root / "verify"
    workspace = verify_root / "verify-0123456789abcdef0123456789abcdef"
    media_workspace = workspace / "media-0123456789abcdef0123456789abcdef"
    unknown_directory = media_workspace / "unexpected-empty-directory"
    unknown_directory.mkdir(parents=True)
    sibling = verify_root / "foreign-sibling.txt"
    sibling.write_text("preserve", encoding="utf-8")
    result = run_setup_script(
        "$ErrorActionPreference = 'Stop'; "
        f". {powershell_literal(VERIFY_SCRIPT)} -QtPython {powershell_literal(Path(sys.executable))}; "
        f"$verify = {powershell_literal(verify_root)}; "
        f"$workspace = {powershell_literal(workspace)}; "
        f"$media = {powershell_literal(media_workspace)}; "
        "$failure = $null; try { Remove-VerificationWorkspace -VerifyRoot $verify -Workspace $workspace -MediaWorkspace $media } catch { $failure = $_ }; "
        "if ($null -eq $failure) { throw 'unknown empty directory was removed' }; "
        "if (-not (Test-Path -LiteralPath $workspace)) { throw 'unknown-directory cleanup deleted its workspace' }; "
        "if (-not (Test-Path -LiteralPath (Join-Path $media 'unexpected-empty-directory'))) { throw 'unknown directory was deleted' }; "
        "'unknown-directory-cleanup-blocked'"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "unknown-directory-cleanup-blocked"
    assert "PET TOOLCHAIN VERIFIED" not in result.stdout
    assert sibling.read_text(encoding="utf-8") == "preserve"


def test_verifier_cleanup_accepts_only_completed_numba_cache_outputs(
    short_local_tmp_path: Path,
) -> None:
    tool_root = short_local_tmp_path / "tool-root"
    verify_root = tool_root / "verify"
    workspace = verify_root / "verify-0123456789abcdef0123456789abcdef"
    media_workspace = workspace / "media-0123456789abcdef0123456789abcdef"
    numba_module_cache = (
        workspace
        / "n"
        / "alpha_16722395fe3807967f9d89cb1b2b24b5deb292f4"
    )
    numba_module_cache.mkdir(parents=True)
    (numba_module_cache / "estimate_alpha_sm.inner-185.py312.nbi").write_bytes(
        b"numba index"
    )
    (numba_module_cache / "estimate_alpha_sm.inner-185.py312.1.nbc").write_bytes(
        b"numba code"
    )
    sibling = verify_root / "foreign-sibling.txt"
    sibling.write_text("preserve", encoding="utf-8")

    result = run_setup_script(
        "$ErrorActionPreference = 'Stop'; "
        f". {powershell_literal(VERIFY_SCRIPT)} -QtPython {powershell_literal(Path(sys.executable))}; "
        f"$verify = {powershell_literal(verify_root)}; "
        f"$workspace = {powershell_literal(workspace)}; "
        f"$media = {powershell_literal(media_workspace)}; "
        "Remove-VerificationWorkspace -VerifyRoot $verify -Workspace $workspace -MediaWorkspace $media; "
        "if (Test-Path -LiteralPath $workspace) { throw 'owned Numba cache workspace survived cleanup' }; "
        "'owned-numba-cache-cleaned'"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "owned-numba-cache-cleaned"
    assert sibling.read_text(encoding="utf-8") == "preserve"


def test_verifier_cleanup_rejects_a_numba_cache_junction_and_preserves_its_target(
    short_local_tmp_path: Path,
) -> None:
    tool_root = short_local_tmp_path / "tool-root"
    verify_root = tool_root / "verify"
    workspace = verify_root / "verify-0123456789abcdef0123456789abcdef"
    media_workspace = workspace / "media-0123456789abcdef0123456789abcdef"
    media_workspace.mkdir(parents=True)
    outside_target = short_local_tmp_path / "outside-target"
    outside_target.mkdir()
    outside_sentinel = outside_target / "preserve.txt"
    outside_sentinel.write_text("preserve outside", encoding="utf-8")
    junction = workspace / "n"
    create_windows_junction(junction, outside_target)
    sibling = verify_root / "foreign-sibling.txt"
    sibling.write_text("preserve sibling", encoding="utf-8")

    try:
        result = run_setup_script(
            "$ErrorActionPreference = 'Stop'; "
            f". {powershell_literal(VERIFY_SCRIPT)} -QtPython {powershell_literal(Path(sys.executable))}; "
            f"$verify = {powershell_literal(verify_root)}; "
            f"$workspace = {powershell_literal(workspace)}; "
            f"$media = {powershell_literal(media_workspace)}; "
            "$failure = $null; try { Remove-VerificationWorkspace -VerifyRoot $verify -Workspace $workspace -MediaWorkspace $media } catch { $failure = $_ }; "
            "if ($null -eq $failure -or $failure.Exception.Message.IndexOf('reparse', [System.StringComparison]::OrdinalIgnoreCase) -lt 0) { throw 'Numba cache junction was not rejected at the reparse gate' }; "
            "if (-not (Test-Path -LiteralPath $workspace)) { throw 'junction rejection removed the workspace' }; "
            "'numba-cache-junction-rejected'"
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stdout.strip() == "numba-cache-junction-rejected"
        assert outside_sentinel.read_text(encoding="utf-8") == "preserve outside"
        assert sibling.read_text(encoding="utf-8") == "preserve sibling"
    finally:
        if junction.exists():
            os.rmdir(junction)


def test_numba_cleanup_holds_validated_identities_during_a_synchronised_swap(
    short_local_tmp_path: Path,
) -> None:
    workspace = (
        short_local_tmp_path
        / "verify"
        / "verify-0123456789abcdef0123456789abcdef"
    )
    module = workspace / "n" / "alpha_16722395fe3807967f9d89cb1b2b24b5deb292f4"
    owned_name = "estimate_alpha_sm.inner-185.py312.nbi"
    module.mkdir(parents=True)
    (module / owned_name).write_bytes(b"owned cache")
    held = workspace / "held-module"
    outside = short_local_tmp_path / "outside"
    outside.mkdir()
    outside_file = outside / owned_name
    outside_file.write_bytes(b"preserve outside")
    sibling = short_local_tmp_path / "foreign-sibling.txt"
    sibling.write_text("preserve sibling", encoding="utf-8")

    command = (
        "$ErrorActionPreference = 'Stop'; "
        f". {powershell_literal(VERIFY_SCRIPT)} -QtPython {powershell_literal(Path(sys.executable))}; "
        f"$workspace = {powershell_literal(workspace)}; "
        f"$module = {powershell_literal(module)}; "
        f"$held = {powershell_literal(held)}; "
        f"$outside = {powershell_literal(outside)}; "
        "$script:swapAttempted = $false; $script:swapBlocked = $false; $script:swapCompleted = $false; "
        "$plan = New-OwnedNumbaCacheDeletionPlan -WorkspaceRoot $workspace; "
        "$callback = [Action]{ "
        "$script:swapAttempted = $true; "
        "try { "
        "[System.IO.Directory]::Move($module, $held); "
        "$process = Start-Process -FilePath $env:ComSpec -ArgumentList @('/d','/c','mklink','/J',('"' + $module + '"'),('"' + $outside + '"')) -Wait -PassThru -WindowStyle Hidden; "
        "if ($process.ExitCode -ne 0) { throw 'junction creation failed' }; "
        "$script:swapCompleted = $true "
        "} catch { $script:swapBlocked = $true } "
        "}; "
        "try { $plan.Delete($callback); $plan.DeleteWorkspaceIfEmpty() } finally { $plan.Dispose() }; "
        "if (-not $script:swapAttempted) { throw 'synchronised swap was not attempted' }; "
        "if (-not $script:swapBlocked) { throw 'validated module identity was not held against replacement' }; "
        "'identity-bound-numba-cleanup-passed'"
    )
    result = run_setup_script(command)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "identity-bound-numba-cleanup-passed"
    assert not workspace.exists()
    assert outside_file.read_bytes() == b"preserve outside"
    assert sibling.read_text(encoding="utf-8") == "preserve sibling"


def test_media_cleanup_holds_validated_identities_during_a_synchronised_swap(
    short_local_tmp_path: Path,
) -> None:
    workspace = (
        short_local_tmp_path
        / "verify"
        / "verify-0123456789abcdef0123456789abcdef"
    )
    media = workspace / "media-0123456789abcdef0123456789abcdef"
    media.mkdir(parents=True)
    (media / "source.png").write_bytes(b"owned media")
    held = workspace / "held-media"
    outside = short_local_tmp_path / "outside-media"
    outside.mkdir()
    outside_file = outside / "source.png"
    outside_file.write_bytes(b"preserve outside")
    sibling = short_local_tmp_path / "foreign-sibling.txt"
    sibling.write_text("preserve sibling", encoding="utf-8")

    command = (
        "$ErrorActionPreference = 'Stop'; "
        f". {powershell_literal(VERIFY_SCRIPT)} -QtPython {powershell_literal(Path(sys.executable))}; "
        f"$workspace = {powershell_literal(workspace)}; "
        f"$media = {powershell_literal(media)}; "
        f"$held = {powershell_literal(held)}; "
        f"$outside = {powershell_literal(outside)}; "
        "$script:swapAttempted = $false; $script:swapBlocked = $false; "
        "$plan = New-OwnedVerificationCleanupPlan -WorkspaceRoot $workspace -MediaWorkspace $media; "
        "$callback = [Action]{ "
        "$script:swapAttempted = $true; "
        "try { "
        "[System.IO.Directory]::Move($media, $held); "
        "$process = Start-Process -FilePath $env:ComSpec -ArgumentList @('/d','/c','mklink','/J',('"' + $media + '"'),('"' + $outside + '"')) -Wait -PassThru -WindowStyle Hidden; "
        "if ($process.ExitCode -ne 0) { throw 'junction creation failed' } "
        "} catch { $script:swapBlocked = $true } "
        "}; "
        "try { $plan.Delete($callback); $plan.DeleteWorkspaceIfEmpty() } finally { $plan.Dispose() }; "
        "if (-not $script:swapAttempted) { throw 'synchronised media swap was not attempted' }; "
        "if (-not $script:swapBlocked) { throw 'validated media identity was not held against replacement' }; "
        "'identity-bound-media-cleanup-passed'"
    )
    try:
        result = run_setup_script(command)

        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stdout.strip() == "identity-bound-media-cleanup-passed"
        assert not workspace.exists()
        assert outside_file.read_bytes() == b"preserve outside"
        assert sibling.read_text(encoding="utf-8") == "preserve sibling"
    finally:
        if media.exists() and (
            getattr(os.lstat(media), "st_file_attributes", 0)
            & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            os.rmdir(media)


def test_numba_cleanup_rejects_an_ancestor_swap_before_handle_binding(
    short_local_tmp_path: Path,
) -> None:
    tool_root = short_local_tmp_path / "tool-root"
    verify_root = tool_root / "verify"
    workspace_name = "verify-0123456789abcdef0123456789abcdef"
    workspace = verify_root / workspace_name
    module_name = "alpha_16722395fe3807967f9d89cb1b2b24b5deb292f4"
    owned_name = "estimate_alpha_sm.inner-185.py312.nbi"
    local_file = workspace / "n" / module_name / owned_name
    local_file.parent.mkdir(parents=True)
    local_file.write_bytes(b"local cache")
    held_verify = tool_root / "verify-held"

    outside_verify = short_local_tmp_path / "outside-verify"
    outside_file = outside_verify / workspace_name / "n" / module_name / owned_name
    outside_file.parent.mkdir(parents=True)
    outside_file.write_bytes(b"preserve outside")
    sibling = short_local_tmp_path / "foreign-sibling.txt"
    sibling.write_text("preserve sibling", encoding="utf-8")

    command = (
        "$ErrorActionPreference = 'Stop'; "
        f". {powershell_literal(VERIFY_SCRIPT)} -QtPython {powershell_literal(Path(sys.executable))}; "
        f"$verify = {powershell_literal(verify_root)}; "
        f"$held = {powershell_literal(held_verify)}; "
        f"$outside = {powershell_literal(outside_verify)}; "
        f"$workspace = {powershell_literal(workspace)}; "
        "$script:swapAttempted = $false; "
        "$callback = [Action]{ "
        "$script:swapAttempted = $true; "
        "[System.IO.Directory]::Move($verify, $held); "
        "New-Item -ItemType Junction -Path $verify -Target $outside | Out-Null "
        "}; "
        "$failure = $null; $plan = $null; try { "
        "$plan = New-OwnedNumbaCacheDeletionPlan -WorkspaceRoot $workspace -AfterPathValidationForTest $callback; "
        "$plan.Delete($null); $plan.DeleteWorkspaceIfEmpty() "
        "} catch { $failure = $_ } finally { if ($null -ne $plan) { $plan.Dispose() } }; "
        "if (-not $script:swapAttempted) { throw 'ancestor swap did not run after path validation' }; "
        "if ($null -eq $failure -or $failure.Exception.Message.IndexOf('reparse', [System.StringComparison]::OrdinalIgnoreCase) -lt 0) { throw ('ancestor junction was not rejected by anchored traversal: ' + $failure.Exception.ToString()) }; "
        "'ancestor-swap-rejected'"
    )
    try:
        result = run_setup_script(command)

        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stdout.strip() == "ancestor-swap-rejected"
        assert outside_file.read_bytes() == b"preserve outside"
        assert sibling.read_text(encoding="utf-8") == "preserve sibling"
        assert (held_verify / workspace_name / "n" / module_name / owned_name).read_bytes() == b"local cache"
    finally:
        if verify_root.exists() and (
            getattr(os.lstat(verify_root), "st_file_attributes", 0)
            & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            os.rmdir(verify_root)


def test_malformed_numba_cache_is_rejected_before_media_diagnostics_are_deleted(
    short_local_tmp_path: Path,
) -> None:
    tool_root = short_local_tmp_path / "tool-root"
    verify_root = tool_root / "verify"
    workspace = verify_root / "verify-0123456789abcdef0123456789abcdef"
    media_workspace = workspace / "media-0123456789abcdef0123456789abcdef"
    media_workspace.mkdir(parents=True)
    media_diagnostic = media_workspace / "source.png"
    media_diagnostic.write_bytes(b"preserve media diagnostic")
    malformed_cache = (
        workspace
        / "n"
        / "alpha_16722395fe3807967f9d89cb1b2b24b5deb292f4"
        / "native.dll"
    )
    malformed_cache.parent.mkdir(parents=True)
    malformed_cache.write_bytes(b"reject cache")
    sibling = verify_root / "foreign-sibling.txt"
    sibling.write_text("preserve sibling", encoding="utf-8")

    command = (
        "$ErrorActionPreference = 'Stop'; "
        f". {powershell_literal(VERIFY_SCRIPT)} -QtPython {powershell_literal(Path(sys.executable))}; "
        f"$verify = {powershell_literal(verify_root)}; "
        f"$workspace = {powershell_literal(workspace)}; "
        f"$media = {powershell_literal(media_workspace)}; "
        "$failure = $null; try { Remove-VerificationWorkspace -VerifyRoot $verify -Workspace $workspace -MediaWorkspace $media } catch { $failure = $_ }; "
        "if ($null -eq $failure) { throw 'malformed cache was accepted' }; "
        "'prevalidated-cleanup-passed'"
    )
    result = run_setup_script(command)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "prevalidated-cleanup-passed"
    assert media_diagnostic.read_bytes() == b"preserve media diagnostic"
    assert malformed_cache.read_bytes() == b"reject cache"
    assert sibling.read_text(encoding="utf-8") == "preserve sibling"


@pytest.mark.parametrize(
    ("relative_path", "contents"),
    [
        (
            "n/alpha_not-a-sha1/estimate_alpha_sm.inner-185.py312.nbi",
            b"bad directory",
        ),
        (
            "n/alpha_16722395fe3807967f9d89cb1b2b24b5deb292f4/nested/cache.nbi",
            b"too deep",
        ),
        (
            "n/alpha_16722395fe3807967f9d89cb1b2b24b5deb292f4/native.dll",
            b"unexpected extension",
        ),
    ],
)
def test_verifier_cleanup_rejects_unowned_numba_cache_shapes(
    short_local_tmp_path: Path, relative_path: str, contents: bytes
) -> None:
    tool_root = short_local_tmp_path / "tool-root"
    verify_root = tool_root / "verify"
    workspace = verify_root / "verify-0123456789abcdef0123456789abcdef"
    media_workspace = workspace / "media-0123456789abcdef0123456789abcdef"
    unexpected = workspace / Path(relative_path)
    unexpected.parent.mkdir(parents=True)
    unexpected.write_bytes(contents)
    sibling = verify_root / "foreign-sibling.txt"
    sibling.write_text("preserve", encoding="utf-8")

    result = run_setup_script(
        "$ErrorActionPreference = 'Stop'; "
        f". {powershell_literal(VERIFY_SCRIPT)} -QtPython {powershell_literal(Path(sys.executable))}; "
        f"$verify = {powershell_literal(verify_root)}; "
        f"$workspace = {powershell_literal(workspace)}; "
        f"$media = {powershell_literal(media_workspace)}; "
        "$failure = $null; try { Remove-VerificationWorkspace -VerifyRoot $verify -Workspace $workspace -MediaWorkspace $media } catch { $failure = $_ }; "
        "if ($null -eq $failure) { throw 'unowned Numba cache shape was removed' }; "
        "if (-not (Test-Path -LiteralPath $workspace)) { throw 'failed cleanup removed its workspace' }; "
        "'unowned-numba-cache-rejected'"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "unowned-numba-cache-rejected"
    assert unexpected.read_bytes() == contents
    assert sibling.read_text(encoding="utf-8") == "preserve"


TOOLCHAIN_DOC = REPO_ROOT / "docs" / "development-pet-toolchain.md"


def test_pet_toolchain_documentation_has_exact_operator_sections_and_commands() -> None:
    text = TOOLCHAIN_DOC.read_text(encoding="utf-8")
    for heading in (
        "## 1. Purpose and non-goals",
        "## 2. Tracked versus machine-local files",
        "## 3. Required Python 3.12 and PySide6 verifier interpreter",
        "## 4. First install",
        "## 5. Read-only verify",
        "## 6. Lock contents and supply-chain updates",
        "## 7. v2/v3/v4 pet production hand-off",
        "## 8. Exact Codex trust and Git safe.directory policy",
        "## 9. Failure messages and rollback procedure / 回滚",
        "## 10. Proof of non-modification boundaries",
    ):
        assert heading in text

    first_install = """~~~powershell
& .\\scripts\\setup_pet_toolchain.ps1 `
  -QtPython 'C:\\path\\to\\PySide6\\python.exe'
~~~"""
    verify = """~~~powershell
& .\\scripts\\verify_pet_toolchain.ps1 `
  -QtPython 'C:\\path\\to\\PySide6\\python.exe'
~~~"""
    assert first_install in text
    assert verify in text
    assert "下面命令中的绝对路径只是本机 local example，不是项目配置值；不能照抄到项目文件。" in text
    assert "-QtPython 路径只是 local example，不是项目配置值" in text
    for required in (
        "%LOCALAPPDATA%\\DesktopCompanionDev\\pet-toolchain",
        "直接短子目录 `n`",
        "最多允许 259 个 UTF-16 字符",
        "Tool root exceeds the locked Numba path budget",
        "每个祖先、媒体目录、媒体文件和 Numba 缓存对象",
        "同一 Windows 用户主动移入的普通同形对象",
        "不修改 PATH",
        "isnet-anime",
        "u2net_human_seg",
        "PET TOOLCHAIN VERIFIED",
    ):
        assert required in text


def test_pet_toolchain_documentation_locks_exact_trust_scope_and_idempotent_git_policy() -> None:
    text = TOOLCHAIN_DOC.read_text(encoding="utf-8")
    codex_trust = """[projects.'c:\\path\\to\\desktop-companion']
trust_level = "trusted"

[projects.'c:\\path\\to\\desktop-companion-worktrees\\yinyue-v4-runtime']
trust_level = "trusted"""
    assert codex_trust in text
    private_user_prefixes = (
        "c:" + chr(92) + "users" + chr(92),
        "c:/" + "users/",
    )
    assert all(prefix not in text.casefold() for prefix in private_user_prefixes)
    assert "不得信任 parent directory、Documents、整个 desktop-companion-worktrees" in text
    assert "不得使用 safe.directory=*" in text
    assert "不得以等价通配配置替代它" in text

    git_policy = text.split(
        "## 8. Exact Codex trust and Git safe.directory policy", 1
    )[1].split("## 9. Failure messages and rollback procedure / 回滚", 1)[0]
    allowed_match = re.search(
        r"\$allowedSafeDirectories = @\(\r?\n(?P<body>.*?)\r?\n\)",
        git_policy,
        re.DOTALL,
    )
    assert allowed_match is not None
    allowed_entries = [
        line.strip().strip("'")
        for line in allowed_match.group("body").splitlines()
        if line.strip()
    ]
    assert allowed_entries == [
        "C:/path/to/desktop-companion",
        "C:/path/to/desktop-companion-worktrees/yinyue-v4-runtime",
    ]
    assert "git config --global --get-all safe.directory 2>$null" in git_policy
    assert "$existingSafeDirectories = @(git config --global --get-all safe.directory 2>$null)" in git_policy
    assert 'Write-Output "Existing safe.directory values:"' in git_policy
    assert "$unexpectedSafeDirectories = @(" in git_policy
    assert "Where-Object { $_ -notin $allowedSafeDirectories }" in git_policy
    assert "if ($unexpectedSafeDirectories.Count -gt 0)" in git_policy
    assert 'throw "Unexpected safe.directory value(s):' in git_policy
    assert "Audit and remove each unexpected value before retrying" in git_policy
    assert "this block will not remove unknown trust" in git_policy
    assert "foreach ($safeDirectory in $allowedSafeDirectories)" in git_policy
    assert "Where-Object { $_ -ieq $safeDirectory }" in git_policy
    assert "git config --global --add safe.directory $safeDirectory" in git_policy
    assert "git config --global --add safe.directory *" not in git_policy
    assert "$finalSafeDirectories = @(git config --global --get-all safe.directory 2>$null)" in git_policy
    assert 'Write-Output "Final safe.directory values:"' in git_policy
    assert "$finalUnexpected = @(" in git_policy
    assert "$finalDuplicates = @(" in git_policy
    assert "Group-Object" in git_policy
    assert "$missingSafeDirectories = @(" in git_policy
    assert "$finalSafeDirectories.Count -ne $allowedSafeDirectories.Count" in git_policy
    assert 'throw "Final safe.directory values must exactly match the two allowed paths' in git_policy
    assert "case-insensitive, no duplicates" in git_policy
    assert "它不会自动撤销任何 safe.directory 值" in git_policy
    assert "重新读取全部 safe.directory 值" in git_policy
    assert "与本次运行前打印的 values 对照" in git_policy
    assert "只删除这些 exact value" in git_policy
    assert "未知值绝不会由该块自动删除" in git_policy
    assert "失败时只撤销本次新增的 exact value" not in git_policy
    unexpected_index = git_policy.index("$unexpectedSafeDirectories = @(")
    throw_index = git_policy.index('throw "Unexpected safe.directory value(s):')
    foreach_index = git_policy.index("foreach ($safeDirectory in $allowedSafeDirectories)")
    add_index = git_policy.index("git config --global --add safe.directory $safeDirectory")
    assert unexpected_index < throw_index < foreach_index < add_index
    for forbidden_mutator in (
        "git config --global --unset",
        "git config --global --unset-all",
        "git config --global --replace-all",
    ):
        assert forbidden_mutator.casefold() not in git_policy.casefold()


def test_pet_toolchain_documentation_uses_a_self_contained_old_repo_rollback() -> None:
    text = TOOLCHAIN_DOC.read_text(encoding="utf-8")
    rollback = text.split(
        "## 9. Failure messages and rollback procedure / 回滚", 1
    )[1].split("## 10. Proof of non-modification boundaries", 1)[0]
    expected_command = """~~~powershell
$oldRepo = 'C:\\path\\to\\clean-prior-source'
& (Join-Path $oldRepo 'scripts\\setup_pet_toolchain.ps1') `
  -QtPython 'C:\\path\\to\\PySide6\\python.exe'
~~~"""
    assert expected_command in rollback
    assert "旧 checkout 必须是 trusted、clean 且包含对应版本" in rollback
    assert "setup 会验证后原子切换 current" in rollback
    assert "& .\\scripts\\setup_pet_toolchain.ps1" not in rollback
    assert "-LockPath (Join-Path $oldRepo" not in rollback
    assert "-RequirementsPath (Join-Path $oldRepo" not in rollback
