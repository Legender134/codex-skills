from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "crafting-desktop-companion-pets"
EXPECTED_SKILL_FILES = {
    "SKILL.md",
    "agents/openai.yaml",
    "references/format-and-runtime.md",
    "references/handoff-contracts.md",
    "references/research-and-identity.md",
    "references/visual-production-and-qa.md",
}


def relative_files(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_pet_skill_is_complete_and_locally_linked() -> None:
    assert relative_files(SKILL) == EXPECTED_SKILL_FILES
    skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert skill_text.startswith("---\nname: crafting-desktop-companion-pets\n")
    for target in re.findall(r"\]\((references/[^)]+\.md)\)", skill_text):
        assert (SKILL / target).is_file(), target
