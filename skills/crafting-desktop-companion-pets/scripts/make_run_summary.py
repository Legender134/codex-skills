"""Build a bounded, read-only evidence summary for one DesktopCompanion run."""

from __future__ import annotations

import argparse
import ctypes
from dataclasses import dataclass
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import stat
import sys

from contracts import evaluate_maturity, validate_json_structure


if os.name == "nt":
    import msvcrt


MAX_RUN_ENTRIES = 4096
MAX_RUN_FILE_BYTES = 64 * 1024 * 1024
MAX_RUN_TOTAL_BYTES = 256 * 1024 * 1024
MAX_RUN_PATH_LENGTH = 240
MAX_RUN_DEPTH = 32
MAX_DRAFT_BYTES = 1024 * 1024
_CHUNK_SIZE = 1024 * 1024
_AT_FDCWD = -100
_AT_SYMLINK_FOLLOW = 0x400
_AT_EMPTY_PATH = 0x1000
_CLASSIFICATIONS = (
    ("keep", "keep"),
    ("archiveCandidate", "archive-candidate"),
    ("cleanupCandidate", "cleanup-candidate"),
    ("uncertainUserOwned", "uncertain-user-owned"),
)


class InputError(Exception):
    """A malformed invocation or unsafe input that must leave output unchanged."""


def _using_windows() -> bool:
    """A narrow platform seam for deterministic descriptor-rooted tests."""
    return os.name == "nt"


if os.name == "nt":
    _GENERIC_READ = 0x80000000
    _GENERIC_WRITE = 0x40000000
    _DELETE = 0x00010000
    _FILE_READ_ATTRIBUTES = 0x80
    _FILE_WRITE_ATTRIBUTES = 0x100
    _FILE_SHARE_READ = 0x1
    _FILE_SHARE_WRITE = 0x2
    _FILE_SHARE_DELETE = 0x4
    _CREATE_NEW = 1
    _OPEN_EXISTING = 3
    _FILE_ATTRIBUTE_NORMAL = 0x80
    _FILE_ATTRIBUTE_REPARSE_POINT = 0x400
    _FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
    _FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
    _FILE_BASIC_INFO_CLASS = 0
    _FILE_RENAME_INFO_CLASS = 3
    _FILE_DISPOSITION_INFO_CLASS = 4
    _INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    class _ByHandleFileInformation(ctypes.Structure):
        _fields_ = [
            ("dwFileAttributes", ctypes.c_uint32),
            ("ftCreationTimeLow", ctypes.c_uint32),
            ("ftCreationTimeHigh", ctypes.c_uint32),
            ("ftLastAccessTimeLow", ctypes.c_uint32),
            ("ftLastAccessTimeHigh", ctypes.c_uint32),
            ("ftLastWriteTimeLow", ctypes.c_uint32),
            ("ftLastWriteTimeHigh", ctypes.c_uint32),
            ("dwVolumeSerialNumber", ctypes.c_uint32),
            ("nFileSizeHigh", ctypes.c_uint32),
            ("nFileSizeLow", ctypes.c_uint32),
            ("nNumberOfLinks", ctypes.c_uint32),
            ("nFileIndexHigh", ctypes.c_uint32),
            ("nFileIndexLow", ctypes.c_uint32),
        ]

    class _FileBasicInformation(ctypes.Structure):
        _fields_ = [
            ("CreationTime", ctypes.c_int64),
            ("LastAccessTime", ctypes.c_int64),
            ("LastWriteTime", ctypes.c_int64),
            ("ChangeTime", ctypes.c_int64),
            ("FileAttributes", ctypes.c_uint32),
        ]

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _create_file = _kernel32.CreateFileW
    _create_file.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    _create_file.restype = ctypes.c_void_p
    _get_file_information = _kernel32.GetFileInformationByHandle
    _get_file_information.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_ByHandleFileInformation),
    ]
    _get_file_information.restype = ctypes.c_int
    _close_handle = _kernel32.CloseHandle
    _close_handle.argtypes = [ctypes.c_void_p]
    _close_handle.restype = ctypes.c_int
    _set_file_information = _kernel32.SetFileInformationByHandle
    _set_file_information.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
    ]
    _set_file_information.restype = ctypes.c_int

    class _FileRenameInformation(ctypes.Structure):
        _fields_ = [
            ("Flags", ctypes.c_uint32),
            ("RootDirectory", ctypes.c_void_p),
            ("FileNameLength", ctypes.c_uint32),
            ("FileName", ctypes.c_wchar * 1),
        ]

    class _FileDispositionInformation(ctypes.Structure):
        _fields_ = [("DeleteFile", ctypes.c_ubyte)]


def _windows_open_descriptor(
    path: Path,
    *,
    directory: bool,
    share_mode: int | None = None,
    desired_access: int | None = None,
    creation_disposition: int | None = None,
    suppress_metadata_updates: bool = False,
) -> int:
    """Open one Windows object without following a final reparse point.

    The generic-read request is deliberate: FILE_READ_ATTRIBUTES alone does not
    participate in the delete-sharing rule that blocks rename and deletion.
    """
    if not _using_windows():
        raise RuntimeError("Windows descriptor requested on a non-Windows host")
    flags = _FILE_FLAG_OPEN_REPARSE_POINT
    if directory:
        flags |= _FILE_FLAG_BACKUP_SEMANTICS
    access = (
        _GENERIC_READ | _FILE_READ_ATTRIBUTES
        if desired_access is None
        else desired_access
    )
    if suppress_metadata_updates:
        access |= _FILE_WRITE_ATTRIBUTES
    handle = _create_file(
        str(path),
        access,
        _FILE_SHARE_READ | _FILE_SHARE_WRITE if share_mode is None else share_mode,
        None,
        _OPEN_EXISTING if creation_disposition is None else creation_disposition,
        flags | (_FILE_ATTRIBUTE_NORMAL if not directory else 0),
        None,
    )
    if handle is None or handle == _INVALID_HANDLE_VALUE:
        raise OSError(ctypes.get_last_error(), f"cannot safely open {path}")
    if suppress_metadata_updates:
        try:
            _windows_suppress_metadata_updates(ctypes.c_void_p(handle))
        except OSError as suppression_error:
            if not _close_handle(handle):
                raise InputError(
                    f"cannot suppress metadata updates for {path}; "
                    "CloseHandle also failed"
                ) from suppression_error
            raise InputError(
                f"cannot suppress metadata updates for {path}: {suppression_error}"
            ) from suppression_error
    try:
        open_flags = (
            os.O_RDWR
            if desired_access is not None
            and desired_access & _GENERIC_WRITE
            else os.O_RDONLY
        )
        return msvcrt.open_osfhandle(handle, open_flags | getattr(os, "O_BINARY", 0))
    except OSError as conversion_error:
        if not _close_handle(handle):
            raise OSError(
                ctypes.get_last_error(),
                f"CloseHandle failed while releasing {path}",
            ) from conversion_error
        raise


def _windows_suppress_metadata_updates(handle: ctypes.c_void_p) -> None:
    """Freeze the I/O-updated timestamps on this live Windows read handle."""
    information = _FileBasicInformation(
        0,  # preserve creation time
        -1,  # suppress access-time updates
        -1,  # suppress write-time updates
        -1,  # suppress change-time updates
        0,  # preserve attributes
    )
    ctypes.set_last_error(0)
    if not _set_file_information(
        handle,
        _FILE_BASIC_INFO_CLASS,
        ctypes.byref(information),
        ctypes.sizeof(information),
    ):
        raise OSError(
            ctypes.get_last_error(), "FileBasicInfo metadata-update suppression failed"
        )


def _windows_handle_information(descriptor: int) -> tuple[int, ...]:
    if not _using_windows():
        raise RuntimeError("Windows handle information requested on a non-Windows host")
    handle = msvcrt.get_osfhandle(descriptor)
    if handle == -1:
        raise OSError("cannot recover the Windows handle")
    information = _ByHandleFileInformation()
    if not _get_file_information(handle, ctypes.byref(information)):
        raise OSError(ctypes.get_last_error(), "GetFileInformationByHandle failed")
    return (
        information.dwFileAttributes,
        information.dwVolumeSerialNumber,
        information.nFileIndexHigh,
        information.nFileIndexLow,
        information.nFileSizeHigh,
        information.nFileSizeLow,
        information.ftLastWriteTimeHigh,
        information.ftLastWriteTimeLow,
        information.nNumberOfLinks,
    )


def _windows_handle_link_count(descriptor: int) -> int:
    """Read the link count from the live handle, never a mutable pathname."""
    information = _windows_handle_information(descriptor)
    return information[-1]


def _windows_handle(descriptor: int) -> ctypes.c_void_p:
    handle = msvcrt.get_osfhandle(descriptor)
    if handle == -1:
        raise OSError("cannot recover the Windows handle")
    return ctypes.c_void_p(handle)


def _windows_mark_handle_for_delete(descriptor: int) -> None:
    information = _FileDispositionInformation(DeleteFile=1)
    if not _set_file_information(
        _windows_handle(descriptor),
        _FILE_DISPOSITION_INFO_CLASS,
        ctypes.byref(information),
        ctypes.sizeof(information),
    ):
        raise OSError(ctypes.get_last_error(), "FileDispositionInfo failed")


