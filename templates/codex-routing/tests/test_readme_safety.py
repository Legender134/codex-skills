from __future__ import annotations

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parents[1]
README = SOURCE_ROOT / "README.md"
APPLY_SECTIONS = (
    "Plan, apply and validate",
    "Recovery",
    "Resolve a same-name global agent conflict",
)
ROUTING_COMMAND = re.compile(
    r"\s-m\s+codex_routing\s+(?:install-global|install-egs|rollback)\b"
)


def readme_text() -> str:
    return README.read_text(encoding="utf-8")


def section(text: str, heading: str) -> str:
    marker = f"## {heading}\n"
    start = text.index(marker) + len(marker)
    end = text.find("\n## ", start)
    return text[start:] if end < 0 else text[start:end]


def bash_blocks(text: str) -> list[tuple[int, int, str]]:
    return [
        (match.start(), match.end(), match.group(1))
        for match in re.finditer(r"```bash\n(.*?)\n```", text, re.DOTALL)
    ]


def shell_commands(block: str) -> list[str]:
    commands: list[str] = []
    pending = ""
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        pending = f"{pending} {line}".strip()
        if pending.endswith("\\"):
            pending = pending[:-1].rstrip()
            continue
        commands.append(pending)
        pending = ""
    if pending:
        commands.append(pending)
    return commands


