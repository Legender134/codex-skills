from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import ctypes
from ctypes import wintypes
import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import signal
import subprocess
import threading
import time
from types import MappingProxyType
import warnings

from PIL import Image

from contracts import (
    _is_utf8_text,
    _validate_untrusted_image_canvas,
    sha256_file,
    validate_json_structure,
)


VALID_STATUSES = frozenset({"pass", "blocked", "unverified"})
MAX_MANIFEST_BYTES = 64 * 1024
MAX_ENCODED_IMAGE_BYTES = 32 * 1024 * 1024
MAX_TOTAL_ENCODED_IMAGE_BYTES = 32 * 1024 * 1024
MAX_TOTAL_DECODED_PIXELS = 50_000_000
MAX_IMAGE_PIXELS = 16 * 1024 * 1024
MAX_SCHEMA_OUTPUT_BYTES = 64 * 1024
PROCESS_TIMEOUT_SECONDS = 30
_DRIVE_OR_UNC_PATH = re.compile(r"^(?:[A-Za-z]:|//|\\\\)")


class PackageInputError(ValueError):
    """A package-controlled problem that becomes one deterministic check."""

    def __init__(
        self,
        code: str,
        message: str,
        evidence: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.evidence = dict(evidence or {})


def _freeze_json(value: object) -> object:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("evidence numbers must be finite")
        return value
    if isinstance(value, str):
        if not _is_utf8_text(value):
            raise ValueError("evidence text must be UTF-8 encodable")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not _is_utf8_text(key):
                raise ValueError("evidence keys must be UTF-8 text")
            frozen[key] = _freeze_json(item)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    raise ValueError("evidence must be JSON-compatible")


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


@dataclass(frozen=True)
class PackageCheck:
    code: str
    status: str
    message: str
    evidence: dict[str, object]

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not self.code or not _is_utf8_text(self.code):
            raise ValueError("PackageCheck code must be non-empty text")
        if self.status not in VALID_STATUSES:
            raise ValueError("PackageCheck status is invalid")
        if not isinstance(self.message, str) or not _is_utf8_text(self.message):
            raise ValueError("PackageCheck message must be UTF-8 text")
        if not isinstance(self.evidence, Mapping):
            raise ValueError("PackageCheck evidence must be an object")
        object.__setattr__(self, "evidence", _freeze_json(self.evidence))

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "status": self.status,
            "message": self.message,
            "evidence": _thaw_json(self.evidence),
        }


class CheckCollector:
    def __init__(self) -> None:
        self._checks: list[PackageCheck] = []
        self._codes: set[str] = set()

    def add(self, check: PackageCheck) -> None:
        if check.code in self._codes:
            raise RuntimeError(f"duplicate package-check code: {check.code}")
        self._codes.add(check.code)
        self._checks.append(check)

    def blocked(self, error: PackageInputError) -> None:
        try:
            check = PackageCheck(error.code, "blocked", error.message, error.evidence)
        except (TypeError, ValueError):
            # Error evidence is diagnostic only; malformed package text may never
            # prevent the package error itself from being reported safely.
            check = PackageCheck(error.code, "blocked", error.message, {})
        self.add(check)

    @property
    def checks(self) -> tuple[PackageCheck, ...]:
        return tuple(self._checks)


@dataclass
class ManifestData:
    root: Path
    manifest_path: Path
    manifest_sha256: str
    manifest: dict[str, object]


@dataclass
class ImageAsset:
    path: Path
    identity: tuple[int, int]
    sha256: str
    width: int
    height: int
    rgba: Image.Image
    visibility_cache: dict[tuple[int, int, int, int], bool] = field(default_factory=dict)

    def close(self) -> None:
        self.rgba.close()


@dataclass(frozen=True)
class AssetSnapshot:
    """A single bounded, stable read of an untrusted package asset."""

    path: Path
    identity: tuple[int, int]
    encoded: bytes
    sha256: str
    width: int
    height: int


@dataclass
class PackageContext:
    root: Path
    manifest_path: Path
    manifest: dict[str, object]
    assets: list[ImageAsset]

    def remember(self, asset: ImageAsset) -> ImageAsset:
        self.assets.append(asset)
        return asset


def is_integer(value: object, lower: int, upper: int) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and lower <= value <= upper
    )


def is_number(value: object, lower: float, upper: float) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return lower <= value <= upper
    return isinstance(value, float) and math.isfinite(value) and lower <= value <= upper


def require_text(value: object, code: str, message: str) -> str:
    if not isinstance(value, str) or not _is_utf8_text(value) or not value:
        raise PackageInputError(code, message)
    return value


