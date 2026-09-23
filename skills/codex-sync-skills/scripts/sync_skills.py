from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import stat
import sys


_symlink = os.symlink
_GUARDED_LINK_CREATION = (
    os.symlink in os.supports_dir_fd
    and hasattr(os, "O_DIRECTORY")
    and hasattr(os, "O_NOFOLLOW")
)


SAFE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
SAFE_SELECTOR = re.compile(r"^(codex|agents)/[a-z0-9][a-z0-9-]{0,63}$")


@dataclass(frozen=True)
class Scope:
    name: str
    source: Path
    destination: Path
    allow_absent_source: bool = False


@dataclass(frozen=True)
class Roots:
    windows_codex: Path
    windows_agents: Path
    wsl_codex: Path
    wsl_agents: Path


@dataclass(frozen=True)
class SourceState:
    directory: Path
    directory_identity: tuple[int, int, int]
    skill_file: Path
    skill_identity: tuple[int, int, int, int, int, int]
    skill_digest: str


@dataclass(frozen=True)
class Action:
    selector: str
    source: Path
    destination: Path
    status: str
    detail: str
    source_root: Path | None = None
    source_root_state: tuple[int, int, int] | None = None
    destination_root_state: tuple[int, int, int] | None = None
    source_state: SourceState | None = None


def infer_default_roots(
    script_file: Path,
    wsl_home: Path | None = None,
) -> Roots:
    resolved_script = script_file.resolve(strict=True)
    windows_profile: Path | None = None

    for candidate in resolved_script.parents:
        if candidate.name != "skills" or candidate.parent.name not in {
            ".codex",
            ".agents",
        }:
            continue
        relative_script = resolved_script.relative_to(candidate)
        if relative_script.parts[0] != "codex-sync-skills":
            continue
        windows_profile = candidate.parent.parent
        break

    if windows_profile is None:
        raise ValueError(
            "cannot infer Windows profile from the installed script path; "
            "provide all root options explicitly"
        )

    resolved_wsl_home = wsl_home if wsl_home is not None else Path.home()
    return Roots(
        windows_profile / ".codex" / "skills",
        windows_profile / ".agents" / "skills",
        resolved_wsl_home / ".codex" / "skills",
        resolved_wsl_home / ".agents" / "skills",
    )


def _require_directory(root: Path, label: str) -> Path:
    _reject_system_path(root.absolute())
    if not root.is_dir():
        raise ValueError(
            f"missing {label} root: {root}; create it before retrying"
        )
    resolved = root.resolve(strict=True)
    _reject_system_path(resolved)
    return resolved


def _has_readable_skill(directory: Path) -> bool:
    skill_file = directory / "SKILL.md"
    try:
        if not skill_file.is_file():
            return False
        with skill_file.open("rb") as stream:
            stream.read(1)
    except OSError:
        return False
    return True


def _reject_system_path(path: Path) -> None:
    if any(part.casefold() == ".system" for part in path.parts):
        raise ValueError(f"path is inside excluded .system directory: {path}")


def _validate_source_location(source: Path, source_root: Path) -> tuple[Path, Path]:
    _reject_system_path(source_root)
    excluded_roots = tuple(
        child.resolve(strict=False) for child in source_root.iterdir()
        if child.name.casefold() == ".system"
    )
    resolved_paths = (source.resolve(strict=True), (source / "SKILL.md").resolve(strict=True))
    for resolved in resolved_paths:
        _reject_system_path(resolved)
        try:
            resolved.relative_to(source_root)
        except ValueError as exc:
            raise ValueError("source escapes approved root") from exc
        if any(resolved.is_relative_to(root) for root in excluded_roots):
            raise ValueError("source resolves into excluded .system directory")
    return resolved_paths


