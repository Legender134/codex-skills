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
    "references/actions-and-motion.md",
    "references/behavior-and-soak.md",
    "references/canonical-identity-and-proportions.md",
    "references/format-v2.md",
    "references/format-v3.md",
    "references/format-v4.md",
    "references/generation-job-graph.md",
    "references/identity-and-evidence.md",
    "references/nangong-wan-calibration-case.md",
    "references/repair-and-convergence.md",
    "references/visual-qa.md",
    "scripts/contracts.py",
    "scripts/format_adapters/__init__.py",
    "scripts/format_adapters/base.py",
    "scripts/format_adapters/v2.py",
    "scripts/format_adapters/v3.py",
    "scripts/format_adapters/v4.py",
    "scripts/inspect_frames.py",
    "scripts/make_contact_sheet.py",
    "scripts/make_identity_review_sheet.py",
    "scripts/make_run_summary.py",
    "scripts/measure_identity_geometry.py",
    "scripts/prepare_generation_jobs.py",
    "scripts/prepare_pet_run.py",
    "scripts/render_timed_previews.py",
    "scripts/validate_identity_gate.py",
    "scripts/validate_package.py",
    "templates/action-contract.json",
    "templates/evidence-ledger.md",
    "templates/identity-contract.json",
    "templates/job-manifest.json",
    "templates/project-brief.md",
    "templates/run-summary.json",
    "templates/visual-verdict.json",
    "tests/behavior/__init__.py",
    "tests/behavior/campaign.py",
    "tests/behavior/rubric.json",
    "tests/behavior/scenarios.json",
    "tests/behavior/test_behavior_evidence.py",
    "tests/fixtures/build_synthetic_dry_run.py",
    "tests/fixtures/v2/pet.json",
    "tests/fixtures/v2/source.json",
    "tests/fixtures/v3/pet.json",
    "tests/fixtures/v3/source.json",
    "tests/fixtures/v4/pet.json",
    "tests/fixtures/v4/source.json",
    "tests/test_canonical_invalidation.py",
    "tests/test_end_to_end_dry_run.py",
    "tests/test_frame_qa.py",
    "tests/test_identity_gate.py",
    "tests/test_identity_geometry.py",
    "tests/test_job_dependencies.py",
    "tests/test_package_routes.py",
    "tests/test_prepare_pet_run.py",
    "tests/test_reference_roles.py",
    "tests/test_run_summary.py",
    "tests/test_skill_structure.py",
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
    required_references = {
        "pet-researcher.toml": {
            "references/identity-and-evidence.md",
            "references/canonical-identity-and-proportions.md",
            "references/actions-and-motion.md",
            "references/nangong-wan-calibration-case.md",
        },
        "pet-builder.toml": {
            "references/identity-and-evidence.md",
            "references/canonical-identity-and-proportions.md",
            "references/actions-and-motion.md",
            "references/generation-job-graph.md",
            "references/visual-qa.md",
            "references/nangong-wan-calibration-case.md",
        },
        "pet-reviewer.toml": {
            "references/identity-and-evidence.md",
            "references/canonical-identity-and-proportions.md",
            "references/visual-qa.md",
            "references/behavior-and-soak.md",
            "references/repair-and-convergence.md",
            "references/nangong-wan-calibration-case.md",
        },
    }
    obsolete_routes = {
        "references/nangong-wan-quality-standard.md",
        "references/production-and-qa.md",
        "references/format-runtime-core.md",
        "templates/action-contract.md",
        "templates/research-brief.md",
        "templates/review-checklist.md",
    }
    format_route_markers = {
        "pet-researcher.toml": (
            "after confirmation, retain only the applicable format authority"
        ),
        "pet-builder.toml": "Read exactly the confirmed format authority",
        "pet-reviewer.toml": "Read exactly the selected format authority",
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
        normalized_instructions = " ".join(instructions.split())
        for reference in (
            "references/format-v2.md",
            "references/format-v3.md",
            "references/format-v4.md",
        ):
            assert reference in instructions
        assert "handoff-contracts.md" not in instructions
        for reference in required_references[filename]:
            assert reference in instructions
        for route in obsolete_routes:
            assert route not in instructions
        assert "only for process calibration when relevant" in normalized_instructions
        assert (
            "never copy its geometry or numerical proportions to another target"
            in normalized_instructions
        )
        assert format_route_markers[filename] in normalized_instructions
        assert "mandatory process baseline" not in instructions
        assert "mandatory review baseline" not in instructions

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
