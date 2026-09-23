"""Managed text blocks and recoverable regular-file transactions."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import platform
import secrets
import stat
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from codex_routing.errors import RoutingConfigError


_MANIFEST_SCHEMA = 1
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_UNSUPPORTED_POSIX_DIRECTORY_FSYNC = {
    errno.EINVAL,
    errno.ENOTSUP,
}


@dataclass(frozen=True)
class FileUpdate:
    path: Path
    after: bytes


@dataclass(frozen=True)
class TransactionResult:
    manifest_path: Path | None
    changed_paths: tuple[Path, ...]


@dataclass(frozen=True)
class _CapturedUpdate:
    path: Path
    after: bytes
    installed_digest: str
    parent_state: tuple[int, int, int, int]
    prior_state: tuple[int, int, int, int] | None
    prior: bytes | None
    prior_digest: str | None


@dataclass(frozen=True)
class _OwnedStage:
    path: Path
    state: tuple[int, int, int, int]
    digest: str


@dataclass(frozen=True)
class _PreparedUpdate:
    captured: _CapturedUpdate
    stage: _OwnedStage


@dataclass(frozen=True)
class _RollbackRecord:
    path: Path
    parent_state: tuple[int, int, int, int]
    installed_state: tuple[int, int, int, int]
    installed: bytes
    installed_digest: str
    prior_exists: bool
    prior: bytes | None
    prior_digest: str | None


def merge_managed_block(
    existing: bytes,
    body: bytes,
    begin: bytes,
    end: bytes,
) -> bytes:
    if begin in body or end in body:
        raise RoutingConfigError("managed block body contains a marker")
    begin_count = existing.count(begin)
    end_count = existing.count(end)
    if begin_count != end_count or begin_count > 1:
        raise RoutingConfigError("managed block markers are incomplete or duplicated")
    if begin_count == 1 and existing.index(end) < existing.index(begin):
        raise RoutingConfigError("managed block markers are incomplete or duplicated")
    newline = b"\r\n" if b"\r\n" in existing else b"\n"
    normalized = body.strip(b"\r\n")
    block = begin + newline + normalized + newline + end
    if begin_count == 0:
        if not normalized:
            return existing
        prefix = existing.rstrip(b"\r\n")
        return prefix + (newline * 2 if prefix else b"") + block + newline
    start = existing.index(begin)
    stop = existing.index(end, start) + len(end)
    if normalized:
        return existing[:start] + block + existing[stop:]
    prefix = existing[:start].rstrip(b"\r\n")
    suffix = existing[stop:].lstrip(b"\r\n")
    separator = newline * 2 if prefix and suffix else b""
    trailing = newline if prefix or suffix else b""
    return prefix + separator + suffix.rstrip(b"\r\n") + trailing


def apply_transaction(
    updates: tuple[FileUpdate, ...],
    backup_root: Path,
    *,
    replace: Callable[[Path, Path], None] = os.replace,
) -> TransactionResult:
    """Replace individual files atomically, with guarded recovery on failure."""

    normalized = _normalize_updates(updates)

    # Capture every leaf before inspecting any parent or reading any file.
    destination_stats = [_capture_destination(update.path) for update in normalized]

    # Preflight every destination parent before reading prior bytes.
    parent_stats = [_capture_parent(update.path.parent) for update in normalized]

    captured: list[_CapturedUpdate] = []
    for update, destination_stat, parent_stat in zip(
        normalized, destination_stats, parent_stats, strict=True
    ):
        prior = (
            _read_captured_regular(update.path, destination_stat)
            if destination_stat is not None
            else None
        )
        captured.append(
            _CapturedUpdate(
                path=update.path,
                after=update.after,
                installed_digest=_digest(update.after),
                parent_state=_stat_identity(parent_stat),
                prior_state=(
                    _stat_identity(destination_stat)
                    if destination_stat is not None
                    else None
                ),
                prior=prior,
                prior_digest=_digest(prior) if prior is not None else None,
            )
        )

    changed = sorted(
        (record for record in captured if record.prior != record.after),
        key=lambda record: os.fspath(record.path),
    )
    if not changed:
        _revalidate_updates(tuple(captured))
        return TransactionResult(manifest_path=None, changed_paths=())
    try:
        (
            transaction_dir,
            pending_manifest,
            pending_owned,
            manifest_digest,
        ) = _prepare_transaction_evidence(changed, _absolute_path(backup_root))
    except Exception as exc:
        if isinstance(exc, RoutingConfigError):
            raise
        raise RoutingConfigError(_failure_message(exc, [], [])) from exc

    prepared: list[_PreparedUpdate] = []
    manifest_path = transaction_dir / "manifest.json"
    manifest_owned: _OwnedStage | None = None
    attempted: list[_PreparedUpdate] = []
    try:
        for record in changed:
            prepared.append(
                _PreparedUpdate(
                    captured=record,
                    stage=_prepare_stage(record.path, record.after, "install"),
                )
            )

        _revalidate_updates(tuple(captured))

        for record in prepared:
            _revalidate_updates((record.captured,))
            _assert_owned_payload(record.stage, "publication")
            attempted.append(record)
            replace(record.stage.path, record.captured.path)
            _assert_published(record.stage, record.captured.path)
            _fsync_directory(record.captured.path.parent)

        _revalidate_success(captured, prepared)
        _assert_owned_payload(pending_owned, "publication")
        # The replacement callback can publish and then raise. Record the
        # destination ownership before invoking it so exception cleanup removes
        # only this exact staged manifest and preserves any foreign rebind.
        manifest_owned = _OwnedStage(
            manifest_path, pending_owned.state, manifest_digest
        )
        replace(pending_manifest, manifest_path)
        try:
            _assert_published(pending_owned, manifest_path)
        except RoutingConfigError:
            raise RoutingConfigError("manifest replacement did not publish expected bytes")
        _fsync_directory(transaction_dir)
        _revalidate_success(captured, prepared)
        cleanup_errors: list[str] = []
        for owned in [item.stage for item in prepared] + [pending_owned]:
            _collect_cleanup_error(owned, cleanup_errors)
        if cleanup_errors:
            raise RoutingConfigError("cleanup failures: " + "; ".join(cleanup_errors))
        return TransactionResult(
            manifest_path=manifest_path,
            changed_paths=tuple(record.path for record in changed),
        )
    except Exception as exc:
        rollback_errors: list[str] = []
        installed: list[_PreparedUpdate] = []
        for record in attempted:
            try:
                if _apply_result_was_published(record):
                    installed.append(record)
            except Exception as inspection_exc:
                rollback_errors.append(
                    f"{record.captured.path}: rollback inspection failed: "
                    f"{_exception_text(inspection_exc)}"
                )
        restored: list[tuple[_CapturedUpdate, _OwnedStage | None]] = []
        for record in reversed(installed):
            try:
                restored.append((record.captured, _restore_captured(record, replace)))
            except Exception as rollback_exc:
                rollback_errors.append(
                    f"{record.captured.path}: {_exception_text(rollback_exc)}"
                )

        cleanup_errors: list[str] = []
        for owned in [item.stage for item in prepared]:
            _collect_cleanup_error(owned, cleanup_errors)
        for captured_record, restored_stage in restored:
            try:
                _revalidate_destination(
                    captured_record.path, captured_record.parent_state, restored_stage
                )
            except Exception as final_exc:
                rollback_errors.append(
                    f"{captured_record.path}: final recovery validation failed: "
                    f"{_exception_text(final_exc)}"
                )
        if rollback_errors:
            # Keep the original mapping and backups when recovery is incomplete.
            # This diagnostic is not a rollback manifest: the destinations can
            # now contain a mixture of original, installed, and foreign bytes.
            try:
                _write_exclusive(
                    transaction_dir / "recovery-required.json",
                    _json_bytes({
                        "schema": 1,
                        "status": "incomplete",
                        "original_error": _exception_text(exc),
                        "rollback_errors": rollback_errors,
                    }),
                )
                _fsync_directory(transaction_dir)
            except Exception as evidence_exc:
                cleanup_errors.append(
                    "could not record recovery status: " + _exception_text(evidence_exc)
                )
        else:
            _collect_cleanup_error(pending_owned, cleanup_errors)
            if manifest_owned is not None:
                _collect_cleanup_error(manifest_owned, cleanup_errors)

        message = _failure_message(exc, rollback_errors, cleanup_errors)
        if rollback_errors:
            message += f"; recovery incomplete; inspect retained evidence at {transaction_dir}"
        raise RoutingConfigError(message) from exc


def rollback_transaction(
    manifest_path: Path,
    *,
    replace: Callable[[Path, Path], None] = os.replace,
) -> tuple[Path, ...]:
    """Restore a manifest only while every installed digest still matches."""

    manifest = _absolute_path(manifest_path)
    manifest_stat = _capture_regular_file(manifest, "manifest")
    payload = _read_captured_regular(manifest, manifest_stat)
    raw_records = _parse_manifest(payload)

    errors: list[str] = []
    records: list[_RollbackRecord] = []
    seen: set[Path] = set()
    for raw in raw_records:
        try:
            path = _manifest_destination(raw)
            if path in seen:
                raise RoutingConfigError(f"duplicate manifest path: {path}")
            seen.add(path)
            parent_stat = _capture_parent(path.parent)
            installed_stat = _capture_regular_file(path, "installed destination")
            installed = _read_captured_regular(path, installed_stat)
            installed_digest = _manifest_digest(raw, "installed_sha256")
            if _digest(installed) != installed_digest:
                raise RoutingConfigError(f"digest mismatch for {path}")

            prior_exists = raw.get("prior_exists")
            if type(prior_exists) is not bool:
                raise RoutingConfigError("manifest prior_exists must be boolean")
            prior_digest = _optional_manifest_digest(raw, "prior_sha256")
            backup_name = raw.get("backup_path")
            if prior_exists:
                if prior_digest is None or not isinstance(backup_name, str):
                    raise RoutingConfigError("manifest prior backup is incomplete")
                backup = _safe_backup_path(manifest.parent, backup_name)
                backup_stat = _capture_regular_file(backup, "backup")
                prior = _read_captured_regular(backup, backup_stat)
                if _digest(prior) != prior_digest:
                    raise RoutingConfigError(f"backup digest mismatch for {path}")
            else:
                if prior_digest is not None or backup_name is not None:
                    raise RoutingConfigError("new-file manifest entry has a prior backup")
                prior = None

            records.append(
                _RollbackRecord(
                    path=path,
                    parent_state=_stat_identity(parent_stat),
                    installed_state=_stat_identity(installed_stat),
                    installed=installed,
                    installed_digest=installed_digest,
                    prior_exists=prior_exists,
                    prior=prior,
                    prior_digest=prior_digest,
                )
            )
        except Exception as exc:
            errors.append(_exception_text(exc))

    if errors:
        raise RoutingConfigError("rollback refused: " + "; ".join(errors))

    records.sort(key=lambda record: os.fspath(record.path))
    prepared: dict[Path, _OwnedStage] = {}
    try:
        for record in records:
            if record.prior_exists:
                assert record.prior is not None
                prepared[record.path] = _prepare_stage(
                    record.path, record.prior, "rollback"
                )

        _revalidate_rollback_records(records)

        attempted: list[_RollbackRecord] = []
        try:
            for record in records:
                _revalidate_rollback_record(record)
                attempted.append(record)
                if record.prior_exists:
                    stage = prepared[record.path]
                    _assert_owned_payload(stage, "publication")
                    replace(stage.path, record.path)
                    _assert_published(stage, record.path)
                else:
                    os.unlink(record.path)
                    _assert_removed(record.path)
                _fsync_directory(record.path.parent)
            for record in records:
                _revalidate_destination(
                    record.path, record.parent_state, prepared.get(record.path)
                )
        except Exception as exc:
            compensation_errors: list[str] = []
            restored: list[_RollbackRecord] = []
            for record in attempted:
                try:
                    if _rollback_result_was_published(
                        record, prepared.get(record.path)
                    ):
                        restored.append(record)
                except Exception as inspection_exc:
                    compensation_errors.append(
                        f"{record.path}: rollback inspection failed: "
                        f"{_exception_text(inspection_exc)}"
                    )
            for record in reversed(restored):
                try:
                    _reinstall_after_failed_rollback(
                        record, prepared.get(record.path), replace
                    )
                except Exception as compensation_exc:
                    compensation_errors.append(
                        f"{record.path}: {_exception_text(compensation_exc)}"
                    )
            raise RoutingConfigError(
                _failure_message(exc, compensation_errors, [])
            ) from exc

        return tuple(record.path for record in records)
    finally:
        cleanup_errors: list[str] = []
        for owned in prepared.values():
            _collect_cleanup_error(owned, cleanup_errors)
        if cleanup_errors:
            active = __import__("sys").exc_info()[1]
            message = "cleanup failures: " + "; ".join(cleanup_errors)
            if active is None:
                raise RoutingConfigError(message)
            raise RoutingConfigError(
                f"{_exception_text(active)}; {message}"
            ) from active


def _normalize_updates(updates: tuple[FileUpdate, ...]) -> tuple[FileUpdate, ...]:
    if not isinstance(updates, tuple):
        raise RoutingConfigError("updates must be a tuple")
    normalized: list[FileUpdate] = []
    seen: set[Path] = set()
    for update in updates:
        if not isinstance(update, FileUpdate) or not isinstance(update.after, bytes):
            raise RoutingConfigError("each update must contain a Path and bytes")
        path = _absolute_path(update.path)
        if path in seen:
            raise RoutingConfigError(f"duplicate destination path: {path}")
        seen.add(path)
        normalized.append(FileUpdate(path, update.after))
    return tuple(normalized)


def _capture_destination(path: Path):
    try:
        result = _lstat(path)
    except FileNotFoundError:
        return None
    _reject_link_or_reparse(path, result)
    if not stat.S_ISREG(result.st_mode):
        raise RoutingConfigError(f"destination is not a regular file: {path}")
    return result


def _capture_parent(path: Path):
    try:
        result = _lstat(path)
    except FileNotFoundError as exc:
        raise RoutingConfigError(f"destination parent does not exist: {path}") from exc
    _reject_link_or_reparse(path, result)
    if not stat.S_ISDIR(result.st_mode):
        raise RoutingConfigError(f"destination parent is not a directory: {path}")
    return result


def _capture_regular_file(path: Path, label: str):
    try:
        result = _lstat(path)
    except FileNotFoundError as exc:
        raise RoutingConfigError(f"{label} does not exist: {path}") from exc
    _reject_link_or_reparse(path, result)
    if not stat.S_ISREG(result.st_mode):
        raise RoutingConfigError(f"{label} is not a regular file: {path}")
    return result


def _reject_link_or_reparse(path: Path, result) -> None:
    attributes = getattr(result, "st_file_attributes", 0)
    if stat.S_ISLNK(result.st_mode) or attributes & _REPARSE_POINT:
        raise RoutingConfigError(f"symlink or reparse point is refused: {path}")


def _read_captured_regular(path: Path, captured) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        if _stat_identity(opened) != _stat_identity(captured):
            raise RoutingConfigError(f"file changed during transaction: {path}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _revalidate_updates(records: tuple[_CapturedUpdate, ...]) -> None:
    for record in records:
        parent = _capture_parent(record.path.parent)
        if _stat_identity(parent) != record.parent_state:
            raise RoutingConfigError(
                f"destination parent changed during transaction: {record.path.parent}"
            )
        current = _capture_destination(record.path)
        if record.prior_state is None:
            if current is not None:
                raise RoutingConfigError(
                    f"destination changed during transaction: {record.path}"
                )
            continue
        if current is None or _stat_identity(current) != record.prior_state:
            raise RoutingConfigError(
                f"destination changed during transaction: {record.path}"
            )
        current_bytes = _read_captured_regular(record.path, current)
        if _digest(current_bytes) != record.prior_digest:
            raise RoutingConfigError(
                f"destination changed during transaction: {record.path}"
            )


def _assert_owned_payload(owned: _OwnedStage, phase: str) -> None:
    try:
        current = _capture_regular_file(owned.path, "owned path")
        if _stat_identity(current) != owned.state:
            raise RoutingConfigError("identity mismatch")
        if _digest(_read_captured_regular(owned.path, current)) != owned.digest:
            raise RoutingConfigError("digest mismatch")
    except Exception as exc:
        raise RoutingConfigError(
            f"owned path changed during {phase}: {owned.path}"
        ) from exc


def _assert_published(owned: _OwnedStage, destination: Path) -> None:
    try:
        current = _capture_regular_file(destination, "published destination")
        if _stat_identity(current) != owned.state:
            raise RoutingConfigError("identity mismatch")
        if _digest(_read_captured_regular(destination, current)) != owned.digest:
            raise RoutingConfigError("digest mismatch")
    except Exception as exc:
        raise RoutingConfigError(
            f"replace did not install owned payload: {destination}"
        ) from exc


def _revalidate_success(
    captured: list[_CapturedUpdate], prepared: list[_PreparedUpdate]
) -> None:
    stages = {record.captured.path: record.stage for record in prepared}
    for record in captured:
        parent = _capture_parent(record.path.parent)
        if _stat_identity(parent) != record.parent_state:
            raise RoutingConfigError(
                f"destination parent changed during transaction: {record.path.parent}"
            )
        stage = stages.get(record.path)
        if stage is not None:
            try:
                _assert_published(stage, record.path)
            except RoutingConfigError as exc:
                raise RoutingConfigError(
                    f"destination changed during transaction: {record.path}"
                ) from exc
            continue
        current = _capture_destination(record.path)
        if (
            current is None
            or record.prior_state is None
            or _stat_identity(current) != record.prior_state
            or _digest(_read_captured_regular(record.path, current))
            != record.prior_digest
        ):
            raise RoutingConfigError(
                f"destination changed during transaction: {record.path}"
            )


def _apply_result_was_published(record: _PreparedUpdate) -> bool:
    captured = record.captured
    parent = _capture_parent(captured.path.parent)
    if _stat_identity(parent) != captured.parent_state:
        raise RoutingConfigError("parent identity no longer matches")
    try:
        current = _capture_regular_file(captured.path, "attempted destination")
    except RoutingConfigError as exc:
        try:
            _lstat(captured.path)
        except FileNotFoundError:
            if captured.prior_state is None:
                return False
        raise RoutingConfigError("attempted destination is ambiguous") from exc
    digest = _digest(_read_captured_regular(captured.path, current))
    if _stat_identity(current) == record.stage.state and digest == record.stage.digest:
        return True
    if (
        captured.prior_state is not None
        and _stat_identity(current) == captured.prior_state
        and digest == captured.prior_digest
    ):
        return False
    raise RoutingConfigError("attempted destination digest is ambiguous")


def _revalidate_destination(
    path: Path, parent_state: tuple[int, int, int, int], stage: _OwnedStage | None
) -> None:
    parent = _capture_parent(path.parent)
    if _stat_identity(parent) != parent_state:
        raise RoutingConfigError(f"destination parent changed during transaction: {path.parent}")
    if stage is None:
        _assert_removed(path)
    else:
        _assert_published(stage, path)


def _restore_captured(
    prepared: _PreparedUpdate, replace: Callable[[Path, Path], None]
) -> _OwnedStage | None:
    record = prepared.captured
    _revalidate_destination(record.path, record.parent_state, prepared.stage)
    if record.prior is None:
        os.unlink(record.path)
        _fsync_directory(record.path.parent)
        _revalidate_destination(record.path, record.parent_state, None)
        return None
    stage = _prepare_stage(record.path, record.prior, "rollback")
    try:
        _revalidate_destination(record.path, record.parent_state, prepared.stage)
        _assert_owned_payload(stage, "publication")
        replace(stage.path, record.path)
        _fsync_directory(record.path.parent)
        _revalidate_destination(record.path, record.parent_state, stage)
        return stage
    finally:
        _remove_owned_stage(stage)


def _prepare_stage(destination: Path, payload: bytes, purpose: str) -> _OwnedStage:
    for _ in range(64):
        candidate = _stage_candidate(destination, purpose)
        try:
            fd = os.open(
                candidate,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_BINARY", 0),
                0o600,
            )
        except FileExistsError:
            continue
        created = _OwnedStage(
            candidate, _stat_identity(os.fstat(fd)), _digest(payload)
        )
        try:
            _write_fd(fd, payload)
            os.close(fd)
            fd = -1
            _assert_owned_payload(created, "write")
            return created
        except Exception as exc:
            if fd >= 0:
                os.close(fd)
                fd = -1
            cleanup_errors: list[str] = []
            _collect_cleanup_error(created, cleanup_errors)
            raise RoutingConfigError(
                _failure_message(exc, [], cleanup_errors)
            ) from exc
        finally:
            if fd >= 0:
                os.close(fd)
    raise RoutingConfigError(f"could not create an exclusive stage for {destination}")


def _stage_candidate(destination: Path, purpose: str = "install") -> Path:
    token = secrets.token_hex(12)
    return destination.parent / (
        f".{destination.name}.codex-routing-{purpose}-{token}.tmp"
    )


def _write_exclusive(path: Path, payload: bytes) -> _OwnedStage:
    try:
        fd = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
            0o600,
        )
    except FileExistsError as exc:
        raise RoutingConfigError(f"refusing to overwrite existing path: {path}") from exc
    owned = _OwnedStage(path, _stat_identity(os.fstat(fd)), _digest(payload))
    try:
        _write_fd(fd, payload)
        os.close(fd)
        fd = -1
        _assert_owned_payload(owned, "write")
        return owned
    except Exception as exc:
        if fd >= 0:
            os.close(fd)
            fd = -1
        cleanup_errors: list[str] = []
        _collect_cleanup_error(owned, cleanup_errors)
        raise RoutingConfigError(_failure_message(exc, [], cleanup_errors)) from exc
    finally:
        if fd >= 0:
            os.close(fd)


def _write_fd(fd: int, payload: bytes) -> None:
    with os.fdopen(fd, "wb", closefd=False) as stream:
        written = stream.write(payload)
        if written != len(payload):
            raise OSError(f"short write: {written} of {len(payload)} bytes")
        stream.flush()
        os.fsync(stream.fileno())


def _remove_owned_stage(owned: _OwnedStage) -> None:
    try:
        current = _lstat(owned.path)
    except FileNotFoundError:
        return
    _reject_link_or_reparse(owned.path, current)
    if not stat.S_ISREG(current.st_mode):
        raise RoutingConfigError(
            f"owned temporary path is not a regular file: {owned.path}"
        )
    if _stat_identity(current) != owned.state:
        raise RoutingConfigError(f"owned temporary path was replaced: {owned.path}")
    if _digest(_read_captured_regular(owned.path, current)) != owned.digest:
        raise RoutingConfigError(
            f"owned temporary path content changed: {owned.path}"
        )
    os.unlink(owned.path)


def _collect_cleanup_error(owned: _OwnedStage, errors: list[str]) -> None:
    try:
        _remove_owned_stage(owned)
    except Exception as exc:
        errors.append(f"{owned.path}: {_exception_text(exc)}")


def _create_transaction_directory(backup_root: Path, timestamp: str) -> Path:
    _ensure_directory_tree(backup_root)
    prefix = timestamp.replace(":", "").replace("-", "") + "-"
    raw = tempfile.mkdtemp(prefix=prefix, dir=backup_root)
    transaction_dir = Path(raw)
    _fsync_directory(backup_root)
    return transaction_dir


def _prepare_transaction_evidence(
    changed: list[_CapturedUpdate], backup_root: Path
) -> tuple[Path, Path, _OwnedStage, str]:
    timestamp = _utc_timestamp()
    pending_owned: _OwnedStage | None = None
    try:
        transaction_dir = _create_transaction_directory(backup_root, timestamp)
        files_dir = transaction_dir / "files"
        files_dir.mkdir(mode=0o700)
        _fsync_directory(transaction_dir)

        manifest_entries: list[dict[str, object]] = []
        for index, record in enumerate(changed):
            relative_backup: str | None = None
            if record.prior is not None:
                relative_backup = f"files/{index:04d}.bak"
                _write_exclusive(files_dir / f"{index:04d}.bak", record.prior)
            manifest_entries.append(
                {
                    "backup_path": relative_backup,
                    "installed_sha256": record.installed_digest,
                    "path": os.fspath(record.path),
                    "prior_exists": record.prior is not None,
                    "prior_sha256": record.prior_digest,
                }
            )
        _fsync_directory(files_dir)

        manifest = {
            "created_at": timestamp,
            "files": manifest_entries,
            "platform": _platform_name(),
            "schema": _MANIFEST_SCHEMA,
        }
        pending_manifest = transaction_dir / "manifest.pending.json"
        manifest_bytes = _json_bytes(manifest)
        pending_owned = _write_exclusive(pending_manifest, manifest_bytes)
        _fsync_directory(transaction_dir)
        return (
            transaction_dir,
            pending_manifest,
            pending_owned,
            _digest(manifest_bytes),
        )
    except Exception as exc:
        cleanup_errors: list[str] = []
        if pending_owned is not None:
            _collect_cleanup_error(pending_owned, cleanup_errors)
        raise RoutingConfigError(
            _failure_message(exc, [], cleanup_errors)
        ) from exc


def _ensure_directory_tree(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            result = _lstat(current)
        except FileNotFoundError:
            try:
                current.mkdir(mode=0o700)
            except FileExistsError:
                pass
            result = _lstat(current)
        _reject_link_or_reparse(current, result)
        if not stat.S_ISDIR(result.st_mode):
            raise RoutingConfigError(f"backup path is not a directory: {current}")


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    fd = os.open(path, flags)
    try:
        try:
            os.fsync(fd)
        except OSError as exc:
            if exc.errno not in _UNSUPPORTED_POSIX_DIRECTORY_FSYNC:
                raise
    finally:
        os.close(fd)


def _parse_manifest(payload: bytes) -> list[dict[str, object]]:
    try:
        manifest = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RoutingConfigError(f"invalid transaction manifest: {exc}") from exc
    if (
        not isinstance(manifest, dict)
        or type(manifest.get("schema")) is not int
        or manifest.get("schema") != _MANIFEST_SCHEMA
    ):
        raise RoutingConfigError("unsupported transaction manifest schema")
    files = manifest.get("files")
    if not isinstance(files, list) or not all(isinstance(item, dict) for item in files):
        raise RoutingConfigError("transaction manifest files must be objects")
    return files


def _manifest_destination(raw: dict[str, object]) -> Path:
    value = raw.get("path")
    if not isinstance(value, str):
        raise RoutingConfigError("manifest path must be a string")
    path = Path(value)
    if not path.is_absolute():
        raise RoutingConfigError("manifest destination path must be absolute")
    return _absolute_path(path)


def _manifest_digest(raw: dict[str, object], key: str) -> str:
    value = raw.get(key)
    if not _is_digest(value):
        raise RoutingConfigError(f"manifest {key} is not a SHA-256 digest")
    assert isinstance(value, str)
    return value


def _optional_manifest_digest(raw: dict[str, object], key: str) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    if not _is_digest(value):
        raise RoutingConfigError(f"manifest {key} is not a SHA-256 digest")
    assert isinstance(value, str)
    return value


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def backup_path_parts(relative: str) -> tuple[str, str]:
    """Validate the manifest's portable files/<basename> path on every host."""

    parts = relative.split("/")
    if (
        len(parts) != 2
        or parts[0] != "files"
        or parts[1] in {"", ".", ".."}
        or any(character in relative for character in ("\\", ":", "\x00"))
    ):
        raise RoutingConfigError("manifest backup path escapes its transaction")
    return parts[0], parts[1]


