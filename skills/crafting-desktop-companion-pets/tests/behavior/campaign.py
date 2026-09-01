from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
import sys


RUN_REPETITIONS = range(1, 6)
REQUIRED_RUN_FILES = {f"{rep:02d}.json" for rep in RUN_REPETITIONS}
SCENARIO_SEQUENCE = {
    "identity-and-reference": ("B01", "B03", "B04", "B05", "B06"),
    "visual-versus-technical": ("B02", "B08", "B02", "B08", "B02"),
    "motion-and-repair": ("B07", "B09", "B07", "B09", "B07"),
    "format-runtime-authority": ("B10", "B11", "B12", "B10", "B11"),
}
REQUIRED_VARIANTS = frozenset(SCENARIO_SEQUENCE)
SKILL_ROOT = Path(__file__).resolve().parents[2]
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
REQUIRED_RECORD_FIELDS = {
    "schemaVersion",
    "scenarioId",
    "variant",
    "rep",
    "skillEntrypointSha256",
    "responsePath",
    "reviewed",
    "pass",
    "observedChoices",
    "rationalizations",
    "reviewerNotes",
}


def _require_nonempty_string(record: dict[str, object], field: str, path: Path) -> None:
    if not isinstance(record[field], str) or not record[field]:
        raise ValueError(f"{path}: {field} must be a non-empty string")


def _require_string_list(record: dict[str, object], field: str, path: Path) -> None:
    value = record[field]
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item.strip() for item in value)
    ):
        raise ValueError(f"{path}: {field} must be a non-empty list of strings")


def _require_plain_evidence_file(path: Path, *, label: str) -> tuple[int, int]:
    """Require one ordinary, single-name file and return its filesystem identity."""
    try:
        metadata = path.lstat()
    except OSError as error:
        raise ValueError(f"{label} file does not exist: {path}: {error}") from error
    file_attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if stat.S_ISLNK(metadata.st_mode) or file_attributes & reparse_attribute:
        raise ValueError(f"{label} file must not be a symlink or reparse point: {path}")
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"{label} file must be a regular file: {path}")
    if metadata.st_nlink != 1:
        raise ValueError(f"{label} file must have exactly one hardlink: {path}")
    return metadata.st_dev, metadata.st_ino


def _validate_record(
    record: object, *, variant: str, path: Path
) -> dict[str, object]:
    if not isinstance(record, dict):
        raise ValueError(f"{path}: record must be a JSON object")

    missing_fields = REQUIRED_RECORD_FIELDS.difference(record)
    if missing_fields:
        missing = ", ".join(sorted(missing_fields))
        raise ValueError(f"{path}: missing required fields: {missing}")

    schema_version = record["schemaVersion"]
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version != 1
    ):
        raise ValueError(f"{path}: schemaVersion must be integer 1")

    for field in (
        "scenarioId",
        "variant",
        "skillEntrypointSha256",
        "responsePath",
        "reviewerNotes",
    ):
        _require_nonempty_string(record, field, path)
    for field in ("observedChoices", "rationalizations"):
        _require_string_list(record, field, path)

    rep = record["rep"]
    if isinstance(rep, bool) or not isinstance(rep, int) or rep not in RUN_REPETITIONS:
        raise ValueError(f"{path}: rep must be an integer from 1 through 5")
    if record["variant"] != variant:
        raise ValueError(f"{path}: variant does not match directory {variant!r}")
    expected_scenario = SCENARIO_SEQUENCE[variant][rep - 1]
    if record["scenarioId"] != expected_scenario:
        raise ValueError(
            f"{path}: scenarioId must be {expected_scenario!r} for "
            f"{variant!r} repetition {rep}"
        )
    expected_response = f"responses/{expected_scenario}-rep{rep}.md"
    if record["responsePath"] != expected_response:
        raise ValueError(
            f"{path}: responsePath must bind this scenario/repetition as "
            f"{expected_response!r}"
        )
    skill_hash = record["skillEntrypointSha256"]
    assert isinstance(skill_hash, str)
    if SHA256_PATTERN.fullmatch(skill_hash) is None:
        raise ValueError(
            f"{path}: skillEntrypointSha256 must be a lowercase SHA-256"
        )
    if record["reviewed"] is not True:
        raise ValueError(f"{path}: reviewed evidence is required")
    if not isinstance(record["pass"], bool):
        raise ValueError(f"{path}: pass must be a manual boolean verdict")

    response_relative = Path(str(record["responsePath"]))
    logical_response_path = path.parent / response_relative
    _require_plain_evidence_file(logical_response_path, label="response evidence")
    response_root = path.parent.resolve()
    response_path = logical_response_path.resolve()
    if response_relative.is_absolute():
        raise ValueError(f"{path}: responsePath must be relative to the variant")
    try:
        response_path.relative_to(response_root)
    except ValueError as error:
        raise ValueError(
            f"{path}: responsePath escapes the variant directory"
        ) from error
    if not response_path.is_file():
        raise ValueError(f"{path}: response file does not exist: {response_path}")
    try:
        raw_response = response_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ValueError(f"{path}: cannot read response evidence: {error}") from error
    if not raw_response.strip():
        raise ValueError(f"{path}: response evidence must not be empty")
    rationalizations = record["rationalizations"]
    assert isinstance(rationalizations, list)
    for rationalization in rationalizations:
        assert isinstance(rationalization, str)
        if rationalization not in raw_response:
            raise ValueError(
                f"{path}: rationalization is not a verbatim response excerpt"
            )

    return record