def discover_candidates(
    scopes: Sequence[Scope],
) -> tuple[dict[str, tuple[Path, Path]], list[str]]:
    candidates: dict[str, tuple[Path, Path]] = {}
    issues: list[str] = []

    for scope in sorted(scopes, key=lambda item: item.name):
        source_root = None
        if os.path.lexists(scope.source) or not scope.allow_absent_source:
            source_root = _require_directory(
                scope.source,
                f"{scope.name} Windows source",
            )
        if source_root is None and not os.path.lexists(scope.destination):
            continue
        destination_root = _require_directory(
            scope.destination,
            f"{scope.name} WSL destination",
        )

        children = source_root.iterdir() if source_root is not None else ()
        for child in sorted(children, key=lambda item: item.name):
            if child.name.casefold() == ".system":
                continue
            try:
                if not child.is_dir() or not (child / "SKILL.md").is_file():
                    continue
            except OSError as exc:
                issues.append(
                    f"REJECTED {scope.name}/{child.name}: cannot inspect source skill: {exc}"
                )
                continue

            selector = f"{scope.name}/{child.name}"
            if not SAFE_NAME.fullmatch(child.name):
                issues.append(f"REJECTED {selector}: unsafe skill name")
                continue

            try:
                _validate_source_location(child, source_root)
            except (OSError, RuntimeError, ValueError) as exc:
                issues.append(f"REJECTED {selector}: {exc}")
                continue

            if not _has_readable_skill(child):
                issues.append(f"REJECTED {selector}: source has no readable SKILL.md")
                continue

            candidates[selector] = (child, destination_root / child.name)

        # Destination-only broken links otherwise disappear from source discovery.
        for destination in sorted(destination_root.iterdir(), key=lambda item: item.name):
            if destination.name.casefold() == ".system" or not destination.is_symlink():
                continue
            if not _has_readable_skill(destination):
                issues.append(
                    f"BROKEN_LINK {scope.name}/{destination.name}: "
                    f"destination has no readable SKILL.md: {destination}"
                )

    return candidates, issues


def _plan_action(selector: str, source: Path, destination: Path) -> Action:
    if not os.path.lexists(destination):
        return Action(
            selector,
            source,
            destination,
            "CREATE",
            "destination is missing",
        )

    if destination.is_symlink():
        raw_target = Path(os.readlink(destination))
        target = raw_target if raw_target.is_absolute() else destination.parent / raw_target
        try:
            _reject_system_path(target.absolute())
            matches_source = target.resolve(strict=False) == source.resolve(strict=False)
        except (OSError, RuntimeError, ValueError) as exc:
            # Python < 3.13 raises RuntimeError for cycles even with strict=False.
            return Action(
                selector,
                source,
                destination,
                "CONFLICT",
                f"link target cannot be resolved: {exc}",
            )
        if matches_source:
            expected_target = Path(os.path.abspath(source))
            if not raw_target.is_absolute():
                expected_target = Path(os.path.relpath(expected_target, destination.parent))
            if raw_target != expected_target:
                return Action(
                    selector, source, destination, "CONFLICT",
                    "link uses an unapproved source alias",
                )
            return Action(
                selector,
                source,
                destination,
                "UNCHANGED",
                "link already targets source",
            )
        return Action(
            selector,
            source,
            destination,
            "CONFLICT",
            "link targets a different or missing source",
        )

    return Action(
        selector,
        source,
        destination,
        "CONFLICT",
        "destination is an existing file or directory",
    )


def plan_actions(
    candidates: Mapping[str, tuple[Path, Path]],
) -> list[Action]:
    actions: list[Action] = []
    for selector in sorted(candidates):
        source, destination = candidates[selector]
        try:
            action = _plan_action(selector, source, destination)
            actions.append(replace(
                action,
                source_root=source.parent,
                source_root_state=_directory_identity(source.parent),
                destination_root_state=_directory_identity(destination.parent),
                source_state=_capture_source_state(source, source.parent),
            ))
        except (OSError, RuntimeError, ValueError) as exc:
            actions.append(Action(selector, source, destination, "CONFLICT", str(exc)))
    return actions


def _directory_identity(path: Path) -> tuple[int, int, int]:
    _reject_system_path(path.absolute())
    _reject_system_path(path.resolve(strict=True))
    state = path.lstat()
    if not stat.S_ISDIR(state.st_mode) or getattr(state, "st_file_attributes", 0) & 0x400:
        raise ValueError(f"reviewed root is not a regular directory: {path}")
    return state.st_dev, state.st_ino, state.st_mode


def _skill_identity(path: Path) -> tuple[int, int, int, int, int, int]:
    state = path.lstat()
    if not stat.S_ISREG(state.st_mode) or getattr(state, "st_file_attributes", 0) & 0x400:
        raise ValueError(f"SKILL.md is not a regular file: {path}")
    return (state.st_dev, state.st_ino, state.st_mode, state.st_size,
            state.st_mtime_ns, state.st_ctime_ns)


