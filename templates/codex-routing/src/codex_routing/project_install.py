"""Manage local EGS overlays and validate repository-owned routing without rewriting it."""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

from codex_routing.errors import RoutingConfigError
from codex_routing.managed_files import (
    FileUpdate,
    apply_transaction,
    merge_managed_block,
    rollback_transaction,
)
from codex_routing.spec import AGENT_POLICIES, REPO_POLICIES
from codex_routing.templates import load_template


_REPO_NAMES = ("preprocess-cli", "3dgs-gen", "egs-main")
_EXCLUDE_BEGIN = b"# BEGIN CODEX ROUTING"
_EXCLUDE_END = b"# END CODEX ROUTING"
_EXCLUDE_BODY = b"/.codex/\n/AGENTS.md"
_PROJECT_TEMPLATE_DIGESTS = {
    "projects/preprocess-cli-AGENTS.md": (
        "d71cfd355e56e117a9b22bf82fc1e5e69923cae824c0a06dc99b7532f808482d"
    ),
    "projects/3dgs-gen-AGENTS.md": (
        "4ae732aae6a78f8bfdb7ac417b46a967a02945ee28e6a940df5d6cd389b2cb49"
    ),
    "projects/egs-main-AGENTS.md": (
        "85893b8ee1c442e8f5ee7da55492e0a8f1447a61b4a390fd4a6f5f6ce50b2d89"
    ),
    "projects/common-config.toml": (
        "a8688cf1be0a447f454078190adeac254e2917af172ab53e55e05d4bbfd5b1d8"
    ),
    "projects/critical_reviewer.toml": (
        "c783c5dddb9cbc73d213a77ed28b5aa3f8855b620281ab2d73253c4f16d18590"
    ),
}
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_lstat = os.lstat


@dataclass(frozen=True)
class ProjectInstallPlan:
    repo_root: Path
    repo_name: str
    updates: tuple[FileUpdate, ...]
    applied: bool = False
    manifest_path: Path | None = None
    ownership: str = "local"


@dataclass(frozen=True)
class ProjectValidationReport:
    repo_root: Path
    repo_name: str
    ignored_paths: tuple[Path, ...]
    valid: bool
    ownership: str = "local"


def plan_project_install(
    repo_root: Path,
    repo_name: str,
    source_root: Path,
) -> ProjectInstallPlan:
    """Return the complete overlay update set without changing the repository."""

    policy = _require_repo_policy(repo_name)
    root = require_exact_git_root(repo_root, repo_name)
    ownership = _overlay_ownership(root)
    if ownership == "repository":
        report = validate_project_overlay(root, repo_name, source_root)
        if not report.valid:
            raise RoutingConfigError(f"repository-owned routing is invalid: {root}")
        return ProjectInstallPlan(root, repo_name, (), ownership="repository")
    _reject_tracked_targets(root)

    templates = _project_templates(source_root, policy.instructions_template)
    config_directory = root / ".codex"
    agents_directory = config_directory / "agents"
    _require_codex_inventory(root)

    destinations = (
        (root / "AGENTS.md", templates["instructions"]),
        (config_directory / "config.toml", templates["config"]),
        (
            agents_directory / "critical_reviewer.toml",
            templates["critical_reviewer"],
        ),
    )
    updates: list[FileUpdate] = []
    for destination, expected in destinations:
        existing = _read_optional_regular(destination, "overlay target")
        if existing is None:
            updates.append(FileUpdate(destination, expected))
        elif existing != expected:
            raise RoutingConfigError(
                f"refusing to overwrite foreign untracked target: {destination}"
            )

    exclude = _git_path(root, "info/exclude")
    _require_directory(exclude.parent, "Git info directory")
    exclude_before = _read_optional_regular(exclude, "Git exclude file")
    try:
        exclude_after = merge_managed_block(
            exclude_before or b"", _EXCLUDE_BODY, _EXCLUDE_BEGIN, _EXCLUDE_END
        )
    except RoutingConfigError as exc:
        raise RoutingConfigError(
            f"unable to merge Git exclude file at {exclude}: {exc}"
        ) from exc
    if exclude_before != exclude_after:
        updates.append(FileUpdate(exclude, exclude_after))

    return ProjectInstallPlan(root, repo_name, tuple(updates))