def require_mapping(value: object, code: str, message: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise PackageInputError(code, message)
    return value


def require_list(value: object, code: str, message: str) -> list[object]:
    if not isinstance(value, list):
        raise PackageInputError(code, message)
    return value


def _is_link_or_junction(path: Path) -> bool:
    try:
        is_junction = getattr(path, "is_junction", None)
        return path.is_symlink() or bool(is_junction and is_junction())
    except (OSError, ValueError, UnicodeError):
        return True


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise PackageInputError(
                "MANIFEST_JSON_DUPLICATE_KEY",
                "pet.json may not contain duplicate object keys",
                {"occurrence": len(result)},
            )
        result[key] = value
    return result


def _reject_nonstandard_number(value: str) -> object:
    raise PackageInputError(
        "MANIFEST_JSON_NONSTANDARD_NUMBER",
        "pet.json may not contain non-standard numeric constants",
        {"constant": value},
    )


def load_manifest(package_root: Path) -> ManifestData:
    try:
        if _is_link_or_junction(package_root):
            raise PackageInputError(
                "PACKAGE_ROOT_INVALID", "package root may not be a link or junction"
            )
        root = package_root.resolve(strict=True)
        if not root.is_dir():
            raise PackageInputError("PACKAGE_ROOT_INVALID", "package root must be a directory")
    except PackageInputError:
        raise
    except (OSError, ValueError, UnicodeError) as error:
        raise PackageInputError(
            "PACKAGE_ROOT_INVALID", "package root is not readable"
        ) from error

    manifest_path = root / "pet.json"
    try:
        if not manifest_path.is_file():
            raise PackageInputError("MANIFEST_FILE_MISSING", "pet.json is missing")
        if _is_link_or_junction(manifest_path):
            raise PackageInputError("PACKAGE_PATH_INVALID", "pet.json may not be a link")
        with manifest_path.open("rb") as source:
            raw = source.read(MAX_MANIFEST_BYTES + 1)
    except PackageInputError:
        raise
    except (OSError, ValueError, UnicodeError) as error:
        raise PackageInputError("MANIFEST_FILE_INVALID", "pet.json is not readable") from error
    if len(raw) > MAX_MANIFEST_BYTES:
        raise PackageInputError(
            "MANIFEST_BYTES_LIMIT",
            "pet.json may not exceed 64 KiB",
            {"maxBytes": MAX_MANIFEST_BYTES},
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise PackageInputError(
            "MANIFEST_JSON_INVALID_UNICODE", "pet.json must be valid UTF-8"
        ) from error
    try:
        manifest = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonstandard_number,
        )
    except PackageInputError:
        raise
    except (json.JSONDecodeError, RecursionError, ValueError, TypeError) as error:
        raise PackageInputError(
            "MANIFEST_JSON_INVALID", "pet.json is not valid JSON"
        ) from error
    if not isinstance(manifest, dict):
        raise PackageInputError(
            "MANIFEST_OBJECT_REQUIRED", "pet.json must contain a JSON object"
        )
    structural_issues = validate_json_structure(manifest, "manifest")
    if structural_issues:
        raise PackageInputError(
            "MANIFEST_JSON_STRUCTURE_INVALID",
            "pet.json exceeds the supported JSON safety policy",
            {"issues": [issue.code for issue in structural_issues]},
        )
    return ManifestData(root, manifest_path, hashlib.sha256(raw).hexdigest(), manifest)


def validate_package_identity(context: PackageContext) -> str:
    package_id = require_text(
        context.manifest.get("id"), "PACKAGE_ID_INVALID", "manifest id must be text"
    )
    if context.root.name != package_id:
        raise PackageInputError(
            "PACKAGE_ID_MISMATCH",
            "manifest id must match the package directory name",
            {"id": package_id, "directory": context.root.name},
        )
    return package_id


def detect_format(manifest: dict[str, object]) -> int:
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be an object with spriteVersionNumber")
    value = manifest.get("spriteVersionNumber")
    if not isinstance(value, int) or isinstance(value, bool) or value not in {2, 3, 4}:
        raise ValueError("spriteVersionNumber must be integer 2, 3, or 4")
    return value


def resolve_package_file(context: PackageContext, value: object, field: str) -> Path:
    if not isinstance(value, str) or not _is_utf8_text(value) or not value:
        raise PackageInputError("PACKAGE_PATH_INVALID", f"{field} must be a relative UTF-8 path")
    if (
        "\x00" in value
        or "\\" in value
        or ":" in value
        or _DRIVE_OR_UNC_PATH.match(value)
    ):
        raise PackageInputError("PACKAGE_PATH_INVALID", f"{field} must be a relative POSIX path")
    pure = PurePosixPath(value)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise PackageInputError("PACKAGE_PATH_INVALID", f"{field} must stay beneath package root")
    try:
        candidate = context.root.joinpath(*pure.parts)
        if _is_link_or_junction(candidate):
            raise PackageInputError("PACKAGE_PATH_INVALID", f"{field} may not be a link")
        resolved = candidate.resolve(strict=True)
        if not resolved.is_relative_to(context.root):
            raise PackageInputError("PACKAGE_PATH_INVALID", f"{field} escapes package root")
        if resolved == context.manifest_path:
            raise PackageInputError("PACKAGE_PATH_INVALID", f"{field} may not alias pet.json")
        if not resolved.is_file():
            raise PackageInputError("PACKAGE_PATH_INVALID", f"{field} must name a file")
        # Return the lexical package path instead of the first resolved target. A
        # later stable open verifies the file that was actually opened, including
        # its final handle identity, rather than trusting this pre-open lookup.
        return candidate
    except PackageInputError:
        raise
    except FileNotFoundError as error:
        raise PackageInputError("PACKAGE_FILE_MISSING", f"{field} is missing") from error
    except (OSError, ValueError, UnicodeError) as error:
        raise PackageInputError("PACKAGE_PATH_INVALID", f"{field} is not a safe file path") from error


def _file_metadata(stat_result: object) -> tuple[int, int, int, int]:
    try:
        return (
            int(getattr(stat_result, "st_dev")),
            int(getattr(stat_result, "st_ino")),
            int(getattr(stat_result, "st_size")),
            int(getattr(stat_result, "st_mtime_ns")),
        )
    except (AttributeError, TypeError, ValueError, OverflowError) as error:
        raise OSError("file metadata is not usable") from error


def _opened_handle_path(source: object, fallback: Path) -> Path:
    """Return the final path for an already-open file handle without reopening it."""

    descriptor = int(getattr(source, "fileno")())
    if os.name == "nt":
        import ctypes
        import msvcrt

        handle = msvcrt.get_osfhandle(descriptor)
        buffer = ctypes.create_unicode_buffer(32_768)
        length = ctypes.windll.kernel32.GetFinalPathNameByHandleW(
            handle, buffer, len(buffer), 0
        )
        if not length or length >= len(buffer):
            raise OSError("could not resolve opened file handle")
        value = buffer.value
        if value.startswith("\\\\?\\UNC\\"):
            value = "\\\\" + value[8:]
        elif value.startswith("\\\\?\\"):
            value = value[4:]
        return Path(value)
    descriptor_path = Path("/proc/self/fd") / str(descriptor)
    try:
        return Path(os.readlink(descriptor_path))
    except (OSError, ValueError, UnicodeError):
        return fallback.resolve(strict=True)


def _read_stable_asset(
    context: PackageContext, value: object, field: str
) -> tuple[Path, tuple[int, int], bytes]:
    path = resolve_package_file(context, value, field)
    try:
        if _is_link_or_junction(path):
            raise PackageInputError("PACKAGE_PATH_INVALID", f"{field} may not be a link")
        named_before = _file_metadata(path.stat(follow_symlinks=False))
        if named_before[2] <= 0:
            raise PackageInputError("PACKAGE_FILE_EMPTY", f"{field} is empty")
        if named_before[2] > MAX_ENCODED_IMAGE_BYTES:
            raise PackageInputError(
                "PACKAGE_IMAGE_BYTES_LIMIT",
                f"{field} exceeds the encoded-image byte limit",
                {"maxBytes": MAX_ENCODED_IMAGE_BYTES},
            )
        with path.open("rb") as source:
            opened_before = _file_metadata(os.fstat(source.fileno()))
            opened_path = _opened_handle_path(source, path)
            try:
                final_path = opened_path.resolve(strict=True)
            except (OSError, ValueError, UnicodeError) as error:
                raise PackageInputError(
                    "PACKAGE_PATH_INVALID", f"{field} final opened path is not readable"
                ) from error
            if not final_path.is_relative_to(context.root):
                raise PackageInputError(
                    "PACKAGE_PATH_INVALID", f"{field} final opened path escapes package root"
                )
            if named_before != opened_before:
                raise PackageInputError(
                    "PACKAGE_FILE_CHANGED", f"{field} changed before it could be read"
                )
            encoded = source.read(MAX_ENCODED_IMAGE_BYTES + 1)
            opened_after = _file_metadata(os.fstat(source.fileno()))
        named_after = _file_metadata(path.stat(follow_symlinks=False))
    except PackageInputError:
        raise
    except FileNotFoundError as error:
        raise PackageInputError("PACKAGE_FILE_MISSING", f"{field} is missing") from error
    except (OSError, UnicodeError, ValueError) as error:
        raise PackageInputError(
            "PACKAGE_FILE_INVALID", f"{field} could not be read safely"
        ) from error
    if len(encoded) > MAX_ENCODED_IMAGE_BYTES:
        raise PackageInputError(
            "PACKAGE_IMAGE_BYTES_LIMIT",
            f"{field} exceeds the encoded-image byte limit",
            {"maxBytes": MAX_ENCODED_IMAGE_BYTES},
        )
    if named_before != opened_after or opened_after != named_after:
        raise PackageInputError(
            "PACKAGE_FILE_CHANGED", f"{field} changed while it was being read"
        )
    return path, opened_after[:2], encoded


def _header_from_encoded(encoded: bytes, field: str) -> tuple[int, int]:
    stream = io.BytesIO(encoded)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(stream) as source:
                _validate_untrusted_image_canvas(*source.size)
                if source.format != "WEBP":
                    raise PackageInputError("PACKAGE_IMAGE_INVALID", f"{field} must be a WebP image")
                if "A" not in source.getbands():
                    raise PackageInputError(
                        "PACKAGE_IMAGE_ALPHA_REQUIRED", f"{field} must have alpha"
                    )
                return source.width, source.height
    except PackageInputError:
        raise
    except (Image.DecompressionBombWarning, Image.DecompressionBombError) as error:
        raise PackageInputError(
            "PACKAGE_IMAGE_PIXELS_LIMIT", f"{field} has an unsafe canvas"
        ) from error
    except (OSError, SyntaxError, UnicodeError, ValueError) as error:
        if isinstance(error, ValueError) and "unsafe canvas" in str(error):
            raise PackageInputError(
                "PACKAGE_IMAGE_PIXELS_LIMIT", f"{field} has an unsafe canvas"
            ) from error
        raise PackageInputError("PACKAGE_IMAGE_INVALID", f"{field} cannot be decoded") from error
    finally:
        stream.close()


def snapshot_webp(context: PackageContext, value: object, field: str) -> AssetSnapshot:
    path, identity, encoded = _read_stable_asset(context, value, field)
    width, height = _header_from_encoded(encoded, field)
    return AssetSnapshot(
        path=path,
        identity=identity,
        encoded=encoded,
        sha256=hashlib.sha256(encoded).hexdigest(),
        width=width,
        height=height,
    )


def decode_snapshot_rgba(snapshot: AssetSnapshot, field: str) -> ImageAsset:
    stream = io.BytesIO(snapshot.encoded)
    rgba: Image.Image | None = None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(stream) as source:
                _validate_untrusted_image_canvas(*source.size)
                if (
                    source.format != "WEBP"
                    or source.width != snapshot.width
                    or source.height != snapshot.height
                    or "A" not in source.getbands()
                ):
                    raise PackageInputError(
                        "PACKAGE_IMAGE_INVALID", f"{field} header changed while decoding"
                    )
                source.load()
                rgba = source.convert("RGBA").copy()
        if rgba.getchannel("A").getbbox() is None:
            raise PackageInputError(
                "PACKAGE_IMAGE_EMPTY_ALPHA", f"{field} has no visible alpha pixels"
            )
        return ImageAsset(
            snapshot.path,
            snapshot.identity,
            snapshot.sha256,
            snapshot.width,
            snapshot.height,
            rgba,
        )
    except PackageInputError:
        if rgba is not None:
            rgba.close()
        raise
    except (Image.DecompressionBombWarning, Image.DecompressionBombError) as error:
        if rgba is not None:
            rgba.close()
        raise PackageInputError(
            "PACKAGE_IMAGE_PIXELS_LIMIT", f"{field} has an unsafe canvas"
        ) from error
    except (OSError, SyntaxError, UnicodeError, ValueError) as error:
        if rgba is not None:
            rgba.close()
        if isinstance(error, ValueError) and "unsafe canvas" in str(error):
            raise PackageInputError(
                "PACKAGE_IMAGE_PIXELS_LIMIT", f"{field} has an unsafe canvas"
            ) from error
        raise PackageInputError("PACKAGE_IMAGE_INVALID", f"{field} cannot be decoded") from error
    finally:
        stream.close()


def load_asset(context: PackageContext, value: object, field: str) -> ImageAsset:
    return context.remember(decode_snapshot_rgba(snapshot_webp(context, value, field), field))


def grid_cell_visible(
    asset: ImageAsset,
    cell_width: int,
    cell_height: int,
    row: int,
    column: int,
) -> bool:
    if not is_integer(cell_width, 1, asset.width) or not is_integer(cell_height, 1, asset.height):
        return False
    columns = asset.width // cell_width
    rows = asset.height // cell_height
    if asset.width % cell_width or asset.height % cell_height:
        return False
    if not is_integer(row, 0, rows - 1) or not is_integer(column, 0, columns - 1):
        return False
    key = (cell_width, cell_height, row, column)
    cached = asset.visibility_cache.get(key)
    if cached is not None:
        return cached
    cell = asset.rgba.crop(
        (
            column * cell_width,
            row * cell_height,
            (column + 1) * cell_width,
            (row + 1) * cell_height,
        )
    )
    try:
        visible = cell.getchannel("A").getbbox() is not None
        asset.visibility_cache[key] = visible
        return visible
    finally:
        cell.close()


def close_assets(context: PackageContext) -> None:
    for asset in context.assets:
        try:
            asset.close()
        except (OSError, ValueError):
            pass


SCHEMA_PROGRAM = (
    "import json,sys;"
    "from jsonschema import Draft202012Validator as V;"
    "s=json.load(open(sys.argv[1],encoding='utf-8'));"
    "m=json.load(open(sys.argv[2],encoding='utf-8'));"
    "V.check_schema(s);"
    "errors=sorted(V(s).iter_errors(m),key=lambda e:list(e.path));"
    "print(json.dumps([{'path':list(e.path),'message':e.message} for e in errors],"
    "ensure_ascii=False,separators=(',',':')));"
    "raise SystemExit(1 if errors else 0)"
)


@dataclass(frozen=True)
class _BoundedProcessResult:
    returncode: int | None
    stdout: bytes
    stderr: bytes
    overflow: bool
    timed_out: bool
    spawn_failed: bool
    read_failed: bool


@dataclass
class _ProcessTree:
    """The resources that make a spawned process tree independently stoppable."""

    process: object
    process_group_id: int | None = None
    job_handle: int | None = None
    closed: bool = False


class _JobBasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _JobIoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _JobExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JobBasicLimitInformation),
        ("IoInfo", _JobIoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _ThreadEntry32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ThreadID", wintypes.DWORD),
        ("th32OwnerProcessID", wintypes.DWORD),
        ("tpBasePri", wintypes.LONG),
        ("tpDeltaPri", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
    ]


_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_TH32CS_SNAPTHREAD = 0x00000004
_THREAD_SUSPEND_RESUME = 0x0002
_ERROR_NO_MORE_FILES = 18
_RESUME_THREAD_FAILED = 0xFFFFFFFF
_INITIAL_THREAD_DISCOVERY_TIMEOUT_SECONDS = 0.5
_INVALID_WINDOWS_HANDLE_VALUE = ctypes.c_void_p(-1).value
# CREATE_SUSPENDED is a documented CreateProcess flag.  CPython does not expose
# it as subprocess.CREATE_SUSPENDED on every supported Windows build.
_CREATE_SUSPENDED = 0x00000004


def _windows_handle_value(value: object) -> int | None:
    try:
        handle = getattr(value, "value", value)
        if isinstance(handle, bool):
            return None
        result = int(handle)
    except (TypeError, ValueError, AttributeError):
        return None
    if result == _INVALID_WINDOWS_HANDLE_VALUE:
        return None
    return result if result > 0 else None


def _windows_kernel32() -> object:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    )
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
    kernel32.TerminateJobObject.restype = wintypes.BOOL
    kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Thread32First.argtypes = (wintypes.HANDLE, ctypes.POINTER(_ThreadEntry32))
    kernel32.Thread32First.restype = wintypes.BOOL
    kernel32.Thread32Next.argtypes = (wintypes.HANDLE, ctypes.POINTER(_ThreadEntry32))
    kernel32.Thread32Next.restype = wintypes.BOOL
    kernel32.OpenThread.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenThread.restype = wintypes.HANDLE
    kernel32.ResumeThread.argtypes = (wintypes.HANDLE,)
    kernel32.ResumeThread.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    return kernel32