def _capture_source_state(source: Path, source_root: Path) -> SourceState:
    directory, skill_file = _validate_source_location(source, source_root)
    directory_state = _directory_identity(directory)
    skill_state = _skill_identity(skill_file)
    digest = hashlib.sha256(skill_file.read_bytes()).hexdigest()
    if (
        _directory_identity(directory) != directory_state
        or _skill_identity(skill_file) != skill_state
        or source.resolve(strict=True) != directory
        or (source / "SKILL.md").resolve(strict=True) != skill_file
    ):
        raise ValueError("source changed while capturing its planned state")
    return SourceState(directory, directory_state, skill_file, skill_state, digest)


def _revalidate_action(action: Action) -> None:
    if action.source_root is None or action.source_root_state is None or action.destination_root_state is None or action.source_state is None:
        raise ValueError("action has no reviewed directory identities; preview again")
    if _directory_identity(action.source_root) != action.source_root_state:
        raise ValueError("Windows source root changed after planning")
    if _directory_identity(action.destination.parent) != action.destination_root_state:
        raise ValueError("WSL destination root changed after planning")
    if _capture_source_state(action.source, action.source_root) != action.source_state:
        raise ValueError("selected source or SKILL.md changed after planning; preview again")


def _revalidate_link(action: Action) -> None:
    _revalidate_action(action)
    current = _plan_action(action.selector, action.source, action.destination)
    if current.status != "UNCHANGED" or not _has_readable_skill(action.destination):
        raise ValueError("destination no longer links to the expected readable source")


def select_actions(
    actions: Sequence[Action],
    selectors: Sequence[str],
    select_all: bool,
) -> list[Action]:
    if select_all and selectors:
        raise ValueError("--all cannot be combined with --skill")

    by_selector = {action.selector: action for action in actions}
    if select_all or not selectors:
        return [by_selector[key] for key in sorted(by_selector)]

    selected: dict[str, Action] = {}
    for selector in selectors:
        if not SAFE_SELECTOR.fullmatch(selector):
            raise ValueError(f"invalid selector: {selector}")
        if selector not in by_selector:
            raise ValueError(f"unknown selector: {selector}")
        selected[selector] = by_selector[selector]
    return [selected[key] for key in sorted(selected)]


def _create_link(action: Action) -> None:
    if not _GUARDED_LINK_CREATION:
        raise ValueError("guarded link creation requires directory-relative symlink support; run from WSL")
    directory_fd = os.open(
        action.destination.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
    )
    try:
        state = os.fstat(directory_fd)
        if (state.st_dev, state.st_ino, state.st_mode) != action.destination_root_state:
            raise ValueError("WSL destination root changed before link creation")
        _revalidate_action(action)
        _symlink(
            action.source, action.destination.name,
            target_is_directory=True, dir_fd=directory_fd,
        )
    finally:
        os.close(directory_fd)


def apply_actions(actions: Sequence[Action]) -> tuple[list[Action], bool]:
    results: list[Action] = []
    for action in actions:
        if action.status not in {"CREATE", "UNCHANGED"}:
            results.append(action)
            continue
        try:
            _revalidate_action(action)
            current = _plan_action(action.selector, action.source, action.destination)
            if current.status == "UNCHANGED":
                _revalidate_link(action)
                results.append(replace(action, status="UNCHANGED", detail=current.detail))
            elif action.status == "CREATE" and current.status == "CREATE":
                _create_link(action)
                _revalidate_link(action)
                results.append(replace(action, status="CREATED", detail="link created"))
            else:
                raise ValueError("destination changed after planning; preview again")
        except (OSError, RuntimeError, ValueError) as exc:
            results.append(replace(action, status="CONFLICT", detail=f"link validation or creation failed: {exc}"))

    # A later action can expose changes to an earlier result. Report the state
    # observed at closeout without deleting or repairing any conflicting link.
    for index, action in enumerate(results):
        if action.status in {"CREATED", "UNCHANGED"}:
            try:
                _revalidate_link(action)
            except (OSError, RuntimeError, ValueError) as exc:
                results[index] = replace(action, status="CONFLICT", detail=f"final link validation failed: {exc}")
    return results, any(action.status == "CONFLICT" for action in results)


class UsageParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")