def _windows_rename_handle_no_replace(descriptor: int, destination: Path) -> None:
    """Atomically bind an open temporary object to an absent absolute destination."""
    destination_text = str(destination)
    encoded = destination_text.encode("utf-16-le")
    if not encoded or len(encoded) > 0xFFFFFFFF:
        raise InputError("invalid summary output destination")
    # FILE_RENAME_INFO has a WCHAR[1] tail.  Leave both an explicit terminator and
    # conservative tail padding; FileNameLength intentionally excludes the NUL.
    buffer_size = ctypes.sizeof(_FileRenameInformation) + len(encoded) + 2
    storage = (ctypes.c_byte * buffer_size)()
    information = _FileRenameInformation.from_buffer(storage)
    information.Flags = 0  # ReplaceIfExists is deliberately false.
    information.RootDirectory = None
    information.FileNameLength = len(encoded)
    encoded_with_nul = encoded + b"\x00\x00"
    ctypes.memmove(
        ctypes.addressof(information) + _FileRenameInformation.FileName.offset,
        encoded_with_nul,
        len(encoded_with_nul),
    )
    if not _set_file_information(
        _windows_handle(descriptor),
        _FILE_RENAME_INFO_CLASS,
        ctypes.byref(information),
        buffer_size,
    ):
        raise OSError(ctypes.get_last_error(), "FileRenameInfo no-replace failed")


