from pathlib import Path
from contextlib import redirect_stderr, redirect_stdout
import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parent))
import sync_skills


def make_skill(root: Path, name: str) -> Path:
    skill = root / name
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Use when testing sync.\n---\n",
        encoding="utf-8",
    )
    return skill


class FilesystemCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.codex_source = self.base / "windows-codex"
        self.agents_source = self.base / "windows-agents"
        self.codex_destination = self.base / "wsl-codex"
        self.agents_destination = self.base / "wsl-agents"
        for root in (
            self.codex_source,
            self.agents_source,
            self.codex_destination,
            self.agents_destination,
        ):
            root.mkdir()
        self.scopes = (
            sync_skills.Scope("codex", self.codex_source, self.codex_destination),
            sync_skills.Scope("agents", self.agents_source, self.agents_destination),
        )

    def tearDown(self):
        self.temp.cleanup()


class PortableDefaultsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.windows_profile = self.base / "mnt" / "c" / "Users" / "alice"
        self.wsl_home = self.base / "home" / "bob"
        self.wsl_home.mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def make_script(self, owner: str) -> Path:
        script = (
            self.windows_profile
            / owner
            / "skills"
            / "codex-sync-skills"
            / "scripts"
            / "sync_skills.py"
        )
        script.parent.mkdir(parents=True)
        script.touch()
        return script

    def test_infers_different_windows_and_wsl_user_profiles(self):
        script = self.make_script(".codex")
        roots = sync_skills.infer_default_roots(script, self.wsl_home)
        self.assertEqual(
            roots,
            sync_skills.Roots(
                self.windows_profile / ".codex" / "skills",
                self.windows_profile / ".agents" / "skills",
                self.wsl_home / ".codex" / "skills",
                self.wsl_home / ".agents" / "skills",
            ),
        )

    def test_infers_profile_when_installed_in_agents_scope(self):
        script = self.make_script(".agents")
        roots = sync_skills.infer_default_roots(script, self.wsl_home)
        self.assertEqual(
            roots.windows_codex,
            self.windows_profile / ".codex" / "skills",
        )
        self.assertEqual(
            roots.windows_agents,
            self.windows_profile / ".agents" / "skills",
        )

    def test_main_uses_inferred_roots_without_account_specific_flags(self):
        script = self.make_script(".codex")
        windows_codex = self.windows_profile / ".codex" / "skills"
        windows_agents = self.windows_profile / ".agents" / "skills"
        wsl_codex = self.wsl_home / ".codex" / "skills"
        wsl_agents = self.wsl_home / ".agents" / "skills"
        for root in (windows_codex, windows_agents, wsl_codex, wsl_agents):
            root.mkdir(parents=True, exist_ok=True)
        make_skill(windows_codex, "portable-skill")

        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = sync_skills.main(
                [],
                script_file=script,
                wsl_home=self.wsl_home,
            )

        self.assertEqual(result, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertIn("CREATE\tcodex/portable-skill\t", stdout.getvalue())

    def test_public_files_do_not_pin_a_local_account_or_distribution(self):
        skill_root = Path(__file__).parent.parent
        paths = (skill_root / "SKILL.md", skill_root / "scripts" / "sync_skills.py")
        forbidden = ("Users/admin", "/home/admin", "Ubuntu-24.04")
        for path in paths:
            content = path.read_text(encoding="utf-8")
            for value in forbidden:
                with self.subTest(path=path.name, value=value):
                    self.assertNotIn(value, content)


class DiscoveryTests(FilesystemCase):
    def test_discovers_direct_safe_skill_and_maps_scope(self):
        source = make_skill(self.codex_source, "safe-skill")
        candidates, issues = sync_skills.discover_candidates(self.scopes)
        self.assertEqual(issues, [])
        self.assertEqual(
            candidates,
            {"codex/safe-skill": (source, self.codex_destination / "safe-skill")},
        )

    def test_skips_system_and_directory_without_skill_file(self):
        make_skill(self.codex_source, ".system")
        (self.codex_source / "ordinary-directory").mkdir()
        candidates, issues = sync_skills.discover_candidates(self.scopes)
        self.assertEqual(candidates, {})
        self.assertEqual(issues, [])

    def test_skips_scope_when_both_roots_are_absent(self):
        source = make_skill(self.codex_source, "codex-only-skill")
        self.agents_source.rmdir()
        self.agents_destination.rmdir()

        candidates, issues = sync_skills.discover_candidates(self.scopes)

        self.assertEqual(issues, [])
        self.assertEqual(
            candidates,
            {
                "codex/codex-only-skill": (
                    source,
                    self.codex_destination / "codex-only-skill",
                )
            },
        )

    def test_rejects_unsafe_name(self):
        make_skill(self.codex_source, "Unsafe_Name")
        candidates, issues = sync_skills.discover_candidates(self.scopes)
        self.assertEqual(candidates, {})
        self.assertEqual(
            issues,
            ["REJECTED codex/Unsafe_Name: unsafe skill name"],
        )

    def test_rejects_source_symlink_that_escapes_root(self):
        outside = self.base / "outside"
        outside.mkdir()
        outside_skill = make_skill(outside, "escaped-skill")
        (self.codex_source / "escaped-skill").symlink_to(
            outside_skill,
            target_is_directory=True,
        )
        candidates, issues = sync_skills.discover_candidates(self.scopes)
        self.assertEqual(candidates, {})
        self.assertEqual(
            issues,
            ["REJECTED codex/escaped-skill: source escapes approved root"],
        )


class PlanningTests(FilesystemCase):
    def action_for(self, name: str):
        source = make_skill(self.codex_source, name)
        candidates = {f"codex/{name}": (source, self.codex_destination / name)}
        return sync_skills.plan_actions(candidates)[0]

    def test_missing_destination_is_create(self):
        action = self.action_for("missing-skill")
        self.assertEqual(action.status, "CREATE")
        self.assertEqual(action.detail, "destination is missing")

    def test_expected_symlink_is_unchanged(self):
        source = make_skill(self.codex_source, "linked-skill")
        destination = self.codex_destination / "linked-skill"
        destination.symlink_to(source, target_is_directory=True)
        action = sync_skills.plan_actions(
            {"codex/linked-skill": (source, destination)}
        )[0]
        self.assertEqual(action.status, "UNCHANGED")
        self.assertEqual(action.detail, "link already targets source")

    def test_real_directory_is_conflict(self):
        source = make_skill(self.codex_source, "directory-conflict")
        destination = self.codex_destination / "directory-conflict"
        destination.mkdir()
        action = sync_skills.plan_actions(
            {"codex/directory-conflict": (source, destination)}
        )[0]
        self.assertEqual(action.status, "CONFLICT")
        self.assertEqual(
            action.detail,
            "destination is an existing file or directory",
        )

    def test_wrong_and_broken_symlinks_are_conflicts(self):
        source = make_skill(self.codex_source, "link-conflict")
        for target_name in ("wrong-target", "missing-target"):
            with self.subTest(target_name=target_name):
                destination = self.codex_destination / target_name
                target = self.base / target_name
                if target_name == "wrong-target":
                    target.mkdir()
                destination.symlink_to(target, target_is_directory=True)
                action = sync_skills.plan_actions(
                    {f"codex/{target_name}": (source, destination)}
                )[0]
                self.assertEqual(action.status, "CONFLICT")
                self.assertEqual(
                    action.detail,
                    "link targets a different or missing source",
                )


class ApplyTests(FilesystemCase):
    def root_arguments(self):
        return [
            "--windows-codex-root",
            str(self.codex_source),
            "--windows-agents-root",
            str(self.agents_source),
            "--wsl-codex-root",
            str(self.codex_destination),
            "--wsl-agents-root",
            str(self.agents_destination),
        ]

    def call_main(self, *arguments):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = sync_skills.main([*self.root_arguments(), *arguments])
        return result, stdout.getvalue(), stderr.getvalue()

    def test_preview_does_not_create_missing_link(self):
        make_skill(self.codex_source, "preview-skill")
        result, stdout, stderr = self.call_main()
        self.assertEqual(result, 0)
        self.assertIn("CREATE\tcodex/preview-skill\t", stdout)
        self.assertEqual(stderr, "")
        self.assertFalse(os.path.lexists(self.codex_destination / "preview-skill"))

    def test_apply_creates_only_selected_link(self):
        first = make_skill(self.codex_source, "first-skill")
        make_skill(self.codex_source, "second-skill")
        result, stdout, stderr = self.call_main(
            "--apply", "--skill", "codex/first-skill"
        )
        self.assertEqual(result, 0)
        self.assertIn("UNCHANGED\tcodex/first-skill\t", stdout)
        self.assertEqual(stderr, "")
        self.assertEqual(
            (self.codex_destination / "first-skill").resolve(),
            first.resolve(),
        )
        self.assertFalse(os.path.lexists(self.codex_destination / "second-skill"))

    def test_repeated_apply_is_idempotent(self):
        source = make_skill(self.codex_source, "repeat-skill")
        arguments = ("--apply", "--skill", "codex/repeat-skill")
        first_result, _, _ = self.call_main(*arguments)
        second_result, stdout, _ = self.call_main(*arguments)
        destination = self.codex_destination / "repeat-skill"
        self.assertEqual((first_result, second_result), (0, 0))
        self.assertTrue(destination.is_symlink())
        self.assertEqual(destination.resolve(), source.resolve())
        self.assertIn("link already targets source", stdout)

    def test_conflicts_remain_byte_for_byte_untouched(self):
        make_skill(self.codex_source, "protected-skill")
        destination = self.codex_destination / "protected-skill"
        destination.write_bytes(b"user-owned")
        before_stat = os.lstat(destination)
        before = (
            destination.read_bytes(),
            before_stat.st_mode,
            before_stat.st_ino,
            before_stat.st_size,
        )
        result, stdout, _ = self.call_main(
            "--apply", "--skill", "codex/protected-skill"
        )
        after_stat = os.lstat(destination)
        after = (
            destination.read_bytes(),
            after_stat.st_mode,
            after_stat.st_ino,
            after_stat.st_size,
        )
        self.assertEqual(result, 2)
        self.assertIn("CONFLICT\tcodex/protected-skill\t", stdout)
        self.assertEqual(before, after)

    def test_apply_without_selector_or_all_is_rejected(self):
        make_skill(self.codex_source, "unselected-skill")
        result, _, stderr = self.call_main("--apply")
        self.assertEqual(result, 1)
        self.assertIn("--apply requires --skill or --all", stderr)
        self.assertFalse(
            os.path.lexists(self.codex_destination / "unselected-skill")
        )

    def test_unknown_selector_is_rejected_before_mutation(self):
        make_skill(self.codex_source, "known-skill")
        result, _, stderr = self.call_main(
            "--apply", "--skill", "codex/missing-skill"
        )
        self.assertEqual(result, 1)
        self.assertIn("unknown selector: codex/missing-skill", stderr)
        self.assertFalse(os.path.lexists(self.codex_destination / "known-skill"))

    def test_malformed_selector_is_rejected_before_mutation(self):
        make_skill(self.codex_source, "known-skill")
        result, _, stderr = self.call_main(
            "--apply", "--skill", "missing-scope-separator"
        )
        self.assertEqual(result, 1)
        self.assertIn("invalid selector: missing-scope-separator", stderr)
        self.assertFalse(os.path.lexists(self.codex_destination / "known-skill"))

    def test_missing_root_is_rejected_before_mutation(self):
        make_skill(self.codex_source, "known-skill")
        self.agents_destination.rmdir()
        result, _, stderr = self.call_main()
        self.assertEqual(result, 1)
        self.assertIn(f"missing root: {self.agents_destination}", stderr)
        self.assertFalse(os.path.lexists(self.codex_destination / "known-skill"))

    def test_apply_processes_safe_items_but_returns_conflict(self):
        safe_source = make_skill(self.codex_source, "safe-skill")
        make_skill(self.codex_source, "conflicting-skill")
        conflict = self.codex_destination / "conflicting-skill"
        conflict.write_bytes(b"preserve-me")
        result, stdout, _ = self.call_main("--apply", "--all")
        self.assertEqual(result, 2)
        self.assertEqual(conflict.read_bytes(), b"preserve-me")
        self.assertEqual(
            (self.codex_destination / "safe-skill").resolve(),
            safe_source.resolve(),
        )
        self.assertIn("CONFLICT\tcodex/conflicting-skill\t", stdout)

    def test_all_selects_every_discovered_candidate(self):
        codex_source = make_skill(self.codex_source, "codex-skill")
        agents_source = make_skill(self.agents_source, "agents-skill")
        result, _, stderr = self.call_main("--apply", "--all")
        self.assertEqual(result, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(
            (self.codex_destination / "codex-skill").resolve(),
            codex_source.resolve(),
        )
        self.assertEqual(
            (self.agents_destination / "agents-skill").resolve(),
            agents_source.resolve(),
        )

    def test_select_all_and_explicit_selectors_are_rejected(self):
        source = make_skill(self.codex_source, "one-skill")
        action = sync_skills.Action(
            "codex/one-skill",
            source,
            self.codex_destination / "one-skill",
            "CREATE",
            "destination is missing",
        )
        with self.assertRaisesRegex(
            ValueError,
            "--all cannot be combined with --skill",
        ):
            sync_skills.select_actions(
                [action],
                ["codex/one-skill"],
                select_all=True,
            )


if __name__ == "__main__":
    unittest.main()