def _safe_backup_path(transaction_dir: Path, relative: str) -> Path:
    backup = transaction_dir.joinpath(*backup_path_parts(relative))
    _capture_parent(backup.parent)
    return backup


def _revalidate_rollback_records(records: list[_RollbackRecord]) -> None:
    for record in records:
        _revalidate_rollback_record(record)


def _revalidate_rollback_record(record: _RollbackRecord) -> None:
    parent = _capture_parent(record.path.parent)
    if _stat_identity(parent) != record.parent_state:
        raise RoutingConfigError(f"parent changed before rollback: {record.path}")
    current = _capture_regular_file(record.path, "installed destination")
    if _stat_identity(current) != record.installed_state:
        raise RoutingConfigError(f"destination changed before rollback: {record.path}")
    if _digest(_read_captured_regular(record.path, current)) != record.installed_digest:
        raise RoutingConfigError(f"digest mismatch for {record.path}")


def _assert_removed(path: Path) -> None:
    try:
        _lstat(path)
    except FileNotFoundError:
        return
    raise RoutingConfigError(f"rollback did not remove destination: {path}")


def _rollback_result_was_published(
    record: _RollbackRecord, stage: _OwnedStage | None
) -> bool:
    parent = _capture_parent(record.path.parent)
    if _stat_identity(parent) != record.parent_state:
        raise RoutingConfigError("parent identity no longer matches")
    try:
        current = _capture_regular_file(record.path, "rollback destination")
    except RoutingConfigError as exc:
        try:
            _lstat(record.path)
        except FileNotFoundError:
            if not record.prior_exists:
                return True
        raise RoutingConfigError("rollback destination is ambiguous") from exc
    digest = _digest(_read_captured_regular(record.path, current))
    if (
        record.prior_exists
        and stage is not None
        and _stat_identity(current) == stage.state
        and digest == stage.digest
    ):
        return True
    if (
        _stat_identity(current) == record.installed_state
        and digest == record.installed_digest
    ):
        return False
    raise RoutingConfigError("rollback destination digest is ambiguous")


