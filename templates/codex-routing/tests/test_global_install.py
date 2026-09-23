import os
import shutil
import tempfile
import tomllib
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from codex_routing.errors import RoutingConfigError
from codex_routing.global_install import (
    _windows_mount_roots,
    install_global,
    plan_global_install,
    validate_global_install,
)
from codex_routing.managed_files import (
    TransactionResult,
    apply_transaction as apply_managed_transaction,
    rollback_transaction,
)


SOURCE_ROOT = Path(__file__).resolve().parents[1]
ROLE_NAMES = ("scout", "explorer", "worker", "reviewer", "routine_worker", "critical_reviewer")


class GlobalInstallTests(unittest.TestCase):
    def setUp(self) -> None:
        self.windows_mount_roots: list[Path] = []
        patcher = mock.patch(
            "codex_routing.global_install._windows_mount_roots",
            side_effect=lambda: tuple(self.windows_mount_roots),
            create=True,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_home(self, raw: str, *, target: str = "wsl") -> Path:
        root = Path(raw)
        if target == "windows":
            mount_root = root / "windows-mount"
            mount_root.mkdir()
            self.windows_mount_roots.append(mount_root)
            home = mount_root / ".codex"
        else:
            home = root / ".codex"
        home.mkdir()
        return home

    def assert_public_apis_reject_target(self, home: Path, target: str) -> None:
        calls = (
            ("plan", lambda: plan_global_install(home, target, SOURCE_ROOT)),
            (
                "apply",
                lambda: install_global(home, target, SOURCE_ROOT, apply=True),
            ),
            ("validation", lambda: validate_global_install(home, target, SOURCE_ROOT)),
        )
        for operation, call in calls:
            with self.subTest(operation=operation):
                with self.assertRaisesRegex(RoutingConfigError, "target"):
                    call()

    def test_windows_plan_preserves_foreign_config_and_sets_cap_two(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = self.make_home(raw, target="windows")
            (home / "config.toml").write_text(
                'model = "gpt-6-sol"\n[mcp_servers.keep]\ncommand = "keep"\n',
                encoding="utf-8",
            )

            plan = plan_global_install(home, "windows", SOURCE_ROOT)
            config = tomllib.loads(plan.config_after.decode("utf-8"))

            self.assertEqual(config["model"], "gpt-6-sol")
            self.assertEqual(config["model_reasoning_effort"], "high")
            self.assertEqual(config["agents"]["max_concurrent_threads_per_session"], 2)
            self.assertEqual(config["mcp_servers"]["keep"]["command"], "keep")
            self.assertFalse(plan.applied)

    def test_public_global_apis_reject_wsl_target_for_mounted_windows_home(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = self.make_home(raw, target="windows")

            self.assert_public_apis_reject_target(home, "wsl")

            self.assertEqual(list(home.iterdir()), [])

    def test_public_global_apis_reject_windows_target_for_native_wsl_home(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = self.make_home(raw)

            self.assert_public_apis_reject_target(home, "windows")

            self.assertEqual(list(home.iterdir()), [])

    def test_windows_mount_reader_detects_drvfs_without_fixed_mount_path(self) -> None:
        mountinfo = (
            "132 82 0:70 / /temporary/windows-home rw - 9p none "
            "rw,aname=drvfs;path=C:\\\\;uid=1001\n"
            "133 82 0:71 / /temporary/not-windows rw - 9p drivers "
            "rw,not-aname=drvfs\n"
            "134 82 0:72 / /temporary/drive-like-source rw - ext4 C:\\134 rw\n"
        )

        with mock.patch(
            "codex_routing.global_install.Path.read_text", return_value=mountinfo
        ):
            roots = _windows_mount_roots()

        self.assertEqual(roots, (Path("/temporary/windows-home"),))

    def test_windows_mount_reader_accepts_a_valid_native_wsl_table(self) -> None:
        mountinfo = "42 1 0:1 / / rw - ext4 /dev/root rw\n"

        with mock.patch(
            "codex_routing.global_install.Path.read_text", return_value=mountinfo
        ):
            roots = _windows_mount_roots()

        self.assertEqual(roots, ())

    def test_windows_mount_reader_refuses_unreadable_or_invalid_utf8_evidence(
        self,
    ) -> None:
        failures = (
            OSError("mountinfo unavailable"),
            UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"),
        )
        for failure in failures:
            with self.subTest(failure=type(failure).__name__), mock.patch(
                "codex_routing.global_install.Path.read_text", side_effect=failure
            ):
                with self.assertRaisesRegex(RoutingConfigError, "mountinfo"):
                    _windows_mount_roots()

    def test_windows_mount_reader_refuses_malformed_mountinfo(self) -> None:
        mountinfos = (
            "malformed mountinfo record\n",
            "42 1 0:1 / relative rw - ext4 /dev/root rw\n",
            "mount 82 0:70 / /temporary/windows-home rw - 9p none rw\n",
            "132 parent 0:70 / /temporary/windows-home rw - 9p none rw\n",
            "132 82 major:70 / /temporary/windows-home rw - 9p none rw\n",
            "132 82 0:70 relative /temporary/windows-home rw - 9p none rw\n",
            "132 82 0:70 / /temporary/\\999 rw - 9p none rw\n",
            "132 82 0:70 / /temporary/\\04 rw - 9p none rw\n",
            "132 82 0:70 / /temporary/windows-home rw - 9p none rw extra-aname=drvfs\n",
        )
        for mountinfo in mountinfos:
            with self.subTest(mountinfo=mountinfo), mock.patch(
                "codex_routing.global_install.Path.read_text", return_value=mountinfo
            ):
                with self.assertRaisesRegex(RoutingConfigError, "mountinfo"):
                    _windows_mount_roots()

    def test_public_global_apis_fail_closed_for_field_complete_malformed_mountinfo(
        self,
    ) -> None:
        mountinfo = (
            "132 82 0:70 / /temporary/windows-home rw - 9p none "
            "rw,aname=drivers trailing-aname=drvfs\n"
        )
        with tempfile.TemporaryDirectory() as raw:
            home = self.make_home(raw)
            calls = (
                lambda: plan_global_install(home, "wsl", SOURCE_ROOT),
                lambda: install_global(home, "wsl", SOURCE_ROOT, apply=True),
                lambda: validate_global_install(home, "wsl", SOURCE_ROOT),
            )
            with (
                mock.patch(
                    "codex_routing.global_install._windows_mount_roots",
                    wraps=_windows_mount_roots,
                ),
                mock.patch(
                    "codex_routing.global_install.Path.read_text",
                    return_value=mountinfo,
                ),
            ):
                for call in calls:
                    with self.assertRaisesRegex(RoutingConfigError, "mountinfo"):
                        call()

            self.assertEqual(list(home.iterdir()), [])

    def test_windows_mount_reader_refuses_no_recognizable_mountinfo_records(
        self,
    ) -> None:
        with mock.patch(
            "codex_routing.global_install.Path.read_text", return_value="\n"
        ):
            with self.assertRaisesRegex(RoutingConfigError, "mountinfo"):
                _windows_mount_roots()

    def test_public_global_apis_fail_closed_when_mount_evidence_is_unavailable(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = self.make_home(raw)
            calls = (
                lambda: plan_global_install(home, "wsl", SOURCE_ROOT),
                lambda: install_global(home, "wsl", SOURCE_ROOT, apply=True),
                lambda: validate_global_install(home, "wsl", SOURCE_ROOT),
            )
            with mock.patch(
                "codex_routing.global_install._windows_mount_roots",
                side_effect=RoutingConfigError("mountinfo unavailable"),
            ):
                for call in calls:
                    with self.assertRaisesRegex(RoutingConfigError, "mountinfo"):
                        call()

            self.assertEqual(list(home.iterdir()), [])

    def test_windows_mount_reader_accepts_a_c_only_wsl_layout(self) -> None:
        mountinfo = (
            "42 1 0:1 / / rw - ext4 /dev/root rw\n"
            "132 82 0:70 / /mnt/c rw - 9p none rw,aname=drvfs\n"
        )
        with mock.patch("codex_routing.global_install.Path.read_text", return_value=mountinfo):
            roots = _windows_mount_roots()

        self.assertEqual(roots, (Path("/mnt/c"),))

    def test_wsl_plan_has_sol_high_luna_max_and_exact_role_templates(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = self.make_home(raw)

            plan = plan_global_install(home, "wsl", SOURCE_ROOT)
            config = tomllib.loads(plan.config_after.decode("utf-8"))
            role_updates = {
                update.path.name: update.after
                for update in plan.updates
                if update.path.parent == home / "agents"
            }

            self.assertEqual(config["model"], "gpt-6-sol")
            self.assertEqual(config["model_reasoning_effort"], "high")
            self.assertEqual(config["agents"]["max_concurrent_threads_per_session"], 2)
            self.assertEqual(
                config["agents"]["default_subagent_model"], "gpt-6-sol"
            )
            self.assertEqual(
                config["agents"]["default_subagent_reasoning_effort"], "high"
            )
            self.assertEqual(
                set(role_updates), {f"{name}.toml" for name in ROLE_NAMES}
            )
            for name in ROLE_NAMES:
                expected = (
                    SOURCE_ROOT / "templates" / "agents" / f"{name}.toml"
                ).read_bytes()
                self.assertEqual(role_updates[f"{name}.toml"], expected)

            scout = tomllib.loads(role_updates["scout.toml"].decode("utf-8"))
            worker = tomllib.loads(role_updates["worker.toml"].decode("utf-8"))
            self.assertEqual(
                (scout["model"], scout["model_reasoning_effort"]),
                ("gpt-6-luna", "low"),
            )
            self.assertEqual(
                (worker["model"], worker["model_reasoning_effort"]),
                ("gpt-6-luna", "max"),
            )

    def test_global_agents_managed_block_preserves_foreign_text_and_crlf(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = self.make_home(raw, target="windows")
            original = b"# Personal notes\r\n\r\nKeep this foreign line.\r\n"
            (home / "AGENTS.md").write_bytes(original)

            plan = plan_global_install(home, "windows", SOURCE_ROOT)
            agents_after = next(
                update.after
                for update in plan.updates
                if update.path == home / "AGENTS.md"
            )

            self.assertIn(b"# Personal notes\r\n", agents_after)
            self.assertIn(b"Keep this foreign line.\r\n", agents_after)
            self.assertIn(b"<!-- BEGIN CODEX ROUTING -->\r\n", agents_after)
            self.assertIn(b"<!-- END CODEX ROUTING -->\r\n", agents_after)
            self.assertIn(
                (SOURCE_ROOT / "templates" / "global" / "windows-AGENTS.md")
                .read_bytes()
                .rstrip(b"\r\n"),
                agents_after,
            )

    def test_dry_run_does_not_create_files_or_directories(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = self.make_home(raw)

            plan = install_global(home, "wsl", SOURCE_ROOT)

            self.assertFalse(plan.applied)
            self.assertFalse((home / "config.toml").exists())
            self.assertFalse((home / "AGENTS.md").exists())
            self.assertFalse((home / "agents").exists())
            self.assertEqual(list(home.iterdir()), [])

    def test_plan_repr_lists_digests_without_foreign_config_values(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = self.make_home(raw, target="windows")
            (home / "config.toml").write_text(
                '[mcp_servers.keep]\ntoken = "secret-token-value"\n',
                encoding="utf-8",
            )

            rendered = repr(plan_global_install(home, "windows", SOURCE_ROOT))

            self.assertIn(str(home / "config.toml"), rendered)
            self.assertIn("sha256=", rendered)
            self.assertNotIn("secret-token-value", rendered)

    def test_foreign_same_name_agent_stops_before_writes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = self.make_home(raw)
            agents = home / "agents"
            agents.mkdir()
            scout = agents / "scout.toml"
            scout.write_text("foreign", encoding="utf-8")

            with self.assertRaisesRegex(RoutingConfigError, "scout.toml"):
                install_global(home, "wsl", SOURCE_ROOT, apply=True)

            self.assertEqual(scout.read_text(encoding="utf-8"), "foreign")
            self.assertFalse((home / "config.toml").exists())
            self.assertFalse((home / "AGENTS.md").exists())
            self.assertFalse((agents / "explorer.toml").exists())

    def test_apply_rechecks_agent_conflicts_after_creating_agents_directory(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = self.make_home(raw)
            agents = home / "agents"
            scout = agents / "scout.toml"

            def create_foreign_agents_directory(path: Path):
                path.mkdir()
                scout.write_text("foreign", encoding="utf-8")
                result = os.lstat(path)
                return (
                    True,
                    (
                        result.st_dev,
                        result.st_ino,
                        result.st_mode,
                        getattr(result, "st_file_attributes", 0),
                    ),
                )

            with mock.patch(
                "codex_routing.global_install._ensure_role_directory",
                side_effect=create_foreign_agents_directory,
            ):
                with mock.patch(
                    "codex_routing.global_install.apply_transaction",
                    return_value=TransactionResult(home / "manifest.json", ()),
                ) as transaction:
                    with self.assertRaisesRegex(RoutingConfigError, "scout.toml"):
                        install_global(home, "wsl", SOURCE_ROOT, apply=True)

            transaction.assert_not_called()
            self.assertEqual(scout.read_text(encoding="utf-8"), "foreign")
            self.assertFalse((home / "config.toml").exists())
            self.assertFalse((home / "AGENTS.md").exists())

    def test_invalid_config_stops_before_writes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = self.make_home(raw, target="windows")
            config = home / "config.toml"
            config.write_text('model = "unterminated\n', encoding="utf-8")

            with self.assertRaisesRegex(RoutingConfigError, "invalid TOML"):
                install_global(home, "windows", SOURCE_ROOT, apply=True)

            self.assertEqual(
                config.read_text(encoding="utf-8"), 'model = "unterminated\n'
            )
            self.assertFalse((home / "AGENTS.md").exists())
            self.assertFalse((home / "agents").exists())

    def test_apply_rolls_back_when_unrelated_config_changes_after_final_plan(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = self.make_home(raw)
            config = home / "config.toml"
            config.write_bytes(b'[mcp_servers.keep]\ncommand = "before"\n')
            foreign = b'[mcp_servers.keep]\ncommand = "foreign"\n'

            def mutate_before_transaction(*args, **kwargs):
                config.write_bytes(foreign)
                return apply_managed_transaction(*args, **kwargs)

            with mock.patch(
                "codex_routing.global_install.apply_transaction",
                side_effect=mutate_before_transaction,
            ):
                with self.assertRaisesRegex(RoutingConfigError, "preflight"):
                    install_global(home, "wsl", SOURCE_ROOT, apply=True)

            self.assertEqual(config.read_bytes(), foreign)
            self.assertFalse((home / "AGENTS.md").exists())
            self.assertFalse((home / "agents").exists())

    def test_apply_rolls_back_when_managed_agents_changes_after_final_plan(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = self.make_home(raw)
            agents = home / "AGENTS.md"
            foreign = b"# Foreign instructions\n"

            def mutate_before_transaction(*args, **kwargs):
                agents.write_bytes(foreign)
                return apply_managed_transaction(*args, **kwargs)

            with mock.patch(
                "codex_routing.global_install.apply_transaction",
                side_effect=mutate_before_transaction,
            ):
                with self.assertRaisesRegex(RoutingConfigError, "preflight"):
                    install_global(home, "wsl", SOURCE_ROOT, apply=True)

            self.assertEqual(agents.read_bytes(), foreign)
            self.assertFalse((home / "config.toml").exists())
            self.assertFalse((home / "agents").exists())

    def test_apply_rolls_back_when_foreign_role_appears_after_final_plan(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = self.make_home(raw)
            scout = home / "agents" / "scout.toml"
            foreign = b'name = "foreign"\n'

            def mutate_before_transaction(*args, **kwargs):
                scout.write_bytes(foreign)
                return apply_managed_transaction(*args, **kwargs)

            with mock.patch(
                "codex_routing.global_install.apply_transaction",
                side_effect=mutate_before_transaction,
            ):
                with self.assertRaisesRegex(RoutingConfigError, "preflight"):
                    install_global(home, "wsl", SOURCE_ROOT, apply=True)

            self.assertEqual(scout.read_bytes(), foreign)
            self.assertFalse((home / "config.toml").exists())
            self.assertFalse((home / "AGENTS.md").exists())
            self.assertFalse((home / "agents" / "explorer.toml").exists())

    def test_apply_rejects_a_no_op_destination_changed_after_precondition_capture(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = self.make_home(raw)
            install_global(home, "wsl", SOURCE_ROOT, apply=True)
            config = home / "config.toml"
            foreign = config.read_bytes().replace(
                b'model = "gpt-6-sol"', b'model = "foreign-model"'
            )

            def mutate_before_transaction(*args, **kwargs):
                config.write_bytes(foreign)
                return apply_managed_transaction(*args, **kwargs)

            with mock.patch(
                "codex_routing.global_install.apply_transaction",
                side_effect=mutate_before_transaction,
            ):
                with self.assertRaisesRegex(RoutingConfigError, "preflight"):
                    install_global(home, "wsl", SOURCE_ROOT, apply=True)

            self.assertEqual(config.read_bytes(), foreign)
            self.assertTrue((home / "AGENTS.md").is_file())
            for role_name in ROLE_NAMES:
                self.assertEqual(
                    (home / "agents" / f"{role_name}.toml").read_bytes(),
                    (
                        SOURCE_ROOT / "templates" / "agents" / f"{role_name}.toml"
                    ).read_bytes(),
                )

    def test_publish_then_raise_restores_global_file_with_preconditioned_callback(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = self.make_home(raw)
            agents = home / "AGENTS.md"
            agents_before = b"# Local instructions\n"
            agents.write_bytes(agents_before)
            real_replace = os.replace
            calls: list[str] = []

            def publish_then_raise(source: Path, destination: Path) -> None:
                real_replace(source, destination)
                if Path(destination) == agents:
                    calls.append(Path(source).name)
                    if len(calls) == 1:
                        raise OSError("injected post-publish global failure")

            with mock.patch(
                "codex_routing.global_install.os.replace",
                side_effect=publish_then_raise,
            ):
                with self.assertRaisesRegex(RoutingConfigError, "post-publish"):
                    install_global(home, "wsl", SOURCE_ROOT, apply=True)

            self.assertEqual(agents.read_bytes(), agents_before)
            self.assertFalse((home / "config.toml").exists())
            self.assertFalse((home / "agents").exists())
            self.assertFalse(list((home / "backups").rglob("manifest.json")))
            self.assertEqual(len(calls), 2)
            self.assertIn("install", calls[0])
            self.assertIn("rollback", calls[1])

    def test_apply_validate_and_rollback_restore_every_global_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = self.make_home(raw)
            config_before = b'[mcp_servers.keep]\ncommand = "keep"\n'
            agents_before = b"# Local instructions\n\nKeep this text.\n"
            (home / "config.toml").write_bytes(config_before)
            (home / "AGENTS.md").write_bytes(agents_before)

            result = install_global(home, "wsl", SOURCE_ROOT, apply=True)
            report = validate_global_install(home, "wsl", SOURCE_ROOT)

            self.assertTrue(result.applied)
            self.assertIsNotNone(result.manifest_path)
            self.assertTrue(report.valid)
            self.assertEqual(
                report.owned_values,
                (
                    ("model", "gpt-6-sol"),
                    ("model_reasoning_effort", "high"),
                    ("agents.enabled", True),
                    ("agents.max_concurrent_threads_per_session", 2),
                    ("agents.default_subagent_model", "gpt-6-sol"),
                    ("agents.default_subagent_reasoning_effort", "high"),
                    ("agents.interrupt_message", True),
                ),
            )
            self.assertEqual(
                report.agent_files,
                tuple(home / "agents" / f"{name}.toml" for name in ROLE_NAMES),
            )
            self.assertEqual(report.unrelated_table_names, ("mcp_servers",))
            for name in ROLE_NAMES:
                self.assertEqual(
                    (home / "agents" / f"{name}.toml").read_bytes(),
                    (
                        SOURCE_ROOT / "templates" / "agents" / f"{name}.toml"
                    ).read_bytes(),
                )

            assert result.manifest_path is not None
            rollback_transaction(result.manifest_path)

            self.assertEqual((home / "config.toml").read_bytes(), config_before)
            self.assertEqual((home / "AGENTS.md").read_bytes(), agents_before)
            for name in ROLE_NAMES:
                self.assertFalse((home / "agents" / f"{name}.toml").exists())

    def test_idempotent_reinstall_reuses_existing_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = self.make_home(raw, target="windows")
            install_global(home, "windows", SOURCE_ROOT, apply=True)
            before = {
                path.relative_to(home): path.read_bytes()
                for path in (home / "agents").glob("*.toml")
            }
            before[Path("config.toml")] = (home / "config.toml").read_bytes()
            before[Path("AGENTS.md")] = (home / "AGENTS.md").read_bytes()
            backups_before = tuple((home / "backups").iterdir())

            dry_plan = plan_global_install(home, "windows", SOURCE_ROOT)
            result = install_global(home, "windows", SOURCE_ROOT, apply=True)
            after = {
                path.relative_to(home): path.read_bytes()
                for path in (home / "agents").glob("*.toml")
            }
            after[Path("config.toml")] = (home / "config.toml").read_bytes()
            after[Path("AGENTS.md")] = (home / "AGENTS.md").read_bytes()

            self.assertEqual(dry_plan.updates, ())
            self.assertTrue(result.applied)
            self.assertIsNone(result.manifest_path)
            self.assertEqual(tuple((home / "backups").iterdir()), backups_before)
            self.assertEqual(after, before)

    def test_identical_existing_role_file_is_a_no_op(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = self.make_home(raw)
            agents = home / "agents"
            agents.mkdir()
            (agents / "scout.toml").write_bytes(
                (
                    SOURCE_ROOT / "templates" / "agents" / "scout.toml"
                ).read_bytes()
            )

            plan = plan_global_install(home, "wsl", SOURCE_ROOT)

            self.assertNotIn(
                agents / "scout.toml", tuple(update.path for update in plan.updates)
            )
            self.assertEqual(
                (agents / "scout.toml").read_bytes(),
                (SOURCE_ROOT / "templates" / "agents" / "scout.toml").read_bytes(),
            )

    def test_plan_rejects_role_template_outside_approved_policy(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            home = self.make_home(raw)
            source_root = root / "source"
            shutil.copytree(SOURCE_ROOT / "templates", source_root / "templates")
            scout_template = source_root / "templates" / "agents" / "scout.toml"
            scout_template.write_text(
                scout_template.read_text(encoding="utf-8").replace(
                    'model = "gpt-6-luna"',
                    'model = "unapproved-model"',
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RoutingConfigError, "approved"):
                plan_global_install(home, "wsl", source_root)

            self.assertEqual(list(home.iterdir()), [])

    def test_plan_rejects_modified_global_template_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            home = self.make_home(raw, target="windows")
            source_root = root / "source"
            shutil.copytree(SOURCE_ROOT / "templates", source_root / "templates")
            (source_root / "templates" / "global" / "windows-AGENTS.md").write_bytes(
                b"# Unapproved global instructions\n"
            )

            with self.assertRaisesRegex(RoutingConfigError, "approved template"):
                plan_global_install(home, "windows", source_root)

            self.assertEqual(list(home.iterdir()), [])

    def test_plan_rejects_modified_role_template_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            home = root / "plan-codex-home"
            home.mkdir()
            source_root = root / "source"
            shutil.copytree(SOURCE_ROOT / "templates", source_root / "templates")
            scout_template = source_root / "templates" / "agents" / "scout.toml"
            scout_template.write_text(
                scout_template.read_text(encoding="utf-8").replace(
                    'description = ',
                    'description = "Unapproved instructions" # ',
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RoutingConfigError, "approved template"):
                plan_global_install(home, "wsl", source_root)

            self.assertEqual(list(home.iterdir()), [])

    def test_validation_rejects_modified_role_template_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            home = self.make_home(raw)
            source_root = root / "source"
            shutil.copytree(SOURCE_ROOT / "templates", source_root / "templates")
            scout_template = source_root / "templates" / "agents" / "scout.toml"
            scout_template.write_text(
                scout_template.read_text(encoding="utf-8").replace(
                    'description = ',
                    'description = "Unapproved instructions" # ',
                ),
                encoding="utf-8",
            )

            install_global(home, "wsl", SOURCE_ROOT, apply=True)

            with self.assertRaisesRegex(RoutingConfigError, "approved template"):
                validate_global_install(home, "wsl", source_root)

    def test_symlink_and_directory_destinations_are_refused_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            home = self.make_home(raw, target="windows")
            target = root / "target.toml"
            target.write_bytes(b"foreign target\n")
            (home / "config.toml").symlink_to(target)

            with self.assertRaisesRegex(RoutingConfigError, "symlink"):
                plan_global_install(home, "windows", SOURCE_ROOT)

            self.assertEqual(target.read_bytes(), b"foreign target\n")
            self.assertFalse((home / "AGENTS.md").exists())

        with tempfile.TemporaryDirectory() as raw:
            home = self.make_home(raw)
            (home / "AGENTS.md").mkdir()

            with self.assertRaisesRegex(RoutingConfigError, "regular file"):
                plan_global_install(home, "wsl", SOURCE_ROOT)

            self.assertTrue((home / "AGENTS.md").is_dir())

    def test_reparse_destination_is_refused_without_reading_or_writing_it(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = self.make_home(raw, target="windows")
            config = home / "config.toml"
            config.write_bytes(b'custom = "keep"\n')
            original_lstat = os.lstat

            def lstat_with_reparse(path: os.PathLike[str] | str):
                result = original_lstat(path)
                if Path(path) == config:
                    return SimpleNamespace(
                        st_mode=result.st_mode,
                        st_file_attributes=0x400,
                    )
                return result

            with mock.patch(
                "codex_routing.global_install._lstat", side_effect=lstat_with_reparse
            ):
                with self.assertRaisesRegex(RoutingConfigError, "reparse"):
                    plan_global_install(home, "windows", SOURCE_ROOT)

            self.assertEqual(config.read_bytes(), b'custom = "keep"\n')
            self.assertFalse((home / "AGENTS.md").exists())

    def test_apply_delegates_all_updates_to_one_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = self.make_home(raw, target="windows")
            manifest = home / "backups" / "transaction" / "manifest.json"
            expected = plan_global_install(home, "windows", SOURCE_ROOT)

            with mock.patch(
                "codex_routing.global_install.apply_transaction",
                return_value=TransactionResult(
                    manifest, tuple(update.path for update in expected.updates)
                ),
            ) as transaction:
                result = install_global(home, "windows", SOURCE_ROOT, apply=True)

            transaction.assert_called_once()
            passed_updates, backup_root = transaction.call_args.args
            self.assertEqual(
                tuple(update.path for update in passed_updates),
                (
                    home / "config.toml",
                    home / "AGENTS.md",
                    *(home / "agents" / f"{name}.toml" for name in ROLE_NAMES),
                ),
            )
            self.assertEqual(backup_root, home / "backups")
            self.assertIn("replace", transaction.call_args.kwargs)
            self.assertTrue(result.applied)
            self.assertEqual(result.manifest_path, manifest)

    def test_validation_is_redacted_and_detects_changed_managed_content(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = self.make_home(raw, target="windows")
            (home / "config.toml").write_text(
                '[mcp_servers.keep]\ntoken = "secret-token-value"\n',
                encoding="utf-8",
            )
            install_global(home, "windows", SOURCE_ROOT, apply=True)

            report = validate_global_install(home, "windows", SOURCE_ROOT)
            self.assertTrue(report.valid)
            self.assertEqual(report.unrelated_table_names, ("mcp_servers",))
            self.assertNotIn("secret-token-value", repr(report))

            (home / "agents" / "worker.toml").write_text(
                "changed", encoding="utf-8"
            )
            self.assertFalse(
                validate_global_install(home, "windows", SOURCE_ROOT).valid
            )

            config_path = home / "config.toml"
            config_path.write_text(
                config_path.read_text(encoding="utf-8").replace(
                    'model = "gpt-6-sol"',
                    'model = "secret-token-value"',
                ),
                encoding="utf-8",
            )
            changed_config_report = validate_global_install(
                home, "windows", SOURCE_ROOT
            )
            self.assertFalse(changed_config_report.valid)
            self.assertNotIn("secret-token-value", repr(changed_config_report))

    def test_validation_requires_exact_owned_toml_types(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            home = self.make_home(raw)
            install_global(home, "wsl", SOURCE_ROOT, apply=True)
            config = home / "config.toml"
            approved = config.read_text(encoding="utf-8")

            self.assertTrue(validate_global_install(home, "wsl", SOURCE_ROOT).valid)
            for label, before, impostor in (
                ("integer for boolean", "enabled = true", "enabled = 1"),
                ("float for boolean", "interrupt_message = true", "interrupt_message = 1.0"),
                (
                    "boolean for integer",
                    "max_concurrent_threads_per_session = 2",
                    "max_concurrent_threads_per_session = true",
                ),
                (
                    "float for integer",
                    "max_concurrent_threads_per_session = 2",
                    "max_concurrent_threads_per_session = 1.0",
                ),
            ):
                with self.subTest(impostor=label):
                    self.assertIn(before, approved)
                    config.write_text(
                        approved.replace(before, impostor), encoding="utf-8"
                    )
                    self.assertFalse(
                        validate_global_install(home, "wsl", SOURCE_ROOT).valid
                    )
            config.write_text(approved, encoding="utf-8")
            self.assertTrue(validate_global_install(home, "wsl", SOURCE_ROOT).valid)


if __name__ == "__main__":
    unittest.main()