def load_campaign_summary(root: Path) -> dict[str, object]:
    """Load complete, manually reviewed campaign records without scoring them."""
    campaign_root = Path(root)
    if not campaign_root.is_dir():
        raise ValueError(f"campaign directory does not exist: {campaign_root}")
    try:
        resolved_campaign_root = campaign_root.resolve(strict=True)
    except OSError as error:
        raise ValueError(f"cannot resolve campaign directory: {error}") from error

    variants = sorted(
        child.name for child in campaign_root.iterdir() if child.is_dir()
    )
    variant_set = set(variants)
    if variant_set != REQUIRED_VARIANTS:
        missing = sorted(REQUIRED_VARIANTS.difference(variant_set))
        unexpected = sorted(variant_set.difference(REQUIRED_VARIANTS))
        details: list[str] = []
        if missing:
            details.append(f"missing {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected {', '.join(unexpected)}")
        raise ValueError(
            f"{campaign_root}: expected the four high-risk variants "
            f"({'; '.join(details)})"
        )

    runs: list[dict[str, object]] = []
    seen_variant_reps: set[tuple[str, int]] = set()
    seen_responses: set[Path] = set()
    seen_response_identities: set[tuple[int, int]] = set()
    for variant in variants:
        variant_root = campaign_root / variant
        try:
            resolved_variant_root = variant_root.resolve(strict=True)
        except OSError as error:
            raise ValueError(f"cannot resolve variant directory: {error}") from error
        if resolved_variant_root != resolved_campaign_root / variant:
            raise ValueError(
                f"{variant_root}: variant directory must be a direct contained "
                "directory, not a link or junction"
            )
        run_files = {
            path.name for path in variant_root.glob("*.json") if path.is_file()
        }
        if run_files != REQUIRED_RUN_FILES:
            missing = sorted(REQUIRED_RUN_FILES.difference(run_files))
            unexpected = sorted(run_files.difference(REQUIRED_RUN_FILES))
            details: list[str] = []
            if missing:
                details.append(f"missing {', '.join(missing)}")
            if unexpected:
                details.append(f"unexpected {', '.join(unexpected)}")
            raise ValueError(f"{variant_root}: expected 01.json through 05.json ({'; '.join(details)})")

        for expected_rep in RUN_REPETITIONS:
            path = variant_root / f"{expected_rep:02d}.json"
            _require_plain_evidence_file(path, label="campaign record")
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise ValueError(f"{path}: cannot read JSON evidence: {error}") from error
            validated = _validate_record(record, variant=variant, path=path)
            rep = validated["rep"]
            assert isinstance(rep, int)
            key = (variant, rep)
            if key in seen_variant_reps:
                raise ValueError(f"{path}: duplicate (variant, rep) pair {key!r}")
            seen_variant_reps.add(key)
            if rep != expected_rep:
                raise ValueError(
                    f"{path}: record rep {rep} does not match {expected_rep:02d}.json"
                )
            response_path = (
                variant_root / str(validated["responsePath"])
            ).resolve(strict=True)
            if response_path in seen_responses:
                raise ValueError(
                    f"{path}: raw response is already bound to another run"
                )
            seen_responses.add(response_path)
            response_identity = _require_plain_evidence_file(
                response_path, label="response evidence"
            )
            if response_identity in seen_response_identities:
                raise ValueError(
                    f"{path}: raw response shares a filesystem identity with "
                    "another run"
                )
            seen_response_identities.add(response_identity)
            runs.append(validated)

    campaign_hashes = {str(run["skillEntrypointSha256"]) for run in runs}
    if len(campaign_hashes) != 1:
        raise ValueError("campaign records do not share one Skill entrypoint hash")

    return {"variants": variants, "runs": runs}


def validate_campaign(root: Path, require_pass: bool) -> dict[str, object]:
    """Validate campaign evidence and optionally require every recorded verdict to pass."""
    summary = load_campaign_summary(root)
    if require_pass:
        current_skill_hash = hashlib.sha256(
            (SKILL_ROOT / "SKILL.md").read_bytes()
        ).hexdigest()
        recorded_hashes = {
            str(run["skillEntrypointSha256"])
            for run in summary["runs"]
            if isinstance(run, dict)
        }
        if recorded_hashes != {current_skill_hash}:
            raise ValueError(
                "campaign Skill hash does not match the current Skill entrypoint"
            )
        failed_runs = [
            run
            for run in summary["runs"]
            if isinstance(run, dict) and run["pass"] is False
        ]
        if failed_runs:
            raise ValueError("campaign includes manually failed evidence")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate campaign evidence records.")
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--require-pass", action="store_true")
    arguments = parser.parse_args(argv)

    try:
        summary = validate_campaign(
            arguments.campaign, require_pass=arguments.require_pass
        )
    except ValueError as error:
        print(f"invalid campaign evidence: {error}", file=sys.stderr)
        return 1

    print(json.dumps(summary, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
