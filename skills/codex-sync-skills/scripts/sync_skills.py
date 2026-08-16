from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
import argparse
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


def _require_directory(root: Path) -> Path:
    if not root.is_dir():
        raise ValueError(f"missing root: {root}")
    return root.resolve(strict=True)


def discover_candidates(
    scopes: Sequence[Scope],
) -> tuple[dict[str, tuple[Path, Path]], list[str]]:
    candidates: dict[str, tuple[Path, Path]] = {}
    issues: list[str] = []

    for scope in sorted(scopes, key=lambda item: item.name):
        if not os.path.lexists(scope.source) and not os.path.lexists(
            scope.destination
        ):
            continue
        source_root = _require_directory(scope.source)
        _require_directory(scope.destination)

        for child in sorted(scope.source.iterdir(), key=lambda item: item.name):
            if child.name == ".system":
                continue
            if not child.is_dir() or not (child / "SKILL.md").is_file():
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

            candidates[selector] = (child, scope.destination / child.name)

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
        if target.resolve(strict=False) == source.resolve(strict=False):
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
                action.destination.symlink_to(
                    action.source,
                    target_is_directory=True,
                )
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
                        "UNCHANGED",
                        "link created",
                    )
                )
        else:
            results.append(action)
            if action.status == "CONFLICT":
                failed = True

    return results, failed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preview or create reviewed WSL links to Windows Codex Skills."
    )
    parser.add_argument("--apply", action="store_true")
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


def _print_actions(actions: Sequence[Action]) -> None:
    for action in actions:
        print(
            action.status,
            action.selector,
            action.destination,
            action.detail,
            sep="\t",
        )


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

    try:
        roots = _resolve_roots(
            args,
            script_file or Path(__file__),
            wsl_home,
        )
        scopes = (
            Scope("codex", roots.windows_codex, roots.wsl_codex),
            Scope("agents", roots.windows_agents, roots.wsl_agents),
        )
        candidates, issues = discover_candidates(scopes)
        planned = plan_actions(candidates)
        selected = select_actions(planned, args.skill, args.all)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.apply:
        results, failed = apply_actions(selected)
    else:
        results = selected
        failed = any(action.status == "CONFLICT" for action in results)

    _print_actions(results)
    for issue in issues:
        print(issue)
    return 2 if failed or issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