def _assign_windows_job(process: object) -> int | None:
    """Attach immediately to a kill-on-close Job Object or fail closed."""

    job_handle: int | None = None
    assigned = False
    try:
        kernel32 = _windows_kernel32()
        job_handle = _windows_handle_value(kernel32.CreateJobObjectW(None, None))
        if job_handle is None:
            return None
        limits = _JobExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            wintypes.HANDLE(job_handle),
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            return None
        process_handle = _windows_handle_value(getattr(process, "_handle", None))
        if process_handle is None or not kernel32.AssignProcessToJobObject(
            wintypes.HANDLE(job_handle), wintypes.HANDLE(process_handle)
        ):
            return None
        assigned = True
        return job_handle
    except Exception:
        return None
    finally:
        if job_handle is not None and not assigned:
            try:
                _windows_kernel32().CloseHandle(wintypes.HANDLE(job_handle))
            except Exception:
                pass


def _terminate_windows_job(job_handle: int) -> bool:
    kernel32: object | None = None
    terminated = False
    closed = False
    try:
        kernel32 = _windows_kernel32()
        terminated = bool(kernel32.TerminateJobObject(wintypes.HANDLE(job_handle), 1))
    except Exception:
        terminated = False
    finally:
        if kernel32 is not None:
            try:
                closed = bool(kernel32.CloseHandle(wintypes.HANDLE(job_handle)))
            except Exception:
                closed = False
    return terminated and closed


