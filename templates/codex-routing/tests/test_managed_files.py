import errno
import hashlib
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from codex_routing.errors import RoutingConfigError
from codex_routing.managed_files import (
    FileUpdate,
    apply_transaction,
    merge_managed_block,
    rollback_transaction,
)
from codex_routing.validate import plan_rollback


BEGIN = b"<!-- BEGIN CODEX ROUTING -->"
END = b"<!-- END CODEX ROUTING -->"


class ManagedFilesTests(unittest.TestCase):
    def assert_no_temporary_files(self, root: Path) -> None:
        self.assertEqual(list(root.rglob("*.tmp")), [])

    def test_rollback_rejects_cross_platform_backup_paths_before_writes(self) -> None:
        paths = (
            r"files/..\..\outside.bak",
            r"files/C:\outside.bak",
            r"files/C:outside.bak",
            r"files/\outside.bak",
            r"files/\\server\share\outside.bak",
            "files/../outside.bak",
            "/files/0000.bak",
            "files/0000.bak:stream",
            "files/0000.bak\x00",
            "files/",
            "files/.",
            "files/..",
        )
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            destination = root / "config.toml"
            destination.write_bytes(b"before\n")
            result = apply_transaction(
                (FileUpdate(destination, b"installed\n"),), root / "backups"
            )
            manifest = json.loads(result.manifest_path.read_bytes())
            original = result.manifest_path.read_bytes()
            for relative in paths:
                with self.subTest(path=relative):
                    manifest["files"][0]["backup_path"] = relative
                    result.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                    with self.assertRaisesRegex(RoutingConfigError, "backup path escapes"):
                        plan_rollback(result.manifest_path)
                    with mock.patch("codex_routing.managed_files._prepare_stage") as stage:
                        with self.assertRaisesRegex(RoutingConfigError, "backup path escapes"):
                            rollback_transaction(result.manifest_path)
                        stage.assert_not_called()
                    self.assertEqual(destination.read_bytes(), b"installed\n")
                    self.assert_no_temporary_files(root)
            result.manifest_path.write_bytes(original)
            self.assertEqual(plan_rollback(result.manifest_path).destinations, (destination,))
            rollback_transaction(result.manifest_path)
            self.assertEqual(destination.read_bytes(), b"before\n")

    def test_second_publish_failure_restores_first_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            first = root / "config.toml"
            second = root / "AGENTS.md"
            first.write_bytes(b"before-config\n")
            second.write_bytes(b"before-agents\n")
            calls = 0

            def fail_second(source: Path, destination: Path) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected publish failure")
                source.replace(destination)

            updates = (
                FileUpdate(first, b"after-config\n"),
                FileUpdate(second, b"after-agents\n"),
            )
            with self.assertRaisesRegex(Exception, "publish failure"):
                apply_transaction(updates, root / "backups", replace=fail_second)
            self.assertEqual(first.read_bytes(), b"before-config\n")
            self.assertEqual(second.read_bytes(), b"before-agents\n")
            self.assert_no_temporary_files(root)

    def test_incomplete_recovery_preserves_manifest_and_failure_status(self) -> None:
        for failure_point in ("second-file", "published-manifest"):
            with self.subTest(failure_point=failure_point), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                first, second = root / "a.toml", root / "b.toml"
                first.write_bytes(b"before-a")
                second.write_bytes(b"before-b")

                def fail_publish_and_recovery(source: Path, destination: Path) -> None:
                    if destination == first and "rollback" in source.name:
                        raise OSError("injected recovery failure")
                    if failure_point == "second-file" and destination == second:
                        raise OSError("injected publication failure")
                    source.replace(destination)
                    if failure_point == "published-manifest" and destination.name == "manifest.json":
                        raise OSError("injected manifest publication failure")

                with self.assertRaises(RoutingConfigError) as caught:
                    apply_transaction(
                        (FileUpdate(first, b"after-a"), FileUpdate(second, b"after-b")),
                        root / "backups", replace=fail_publish_and_recovery,
                    )

                transaction = next((root / "backups").iterdir())
                manifest_name = "manifest.pending.json" if failure_point == "second-file" else "manifest.json"
                manifest = transaction / manifest_name
                self.assertIn(str(transaction), str(caught.exception))
                self.assertIn("recovery incomplete", str(caught.exception))
                self.assertEqual(plan_rollback(manifest).destinations, (first, second))
                for record in json.loads(manifest.read_bytes())["files"]:
                    prior = (transaction / record["backup_path"]).read_bytes()
                    self.assertEqual(hashlib.sha256(prior).hexdigest(), record["prior_sha256"])
                    self.assertEqual(prior, b"before-a" if record["path"] == str(first) else b"before-b")
                status = json.loads((transaction / "recovery-required.json").read_bytes())
                self.assertEqual(status["status"], "incomplete")
                self.assertIn("injected recovery failure", status["rollback_errors"][0])
                # A mixed transaction needs reconciliation; it cannot be blindly rerun.
                with self.assertRaisesRegex(RoutingConfigError, "digest mismatch"):
                    rollback_transaction(manifest)
                self.assertEqual(first.read_bytes(), b"after-a")
                self.assertEqual(second.read_bytes(), b"before-b")
                self.assert_no_temporary_files(root)

    def test_automatic_recovery_preserves_same_digest_foreign_replacement(self) -> None:
        cases = ((True, "between-records"), (False, "between-records"), (True, "staging"))
        for prior_exists, timing in cases:
            with self.subTest(prior_exists=prior_exists, timing=timing), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                first, second = root / "a.toml", root / "b.toml"
                if prior_exists:
                    first.write_bytes(b"before-a")
                second.write_bytes(b"before-b")
                module = __import__("codex_routing.managed_files", fromlist=["_prepare_stage"])
                real_prepare = module._prepare_stage
                foreign_state = None

                def rebind_first() -> None:
                    nonlocal foreign_state
                    foreign = root / "foreign.toml"
                    foreign.write_bytes(b"installed-a")
                    foreign.replace(first)
                    foreign_state = module._stat_identity(first.stat())

                def race_after_staging(path: Path, payload: bytes, purpose: str):
                    stage = real_prepare(path, payload, purpose)
                    if timing == "staging" and path == first and purpose == "rollback":
                        rebind_first()
                    return stage

                def fail_manifest(source: Path, destination: Path) -> None:
                    if destination.name == "manifest.json":
                        raise OSError("injected manifest failure")
                    source.replace(destination)
                    if timing == "between-records" and destination == second and "rollback" in source.name:
                        rebind_first()

                with mock.patch.object(module, "_prepare_stage", side_effect=race_after_staging):
                    with self.assertRaisesRegex(RoutingConfigError, "recovery incomplete"):
                        apply_transaction(
                            (FileUpdate(first, b"installed-a"), FileUpdate(second, b"installed-b")),
                            root / "backups", replace=fail_manifest,
                        )

                self.assertEqual(first.read_bytes(), b"installed-a")
                self.assertEqual(module._stat_identity(first.stat()), foreign_state)
                self.assertEqual(second.read_bytes(), b"before-b")
                manifest = next((root / "backups").rglob("manifest.pending.json"))
                self.assertEqual(plan_rollback(manifest).destinations, (first, second))
                self.assertTrue((manifest.parent / "recovery-required.json").is_file())
                self.assert_no_temporary_files(root)

    @unittest.skipIf(os.name == "nt", "directory permission identity is POSIX-specific")
    def test_automatic_recovery_rechecks_parent_after_staging(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            parent = root / "owned"
            parent.mkdir(mode=0o755)
            destination = parent / "config.toml"
            destination.write_bytes(b"before")
            module = __import__("codex_routing.managed_files", fromlist=["_prepare_stage"])
            real_prepare = module._prepare_stage

            def change_parent(path: Path, payload: bytes, purpose: str):
                stage = real_prepare(path, payload, purpose)
                if purpose == "rollback":
                    parent.chmod(0o700)
                return stage

            def fail_manifest(source: Path, target: Path) -> None:
                if target.name == "manifest.json":
                    raise OSError("injected manifest failure")
                source.replace(target)

            with mock.patch.object(module, "_prepare_stage", side_effect=change_parent):
                with self.assertRaisesRegex(RoutingConfigError, "parent changed during transaction"):
                    apply_transaction(
                        (FileUpdate(destination, b"installed"),), root / "backups",
                        replace=fail_manifest,
                    )
            self.assertEqual(destination.read_bytes(), b"installed")
            self.assertTrue(list((root / "backups").rglob("recovery-required.json")))
            self.assert_no_temporary_files(root)

    def test_automatic_recovery_validates_all_restored_results_before_removing_evidence(self) -> None:
        for change in ("rewrite", "same-digest-rebind", "recreate", "during-cleanup"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                first, second = root / "a.toml", root / "b.toml"
                first.write_bytes(b"before-a")
                if change != "recreate":
                    second.write_bytes(b"before-b")
                module = __import__("codex_routing.managed_files", fromlist=["_remove_owned_stage"])
                real_remove = module._remove_owned_stage
                foreign = b"before-b" if change == "same-digest-rebind" else b"foreign-edit"
                restored = False

                def change_second() -> None:
                    if change == "rewrite":
                        second.write_bytes(foreign)
                        return
                    replacement = root / "foreign.toml"
                    replacement.write_bytes(foreign)
                    replacement.replace(second)

                def fail_manifest(source: Path, target: Path) -> None:
                    nonlocal restored
                    if target.name == "manifest.json":
                        raise OSError("injected manifest failure")
                    source.replace(target)
                    if target == first and "rollback" in source.name:
                        restored = True
                        if change != "during-cleanup":
                            change_second()

                def race_during_cleanup(owned) -> None:
                    real_remove(owned)
                    if change == "during-cleanup" and restored and "install" in owned.path.name:
                        change_second()

                with mock.patch.object(module, "_remove_owned_stage", side_effect=race_during_cleanup):
                    with self.assertRaisesRegex(RoutingConfigError, "final recovery validation failed"):
                        apply_transaction(
                            (FileUpdate(first, b"installed-a"), FileUpdate(second, b"installed-b")),
                            root / "backups", replace=fail_manifest,
                        )
                self.assertEqual(first.read_bytes(), b"before-a")
                self.assertEqual(second.read_bytes(), foreign)
                manifest = next((root / "backups").rglob("manifest.pending.json"))
                self.assertEqual(plan_rollback(manifest).destinations, (first, second))
                status = json.loads((manifest.parent / "recovery-required.json").read_bytes())
                self.assertEqual(status["status"], "incomplete")
                self.assertIn("final recovery validation failed", status["rollback_errors"][0])
                for record in json.loads(manifest.read_bytes())["files"]:
                    if record["prior_exists"]:
                        backup = (manifest.parent / record["backup_path"]).read_bytes()
                        self.assertEqual(hashlib.sha256(backup).hexdigest(), record["prior_sha256"])
                self.assert_no_temporary_files(root)

    def test_recovery_status_write_failure_still_preserves_original_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            destination = root / "config.toml"
            destination.write_bytes(b"before")
            module = __import__("codex_routing.managed_files", fromlist=["_write_exclusive"])
            real_write = module._write_exclusive

            def fail_status(path: Path, payload: bytes):
                if path.name == "recovery-required.json":
                    raise OSError("status storage unavailable")
                return real_write(path, payload)

            def fail_after_publish(source: Path, target: Path) -> None:
                if "rollback" in source.name:
                    raise OSError("recovery unavailable")
                source.replace(target)
                raise OSError("publication failed after replacement")

            with mock.patch("codex_routing.managed_files._write_exclusive", side_effect=fail_status):
                with self.assertRaisesRegex(RoutingConfigError, "status storage unavailable"):
                    apply_transaction(
                        (FileUpdate(destination, b"after"),), root / "backups",
                        replace=fail_after_publish,
                    )
            manifest = next((root / "backups").rglob("manifest.pending.json"))
            self.assertEqual(plan_rollback(manifest).destinations, (destination,))
            self.assertEqual(destination.read_bytes(), b"after")

    def test_manifest_publish_then_raise_removes_owned_manifest_and_restores_files(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            first = root / "config.toml"
            second = root / "AGENTS.md"
            first.write_bytes(b"before-config\n")
            backup_root = root / "backups"

            def publish_manifest_then_raise(source: Path, destination: Path) -> None:
                source.replace(destination)
                if destination.name == "manifest.json":
                    raise OSError("injected post-publish manifest failure")

            with self.assertRaisesRegex(RoutingConfigError, "post-publish manifest"):
                apply_transaction(
                    (
                        FileUpdate(first, b"after-config\n"),
                        FileUpdate(second, b"after-agents\n"),
                    ),
                    backup_root,
                    replace=publish_manifest_then_raise,
                )

            self.assertEqual(first.read_bytes(), b"before-config\n")
            self.assertFalse(second.exists())
            self.assertFalse(list(backup_root.rglob("manifest.json")))
            self.assertFalse(list(backup_root.rglob("manifest.pending.json")))
            self.assert_no_temporary_files(root)

    def test_manifest_publish_then_foreign_rebind_preserves_foreign_manifest(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            destination = root / "config.toml"
            destination.write_bytes(b"before\n")
            backup_root = root / "backups"
            foreign = b"foreign manifest\n"

            def publish_then_rebind_foreign(source: Path, target: Path) -> None:
                source.replace(target)
                if target.name == "manifest.json":
                    target.unlink()
                    target.write_bytes(foreign)
                    raise OSError("injected foreign manifest rebind")

            with self.assertRaisesRegex(RoutingConfigError, "foreign manifest rebind"):
                apply_transaction(
                    (FileUpdate(destination, b"installed\n"),),
                    backup_root,
                    replace=publish_then_rebind_foreign,
                )

            manifests = list(backup_root.rglob("manifest.json"))
            self.assertEqual(destination.read_bytes(), b"before\n")
            self.assertEqual(len(manifests), 1)
            self.assertEqual(manifests[0].read_bytes(), foreign)
            self.assertFalse(list(backup_root.rglob("manifest.pending.json")))
            self.assert_no_temporary_files(root)

    def test_manifest_publish_then_same_inode_rewrite_preserves_foreign_bytes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            destination = root / "config.toml"
            destination.write_bytes(b"before\n")
            backup_root = root / "backups"
            foreign = b"foreign manifest rewritten in place\n"
            rewrite_kept_inode = False

            def publish_then_rewrite_in_place(source: Path, target: Path) -> None:
                nonlocal rewrite_kept_inode
                source.replace(target)
                if target.name == "manifest.json":
                    published_inode = target.stat().st_ino
                    target.write_bytes(foreign)
                    rewrite_kept_inode = target.stat().st_ino == published_inode
                    raise OSError("injected same-inode manifest rewrite")

            with self.assertRaises(RoutingConfigError) as caught:
                apply_transaction(
                    (FileUpdate(destination, b"installed\n"),),
                    backup_root,
                    replace=publish_then_rewrite_in_place,
                )

            manifests = list(backup_root.rglob("manifest.json"))
            message = str(caught.exception)
            self.assertIn("injected same-inode manifest rewrite", message)
            self.assertIn("owned temporary path content changed", message)
            self.assertTrue(rewrite_kept_inode)
            self.assertEqual(destination.read_bytes(), b"before\n")
            self.assertEqual(len(manifests), 1)
            self.assertEqual(manifests[0].read_bytes(), foreign)
            self.assertFalse(list(backup_root.rglob("manifest.pending.json")))
            self.assert_no_temporary_files(root)

    def test_apply_failure_never_restores_an_unattempted_matching_path(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            first = root / "a.toml"
            second = root / "b.md"
            third = root / "c.toml"
            first.write_bytes(b"before-a\n")
            second.write_bytes(b"before-b\n")
            third.write_bytes(b"before-c\n")

            def fail_second_after_concurrent_third_change(
                source: Path, destination: Path
            ) -> None:
                if destination == second:
                    third.write_bytes(b"installed-c\n")
                    raise OSError("injected second publish failure")
                source.replace(destination)

            with self.assertRaisesRegex(RoutingConfigError, "second publish failure"):
                apply_transaction(
                    (
                        FileUpdate(first, b"installed-a\n"),
                        FileUpdate(second, b"installed-b\n"),
                        FileUpdate(third, b"installed-c\n"),
                    ),
                    root / "backups",
                    replace=fail_second_after_concurrent_third_change,
                )

            self.assertEqual(first.read_bytes(), b"before-a\n")
            self.assertEqual(second.read_bytes(), b"before-b\n")
            self.assertEqual(third.read_bytes(), b"installed-c\n")
            self.assert_no_temporary_files(root)

    def test_stage_creation_is_exclusive_and_preserves_a_foreign_collision(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            destination = root / "config.toml"
            collision = root / ".config.toml.codex-routing-foreign.tmp"
            stage = root / ".config.toml.codex-routing-owned.tmp"
            collision.write_bytes(b"foreign-temp\n")

            with mock.patch(
                "codex_routing.managed_files._stage_candidate",
                side_effect=(collision, stage),
            ):
                result = apply_transaction(
                    (FileUpdate(destination, b"installed\n"),), root / "backups"
                )

            self.assertEqual(result.changed_paths, (destination,))
            self.assertEqual(destination.read_bytes(), b"installed\n")
            self.assertEqual(collision.read_bytes(), b"foreign-temp\n")
            self.assertFalse(stage.exists())
            self.assertEqual(list(root.rglob("*.tmp")), [collision])

    def test_stage_replaced_after_write_is_never_adopted_or_published(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            destination = root / "config.toml"
            destination.write_bytes(b"before\n")
            stage = root / ".config.toml.codex-routing-install-fixed.tmp"
            module = __import__("codex_routing.managed_files", fromlist=["_assert_owned_payload"])
            real_assert = module._assert_owned_payload

            def replace_stage(owned, phase: str) -> None:
                if owned.path == stage and phase == "write":
                    foreign = root / "foreign.tmp"
                    foreign.write_bytes(b"foreign-stage\n")
                    foreign.replace(stage)
                real_assert(owned, phase)

            with (
                mock.patch(
                    "codex_routing.managed_files._stage_candidate",
                    return_value=stage,
                ),
                mock.patch(
                    "codex_routing.managed_files._assert_owned_payload",
                    side_effect=replace_stage,
                ),
            ):
                with self.assertRaisesRegex(RoutingConfigError, "changed during write"):
                    apply_transaction(
                        (FileUpdate(destination, b"installed\n"),), root / "backups"
                    )

            self.assertEqual(destination.read_bytes(), b"before\n")
            self.assertEqual(stage.read_bytes(), b"foreign-stage\n")

    def test_backup_replaced_after_write_is_never_adopted(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            destination = root / "config.toml"
            destination.write_bytes(b"before\n")
            backup_root = root / "backups"
            module = __import__("codex_routing.managed_files", fromlist=["_assert_owned_payload"])
            real_assert = module._assert_owned_payload
            replacement: Path | None = None

            def replace_backup(owned, phase: str) -> None:
                nonlocal replacement
                if phase == "write" and owned.path.suffix == ".bak" and replacement is None:
                    replacement = owned.path
                    foreign = root / "foreign.tmp"
                    foreign.write_bytes(b"foreign-backup\n")
                    foreign.replace(replacement)
                real_assert(owned, phase)

            with mock.patch(
                "codex_routing.managed_files._assert_owned_payload",
                side_effect=replace_backup,
            ):
                with self.assertRaisesRegex(RoutingConfigError, "changed during write"):
                    apply_transaction(
                        (FileUpdate(destination, b"installed\n"),), backup_root
                    )

            self.assertEqual(destination.read_bytes(), b"before\n")
            self.assertIsNotNone(replacement)
            assert replacement is not None
            self.assertEqual(replacement.read_bytes(), b"foreign-backup\n")

    def test_pending_manifest_replaced_after_write_is_never_adopted(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            destination = root / "new.toml"
            backup_root = root / "backups"
            module = __import__("codex_routing.managed_files", fromlist=["_assert_owned_payload"])
            real_assert = module._assert_owned_payload
            replacement: Path | None = None

            def replace_pending_manifest(owned, phase: str) -> None:
                nonlocal replacement
                if phase == "write" and owned.path.name == "manifest.pending.json" and replacement is None:
                    replacement = owned.path
                    foreign = root / "foreign.tmp"
                    foreign.write_bytes(b"foreign-manifest\n")
                    foreign.replace(replacement)
                real_assert(owned, phase)

            with mock.patch(
                "codex_routing.managed_files._assert_owned_payload",
                side_effect=replace_pending_manifest,
            ):
                with self.assertRaisesRegex(RoutingConfigError, "changed during write"):
                    apply_transaction(
                        (FileUpdate(destination, b"installed\n"),), backup_root
                    )

            self.assertFalse(destination.exists())
            self.assertIsNotNone(replacement)
            assert replacement is not None
            self.assertEqual(replacement.read_bytes(), b"foreign-manifest\n")

    def test_symlink_destination_is_refused_without_touching_its_target(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target = root / "target.toml"
            target.write_bytes(b"target\n")
            destination = root / "config.toml"
            try:
                destination.symlink_to(target)
            except OSError as exc:
                if os.name == "nt" and getattr(exc, "winerror", None) == 1314:
                    self.skipTest("Windows symlink privilege is unavailable")
                raise

            with self.assertRaisesRegex(RoutingConfigError, "symlink|reparse"):
                apply_transaction(
                    (FileUpdate(destination, b"installed\n"),), root / "backups"
                )

            self.assertEqual(target.read_bytes(), b"target\n")

    def test_reparse_destination_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            destination = root / "config.toml"
            destination.write_bytes(b"before\n")
            real_lstat = Path.lstat
            original = real_lstat(destination)
            flagged = SimpleNamespace(
                st_mode=original.st_mode,
                st_file_attributes=getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400),
            )

            def lstat_with_reparse(path: Path):
                return flagged if path == destination else real_lstat(path)

            with mock.patch(
                "codex_routing.managed_files._lstat", side_effect=lstat_with_reparse
            ):
                with self.assertRaisesRegex(RoutingConfigError, "symlink|reparse"):
                    apply_transaction(
                        (FileUpdate(destination, b"installed\n"),), root / "backups"
                    )

            self.assertEqual(destination.read_bytes(), b"before\n")

    def test_directory_destination_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            destination = root / "config.toml"
            destination.mkdir()

            with self.assertRaisesRegex(RoutingConfigError, "regular file"):
                apply_transaction(
                    (FileUpdate(destination, b"installed\n"),), root / "backups"
                )

    def test_manifest_json_is_exact_and_deterministically_ordered(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            existing = root / "z-existing.toml"
            created = root / "a-created.md"
            existing.write_bytes(b"before\n")

            with (
                mock.patch(
                    "codex_routing.managed_files._utc_timestamp",
                    return_value="2026-08-18T01:02:03Z",
                ),
                mock.patch(
                    "codex_routing.managed_files._platform_name",
                    return_value="test-platform",
                ),
            ):
                result = apply_transaction(
                    (
                        FileUpdate(existing, b"after\n"),
                        FileUpdate(created, b"created\n"),
                    ),
                    root / "backups",
                )

            expected = {
                "created_at": "2026-08-18T01:02:03Z",
                "files": [
                    {
                        "backup_path": None,
                        "installed_sha256": hashlib.sha256(b"created\n").hexdigest(),
                        "path": str(created),
                        "prior_exists": False,
                        "prior_sha256": None,
                    },
                    {
                        "backup_path": "files/0001.bak",
                        "installed_sha256": hashlib.sha256(b"after\n").hexdigest(),
                        "path": str(existing),
                        "prior_exists": True,
                        "prior_sha256": hashlib.sha256(b"before\n").hexdigest(),
                    },
                ],
                "platform": "test-platform",
                "schema": 1,
            }
            expected_bytes = (
                json.dumps(expected, indent=2, sort_keys=True, separators=(",", ": "))
                + "\n"
            ).encode("utf-8")
            self.assertEqual(result.manifest_path.read_bytes(), expected_bytes)
            self.assertEqual(result.changed_paths, (created, existing))

    def test_write_failure_preserves_unverified_owned_stage(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            destination = root / "config.toml"
            module = __import__("codex_routing.managed_files", fromlist=["_write_fd"])
            real_write = module._write_fd
            calls = 0

            def fail_stage_write(fd: int, payload: bytes) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected write failure")
                real_write(fd, payload)

            with mock.patch(
                "codex_routing.managed_files._write_fd", side_effect=fail_stage_write
            ):
                with self.assertRaisesRegex(
                    RoutingConfigError,
                    "owned temporary path content changed",
                ):
                    apply_transaction(
                        (FileUpdate(destination, b"installed\n"),), root / "backups"
                    )

            self.assertFalse(destination.exists())
            stages = list(root.rglob("*.tmp"))
            self.assertEqual(len(stages), 1)
            self.assertEqual(stages[0].read_bytes(), b"")

    def test_fsync_failure_keeps_destination_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            destination = root / "config.toml"
            destination.write_bytes(b"before\n")

            with mock.patch(
                "codex_routing.managed_files.os.fsync",
                side_effect=OSError("injected fsync failure"),
            ):
                with self.assertRaisesRegex(RoutingConfigError, "fsync failure"):
                    apply_transaction(
                        (FileUpdate(destination, b"installed\n"),), root / "backups"
                    )

            self.assertEqual(destination.read_bytes(), b"before\n")
            self.assert_no_temporary_files(root)

    @unittest.skipIf(os.name == "nt", "directory fsync is POSIX-specific")
    def test_directory_fsync_propagates_permission_errors_on_posix(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            module = __import__(
                "codex_routing.managed_files", fromlist=["_fsync_directory"]
            )
            with mock.patch(
                "codex_routing.managed_files.os.open",
                side_effect=PermissionError(errno.EACCES, "permission denied"),
            ):
                with self.assertRaises(PermissionError):
                    module._fsync_directory(Path(raw))

    @unittest.skipIf(os.name == "nt", "directory fsync is POSIX-specific")
    def test_directory_fsync_ignores_only_unsupported_posix_fsync(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            module = __import__(
                "codex_routing.managed_files", fromlist=["_fsync_directory"]
            )
            with mock.patch(
                "codex_routing.managed_files.os.fsync",
                side_effect=OSError(errno.EINVAL, "directory fsync unsupported"),
            ):
                module._fsync_directory(Path(raw))

    def test_publication_order_is_sorted_by_destination_path(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            first = root / "a.md"
            second = root / "z.toml"
            published: list[Path] = []

            def record_replace(source: Path, destination: Path) -> None:
                if destination in (first, second):
                    published.append(destination)
                source.replace(destination)

            apply_transaction(
                (
                    FileUpdate(second, b"second\n"),
                    FileUpdate(first, b"first\n"),
                ),
                root / "backups",
                replace=record_replace,
            )

            self.assertEqual(published, [first, second])

    def test_replace_callback_that_does_not_publish_is_refused_and_cleaned(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            destination = root / "config.toml"
            destination.write_bytes(b"before\n")

            def no_op_replace(source: Path, target: Path) -> None:
                del source, target

            with self.assertRaisesRegex(RoutingConfigError, "did not install"):
                apply_transaction(
                    (FileUpdate(destination, b"installed\n"),),
                    root / "backups",
                    replace=no_op_replace,
                )

            self.assertEqual(destination.read_bytes(), b"before\n")
            self.assert_no_temporary_files(root)

    def test_idempotent_apply_publishes_no_destination(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            destination = root / "config.toml"
            destination.write_bytes(b"same\n")
            destination_replaces: list[Path] = []

            def record_replace(source: Path, target: Path) -> None:
                if target == destination:
                    destination_replaces.append(target)
                source.replace(target)

            result = apply_transaction(
                (FileUpdate(destination, b"same\n"),),
                root / "backups",
                replace=record_replace,
            )

            self.assertEqual(result.changed_paths, ())
            self.assertEqual(destination_replaces, [])
            self.assertEqual(destination.read_bytes(), b"same\n")
            self.assertIsNone(result.manifest_path)
            self.assertFalse((root / "backups").exists())

    def test_no_op_apply_rechecks_captured_bytes_without_creating_backups(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            destination = root / "config.toml"
            destination.write_bytes(b"same")
            module = __import__("codex_routing.managed_files", fromlist=["_revalidate_updates"])
            real_revalidate = module._revalidate_updates

            def change_before_revalidation(records):
                destination.write_bytes(b"foreign")
                real_revalidate(records)

            with mock.patch("codex_routing.managed_files._revalidate_updates", side_effect=change_before_revalidation):
                with self.assertRaisesRegex(RoutingConfigError, "changed during transaction"):
                    apply_transaction((FileUpdate(destination, b"same"),), root / "backups")
            self.assertEqual(destination.read_bytes(), b"foreign")
            self.assertFalse((root / "backups").exists())

    def test_no_op_destination_race_is_revalidated_before_publication(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            unchanged = root / "a.toml"
            changed = root / "b.md"
            unchanged.write_bytes(b"same\n")
            changed.write_bytes(b"before\n")
            module = __import__(
                "codex_routing.managed_files", fromlist=["_prepare_stage"]
            )
            real_prepare = module._prepare_stage
            raced = False

            def race_no_op(path: Path, payload: bytes, purpose: str):
                nonlocal raced
                stage = real_prepare(path, payload, purpose)
                if purpose == "install" and not raced:
                    raced = True
                    unchanged.write_bytes(b"foreign-no-op\n")
                return stage

            with mock.patch(
                "codex_routing.managed_files._prepare_stage",
                side_effect=race_no_op,
            ):
                with self.assertRaisesRegex(RoutingConfigError, "changed during transaction"):
                    apply_transaction(
                        (
                            FileUpdate(unchanged, b"same\n"),
                            FileUpdate(changed, b"installed\n"),
                        ),
                        root / "backups",
                    )

            self.assertEqual(unchanged.read_bytes(), b"foreign-no-op\n")
            self.assertEqual(changed.read_bytes(), b"before\n")
            self.assert_no_temporary_files(root)

    def test_destination_identity_change_before_publish_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            destination = root / "config.toml"
            destination.write_bytes(b"before\n")
            module = __import__(
                "codex_routing.managed_files", fromlist=["_prepare_stage"]
            )
            real_prepare = module._prepare_stage
            replaced = False

            def replace_destination_after_staging(path: Path, payload: bytes, purpose: str):
                nonlocal replaced
                prepared = real_prepare(path, payload, purpose)
                if purpose == "install" and not replaced:
                    replaced = True
                    path.unlink()
                    path.write_bytes(b"foreign\n")
                return prepared

            with mock.patch(
                "codex_routing.managed_files._prepare_stage",
                side_effect=replace_destination_after_staging,
            ):
                with self.assertRaisesRegex(RoutingConfigError, "changed during transaction"):
                    apply_transaction(
                        (FileUpdate(destination, b"installed\n"),), root / "backups"
                    )

            self.assertEqual(destination.read_bytes(), b"foreign\n")
            self.assert_no_temporary_files(root)

    @unittest.skipIf(os.name == "nt", "directory permission identity is POSIX-specific")
    def test_parent_change_before_publish_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            parent = root / "owned"
            parent.mkdir(mode=0o755)
            destination = parent / "config.toml"
            destination.write_bytes(b"before\n")
            module = __import__(
                "codex_routing.managed_files", fromlist=["_prepare_stage"]
            )
            real_prepare = module._prepare_stage
            changed = False

            def chmod_parent_after_staging(path: Path, payload: bytes, purpose: str):
                nonlocal changed
                prepared = real_prepare(path, payload, purpose)
                if purpose == "install" and not changed:
                    changed = True
                    parent.chmod(0o700)
                return prepared

            with mock.patch(
                "codex_routing.managed_files._prepare_stage",
                side_effect=chmod_parent_after_staging,
            ):
                with self.assertRaisesRegex(RoutingConfigError, "parent changed"):
                    apply_transaction(
                        (FileUpdate(destination, b"installed\n"),), root / "backups"
                    )

            self.assertEqual(destination.read_bytes(), b"before\n")
            self.assert_no_temporary_files(root)

    def test_rollback_removes_only_an_unchanged_newly_created_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            destination = root / "new.md"
            result = apply_transaction(
                (FileUpdate(destination, b"installed\n"),), root / "backups"
            )

            rolled_back = rollback_transaction(result.manifest_path)

            self.assertEqual(rolled_back, (destination,))
            self.assertFalse(destination.exists())
            self.assert_no_temporary_files(root)

    def test_rollback_restores_exact_prior_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            destination = root / "config.toml"
            destination.write_bytes(b"prior\x00bytes\r\n")
            result = apply_transaction(
                (FileUpdate(destination, b"installed\n"),), root / "backups"
            )

            rolled_back = rollback_transaction(result.manifest_path)

            self.assertEqual(rolled_back, (destination,))
            self.assertEqual(destination.read_bytes(), b"prior\x00bytes\r\n")
            self.assert_no_temporary_files(root)

    def test_rollback_preserves_digest_changed_foreign_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            destination = root / "new.md"
            result = apply_transaction(
                (FileUpdate(destination, b"installed\n"),), root / "backups"
            )
            destination.write_bytes(b"foreign-replacement\n")

            with self.assertRaisesRegex(RoutingConfigError, "digest mismatch"):
                rollback_transaction(result.manifest_path)

            self.assertEqual(destination.read_bytes(), b"foreign-replacement\n")

    def test_rollback_publish_failure_reinstalls_already_restored_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            first = root / "a.toml"
            second = root / "b.md"
            first.write_bytes(b"before-a\n")
            second.write_bytes(b"before-b\n")
            result = apply_transaction(
                (
                    FileUpdate(first, b"installed-a\n"),
                    FileUpdate(second, b"installed-b\n"),
                ),
                root / "backups",
            )

            def fail_second_restore(source: Path, destination: Path) -> None:
                if destination == second and "rollback" in source.name:
                    raise OSError("injected rollback publish failure")
                source.replace(destination)

            with self.assertRaisesRegex(RoutingConfigError, "rollback publish failure"):
                rollback_transaction(
                    result.manifest_path, replace=fail_second_restore
                )

            self.assertEqual(first.read_bytes(), b"installed-a\n")
            self.assertEqual(second.read_bytes(), b"installed-b\n")
            self.assert_no_temporary_files(root)

    def test_rollback_publish_then_raise_compensates_current_record(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            destination = root / "config.toml"
            destination.write_bytes(b"before\n")
            result = apply_transaction(
                (FileUpdate(destination, b"installed\n"),), root / "backups"
            )

            def publish_then_raise(source: Path, target: Path) -> None:
                source.replace(target)
                if "rollback" in source.name:
                    raise OSError("injected post-publish rollback failure")

            with self.assertRaisesRegex(
                RoutingConfigError, "post-publish rollback failure"
            ):
                rollback_transaction(
                    result.manifest_path, replace=publish_then_raise
                )

            self.assertEqual(destination.read_bytes(), b"installed\n")
            self.assert_no_temporary_files(root)

    def test_rollback_compensation_preserves_concurrent_destination_changes(self) -> None:
        cases = ((True, "rewrite"), (False, "recreate"), (True, "replace"))
        for prior_exists, change in cases:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                first, second = root / "a.toml", root / "b.toml"
                if prior_exists:
                    first.write_bytes(b"before-a")
                second.write_bytes(b"before-b")
                result = apply_transaction(
                    (FileUpdate(first, b"installed-a"), FileUpdate(second, b"installed-b")),
                    root / "backups",
                )
                module = __import__("codex_routing.managed_files", fromlist=["_prepare_stage"])
                real_prepare = module._prepare_stage
                foreign = b"before-a" if change == "replace" else b"concurrent-edit"
                foreign_state = None

                def race_after_staging(path: Path, payload: bytes, purpose: str):
                    nonlocal foreign_state
                    stage = real_prepare(path, payload, purpose)
                    if path == first and purpose == "compensate":
                        if change == "replace":
                            replacement = root / "foreign.toml"
                            replacement.write_bytes(foreign)
                            replacement.replace(first)
                        else:
                            first.write_bytes(foreign)
                        foreign_state = module._stat_identity(first.stat())
                    return stage

                def fail_second_restore(source: Path, destination: Path) -> None:
                    if destination == second and "rollback" in source.name:
                        raise OSError("injected second rollback failure")
                    source.replace(destination)

                with mock.patch.object(module, "_prepare_stage", side_effect=race_after_staging):
                    with self.assertRaises(RoutingConfigError) as caught:
                        rollback_transaction(result.manifest_path, replace=fail_second_restore)

                message = str(caught.exception)
                self.assertIn("injected second rollback failure", message)
                self.assertIn("destination changed during transaction", message)
                self.assertEqual(first.read_bytes(), foreign)
                self.assertEqual(module._stat_identity(first.stat()), foreign_state)
                self.assertEqual(second.read_bytes(), b"installed-b")
                self.assertTrue(result.manifest_path.is_file())
                self.assert_no_temporary_files(root)

    @unittest.skipIf(os.name == "nt", "directory permission identity is POSIX-specific")
    def test_rollback_compensation_rechecks_parent_after_staging(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            parent = root / "owned"
            parent.mkdir(mode=0o755)
            first, second = parent / "a.toml", parent / "b.toml"
            first.write_bytes(b"before-a")
            second.write_bytes(b"before-b")
            result = apply_transaction(
                (FileUpdate(first, b"installed-a"), FileUpdate(second, b"installed-b")),
                root / "backups",
            )
            module = __import__("codex_routing.managed_files", fromlist=["_prepare_stage"])
            real_prepare = module._prepare_stage

            def change_parent(path: Path, payload: bytes, purpose: str):
                stage = real_prepare(path, payload, purpose)
                if purpose == "compensate":
                    parent.chmod(0o700)
                return stage

            def fail_second_restore(source: Path, destination: Path) -> None:
                if destination == second and "rollback" in source.name:
                    raise OSError("injected second rollback failure")
                source.replace(destination)

            with mock.patch.object(module, "_prepare_stage", side_effect=change_parent):
                with self.assertRaisesRegex(RoutingConfigError, "parent changed during transaction"):
                    rollback_transaction(result.manifest_path, replace=fail_second_restore)

            self.assertEqual(first.read_bytes(), b"before-a")
            self.assertEqual(second.read_bytes(), b"installed-b")
            self.assert_no_temporary_files(root)

    def test_compensation_keeps_original_rollback_identity_between_records(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            first, second, third = (root / name for name in ("a.toml", "b.toml", "c.toml"))
            for path in (first, second, third):
                path.write_bytes(b"before")
            result = apply_transaction(
                tuple(FileUpdate(path, b"installed") for path in (first, second, third)),
                root / "backups",
            )
            module = __import__("codex_routing.managed_files", fromlist=["_prepare_stage"])
            real_prepare = module._prepare_stage
            foreign_state = None

            def replace_first_while_compensating_second(path: Path, payload: bytes, purpose: str):
                nonlocal foreign_state
                stage = real_prepare(path, payload, purpose)
                if path == second and purpose == "compensate":
                    foreign = root / "foreign.toml"
                    foreign.write_bytes(b"before")
                    foreign.replace(first)
                    foreign_state = module._stat_identity(first.stat())
                return stage

            def fail_third_restore(source: Path, destination: Path) -> None:
                if destination == third and "rollback" in source.name:
                    raise OSError("injected third rollback failure")
                source.replace(destination)

            with mock.patch.object(module, "_prepare_stage", side_effect=replace_first_while_compensating_second):
                with self.assertRaises(RoutingConfigError) as caught:
                    rollback_transaction(result.manifest_path, replace=fail_third_restore)

            self.assertIn("injected third rollback failure", str(caught.exception))
            self.assertIn("destination changed during transaction", str(caught.exception))
            self.assertEqual(first.read_bytes(), b"before")
            self.assertEqual(module._stat_identity(first.stat()), foreign_state)
            self.assertEqual(second.read_bytes(), b"installed")
            self.assertEqual(third.read_bytes(), b"installed")
            self.assert_no_temporary_files(root)

    def test_rollback_publish_and_cleanup_failures_are_aggregated(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            destination = root / "config.toml"
            destination.write_bytes(b"before\n")
            result = apply_transaction(
                (FileUpdate(destination, b"installed\n"),), root / "backups"
            )

            def fail_restore(source: Path, target: Path) -> None:
                del source, target
                raise OSError("injected rollback publish failure")

            with mock.patch(
                "codex_routing.managed_files._remove_owned_stage",
                side_effect=OSError("injected rollback cleanup failure"),
            ):
                with self.assertRaises(RoutingConfigError) as caught:
                    rollback_transaction(
                        result.manifest_path, replace=fail_restore
                    )

            message = str(caught.exception)
            self.assertIn("rollback publish failure", message)
            self.assertIn("rollback cleanup failure", message)
            self.assertEqual(destination.read_bytes(), b"installed\n")

    def test_publish_rollback_and_cleanup_failures_are_aggregated(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            first = root / "a.toml"
            second = root / "b.md"
            first.write_bytes(b"before-a\n")
            second.write_bytes(b"before-b\n")

            def fail_publish_and_rollback(source: Path, destination: Path) -> None:
                if destination == second and "rollback" not in source.name:
                    raise OSError("injected publish failure")
                if destination == first and "rollback" in source.name:
                    raise OSError("injected rollback failure")
                source.replace(destination)

            with mock.patch(
                "codex_routing.managed_files._remove_owned_stage",
                side_effect=OSError("injected cleanup failure"),
            ):
                with self.assertRaises(RoutingConfigError) as caught:
                    apply_transaction(
                        (
                            FileUpdate(first, b"after-a\n"),
                            FileUpdate(second, b"after-b\n"),
                        ),
                        root / "backups",
                        replace=fail_publish_and_rollback,
                    )

            message = str(caught.exception)
            self.assertIn("publish failure", message)
            self.assertIn("rollback failure", message)
            self.assertIn("cleanup failure", message)

    def test_merge_managed_block_inserts_replaces_and_removes_owned_text(self) -> None:
        inserted = merge_managed_block(b"heading\n", b"owned\n", BEGIN, END)
        self.assertEqual(
            inserted,
            b"heading\n\n" + BEGIN + b"\nowned\n" + END + b"\n",
        )

        replaced = merge_managed_block(inserted, b"replacement\n", BEGIN, END)
        self.assertEqual(
            replaced,
            b"heading\n\n" + BEGIN + b"\nreplacement\n" + END + b"\n",
        )

        removed = merge_managed_block(replaced + b"\nafter\n", b"", BEGIN, END)
        self.assertEqual(removed, b"heading\n\nafter\n")

    def test_merge_managed_block_preserves_crlf_and_rejects_ambiguous_markers(self) -> None:
        merged = merge_managed_block(b"heading\r\n", b"owned\r\n", BEGIN, END)
        self.assertNotIn(b"\n", merged.replace(b"\r\n", b""))

        with self.assertRaisesRegex(RoutingConfigError, "contains a marker"):
            merge_managed_block(b"", BEGIN, BEGIN, END)
        with self.assertRaisesRegex(RoutingConfigError, "incomplete or duplicated"):
            merge_managed_block(BEGIN + b"\n", b"owned", BEGIN, END)
        with self.assertRaisesRegex(RoutingConfigError, "incomplete or duplicated"):
            merge_managed_block(END + b"\n" + BEGIN, b"owned", BEGIN, END)


if __name__ == "__main__":
    unittest.main()
