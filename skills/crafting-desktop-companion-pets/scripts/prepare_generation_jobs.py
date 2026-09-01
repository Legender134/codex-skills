from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import tempfile

from contracts import (
    validate_action_contract,
    validate_job_manifest,
    validate_json_structure,
)


_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


class InputError(Exception):
    pass


class SelectionError(InputError):
    pass


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")


def _reject_nonstandard_json_constant(value: str) -> object:
    raise ValueError(f"non-standard JSON constant: {value}")


def _is_utf8_text(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _load_json_object(path: Path, label: str) -> dict[str, object]:
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_nonstandard_json_constant,
        )
    except (OSError, UnicodeError, ValueError, RecursionError) as error:
        raise InputError(f"Cannot read {label} JSON from {path}: {error}") from error
    structural_issues = validate_json_structure(payload, label)
    if structural_issues:
        codes = ", ".join(sorted({issue.code for issue in structural_issues}))
        raise InputError(f"{label} has invalid JSON structure {path}: {codes}")
    if not isinstance(payload, dict):
        raise InputError(f"{label} must contain a JSON object: {path}")
    return payload


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256_PATTERN.fullmatch(value) is not None


def _selected_identity_root(identity: dict[str, object]) -> tuple[dict[str, object], str]:
    canonical_sha256 = identity.get("canonicalSha256")
    visual_verdict_ids = identity.get("visualVerdictIds")
    if identity.get("identityGateStatus") != "identity-selected":
        raise SelectionError("identityGateStatus must be identity-selected")
    if identity.get("selection") != "selected":
        raise SelectionError("identity selection must be selected")
    if identity.get("technicalStatus") != "pass":
        raise SelectionError("identity technicalStatus must be pass")
    if not _is_sha256(canonical_sha256):
        raise SelectionError("identity canonicalSha256 must be a SHA-256 string")
    if not isinstance(visual_verdict_ids, list) or not all(
        _is_utf8_text(verdict_id) and bool(verdict_id.strip())
        for verdict_id in visual_verdict_ids
    ):
        raise SelectionError("identity visualVerdictIds must contain non-empty text ids")
    if not visual_verdict_ids:
        raise SelectionError("identity requires at least one visual verdict id")
    visual_verdict_id = sorted(set(visual_verdict_ids))[0]
    return (
        {
            "id": "identity",
            "kind": "identity",
            "status": "selected",
            "dependsOn": [],
            "inputHashes": {},
            "artifactSha256": canonical_sha256,
            "canonicalIdentitySha256": canonical_sha256,
            # The Task 3 identity contract has technicalStatus, but no auditable
            # technical verdict id. This explicit imported root preserves that fact.
            "importedIdentityRoot": True,
            "technicalVerdictId": None,
            "visualVerdictId": visual_verdict_id,
            "retryCount": 0,
        },
        canonical_sha256,
    )


def _read_actions(
    actions_path: Path, canonical_sha256: str
) -> tuple[list[dict[str, object]], list[Path]]:
    if not actions_path.is_dir():
        raise InputError(f"actions must be a directory: {actions_path}")
    actions: list[dict[str, object]] = []
    action_paths: list[Path] = []
    for path in sorted(actions_path.glob("*.json"), key=lambda item: item.name):
        action = _load_json_object(path, "action contract")
        issues = validate_action_contract(action)
        if issues:
            codes = ", ".join(sorted({issue.code for issue in issues}))
            raise InputError(f"invalid action contract {path}: {codes}")
        if action["identitySha256"].lower() != canonical_sha256.lower():
            raise InputError(
                f"action contract {path} does not use the selected canonical identity hash"
            )
        actions.append(action)
        action_paths.append(path.resolve(strict=False))
    action_ids = [action["actionId"] for action in actions]
    if len(set(action_ids)) != len(action_ids):
        raise InputError("action contracts must have unique actionId values")
    return sorted(actions, key=lambda action: action["actionId"]), action_paths


def _resolve_cli_paths(
    identity_path: Path, actions_path: Path, output_path: Path
) -> tuple[Path, Path, Path]:
    identity = identity_path.resolve(strict=False)
    actions = actions_path.resolve(strict=False)
    output = output_path.resolve(strict=False)
    if output == identity:
        raise InputError("output must not replace the identity contract")
    try:
        output.relative_to(actions)
    except ValueError:
        pass
    else:
        raise InputError("output must not be inside the actions directory")
    return identity, actions, output


def build_generation_jobs(
    identity: dict[str, object], actions: list[dict[str, object]]
) -> dict[str, object]:
    """Build a deterministic identity-rooted generation graph without side effects."""
    root_job, canonical_sha256 = _selected_identity_root(identity)
    jobs: list[dict[str, object]] = [root_job]
    for action in sorted(actions, key=lambda item: item["actionId"]):
        action_id = action["actionId"]
        key_pose_id = f"{action_id}-key-poses"
        jobs.extend(
            [
                {
                    "id": key_pose_id,
                    "kind": "semantic-key-poses",
                    "status": "pending",
                    "dependsOn": ["identity"],
                    "inputHashes": {"identity": canonical_sha256},
                    "artifactSha256": None,
                    "canonicalIdentitySha256": canonical_sha256,
                    "importedIdentityRoot": False,
                    "technicalVerdictId": None,
                    "visualVerdictId": None,
                    "retryCount": 0,
                },
                {
                    "id": f"{action_id}-atlas",
                    "kind": "atlas",
                    "status": "pending",
                    "dependsOn": [key_pose_id],
                    "inputHashes": {},
                    "artifactSha256": None,
                    "canonicalIdentitySha256": canonical_sha256,
                    "importedIdentityRoot": False,
                    "technicalVerdictId": None,
                    "visualVerdictId": None,
                    "retryCount": 0,
                },
            ]
        )
    manifest = {
        "schemaVersion": 1,
        "projectId": identity.get("projectId", "draft-pet"),
        "identityRoute": identity.get("identityRoute", "source-faithful"),
        "formatRoute": identity.get("formatRoute", "undecided"),
        "status": "draft",
        "selection": "candidate",
        "jobs": jobs,
    }
    issues = validate_job_manifest(manifest)
    if issues:
        codes = ", ".join(sorted({issue.code for issue in issues}))
        raise InputError(f"generated job manifest is invalid: {codes}")
    return manifest


def _write_json_atomically(path: Path, payload: dict[str, object]) -> None:
    if not path.parent.is_dir():
        raise InputError(f"output directory does not exist: {path.parent}")
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(payload, temporary, indent=2, ensure_ascii=False)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    except (OSError, UnicodeError) as error:
        raise InputError(f"Cannot write output JSON to {path}: {error}") from error
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except OSError:
                pass


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = _ArgumentParser(
        description="Create deterministic DesktopCompanion generation jobs."
    )
    parser.add_argument("--identity", required=True, type=Path)
    parser.add_argument("--actions", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        identity_path, actions_path, output_path = _resolve_cli_paths(
            args.identity, args.actions, args.output
        )
        identity = _load_json_object(identity_path, "identity contract")
        _, canonical_sha256 = _selected_identity_root(identity)
        actions, action_paths = _read_actions(actions_path, canonical_sha256)
        if output_path in action_paths:
            raise InputError("output must not replace an action contract")
        manifest = build_generation_jobs(identity, actions)
        _write_json_atomically(output_path, manifest)
    except SelectionError as error:
        print(error, file=sys.stderr)
        return 2
    except InputError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