class ReadmeSafetyTests(unittest.TestCase):
    def conflict_recipe(self) -> str:
        body = section(readme_text(), "Resolve a same-name global agent conflict")
        matches = [
            block
            for _, _, block in bash_blocks(body)
            if 'CONFLICT="$TARGET_CODEX_HOME/agents/$ROLE.toml"' in block
        ]
        self.assertEqual(len(matches), 1)
        return matches[0]

    def run_conflict_recipe(
        self, codex_home: Path, *, path: str | None = None
    ) -> subprocess.CompletedProcess:
        environment = os.environ.copy()
        environment.update(
            {
                "WSL_CODEX_HOME": str(codex_home),
                "ROUTING_PYTHON": "/bin/true",
            }
        )
        if path is not None:
            environment["PATH"] = path
        return subprocess.run(
            ("bash", "-c", self.conflict_recipe()),
            cwd=SOURCE_ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )

    def test_apply_commands_are_isolated_behind_manual_checkpoints(self) -> None:
        text = readme_text()
        for heading in APPLY_SECTIONS:
            with self.subTest(section=heading):
                body = section(text, heading)
                blocks = bash_blocks(body)
                preview_count = 0
                apply_count = 0
                previous_end = 0
                for start, end, block in blocks:
                    routing_commands = [
                        command
                        for command in shell_commands(block)
                        if ROUTING_COMMAND.search(command)
                    ]
                    preview = [
                        command
                        for command in routing_commands
                        if "--apply" not in command
                    ]
                    apply = [
                        command for command in routing_commands if "--apply" in command
                    ]
                    self.assertFalse(
                        preview and apply,
                        f"{heading} mixes preview and apply commands in one block",
                    )
                    preview_count += len(preview)
                    apply_count += len(apply)
                    if apply:
                        checkpoint = body[previous_end:start]
                        self.assertIn("STOP", checkpoint)
                        self.assertRegex(checkpoint.lower(), r"\b(review|confirm)\b")
                    previous_end = end
                self.assertGreater(preview_count, 0)
                self.assertGreater(apply_count, 0)

    def test_conflict_recipe_is_standalone_fail_fast_and_non_clobbering(self) -> None:
        recipe = self.conflict_recipe()

        self.assertIn("set -euo pipefail", recipe)
        self.assertIn("mv --no-clobber", recipe)
        self.assertNotIn("-m codex_routing", recipe)

    def test_conflict_recipe_preserves_regular_foreign_bytes(self) -> None:
        foreign = b"foreign role bytes\n"
        with tempfile.TemporaryDirectory() as raw:
            codex_home = Path(raw) / ".codex"
            agents = codex_home / "agents"
            agents.mkdir(parents=True)
            conflict = agents / "scout.toml"
            conflict.write_bytes(foreign)

            result = self.run_conflict_recipe(codex_home)

            archive = codex_home / "routing-conflicts" / "scout.toml.before-routing"
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(conflict.exists())
            self.assertTrue(archive.is_file())
            self.assertEqual(archive.read_bytes(), foreign)

    def test_conflict_recipe_stops_before_move_when_digest_command_fails(
        self,
    ) -> None:
        foreign = b"foreign role bytes\n"
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            codex_home = root / ".codex"
            agents = codex_home / "agents"
            agents.mkdir(parents=True)
            conflict = agents / "scout.toml"
            conflict.write_bytes(foreign)
            shim_dir = root / "bin"
            shim_dir.mkdir()
            sha256sum = shim_dir / "sha256sum"
            sha256sum.write_text("#!/bin/sh\nexit 9\n", encoding="utf-8")
            sha256sum.chmod(0o755)
            path = f"{shim_dir}:{os.environ.get('PATH', '')}"

            result = self.run_conflict_recipe(codex_home, path=path)

            archive = codex_home / "routing-conflicts" / "scout.toml.before-routing"
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(conflict.is_file())
            self.assertEqual(conflict.read_bytes(), foreign)
            self.assertFalse(archive.exists())
            self.assertFalse(archive.is_symlink())

    def test_conflict_recipe_refuses_an_existing_archive_without_changes(self) -> None:
        foreign = b"foreign role bytes\n"
        archived = b"existing archive bytes\n"
        with tempfile.TemporaryDirectory() as raw:
            codex_home = Path(raw) / ".codex"
            agents = codex_home / "agents"
            archive_dir = codex_home / "routing-conflicts"
            agents.mkdir(parents=True)
            archive_dir.mkdir()
            conflict = agents / "scout.toml"
            archive = archive_dir / "scout.toml.before-routing"
            conflict.write_bytes(foreign)
            archive.write_bytes(archived)

            result = self.run_conflict_recipe(codex_home)

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(conflict.read_bytes(), foreign)
            self.assertEqual(archive.read_bytes(), archived)

    def test_conflict_recipe_refuses_linked_or_non_directory_paths(self) -> None:
        foreign = b"foreign role bytes\n"
        cases = (
            "linked-conflict",
            "directory-conflict",
            "linked-archive-directory",
            "file-archive-directory",
        )
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                codex_home = root / ".codex"
                agents = codex_home / "agents"
                agents.mkdir(parents=True)
                conflict = agents / "scout.toml"
                archive_dir = codex_home / "routing-conflicts"
                external = root / "external"

                if case == "linked-conflict":
                    external.write_bytes(foreign)
                    try:
                        conflict.symlink_to(external)
                    except (NotImplementedError, OSError) as exc:
                        self.skipTest(f"symbolic links unavailable: {exc}")
                elif case == "directory-conflict":
                    conflict.mkdir()
                else:
                    conflict.write_bytes(foreign)
                    if case == "linked-archive-directory":
                        external.mkdir()
                        try:
                            archive_dir.symlink_to(external, target_is_directory=True)
                        except (NotImplementedError, OSError) as exc:
                            self.skipTest(f"symbolic links unavailable: {exc}")
                    else:
                        archive_dir.write_bytes(b"not a directory\n")

                result = self.run_conflict_recipe(codex_home)

                self.assertNotEqual(result.returncode, 0)
                if case == "linked-conflict":
                    self.assertTrue(conflict.is_symlink())
                    self.assertEqual(external.read_bytes(), foreign)
                    self.assertFalse(archive_dir.exists())
                elif case == "directory-conflict":
                    self.assertTrue(conflict.is_dir())
                    self.assertFalse(archive_dir.exists())
                elif case == "linked-archive-directory":
                    self.assertEqual(conflict.read_bytes(), foreign)
                    self.assertTrue(archive_dir.is_symlink())
                    self.assertEqual(list(external.iterdir()), [])
                else:
                    self.assertEqual(conflict.read_bytes(), foreign)
                    self.assertEqual(archive_dir.read_bytes(), b"not a directory\n")


if __name__ == "__main__":
    unittest.main()
