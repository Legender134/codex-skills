from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "crafting-desktop-companion-pets"
TEMPLATE = ROOT / "templates" / "desktop-companion-pet-studio"
EXPECTED_SKILL_FILES = {
    "SKILL.md",
    "agents/openai.yaml",
    "references/format-runtime-core.md",
    "references/nangong-wan-quality-standard.md",
    "references/production-and-qa.md",
    "templates/action-contract.md",
    "templates/research-brief.md",
    "templates/review-checklist.md",
}
EXPECTED_TOOLCHAIN_FILES = {
    "docs/development-pet-toolchain.md",
    "requirements/pet-media.in",
    "requirements/pet-media.txt",
    "scripts/pet_toolchain_common.ps1",
    "scripts/setup_pet_toolchain.ps1",
    "scripts/verify_pet_toolchain.ps1",
    "tests/test_pet_toolchain_contract.py",
    "tools/pet-toolchain.lock.json",
    "tools/verify_pet_media.py",
    "tools/verify_qt_webp.py",
}
EXPECTED_PROJECT_AGENT_FILES = {
    ".codex/agents/pet-builder.toml",
    ".codex/agents/pet-researcher.toml",
    ".codex/agents/pet-reviewer.toml",
}
FORBIDDEN_SUFFIXES = {".exe", ".dll", ".onnx", ".whl", ".zip", ".7z", ".tar", ".gz"}
GENERIC_QT_PYTHON = r"C:\path\to\PySide6\python.exe"
PRIVATE_KEY_HEADER = re.compile(
    r"-----BEGIN(?: [A-Z0-9]+)* PRIVATE KEY-----", re.IGNORECASE
)
CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?im)^\s*(?:\$env:)?[A-Z0-9_]*(?:token|secret|password|passwd|api[_-]?key|credential)[A-Z0-9_]*\s*[:=]\s*\S+"
)


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
    assert "Use the Nangong Wan/南宫婉 pet as the mandatory quality baseline" in skill_text
    assert "Always read [nangong-wan-quality-standard.md]" in skill_text
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


def test_project_profile_publishes_version_neutral_pet_agents() -> None:
    files = relative_files(TEMPLATE)
    assert EXPECTED_PROJECT_AGENT_FILES <= files
    assert not (TEMPLATE / ".agents").exists()

    expected = {
        "pet-researcher.toml": ("pet_researcher", "gpt-5.6-luna", "max", "read-only"),
        "pet-builder.toml": ("pet_builder", "gpt-5.6-terra", "max", "workspace-write"),
        "pet-reviewer.toml": ("pet_reviewer", "gpt-5.6-sol", "xhigh", "read-only"),
    }
    for filename, (name, model, effort, sandbox) in expected.items():
        path = TEMPLATE / ".codex" / "agents" / filename
        agent = tomllib.loads(path.read_text(encoding="utf-8"))
        instructions = agent["developer_instructions"]
        assert agent["name"] == name
        assert agent["model"] == model
        assert agent["model_reasoning_effort"] == effort
        assert agent["sandbox_mode"] == sandbox
        assert "crafting-desktop-companion-pets" in instructions
        assert all(version in instructions for version in ("v2", "v3", "v4"))
        assert "handoff-contracts.md" not in instructions
        for reference in (
            "references/nangong-wan-quality-standard.md",
            "references/production-and-qa.md",
            "references/format-runtime-core.md",
        ):
            assert reference in instructions

    researcher = tomllib.loads(
        (TEMPLATE / ".codex" / "agents" / "pet-researcher.toml").read_text(
            encoding="utf-8"
        )
    )["developer_instructions"]
    for field in (
        "SOURCE_CAPABILITY_INVENTORY",
        "VERSION_RECOMMENDATION",
        "FORMAT_CONFIRMATION",
        "ACTION_FORM_CONTRACT",
    ):
        assert field in researcher

    builder = tomllib.loads(
        (TEMPLATE / ".codex" / "agents" / "pet-builder.toml").read_text(
            encoding="utf-8"
        )
    )["developer_instructions"]
    for field in ("SELECTED_INPUTS", "SCOPE", "OUTPUTS", "VALIDATION", "UNVERIFIED"):
        assert field in builder

    reviewer = tomllib.loads(
        (TEMPLATE / ".codex" / "agents" / "pet-reviewer.toml").read_text(
            encoding="utf-8"
        )
    )["developer_instructions"]
    for field in ("VALIDATED", "BLOCKERS", "FINDINGS", "MINIMUM_REWORK", "LIMITATIONS"):
        assert field in reviewer


def test_toolchain_overlay_is_complete_and_source_only() -> None:
    files = relative_files(TEMPLATE)
    assert EXPECTED_TOOLCHAIN_FILES <= files
    assert not [path for path in TEMPLATE.rglob("*") if path.suffix.casefold() in FORBIDDEN_SUFFIXES]
    lock = json.loads((TEMPLATE / "tools/pet-toolchain.lock.json").read_text(encoding="utf-8"))
    assert set(lock["models"]) == {"isnet-anime", "u2net_human_seg"}
    assert set(lock["tools"]) == {"ffmpeg", "imagemagick", "libwebp", "rife"}

    for relative_path in EXPECTED_TOOLCHAIN_FILES:
        text = (TEMPLATE / relative_path).read_bytes().decode("utf-8", errors="strict")
        folded = text.casefold()
        assert "\ufffd" not in text, relative_path
        assert "c:\\users\\" not in folded, relative_path
        assert "c:/users/" not in folded, relative_path
        assert "gho_" not in folded, relative_path
        assert "github_pat_" not in folded, relative_path
        assert not PRIVATE_KEY_HEADER.search(text), relative_path
        assert not CREDENTIAL_ASSIGNMENT.search(text), relative_path

    guide_text = (TEMPLATE / "docs/development-pet-toolchain.md").read_text(encoding="utf-8")
    contract_text = (TEMPLATE / "tests/test_pet_toolchain_contract.py").read_text(
        encoding="utf-8"
    )
    assert GENERIC_QT_PYTHON in guide_text
    assert GENERIC_QT_PYTHON in contract_text


def test_root_catalog_documents_pet_studio_installation() -> None:
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "`crafting-desktop-companion-pets`" in readme_text
    assert (
        "[detailed project overlay README](templates/desktop-companion-pet-studio/README.md)"
        in readme_text
    )
    assert (
        "Use `skill-installer` to install `skills/crafting-desktop-companion-pets` "
        "from `Legender134/codex-skills`."
        in readme_text
    )
    assert "Install the Skill" in readme_text
    assert "Copy the project overlay" in readme_text
    assert "not a Skill" in readme_text