def _parser() -> argparse.ArgumentParser:
    parser = UsageParser(
        description="Preview or create reviewed WSL links to Windows Codex Skills.",
        epilog="Exit codes: 0=safe result, 1=usage/environment error, "
        "2=conflict or rejected candidate.",
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit structured actions and issues",
    )
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--skill", action="append", default=[])
    selection.add_argument("--all", action="store_true")
    parser.add_argument(
        "--windows-codex-root",
        type=Path,
    )
    parser.add_argument(
        "--windows-agents-root",
        type=Path,
    )
    parser.add_argument(
        "--wsl-codex-root",
        type=Path,
    )
    parser.add_argument(
        "--wsl-agents-root",
        type=Path,
    )
    return parser


def _is_wsl_environment() -> bool:
    return bool(
        os.environ.get("WSL_DISTRO_NAME")
        or os.environ.get("WSL_INTEROP")
    )


def _uses_inferred_roots(args: argparse.Namespace) -> bool:
    return any(
        root is None
        for root in (
            args.windows_codex_root,
            args.windows_agents_root,
            args.wsl_codex_root,
            args.wsl_agents_root,
        )
    )


def _resolve_roots(
    args: argparse.Namespace,
    script_file: Path,
    wsl_home: Path | None,
) -> Roots:
    supplied = (
        args.windows_codex_root,
        args.windows_agents_root,
        args.wsl_codex_root,
        args.wsl_agents_root,
    )
    if all(root is not None for root in supplied):
        return Roots(*supplied)

    defaults = infer_default_roots(script_file, wsl_home)
    return Roots(
        args.windows_codex_root or defaults.windows_codex,
        args.windows_agents_root or defaults.windows_agents,
        args.wsl_codex_root or defaults.wsl_codex,
        args.wsl_agents_root or defaults.wsl_agents,
    )


def _print_results(
    actions: Sequence[Action],
    issues: Sequence[str],
    json_output: bool,
) -> None:
    if json_output:
        print(
            json.dumps(
                {
                    "actions": [
                        {
                            "selector": action.selector,
                            "source": str(action.source),
                            "destination": str(action.destination),
                            "status": action.status,
                            "detail": action.detail,
                        }
                        for action in actions
                    ],
                    "issues": list(issues),
                },
                indent=2,
            )
        )
        return

    for action in actions:
        print(
            action.status,
            action.selector,
            action.source,
            action.destination,
            action.detail,
            sep="\t",
        )
    for issue in issues:
        print(issue)


def main(
    argv: Sequence[str] | None = None,
    *,
    script_file: Path | None = None,
    wsl_home: Path | None = None,
) -> int:
    args = _parser().parse_args(argv)
    if args.apply and not (args.skill or args.all):
        print("--apply requires --skill or --all", file=sys.stderr)
        return 1
    if _uses_inferred_roots(args) and not _is_wsl_environment():
        print(
            "inferred-root mode must run inside WSL; provide all four "
            "root options for an explicit non-WSL layout",
            file=sys.stderr,
        )
        return 1

    try:
        selected_scopes = set()
        for selector in args.skill:
            if not SAFE_SELECTOR.fullmatch(selector):
                raise ValueError(f"invalid selector: {selector}")
            selected_scopes.add(selector.split("/", 1)[0])
        roots = _resolve_roots(
            args,
            script_file or Path(__file__),
            wsl_home,
        )
        scopes = (
            Scope(
                "codex", roots.windows_codex, roots.wsl_codex,
                allow_absent_source=args.windows_codex_root is None,
            ),
            Scope(
                "agents", roots.windows_agents, roots.wsl_agents,
                allow_absent_source=args.windows_agents_root is None,
            ),
        )
        if selected_scopes:
            scopes = tuple(scope for scope in scopes if scope.name in selected_scopes)
        for scope in scopes:
            if getattr(args, f"wsl_{scope.name}_root") is not None:
                _require_directory(scope.destination, f"{scope.name} WSL destination")
        candidates, issues = discover_candidates(scopes)
        planned = plan_actions(candidates)
        selected = select_actions(planned, args.skill, args.all)
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.apply:
        results, failed = apply_actions(selected)
    else:
        results = selected
        failed = any(action.status == "CONFLICT" for action in results)

    _print_results(results, issues, args.json)
    return 2 if failed or issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
