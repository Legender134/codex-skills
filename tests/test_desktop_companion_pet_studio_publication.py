from __future__ import annotations

import re
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "crafting-desktop-companion-pets"
TEMPLATE = ROOT / "templates" / "desktop-companion-pet-studio"
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


def test_project_profile_routes_models_without_machine_trust() -> None:
    config_path = TEMPLATE / ".codex" / "config.toml"
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert config["model"] == "gpt-5.6-sol"
    assert config["model_reasoning_effort"] == "xhigh"
    assert config["agents"]["max_concurrent_threads_per_session"] == 1
    assert config["agents"]["default_subagent_model"] == "gpt-5.6-terra"
    assert config["agents"]["default_subagent_reasoning_effort"] == "max"
    assert "projects" not in config