def _reinstall_after_failed_rollback(
    record: _RollbackRecord,
    restored_stage: _OwnedStage | None,
    replace: Callable[[Path, Path], None],
) -> None:
    if record.prior_exists:
        assert restored_stage is not None
    restored = _CapturedUpdate(
        path=record.path,
        after=record.installed,
        installed_digest=record.installed_digest,
        parent_state=record.parent_state,
        prior_state=restored_stage.state if record.prior_exists else None,
        prior=record.prior,
        prior_digest=record.prior_digest,
    )
    # Keep the identity of our published rollback stage across compensation of
    # other records; identical bytes do not establish ownership of a replacement.
    _revalidate_updates((restored,))
    stage = _prepare_stage(record.path, record.installed, "compensate")
    try:
        _assert_owned_payload(stage, "publication")
        # Staging may overlap another writer. Protect both restored files and
        # removed destinations, including a changed parent or file identity.
        _revalidate_updates((restored,))
        replace(stage.path, record.path)
        _assert_published(stage, record.path)
        _fsync_directory(record.path.parent)
    finally:
        _remove_owned_stage(stage)


def _stat_identity(result) -> tuple[int, int, int, int]:
    return (
        int(getattr(result, "st_dev", 0)),
        int(getattr(result, "st_ino", 0)),
        stat.S_IFMT(result.st_mode),
        stat.S_IMODE(result.st_mode),
    )


def _lstat(path: Path):
    return path.lstat()


def _absolute_path(path: Path) -> Path:
    if not isinstance(path, Path):
        raise RoutingConfigError("transaction paths must be pathlib.Path values")
    return Path(os.path.abspath(os.fspath(path)))


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json_bytes(payload: dict[str, object]) -> bytes:
    return (
        json.dumps(payload, indent=2, sort_keys=True, separators=(",", ": ")) + "\n"
    ).encode("utf-8")


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _platform_name() -> str:
    return platform.system().lower()


def _exception_text(exc: Exception) -> str:
    return str(exc) or exc.__class__.__name__


def _failure_message(
    original: Exception,
    rollback_errors: list[str],
    cleanup_errors: list[str],
) -> str:
    parts = [f"transaction failed: {_exception_text(original)}"]
    if rollback_errors:
        parts.append("rollback failures: " + "; ".join(rollback_errors))
    if cleanup_errors:
        parts.append("cleanup failures: " + "; ".join(cleanup_errors))
    return "; ".join(parts)