def install_project_overlay(
    repo_root: Path,
    repo_name: str,
    source_root: Path,
    *,
    apply: bool = False,
) -> ProjectInstallPlan:
    """Dry-run or atomically publish one repository's local overlay."""

    plan = plan_project_install(repo_root, repo_name, source_root)
    if not apply or plan.ownership == "repository":
        return plan
    status_before = _git_status(plan.repo_root)

    created: list[tuple[Path, tuple[int, int, int, int]]] = []
    try:
        created = _ensure_overlay_directories((plan.repo_root,))
        plan = plan_project_install(plan.repo_root, repo_name, source_root)
        transaction_updates, expected_before = _capture_transaction_preconditions(
            (plan,), source_root
        )
        result = apply_transaction(
            transaction_updates,
            _git_path(plan.repo_root, "codex-routing-backups"),
            replace=_preconditioned_replace(expected_before),
        )
        _require_unchanged_status(
            ((plan.repo_root, status_before),), result.manifest_path, created
        )
    except Exception:
        _remove_created_directories(created)
        raise

    return ProjectInstallPlan(
        plan.repo_root,
        plan.repo_name,
        plan.updates,
        applied=True,
        manifest_path=result.manifest_path,
    )


def install_egs_workspace(
    workspace_root: Path,
    source_root: Path,
    *,
    apply: bool = False,
) -> tuple[ProjectInstallPlan, ...]:
    """Preflight and publish all three EGS overlays as one transaction."""

    workspace = _require_directory_path(workspace_root, "EGS workspace")
    roots = tuple(workspace / name for name in _REPO_NAMES)
    plans = tuple(
        plan_project_install(root, name, source_root)
        for root, name in zip(roots, _REPO_NAMES, strict=True)
    )
    if not apply or all(plan.ownership == "repository" for plan in plans):
        return plans
    statuses = tuple((plan.repo_root, _git_status(plan.repo_root)) for plan in plans)

    created: list[tuple[Path, tuple[int, int, int, int]]] = []
    try:
        created = _ensure_overlay_directories(tuple(root for root, _ in statuses))
        plans = tuple(
            plan_project_install(root, name, source_root)
            for root, name in zip(roots, _REPO_NAMES, strict=True)
        )
        transaction_updates, expected_before = _capture_transaction_preconditions(
            plans, source_root
        )
        result = apply_transaction(
            transaction_updates,
            workspace / ".codex-routing-backups",
            replace=_preconditioned_replace(expected_before),
        )
        _require_unchanged_status(
            statuses, result.manifest_path, created,
            repository_roots=tuple(plan.repo_root for plan in plans if plan.ownership == "repository"),
        )
    except Exception:
        _remove_created_directories(created)
        raise

    return tuple(
        ProjectInstallPlan(
            plan.repo_root,
            plan.repo_name,
            plan.updates,
            applied=plan.ownership == "local",
            manifest_path=result.manifest_path if plan.ownership == "local" else None,
            ownership=plan.ownership,
        )
        for plan in plans
    )


def validate_project_overlay(
    repo_root: Path,
    repo_name: str,
    source_root: Path,
) -> ProjectValidationReport:
    """Validate exact overlay bytes, TOML, ignore behavior, and read-only status."""

    policy = _require_repo_policy(repo_name)
    root = require_exact_git_root(repo_root, repo_name)
    status_before = _git_status(root)
    templates = _project_templates(source_root, policy.instructions_template)
    ownership = _overlay_ownership(root)
    if ownership == "repository":
        valid = _validate_repository_routing(root)
        return ProjectValidationReport(
            root, repo_name, (), valid and _git_status(root) == status_before,
            ownership="repository",
        )
    ignored_candidates = (root / "AGENTS.md", root / ".codex")
    valid = True

    try:
        _require_codex_inventory(root)
    except RoutingConfigError:
        valid = False

    actual: dict[str, bytes | None] = {}
    for key, path in (
        ("instructions", root / "AGENTS.md"),
        ("config", root / ".codex/config.toml"),
        ("critical_reviewer", root / ".codex/agents/critical_reviewer.toml"),
    ):
        try:
            actual[key] = _read_optional_regular(path, "overlay target")
        except RoutingConfigError:
            actual[key] = None
            valid = False
    valid = valid and all(actual[key] == expected for key, expected in templates.items())

    for key in ("config", "critical_reviewer"):
        try:
            raw = actual[key]
            if raw is None:
                valid = False
            else:
                tomllib.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, tomllib.TOMLDecodeError):
            valid = False

    exclude = _git_path(root, "info/exclude")
    try:
        exclude_bytes = _read_optional_regular(exclude, "Git exclude file")
        valid = valid and exclude_bytes is not None and merge_managed_block(
            exclude_bytes, _EXCLUDE_BODY, _EXCLUDE_BEGIN, _EXCLUDE_END
        ) == exclude_bytes
    except RoutingConfigError:
        valid = False

    ignored = tuple(path for path in ignored_candidates if _is_ignored(root, path))
    valid = valid and ignored == ignored_candidates
    valid = valid and _git_status(root) == status_before
    return ProjectValidationReport(root, repo_name, ignored, valid)