def _find_initial_windows_thread_id(process: object) -> int | None:
    """Find the one primary thread created by CREATE_SUSPENDED, or fail closed."""

    process_id = getattr(process, "pid", None)
    if (
        not isinstance(process_id, int)
        or isinstance(process_id, bool)
        or process_id <= 0
    ):
        return None
    deadline = time.monotonic() + _INITIAL_THREAD_DISCOVERY_TIMEOUT_SECONDS
    while True:
        try:
            kernel32 = _windows_kernel32()
            snapshot = _windows_handle_value(
                kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPTHREAD, 0)
            )
        except Exception:
            return None
        if snapshot is None:
            return None
        thread_ids: list[int] = []
        try:
            entry = _ThreadEntry32()
            entry.dwSize = ctypes.sizeof(entry)
            ctypes.set_last_error(0)
            if not kernel32.Thread32First(
                wintypes.HANDLE(snapshot), ctypes.byref(entry)
            ):
                return None
            while True:
                if int(entry.th32OwnerProcessID) == process_id:
                    thread_ids.append(int(entry.th32ThreadID))
                ctypes.set_last_error(0)
                if kernel32.Thread32Next(
                    wintypes.HANDLE(snapshot), ctypes.byref(entry)
                ):
                    continue
                if ctypes.get_last_error() not in (0, _ERROR_NO_MORE_FILES):
                    return None
                break
        except Exception:
            return None
        finally:
            try:
                kernel32.CloseHandle(wintypes.HANDLE(snapshot))
            except Exception:
                pass
        if len(thread_ids) == 1:
            return thread_ids[0]
        if len(thread_ids) > 1 or time.monotonic() >= deadline:
            return None
        time.sleep(0.005)


