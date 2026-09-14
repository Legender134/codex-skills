"""Validate immutable routing source artifacts and plan guarded rollbacks."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from codex_routing.errors import RoutingConfigError
from codex_routing.templates import load_template


_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_EXPECTED_TEMPLATE_DIGESTS: dict[str, str] = {
    "agents/routine_worker.toml": "036d222bfde9c82619f0f35bc74a1e8257b59d3289e41196f52894af9a0c0f4d",
    "agents/critical_reviewer.toml": "d613a4cb503f40ec3a23d92ec57233020c0ee883cc6c9015316f997d94f762fd",
    "agents/explorer.toml": (
        "1a9980f408b220458985cbaa0100cb3ee7aff97e6b050fca5ecf3649437d9a26"
    ),
    "agents/reviewer.toml": (
        "a8417f650d7e00b4f313a4347c0476e71bde38bcfc59a1082a8dc8d47d17dd3d"
    ),
    "agents/scout.toml": (
        "ddd5f721ec481809c75c966bad85c8fa53e7c5f3ea28068142ebf89d6141d60d"
    ),
    "agents/worker.toml": (
        "c81e6e6073154e0c917e002aa561db99d8c701a3d50be54c1fe1c79c737d6f1a"
    ),
    "global/windows-AGENTS.md": (
        "42a8e02942a6a4e2c635d4ee301b78eb82bbf8d8c4d7e99dd6760707d7a236f0"
    ),
    "global/wsl-AGENTS.md": (
        "813f679e261111d8e2902b59e43dce855570e76784b7ebfc3b95fb9c1de9ba62"
    ),
    "projects/3dgs-gen-AGENTS.md": (
        "4ae732aae6a78f8bfdb7ac417b46a967a02945ee28e6a940df5d6cd389b2cb49"
    ),
    "projects/common-config.toml": (
        "a8688cf1be0a447f454078190adeac254e2917af172ab53e55e05d4bbfd5b1d8"
    ),
    "projects/critical_reviewer.toml": (
        "c783c5dddb9cbc73d213a77ed28b5aa3f8855b620281ab2d73253c4f16d18590"
    ),
    "projects/egs-main-AGENTS.md": (
        "85893b8ee1c442e8f5ee7da55492e0a8f1447a61b4a390fd4a6f5f6ce50b2d89"
    ),
    "projects/preprocess-cli-AGENTS.md": (
        "d71cfd355e56e117a9b22bf82fc1e5e69923cae824c0a06dc99b7532f808482d"
    ),
}
_EXPECTED_DIRECTORIES = {"", "agents", "global", "projects"}


@dataclass(frozen=True, repr=False)
class SourceValidationReport:
    """A source-only validation result with no template contents."""

    source_root: Path
    template_digests: tuple[tuple[str, str], ...]

    def __repr__(self) -> str:
        templates = ", ".join(
            f"{path}:sha256={digest}" for path, digest in self.template_digests
        )
        return (
            "SourceValidationReport("
            f"source_root={self.source_root!s}, templates=({templates}))"
        )


@dataclass(frozen=True, repr=False)
class RollbackPlan:
    """A parsed manifest summary used for a no-mutation rollback preview."""

    manifest_path: Path
    destinations: tuple[Path, ...]

    def __repr__(self) -> str:
        paths = ", ".join(os.fspath(path) for path in self.destinations)
        return (
            "RollbackPlan("
            f"manifest_path={self.manifest_path!s}, destinations=({paths}))"
        )


def validate_source(source_root: Path) -> SourceValidationReport:
    """Require the exact approved template inventory and SHA-256 bytes.

    This function intentionally operates only on the checked-in source tree. It
    does not accept or inspect a live Codex home, project workspace, or config.
    """

    root = _require_source_root(source_root)
    _validate_template_inventory(root / "templates")
    digests: list[tuple[str, str]] = []
    for relative_path, expected_digest in _EXPECTED_TEMPLATE_DIGESTS.items():
        payload = load_template(root, relative_path)
        actual_digest = hashlib.sha256(payload).hexdigest()
        if actual_digest != expected_digest:
            raise RoutingConfigError(
                f"source template digest does not match approval: {relative_path}"
            )
        digests.append((relative_path, actual_digest))
    return SourceValidationReport(root, tuple(digests))


def plan_rollback(manifest_path: Path) -> RollbackPlan:
    """Parse a transaction manifest without reading or modifying destinations."""

    manifest = _require_regular_file(manifest_path, "rollback manifest")
    payload = _read_regular_file(manifest, "rollback manifest")
    raw = _parse_manifest(payload)
    destinations = tuple(_manifest_destination(item) for item in raw)
    if len(set(destinations)) != len(destinations):
        raise RoutingConfigError("transaction manifest contains duplicate paths")
    return RollbackPlan(manifest, tuple(sorted(destinations, key=os.fspath)))


def _require_source_root(source_root: Path) -> Path:
    try:
        root = Path(os.path.abspath(os.fspath(source_root)))
    except (TypeError, ValueError) as exc:
        raise RoutingConfigError("source root must be a filesystem path") from exc
    try:
        state = os.lstat(root)
    except FileNotFoundError as exc:
        raise RoutingConfigError(f"source root does not exist: {root}") from exc
    except OSError as exc:
        raise RoutingConfigError(f"unable to inspect source root: {root}") from exc
    _reject_link_or_reparse(root, state)
    if not stat.S_ISDIR(state.st_mode):
        raise RoutingConfigError(f"source root is not a directory: {root}")
    return root


def _validate_template_inventory(templates_root: Path) -> None:
    _require_directory(templates_root, "template root")
    found_files: set[str] = set()
    pending = [templates_root]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    path = Path(entry.path)
                    relative = path.relative_to(templates_root).as_posix()
                    state = os.lstat(path)
                    _reject_link_or_reparse(path, state)
                    if stat.S_ISDIR(state.st_mode):
                        if relative not in _EXPECTED_DIRECTORIES:
                            raise RoutingConfigError(
                                f"unapproved source template artifact: {relative}"
                            )
                        pending.append(path)
                        continue
                    if not stat.S_ISREG(state.st_mode):
                        raise RoutingConfigError(
                            f"source template artifact is not a regular file: {relative}"
                        )
                    if relative not in _EXPECTED_TEMPLATE_DIGESTS:
                        raise RoutingConfigError(
                            f"unapproved source template artifact: {relative}"
                        )
                    found_files.add(relative)
        except OSError as exc:
            raise RoutingConfigError(
                f"unable to validate source artifacts at {templates_root.parent}"
            ) from exc

    missing = tuple(sorted(set(_EXPECTED_TEMPLATE_DIGESTS) - found_files))
    if missing:
        raise RoutingConfigError(f"missing approved source template: {missing[0]}")


def _parse_manifest(payload: bytes) -> list[dict[str, object]]:
    try:
        manifest = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RoutingConfigError("invalid transaction manifest") from exc
    if (
        not isinstance(manifest, dict)
        or type(manifest.get("schema")) is not int
        or manifest.get("schema") != 1
    ):
        raise RoutingConfigError("unsupported transaction manifest schema")
    files = manifest.get("files")
    if not isinstance(files, list) or not all(isinstance(item, dict) for item in files):
        raise RoutingConfigError("transaction manifest files must be objects")
    for item in files:
        _validate_manifest_record(item)
    return files


def _validate_manifest_record(record: dict[str, object]) -> None:
    _manifest_destination(record)
    if not _is_digest(record.get("installed_sha256")):
        raise RoutingConfigError("manifest installed_sha256 is not a SHA-256 digest")
    prior_exists = record.get("prior_exists")
    if type(prior_exists) is not bool:
        raise RoutingConfigError("manifest prior_exists must be boolean")
    prior_digest = record.get("prior_sha256")
    backup_path = record.get("backup_path")
    if prior_exists:
        if not _is_digest(prior_digest) or not isinstance(backup_path, str):
            raise RoutingConfigError("manifest prior backup is incomplete")
        _validate_backup_path(backup_path)
    elif prior_digest is not None or backup_path is not None:
        raise RoutingConfigError("new-file manifest entry has a prior backup")


def _manifest_destination(record: dict[str, object]) -> Path:
    value = record.get("path")
    if not isinstance(value, str):
        raise RoutingConfigError("manifest path must be a string")
    path = Path(value)
    if not path.is_absolute():
        raise RoutingConfigError("manifest destination path must be absolute")
    return Path(os.path.abspath(os.fspath(path)))


def _validate_backup_path(value: str) -> None:
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or len(path.parts) != 2
        or path.parts[0] != "files"
        or ".." in path.parts
    ):
        raise RoutingConfigError("manifest backup path escapes its transaction")


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _require_directory(path: Path, label: str) -> None:
    try:
        state = os.lstat(path)
    except FileNotFoundError as exc:
        raise RoutingConfigError(f"{label} does not exist: {path}") from exc
    except OSError as exc:
        raise RoutingConfigError(f"unable to inspect {label}: {path}") from exc
    _reject_link_or_reparse(path, state)
    if not stat.S_ISDIR(state.st_mode):
        raise RoutingConfigError(f"{label} is not a directory: {path}")


def _require_regular_file(path: Path, label: str) -> Path:
    try:
        candidate = Path(os.path.abspath(os.fspath(path)))
    except (TypeError, ValueError) as exc:
        raise RoutingConfigError(f"{label} must be a filesystem path") from exc
    try:
        state = os.lstat(candidate)
    except FileNotFoundError as exc:
        raise RoutingConfigError(f"{label} does not exist: {candidate}") from exc
    except OSError as exc:
        raise RoutingConfigError(f"unable to inspect {label}: {candidate}") from exc
    _reject_link_or_reparse(candidate, state)
    if not stat.S_ISREG(state.st_mode):
        raise RoutingConfigError(f"{label} is not a regular file: {candidate}")
    return candidate


def _read_regular_file(path: Path, label: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        expected = os.lstat(path)
        fd = os.open(path, flags)
    except OSError as exc:
        raise RoutingConfigError(f"unable to read {label}: {path}") from exc
    try:
        opened = os.fstat(fd)
        _reject_link_or_reparse(path, opened)
        if not stat.S_ISREG(opened.st_mode) or _stat_identity(opened) != _stat_identity(
            expected
        ):
            raise RoutingConfigError(f"{label} changed during read: {path}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
    except OSError as exc:
        raise RoutingConfigError(f"unable to read {label}: {path}") from exc
    finally:
        try:
            os.close(fd)
        except OSError as exc:
            raise RoutingConfigError(f"unable to read {label}: {path}") from exc


def _reject_link_or_reparse(path: Path, state) -> None:
    attributes = getattr(state, "st_file_attributes", 0)
    if stat.S_ISLNK(state.st_mode) or attributes & _REPARSE_POINT:
        raise RoutingConfigError(f"symlink or reparse point is refused: {path}")


def _stat_identity(state) -> tuple[int, int, int, int]:
    return (
        state.st_dev,
        state.st_ino,
        state.st_mode,
        getattr(state, "st_file_attributes", 0),
    )