def require_exact_git_root(repo_root: Path, expected_name: str) -> Path:
    """Require a non-linked directory that is exactly Git's reported worktree root."""

    try:
        path = Path(repo_root)
        _require_directory(path, "project target")
        resolved = path.resolve(strict=True)
    except (TypeError, ValueError, OSError) as exc:
        raise RoutingConfigError(
            "project target is not the expected exact Git root"
        ) from exc
    try:
        actual = _run_git(resolved, "rev-parse", "--show-toplevel").stdout.strip()
        actual_root = Path(actual).resolve(strict=True)
    except (RoutingConfigError, OSError, RuntimeError, ValueError) as exc:
        raise RoutingConfigError(
            "project target is not the expected exact Git root"
        ) from exc
    if actual_root != resolved or resolved.name != expected_name:
        raise RoutingConfigError("project target is not the expected exact Git root")
    return resolved


def _require_repo_policy(repo_name: str):
    if repo_name not in _REPO_NAMES or repo_name not in REPO_POLICIES:
        raise RoutingConfigError(f"not an approved EGS repository: {repo_name!r}")
    return REPO_POLICIES[repo_name]


def _project_templates(source_root: Path, instructions_path: str) -> dict[str, bytes]:
    relative_paths = {
        "instructions": instructions_path,
        "config": "projects/common-config.toml",
        "critical_reviewer": "projects/critical_reviewer.toml",
    }
    templates = {
        key: _load_approved_template(source_root, relative)
        for key, relative in relative_paths.items()
    }
    _assert_project_toml(templates["config"], templates["critical_reviewer"])
    return templates


def _load_approved_template(source_root: Path, relative_path: str) -> bytes:
    template = load_template(source_root, relative_path)
    if hashlib.sha256(template).hexdigest() != _PROJECT_TEMPLATE_DIGESTS[relative_path]:
        raise RoutingConfigError(
            f"template does not match approved template bytes: {relative_path}"
        )
    return template