def _resume_suspended_windows_process(process: object) -> bool:
    """Resume only the verified initial thread after its process owns a Job."""

    thread_id = _find_initial_windows_thread_id(process)
    if thread_id is None:
        return False
    thread_handle: int | None = None
    try:
        kernel32 = _windows_kernel32()
        thread_handle = _windows_handle_value(
            kernel32.OpenThread(_THREAD_SUSPEND_RESUME, False, thread_id)
        )
        if thread_handle is None:
            return False
        previous_suspend_count = int(
            kernel32.ResumeThread(wintypes.HANDLE(thread_handle))
        )
        return previous_suspend_count == 1
    except Exception:
        return False
    finally:
        if thread_handle is not None:
            try:
                kernel32.CloseHandle(wintypes.HANDLE(thread_handle))
            except Exception:
                pass


def _process_returncode(process: object) -> int | None:
    try:
        result = getattr(process, "returncode")
    except AttributeError:
        return None
    return result if isinstance(result, int) else None


def _poll_process(process: object) -> int | None:
    try:
        result = getattr(process, "poll")()
    except (AttributeError, OSError, TypeError, ValueError, subprocess.SubprocessError):
        return None
    return result if isinstance(result, int) else None


def _wait_for_process(process: object, timeout_seconds: float) -> int | None:
    try:
        result = getattr(process, "wait")(timeout=timeout_seconds)
    except (AttributeError, OSError, TypeError, ValueError, subprocess.SubprocessError):
        return _process_returncode(process)
    return result if isinstance(result, int) else _process_returncode(process)


