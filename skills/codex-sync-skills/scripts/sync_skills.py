from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
import argparse
import json
import os
import re
import sys


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
class Action:
    selector: str
    source: Path
    destination: Path
    status: str
    detail: str


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
    if not root.is_dir():
        raise ValueError(
            f"missing {label} root: {root}; create it before retrying"
        )
    return root.resolve(strict=True)


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
            if child.name == ".system":
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

            resolved_child = child.resolve(strict=True)
            try:
                resolved_child.relative_to(source_root)
            except ValueError:
                issues.append(
                    f"REJECTED {selector}: source escapes approved root"
                )
                continue

            if not _has_readable_skill(child):
                issues.append(f"REJECTED {selector}: source has no readable SKILL.md")
                continue

            candidates[selector] = (child, destination_root / child.name)

        # Destination-only broken links otherwise disappear from source discovery.
        for destination in sorted(destination_root.iterdir(), key=lambda item: item.name):
            if destination.name == ".system" or not destination.is_symlink():
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
            matches_source = target.resolve(strict=False) == source.resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            # Python < 3.13 raises RuntimeError for cycles even with strict=False.
            return Action(
                selector,
                source,
                destination,
                "CONFLICT",
                f"link target cannot be resolved: {exc}",
            )
        if matches_source:
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
    return [
        _plan_action(selector, *candidates[selector])
        for selector in sorted(candidates)
    ]


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


def apply_actions(actions: Sequence[Action]) -> tuple[list[Action], bool]:
    results: list[Action] = []
    failed = False

    for action in actions:
        if action.status == "CREATE":
            try:
                if not _has_readable_skill(action.source):
                    raise OSError("source has no readable SKILL.md")
                action.destination.symlink_to(
                    action.source,
                    target_is_directory=True,
                )
                if not _has_readable_skill(action.destination):
                    raise OSError("created link has no readable SKILL.md")
            except OSError as exc:
                results.append(
                    Action(
                        action.selector,
                        action.source,
                        action.destination,
                        "CONFLICT",
                        f"link creation failed: {exc}",
                    )
                )
                failed = True
            else:
                results.append(
                    Action(
                        action.selector,
                        action.source,
                        action.destination,
                        "CREATED",
                        "link created",
                    )
                )
        else:
            results.append(action)
            if action.status == "CONFLICT":
                failed = True

    return results, failed


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
