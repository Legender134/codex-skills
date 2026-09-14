import os
import shutil
import stat
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import codex_routing.managed_files as managed_files
from codex_routing.errors import RoutingConfigError
from codex_routing.project_install import (
    install_egs_workspace,
    install_project_overlay,
    plan_project_install,
    validate_project_overlay,
)


SOURCE_ROOT = Path(__file__).resolve().parents[1]
REPO_NAMES = ("preprocess-cli", "3dgs-gen", "egs-main")
EXCLUDE_BLOCK = (
    b"# BEGIN CODEX ROUTING\n"
    b"/.codex/\n"
    b"/AGENTS.md\n"
    b"# END CODEX ROUTING\n"
)


def git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True,
    )


def init_repo(parent: Path, name: str) -> Path:
    repo = parent / name
    repo.mkdir()
    git("init", "-b", "main", str(repo))
    (repo / "tracked.txt").write_bytes(b"tracked\n")
    git("add", "tracked.txt", cwd=repo)
    git("-c", "user.name=test", "-c", "user.email=test@example.invalid",
        "commit", "-m", "base", cwd=repo)
    return repo


def exclude_path(repo: Path) -> Path:
    result = git(
        "rev-parse", "--path-format=absolute", "--git-path", "info/exclude",
        cwd=repo,
    )
    return Path(result.stdout.strip())


def index_path(repo: Path) -> Path:
    result = git(
        "rev-parse", "--path-format=absolute", "--git-path", "index", cwd=repo
    )
    return Path(result.stdout.strip())


def read_only_status(repo: Path) -> str:
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    return subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain=v1", "-z",
         "--untracked-files=all"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    ).stdout


def stale_index_snapshot(repo: Path) -> tuple[bytes, int]:
    index = index_path(repo)
    future = index.stat().st_mtime_ns + 5_000_000_000
    os.utime(repo / "tracked.txt", ns=(future, future))
    return index.read_bytes(), index.stat().st_mtime_ns


def working_tree_snapshot(repo: Path) -> tuple[tuple[str, str | bytes], ...]:
    snapshot: list[tuple[str, str | bytes]] = []
    for path in sorted(repo.rglob("*")):
        relative = path.relative_to(repo)
        if relative.parts[0] == ".git":
            continue
        if path.is_dir():
            snapshot.append((relative.as_posix(), "directory"))
        else:
            snapshot.append((relative.as_posix(), path.read_bytes()))
    return tuple(snapshot)