def _terminate_direct_process(process: object) -> int | None:
    if _poll_process(process) is None:
        try:
            getattr(process, "terminate")()
        except (AttributeError, OSError, TypeError, ValueError, subprocess.SubprocessError):
            pass
    result = _wait_for_process(process, 0.5)
    if result is not None:
        return result
    try:
        getattr(process, "kill")()
    except (AttributeError, OSError, TypeError, ValueError, subprocess.SubprocessError):
        pass
    return _wait_for_process(process, 0.5)


def _terminate_suspended_windows_process(
    process: object, tree: _ProcessTree | None
) -> int | None:
    """Close owned Job state and directly reap a process that never ran user code."""

    if tree is not None:
        try:
            _terminate_process_tree(tree)
        except Exception:
            pass
    return _terminate_direct_process(process)


def _establish_process_tree(process: object) -> _ProcessTree | None:
    if os.name == "nt":
        job_handle = _assign_windows_job(process)
        return None if job_handle is None else _ProcessTree(process, job_handle=job_handle)
    process_group_id = getattr(process, "pid", None)
    if not isinstance(process_group_id, int) or isinstance(process_group_id, bool) or process_group_id <= 0:
        return None
    return _ProcessTree(process, process_group_id=process_group_id)


def _signal_process_group(process_group_id: int, signal_value: int) -> bool:
    try:
        os.killpg(process_group_id, signal_value)
        return True
    except ProcessLookupError:
        return True
    except (OSError, ValueError):
        return False


def _terminate_process_tree(tree: _ProcessTree) -> bool:
    """Stop the entire owned tree before closing its pipe handles."""

    if tree.closed:
        return True
    tree.closed = True
    if os.name == "nt":
        job_handle = tree.job_handle
        tree.job_handle = None
        if job_handle is None:
            _terminate_direct_process(tree.process)
            return False
        return _terminate_windows_job(job_handle)
    process_group_id = tree.process_group_id
    if process_group_id is None:
        _terminate_direct_process(tree.process)
        return False
    first_signal = _signal_process_group(process_group_id, signal.SIGTERM)
    if first_signal:
        time.sleep(0.05)
        second_signal = _signal_process_group(process_group_id, signal.SIGKILL)
        return second_signal
    _terminate_direct_process(tree.process)
    return False


def _read_available(stream: object, count: int) -> bytes:
    reader = getattr(stream, "read1", None)
    if callable(reader):
        return reader(count)
    descriptor = getattr(stream, "fileno")()
    return os.read(descriptor, count)


def _close_streams(streams: tuple[object | None, object | None]) -> None:
    for stream in streams:
        if stream is None:
            continue
        try:
            getattr(stream, "close")()
        except (AttributeError, OSError, TypeError, ValueError):
            pass