def _assert_project_toml(config: bytes, reviewer: bytes) -> None:
    try:
        config_data = tomllib.loads(config.decode("utf-8"))
        reviewer_data = tomllib.loads(reviewer.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise RoutingConfigError("approved project template is invalid TOML") from exc
    agents = config_data.get("agents")
    policy = AGENT_POLICIES["critical_reviewer"]
    if (
        "model" in config_data
        or "model_reasoning_effort" in config_data
        or not isinstance(agents, dict)
        or agents.get("max_concurrent_threads_per_session") != 2
        or "default_subagent_model" in agents
        or "default_subagent_reasoning_effort" in agents
        or reviewer_data.get("name") != policy.name
        or reviewer_data.get("model") != policy.model
        or reviewer_data.get("model_reasoning_effort") != policy.effort
        or reviewer_data.get("sandbox_mode") != policy.sandbox_mode
    ):
        raise RoutingConfigError("project templates do not match approved policy")


def _overlay_ownership(root: Path) -> str:
    targets = {"AGENTS.md", ".codex/config.toml", ".codex/agents/critical_reviewer.toml"}
    tracked = set(_run_git(root, "ls-files", "--", "AGENTS.md", ".codex").stdout.splitlines())
    # A partially tracked overlay remains a conflict; never adopt it implicitly.
    return "repository" if targets <= tracked else "local"


def _validate_repository_routing(root: Path) -> bool:
    """Check machine-readable routing; repository owners maintain prose governance."""
    try:
        _require_directory(root / ".codex", ".codex")
        _require_directory(root / ".codex/agents", ".codex/agents")
        instructions = _read_optional_regular(root / "AGENTS.md", "repository instructions")
        config = _read_optional_regular(root / ".codex/config.toml", "repository config")
        reviewer = _read_optional_regular(root / ".codex/agents/critical_reviewer.toml", "repository reviewer")
        if not instructions or not instructions.decode("utf-8").strip() or not config or not reviewer:
            return False
        _assert_project_toml(config, reviewer)
        config_data = tomllib.loads(config.decode("utf-8"))
        reviewer_data = tomllib.loads(reviewer.decode("utf-8"))
        return (
            config_data["agents"].get("enabled", True) is True
            and config_data.get("features", {}).get("multi_agent", True) is not False
            and bool(reviewer_data.get("developer_instructions", "").strip())
        )
    except (RoutingConfigError, OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, AttributeError):
        return False


def _reject_tracked_targets(root: Path) -> None:
    tracked = _run_git(root, "ls-files", "--", "AGENTS.md", ".codex").stdout
    if tracked:
        paths = ", ".join(line for line in tracked.splitlines() if line)
        raise RoutingConfigError(f"tracked overlay target is refused: {paths}")


def _git_path(root: Path, relative: str) -> Path:
    raw = _run_git(root, "rev-parse", "--git-path", relative).stdout.strip()
    if not raw:
        raise RoutingConfigError(f"Git returned no path for {relative}")
    path = Path(raw)
    if not path.is_absolute():
        path = root / path
    try:
        return Path(os.path.abspath(os.fspath(path)))
    except (OSError, ValueError) as exc:
        raise RoutingConfigError(f"unable to resolve Git path for {relative}") from exc


def _git_status(root: Path) -> bytes:
    return _run_git_bytes(
        root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        "--",
        ".",
        ":(top,exclude)AGENTS.md",
        ":(top,exclude).codex/config.toml",
        ":(top,exclude).codex/agents/critical_reviewer.toml",
    )


def _is_ignored(root: Path, path: Path) -> bool:
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        return False
    try:
        result = subprocess.run(
            ["git", "-C", os.fspath(root), "check-ignore", "-q", "--", relative],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=_read_only_git_environment(),
        )
    except OSError as exc:
        raise RoutingConfigError(
            f"Git ignore check failed at {root}: {path}"
        ) from exc
    return result.returncode == 0


def _run_git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", os.fspath(root), *args],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=_read_only_git_environment(),
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RoutingConfigError(f"Git command failed at {root}") from exc


def _run_git_bytes(root: Path, *args: str) -> bytes:
    try:
        return subprocess.run(
            ["git", "-C", os.fspath(root), *args],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_read_only_git_environment(),
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RoutingConfigError(f"Git command failed at {root}") from exc


def _read_only_git_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    return environment


def _capture_transaction_preconditions(
    plans: tuple[ProjectInstallPlan, ...],
    source_root: Path,
) -> tuple[tuple[FileUpdate, ...], dict[Path, bytes | None]]:
    updates: list[FileUpdate] = []
    expected_before: dict[Path, bytes | None] = {}
    for plan in plans:
        if plan.ownership == "repository":
            continue
        _require_codex_inventory(plan.repo_root)
        policy = _require_repo_policy(plan.repo_name)
        templates = _project_templates(source_root, policy.instructions_template)
        overlay_updates = (
            FileUpdate(plan.repo_root / "AGENTS.md", templates["instructions"]),
            FileUpdate(plan.repo_root / ".codex/config.toml", templates["config"]),
            FileUpdate(
                plan.repo_root / ".codex/agents/critical_reviewer.toml",
                templates["critical_reviewer"],
            ),
        )
        for update in overlay_updates:
            before = _read_optional_regular(update.path, "overlay target")
            if before is not None and before != update.after:
                raise RoutingConfigError(
                    f"overlay target changed after project preflight: {update.path}"
                )
            expected_before[update.path] = before
            updates.append(update)

        exclude = _git_path(plan.repo_root, "info/exclude")
        exclude_before = _read_optional_regular(exclude, "Git exclude file")
        try:
            exclude_after = merge_managed_block(
                exclude_before or b"",
                _EXCLUDE_BODY,
                _EXCLUDE_BEGIN,
                _EXCLUDE_END,
            )
        except RoutingConfigError as exc:
            raise RoutingConfigError(
                f"Git exclude file changed after project preflight: {exclude}"
            ) from exc
        planned_exclude = next(
            (update.after for update in plan.updates if update.path == exclude),
            exclude_before,
        )
        if exclude_after != planned_exclude:
            raise RoutingConfigError(
                f"Git exclude file changed after project preflight: {exclude}"
            )
        expected_before[exclude] = exclude_before
        updates.append(FileUpdate(exclude, exclude_after))
    return tuple(updates), expected_before


def _preconditioned_replace(expected_before: dict[Path, bytes | None]):
    pending = dict(expected_before)

    def replace(source: Path, destination: Path) -> None:
        expected = pending.get(destination)
        if destination in pending:
            current = _read_optional_regular(destination, "transaction destination")
            if current != expected:
                raise RoutingConfigError(
                    f"transaction destination changed after project preflight: {destination}"
                )
            # Task 3 can re-enter this transaction-scoped callback for rollback
            # when os.replace published before raising. The initial
            # compare-before-replace guard is consumed before that call so the
            # rollback can restore the bytes captured by Task 3.
            pending.pop(destination)
        os.replace(source, destination)

    return replace


def _ensure_overlay_directories(
    roots: tuple[Path, ...],
) -> list[tuple[Path, tuple[int, int, int, int]]]:
    created: list[tuple[Path, tuple[int, int, int, int]]] = []
    try:
        for root in roots:
            for path, label in (
                (root / ".codex", ".codex"),
                (root / ".codex/agents", ".codex/agents"),
            ):
                if _require_optional_directory(path, label):
                    continue
                try:
                    path.mkdir()
                except OSError as exc:
                    raise RoutingConfigError(f"unable to create {label}: {path}") from exc
                created.append((path, _require_directory(path, label)))
    except Exception:
        _remove_created_directories(created)
        raise
    return created


def _require_codex_inventory(root: Path) -> None:
    config_directory = root / ".codex"
    if not _require_optional_directory(config_directory, ".codex"):
        return
    config_entries = _directory_entry_names(config_directory, ".codex")
    foreign_config = config_entries - {"config.toml", "agents"}
    if foreign_config:
        names = ", ".join(sorted(foreign_config))
        raise RoutingConfigError(f"foreign .codex entry is refused: {names}")

    agents_directory = config_directory / "agents"
    if not _require_optional_directory(agents_directory, ".codex/agents"):
        return
    agent_entries = _directory_entry_names(agents_directory, ".codex/agents")
    foreign_agents = agent_entries - {"critical_reviewer.toml"}
    if foreign_agents:
        names = ", ".join(sorted(foreign_agents))
        raise RoutingConfigError(f"foreign .codex entry is refused: agents/{names}")


def _directory_entry_names(path: Path, label: str) -> set[str]:
    try:
        with os.scandir(path) as entries:
            return {entry.name for entry in entries}
    except OSError as exc:
        raise RoutingConfigError(f"unable to inspect {label} inventory: {path}") from exc


def _require_unchanged_status(
    statuses: tuple[tuple[Path, bytes], ...],
    manifest_path: Path,
    created: list[tuple[Path, tuple[int, int, int, int]]],
    *,
    repository_roots: tuple[Path, ...] = (),
) -> None:
    try:
        changed = tuple(
            root
            for root, before in statuses
            if _git_status(root) != before
            or (
                root in repository_roots
                and (_overlay_ownership(root) != "repository" or not _validate_repository_routing(root))
            )
            or (
                root not in repository_roots
                and (
                    not _codex_inventory_is_approved(root)
                    or not all(
                        _is_ignored(root, path)
                        for path in (root / "AGENTS.md", root / ".codex")
                    )
                )
            )
        )
    except (OSError, RoutingConfigError) as status_exc:
        try:
            rollback_transaction(manifest_path)
        except RoutingConfigError as rollback_exc:
            raise RoutingConfigError(
                "Git status verification and project installation rollback failed"
            ) from rollback_exc
        _remove_created_directories(created)
        raise status_exc
    if not changed:
        return
    try:
        rollback_transaction(manifest_path)
    except RoutingConfigError as exc:
        raise RoutingConfigError(
            "Git status changed during project installation and rollback failed"
        ) from exc
    _remove_created_directories(created)
    names = ", ".join(path.name for path in changed)
    raise RoutingConfigError(f"Git status changed during project installation: {names}")


def _codex_inventory_is_approved(root: Path) -> bool:
    try:
        _require_codex_inventory(root)
    except RoutingConfigError:
        return False
    return True


def _require_directory_path(path: Path, label: str) -> Path:
    try:
        candidate = Path(os.path.abspath(os.fspath(path)))
    except (TypeError, ValueError) as exc:
        raise RoutingConfigError(f"{label} must be a filesystem path") from exc
    _require_directory(candidate, label)
    return candidate


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
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise RoutingConfigError(f"unable to read {label}: {path}") from exc
    try:
        opened = os.fstat(fd)
        _reject_link_or_reparse(path, opened)
        if _stat_identity(opened) != _stat_identity(result):
            raise RoutingConfigError(f"{label} changed during read: {path}")
        chunks: list[bytes] = []
        while chunk := os.read(fd, 1024 * 1024):
            chunks.append(chunk)
        return b"".join(chunks)
    except OSError as exc:
        raise RoutingConfigError(f"unable to read {label}: {path}") from exc
    finally:
        os.close(fd)


def _remove_created_directories(
    created: list[tuple[Path, tuple[int, int, int, int]]],
) -> None:
    for path, expected_state in reversed(created):
        try:
            current = _lstat(path)
        except OSError:
            continue
        if _stat_identity(current) != expected_state:
            continue
        try:
            path.rmdir()
        except OSError:
            continue


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