class ProjectInstallTests(unittest.TestCase):
    def test_dry_run_has_exact_updates_and_zero_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = init_repo(Path(raw), "preprocess-cli")
            exclude = exclude_path(repo)
            exclude_before = exclude.read_bytes()
            before = tuple(sorted(path.relative_to(repo) for path in repo.rglob("*")))

            plan = install_project_overlay(repo, "preprocess-cli", SOURCE_ROOT)

            self.assertFalse(plan.applied)
            self.assertIsNone(plan.manifest_path)
            self.assertEqual(plan.repo_root, repo.resolve())
            self.assertEqual(plan.repo_name, "preprocess-cli")
            self.assertEqual(
                tuple(update.path for update in plan.updates),
                (repo / "AGENTS.md", repo / ".codex/config.toml",
                 repo / ".codex/agents/critical_reviewer.toml", exclude),
            )
            self.assertEqual(
                tuple(sorted(path.relative_to(repo) for path in repo.rglob("*"))),
                before,
            )
            self.assertEqual(exclude.read_bytes(), exclude_before)

    def test_single_dry_run_does_not_refresh_stale_git_index(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = init_repo(Path(raw), "preprocess-cli")
            index = index_path(repo)
            index_before = stale_index_snapshot(repo)
            tree_before = working_tree_snapshot(repo)
            exclude_before = exclude_path(repo).read_bytes()
            status_before = read_only_status(repo)

            plan = install_project_overlay(repo, "preprocess-cli", SOURCE_ROOT)

            self.assertFalse(plan.applied)
            self.assertEqual((index.read_bytes(), index.stat().st_mtime_ns), index_before)
            self.assertEqual(working_tree_snapshot(repo), tree_before)
            self.assertEqual(exclude_path(repo).read_bytes(), exclude_before)
            self.assertEqual(read_only_status(repo), status_before)

    def test_workspace_dry_run_does_not_refresh_any_stale_git_index(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            repos = {name: init_repo(workspace, name) for name in REPO_NAMES}
            indexes = {name: index_path(repo) for name, repo in repos.items()}
            index_before = {
                name: stale_index_snapshot(repo) for name, repo in repos.items()
            }
            trees_before = {
                name: working_tree_snapshot(repo) for name, repo in repos.items()
            }
            excludes_before = {
                name: exclude_path(repo).read_bytes() for name, repo in repos.items()
            }
            statuses_before = {
                name: read_only_status(repo) for name, repo in repos.items()
            }

            plans = install_egs_workspace(workspace, SOURCE_ROOT)

            self.assertEqual(tuple(plan.repo_name for plan in plans), REPO_NAMES)
            for name, repo in repos.items():
                self.assertEqual(
                    (indexes[name].read_bytes(), indexes[name].stat().st_mtime_ns),
                    index_before[name],
                )
                self.assertEqual(working_tree_snapshot(repo), trees_before[name])
                self.assertEqual(exclude_path(repo).read_bytes(), excludes_before[name])
                self.assertEqual(read_only_status(repo), statuses_before[name])

    def test_install_is_exact_local_and_preserves_dirty_business_status(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = init_repo(Path(raw), "preprocess-cli")
            (repo / "tracked.txt").write_bytes(b"business edit\n")
            (repo / "business.tmp").write_bytes(b"business untracked\n")
            status_before = git("status", "--porcelain", cwd=repo).stdout

            result = install_project_overlay(repo, "preprocess-cli", SOURCE_ROOT,
                                             apply=True)
            report = validate_project_overlay(repo, "preprocess-cli", SOURCE_ROOT)

            self.assertTrue(result.applied)
            self.assertIsNotNone(result.manifest_path)
            self.assertEqual(git("status", "--porcelain", cwd=repo).stdout,
                             status_before)
            expected = {
                "AGENTS.md": "preprocess-cli-AGENTS.md",
                ".codex/config.toml": "common-config.toml",
                ".codex/agents/critical_reviewer.toml": "critical_reviewer.toml",
            }
            for destination, template in expected.items():
                self.assertEqual(
                    (repo / destination).read_bytes(),
                    (SOURCE_ROOT / "templates/projects" / template).read_bytes(),
                )
            config = tomllib.loads((repo / ".codex/config.toml").read_text())
            reviewer = tomllib.loads(
                (repo / ".codex/agents/critical_reviewer.toml").read_text()
            )
            self.assertEqual(
                (config.get("model"), config.get("model_reasoning_effort"),
                 config["agents"]["max_concurrent_threads_per_session"],
                 config["agents"].get("default_subagent_model"),
                 config["agents"].get("default_subagent_reasoning_effort")),
                (None, None, 2, None, None),
            )
            self.assertEqual(
                (reviewer["name"], reviewer["model"],
                 reviewer["model_reasoning_effort"], reviewer["sandbox_mode"]),
                ("critical_reviewer", "gpt-6-astra", "high", "read-only"),
            )
            self.assertTrue(report.valid)
            self.assertEqual(report.ignored_paths,
                             (repo / "AGENTS.md", repo / ".codex"))

    def test_each_repository_receives_exact_instruction_template(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            for repo_name in REPO_NAMES:
                repo = init_repo(root, repo_name)
                install_project_overlay(repo, repo_name, SOURCE_ROOT, apply=True)
                self.assertEqual(
                    (repo / "AGENTS.md").read_bytes(),
                    (SOURCE_ROOT / f"templates/projects/{repo_name}-AGENTS.md").read_bytes(),
                )
                self.assertTrue(
                    validate_project_overlay(repo, repo_name, SOURCE_ROOT).valid
                )

    def test_rejects_wrong_name_non_git_nested_and_unapproved(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            repo = init_repo(root, "preprocess-cli")
            nested = repo / "egs-main"
            nested.mkdir()
            non_git = root / "egs-main"
            non_git.mkdir()
            for target, name in ((repo, "egs-main"), (nested, "egs-main"),
                                 (non_git, "egs-main")):
                with self.subTest(target=target):
                    with self.assertRaisesRegex(RoutingConfigError, "exact Git root"):
                        plan_project_install(target, name, SOURCE_ROOT)
            other = init_repo(root, "other")
            with self.assertRaisesRegex(RoutingConfigError, "approved EGS repository"):
                plan_project_install(other, "other", SOURCE_ROOT)

    def test_rejects_tracked_overlay_targets_without_writes(self) -> None:
        for tracked_path in ("AGENTS.md", ".codex/config.toml"):
            with self.subTest(tracked_path=tracked_path), tempfile.TemporaryDirectory() as raw:
                repo = init_repo(Path(raw), "preprocess-cli")
                target = repo / tracked_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"tracked overlay target\n")
                git("add", tracked_path, cwd=repo)
                git("-c", "user.name=test", "-c", "user.email=test@example.invalid",
                    "commit", "-m", "tracked target", cwd=repo)
                exclude_before = exclude_path(repo).read_bytes()
                with self.assertRaisesRegex(RoutingConfigError, "tracked overlay target"):
                    install_project_overlay(repo, "preprocess-cli", SOURCE_ROOT,
                                            apply=True)
                self.assertEqual(target.read_bytes(), b"tracked overlay target\n")
                self.assertEqual(exclude_path(repo).read_bytes(), exclude_before)

    def test_rejects_foreign_untracked_targets_without_writes(self) -> None:
        targets = ("AGENTS.md", ".codex/config.toml",
                   ".codex/agents/critical_reviewer.toml")
        for relative in targets:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as raw:
                repo = init_repo(Path(raw), "preprocess-cli")
                target = repo / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"foreign local bytes\n")
                exclude_before = exclude_path(repo).read_bytes()
                with self.assertRaisesRegex(RoutingConfigError,
                                            "foreign untracked target"):
                    install_project_overlay(repo, "preprocess-cli", SOURCE_ROOT,
                                            apply=True)
                self.assertEqual(target.read_bytes(), b"foreign local bytes\n")
                self.assertEqual(exclude_path(repo).read_bytes(), exclude_before)

    def test_install_rejects_foreign_codex_inventory_without_mutation(self) -> None:
        foreign_layouts = (
            (".codex/foreign-local.txt", b"foreign file\n"),
            (".codex/foreign-dir/nested.txt", b"foreign nested file\n"),
            (".codex/agents/foreign-agent.toml", b"foreign agent\n"),
        )
        for relative, payload in foreign_layouts:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as raw:
                repo = init_repo(Path(raw), "preprocess-cli")
                foreign = repo / relative
                foreign.parent.mkdir(parents=True, exist_ok=True)
                foreign.write_bytes(payload)
                before = working_tree_snapshot(repo)
                exclude_before = exclude_path(repo).read_bytes()
                status_before = git(
                    "status", "--porcelain=v1", "-z", "--untracked-files=all",
                    cwd=repo,
                ).stdout

                with self.assertRaisesRegex(RoutingConfigError,
                                            "foreign .codex entry"):
                    install_project_overlay(repo, "preprocess-cli", SOURCE_ROOT,
                                            apply=True)

                self.assertEqual(working_tree_snapshot(repo), before)
                self.assertEqual(exclude_path(repo).read_bytes(), exclude_before)
                self.assertEqual(
                    git("status", "--porcelain=v1", "-z",
                        "--untracked-files=all", cwd=repo).stdout,
                    status_before,
                )

    def test_validation_rejects_foreign_codex_inventory_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = init_repo(Path(raw), "preprocess-cli")
            install_project_overlay(repo, "preprocess-cli", SOURCE_ROOT, apply=True)
            foreign_file = repo / ".codex/foreign-local.txt"
            foreign_file.write_bytes(b"foreign file\n")
            foreign_directory = repo / ".codex/foreign-dir"
            foreign_directory.mkdir()
            (foreign_directory / "nested.txt").write_bytes(b"nested\n")
            before = working_tree_snapshot(repo)
            exclude_before = exclude_path(repo).read_bytes()
            status_before = git(
                "status", "--porcelain=v1", "-z", "--untracked-files=all",
                cwd=repo,
            ).stdout

            report = validate_project_overlay(repo, "preprocess-cli", SOURCE_ROOT)

            self.assertFalse(report.valid)
            self.assertEqual(working_tree_snapshot(repo), before)
            self.assertEqual(exclude_path(repo).read_bytes(), exclude_before)
            self.assertEqual(
                git("status", "--porcelain=v1", "-z", "--untracked-files=all",
                    cwd=repo).stdout,
                status_before,
            )

    def test_identical_untracked_targets_are_accepted_and_become_local(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = init_repo(Path(raw), "preprocess-cli")
            (repo / ".codex/agents").mkdir(parents=True)
            copies = {
                repo / "AGENTS.md": "preprocess-cli-AGENTS.md",
                repo / ".codex/config.toml": "common-config.toml",
                repo / ".codex/agents/critical_reviewer.toml": "critical_reviewer.toml",
            }
            for destination, template in copies.items():
                destination.write_bytes(
                    (SOURCE_ROOT / "templates/projects" / template).read_bytes()
                )
            self.assertIn("?? .codex/", git("status", "--porcelain", cwd=repo).stdout)
            plan = install_project_overlay(
                repo, "preprocess-cli", SOURCE_ROOT, apply=True
            )
            self.assertEqual(tuple(update.path for update in plan.updates),
                             (exclude_path(repo),))
            self.assertEqual(git("status", "--porcelain", cwd=repo).stdout, "")

    def test_rejects_symlink_directory_and_reparse_targets(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            repo = init_repo(root, "preprocess-cli")
            foreign = root / "foreign"
            foreign.write_bytes(b"foreign\n")
            (repo / "AGENTS.md").symlink_to(foreign)
            with self.assertRaisesRegex(RoutingConfigError, "symlink|reparse"):
                plan_project_install(repo, "preprocess-cli", SOURCE_ROOT)
            self.assertEqual(foreign.read_bytes(), b"foreign\n")

            shutil.rmtree(repo)
            repo = init_repo(root, "preprocess-cli")
            (repo / "AGENTS.md").mkdir()
            with self.assertRaisesRegex(RoutingConfigError, "regular file"):
                plan_project_install(repo, "preprocess-cli", SOURCE_ROOT)

            shutil.rmtree(repo)
            repo = init_repo(root, "preprocess-cli")
            target = repo / "AGENTS.md"
            target.write_bytes(
                (SOURCE_ROOT / "templates/projects/preprocess-cli-AGENTS.md").read_bytes()
            )
            real_lstat = os.lstat
            original = real_lstat(target)
            flagged = SimpleNamespace(
                st_mode=original.st_mode, st_dev=original.st_dev,
                st_ino=original.st_ino,
                st_file_attributes=getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400),
            )
            with mock.patch(
                "codex_routing.project_install._lstat",
                side_effect=lambda path: flagged if Path(path) == target else real_lstat(path),
            ):
                with self.assertRaisesRegex(RoutingConfigError, "symlink|reparse"):
                    plan_project_install(repo, "preprocess-cli", SOURCE_ROOT)

    def test_rejects_symlinked_git_exclude_without_touching_target(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            repo = init_repo(root, "preprocess-cli")
            exclude = exclude_path(repo)
            foreign = root / "foreign-exclude"
            foreign.write_bytes(b"foreign\n")
            exclude.unlink()
            exclude.symlink_to(foreign)
            with self.assertRaisesRegex(RoutingConfigError, "symlink|reparse"):
                plan_project_install(repo, "preprocess-cli", SOURCE_ROOT)
            self.assertEqual(foreign.read_bytes(), b"foreign\n")

    def test_exclude_block_preserves_foreign_bytes_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = init_repo(Path(raw), "preprocess-cli")
            exclude = exclude_path(repo)
            foreign = b"# foreign rule\n/build/\n"
            exclude.write_bytes(foreign)
            install_project_overlay(repo, "preprocess-cli", SOURCE_ROOT, apply=True)
            self.assertEqual(exclude.read_bytes(), foreign + b"\n" + EXCLUDE_BLOCK)
            reinstall = install_project_overlay(repo, "preprocess-cli", SOURCE_ROOT,
                                                apply=True)
            self.assertTrue(reinstall.applied)
            self.assertEqual(reinstall.updates, ())
            self.assertEqual(exclude.read_bytes(), foreign + b"\n" + EXCLUDE_BLOCK)

    def test_linked_worktree_uses_git_reported_exclude_path(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            primary = init_repo(root, "seed")
            linked = root / "preprocess-cli"
            git("worktree", "add", "-b", "linked", str(linked), cwd=primary)
            primary_exclude = exclude_path(primary)
            linked_exclude = exclude_path(linked)
            linked_before = linked_exclude.read_bytes()
            primary_before = primary_exclude.read_bytes()
            plan = install_project_overlay(linked, "preprocess-cli", SOURCE_ROOT,
                                           apply=True)
            self.assertIn(linked_exclude,
                          tuple(update.path for update in plan.updates))
            expected = linked_before.rstrip(b"\r\n") + b"\n\n" + EXCLUDE_BLOCK
            self.assertEqual(linked_exclude.read_bytes(), expected)
            if linked_exclude != primary_exclude:
                self.assertEqual(primary_exclude.read_bytes(), primary_before)
            self.assertEqual(git("status", "--porcelain", cwd=linked).stdout, "")

    def test_modified_caller_templates_are_rejected_before_writes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            repo = init_repo(root, "preprocess-cli")
            source = root / "source"
            shutil.copytree(SOURCE_ROOT / "templates", source / "templates")
            (source / "templates/projects/common-config.toml").write_bytes(
                b'model = "caller-controlled"\n'
            )
            exclude_before = exclude_path(repo).read_bytes()
            with self.assertRaisesRegex(RoutingConfigError, "approved template"):
                install_project_overlay(repo, "preprocess-cli", source, apply=True)
            self.assertFalse((repo / "AGENTS.md").exists())
            self.assertFalse((repo / ".codex").exists())
            self.assertEqual(exclude_path(repo).read_bytes(), exclude_before)

    def test_status_change_caused_by_installer_rolls_back_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = init_repo(Path(raw), "preprocess-cli")
            exclude = exclude_path(repo)
            exclude_before = exclude.read_bytes()

            def omit_codex(existing: bytes, body: bytes, begin: bytes,
                           end: bytes) -> bytes:
                del body
                return (existing.rstrip(b"\r\n") + b"\n\n" + begin
                        + b"\n/AGENTS.md\n" + end + b"\n")

            with mock.patch("codex_routing.project_install.merge_managed_block",
                            side_effect=omit_codex):
                with self.assertRaisesRegex(RoutingConfigError, "Git status changed"):
                    install_project_overlay(repo, "preprocess-cli", SOURCE_ROOT,
                                            apply=True)
            self.assertFalse((repo / "AGENTS.md").exists())
            self.assertFalse((repo / ".codex").exists())
            self.assertEqual(exclude.read_bytes(), exclude_before)
            self.assertEqual(git("status", "--porcelain", cwd=repo).stdout, "")

    def test_status_verification_failure_rolls_back_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = init_repo(Path(raw), "preprocess-cli")
            exclude = exclude_path(repo)
            exclude_before = exclude.read_bytes()
            with mock.patch(
                "codex_routing.project_install._git_status",
                side_effect=("", RoutingConfigError("status unavailable")),
            ):
                with self.assertRaisesRegex(RoutingConfigError, "status unavailable"):
                    install_project_overlay(repo, "preprocess-cli", SOURCE_ROOT,
                                            apply=True)
            self.assertFalse((repo / "AGENTS.md").exists())
            self.assertFalse((repo / ".codex").exists())
            self.assertEqual(exclude.read_bytes(), exclude_before)

    def test_apply_wraps_git_ignore_launch_failure_and_rolls_back_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = init_repo(Path(raw), "preprocess-cli")
            exclude = exclude_path(repo)
            exclude_before = exclude.read_bytes()
            real_run = subprocess.run

            def fail_ignore_check(command, *args, **kwargs):
                if "check-ignore" in command:
                    raise OSError("injected Git launch failure")
                return real_run(command, *args, **kwargs)

            with mock.patch(
                "codex_routing.project_install.subprocess.run",
                side_effect=fail_ignore_check,
            ):
                with self.assertRaisesRegex(RoutingConfigError, "Git ignore check"):
                    install_project_overlay(repo, "preprocess-cli", SOURCE_ROOT,
                                            apply=True)
            self.assertFalse((repo / "AGENTS.md").exists())
            self.assertFalse((repo / ".codex").exists())
            self.assertEqual(exclude.read_bytes(), exclude_before)

    def test_validation_wraps_git_ignore_launch_failure_with_repo_context(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = init_repo(Path(raw), "preprocess-cli")
            install_project_overlay(repo, "preprocess-cli", SOURCE_ROOT, apply=True)
            real_run = subprocess.run

            def fail_ignore_check(command, *args, **kwargs):
                if "check-ignore" in command:
                    raise OSError("injected Git launch failure")
                return real_run(command, *args, **kwargs)

            with mock.patch(
                "codex_routing.project_install.subprocess.run",
                side_effect=fail_ignore_check,
            ):
                with self.assertRaisesRegex(
                    RoutingConfigError, f"Git ignore check.*{repo}"
                ):
                    validate_project_overlay(repo, "preprocess-cli", SOURCE_ROOT)

    def test_validation_propagates_unknown_git_ignore_failures(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = init_repo(Path(raw), "preprocess-cli")
            install_project_overlay(repo, "preprocess-cli", SOURCE_ROOT, apply=True)
            real_run = subprocess.run

            for failure in (
                RuntimeError("unexpected Git ignore fault"),
                KeyboardInterrupt(),
                SystemExit(7),
            ):
                with self.subTest(failure=type(failure).__name__):
                    def fail_ignore_check(command, *args, **kwargs):
                        if "check-ignore" in command:
                            raise failure
                        return real_run(command, *args, **kwargs)

                    with mock.patch(
                        "codex_routing.project_install.subprocess.run",
                        side_effect=fail_ignore_check,
                    ):
                        with self.assertRaises(type(failure)):
                            validate_project_overlay(
                                repo, "preprocess-cli", SOURCE_ROOT
                            )

    def test_foreign_target_created_at_transaction_boundary_is_preserved(self) -> None:
        for identical_before in (False, True):
            with self.subTest(identical_before=identical_before), tempfile.TemporaryDirectory() as raw:
                repo = init_repo(Path(raw), "preprocess-cli")
                target = repo / "AGENTS.md"
                if identical_before:
                    target.write_bytes(
                        (SOURCE_ROOT / "templates/projects/preprocess-cli-AGENTS.md")
                        .read_bytes()
                    )
                exclude = exclude_path(repo)
                exclude_before = exclude.read_bytes()

                def inject_foreign(updates, backup_root, **kwargs):
                    target.write_bytes(b"foreign race bytes\n")
                    return managed_files.apply_transaction(
                        updates, backup_root, **kwargs
                    )

                with mock.patch(
                    "codex_routing.project_install.apply_transaction",
                    side_effect=inject_foreign,
                ):
                    with self.assertRaisesRegex(RoutingConfigError, "changed"):
                        install_project_overlay(repo, "preprocess-cli", SOURCE_ROOT,
                                                apply=True)
                self.assertEqual(target.read_bytes(), b"foreign race bytes\n")
                self.assertFalse((repo / ".codex").exists())
                self.assertEqual(exclude.read_bytes(), exclude_before)

    def test_publish_then_raise_restores_project_files_with_preconditioned_callback(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = init_repo(Path(raw), "preprocess-cli")
            exclude = exclude_path(repo)
            exclude_before = exclude.read_bytes()
            real_replace = os.replace
            calls: list[str] = []

            def publish_then_raise(source: Path, destination: Path) -> None:
                real_replace(source, destination)
                if Path(destination) == exclude:
                    calls.append(Path(source).name)
                    if len(calls) == 1:
                        raise OSError("injected post-publish project failure")

            with mock.patch(
                "codex_routing.project_install.os.replace",
                side_effect=publish_then_raise,
            ):
                with self.assertRaisesRegex(RoutingConfigError, "post-publish"):
                    install_project_overlay(
                        repo, "preprocess-cli", SOURCE_ROOT, apply=True
                    )

            self.assertEqual(exclude.read_bytes(), exclude_before)
            self.assertFalse((repo / "AGENTS.md").exists())
            self.assertFalse((repo / ".codex").exists())
            self.assertFalse(
                list((repo / ".git" / "codex-routing-backups").rglob("manifest.json"))
            )
            self.assertEqual(len(calls), 2)
            self.assertIn("install", calls[0])
            self.assertIn("rollback", calls[1])

    def test_workspace_preflights_all_before_any_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            repos = {name: init_repo(workspace, name) for name in REPO_NAMES}
            foreign = repos["egs-main"] / "AGENTS.md"
            foreign.write_bytes(b"foreign\n")
            excludes = {name: exclude_path(repo).read_bytes()
                        for name, repo in repos.items()}
            with self.assertRaisesRegex(RoutingConfigError, "foreign untracked target"):
                install_egs_workspace(workspace, SOURCE_ROOT, apply=True)
            for name in ("preprocess-cli", "3dgs-gen"):
                self.assertFalse((repos[name] / "AGENTS.md").exists())
                self.assertFalse((repos[name] / ".codex").exists())
            self.assertEqual(foreign.read_bytes(), b"foreign\n")
            for name, repo in repos.items():
                self.assertEqual(exclude_path(repo).read_bytes(), excludes[name])

    def test_workspace_publishes_all_in_one_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            repos = {name: init_repo(workspace, name) for name in REPO_NAMES}
            plans = install_egs_workspace(workspace, SOURCE_ROOT, apply=True)
            self.assertEqual(tuple(plan.repo_name for plan in plans), REPO_NAMES)
            self.assertTrue(all(plan.applied for plan in plans))
            self.assertEqual(len({plan.manifest_path for plan in plans}), 1)
            self.assertIsNotNone(plans[0].manifest_path)
            for name, repo in repos.items():
                self.assertTrue(validate_project_overlay(repo, name, SOURCE_ROOT).valid)
                self.assertEqual(git("status", "--porcelain", cwd=repo).stdout, "")

    def test_validation_rejects_changed_bytes_invalid_toml_and_missing_ignore(self) -> None:
        mutations = (
            ("AGENTS.md", b"changed\n"),
            (".codex/config.toml", b'model = "unterminated\n'),
            (".codex/agents/critical_reviewer.toml", b"changed\n"),
        )
        for relative, payload in mutations:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as raw:
                repo = init_repo(Path(raw), "preprocess-cli")
                install_project_overlay(repo, "preprocess-cli", SOURCE_ROOT, apply=True)
                (repo / relative).write_bytes(payload)
                self.assertFalse(
                    validate_project_overlay(repo, "preprocess-cli", SOURCE_ROOT).valid
                )
        with tempfile.TemporaryDirectory() as raw:
            repo = init_repo(Path(raw), "preprocess-cli")
            install_project_overlay(repo, "preprocess-cli", SOURCE_ROOT, apply=True)
            exclude_path(repo).write_bytes(b"# foreign only\n")
            self.assertFalse(
                validate_project_overlay(repo, "preprocess-cli", SOURCE_ROOT).valid
            )


if __name__ == "__main__":
    unittest.main()
