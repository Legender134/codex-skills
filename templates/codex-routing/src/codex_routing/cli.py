"""Command-line interface for safe Codex routing management."""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from codex_routing.errors import RoutingConfigError
from codex_routing.global_install import (
    GlobalInstallPlan,
    GlobalValidationReport,
    install_global,
    plan_global_install,
    validate_global_install,
)
from codex_routing.managed_files import rollback_transaction
from codex_routing.project_install import (
    ProjectInstallPlan,
    ProjectValidationReport,
    install_egs_workspace,
    validate_project_overlay,
)
from codex_routing.spec import REPO_POLICIES
from codex_routing.validate import RollbackPlan, SourceValidationReport, plan_rollback, validate_source


_PLATFORMS = ("windows", "wsl")


def build_parser() -> argparse.ArgumentParser:
    """Build the public CLI parser without touching configuration files."""

    parser = argparse.ArgumentParser(
        prog="codex-routing",
        description="Plan, install, validate, and roll back approved Codex routing.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    check_source = commands.add_parser(
        "check-source", help="validate the approved routing source templates"
    )
    check_source.add_argument("--source-root", type=Path, required=True, metavar="PATH")

    _add_global_command(commands, "plan-global", "plan a global routing installation")
    _add_global_command(
        commands,
        "install-global",
        "install a global routing configuration",
        include_apply=True,
    )
    _add_workspace_command(
        commands,
        "install-egs",
        "install local EGS project overlays",
        include_apply=True,
    )
    _add_global_command(
        commands, "validate-global", "validate a global routing configuration"
    )
    _add_workspace_command(
        commands, "validate-egs", "validate local EGS project overlays"
    )

    rollback = commands.add_parser(
        "rollback", help="restore one transaction manifest"
    )
    rollback.add_argument("--manifest", type=Path, required=True, metavar="PATH")
    rollback.add_argument(
        "--apply", action="store_true", help="perform the rollback after parsing it"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and turn only expected routing errors into exit code 2."""

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return dispatch(args)
    except RoutingConfigError as exc:
        print(f"error: {one_line(str(exc))}", file=sys.stderr)
        return 2


def dispatch(args: argparse.Namespace) -> int:
    """Dispatch a parsed command while preserving unexpected exceptions."""

    if args.command == "check-source":
        _print_source_report(validate_source(args.source_root))
        return 0
    if args.command == "plan-global":
        _check_source(args.source_root)
        _print_global_plan(
            plan_global_install(args.codex_home, args.target, args.source_root),
            status="dry-run",
        )
        return 0
    if args.command == "install-global":
        _check_source(args.source_root)
        plan = install_global(
            args.codex_home,
            args.target,
            args.source_root,
            apply=args.apply,
        )
        _print_global_plan(plan, status="applied" if plan.applied else "dry-run")
        return 0
    if args.command == "install-egs":
        _check_source(args.source_root)
        plans = install_egs_workspace(
            args.workspace, args.source_root, apply=args.apply
        )
        _print_project_plans(plans, status="applied" if args.apply else "dry-run")
        return 0
    if args.command == "validate-global":
        _check_source(args.source_root)
        report = validate_global_install(
            args.codex_home, args.target, args.source_root
        )
        _print_global_validation(report)
        return 0 if report.valid else 1
    if args.command == "validate-egs":
        _check_source(args.source_root)
        reports = tuple(
            validate_project_overlay(
                args.workspace / name, name, args.source_root
            )
            for name in REPO_POLICIES
        )
        _print_project_validations(reports)
        return 0 if all(report.valid for report in reports) else 1
    if args.command == "rollback":
        plan = plan_rollback(args.manifest)
        if args.apply:
            restored = rollback_transaction(plan.manifest_path)
            _print_rollback(plan, status="applied", restored=restored)
        else:
            _print_rollback(plan, status="dry-run")
        return 0
    raise RuntimeError(f"unrecognized command: {args.command!r}")


def one_line(value: str) -> str:
    """Keep a domain error on exactly one predictable stderr line."""

    flattened = " ".join(value.splitlines()).strip()
    return flattened or "routing configuration error"


def _add_global_command(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
    name: str,
    help_text: str,
    *,
    include_apply: bool = False,
) -> None:
    parser = commands.add_parser(name, help=help_text)
    parser.add_argument("--target", choices=_PLATFORMS, required=True)
    parser.add_argument("--codex-home", type=Path, required=True, metavar="PATH")
    _add_source_root(parser)
    if include_apply:
        parser.add_argument(
            "--apply", action="store_true", help="perform the planned installation"
        )


def _add_workspace_command(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
    name: str,
    help_text: str,
    *,
    include_apply: bool = False,
) -> None:
    parser = commands.add_parser(name, help=help_text)
    parser.add_argument("--workspace", type=Path, required=True, metavar="PATH")
    _add_source_root(parser)
    if include_apply:
        parser.add_argument(
            "--apply", action="store_true", help="perform the planned installation"
        )


def _add_source_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path.cwd(),
        metavar="PATH",
        help="routing source tree (defaults to the current directory)",
    )


def _check_source(source_root: Path) -> None:
    validate_source(source_root)


def _print_source_report(report: SourceValidationReport) -> None:
    print(f"source valid=true root={_path_text(report.source_root)}")
    for relative_path, digest in report.template_digests:
        print(f"template={relative_path} sha256={digest}")


def _print_global_plan(plan: GlobalInstallPlan, *, status: str) -> None:
    print(
        f"{status} global target={plan.platform} "
        f"codex_home={_path_text(plan.codex_home)} updates={len(plan.updates)}"
    )
    _print_updates(plan.updates)
    if plan.manifest_path is not None:
        print(f"manifest={_path_text(plan.manifest_path)}")


def _print_project_plans(
    plans: tuple[ProjectInstallPlan, ...], *, status: str
) -> None:
    for plan in plans:
        print(
            f"{status} egs repo={plan.repo_name} "
            f"root={_path_text(plan.repo_root)} updates={len(plan.updates)} ownership={plan.ownership}"
        )
        _print_updates(plan.updates)
        if plan.manifest_path is not None:
            print(f"manifest={_path_text(plan.manifest_path)}")


def _print_updates(updates) -> None:
    for update in updates:
        digest = hashlib.sha256(update.after).hexdigest()
        print(f"path={_path_text(update.path)} sha256={digest}")


def _print_global_validation(report: GlobalValidationReport) -> None:
    print(f"global validation target={report.platform} valid={str(report.valid).lower()}")
    for agent_path in report.agent_files:
        print(f"agent_file={_path_text(agent_path)}")
    tables = ",".join(report.unrelated_table_names) or "none"
    print(f"unrelated_tables={tables}")


def _print_project_validations(
    reports: tuple[ProjectValidationReport, ...]
) -> None:
    for report in reports:
        ignored = ",".join(_path_text(path) for path in report.ignored_paths) or "none"
        print(
            f"egs validation repo={report.repo_name} valid={str(report.valid).lower()} "
            f"root={_path_text(report.repo_root)} ignored={ignored} ownership={report.ownership}"
        )


def _print_rollback(
    plan: RollbackPlan,
    *,
    status: str,
    restored: tuple[Path, ...] | None = None,
) -> None:
    paths = restored if restored is not None else plan.destinations
    print(
        f"{status} rollback manifest={_path_text(plan.manifest_path)} "
        f"files={len(paths)}"
    )
    for path in paths:
        print(f"path={_path_text(path)}")


def _path_text(path: Path) -> str:
    return one_line(os.fspath(path))