def _windows_info_is_reparse_point(information: tuple[int, ...] | None) -> bool:
    return bool(
        information is not None
        and information[0] & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")


def _reject_nonstandard_json_constant(value: str) -> object:
    raise ValueError(f"non-standard JSON constant: {value}")


def _reject_duplicate_json_object_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def _is_utf8_text(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _is_sha256(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _absolute_path(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _is_reparse_point(metadata: os.stat_result) -> bool:
    attributes = getattr(metadata, "st_file_attributes", 0) or 0
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _identity(metadata: os.stat_result) -> tuple[int, int, int, int, int, int]:
    """Identity for a protected regular object, including content-change metadata."""
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        getattr(metadata, "st_ctime_ns", metadata.st_ctime),
        metadata.st_nlink,
    )


def _directory_identity(metadata: os.stat_result) -> tuple[int, int]:
    return metadata.st_dev, metadata.st_ino


def _windows_object_identity(information: tuple[int, ...] | None) -> tuple[int, ...] | None:
    if information is None:
        return None
    return information[:4]


def _same_regular_identity(
    first: os.stat_result, second: os.stat_result
) -> bool:
    return (
        stat.S_ISREG(first.st_mode)
        and stat.S_ISREG(second.st_mode)
        and not _is_reparse_point(first)
        and not _is_reparse_point(second)
        and _identity(first) == _identity(second)
    )


def _same_regular_path_binding(
    first: os.stat_result, second: os.stat_result
) -> bool:
    """Compare a pathname to a held object without trusting delayed Windows ctime."""
    return (
        stat.S_ISREG(first.st_mode)
        and stat.S_ISREG(second.st_mode)
        and not _is_reparse_point(first)
        and not _is_reparse_point(second)
        and (
            first.st_dev,
            first.st_ino,
            first.st_size,
            first.st_mtime_ns,
            first.st_nlink,
        )
        == (
            second.st_dev,
            second.st_ino,
            second.st_size,
            second.st_mtime_ns,
            second.st_nlink,
        )
    )


def _same_protected_regular_identity(
    first: os.stat_result, second: os.stat_result
) -> bool:
    """Use ctime on POSIX; Windows verifies its stable native handle metadata."""
    if not _using_windows():
        return _same_regular_identity(first, second)
    return _same_regular_path_binding(first, second)


def _same_directory_identity(
    first: os.stat_result, second: os.stat_result
) -> bool:
    return (
        stat.S_ISDIR(first.st_mode)
        and stat.S_ISDIR(second.st_mode)
        and not _is_reparse_point(first)
        and not _is_reparse_point(second)
        and _directory_identity(first) == _directory_identity(second)
    )


def _close_descriptor(descriptor: int, *, subject: str) -> None:
    try:
        os.close(descriptor)
    except OSError as error:
        raise InputError(f"cannot close protected {subject}: {error}") from error


def _open_posix_directory_descriptor(
    name: str | Path, *, parent_descriptor: int | None = None
) -> int:
    """Open a directory by descriptor, never by a reparsed child path."""
    directory_flag = getattr(os, "O_DIRECTORY", 0)
    nofollow_flag = getattr(os, "O_NOFOLLOW", 0)
    if not isinstance(directory_flag, int) or directory_flag == 0:
        raise InputError("POSIX O_DIRECTORY capability is required")
    if not isinstance(nofollow_flag, int) or nofollow_flag == 0:
        raise InputError("POSIX O_NOFOLLOW capability is required")
    flags = os.O_RDONLY | directory_flag | nofollow_flag
    flags |= getattr(os, "O_CLOEXEC", 0)
    try:
        if parent_descriptor is None:
            return os.open(os.fspath(name), flags)
        return os.open(os.fspath(name), flags, dir_fd=parent_descriptor)
    except (TypeError, NotImplementedError) as error:
        raise InputError("POSIX descriptor-rooted directory open is unavailable") from error


def _before_directory_component_open(parent_path: Path, component: str) -> None:
    """Deterministic test seam after a parent has been held, before child descent."""


@dataclass(frozen=True)
class _HeldDirectory:
    path: Path
    metadata: os.stat_result
    descriptor: int
    native_information: tuple[int, ...] | None


def _directory_record_is_stable(record: _HeldDirectory) -> None:
    try:
        current = os.fstat(record.descriptor)
        native_information = (
            _windows_handle_information(record.descriptor) if _using_windows() else None
        )
    except OSError as error:
        raise InputError(
            f"cannot inspect protected directory: {record.path}: {error}"
        ) from error
    changed = not _same_directory_identity(record.metadata, current)
    if _using_windows():
        changed = changed or _windows_info_is_reparse_point(native_information)
        changed = changed or (
            _windows_object_identity(native_information)
            != _windows_object_identity(record.native_information)
        )
    if changed:
        raise InputError(f"protected directory changed: {record.path}")


def _validate_held_directory(record: _HeldDirectory) -> None:
    if (
        not stat.S_ISDIR(record.metadata.st_mode)
        or _is_reparse_point(record.metadata)
        or _windows_info_is_reparse_point(record.native_information)
    ):
        raise InputError(f"directory is unsafe or changed: {record.path}")


def _open_windows_directory_chain(path: Path) -> tuple[_HeldDirectory, list[_HeldDirectory]]:
    """Hold the drive root and every path component against delete/rename races."""
    absolute = _absolute_path(path)
    raw = str(absolute)
    drive, tail = os.path.splitdrive(raw)
    if not drive or raw.startswith("\\\\") or not tail.startswith(("\\", "/")):
        raise InputError(f"Windows path has an unsupported root: {absolute}")
    root_path = Path(drive + "\\")
    components = [piece for piece in Path(tail).parts if piece not in {"\\", "/"}]
    records: list[_HeldDirectory] = []
    try:
        descriptor = _windows_open_descriptor(root_path, directory=True)
        record = _HeldDirectory(
            root_path,
            os.fstat(descriptor),
            descriptor,
            _windows_handle_information(descriptor),
        )
        _validate_held_directory(record)
        records.append(record)
        current_path = root_path
        for component in components:
            _directory_record_is_stable(records[-1])
            _before_directory_component_open(current_path, component)
            current_path = current_path / component
            descriptor = _windows_open_descriptor(current_path, directory=True)
            record = _HeldDirectory(
                current_path,
                os.fstat(descriptor),
                descriptor,
                _windows_handle_information(descriptor),
            )
            _validate_held_directory(record)
            records.append(record)
    except BaseException:
        for record in reversed(records):
            try:
                _close_descriptor(record.descriptor, subject=f"directory {record.path}")
            except InputError:
                pass
        raise
    if not records:
        raise InputError(f"cannot access directory {absolute}")
    return records[-1], records[:-1]


def _open_posix_directory_chain(path: Path) -> tuple[_HeldDirectory, list[_HeldDirectory]]:
    """Descend an absolute path from '/' using retained O_NOFOLLOW descriptors."""
    absolute = _absolute_path(path)
    if not absolute.is_absolute() or absolute.anchor != os.path.sep:
        raise InputError(f"POSIX path has an unsupported root: {absolute}")
    components = [piece for piece in absolute.parts if piece != absolute.anchor]
    records: list[_HeldDirectory] = []
    try:
        descriptor = _open_posix_directory_descriptor(os.path.sep)
        record = _HeldDirectory(os.path.sep and Path(os.path.sep), os.fstat(descriptor), descriptor, None)
        _validate_held_directory(record)
        records.append(record)
        current_path = Path(os.path.sep)
        for component in components:
            _directory_record_is_stable(records[-1])
            _before_directory_component_open(current_path, component)
            current_path = current_path / component
            descriptor = _open_posix_directory_descriptor(
                component, parent_descriptor=records[-1].descriptor
            )
            record = _HeldDirectory(current_path, os.fstat(descriptor), descriptor, None)
            _validate_held_directory(record)
            records.append(record)
    except BaseException:
        for record in reversed(records):
            try:
                _close_descriptor(record.descriptor, subject=f"directory {record.path}")
            except InputError:
                pass
        raise
    return records[-1], records[:-1]


class _DirectoryLock:
    """Retain one descriptor-rooted directory for a sensitive operation."""

    def __init__(
        self,
        path: Path,
        metadata: os.stat_result,
        descriptor: int,
        native_information: tuple[int, ...] | None,
        ancestors: list[_HeldDirectory] | None = None,
    ) -> None:
        self.path = path
        self._metadata = metadata
        self._descriptor: int | None = descriptor
        self._native_information = native_information
        self._ancestors = list(ancestors or [])

    def _records(self) -> list[_HeldDirectory]:
        descriptor = self.descriptor
        return [
            *self._ancestors,
            _HeldDirectory(self.path, self._metadata, descriptor, self._native_information),
        ]

    @property
    def descriptor(self) -> int:
        if self._descriptor is None:
            raise InputError(f"protected directory was already closed: {self.path}")
        return self._descriptor

    def __enter__(self) -> _DirectoryLock:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def assert_stable(self) -> None:
        for record in self._records():
            _directory_record_is_stable(record)

    def assert_path_matches_handle(self) -> None:
        """Require each requested ancestor name to still name its held object."""
        self.assert_stable()
        for record in self._records():
            try:
                current = os.lstat(record.path)
            except OSError as error:
                raise InputError(
                    f"cannot recheck protected directory pathname: {record.path}: {error}"
                ) from error
            if not _same_directory_identity(record.metadata, current):
                raise InputError(f"protected directory path changed: {record.path}")

    def close(self) -> None:
        if self._descriptor is None:
            return
        descriptor, self._descriptor = self._descriptor, None
        records = [
            _HeldDirectory(self.path, self._metadata, descriptor, self._native_information),
            *reversed(self._ancestors),
        ]
        self._ancestors.clear()
        first_error: InputError | None = None
        for record in records:
            try:
                _close_descriptor(record.descriptor, subject=f"directory {record.path}")
            except InputError as error:
                if first_error is None:
                    first_error = error
        if first_error is not None:
            raise first_error


def _open_directory_lock(
    path: Path,
    expected: os.stat_result | None = None,
    *,
    parent_descriptor: int | None = None,
    entry_name: str | None = None,
) -> _DirectoryLock:
    """Open one real directory and retain a stable descriptor for it."""
    absolute = _absolute_path(path)
    descriptor: int | None = None
    ancestors: list[_HeldDirectory] = []
    try:
        if _using_windows():
            record, ancestors = _open_windows_directory_chain(absolute)
            descriptor = record.descriptor
            metadata = record.metadata
            native_information = record.native_information
            is_reparse = _windows_info_is_reparse_point(native_information)
        else:
            if parent_descriptor is None:
                record, ancestors = _open_posix_directory_chain(absolute)
                descriptor = record.descriptor
                metadata = record.metadata
                native_information = record.native_information
            elif entry_name is None:
                raise InputError("descriptor-rooted directory open requires an entry name")
            else:
                descriptor = _open_posix_directory_descriptor(
                    entry_name, parent_descriptor=parent_descriptor
                )
                metadata = os.fstat(descriptor)
                native_information = None
            is_reparse = _is_reparse_point(metadata)
    except InputError:
        raise
    except OSError as error:
        if descriptor is not None:
            _close_descriptor(descriptor, subject=f"directory {absolute}")
        for ancestor in reversed(ancestors):
            _close_descriptor(ancestor.descriptor, subject=f"directory {ancestor.path}")
        raise InputError(f"cannot access directory {absolute}: {error}") from error
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or _is_reparse_point(metadata)
        or is_reparse
        or (expected is not None and not _same_directory_identity(expected, metadata))
    ):
        if descriptor is not None:
            _close_descriptor(descriptor, subject=f"directory {absolute}")
        for ancestor in reversed(ancestors):
            _close_descriptor(ancestor.descriptor, subject=f"directory {ancestor.path}")
        raise InputError(f"directory is unsafe or changed: {absolute}")
    return _DirectoryLock(absolute, metadata, descriptor, native_information, ancestors)


def _after_directory_lock_open(lock: _DirectoryLock) -> None:
    """A deterministic boundary for tests that simulate a directory replacement."""


class _RunDirectoryLocks:
    def __init__(self, root: Path) -> None:
        self._root_path = _absolute_path(root)
        self._locks: list[_DirectoryLock] = []
        self.root: _DirectoryLock | None = None

    def __enter__(self) -> _RunDirectoryLocks:
        try:
            self.root = self.open(self._root_path)
        except BaseException:
            self._close_all()
            raise
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self._close_all()

    def _close_all(self) -> None:
        locks = list(reversed(self._locks))
        self._locks.clear()
        self.root = None
        first_error: InputError | None = None
        for lock in locks:
            try:
                lock.close()
            except InputError as error:
                if first_error is None:
                    first_error = error
        if first_error is not None:
            raise first_error

    def open(
        self,
        path: Path,
        expected: os.stat_result | None = None,
        *,
        parent_lock: _DirectoryLock | None = None,
        entry_name: str | None = None,
    ) -> _DirectoryLock:
        lock = _open_directory_lock(
            path,
            expected,
            parent_descriptor=(
                parent_lock.descriptor
                if parent_lock is not None and not _using_windows()
                else None
            ),
            entry_name=entry_name,
        )
        self._locks.append(lock)
        try:
            _after_directory_lock_open(lock)
        except BaseException:
            try:
                lock.close()
            finally:
                if self._locks and self._locks[-1] is lock:
                    self._locks.pop()
            raise
        return lock


def _normalized_relative_path(value: object) -> str | None:
    if (
        not _is_utf8_text(value)
        or not value
        or len(value) > MAX_RUN_PATH_LENGTH
        or "\\" in value
        or "\x00" in value
    ):
        return None
    candidate = PurePosixPath(value)
    if (
        candidate.is_absolute()
        or candidate.name in {"", ".", ".."}
        or any(part in {"", ".", ".."} for part in candidate.parts)
        or candidate.as_posix() != value
    ):
        return None
    return value


def _relative_path(root: Path, path: Path) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise InputError(f"run entry escapes root: {path}") from error
    normalized = relative.as_posix()
    if _normalized_relative_path(normalized) is None:
        raise InputError(f"run entry has an unsafe relative path: {normalized!r}")
    return normalized


def _before_regular_file_open(path: Path, expected: os.stat_result) -> None:
    """A deterministic boundary for tests that simulate a file replacement."""


def _open_regular_file_descriptor(
    path: Path,
    *,
    parent_descriptor: int | None = None,
    entry_name: str | None = None,
    share_mode: int | None = None,
    allow_missing: bool = False,
) -> tuple[int, tuple[int, ...] | None]:
    if _using_windows():
        descriptor = _windows_open_descriptor(
            path,
            directory=False,
            share_mode=share_mode,
            suppress_metadata_updates=True,
        )
        try:
            information = _windows_handle_information(descriptor)
        except OSError:
            _close_descriptor(descriptor, subject=f"file {path}")
            raise
        if _windows_info_is_reparse_point(information):
            _close_descriptor(descriptor, subject=f"file {path}")
            raise InputError(f"file is a reparse point: {path}")
        return descriptor, information
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    no_atime = getattr(os, "O_NOATIME", 0)
    if not isinstance(no_follow, int) or no_follow == 0:
        raise InputError("POSIX O_NOFOLLOW capability is required for regular reads")
    if not isinstance(no_atime, int) or no_atime == 0:
        raise InputError("POSIX O_NOATIME capability is required for regular reads")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | no_follow
        | no_atime
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        if parent_descriptor is not None:
            if entry_name is None:
                raise InputError("descriptor-rooted file open requires an entry name")
            return os.open(entry_name, flags, dir_fd=parent_descriptor), None
        return os.open(path, flags), None
    except FileNotFoundError:
        if allow_missing:
            raise
        raise InputError(f"cannot safely open regular file {path}: file is missing")
    except (TypeError, NotImplementedError) as error:
        raise InputError(
            "POSIX O_NOFOLLOW/O_NOATIME regular-read capability is unavailable"
        ) from error
    except OSError as error:
        raise InputError(f"cannot safely open regular file {path}: {error}") from error


def _stat_unfollowed(
    path: Path,
    *,
    parent_descriptor: int | None = None,
    entry_name: str | None = None,
) -> os.stat_result:
    if parent_descriptor is not None and not _using_windows():
        if entry_name is None:
            raise InputError("descriptor-rooted stat requires an entry name")
        try:
            return os.stat(entry_name, dir_fd=parent_descriptor, follow_symlinks=False)
        except (TypeError, NotImplementedError) as error:
            raise InputError("POSIX descriptor-rooted stat capability is required") from error
    return os.lstat(path)


class _ReadBudget:
    """Account actual bytes returned from stable file handles, never estimates."""

    def __init__(self, limit: int, *, subject: str) -> None:
        self._limit = limit
        self._subject = subject
        self.actual_bytes = 0

    def consume(self, size: int) -> None:
        if not isinstance(size, int) or size < 0:
            raise InputError(f"{self._subject} produced an invalid read length")
        if self.actual_bytes + size > self._limit:
            raise InputError(f"{self._subject} exceeds the actual-read byte ceiling")
        self.actual_bytes += size


def _read_expected_chunks(
    source: object,
    expected_size: int,
    budget: _ReadBudget,
    *,
    subject: str,
) -> list[bytes]:
    """Read exactly the snapshot size; post-read identity checks catch growth."""
    remaining = expected_size
    chunks: list[bytes] = []
    while remaining:
        request_size = min(_CHUNK_SIZE, remaining)
        chunk = source.read(request_size)  # type: ignore[attr-defined]
        if not isinstance(chunk, bytes) or len(chunk) > request_size:
            raise InputError(f"{subject} returned an invalid bounded read")
        if not chunk:
            raise InputError(f"{subject} shrank while reading")
        budget.consume(len(chunk))
        chunks.append(chunk)
        remaining -= len(chunk)
    return chunks


def _read_bounded_regular_file(
    path: Path,
    expected: os.stat_result,
    maximum_bytes: int,
    *,
    subject: str,
    parent_descriptor: int | None = None,
    entry_name: str | None = None,
) -> tuple[bytes, os.stat_result, tuple[int, ...] | None, tuple[int, ...] | None]:
    if expected.st_size > maximum_bytes:
        raise InputError(f"{subject} exceeds its byte ceiling")
    descriptor: int | None = None
    try:
        _before_regular_file_open(path, expected)
        descriptor, native_before = _open_regular_file_descriptor(
            path,
            parent_descriptor=parent_descriptor,
            entry_name=entry_name,
        )
        opened = os.fstat(descriptor)
        if not _same_protected_regular_identity(expected, opened):
            raise InputError(f"{subject} changed before reading")
        with os.fdopen(descriptor, "rb", closefd=False) as source:
            chunks = _read_expected_chunks(
                source,
                expected.st_size,
                _ReadBudget(expected.st_size, subject=subject),
                subject=subject,
            )
        contents = b"".join(chunks)
        after_open = os.fstat(descriptor)
        native_after = (
            _windows_handle_information(descriptor) if _using_windows() else None
        )
    except InputError:
        raise
    except OSError as error:
        raise InputError(f"cannot read {subject}: {error}") from error
    finally:
        if descriptor is not None:
            _close_descriptor(descriptor, subject=subject)
    return contents, after_open, native_before, native_after


@dataclass
class _InputSnapshot:
    """A hash-bound run input retained from inventory through native commit."""

    path: str
    filesystem_path: Path
    metadata: os.stat_result
    descriptor: int
    native_information: tuple[int, ...] | None
    parent_lock: _DirectoryLock
    entry_name: str
    sha256: str
    size: int
    contents: bytes | None = None
    _closed: bool = False

    def _live_descriptor(self) -> int:
        if self._closed:
            raise InputError(f"protected input was already closed: {self.path}")
        return self.descriptor

    def _assert_handle_identity(self) -> None:
        descriptor = self._live_descriptor()
        try:
            current = os.fstat(descriptor)
            native_information = (
                _windows_handle_information(descriptor) if _using_windows() else None
            )
        except OSError as error:
            raise InputError(f"cannot inspect protected input {self.path}: {error}") from error
        if not _same_protected_regular_identity(self.metadata, current):
            raise InputError(f"run input changed while retained: {self.path}")
        if self.native_information is not None and native_information != self.native_information:
            raise InputError(f"run input handle changed while retained: {self.path}")

    def assert_path_stable(self) -> None:
        self.parent_lock.assert_stable()
        self._assert_handle_identity()
        try:
            current = _stat_unfollowed(
                self.filesystem_path,
                parent_descriptor=(
                    self.parent_lock.descriptor if not _using_windows() else None
                ),
                entry_name=self.entry_name if not _using_windows() else None,
            )
        except OSError as error:
            raise InputError(f"cannot recheck run input {self.path}: {error}") from error
        if not _same_regular_path_binding(self.metadata, current):
            raise InputError(f"run input path changed while retained: {self.path}")

    def reverify(self, budget: _ReadBudget) -> None:
        """Rehash exactly the already-open object under the final bounded budget."""
        self.assert_path_stable()
        descriptor = self._live_descriptor()
        digest = hashlib.sha256()
        try:
            os.lseek(descriptor, 0, os.SEEK_SET)
            with os.fdopen(descriptor, "rb", closefd=False) as source:
                for chunk in _read_expected_chunks(
                    source,
                    self.size,
                    budget,
                    subject=f"run input {self.path}",
                ):
                    digest.update(chunk)
            os.lseek(descriptor, 0, os.SEEK_SET)
        except InputError:
            raise
        except OSError as error:
            raise InputError(f"cannot rehash protected input {self.path}: {error}") from error
        self.assert_path_stable()
        if digest.hexdigest() != self.sha256:
            raise InputError(f"run input contents changed while retained: {self.path}")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        _close_descriptor(self.descriptor, subject=f"run input {self.path}")


@dataclass
class _DraftSnapshot:
    path: Path
    payload: dict[str, object]
    contents: bytes
    sha256: str
    metadata: os.stat_result
    parent_descriptor: int | None
    entry_name: str | None
    snapshot: _InputSnapshot

    def assert_path_stable(self) -> None:
        self.snapshot.assert_path_stable()

    def reverify(self, budget: _ReadBudget) -> None:
        self.snapshot.reverify(budget)

    def close(self) -> None:
        self.snapshot.close()


@dataclass(frozen=True)
class _InputIdentity:
    path: str
    metadata: os.stat_result


def _open_input_snapshot(
    relative: str,
    path: Path,
    expected: os.stat_result,
    parent_lock: _DirectoryLock,
    entry_name: str,
    budget: _ReadBudget,
    *,
    subject: str,
    retain_contents: bool = False,
) -> _InputSnapshot:
    """Hash an input once from a retained descriptor and bind its pathname/handle."""
    if expected.st_size > MAX_RUN_FILE_BYTES:
        raise InputError(f"{subject} exceeds its byte ceiling")
    descriptor: int | None = None
    try:
        parent_lock.assert_stable()
        _before_regular_file_open(path, expected)
        descriptor, native_before = _open_regular_file_descriptor(
            path,
            parent_descriptor=(parent_lock.descriptor if not _using_windows() else None),
            entry_name=entry_name if not _using_windows() else None,
            share_mode=_FILE_SHARE_READ if _using_windows() else None,
        )
        opened = os.fstat(descriptor)
        if not _same_regular_path_binding(expected, opened):
            raise InputError(f"{subject} changed before hashing")
        digest = hashlib.sha256()
        chunks: list[bytes] = []
        with os.fdopen(descriptor, "rb", closefd=False) as source:
            for chunk in _read_expected_chunks(
                source, expected.st_size, budget, subject=subject
            ):
                digest.update(chunk)
                if retain_contents:
                    chunks.append(chunk)
        os.lseek(descriptor, 0, os.SEEK_SET)
        after_open = os.fstat(descriptor)
        native_after = (
            _windows_handle_information(descriptor) if _using_windows() else None
        )
        current = _stat_unfollowed(
            path,
            parent_descriptor=(parent_lock.descriptor if not _using_windows() else None),
            entry_name=entry_name if not _using_windows() else None,
        )
        if (
            not _same_regular_path_binding(expected, after_open)
            or not _same_regular_path_binding(expected, current)
            or (native_before is not None and native_before != native_after)
        ):
            raise InputError(f"{subject} changed while hashing")
        snapshot = _InputSnapshot(
            relative,
            path,
            expected,
            descriptor,
            native_before,
            parent_lock,
            entry_name,
            digest.hexdigest(),
            expected.st_size,
            b"".join(chunks) if retain_contents else None,
        )
        descriptor = None
        return snapshot
    except InputError:
        raise
    except OSError as error:
        raise InputError(f"cannot hash {subject}: {error}") from error
    finally:
        if descriptor is not None:
            _close_descriptor(descriptor, subject=subject)


def _read_draft_json(
    path: Path,
    *,
    parent_lock: _DirectoryLock,
    budget: _ReadBudget,
    parent_descriptor: int | None = None,
    entry_name: str | None = None,
) -> _DraftSnapshot:
    try:
        before = _stat_unfollowed(
            path, parent_descriptor=parent_descriptor, entry_name=entry_name
        )
    except OSError as error:
        raise InputError(f"cannot access draft run-summary.json: {error}") from error
    if (
        not stat.S_ISREG(before.st_mode)
        or _is_reparse_point(before)
        or before.st_size > MAX_DRAFT_BYTES
    ):
        raise InputError("draft run-summary.json is not a bounded regular file")
    snapshot = _open_input_snapshot(
        "run-summary.json",
        path,
        before,
        parent_lock,
        entry_name or "run-summary.json",
        budget,
        subject="draft run-summary.json",
        retain_contents=True,
    )
    contents = snapshot.contents
    if contents is None or len(contents) > MAX_DRAFT_BYTES:
        snapshot.close()
        raise InputError("draft run-summary.json changed while reading")
    try:
        payload = json.loads(
            contents.decode("utf-8"),
            parse_constant=_reject_nonstandard_json_constant,
            object_pairs_hook=_reject_duplicate_json_object_keys,
        )
    except (UnicodeError, ValueError, RecursionError) as error:
        snapshot.close()
        raise InputError(f"draft run-summary.json is not strict UTF-8 JSON: {error}") from error
    structural_issues = validate_json_structure(payload, "run-summary")
    if structural_issues:
        codes = ", ".join(sorted({issue.code for issue in structural_issues}))
        snapshot.close()
        raise InputError(f"draft run-summary.json has invalid structure: {codes}")
    if not isinstance(payload, dict):
        snapshot.close()
        raise InputError("draft run-summary.json must contain a JSON object")
    return _DraftSnapshot(
        path=path,
        payload=payload,
        contents=contents,
        sha256=snapshot.sha256,
        metadata=before,
        parent_descriptor=parent_descriptor,
        entry_name=entry_name,
        snapshot=snapshot,
    )


def _walk_run_root(
    root: Path, directory_locks: _RunDirectoryLocks | None = None
) -> tuple[list[tuple[str, Path, os.stat_result, _DirectoryLock, str]], set[str]]:
    if directory_locks is None:
        with _RunDirectoryLocks(root) as owned_locks:
            return _walk_run_root(root, owned_locks)
    if directory_locks.root is None:
        raise InputError("run-root directory lock was not initialized")
    directory_locks.root.assert_stable()
    files: list[tuple[str, Path, os.stat_result, _DirectoryLock, str]] = []
    blockers: set[str] = set()
    total_bytes = 0
    entry_count = 0
    pending: list[tuple[_DirectoryLock, int, str]] = [(directory_locks.root, 0, "")]
    while pending:
        directory_lock, depth, prefix = pending.pop()
        directory_lock.assert_stable()
        try:
            entries: list[os.DirEntry[str]] = []
            scan_target: str | int = (
                str(directory_lock.path)
                if _using_windows()
                else directory_lock.descriptor
            )
            with os.scandir(scan_target) as iterator:
                for entry in iterator:
                    entry_count += 1
                    if entry_count > MAX_RUN_ENTRIES:
                        raise InputError("run root exceeds the maximum entry count")
                    entries.append(entry)
        except (OSError, TypeError, NotImplementedError) as error:
            raise InputError(
                f"cannot enumerate run directory {directory_lock.path}: "
                f"descriptor scandir unavailable or failed: {error}"
            ) from error
        directory_lock.assert_stable()
        entries.sort(key=lambda item: item.name)
        for entry in entries:
            name = entry.name
            entry_path = directory_lock.path / name
            relative = name if not prefix else f"{prefix}/{name}"
            if _normalized_relative_path(relative) is None:
                raise InputError(f"run entry has an unsafe relative path: {relative!r}")
            try:
                metadata = _stat_unfollowed(
                    entry_path,
                    parent_descriptor=(
                        directory_lock.descriptor if not _using_windows() else None
                    ),
                    entry_name=name if not _using_windows() else None,
                )
            except OSError as error:
                blockers.add(f"RUN_ENTRY_INACCESSIBLE:{relative}")
                continue
            try:
                is_link = (
                    entry.is_symlink()
                    if _using_windows()
                    else stat.S_ISLNK(metadata.st_mode)
                )
            except OSError as error:
                raise InputError(f"cannot inspect run entry {relative}: {error}") from error
            if is_link or _is_reparse_point(metadata):
                blockers.add(f"RUN_LINK_REJECTED:{relative}")
                continue
            if stat.S_ISDIR(metadata.st_mode):
                if depth + 1 > MAX_RUN_DEPTH:
                    raise InputError("run root exceeds the maximum directory depth")
                child_lock = directory_locks.open(
                    entry_path,
                    metadata,
                    parent_lock=directory_lock,
                    entry_name=name,
                )
                pending.append((child_lock, depth + 1, relative))
                continue
            if not stat.S_ISREG(metadata.st_mode):
                blockers.add(f"RUN_SPECIAL_FILE_REJECTED:{relative}")
                continue
            if metadata.st_size > MAX_RUN_FILE_BYTES:
                raise InputError(f"run file exceeds per-file byte ceiling: {relative}")
            files.append((relative, entry_path, metadata, directory_lock, name))
            total_bytes += metadata.st_size
            if total_bytes > MAX_RUN_TOTAL_BYTES:
                raise InputError("run root exceeds the aggregate byte ceiling")
    return sorted(files, key=lambda item: item[0]), blockers


def _hash_regular_file(
    path: Path,
    expected: os.stat_result,
    *,
    parent_descriptor: int | None = None,
    entry_name: str | None = None,
    budget: _ReadBudget | None = None,
) -> tuple[str, int]:
    read_budget = budget or _ReadBudget(expected.st_size, subject=f"file {path}")
    descriptor: int | None = None
    try:
        _before_regular_file_open(path, expected)
        descriptor, native_before = _open_regular_file_descriptor(
            path,
            parent_descriptor=parent_descriptor,
            entry_name=entry_name,
        )
        opened = os.fstat(descriptor)
        if not _same_protected_regular_identity(expected, opened):
            raise InputError(f"run file changed before hashing: {path}")
        digest = hashlib.sha256()
        with os.fdopen(descriptor, "rb", closefd=False) as source:
            for chunk in _read_expected_chunks(
                source,
                expected.st_size,
                read_budget,
                subject=f"run file {path}",
            ):
                digest.update(chunk)
        after_open = os.fstat(descriptor)
        native_after = (
            _windows_handle_information(descriptor) if _using_windows() else None
        )
        after = _stat_unfollowed(
            path, parent_descriptor=parent_descriptor, entry_name=entry_name
        )
    except InputError:
        raise
    except OSError as error:
        raise InputError(f"cannot hash run file {path}: {error}") from error
    finally:
        if descriptor is not None:
            _close_descriptor(descriptor, subject=f"file {path}")
    if (
        not _same_protected_regular_identity(expected, after_open)
        or not _same_regular_identity(expected, after)
        or (native_before is not None and native_before != native_after)
    ):
        raise InputError(f"run file changed while hashing: {path}")
    return digest.hexdigest(), expected.st_size


def _classifications(
    draft: dict[str, object], inventory_paths: set[str], blockers: set[str]
) -> tuple[dict[str, str], dict[str, list[str]]]:
    raw_state = draft.get("localState")
    source = raw_state if isinstance(raw_state, dict) else {}
    if raw_state is not None and not isinstance(raw_state, dict):
        blockers.add("LOCAL_STATE_INVALID")
    assignments: dict[str, str] = {}
    rendered = {key: [] for key, _ in _CLASSIFICATIONS}
    for key, classification in _CLASSIFICATIONS:
        values = source.get(key, [])
        if not isinstance(values, list):
            blockers.add("LOCAL_STATE_CLASSIFICATION_INVALID")
            continue
        for value in values:
            normalized = _normalized_relative_path(value)
            if normalized is None:
                blockers.add("LOCAL_STATE_PATH_INVALID")
                continue
            if normalized in assignments:
                blockers.add("LOCAL_STATE_CLASSIFICATION_DUPLICATE")
                continue
            assignments[normalized] = classification
            rendered[key].append(normalized)
    for key in rendered:
        rendered[key].sort()
    for path in sorted(inventory_paths - set(assignments)):
        blockers.add("LOCAL_STATE_CLASSIFICATION_MISSING")
    for path in sorted(set(assignments) - inventory_paths):
        blockers.add("LOCAL_STATE_PATH_UNKNOWN")
    return assignments, rendered


def _verify_artifacts(
    draft: dict[str, object], inventory: list[dict[str, object]], blockers: set[str]
) -> tuple[list[dict[str, object]], dict[str, str]]:
    raw_artifacts = draft.get("verifiedArtifacts", [])
    by_path = {record["path"]: record for record in inventory}
    verified_index: dict[str, str] = {}
    rendered: list[dict[str, object]] = []
    seen_paths: set[str] = set()
    context_invalid = False
    if not isinstance(raw_artifacts, list):
        blockers.add("VERIFIED_ARTIFACTS_INVALID")
        return rendered, verified_index
    for index, record in enumerate(raw_artifacts):
        if not isinstance(record, dict):
            blockers.add(f"VERIFIED_ARTIFACT_{index}_INVALID")
            context_invalid = True
            continue
        path = _normalized_relative_path(record.get("path"))
        expected = record.get("expectedSha256")
        if path is None or not _is_sha256(expected):
            blockers.add(f"VERIFIED_ARTIFACT_{index}_INVALID")
            context_invalid = True
            continue
        if path in seen_paths:
            blockers.add("VERIFIED_ARTIFACT_DUPLICATE")
            context_invalid = True
            continue
        seen_paths.add(path)
        inventory_record = by_path.get(path)
        actual = inventory_record.get("sha256") if inventory_record else None
        status = "verified"
        if inventory_record is None:
            blockers.add("VERIFIED_ARTIFACT_MISSING")
            status = "missing"
            context_invalid = True
        elif actual != expected.lower():
            blockers.add("VERIFIED_ARTIFACT_HASH_MISMATCH")
            status = "mismatch"
            context_invalid = True
        else:
            verified_index[path] = expected.lower()
        rendered.append(
            {
                "path": path,
                "expectedSha256": expected.lower(),
                "actualSha256": actual,
                "status": status,
            }
        )
    rendered = sorted(rendered, key=lambda item: item["path"])
    if context_invalid:
        return rendered, {}
    return rendered, dict(sorted(verified_index.items()))


def _build_run_summary_locked(
    root: Path,
    directory_locks: _RunDirectoryLocks,
    *,
    include_input_identities: bool = False,
) -> dict[str, object] | tuple[dict[str, object], list[_InputSnapshot]]:
    draft_path = root / "run-summary.json"
    if directory_locks.root is None:
        raise InputError("run-root directory lock was not initialized")
    read_budget = _ReadBudget(MAX_RUN_TOTAL_BYTES, subject="run root")
    snapshots: list[_InputSnapshot] = []
    try:
        draft = _read_draft_json(
            draft_path,
            parent_lock=directory_locks.root,
            budget=read_budget,
            parent_descriptor=(
                directory_locks.root.descriptor if not _using_windows() else None
            ),
            entry_name="run-summary.json" if not _using_windows() else None,
        )
        snapshots.append(draft.snapshot)
        entries, blockers = _walk_run_root(root, directory_locks)
        inventory_paths = {relative for relative, _, _, _, _ in entries}
        assignments, rendered_state = _classifications(
            draft.payload, inventory_paths, blockers
        )
        inventory: list[dict[str, object]] = []
        for relative, path, metadata, parent_lock, entry_name in entries:
            if relative == "run-summary.json":
                if not _same_regular_path_binding(draft.metadata, metadata):
                    raise InputError("draft run-summary.json changed before inventory")
                draft.assert_path_stable()
                snapshot = draft.snapshot
            else:
                snapshot = _open_input_snapshot(
                    relative,
                    path,
                    metadata,
                    parent_lock,
                    entry_name,
                    read_budget,
                    subject=f"run file {relative}",
                )
                snapshots.append(snapshot)
            status = "verified" if relative in assignments else "unclassified"
            inventory.append(
                {
                    "path": relative,
                    "sha256": snapshot.sha256,
                    "size": snapshot.size,
                    "status": status,
                    "classification": assignments.get(relative),
                }
            )
        for snapshot in snapshots:
            snapshot.assert_path_stable()
        verified_artifacts, verified_index = _verify_artifacts(
            draft.payload, inventory, blockers
        )
        evaluator_input = dict(draft.payload)
        evaluator_input["verifiedArtifactIndex"] = verified_index
        maturity = evaluate_maturity(evaluator_input)
        combined_blockers = set(maturity["blockers"])
        combined_blockers.update(blockers)
        final_summary = (
            not combined_blockers
            and maturity["maturity"] == "release-candidate"
            and all(entry["status"] == "verified" for entry in inventory)
        )
        summary: dict[str, object] = {
            "schemaVersion": 1,
            "maturity": maturity["maturity"],
            "technicalStatus": maturity["technicalStatus"],
            "visualStatus": maturity["visualStatus"],
            "packageStatus": maturity["packageStatus"],
            "runtimeStatus": maturity["runtimeStatus"],
            "installedStatus": maturity["installedStatus"],
            "userAcceptance": maturity["userAcceptance"],
            "authorities": maturity["authorities"],
            "releaseAuthority": maturity["releaseAuthority"],
            "verifiedArtifacts": verified_artifacts,
            "unverifiedChecks": maturity["unverifiedChecks"],
            "localState": rendered_state,
            "inventory": inventory,
            "blockers": sorted(combined_blockers),
            "finalSummary": final_summary,
        }
        if include_input_identities:
            return summary, snapshots
        for snapshot in reversed(snapshots):
            snapshot.close()
        snapshots.clear()
        return summary
    except BaseException:
        first_error: InputError | None = None
        for snapshot in reversed(snapshots):
            try:
                snapshot.close()
            except InputError as error:
                if first_error is None:
                    first_error = error
        if first_error is not None:
            raise first_error
        raise


def build_run_summary(run_root: Path) -> dict[str, object]:
    """Read and inventory a run without altering any run-root file or metadata."""
    if not isinstance(run_root, Path):
        raise TypeError("run_root must be pathlib.Path")
    root = _absolute_path(run_root)
    with _RunDirectoryLocks(root) as directory_locks:
        return _build_run_summary_locked(root, directory_locks)


def _resolve_output_path(root: Path, output: Path) -> Path:
    try:
        requested = _absolute_path(Path(output))
        resolved = requested.resolve(strict=False)
        canonical_root = root.resolve(strict=True)
    except OSError as error:
        raise InputError(f"cannot resolve output path: {error}") from error
    if requested != resolved:
        raise InputError("output path must not traverse a link or reparse point")
    try:
        resolved.relative_to(canonical_root)
    except ValueError:
        pass
    else:
        raise InputError("output must resolve outside run_root")
    return resolved


def _existing_output_identity(path: Path) -> os.stat_result | None:
    try:
        metadata = os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise InputError(f"cannot inspect output path: {error}") from error
    if not stat.S_ISREG(metadata.st_mode) or _is_reparse_point(metadata):
        raise InputError("output must be a regular non-reparse file")
    return metadata


def _same_object_identity(first: os.stat_result, second: os.stat_result) -> bool:
    return (
        stat.S_ISREG(first.st_mode)
        and stat.S_ISREG(second.st_mode)
        and not _is_reparse_point(first)
        and not _is_reparse_point(second)
        and (first.st_dev, first.st_ino) == (second.st_dev, second.st_ino)
    )


class _ExistingOutput:
    """A no-delete-share (Windows) or descriptor-rooted (POSIX) output snapshot."""

    def __init__(
        self,
        path: Path,
        descriptor: int,
        metadata: os.stat_result,
        parent_lock: _DirectoryLock,
        native_information: tuple[int, ...] | None,
    ) -> None:
        self.path = path
        self._descriptor: int | None = descriptor
        self.metadata = metadata
        self._parent_lock = parent_lock
        self._native_information = native_information

    @property
    def descriptor(self) -> int:
        if self._descriptor is None:
            raise InputError(f"existing output was already closed: {self.path}")
        return self._descriptor

    def assert_path_stable(self) -> None:
        self._parent_lock.assert_stable()
        try:
            current = _stat_unfollowed(
                self.path,
                parent_descriptor=(
                    self._parent_lock.descriptor if not _using_windows() else None
                ),
                entry_name=self.path.name if not _using_windows() else None,
            )
            opened = os.fstat(self.descriptor)
            native_information = (
                _windows_handle_information(self.descriptor)
                if _using_windows()
                else None
            )
        except OSError as error:
            raise InputError(f"cannot recheck existing output: {error}") from error
        if (
            not _same_regular_path_binding(self.metadata, current)
            or not _same_protected_regular_identity(self.metadata, opened)
            or (
                self._native_information is not None
                and self._native_information != native_information
            )
        ):
            raise InputError("output path changed during stable comparison")

    def require_identical_bytes(self, encoded: bytes) -> None:
        if self.metadata.st_size != len(encoded):
            raise InputError("output collision: existing bytes differ")
        try:
            with os.fdopen(self.descriptor, "rb", closefd=False) as source:
                actual = b"".join(
                    _read_expected_chunks(
                        source,
                        self.metadata.st_size,
                        _ReadBudget(
                            len(encoded), subject="existing summary output"
                        ),
                        subject="existing summary output",
                    )
                )
        except InputError:
            raise
        except OSError as error:
            raise InputError(f"cannot read existing output: {error}") from error
        self.assert_path_stable()
        if actual != encoded:
            raise InputError("output collision: existing bytes differ")

    def close(self) -> None:
        if self._descriptor is None:
            return
        descriptor, self._descriptor = self._descriptor, None
        _close_descriptor(descriptor, subject=f"existing output {self.path}")


def _open_existing_output(
    path: Path, parent_lock: _DirectoryLock
) -> _ExistingOutput | None:
    if parent_lock.path != _absolute_path(path.parent):
        raise InputError("output parent lock does not match the output path")
    parent_lock.assert_stable()
    descriptor: int | None = None
    try:
        descriptor, _ = _open_regular_file_descriptor(
            path,
            parent_descriptor=(parent_lock.descriptor if not _using_windows() else None),
            entry_name=path.name if not _using_windows() else None,
            share_mode=_FILE_SHARE_READ if _using_windows() else None,
            allow_missing=True,
        )
    except OSError as error:
        error_codes = {error.errno, getattr(error, "winerror", None)}
        if error_codes & {2, 3}:
            return None
        raise InputError(f"cannot safely open existing output: {error}") from error
    try:
        metadata = os.fstat(descriptor)
        native_information = (
            _windows_handle_information(descriptor) if _using_windows() else None
        )
    except OSError as error:
        _close_descriptor(descriptor, subject=f"existing output {path}")
        raise InputError(f"cannot inspect existing output: {error}") from error
    if (
        not stat.S_ISREG(metadata.st_mode)
        or _is_reparse_point(metadata)
        or _windows_info_is_reparse_point(native_information)
    ):
        _close_descriptor(descriptor, subject=f"existing output {path}")
        raise InputError("output must be a regular non-reparse file")
    return _ExistingOutput(
        path, descriptor, metadata, parent_lock, native_information
    )


def _reject_existing_output_alias(
    existing: _ExistingOutput, input_identities: list[_InputIdentity | _InputSnapshot]
) -> None:
    for input_identity in input_identities:
        if _same_object_identity(existing.metadata, input_identity.metadata):
            raise InputError(
                f"output must not alias a run input: {input_identity.path}"
            )


def _reverify_input_snapshots(
    input_identities: list[_InputIdentity | _InputSnapshot] | None,
) -> None:
    """Make the final input assertion from retained handles immediately precommit."""
    if not input_identities:
        return
    snapshots: list[_InputSnapshot] = []
    for identity in input_identities:
        if not isinstance(identity, _InputSnapshot):
            raise InputError("summary publication lacks protected input snapshot context")
        snapshots.append(identity)
    total = sum(snapshot.size for snapshot in snapshots)
    if total > MAX_RUN_TOTAL_BYTES:
        raise InputError("run root exceeds the aggregate byte ceiling")
    budget = _ReadBudget(total, subject="run root final snapshot")
    for snapshot in snapshots:
        snapshot.reverify(budget)


def _validate_output_path(
    root: Path,
    output: Path,
    inventory: list[dict[str, object]],
    parent_lock: _DirectoryLock,
) -> None:
    if parent_lock.path != _absolute_path(output.parent):
        raise InputError("output parent lock does not match the output path")
    parent_lock.assert_stable()
    parent_lock.assert_stable()


def _output_path(
    root: Path,
    output: Path,
    inventory: list[dict[str, object]],
    parent_lock: _DirectoryLock | None = None,
) -> Path:
    resolved = _resolve_output_path(root, output)
    if parent_lock is not None:
        _validate_output_path(root, resolved, inventory, parent_lock)
        return resolved
    with _open_directory_lock(resolved.parent) as owned_parent_lock:
        _validate_output_path(root, resolved, inventory, owned_parent_lock)
    return resolved


def _output_identity_is_stable(
    path: Path, expected: os.stat_result | None
) -> None:
    current = _existing_output_identity(path)
    if expected is None:
        if current is not None:
            raise InputError("output path appeared during publication")
        return
    if current is None or not _same_regular_identity(expected, current):
        raise InputError("output path changed during publication")


def _before_atomic_replace(parent_lock: _DirectoryLock) -> None:
    """A deterministic boundary immediately before immutable no-replace commit."""
    parent_lock.assert_path_matches_handle()


def _after_atomic_no_replace_commit(parent_lock: _DirectoryLock) -> None:
    """Confirm the requested parent name still resolves to the committed directory."""
    parent_lock.assert_path_matches_handle()
    _after_post_commit_parent_observation()


def _after_post_commit_parent_observation() -> None:
    """A deterministic seam after the final post-commit path observation."""


def _encode_summary(payload: dict[str, object]) -> bytes:
    try:
        return (
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (UnicodeError, ValueError, TypeError) as error:
        raise InputError(f"cannot encode summary output: {error}") from error


@dataclass
class _TemporaryOutput:
    """One live temporary object whose identity is retained through commit."""

    path: Path
    descriptor: int
    parent_lock: _DirectoryLock
    named: bool
    metadata: os.stat_result | None = None
    native_information: tuple[int, ...] | None = None
    expected_sha256: str | None = None
    expected_size: int | None = None
    committed: bool = False
    _closed: bool = False

    def _live_descriptor(self) -> int:
        if self._closed:
            raise InputError("temporary summary output was already closed")
        return self.descriptor

    def _assert_live_object(self, *, allow_metadata_change: bool = False) -> os.stat_result:
        descriptor = self._live_descriptor()
        try:
            metadata = os.fstat(descriptor)
            native_information = (
                _windows_handle_information(descriptor) if _using_windows() else None
            )
        except OSError as error:
            raise InputError(f"cannot inspect temporary summary output: {error}") from error
        if not stat.S_ISREG(metadata.st_mode) or _is_reparse_point(metadata):
            raise InputError("temporary summary output is not a regular object")
        if _using_windows() and _windows_handle_link_count(descriptor) != 1:
            raise InputError("temporary summary output link count changed")
        if not _using_windows() and metadata.st_nlink != (1 if self.committed else 0):
            raise InputError("unnamed temporary summary output link count changed")
        if (
            not allow_metadata_change
            and self.metadata is not None
            and not _same_regular_identity(
            self.metadata, metadata
            )
        ):
            raise InputError("temporary summary output changed while retained")
        if _using_windows():
            if _windows_info_is_reparse_point(native_information):
                raise InputError("temporary summary output is a reparse point")
            if self.native_information is not None and (
                _windows_object_identity(native_information)
                != _windows_object_identity(self.native_information)
            ):
                raise InputError("temporary summary output handle changed")
        return metadata

    def write_and_verify(self, encoded: bytes) -> None:
        descriptor = self._live_descriptor()
        try:
            with os.fdopen(descriptor, "wb", closefd=False) as temporary:
                offset = 0
                while offset < len(encoded):
                    remaining = encoded[offset:]
                    written = temporary.write(remaining)
                    if (
                        isinstance(written, bool)
                        or not isinstance(written, int)
                        or written <= 0
                        or written > len(remaining)
                    ):
                        raise InputError("cannot write temporary summary output completely")
                    offset += written
                temporary.flush()
                os.fsync(temporary.fileno())
            self.metadata = os.fstat(descriptor)
            self.native_information = (
                _windows_handle_information(descriptor) if _using_windows() else None
            )
        except InputError:
            raise
        except OSError as error:
            raise InputError(f"cannot write temporary summary output: {error}") from error
        if self.metadata.st_size != len(encoded):
            raise InputError("temporary summary output size verification failed")
        self.expected_size = len(encoded)
        self.expected_sha256 = hashlib.sha256(encoded).hexdigest()
        self.reverify_contents()

    def reverify_contents(self) -> None:
        if self.metadata is None or self.expected_size is None or self.expected_sha256 is None:
            raise InputError("temporary summary output was not initialized")
        descriptor = self._live_descriptor()
        self._assert_live_object()
        try:
            os.lseek(descriptor, 0, os.SEEK_SET)
            with os.fdopen(descriptor, "rb", closefd=False) as source:
                digest = hashlib.sha256()
                for chunk in _read_expected_chunks(
                    source,
                    self.expected_size,
                    _ReadBudget(
                        self.expected_size, subject="temporary summary output"
                    ),
                    subject="temporary summary output",
                ):
                    digest.update(chunk)
            os.lseek(descriptor, 0, os.SEEK_SET)
        except InputError:
            raise
        except OSError as error:
            raise InputError(f"cannot verify temporary summary output: {error}") from error
        self._assert_live_object()
        if digest.hexdigest() != self.expected_sha256:
            raise InputError("temporary summary output content verification failed")
        if self.named:
            try:
                current = _stat_unfollowed(self.path)
            except OSError as error:
                raise InputError(
                    f"cannot recheck temporary summary output path: {error}"
                ) from error
            # Windows can expose a delayed pathname ctime after a buffered handle
            # write.  The pathname check is an alias/replacement check; exact bytes,
            # size, and ctime are already verified from the same live handle.
            if (
                not _same_object_identity(self.metadata, current)
                or self.metadata.st_size != current.st_size
                or self.metadata.st_nlink != current.st_nlink
            ):
                raise InputError("temporary summary output path changed")

    def discard_precommit(self) -> None:
        primary_error: InputError | None = None
        try:
            if _using_windows():
                _windows_mark_handle_for_delete(self._live_descriptor())
        except OSError as error:
            primary_error = InputError(
                f"cannot clean temporary summary output {self.path}: {error}"
            )
        try:
            self.close()
        except InputError as close_error:
            if primary_error is not None:
                raise primary_error from close_error
            raise
        if primary_error is not None:
            raise primary_error

    def commit_no_replace(self, output: Path) -> None:
        self.reverify_contents()
        try:
            if _using_windows():
                _windows_rename_handle_no_replace(self._live_descriptor(), output)
            else:
                _posix_link_unnamed_temporary_no_replace(
                    self._live_descriptor(), output.name, self.parent_lock.descriptor
                )
        except OSError as error:
            raise InputError(
                f"cannot publish summary without replacement: {error}"
            ) from error
        self.committed = True
        # A successful rename changes ctime/name metadata by design.  The native
        # call is the commit boundary; afterwards only the retained handle/object
        # identity and link count are meaningful, and no pathname rollback is safe.
        self._assert_live_object(allow_metadata_change=True)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        _close_descriptor(self.descriptor, subject=f"temporary summary output {self.path}")


def _posix_link_unnamed_temporary_no_replace(
    descriptor: int, output_name: str, parent_descriptor: int
) -> None:
    """Publish an O_TMPFILE inode by descriptor with linkat(AT_EMPTY_PATH)."""
    if _using_windows():
        raise RuntimeError("POSIX linkat requested on Windows")
    if not output_name or "/" in output_name or "\\" in output_name:
        raise InputError("invalid summary output name")
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        linkat = libc.linkat
        linkat.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
        linkat.restype = ctypes.c_int
    except (AttributeError, OSError) as error:
        raise InputError("POSIX object-bound linkat capability is required") from error
    encoded_name = os.fsencode(output_name)
    ctypes.set_errno(0)
    if linkat(descriptor, b"", parent_descriptor, encoded_name, _AT_EMPTY_PATH) == 0:
        return
    direct_errno = ctypes.get_errno()
    if direct_errno != errno.ENOENT:
        raise OSError(direct_errno, "linkat(AT_EMPTY_PATH) failed")
    # Linux documents /proc/self/fd plus AT_SYMLINK_FOLLOW as the descriptor-
    # bound alternative when AT_EMPTY_PATH lacks CAP_DAC_READ_SEARCH.  The
    # source is derived solely from the live fd; the destination remains the
    # held parent descriptor and linkat still has no-replace semantics.
    proc_descriptor = f"/proc/self/fd/{descriptor}".encode("ascii")
    ctypes.set_errno(0)
    if (
        linkat(
            _AT_FDCWD,
            proc_descriptor,
            parent_descriptor,
            encoded_name,
            _AT_SYMLINK_FOLLOW,
        )
        != 0
    ):
        raise OSError(ctypes.get_errno(), "linkat(/proc/self/fd) failed")


def _create_output_temporary(path: Path, parent_lock: _DirectoryLock) -> _TemporaryOutput:
    parent_lock.assert_path_matches_handle()
    if _using_windows():
        for _ in range(32):
            temporary_path = path.parent / f".{path.name}.{secrets.token_hex(16)}.tmp"
            try:
                descriptor = _windows_open_descriptor(
                    temporary_path,
                    directory=False,
                    share_mode=_FILE_SHARE_READ,
                    desired_access=_GENERIC_READ | _GENERIC_WRITE | _DELETE,
                    creation_disposition=_CREATE_NEW,
                )
            except OSError as error:
                if getattr(error, "winerror", error.errno) in {80, 183}:
                    continue
                raise InputError(
                    f"cannot create temporary summary output: {error}"
                ) from error
            temporary = _TemporaryOutput(temporary_path, descriptor, parent_lock, True)
            try:
                temporary.metadata = os.fstat(descriptor)
                temporary.native_information = _windows_handle_information(descriptor)
                temporary._assert_live_object()
            except BaseException:
                try:
                    temporary.discard_precommit()
                except InputError:
                    pass
                raise
            return temporary
        raise InputError("cannot create a unique temporary summary output")
    tmpfile_flag = getattr(os, "O_TMPFILE", 0)
    if not isinstance(tmpfile_flag, int) or tmpfile_flag == 0:
        raise InputError("POSIX O_TMPFILE capability is required")
    if os.open not in getattr(os, "supports_dir_fd", set()):
        raise InputError("POSIX descriptor-rooted temporary capability is required")
    flags = os.O_RDWR | tmpfile_flag | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(".", flags, 0o600, dir_fd=parent_lock.descriptor)
    except (TypeError, NotImplementedError) as error:
        raise InputError("POSIX O_TMPFILE capability is unavailable") from error
    except OSError as error:
        raise InputError(f"cannot create unnamed temporary summary output: {error}") from error
    temporary = _TemporaryOutput(path.parent / "(unnamed temporary)", descriptor, parent_lock, False)
    try:
        temporary.metadata = os.fstat(descriptor)
        temporary.native_information = None
        temporary._assert_live_object()
    except BaseException:
        try:
            temporary.close()
        except InputError:
            pass
        raise
    return temporary


def _write_temporary_output(
    descriptor: int, encoded: bytes, path: Path
) -> os.stat_result:
    """Legacy focused seam: strict-write and leave the caller's handle live."""
    holder = _TemporaryOutput(path, descriptor, _DirectoryLock(path.parent, os.stat(path.parent), -1, None), True)
    holder.write_and_verify(encoded)
    if holder.metadata is None:
        raise InputError(f"cannot verify temporary summary output {path}")
    return holder.metadata


def _cleanup_temporary_output(
    temporary_path: Path | _TemporaryOutput,
    temporary_name: str | _TemporaryOutput | None,
    parent_lock: _DirectoryLock,
) -> None:
    if isinstance(temporary_path, _TemporaryOutput):
        temporary_path.discard_precommit()
        return
    raise InputError("refusing pathname-based temporary summary cleanup")


def _commit_output_no_replace(
    temporary_path: Path | _TemporaryOutput,
    temporary_name: str | _TemporaryOutput | None,
    output: Path,
    parent_lock: _DirectoryLock,
) -> str | None:
    if not isinstance(temporary_path, _TemporaryOutput):
        raise InputError("refusing pathname-based summary publication")
    temporary_path.commit_no_replace(output)
    return None


@dataclass(frozen=True)
class _Publication:
    committed: bool
    diagnostic: str | None = None


def _write_json_atomically_locked(
    path: Path,
    payload: dict[str, object],
    parent_lock: _DirectoryLock,
    input_identities: list[_InputIdentity | _InputSnapshot] | None = None,
) -> _Publication:
    """Publish immutable deterministic bytes, never overwrite a pre-existing path."""
    encoded = _encode_summary(payload)
    parent_lock.assert_path_matches_handle()
    existing = _open_existing_output(path, parent_lock)
    if existing is not None:
        primary_error: InputError | None = None
        try:
            existing.assert_path_stable()
            _reject_existing_output_alias(existing, input_identities or [])
            existing.require_identical_bytes(encoded)
            existing.assert_path_stable()
            _reverify_input_snapshots(input_identities)
            existing.assert_path_stable()
            _reject_existing_output_alias(existing, input_identities or [])
        except InputError as error:
            primary_error = error
        try:
            existing.close()
        except InputError as close_error:
            if primary_error is not None:
                raise primary_error from close_error
            raise
        if primary_error is not None:
            raise primary_error
        parent_lock.assert_path_matches_handle()
        return _Publication(committed=False)

    temporary: _TemporaryOutput | None = None
    publication: _Publication | None = None
    primary_error: InputError | None = None
    primary_cause: OSError | None = None
    committed = False
    try:
        parent_lock.assert_path_matches_handle()
        temporary = _create_output_temporary(path, parent_lock)
        temporary.write_and_verify(encoded)
        _output_identity_is_stable(path, None)
        _before_atomic_replace(parent_lock)
        _reverify_input_snapshots(input_identities)
        diagnostic = _commit_output_no_replace(
            temporary, temporary, path, parent_lock
        )
        committed = True
        post_commit_details: list[str] = []
        if diagnostic is not None:
            post_commit_details.append(diagnostic)
        # Native rename is the commit boundary.  Release the write/delete-denying
        # temporary handle before the post-commit observation, so that observation
        # tests model the real non-interference race rather than a self-imposed lock.
        try:
            temporary.close()
        except InputError as close_error:
            post_commit_details.append(
                "post-commit temporary-handle close diagnostic: " + str(close_error)
            )
        try:
            _after_atomic_no_replace_commit(parent_lock)
        except InputError as post_commit_error:
            details = [
                "post-commit requested output parent mismatch; "
                "committed output retained in verified parent: "
                f"{post_commit_error}"
            ]
            details.extend(post_commit_details)
            publication = _Publication(committed=True, diagnostic="; ".join(details))
        else:
            publication = _Publication(
                committed=True,
                diagnostic="; ".join(post_commit_details) or None,
            )
    except InputError as error:
        if temporary is not None and temporary.committed:
            committed = True
            publication = _Publication(
                committed=True,
                diagnostic="summary publication committed; post-commit diagnostic: "
                + str(error),
            )
        else:
            primary_error = error
    except OSError as error:
        if temporary is not None and temporary.committed:
            committed = True
            publication = _Publication(
                committed=True,
                diagnostic="summary publication committed; post-commit diagnostic: "
                + str(error),
            )
        else:
            primary_error = InputError(f"cannot write summary output: {error}")
            primary_cause = error
    if temporary is not None and not committed:
        try:
            _cleanup_temporary_output(temporary, temporary, parent_lock)
        except InputError as cleanup_error:
            if primary_error is not None:
                raise primary_error from cleanup_error
            raise
    if temporary is not None and committed and not temporary._closed:
        try:
            temporary.close()
        except InputError as close_error:
            details = ["post-commit temporary-handle close diagnostic: " + str(close_error)]
            if publication is not None and publication.diagnostic is not None:
                details.insert(0, publication.diagnostic)
            publication = _Publication(committed=True, diagnostic="; ".join(details))
    if primary_error is not None:
        if primary_cause is not None:
            raise primary_error from primary_cause
        raise primary_error
    if publication is None:
        raise InputError("summary output publication did not reach a commit boundary")
    return publication


def _write_json_atomically(
    path: Path,
    payload: dict[str, object],
    parent_lock: _DirectoryLock | None = None,
    input_identities: list[_InputIdentity | _InputSnapshot] | None = None,
) -> _Publication:
    if parent_lock is not None:
        return _write_json_atomically_locked(
            path, payload, parent_lock, input_identities
        )
    with _open_directory_lock(path.parent) as owned_parent_lock:
        return _write_json_atomically_locked(
            path, payload, owned_parent_lock, input_identities
        )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = _ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    directory_locks: _RunDirectoryLocks | None = None
    input_snapshots: list[_InputSnapshot] = []
    summary: dict[str, object] | None = None
    normal_exit = 1
    committed = False
    primary_error: InputError | TypeError | None = None
    close_error: InputError | None = None
    publication_diagnostic: str | None = None
    try:
        root = _absolute_path(args.run_root)
        directory_locks = _RunDirectoryLocks(root)
        directory_locks.__enter__()
        built = _build_run_summary_locked(
            root, directory_locks, include_input_identities=True
        )
        if not isinstance(built, tuple):
            raise InputError("run summary identity context was not returned")
        summary, input_snapshots = built
        resolved_output = _resolve_output_path(root, args.output)
        output_parent_lock = directory_locks.open(resolved_output.parent)
        output = _output_path(
            root,
            resolved_output,
            summary["inventory"],
            output_parent_lock,
        )
        publication = _write_json_atomically(
            output, summary, output_parent_lock, input_snapshots
        )
        committed = publication.committed
        publication_diagnostic = publication.diagnostic
        normal_exit = 0 if summary["finalSummary"] else 2
        if committed and publication_diagnostic is not None and normal_exit == 0:
            normal_exit = 2
    except (InputError, TypeError) as error:
        primary_error = error
    finally:
        for snapshot in reversed(input_snapshots):
            try:
                snapshot.close()
            except InputError as error:
                if close_error is None:
                    close_error = error
        if directory_locks is not None:
            try:
                directory_locks._close_all()
            except InputError as error:
                if close_error is None:
                    close_error = error
    if primary_error is not None:
        print(primary_error, file=sys.stderr)
        if isinstance(primary_error.__cause__, InputError):
            print(
                f"secondary cleanup/close diagnostic: {primary_error.__cause__}",
                file=sys.stderr,
            )
        if close_error is not None:
            print(f"while closing protected paths: {close_error}", file=sys.stderr)
        return 1
    if publication_diagnostic is not None:
        print(publication_diagnostic, file=sys.stderr)
    if close_error is not None:
        if committed:
            print(
                f"summary publication committed; post-commit close diagnostic: {close_error}",
                file=sys.stderr,
            )
            return 2 if normal_exit == 0 else normal_exit
        print(close_error, file=sys.stderr)
        return 1
    return normal_exit


if __name__ == "__main__":
    raise SystemExit(main())
