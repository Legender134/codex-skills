"""Plan, install, and validate isolated global Codex routing configuration."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from codex_routing.errors import RoutingConfigError
from codex_routing.managed_files import (
    FileUpdate,
    apply_transaction,
    merge_managed_block,
)
from codex_routing.spec import AGENT_POLICIES, GLOBAL_POLICIES, PlatformName
from codex_routing.templates import load_template
from codex_routing.toml_merge import merge_global_config


_MANAGED_BLOCK_BEGIN = b"<!-- BEGIN CODEX ROUTING -->"
_MANAGED_BLOCK_END = b"<!-- END CODEX ROUTING -->"
_ROLE_NAMES = ("scout", "explorer", "worker", "reviewer", "routine_worker", "critical_reviewer")
# These digests bind the installer to the approved Task 1 template bytes rather
# than trusting a caller-supplied source root. Update them only with an approved
# template change.
_GLOBAL_TEMPLATE_DIGESTS: dict[PlatformName, str] = {
    "windows": "d704ca463dfbb5dd70fac40181bad5d2461aab857f8b55ee988e950bfa6bcd1f",
    "wsl": "efb3ce759ffe063f5e11e537722de0190d82b73b74557ca85b5d5a3929bb4970",
}
_ROLE_TEMPLATE_DIGESTS: dict[str, str] = {
    "routine_worker": "3ca445b06ec2d29e0fa0d7af9fe96eeb23ac306993d55539f95756b8ee7b6e71",
    "critical_reviewer": "60f571b2dba957aa7f4fb661995ba0e3a60385a47a7d447f03ccc365d77f52af",
    "scout": "868ad6866055f7268c9f7487f88fe51824c03ea0c46e6dbbb84bb11e80e5edba",
    "explorer": "b2815c97e9df121f4e69b6c3f3e0be0a8710d42f039fa62f5391fc839593a734",
    "worker": "3bb2030b40c09e6cc2fd1c3c516b9cc315cedcbc8a432d732cf070d9e6cbd92d",
    "reviewer": "25bc68ee68b310ade6318c9c4f9f8df693f160eba03c8cef2b2a2d71377eb751",
}
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_MOUNTINFO_DECIMAL = re.compile(r"^[0-9]+$")
_MOUNTINFO_MAJOR_MINOR = re.compile(r"^[0-9]+:[0-9]+$")
_MOUNTINFO_ESCAPES = {
    "040": " ",
    "011": "\t",
    "012": "\n",
    "134": "\\",
}
_lstat = os.lstat


@dataclass(frozen=True, repr=False)
class GlobalInstallPlan:
    """The complete dry-run state for one global routing installation."""

    platform: PlatformName
    codex_home: Path
    config_after: bytes
    updates: tuple[FileUpdate, ...]
    applied: bool = False
    manifest_path: Path | None = None
    _managed_before: tuple[tuple[Path, bytes | None], ...] = field(
        default=(), repr=False, compare=False
    )

    def __repr__(self) -> str:
        updates = ", ".join(
            f"{update.path}:sha256={hashlib.sha256(update.after).hexdigest()}"
            for update in self.updates
        )
        return (
            "GlobalInstallPlan("
            f"platform={self.platform!r}, codex_home={self.codex_home!s}, "
            f"updates=({updates}), applied={self.applied!r}, "
            f"manifest_path={self.manifest_path!s})"
        )


@dataclass(frozen=True)
class GlobalValidationReport:
    """A redacted validation result for one installed global configuration."""

    platform: PlatformName
    owned_values: tuple[tuple[str, object], ...]
    agent_files: tuple[Path, ...]
    unrelated_table_names: tuple[str, ...]
    valid: bool


def plan_global_install(
    codex_home: Path,
    platform: PlatformName,
    source_root: Path,
) -> GlobalInstallPlan:
    """Build a no-mutation global installation plan for one platform."""

    policy = _require_platform(platform)
    home = _require_target_home(codex_home, platform)
    config_path = home / "config.toml"
    agents_path = home / "AGENTS.md"
    role_directory = home / "agents"

    config_before = _read_optional_regular(config_path, "config.toml")
    config_after = _merge_config(config_path, config_before, policy)

    agents_before = _read_optional_regular(agents_path, "AGENTS.md")
    global_body = _global_template(source_root, platform)
    agents_after = _merge_agents(agents_path, agents_before, global_body)

    role_directory_exists = _require_optional_directory(role_directory, "agents")
    role_templates = _role_templates(source_root)
    updates: list[FileUpdate] = []
    managed_before: dict[Path, bytes | None] = {
        config_path: config_before,
        agents_path: agents_before,
    }
    if config_before != config_after:
        updates.append(FileUpdate(config_path, config_after))
    if agents_before != agents_after:
        updates.append(FileUpdate(agents_path, agents_after))

    for role_name in _ROLE_NAMES:
        destination = role_directory / f"{role_name}.toml"
        existing = (
            _read_optional_regular(destination, f"agent {destination.name}")
            if role_directory_exists
            else None
        )
        managed_before[destination] = existing
        template = role_templates[role_name]
        if existing is None:
            updates.append(FileUpdate(destination, template))
        elif existing != template:
            raise RoutingConfigError(
                f"refusing to overwrite foreign agent file: {destination}"
            )

    return GlobalInstallPlan(
        platform=platform,
        codex_home=home,
        config_after=config_after,
        updates=tuple(updates),
        _managed_before=tuple(managed_before.items()),
    )


def install_global(
    codex_home: Path,
    platform: PlatformName,
    source_root: Path,
    *,
    apply: bool = False,
) -> GlobalInstallPlan:
    """Return a dry-run plan, or atomically install all global routing files."""

    plan = plan_global_install(codex_home, platform, source_root)
    if not apply:
        return plan

    role_directory = plan.codex_home / "agents"
    created_directory, directory_state = _ensure_role_directory(role_directory)
    try:
        plan = plan_global_install(plan.codex_home, platform, source_root)
        transaction_updates, expected_before = _capture_transaction_preconditions(
            plan, source_root
        )
        result = apply_transaction(
            transaction_updates,
            plan.codex_home / "backups",
            replace=_preconditioned_replace(expected_before),
        )
    except RoutingConfigError:
        _remove_created_directory(role_directory, created_directory, directory_state)
        raise
    except OSError as exc:
        _remove_created_directory(role_directory, created_directory, directory_state)
        raise RoutingConfigError(
            f"global installation transaction failed at {plan.codex_home}"
        ) from exc

    return GlobalInstallPlan(
        platform=plan.platform,
        codex_home=plan.codex_home,
        config_after=plan.config_after,
        updates=plan.updates,
        applied=True,
        manifest_path=result.manifest_path,
    )


def validate_global_install(
    codex_home: Path,
    platform: PlatformName,
    source_root: Path,
) -> GlobalValidationReport:
    """Validate only routing-owned values without exposing unrelated contents."""

    policy = _require_platform(platform)
    home = _require_target_home(codex_home, platform)
    config_path = home / "config.toml"
    agents_path = home / "AGENTS.md"
    role_directory = home / "agents"

    config_bytes = _read_optional_regular(config_path, "config.toml")
    payload = _parse_config(config_path, config_bytes)
    actual_owned_values = _actual_owned_values(payload)
    expected_owned_values = _expected_owned_values(policy)

    agents_bytes = _read_optional_regular(agents_path, "AGENTS.md")
    global_body = _global_template(source_root, platform)
    managed_block_valid = _managed_block_is_current(
        agents_path, agents_bytes, global_body
    )

    role_directory_exists = _require_optional_directory(role_directory, "agents")
    role_templates = _role_templates(source_root)
    agent_files = tuple(role_directory / f"{role_name}.toml" for role_name in _ROLE_NAMES)
    role_files_valid = role_directory_exists
    for role_name, destination in zip(_ROLE_NAMES, agent_files, strict=True):
        existing = (
            _read_optional_regular(destination, f"agent {destination.name}")
            if role_directory_exists
            else None
        )
        if existing != role_templates[role_name]:
            role_files_valid = False

    return GlobalValidationReport(
        platform=platform,
        owned_values=expected_owned_values,
        agent_files=agent_files,
        unrelated_table_names=_unrelated_table_names(payload),
        valid=(
            _owned_values_match(actual_owned_values, expected_owned_values)
            and managed_block_valid
            and role_files_valid
        ),
    )


def _require_platform(platform: PlatformName):
    if platform not in GLOBAL_POLICIES:
        raise RoutingConfigError(f"unsupported platform target: {platform!r}")
    return GLOBAL_POLICIES[platform]


def _require_home(codex_home: Path) -> Path:
    try:
        home = Path(os.path.abspath(os.fspath(codex_home)))
    except (TypeError, ValueError) as exc:
        raise RoutingConfigError("codex home must be a filesystem path") from exc
    _require_directory(home, "codex home")
    return home


def _require_target_home(codex_home: Path, platform: PlatformName) -> Path:
    home = _require_home(codex_home)
    resolved = _resolve_home(home)
    lexical_target = _classify_home_target(home)
    resolved_target = _classify_home_target(resolved)
    if lexical_target != resolved_target:
        raise RoutingConfigError(f"codex home target is ambiguous: {home}")
    if lexical_target != platform:
        raise RoutingConfigError(
            f"codex home target {lexical_target!r} does not match {platform!r}: {home}"
        )
    return home


def _resolve_home(home: Path) -> Path:
    try:
        resolved = Path(os.path.abspath(os.fspath(home.resolve(strict=True))))
    except (OSError, RuntimeError) as exc:
        raise RoutingConfigError(f"unable to resolve codex home: {home}") from exc
    _require_directory(resolved, "resolved codex home")
    return resolved


def _classify_home_target(home: Path) -> PlatformName:
    if os.name == "nt":
        return "windows"
    for mount_root in _windows_mount_roots():
        try:
            home.relative_to(mount_root)
        except ValueError:
            continue
        return "windows"
    return "wsl"


def _windows_mount_roots() -> tuple[Path, ...]:
    try:
        mountinfo = Path("/proc/self/mountinfo").read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise RoutingConfigError("unable to inspect WSL mountinfo") from exc

    roots: list[Path] = []
    records = 0
    for line in mountinfo.splitlines():
        if not line.strip():
            continue
        fields = line.split()
        try:
            separator = fields.index("-")
        except ValueError:
            raise RoutingConfigError("malformed WSL mountinfo")
        if (
            fields.count("-") != 1
            or separator < 6
            or len(fields) != separator + 4
            or not _MOUNTINFO_DECIMAL.fullmatch(fields[0])
            or not _MOUNTINFO_DECIMAL.fullmatch(fields[1])
            or not _MOUNTINFO_MAJOR_MINOR.fullmatch(fields[2])
        ):
            raise RoutingConfigError("malformed WSL mountinfo")
        records += 1
        root = _decode_mountinfo_path(fields[3])
        mountpoint = _decode_mountinfo_path(fields[4])
        if not os.path.isabs(root) or not os.path.isabs(mountpoint):
            raise RoutingConfigError("malformed WSL mountinfo")
        filesystem = fields[separator + 1]
        super_options = fields[separator + 3]
        is_drvfs = (
            filesystem == "drvfs"
            or (
                filesystem == "9p"
                and _has_drvfs_super_option(super_options)
            )
        )
        if is_drvfs:
            roots.append(Path(os.path.abspath(mountpoint)))
    if records == 0:
        raise RoutingConfigError("WSL mountinfo contains no recognizable records")
    return tuple(sorted(set(roots), key=lambda path: len(os.fspath(path)), reverse=True))


def _decode_mountinfo_path(value: str) -> str:
    decoded: list[str] = []
    index = 0
    while index < len(value):
        character = value[index]
        if character != "\\":
            decoded.append(character)
            index += 1
            continue
        escape = value[index + 1 : index + 4]
        replacement = _MOUNTINFO_ESCAPES.get(escape)
        if replacement is None:
            raise RoutingConfigError("malformed WSL mountinfo")
        decoded.append(replacement)
        index += 4
    return "".join(decoded)


def _has_drvfs_super_option(super_options: str) -> bool:
    return any(
        option == "aname=drvfs"
        for field in super_options.split(",")
        for option in field.split(";")
    )


def _capture_transaction_preconditions(
    plan: GlobalInstallPlan, source_root: Path
) -> tuple[tuple[FileUpdate, ...], dict[Path, bytes | None]]:
    config_path = plan.codex_home / "config.toml"
    agents_path = plan.codex_home / "AGENTS.md"
    role_directory = plan.codex_home / "agents"
    destinations = (config_path, agents_path) + tuple(
        role_directory / f"{role_name}.toml" for role_name in _ROLE_NAMES
    )
    expected_before = dict(plan._managed_before)
    if set(expected_before) != set(destinations):
        raise RoutingConfigError("global installation preconditions are incomplete")

    planned_after = {update.path: update.after for update in plan.updates}
    agents_after = planned_after.get(agents_path, expected_before[agents_path])
    if agents_after is None:
        raise RoutingConfigError("global AGENTS.md precondition is incomplete")

    role_templates = _role_templates(source_root)
    transaction_updates = [
        FileUpdate(config_path, plan.config_after),
        FileUpdate(agents_path, agents_after),
    ]
    transaction_updates.extend(
        FileUpdate(role_directory / f"{role_name}.toml", role_templates[role_name])
        for role_name in _ROLE_NAMES
    )

    for update in transaction_updates:
        current = _read_optional_regular(update.path, "global transaction target")
        if current != expected_before[update.path]:
            raise RoutingConfigError(
                f"global destination changed after final preflight: {update.path}"
            )
    return tuple(transaction_updates), expected_before


def _preconditioned_replace(expected_before: dict[Path, bytes | None]):
    pending = dict(expected_before)

    def replace(source: Path, destination: Path) -> None:
        if destination in pending:
            current = _read_optional_regular(destination, "global transaction target")
            if current != pending[destination]:
                raise RoutingConfigError(
                    f"global destination changed after final preflight: {destination}"
                )
            # Task 3 invokes this transaction-scoped callback again only to
            # roll back a destination that os.replace may have published before
            # reporting an error. Consume the first-publication guard before
            # that call so the rollback can restore Task 3's captured bytes.
            pending.pop(destination)
        os.replace(source, destination)

    return replace


def _role_templates(source_root: Path) -> dict[str, bytes]:
    templates: dict[str, bytes] = {}
    for role_name in _ROLE_NAMES:
        template = _load_approved_template(
            source_root,
            f"agents/{role_name}.toml",
            _ROLE_TEMPLATE_DIGESTS[role_name],
        )
        _assert_approved_role_template(role_name, template)
        templates[role_name] = template
    return templates


def _global_template(source_root: Path, platform: PlatformName) -> bytes:
    return _load_approved_template(
        source_root,
        f"global/{platform}-AGENTS.md",
        _GLOBAL_TEMPLATE_DIGESTS[platform],
    )


def _load_approved_template(
    source_root: Path, relative_path: str, expected_digest: str
) -> bytes:
    template = load_template(source_root, relative_path)
    if hashlib.sha256(template).hexdigest() != expected_digest:
        raise RoutingConfigError(
            f"template does not match approved template bytes: {relative_path}"
        )
    return template


def _assert_approved_role_template(role_name: str, template: bytes) -> None:
    policy = AGENT_POLICIES.get(role_name)
    if policy is None:
        raise RoutingConfigError(f"unknown approved agent role: {role_name}")
    try:
        payload = tomllib.loads(template.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise RoutingConfigError(
            f"agent template is invalid: {role_name}.toml"
        ) from exc
    if (
        payload.get("name") != policy.name
        or payload.get("model") != policy.model
        or payload.get("model_reasoning_effort") != policy.effort
        or payload.get("sandbox_mode") != policy.sandbox_mode
    ):
        raise RoutingConfigError(
            f"agent template does not match approved policy: {role_name}.toml"
        )


def _merge_config(config_path: Path, before: bytes | None, policy) -> bytes:
    raw = before or b""
    try:
        existing = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RoutingConfigError(f"config.toml is not UTF-8: {config_path}") from exc
    try:
        return merge_global_config(existing, policy).encode("utf-8")
    except RoutingConfigError as exc:
        raise RoutingConfigError(
            f"unable to merge config.toml at {config_path}: {exc}"
        ) from exc


def _merge_agents(agents_path: Path, before: bytes | None, body: bytes) -> bytes:
    try:
        return merge_managed_block(
            before or b"",
            body,
            _MANAGED_BLOCK_BEGIN,
            _MANAGED_BLOCK_END,
        )
    except RoutingConfigError as exc:
        raise RoutingConfigError(
            f"unable to merge AGENTS.md at {agents_path}: {exc}"
        ) from exc


def _parse_config(config_path: Path, raw: bytes | None) -> dict[str, object]:
    if raw is None:
        return {}
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RoutingConfigError(f"config.toml is not UTF-8: {config_path}") from exc
    try:
        return tomllib.loads(decoded) if decoded.strip() else {}
    except tomllib.TOMLDecodeError as exc:
        raise RoutingConfigError(f"invalid TOML at {config_path}: {exc}") from exc


def _expected_owned_values(policy) -> tuple[tuple[str, object], ...]:
    return (
        ("model", policy.primary_model),
        ("model_reasoning_effort", policy.primary_effort),
        ("agents.enabled", True),
        ("agents.max_concurrent_threads_per_session", policy.max_threads),
        ("agents.default_subagent_model", policy.default_subagent_model),
        (
            "agents.default_subagent_reasoning_effort",
            policy.default_subagent_effort,
        ),
        ("agents.interrupt_message", policy.interrupt_message),
    )


def _actual_owned_values(payload: dict[str, object]) -> tuple[tuple[str, object], ...]:
    agents = payload.get("agents")
    agent_values = agents if isinstance(agents, dict) else {}
    return (
        ("model", payload.get("model")),
        ("model_reasoning_effort", payload.get("model_reasoning_effort")),
        ("agents.enabled", agent_values.get("enabled")),
        (
            "agents.max_concurrent_threads_per_session",
            agent_values.get("max_concurrent_threads_per_session"),
        ),
        ("agents.default_subagent_model", agent_values.get("default_subagent_model")),
        (
            "agents.default_subagent_reasoning_effort",
            agent_values.get("default_subagent_reasoning_effort"),
        ),
        ("agents.interrupt_message", agent_values.get("interrupt_message")),
    )


def _owned_values_match(
    actual: tuple[tuple[str, object], ...], expected: tuple[tuple[str, object], ...]
) -> bool:
    return len(actual) == len(expected) and all(
        actual_key == expected_key
        and type(actual_value) is type(expected_value)
        and actual_value == expected_value
        for (actual_key, actual_value), (expected_key, expected_value) in zip(
            actual, expected, strict=True
        )
    )


def _managed_block_is_current(
    agents_path: Path, existing: bytes | None, body: bytes
) -> bool:
    if existing is None:
        return False
    try:
        return (
            merge_managed_block(
                existing,
                body,
                _MANAGED_BLOCK_BEGIN,
                _MANAGED_BLOCK_END,
            )
            == existing
        )
    except RoutingConfigError:
        return False


def _unrelated_table_names(payload: dict[str, object]) -> tuple[str, ...]:
    return tuple(
        sorted(
            key
            for key, value in payload.items()
            if key != "agents"
            and key not in {"model", "model_reasoning_effort"}
            and isinstance(value, dict)
        )
    )


def _require_optional_directory(path: Path, label: str) -> bool:
    try:
        result = _lstat(path)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise RoutingConfigError(f"unable to inspect {label}: {path}") from exc
    _reject_link_or_reparse(path, result)
    if not stat.S_ISDIR(result.st_mode):
        raise RoutingConfigError(f"{label} is not a directory: {path}")
    return True


def _require_directory(path: Path, label: str) -> tuple[int, int, int, int]:
    try:
        result = _lstat(path)
    except FileNotFoundError as exc:
        raise RoutingConfigError(f"{label} does not exist: {path}") from exc
    except OSError as exc:
        raise RoutingConfigError(f"unable to inspect {label}: {path}") from exc
    _reject_link_or_reparse(path, result)
    if not stat.S_ISDIR(result.st_mode):
        raise RoutingConfigError(f"{label} is not a directory: {path}")
    return _stat_identity(result)


def _read_optional_regular(path: Path, label: str) -> bytes | None:
    try:
        result = _lstat(path)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise RoutingConfigError(f"unable to inspect {label}: {path}") from exc
    _reject_link_or_reparse(path, result)
    if not stat.S_ISREG(result.st_mode):
        raise RoutingConfigError(f"{label} is not a regular file: {path}")
    return _read_captured_regular(path, result, label)


def _read_captured_regular(path: Path, captured, label: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise RoutingConfigError(f"unable to read {label}: {path}") from exc
    try:
        opened = os.fstat(fd)
        _reject_link_or_reparse(path, opened)
        if _stat_identity(opened) != _stat_identity(captured):
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
        os.close(fd)


def _ensure_role_directory(
    role_directory: Path,
) -> tuple[bool, tuple[int, int, int, int]]:
    try:
        result = _lstat(role_directory)
    except FileNotFoundError:
        try:
            role_directory.mkdir()
        except FileExistsError:
            return False, _require_directory(role_directory, "agents")
        except OSError as exc:
            raise RoutingConfigError(
                f"unable to create agents directory: {role_directory}"
            ) from exc
        return True, _require_directory(role_directory, "agents")
    except OSError as exc:
        raise RoutingConfigError(
            f"unable to inspect agents directory: {role_directory}"
        ) from exc
    _reject_link_or_reparse(role_directory, result)
    if not stat.S_ISDIR(result.st_mode):
        raise RoutingConfigError(f"agents is not a directory: {role_directory}")
    return False, _stat_identity(result)


def _remove_created_directory(
    path: Path, created: bool, expected_state: tuple[int, int, int, int]
) -> None:
    if not created:
        return
    try:
        current = _lstat(path)
    except OSError:
        return
    if _stat_identity(current) != expected_state:
        return
    try:
        path.rmdir()
    except OSError:
        return


def _reject_link_or_reparse(path: Path, result) -> None:
    attributes = getattr(result, "st_file_attributes", 0)
    if stat.S_ISLNK(result.st_mode) or attributes & _REPARSE_POINT:
        raise RoutingConfigError(f"symlink or reparse point is refused: {path}")


def _stat_identity(result) -> tuple[int, int, int, int]:
    return (
        result.st_dev,
        result.st_ino,
        result.st_mode,
        getattr(result, "st_file_attributes", 0),
    )
