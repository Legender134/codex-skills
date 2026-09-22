import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from codex_routing.cli import main
from codex_routing.errors import RoutingConfigError
from codex_routing.validate import plan_rollback, validate_source


SOURCE_ROOT = Path(__file__).resolve().parents[1]
COMMANDS = (
    "check-source",
    "plan-global",
    "install-global",
    "install-egs",
    "validate-global",
    "validate-egs",
    "rollback",
)


def run_main(arguments: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = main(arguments)
    return code, stdout.getvalue(), stderr.getvalue()


def init_repo(workspace: Path, name: str) -> Path:
    repo = workspace / name
    repo.mkdir()
    for command in (
        ("git", "init", "-q"),
        ("git", "config", "user.email", "routing-tests@example.invalid"),
        ("git", "config", "user.name", "Routing Tests"),
    ):
        subprocess.run(command, cwd=repo, check=True, capture_output=True, text=True)
    (repo / "README.md").write_text(f"# {name}\n", encoding="utf-8")
    subprocess.run(
        ("git", "add", "README.md"),
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ("git", "commit", "-qm", "initial"),
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return repo


class CliTests(unittest.TestCase):
    def make_home(self, raw: str) -> Path:
        home = Path(raw) / ".codex"
        home.mkdir()
        return home

    def copy_source(self, raw: str) -> Path:
        source_root = Path(raw) / "source"
        shutil.copytree(SOURCE_ROOT / "templates", source_root / "templates")
        return source_root

    def test_every_subcommand_help_exits_successfully(self) -> None:
        for command in COMMANDS:
            with self.subTest(command=command):
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    with self.assertRaises(SystemExit) as raised:
                        main([command, "--help"])
                self.assertEqual(raised.exception.code, 0)
                self.assertIn("usage:", stdout.getvalue())

    def test_subcommands_require_their_operation_arguments(self) -> None:
        for command in COMMANDS:
            with self.subTest(command=command):
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as raised:
                        main([command])
                self.assertEqual(raised.exception.code, 2)
                self.assertIn("usage:", stderr.getvalue())

    def test_install_global_is_dry_run_without_apply(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            codex_home = self.make_home(raw)

            code, stdout, stderr = run_main(
                [
                    "install-global",
                    "--target",
                    "wsl",
                    "--codex-home",
                    str(codex_home),
                    "--source-root",
                    str(SOURCE_ROOT),
                ]
            )

            self.assertEqual(code, 0)
            self.assertIn("dry-run", stdout)
            self.assertEqual(stderr, "")
            self.assertFalse((codex_home / "agents" / "scout.toml").exists())

    def test_install_global_apply_creates_a_manifest_and_validates(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            codex_home = self.make_home(raw)
            base = [
                "--target",
                "wsl",
                "--codex-home",
                str(codex_home),
                "--source-root",
                str(SOURCE_ROOT),
            ]

            code, stdout, stderr = run_main(["install-global", *base, "--apply"])

            self.assertEqual(code, 0)
            self.assertIn("applied", stdout)
            self.assertEqual(stderr, "")
            self.assertTrue((codex_home / "agents" / "scout.toml").is_file())
            manifests = list((codex_home / "backups").rglob("manifest.json"))
            self.assertEqual(len(manifests), 1)

            code, stdout, stderr = run_main(["validate-global", *base])

            self.assertEqual(code, 0)
            self.assertIn("valid=true", stdout)
            self.assertEqual(stderr, "")

    def test_validate_global_reports_invalid_state_with_exit_one(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            codex_home = self.make_home(raw)

            code, stdout, stderr = run_main(
                [
                    "validate-global",
                    "--target",
                    "wsl",
                    "--codex-home",
                    str(codex_home),
                    "--source-root",
                    str(SOURCE_ROOT),
                ]
            )

            self.assertEqual(code, 1)
            self.assertIn("valid=false", stdout)
            self.assertEqual(stderr, "")

    def test_domain_error_is_one_stderr_line_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            missing = Path(raw) / "missing"

            code, stdout, stderr = run_main(
                ["validate-global", "--target", "wsl", "--codex-home", str(missing)]
            )

            self.assertEqual(code, 2)
            self.assertEqual(stdout, "")
            self.assertEqual(len(stderr.splitlines()), 1)
            self.assertTrue(stderr.startswith("error: "))
            self.assertNotIn("Traceback", stderr)

    def test_programming_errors_propagate_from_the_cli_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            codex_home = self.make_home(raw)
            with mock.patch(
                "codex_routing.cli.plan_global_install",
                side_effect=RuntimeError("unexpected programmer error"),
            ):
                with self.assertRaisesRegex(RuntimeError, "unexpected programmer error"):
                    main(
                        [
                            "plan-global",
                            "--target",
                            "wsl",
                            "--codex-home",
                            str(codex_home),
                            "--source-root",
                            str(SOURCE_ROOT),
                        ]
                    )

    def test_plan_output_does_not_expose_unrelated_config_values(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            codex_home = self.make_home(raw)
            (codex_home / "config.toml").write_text(
                '[mcp_servers.keep]\ntoken = "secret-token-value"\n',
                encoding="utf-8",
            )

            code, stdout, stderr = run_main(
                [
                    "plan-global",
                    "--target",
                    "wsl",
                    "--codex-home",
                    str(codex_home),
                    "--source-root",
                    str(SOURCE_ROOT),
                ]
            )

            self.assertEqual(code, 0)
            self.assertIn("sha256=", stdout)
            self.assertNotIn("secret-token-value", stdout + stderr)

    def test_check_source_uses_only_the_approved_source_artifacts(self) -> None:
        with mock.patch(
            "codex_routing.cli.validate_global_install",
            side_effect=AssertionError("live configuration must not be read"),
        ):
            code, stdout, stderr = run_main(
                ["check-source", "--source-root", str(SOURCE_ROOT)]
            )

        self.assertEqual(code, 0)
        self.assertIn("sha256=", stdout)
        self.assertEqual(stderr, "")
        self.assertNotIn("secret-token-value", stdout)

    def test_source_validation_binds_the_exact_approved_template_digests(self) -> None:
        report = validate_source(SOURCE_ROOT)

        self.assertEqual(len(report.template_digests), 8)
        self.assertEqual(
            tuple(path for path, _ in report.template_digests),
            (
                "agents/routine_worker.toml",
                "agents/critical_reviewer.toml",
                "agents/explorer.toml",
                "agents/reviewer.toml",
                "agents/scout.toml",
                "agents/worker.toml",
                "global/windows-AGENTS.md",
                "global/wsl-AGENTS.md",
            ),
        )
        self.assertNotIn("secret-token-value", repr(report))

    def test_source_validation_rejects_a_missing_approved_template(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source_root = self.copy_source(raw)
            (source_root / "templates" / "agents" / "scout.toml").unlink()

            with self.assertRaisesRegex(RoutingConfigError, "scout.toml"):
                validate_source(source_root)

    def test_source_validation_rejects_modified_approved_template_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source_root = self.copy_source(raw)
            (source_root / "templates" / "agents" / "scout.toml").write_text(
                "modified\n", encoding="utf-8"
            )

            with self.assertRaisesRegex(RoutingConfigError, "scout.toml"):
                validate_source(source_root)

    def test_source_validation_rejects_an_extra_template_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source_root = self.copy_source(raw)
            (source_root / "templates" / "agents" / "unapproved.toml").write_text(
                "unapproved\n", encoding="utf-8"
            )

            with self.assertRaisesRegex(RoutingConfigError, "unapproved.toml"):
                validate_source(source_root)

    def test_source_validation_rejects_a_linked_template_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source_root = self.copy_source(raw)
            scout = source_root / "templates" / "agents" / "scout.toml"
            scout.unlink()
            scout.symlink_to(SOURCE_ROOT / "templates" / "agents" / "scout.toml")

            with self.assertRaisesRegex(RoutingConfigError, "symlink|reparse"):
                validate_source(source_root)

    def test_source_validation_wraps_filesystem_errors_with_action_and_path(self) -> None:
        with mock.patch(
            "codex_routing.validate.os.scandir",
            side_effect=OSError("injected source scan failure"),
        ):
            with self.assertRaisesRegex(
                RoutingConfigError, "unable to validate source artifacts at"
            ):
                validate_source(SOURCE_ROOT)

    def test_source_validation_propagates_unknown_runtime_and_value_errors(self) -> None:
        for failure in (
            RuntimeError("unexpected source traversal fault"),
            ValueError("unexpected source traversal value"),
        ):
            with self.subTest(failure=type(failure).__name__), mock.patch(
                "codex_routing.validate.os.scandir", side_effect=failure
            ):
                with self.assertRaisesRegex(type(failure), str(failure)):
                    validate_source(SOURCE_ROOT)

    def test_check_source_propagates_unknown_runtime_errors(self) -> None:
        with mock.patch(
            "codex_routing.validate.os.scandir",
            side_effect=RuntimeError("unexpected source traversal fault"),
        ):
            with self.assertRaisesRegex(
                RuntimeError, "unexpected source traversal fault"
            ):
                main(["check-source", "--source-root", str(SOURCE_ROOT)])

    def test_retired_project_commands_never_touch_repositories(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            repo = init_repo(workspace, "preprocess-cli")
            (repo / "AGENTS.md").write_text("User domain rules")
            (repo / ".codex").mkdir()
            config = repo / ".codex/config.toml"
            config.write_text('[hooks]\nkeep = true\n')
            before = {str(p.relative_to(workspace)): p.read_bytes() for p in workspace.rglob("*") if p.is_file()}
            for arguments in (["install-egs"], ["install-egs", "--apply"], ["validate-egs"]):
                code, stdout, stderr = run_main([*arguments, "--workspace", str(workspace), "--source-root", str(SOURCE_ROOT)])
                self.assertEqual(code, 2)
                self.assertEqual(stdout, "")
                self.assertIn("project routing is retired", stderr)
                self.assertEqual(before, {str(p.relative_to(workspace)): p.read_bytes() for p in workspace.rglob("*") if p.is_file()})

    def test_rollback_parses_manifest_dry_run_and_applies_only_with_apply(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            codex_home = self.make_home(raw)
            original = b'[mcp_servers.keep]\ntoken = "secret-token-value"\n'
            (codex_home / "config.toml").write_bytes(original)
            install_arguments = [
                "install-global",
                "--target",
                "wsl",
                "--codex-home",
                str(codex_home),
                "--source-root",
                str(SOURCE_ROOT),
                "--apply",
            ]
            self.assertEqual(run_main(install_arguments)[0], 0)
            manifest = next((codex_home / "backups").rglob("manifest.json"))
            rollback_arguments = ["rollback", "--manifest", str(manifest)]

            code, stdout, stderr = run_main(rollback_arguments)

            self.assertEqual(code, 0)
            self.assertIn("dry-run", stdout)
            self.assertEqual(stderr, "")
            self.assertNotIn("secret-token-value", stdout + stderr)
            self.assertNotEqual((codex_home / "config.toml").read_bytes(), original)

            code, stdout, stderr = run_main([*rollback_arguments, "--apply"])

            self.assertEqual(code, 0)
            self.assertIn("applied", stdout)
            self.assertEqual(stderr, "")
            self.assertEqual((codex_home / "config.toml").read_bytes(), original)
            self.assertFalse((codex_home / "agents" / "scout.toml").exists())

    def test_rollback_rejects_a_malformed_manifest_as_a_domain_error(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            manifest = Path(raw) / "manifest.json"
            manifest.write_text("not JSON", encoding="utf-8")

            code, stdout, stderr = run_main(["rollback", "--manifest", str(manifest)])

            self.assertEqual(code, 2)
            self.assertEqual(stdout, "")
            self.assertEqual(len(stderr.splitlines()), 1)
            self.assertTrue(stderr.startswith("error: "))
            self.assertNotIn("Traceback", stderr)

    def test_rollback_preview_requires_an_exact_integer_manifest_schema(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            manifest = Path(raw) / "manifest.json"
            for schema in (True, 1.0):
                with self.subTest(schema=schema):
                    manifest.write_text(
                        json.dumps({"schema": schema, "files": []}),
                        encoding="utf-8",
                    )

                    code, stdout, stderr = run_main(
                        ["rollback", "--manifest", str(manifest)]
                    )

                    self.assertEqual(code, 2)
                    self.assertEqual(stdout, "")
                    self.assertIn("manifest schema", stderr)

            manifest.write_text(
                json.dumps({"schema": 1, "files": []}), encoding="utf-8"
            )
            code, stdout, stderr = run_main(["rollback", "--manifest", str(manifest)])

            self.assertEqual(code, 0)
            self.assertIn("files=0", stdout)
            self.assertEqual(stderr, "")

    def test_rollback_parsing_propagates_unknown_runtime_errors(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            manifest = Path(raw) / "manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            failure = RuntimeError("unexpected rollback parser fault")

            with mock.patch(
                "codex_routing.validate._parse_manifest", side_effect=failure
            ):
                with self.assertRaisesRegex(RuntimeError, str(failure)):
                    plan_rollback(manifest)

            with mock.patch(
                "codex_routing.validate._parse_manifest", side_effect=failure
            ):
                with self.assertRaisesRegex(RuntimeError, str(failure)):
                    main(["rollback", "--manifest", str(manifest)])

    def test_rollback_read_close_errors_are_contextual_domain_errors(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            manifest = Path(raw) / "manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            real_close = os.close

            def fail_after_closing(fd: int) -> None:
                real_close(fd)
                raise OSError("injected close failure")

            with mock.patch(
                "codex_routing.validate.os.close", side_effect=fail_after_closing
            ):
                with self.assertRaisesRegex(
                    RoutingConfigError,
                    f"unable to read rollback manifest: {manifest}",
                ):
                    plan_rollback(manifest)
