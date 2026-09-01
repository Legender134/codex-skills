from __future__ import annotations

import json
from pathlib import Path
import re


SKILL_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_ROOT = SKILL_ROOT / "templates"
PROJECT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
IDENTITY_ROUTES = {"source-faithful", "original-brand"}
FORMAT_ROUTES = {"undecided", "v2", "v3", "v4"}
RUN_DIRECTORIES = (
    "evidence",
    "contracts",
    "contracts/actions",
    "references",
    "references/selected-sources",
    "decoded",
    "frames",
    "atlases",
    "package",
    "qa",
    "qa/identity",
    "qa/actions",
    "qa/runtime",
    "qa/behavior",
)


def _validate_choice(value: str, name: str, accepted: set[str]) -> None:
    if value not in accepted:
        choices = ", ".join(sorted(accepted))
        raise ValueError(f"{name} must be one of: {choices}")


def _read_json_template(name: str) -> dict[str, object]:
    return json.loads((TEMPLATES_ROOT / name).read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def prepare_pet_run(
    output_root: Path,
    project_id: str,
    identity_route: str,
    format_route: str,
) -> Path:
    """Create one new draft run directory without changing existing runs."""
    if not isinstance(project_id, str) or not PROJECT_ID_PATTERN.fullmatch(project_id):
        raise ValueError("project_id must match ^[a-z0-9][a-z0-9-]{0,63}$")
    _validate_choice(identity_route, "identity_route", IDENTITY_ROUTES)
    _validate_choice(format_route, "format_route", FORMAT_ROUTES)

    json_templates = {
        name: _read_json_template(name)
        for name in (
            "identity-contract.json",
            "action-contract.json",
            "job-manifest.json",
            "visual-verdict.json",
            "run-summary.json",
        )
    }
    markdown_templates = {
        name: (TEMPLATES_ROOT / name).read_text(encoding="utf-8")
        for name in ("project-brief.md", "evidence-ledger.md")
    }

    run_dir = Path(output_root) / project_id
    run_dir.mkdir(exist_ok=False)
    for relative_path in RUN_DIRECTORIES:
        (run_dir / relative_path).mkdir()

    (run_dir / "project-brief.md").write_text(
        markdown_templates["project-brief.md"], encoding="utf-8"
    )
    (run_dir / "evidence" / "ledger.md").write_text(
        markdown_templates["evidence-ledger.md"], encoding="utf-8"
    )
    _write_json(
        run_dir / "evidence" / "sources.json",
        {"schemaVersion": 1, "sources": []},
    )

    identity = json_templates["identity-contract.json"]
    identity["projectId"] = project_id
    identity["identityRoute"] = identity_route
    _write_json(run_dir / "contracts" / "identity.json", identity)

    for template_name, destination in (
        ("action-contract.json", run_dir / "contracts" / "actions" / "action-contract.json"),
        ("job-manifest.json", run_dir / "jobs.json"),
        ("visual-verdict.json", run_dir / "qa" / "visual-verdict.json"),
        ("run-summary.json", run_dir / "run-summary.json"),
    ):
        payload = json_templates[template_name]
        payload["projectId"] = project_id
        payload["identityRoute"] = identity_route
        payload["formatRoute"] = format_route
        _write_json(destination, payload)

    return run_dir
