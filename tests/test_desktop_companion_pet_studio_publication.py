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
    "references/format-and-runtime.md",
    "references/handoff-contracts.md",
    "references/research-and-identity.md",
    "references/visual-production-and-qa.md",
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