def _run_bounded_process(
    command: list[str], *, timeout_seconds: float, output_limit: int
) -> _BoundedProcessResult:
    """Run a fixed argument vector while keeping both pipe buffers bounded."""

    if not command or timeout_seconds <= 0 or output_limit < 1:
        return _BoundedProcessResult(-1, b"", b"", False, False, True, False)
    popen_arguments: dict[str, object] = {
        "shell": False,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
    }
    windows_suspended = os.name == "nt"
    if windows_suspended:
        popen_arguments["creationflags"] = _CREATE_SUSPENDED
    else:
        popen_arguments["start_new_session"] = True
    try:
        process = subprocess.Popen(command, **popen_arguments)
    except (OSError, ValueError, subprocess.SubprocessError):
        return _BoundedProcessResult(-1, b"", b"", False, False, True, False)

    tree = _establish_process_tree(process)
    if tree is None:
        streams = (getattr(process, "stdout", None), getattr(process, "stderr", None))
        returncode = _terminate_direct_process(process)
        _close_streams(streams)
        return _BoundedProcessResult(
            returncode if isinstance(returncode, int) else -1,
            b"",
            b"",
            False,
            False,
            True,
            False,
        )
    if windows_suspended:
        try:
            resumed = _resume_suspended_windows_process(process)
        except Exception:
            resumed = False
        if not resumed:
            returncode = _terminate_suspended_windows_process(process, tree)
            streams = (getattr(process, "stdout", None), getattr(process, "stderr", None))
            _close_streams(streams)
            return _BoundedProcessResult(
                returncode if isinstance(returncode, int) else -1,
                b"",
                b"",
                False,
                False,
                True,
                False,
            )

    streams = (getattr(process, "stdout", None), getattr(process, "stderr", None))

    stdout_buffer = bytearray()
    stderr_buffer = bytearray()
    state_lock = threading.Lock()
    stop_requested = threading.Event()
    overflow = False
    read_failed = False

    def drain(stream: object, target: bytearray) -> None:
        nonlocal overflow, read_failed
        try:
            while True:
                with state_lock:
                    read_size = output_limit - len(target) + 1
                    if read_size < 1:
                        read_size = 1
                chunk = _read_available(stream, read_size)
                if not chunk:
                    return
                if not isinstance(chunk, bytes):
                    raise OSError("process pipe produced text instead of bytes")
                with state_lock:
                    remaining = output_limit - len(target)
                    if remaining <= 0 or len(chunk) > remaining:
                        if remaining > 0:
                            target.extend(chunk[:remaining])
                        overflow = True
                        stop_requested.set()
                    else:
                        target.extend(chunk)
        except (AttributeError, OSError, TypeError, ValueError):
            with state_lock:
                read_failed = True
                stop_requested.set()

    if any(stream is None for stream in streams):
        _terminate_process_tree(tree)
        returncode = _wait_for_process(process, 0.5)
        _close_streams(streams)
        return _BoundedProcessResult(
            returncode if isinstance(returncode, int) else -1,
            b"",
            b"",
            False,
            False,
            False,
            True,
        )
    readers = (
        threading.Thread(target=drain, args=(streams[0], stdout_buffer)),
        threading.Thread(target=drain, args=(streams[1], stderr_buffer)),
    )
    for reader in readers:
        reader.start()

    timed_out = False
    deadline = time.monotonic() + timeout_seconds
    returncode: int | None = None
    tree_stopped = True
    try:
        while True:
            try:
                observed = getattr(process, "poll")()
            except (OSError, ValueError, subprocess.SubprocessError):
                with state_lock:
                    read_failed = True
                stop_requested.set()
                observed = None
            if stop_requested.is_set():
                tree_stopped = _terminate_process_tree(tree)
                returncode = _wait_for_process(process, 0.5)
                break
            if observed is not None:
                returncode = observed if isinstance(observed, int) else None
                tree_stopped = _terminate_process_tree(tree)
                break
            if time.monotonic() >= deadline:
                timed_out = True
                tree_stopped = _terminate_process_tree(tree)
                returncode = _wait_for_process(process, 0.5)
                break
            time.sleep(0.005)
        returncode = _wait_for_process(process, 0.5)
    finally:
        if not tree.closed:
            tree_stopped = _terminate_process_tree(tree) and tree_stopped
        if returncode is None:
            returncode = _wait_for_process(process, 0.5)
        for reader in readers:
            reader.join(timeout=1)
        _close_streams(streams)
        for reader in readers:
            reader.join(timeout=0.25)
        if not tree_stopped or any(reader.is_alive() for reader in readers):
            with state_lock:
                read_failed = True
    with state_lock:
        return _BoundedProcessResult(
            returncode if isinstance(returncode, int) else -1,
            bytes(stdout_buffer),
            bytes(stderr_buffer),
            overflow,
            timed_out,
            False,
            read_failed,
        )


def _limited_text(value: object) -> str | None:
    if isinstance(value, bytes):
        if len(value) > MAX_SCHEMA_OUTPUT_BYTES:
            return None
        return value.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    if not isinstance(value, str) or not _is_utf8_text(value):
        return None
    if len(value.encode("utf-8", errors="replace")) > MAX_SCHEMA_OUTPUT_BYTES:
        return None
    return value


def _git_command(runtime_root: Path, arguments: list[str]) -> str | None:
    completed = _run_bounded_process(
        ["git", "-C", str(runtime_root), *arguments],
        timeout_seconds=PROCESS_TIMEOUT_SECONDS,
        output_limit=MAX_SCHEMA_OUTPUT_BYTES,
    )
    if (
        completed.overflow
        or completed.timed_out
        or completed.spawn_failed
        or completed.read_failed
    ):
        return None
    stdout = _limited_text(completed.stdout)
    stderr = _limited_text(completed.stderr)
    if completed.returncode != 0 or stdout is None or stderr is None or stderr:
        return None
    return stdout


def _runtime_snapshot(runtime_root: Path, schema_relative_path: str) -> tuple[str, str] | None:
    head = _git_command(runtime_root, ["rev-parse", "HEAD"])
    status = _git_command(runtime_root, ["status", "--porcelain"])
    tracked = _git_command(runtime_root, ["ls-files", "--error-unmatch", "--", schema_relative_path])
    if head is None or status is None or tracked is None:
        return None
    normalized_head = head.strip()
    if len(normalized_head) != 40 or any(character not in "0123456789abcdef" for character in normalized_head.lower()):
        return None
    if status.strip() or schema_relative_path not in {line.strip() for line in tracked.splitlines()}:
        return None
    try:
        schema_path = (runtime_root / schema_relative_path).resolve(strict=True)
        if not schema_path.is_relative_to(runtime_root) or not schema_path.is_file() or _is_link_or_junction(schema_path):
            return None
        return normalized_head, sha256_file(schema_path)
    except (OSError, UnicodeError, ValueError):
        return None


