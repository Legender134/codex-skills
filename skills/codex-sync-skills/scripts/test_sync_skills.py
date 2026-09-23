from pathlib import Path
from contextlib import redirect_stderr, redirect_stdout
from itertools import product
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
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
        with (
            patch.dict(os.environ, {"WSL_DISTRO_NAME": "Ubuntu-Test"}, clear=True),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            result = sync_skills.main(
                [],
                script_file=script,
                wsl_home=self.wsl_home,
            )

        self.assertEqual(result, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertIn("CREATE\tcodex/portable-skill\t", stdout.getvalue())

    def test_inferred_roots_reject_non_wsl_execution(self):
        script = self.make_script(".codex")
        stdout = io.StringIO()
        stderr = io.StringIO()

        with (
            patch.dict(os.environ, {}, clear=True),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            result = sync_skills.main(
                [],
                script_file=script,
                wsl_home=self.wsl_home,
            )

        self.assertEqual(result, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn(
            "inferred-root mode must run inside WSL",
            stderr.getvalue(),
        )

    def test_absent_inferred_source_preserves_wsl_only_skills(self):
        script = self.make_script(".codex")
        windows_codex = self.windows_profile / ".codex" / "skills"
        wsl_codex = self.wsl_home / ".codex" / "skills"
        wsl_agents = self.wsl_home / ".agents" / "skills"
        wsl_codex.mkdir(parents=True)
        wsl_agents.mkdir(parents=True)
        make_skill(windows_codex, "portable-skill")
        local = make_skill(wsl_agents, "local-only")
        before = (local / "SKILL.md").read_bytes()
        stdout = io.StringIO()
        with (
            patch.dict(os.environ, {"WSL_DISTRO_NAME": "Ubuntu-Test"}, clear=True),
            redirect_stdout(stdout),
        ):
            result = sync_skills.main([], script_file=script, wsl_home=self.wsl_home)
        self.assertEqual(result, 0)
        self.assertIn("CREATE\tcodex/portable-skill\t", stdout.getvalue())
        self.assertEqual((local / "SKILL.md").read_bytes(), before)
        self.assertFalse((self.windows_profile / ".agents").exists())

    def test_absent_inferred_source_does_not_hide_invalid_explicit_destination(self):
        script = self.make_script(".codex")
        wsl_codex = self.wsl_home / ".codex" / "skills"
        wsl_codex.mkdir(parents=True)
        destination = self.wsl_home / "misspelled-agents-root"
        stderr = io.StringIO()
        with (
            patch.dict(os.environ, {"WSL_DISTRO_NAME": "Ubuntu-Test"}, clear=True),
            redirect_stderr(stderr),
        ):
            result = sync_skills.main(
                ["--wsl-agents-root", str(destination)],
                script_file=script, wsl_home=self.wsl_home,
            )
        self.assertEqual(result, 1)
        self.assertIn("missing agents WSL destination root", stderr.getvalue())
        self.assertFalse(destination.exists())

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
    def test_system_alias_targets_are_excluded_for_all_case_variants(self):
        for spelling in (".system", ".SYSTEM", ".SyStEm"):
            with self.subTest(spelling=spelling), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                source, destination = root / "source", root / "destination"
                source.mkdir()
                destination.mkdir()
                skill = make_skill(source, "portable")
                (source / spelling).symlink_to(skill)
                reserved_destination = destination / spelling
                reserved_destination.symlink_to(root / "missing")
                candidates, issues = sync_skills.discover_candidates([
                    sync_skills.Scope("codex", source, destination),
                ])
                self.assertEqual(candidates, {})
                self.assertEqual(issues, [
                    "REJECTED codex/portable: source resolves into excluded .system directory",
                ])
                self.assertTrue(reserved_destination.is_symlink())
                self.assertEqual(list(destination.iterdir()), [reserved_destination])

    def test_explicit_roots_cannot_enter_system_directories(self):
        for scope_name, blocked_side, layout in product(
            ("codex", "agents"), ("source", "destination"),
            ("direct", "nested", "linked-root", "linked-system"),
        ):
            with self.subTest(scope=scope_name, side=blocked_side, layout=layout), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                system = root / ".system"
                blocked = system / "nested" if layout == "nested" else system
                if layout == "linked-system":
                    storage = root / "storage"
                    storage.mkdir()
                    system.symlink_to(storage)
                else:
                    blocked.mkdir(parents=True)
                if layout == "linked-root":
                    blocked = root / "root-alias"
                    blocked.symlink_to(system)
                normal = root / "normal"
                normal.mkdir()
                source, destination = (blocked, normal) if blocked_side == "source" else (normal, blocked)
                make_skill(source, "internal")
                marker = destination / "keep.txt"
                marker.write_bytes(b"existing destination bytes")
                arguments = [
                    "--windows-codex-root", str(source), "--windows-agents-root", str(source),
                    "--wsl-codex-root", str(destination), "--wsl-agents-root", str(destination),
                    "--skill", f"{scope_name}/internal", "--json",
                ]
                for mode in ([], ["--apply"]):
                    errors = io.StringIO()
                    with redirect_stderr(errors), redirect_stdout(io.StringIO()):
                        result = sync_skills.main(arguments + mode)
                    self.assertEqual(result, 1)
                    self.assertIn("excluded .system", errors.getvalue())
                    self.assertEqual(list(destination.iterdir()), [marker])
                    self.assertEqual(marker.read_bytes(), b"existing destination bytes")
                self.assertTrue((source / "internal" / "SKILL.md").is_file())

    def test_system_aliases_are_rejected_without_creating_links(self):
        for alias_kind in ("directory", "skill-file"):
            for linked_system in (False, True):
                with self.subTest(alias=alias_kind, linked_system=linked_system), tempfile.TemporaryDirectory() as raw:
                    root = Path(raw)
                    source, destination = root / "source", root / "destination"
                    source.mkdir()
                    destination.mkdir()
                    system = source / ("private-content" if linked_system else ".system")
                    system.mkdir()
                    internal = make_skill(system, "internal")
                    if linked_system:
                        (source / ".system").symlink_to(system)
                    alias = source / "portable-alias"
                    if alias_kind == "directory":
                        alias.symlink_to(internal)
                    else:
                        alias.mkdir()
                        (alias / "SKILL.md").symlink_to(internal / "SKILL.md")
                    arguments = [
                        "--windows-codex-root", str(source), "--windows-agents-root", str(source),
                        "--wsl-codex-root", str(destination), "--wsl-agents-root", str(destination),
                        "--json", "--all",
                    ]
                    for mode in ([], ["--apply"]):
                        output = io.StringIO()
                        with redirect_stdout(output):
                            result = sync_skills.main(arguments + mode)
                        report = json.loads(output.getvalue())
                        self.assertEqual(result, 2)
                        self.assertEqual(report["actions"], [])
                        self.assertTrue(any("excluded .system" in issue for issue in report["issues"]))
                        self.assertEqual(list(destination.iterdir()), [])
                    self.assertTrue((alias / "SKILL.md").is_file())

    def test_skill_file_links_must_stay_inside_approved_root(self):
        outside = self.base / "outside.md"
        outside.write_text("external skill", encoding="utf-8")
        skill = self.codex_source / "external-file"
        skill.mkdir()
        (skill / "SKILL.md").symlink_to(outside)
        candidates, issues = sync_skills.discover_candidates(self.scopes)
        self.assertNotIn("codex/external-file", candidates)
        self.assertIn("REJECTED codex/external-file: source escapes approved root", issues)

    def test_normal_user_skill_aliases_inside_root_remain_supported(self):
        original = make_skill(self.codex_source, "original")
        (self.codex_source / "directory-alias").symlink_to(original)
        file_alias = self.codex_source / "file-alias"
        file_alias.mkdir()
        (file_alias / "SKILL.md").symlink_to(original / "SKILL.md")
        candidates, issues = sync_skills.discover_candidates(self.scopes)
        self.assertEqual(issues, [])
        results, failed = sync_skills.apply_actions(sync_skills.plan_actions(candidates))
        self.assertFalse(failed)
        self.assertEqual(len(results), 3)
        self.assertTrue(all(action.status == "CREATED" for action in results))

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

        scopes = (
            self.scopes[0],
            sync_skills.Scope(
                "agents", self.agents_source, self.agents_destination,
                allow_absent_source=True,
            ),
        )
        candidates, issues = sync_skills.discover_candidates(scopes)

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

    def test_optional_source_root_with_broken_link_is_not_skipped(self):
        self.agents_source.rmdir()
        self.agents_source.symlink_to(self.base / "missing-root")
        scope = sync_skills.Scope(
            "agents", self.agents_source, self.agents_destination,
            allow_absent_source=True,
        )
        with self.assertRaisesRegex(ValueError, "missing agents Windows source root"):
            sync_skills.discover_candidates([scope])
        self.assertTrue(self.agents_source.is_symlink())


class OrphanedLinkTests(FilesystemCase):
    def test_absent_optional_source_still_reports_orphaned_links(self):
        self.agents_source.rmdir()
        target = self.agents_source / "retired"
        destination = self.agents_destination / "retired"
        destination.symlink_to(target)
        scope = sync_skills.Scope(
            "agents", self.agents_source, self.agents_destination,
            allow_absent_source=True,
        )
        candidates, issues = sync_skills.discover_candidates([scope])
        self.assertEqual(candidates, {})
        self.assertEqual(len(issues), 1)
        self.assertIn("BROKEN_LINK agents/retired", issues[0])
        self.assertEqual(destination.readlink(), target)

    def test_unreadable_skill_is_rejected_and_link_is_reported(self):
        source = make_skill(self.codex_source, "unreadable")
        destination = self.codex_destination / "unreadable"
        destination.symlink_to(source)
        original_open = Path.open

        def deny_skill_read(path, *args, **kwargs):
            if path.name == "SKILL.md" and path.parent.resolve() == source:
                raise PermissionError("fixture denies reading this skill")
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", deny_skill_read):
            candidates, issues = sync_skills.discover_candidates(self.scopes)
        self.assertEqual(candidates, {})
        self.assertTrue(any("REJECTED codex/unreadable" in issue for issue in issues))
        self.assertTrue(any("BROKEN_LINK codex/unreadable" in issue for issue in issues))
        self.assertEqual(destination.readlink(), source)

    def test_preview_reports_source_missing_link_without_changing_it(self):
        destination = self.codex_destination / "retired-gpu-skill"
        target = self.codex_source / "retired-gpu-skill"
        destination.symlink_to(target, target_is_directory=True)

        candidates, issues = sync_skills.discover_candidates(self.scopes)

        self.assertEqual(candidates, {})
        self.assertEqual(len(issues), 1)
        self.assertIn("BROKEN_LINK codex/retired-gpu-skill", issues[0])
        self.assertTrue(destination.is_symlink())
        self.assertEqual(destination.readlink(), target)
        self.assertFalse(target.exists())

    def test_healthy_destination_only_skill_is_preserved(self):
        outside = self.base / "native-skills"
        outside.mkdir()
        source = make_skill(outside, "native-gpu")
        destination = self.codex_destination / "native-gpu"
        destination.symlink_to(source, target_is_directory=True)
        candidates, issues = sync_skills.discover_candidates(self.scopes)
        self.assertEqual(candidates, {})
        self.assertEqual(issues, [])
        self.assertEqual(destination.readlink(), source)


class PlanningTests(FilesystemCase):
    def test_existing_links_cannot_use_alternative_source_aliases(self):
        for layout in (".system", ".SYSTEM", "indirect-system", "outside"):
            with self.subTest(layout=layout), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                source, destination = root / "source", root / "destination"
                source.mkdir()
                destination.mkdir()
                skill = make_skill(source, "selected")
                if layout == "outside":
                    alias = root / "outside-alias"
                else:
                    system = source / (layout if layout.startswith(".") else ".system")
                    system.mkdir()
                    alias = system / "alias"
                alias.symlink_to(skill)
                if layout == "indirect-system":
                    indirect = source / "indirect"
                    indirect.symlink_to(alias)
                    alias = indirect
                target = destination / "selected"
                target.symlink_to(alias)
                actions = sync_skills.plan_actions({"codex/selected": (skill, target)})
                self.assertEqual(actions[0].status, "CONFLICT")
                results, failed = sync_skills.apply_actions(actions)
                self.assertTrue(failed)
                self.assertEqual(results[0].status, "CONFLICT")
                self.assertEqual(target.readlink(), alias)

    def test_relative_path_to_selected_source_remains_unchanged(self):
        source = make_skill(self.codex_source, "selected")
        target = self.codex_destination / "selected"
        target.symlink_to(os.path.relpath(source, target.parent))
        results, failed = sync_skills.apply_actions(
            sync_skills.plan_actions({"codex/selected": (source, target)})
        )
        self.assertFalse(failed)
        self.assertEqual(results[0].status, "UNCHANGED")

    def test_intermediate_alias_cannot_be_hidden_by_parent_components(self):
        source = make_skill(self.codex_source, "selected")
        nested = self.codex_source / "nested"
        nested.mkdir()
        alias = self.codex_source / "alias"
        alias.symlink_to(nested)
        for relative in (False, True):
            with self.subTest(relative=relative):
                target = self.codex_destination / str(relative)
                prefix = Path(os.path.relpath(self.codex_source, target.parent)) if relative else self.codex_source
                address = prefix / "alias" / ".." / "selected"
                target.symlink_to(address)
                self.assertEqual(target.resolve(), source)
                actions = sync_skills.plan_actions({"codex/selected": (source, target)})
                self.assertEqual(actions[0].status, "CONFLICT")
                results, failed = sync_skills.apply_actions(actions)
                self.assertTrue(failed)
                self.assertEqual(results[0].status, "CONFLICT")
                self.assertEqual(target.readlink(), address)

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
    def test_existing_link_retargeted_to_equivalent_alias_is_a_conflict(self):
        source = make_skill(self.codex_source, "selected")
        target = self.codex_destination / "selected"
        target.symlink_to(source)
        actions = sync_skills.plan_actions({"codex/selected": (source, target)})
        alias = self.base / "alias"
        alias.symlink_to(source)
        target.unlink()
        target.symlink_to(alias)
        results, failed = sync_skills.apply_actions(actions)
        self.assertTrue(failed)
        self.assertEqual(results[0].status, "CONFLICT")
        self.assertEqual(target.readlink(), alias)

    def test_creation_cannot_be_redirected_by_rebinding_destination_path(self):
        for replacement in ("outside", ".system"):
            with self.subTest(replacement=replacement), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                source, destination, foreign = root / "source", root / "destination", root / replacement
                for directory in (source, destination, foreign):
                    directory.mkdir()
                skill = make_skill(source, "selected")
                preserved = root / "preserved"
                actions = sync_skills.plan_actions({"codex/selected": (skill, destination / "selected")})
                real_symlink = sync_skills._symlink

                def rebind_at_creation(source_path, name, **kwargs):
                    destination.rename(preserved)
                    destination.symlink_to(foreign)
                    real_symlink(source_path, name, **kwargs)

                with patch.object(sync_skills, "_symlink", new=rebind_at_creation):
                    results, failed = sync_skills.apply_actions(actions)
                self.assertTrue(failed)
                self.assertEqual(results[0].status, "CONFLICT")
                self.assertEqual(list(foreign.iterdir()), [])
                self.assertEqual((preserved / "selected").readlink(), skill)

    def test_creation_refuses_directory_replacement_at_open(self):
        for replacement in ("directory", "symlink"):
            with self.subTest(replacement=replacement), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                source, destination, foreign = root / "source", root / "destination", root / "foreign"
                for directory in (source, destination, foreign):
                    directory.mkdir()
                skill = make_skill(source, "selected")
                preserved = root / "preserved"
                actions = sync_skills.plan_actions({"codex/selected": (skill, destination / "selected")})
                real_open = os.open

                def replace_at_open(path, flags, *args, **kwargs):
                    if path == destination:
                        destination.rename(preserved)
                        if replacement == "directory":
                            destination.mkdir()
                        else:
                            destination.symlink_to(foreign)
                    return real_open(path, flags, *args, **kwargs)

                with patch.object(sync_skills.os, "open", new=replace_at_open):
                    results, failed = sync_skills.apply_actions(actions)
                self.assertTrue(failed)
                self.assertEqual(results[0].status, "CONFLICT")
                for directory in (destination, preserved, foreign):
                    self.assertEqual(list(directory.iterdir()), [])

    def test_creation_closes_directory_handle_on_success_and_failure(self):
        source = make_skill(self.codex_source, "selected")
        for fail in (False, True):
            with self.subTest(fail=fail):
                target = self.codex_destination / str(fail)
                actions = sync_skills.plan_actions({"codex/selected": (source, target)})
                handles = []
                real_symlink = sync_skills._symlink

                def capture_handle(source_path, name, **kwargs):
                    handles.append(kwargs["dir_fd"])
                    if fail:
                        raise PermissionError("injected create failure")
                    real_symlink(source_path, name, **kwargs)

                with patch.object(sync_skills, "_symlink", new=capture_handle):
                    results, failed = sync_skills.apply_actions(actions)
                self.assertEqual(failed, fail)
                self.assertEqual(results[0].status, "CONFLICT" if fail else "CREATED")
                self.assertEqual(len(handles), 1)
                with self.assertRaises(OSError):
                    os.fstat(handles[0])

    def test_unsupported_host_refuses_creation_but_preserves_correct_links(self):
        source = make_skill(self.codex_source, "selected")
        target = self.codex_destination / "selected"
        with patch.object(sync_skills, "_GUARDED_LINK_CREATION", False):
            actions = sync_skills.plan_actions({"codex/selected": (source, target)})
            results, failed = sync_skills.apply_actions(actions)
            self.assertTrue(failed)
            self.assertEqual(results[0].status, "CONFLICT")
            self.assertIn("run from WSL", results[0].detail)
            self.assertFalse(os.path.lexists(target))
            target.symlink_to(source)
            actions = sync_skills.plan_actions({"codex/selected": (source, target)})
            results, failed = sync_skills.apply_actions(actions)
            self.assertFalse(failed)
            self.assertEqual(results[0].status, "UNCHANGED")

    def test_direct_plan_cannot_create_inside_system_destination(self):
        source = make_skill(self.codex_source, "selected")
        destination = self.base / ".system"
        destination.mkdir()
        actions = sync_skills.plan_actions({"codex/selected": (source, destination / "selected")})
        results, failed = sync_skills.apply_actions(actions)
        self.assertTrue(failed)
        self.assertEqual(results[0].status, "CONFLICT")
        self.assertIn("excluded .system", results[0].detail)
        self.assertEqual(list(destination.iterdir()), [])

    def test_apply_rejects_destination_moved_under_system_without_identity_change(self):
        source = make_skill(self.codex_source, "selected")
        parent = self.base / "container"
        destination = parent / "destination"
        destination.mkdir(parents=True)
        actions = sync_skills.plan_actions({"codex/selected": (source, destination / "selected")})
        system = self.base / ".system"
        system.mkdir()
        parent.rename(system / "container")
        parent.symlink_to(system / "container")
        results, failed = sync_skills.apply_actions(actions)
        self.assertTrue(failed)
        self.assertEqual(results[0].status, "CONFLICT")
        self.assertIn("excluded .system", results[0].detail)
        self.assertEqual(list(destination.iterdir()), [])

    def test_apply_rejects_in_root_source_identity_or_instruction_changes(self):
        for change in ("directory-alias", "directory-replacement", "skill-alias", "skill-replacement", "skill-rewrite"):
            for existing in (False, True):
                with self.subTest(change=change, existing=existing), tempfile.TemporaryDirectory() as raw:
                    root = Path(raw)
                    source, destination = root / "source", root / "destination"
                    source.mkdir()
                    destination.mkdir()
                    first = make_skill(source, "first")
                    second = make_skill(source, "second")
                    selected = source / "selected"
                    if change == "directory-alias":
                        selected.symlink_to(first)
                    else:
                        selected.mkdir()
                        (selected / "SKILL.md").write_bytes((first / "SKILL.md").read_bytes())
                    if change == "skill-alias":
                        (selected / "SKILL.md").unlink()
                        (selected / "SKILL.md").symlink_to(first / "SKILL.md")
                    target = destination / "selected"
                    if existing:
                        target.symlink_to(selected)
                    actions = sync_skills.plan_actions({"codex/selected": (selected, target)})
                    if change == "directory-alias":
                        selected.unlink()
                        selected.symlink_to(second)
                    elif change == "directory-replacement":
                        selected.rename(source / "preserved")
                        selected.mkdir()
                        (selected / "SKILL.md").write_bytes((first / "SKILL.md").read_bytes())
                    elif change == "skill-alias":
                        (selected / "SKILL.md").unlink()
                        (selected / "SKILL.md").symlink_to(second / "SKILL.md")
                    elif change == "skill-replacement":
                        replacement = source / "replacement.md"
                        replacement.write_bytes((selected / "SKILL.md").read_bytes())
                        replacement.replace(selected / "SKILL.md")
                    else:
                        (selected / "SKILL.md").write_bytes((second / "SKILL.md").read_bytes())
                    results, failed = sync_skills.apply_actions(actions)
                    self.assertTrue(failed)
                    self.assertEqual(results[0].status, "CONFLICT")
                    self.assertIn("changed after planning", results[0].detail)
                    if existing:
                        self.assertEqual(target.readlink(), selected)
                    else:
                        self.assertFalse(os.path.lexists(target))

    def test_correct_link_created_after_planning_is_revalidated_and_preserved(self):
        source = make_skill(self.codex_source, "selected")
        target = self.codex_destination / "selected"
        actions = sync_skills.plan_actions({"codex/selected": (source, target)})
        target.symlink_to(source)
        before = target.lstat()
        with patch.object(sync_skills, "_symlink", side_effect=AssertionError("must preserve existing link")):
            results, failed = sync_skills.apply_actions(actions)
        self.assertFalse(failed)
        self.assertEqual(results[0].status, "UNCHANGED")
        self.assertEqual((target.lstat().st_dev, target.lstat().st_ino), (before.st_dev, before.st_ino))

    def test_apply_rejects_system_aliases_introduced_after_planning(self):
        for alias_kind in ("directory", "skill-file"):
            for existing in (False, True):
                with self.subTest(alias=alias_kind, existing=existing), tempfile.TemporaryDirectory() as raw:
                    root = Path(raw)
                    source, destination = root / "source", root / "destination"
                    source.mkdir()
                    destination.mkdir()
                    (source / ".system").mkdir()
                    internal = make_skill(source / ".system", "internal")
                    skill = make_skill(source, "selected")
                    target = destination / "selected"
                    if existing:
                        target.symlink_to(skill)
                    actions = sync_skills.plan_actions({"codex/selected": (skill, target)})
                    if alias_kind == "directory":
                        skill.rename(source / "preserved")
                        skill.symlink_to(internal)
                    else:
                        (skill / "SKILL.md").unlink()
                        (skill / "SKILL.md").symlink_to(internal / "SKILL.md")
                    results, failed = sync_skills.apply_actions(actions)
                    self.assertTrue(failed)
                    self.assertEqual(results[0].status, "CONFLICT")
                    self.assertIn("excluded .system", results[0].detail)
                    if existing:
                        self.assertEqual(target.readlink(), skill)
                    else:
                        self.assertFalse(os.path.lexists(target))

    def test_apply_rejects_directory_and_link_changes_after_planning(self):
        for change in ("retarget", "unlink", "unreadable", "source-escape", "destination-root", "source-root"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                source, destination, outside = (root / name for name in ("source", "destination", "outside"))
                for path in (source, destination, outside):
                    path.mkdir()
                skill = make_skill(source, "chosen")
                foreign = make_skill(outside, "foreign")
                target = destination / "chosen"
                if change in ("retarget", "unlink", "unreadable"):
                    target.symlink_to(skill)
                real_select = sync_skills.select_actions

                def mutate_after_plan(*args, **kwargs):
                    selected = real_select(*args, **kwargs)
                    if change == "retarget":
                        target.unlink()
                        target.symlink_to(foreign)
                    elif change == "unlink":
                        target.unlink()
                    elif change == "unreadable":
                        (skill / "SKILL.md").unlink()
                    elif change == "source-escape":
                        skill.rename(source / "preserved")
                        skill.symlink_to(foreign)
                    elif change == "destination-root":
                        destination.rename(root / "preserved")
                        destination.symlink_to(outside)
                    else:
                        source.rename(root / "preserved")
                        source.symlink_to(outside)
                    return selected

                arguments = [
                    "--windows-codex-root", str(source), "--windows-agents-root", str(source),
                    "--wsl-codex-root", str(destination), "--wsl-agents-root", str(destination),
                    "--apply", "--skill", "codex/chosen", "--json",
                ]
                stdout = io.StringIO()
                with patch.object(sync_skills, "select_actions", side_effect=mutate_after_plan), redirect_stdout(stdout):
                    result = sync_skills.main(arguments)
                report = json.loads(stdout.getvalue())
                self.assertEqual(result, 2)
                self.assertEqual(report["actions"][0]["status"], "CONFLICT")
                self.assertFalse(os.path.lexists(outside / "chosen"))
                if change == "retarget":
                    self.assertEqual(target.readlink(), foreign)
                elif change == "unreadable":
                    self.assertEqual(target.readlink(), skill)
                else:
                    self.assertFalse(os.path.lexists(target))

    def test_apply_rechecks_created_link_target(self):
        source = make_skill(self.codex_source, "chosen")
        foreign = make_skill(self.agents_source, "foreign")
        target = self.codex_destination / "chosen"
        real_link = sync_skills._symlink

        def retarget_after_create(source_path, name, **kwargs):
            real_link(source_path, name, **kwargs)
            target.unlink()
            real_link(foreign, name, **kwargs)

        actions = sync_skills.plan_actions({"codex/chosen": (source, target)})
        with patch.object(sync_skills, "_symlink", new=retarget_after_create):
            results, failed = sync_skills.apply_actions(actions)
        self.assertTrue(failed)
        self.assertEqual(results[0].status, "CONFLICT")
        self.assertEqual(target.readlink(), foreign)

    def test_apply_rechecks_earlier_results_at_closeout(self):
        first = make_skill(self.codex_source, "first")
        second = make_skill(self.codex_source, "second")
        foreign = make_skill(self.agents_source, "foreign")
        first_target, second_target = self.codex_destination / "first", self.codex_destination / "second"
        first_target.symlink_to(first)
        real_link = sync_skills._symlink

        def change_earlier_link(source_path, name, **kwargs):
            real_link(source_path, name, **kwargs)
            first_target.unlink()
            first_target.symlink_to(foreign)

        actions = sync_skills.plan_actions({
            "codex/first": (first, first_target), "codex/second": (second, second_target),
        })
        with patch.object(sync_skills, "_symlink", new=change_earlier_link):
            results, failed = sync_skills.apply_actions(actions)
        self.assertTrue(failed)
        self.assertEqual([r.status for r in results], ["CONFLICT", "CREATED"])
        self.assertEqual(first_target.readlink(), foreign)
        self.assertEqual(second_target.readlink(), second)

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
            try:
                result = sync_skills.main([*self.root_arguments(), *arguments])
            except SystemExit as exc:
                result = int(exc.code)
        return result, stdout.getvalue(), stderr.getvalue()

    def test_preview_does_not_create_missing_link(self):
        make_skill(self.codex_source, "preview-skill")
        result, stdout, stderr = self.call_main()
        self.assertEqual(result, 0)
        self.assertIn("CREATE\tcodex/preview-skill\t", stdout)
        self.assertEqual(stderr, "")
        self.assertFalse(os.path.lexists(self.codex_destination / "preview-skill"))

    def test_text_preview_includes_reviewable_source_and_destination(self):
        source = make_skill(self.codex_source, "preview-paths")
        result, stdout, stderr = self.call_main()
        self.assertEqual(result, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(
            stdout.strip().split("\t"),
            ["CREATE", "codex/preview-paths", str(source),
             str(self.codex_destination / "preview-paths"), "destination is missing"],
        )

    def test_inaccessible_source_directory_does_not_hide_valid_preview(self):
        make_skill(self.codex_source, "good-skill")
        blocked = make_skill(self.codex_source, "blocked-skill")
        original_is_file = Path.is_file

        def deny_metadata(path):
            if path == blocked / "SKILL.md":
                raise PermissionError("fixture denies directory traversal")
            return original_is_file(path)

        with patch.object(Path, "is_file", deny_metadata):
            result, stdout, stderr = self.call_main("--skill", "codex/good-skill")
        self.assertEqual(result, 2)
        self.assertEqual(stderr, "")
        self.assertIn("CREATE\tcodex/good-skill\t", stdout)
        self.assertIn("REJECTED codex/blocked-skill", stdout)
        self.assertFalse(os.path.lexists(self.codex_destination / "good-skill"))

    def test_relative_cli_roots_create_readable_link_and_preview_unchanged(self):
        source = make_skill(self.codex_source, "relative-roots")
        arguments = self.root_arguments()
        for index in range(1, len(arguments), 2):
            arguments[index] = str(Path(arguments[index]).relative_to(self.base))
        command = [
            sys.executable, str(Path(sync_skills.__file__).resolve()),
            *arguments, "--skill", "codex/relative-roots", "--json",
        ]
        applied = subprocess.run(
            [*command, "--apply"], cwd=self.base, capture_output=True, text=True,
        )
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertEqual(json.loads(applied.stdout)["actions"][0]["status"], "CREATED")
        destination = self.codex_destination / "relative-roots"
        self.assertEqual(destination.resolve(), source)
        self.assertEqual((destination / "SKILL.md").read_bytes(), (source / "SKILL.md").read_bytes())
        preview = subprocess.run(command, cwd=self.base, capture_output=True, text=True)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertEqual(json.loads(preview.stdout)["actions"][0]["status"], "UNCHANGED")

    def test_selected_scope_ignores_missing_unselected_roots(self):
        source = make_skill(self.codex_source, "selected-scope")
        self.agents_source.rmdir()
        self.agents_destination.rmdir()
        result, stdout, stderr = self.call_main(
            "--apply", "--skill", "codex/selected-scope",
        )
        self.assertEqual(result, 0, stderr)
        self.assertIn("CREATED\tcodex/selected-scope\t", stdout)
        self.assertEqual((self.codex_destination / "selected-scope").resolve(), source)
        self.assertFalse(self.agents_source.exists())
        self.assertFalse(self.agents_destination.exists())

    def test_explicit_missing_source_is_error_before_mutation(self):
        make_skill(self.codex_source, "valid-skill")
        self.agents_source.rmdir()
        result, stdout, stderr = self.call_main("--apply", "--all")
        self.assertEqual(result, 1)
        self.assertEqual(stdout, "")
        self.assertIn("missing agents Windows source root", stderr)
        self.assertFalse(os.path.lexists(self.codex_destination / "valid-skill"))

    def test_source_lost_after_preview_is_not_reported_created(self):
        source = make_skill(self.codex_source, "lost-source")
        destination = self.codex_destination / "lost-source"
        actions = sync_skills.plan_actions({"codex/lost-source": (source, destination)})
        (source / "SKILL.md").unlink()
        results, failed = sync_skills.apply_actions(actions)
        self.assertTrue(failed)
        self.assertEqual(results[0].status, "CONFLICT")
        self.assertFalse(os.path.lexists(destination))

    def test_unreadable_new_link_reports_conflict_without_removing_it(self):
        source = make_skill(self.codex_source, "lost-during-create")
        original_symlink = sync_skills._symlink

        def link_then_lose_source(source_path, name, **kwargs):
            original_symlink(source_path, name, **kwargs)
            (source / "SKILL.md").unlink()

        with patch.object(sync_skills, "_symlink", link_then_lose_source):
            result, stdout, _ = self.call_main(
                "--apply", "--skill", "codex/lost-during-create",
            )
        self.assertEqual(result, 2)
        self.assertIn("CONFLICT\tcodex/lost-during-create\t", stdout)
        self.assertNotIn("CREATED", stdout)
        self.assertTrue((self.codex_destination / "lost-during-create").is_symlink())

    def test_parser_usage_errors_return_one_and_do_not_mutate(self):
        make_skill(self.codex_source, "parser-skill")
        for arguments in [("--unknown-option",), ("--skill",),
                          ("--all", "--skill", "codex/parser-skill")]:
            with self.subTest(arguments=arguments):
                result, stdout, stderr = self.call_main(*arguments)
                self.assertEqual(result, 1)
                self.assertEqual(stdout, "")
                self.assertIn("error:", stderr)
                self.assertFalse(os.path.lexists(self.codex_destination / "parser-skill"))

    def test_apply_creates_only_selected_link(self):
        first = make_skill(self.codex_source, "first-skill")
        make_skill(self.codex_source, "second-skill")
        result, stdout, stderr = self.call_main(
            "--apply", "--skill", "codex/first-skill"
        )
        self.assertEqual(result, 0)
        self.assertIn("CREATED\tcodex/first-skill\t", stdout)
        self.assertEqual(stderr, "")
        self.assertEqual(
            (self.codex_destination / "first-skill").resolve(),
            first.resolve(),
        )
        self.assertFalse(os.path.lexists(self.codex_destination / "second-skill"))

    def test_repeated_apply_is_idempotent(self):
        source = make_skill(self.codex_source, "repeat-skill")
        arguments = ("--apply", "--skill", "codex/repeat-skill")
        first_result, first_stdout, _ = self.call_main(*arguments)
        second_result, stdout, _ = self.call_main(*arguments)
        destination = self.codex_destination / "repeat-skill"
        self.assertEqual((first_result, second_result), (0, 0))
        self.assertTrue(destination.is_symlink())
        self.assertEqual(destination.resolve(), source.resolve())
        self.assertIn("CREATED\tcodex/repeat-skill\t", first_stdout)
        self.assertIn("UNCHANGED\tcodex/repeat-skill\t", stdout)
        self.assertIn("link already targets source", stdout)

    def test_json_preview_reports_actions_and_issues(self):
        source = make_skill(self.codex_source, "json-skill")
        destination = self.codex_destination / "json-skill"

        result, stdout, stderr = self.call_main("--json")

        self.assertEqual(result, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(
            json.loads(stdout),
            {
                "actions": [
                    {
                        "selector": "codex/json-skill",
                        "source": str(source),
                        "destination": str(destination),
                        "status": "CREATE",
                        "detail": "destination is missing",
                    }
                ],
                "issues": [],
            },
        )

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
        self.assertIn(
            f"missing agents WSL destination root: {self.agents_destination}; "
            "create it before retrying",
            stderr,
        )
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

    def test_cyclic_links_are_reported_without_blocking_safe_items(self):
        safe = make_skill(self.codex_source, "safe-skill")
        make_skill(self.codex_source, "self-loop")
        make_skill(self.codex_source, "cycle-a")
        self_loop = self.codex_destination / "self-loop"
        cycle_a = self.codex_destination / "cycle-a"
        cycle_b = self.codex_destination / "cycle-b"
        self_loop.symlink_to("self-loop")
        cycle_a.symlink_to("cycle-b")
        cycle_b.symlink_to("cycle-a")
        links = {path: path.readlink() for path in (self_loop, cycle_a, cycle_b)}

        for apply in (False, True):
            with self.subTest(apply=apply):
                arguments = ["--json", "--all"] + (["--apply"] if apply else [])
                result, stdout, stderr = self.call_main(*arguments)
                self.assertEqual(result, 2)
                self.assertEqual(stderr, "")
                report = json.loads(stdout)
                statuses = {action["selector"]: action["status"] for action in report["actions"]}
                self.assertEqual(statuses, {
                    "codex/safe-skill": "CREATED" if apply else "CREATE",
                    "codex/self-loop": "CONFLICT",
                    "codex/cycle-a": "CONFLICT",
                })
                for path, target in links.items():
                    self.assertEqual(path.readlink(), target)
                    self.assertTrue(any(f"BROKEN_LINK codex/{path.name}:" in issue
                                        for issue in report["issues"]))
                destination = self.codex_destination / "safe-skill"
                if apply:
                    self.assertEqual(destination.resolve(), safe)
                else:
                    self.assertFalse(os.path.lexists(destination))

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