def _parse_schema_errors(output: str) -> list[dict[str, object]] | None:
    if output.endswith("\n"):
        output = output[:-1]
    if not output or output != output.strip():
        return None
    try:
        parsed = json.loads(output)
    except (json.JSONDecodeError, RecursionError, UnicodeError, ValueError, TypeError):
        return None
    if not isinstance(parsed, list) or len(parsed) > 1024:
        return None
    normalized: list[dict[str, object]] = []
    for item in parsed:
        if not isinstance(item, dict) or set(item) != {"path", "message"}:
            return None
        path = item.get("path")
        message = item.get("message")
        if not isinstance(path, list) or len(path) > 128 or not isinstance(message, str) or not _is_utf8_text(message):
            return None
        if any(
            (
                not isinstance(segment, (str, int))
                or isinstance(segment, bool)
                or (isinstance(segment, str) and not _is_utf8_text(segment))
            )
            for segment in path
        ):
            return None
        normalized.append({"path": list(path), "message": message})
    return normalized


def authoritative_schema_check(
    manifest: ManifestData,
    format_version: int,
    runtime_repo: Path | None,
    runtime_python: Path | None,
) -> PackageCheck:
    if runtime_repo is None or runtime_python is None:
        return PackageCheck(
            "SCHEMA_VALIDATION",
            "unverified",
            "runtime schema authority was not supplied",
            {"reason": "runtime_repo and runtime_python are both required"},
        )
    try:
        if _is_link_or_junction(runtime_repo) or not runtime_repo.is_dir():
            raise ValueError
        runtime_root = runtime_repo.resolve(strict=True)
        if _is_link_or_junction(runtime_python) or not runtime_python.is_file():
            raise ValueError
        schema_relative_path = f"schemas/pet-pack-v{format_version}.schema.json"
        schema_path = (runtime_root / schema_relative_path).resolve(strict=True)
        if not schema_path.is_relative_to(runtime_root) or not schema_path.is_file():
            raise ValueError
    except (OSError, UnicodeError, ValueError):
        return PackageCheck(
            "SCHEMA_VALIDATION",
            "unverified",
            "runtime schema authority is not readable",
            {},
        )
    before = _runtime_snapshot(runtime_root, schema_relative_path)
    if before is None:
        return PackageCheck(
            "SCHEMA_VALIDATION",
            "unverified",
            "runtime schema authority is missing, dirty, or unstable",
            {},
        )
    completed = _run_bounded_process(
        [
            str(runtime_python),
            "-c",
            SCHEMA_PROGRAM,
            str(schema_path),
            str(manifest.manifest_path),
        ],
        timeout_seconds=PROCESS_TIMEOUT_SECONDS,
        output_limit=MAX_SCHEMA_OUTPUT_BYTES,
    )
    if (
        completed.overflow
        or completed.timed_out
        or completed.spawn_failed
        or completed.read_failed
    ):
        return PackageCheck(
            "SCHEMA_VALIDATION",
            "unverified",
            "runtime schema process could not be verified",
            {},
        )
    stdout = _limited_text(completed.stdout)
    stderr = _limited_text(completed.stderr)
    after = _runtime_snapshot(runtime_root, schema_relative_path)
    if stdout is None or stderr is None or stderr or after is None or before != after:
        return PackageCheck(
            "SCHEMA_VALIDATION",
            "unverified",
            "runtime schema authority changed or returned unverifiable output",
            {},
        )
    errors = _parse_schema_errors(stdout)
    evidence = {
        "schemaPath": schema_relative_path,
        "schemaSha256": before[1],
        "runtimeCommit": before[0],
    }
    if completed.returncode == 0 and errors == []:
        return PackageCheck("SCHEMA_VALIDATION", "pass", "runtime schema passed", evidence)
    if completed.returncode == 1 and errors:
        evidence["errors"] = errors
        return PackageCheck(
            "SCHEMA_VALIDATION", "blocked", "runtime schema rejected manifest", evidence
        )
    return PackageCheck(
        "SCHEMA_VALIDATION",
        "unverified",
        "runtime schema process returned an unsupported result",
        evidence,
    )


def stable_manifest(manifest: ManifestData) -> bool:
    try:
        with manifest.manifest_path.open("rb") as source:
            raw = source.read(MAX_MANIFEST_BYTES + 1)
        return (
            len(raw) <= MAX_MANIFEST_BYTES
            and hashlib.sha256(raw).hexdigest() == manifest.manifest_sha256
        )
    except (OSError, ValueError, UnicodeError):
        return False


def report_for(
    checks: tuple[PackageCheck, ...], format_version: int | None
) -> dict[str, object]:
    statuses = {check.status for check in checks}
    if "blocked" in statuses or statuses - VALID_STATUSES:
        status = "blocked"
    elif "unverified" in statuses or not checks:
        status = "unverified"
    else:
        status = "pass"
    return {
        "formatVersion": format_version,
        "status": status,
        "checks": [check.to_dict() for check in checks],
        "packageStatus": "local-candidate",
        "runtimeStatus": "unverified",
        "installedStatus": "not-authorized",
        "releaseAuthority": False,
    }
