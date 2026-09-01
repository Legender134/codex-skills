from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
import math
from pathlib import Path, PurePosixPath
import re


IDENTITY_ROUTES = {"source-faithful", "original-brand"}
AUTHORITATIVE_EVIDENCE_CLASSES = {
    "current-official",
    "same-character-current",
    "approved-original-design",
}
VISUAL_REVIEWER_TYPES = {"builder", "independent", "user"}
VISUAL_VERDICT_GATES = {"identity", "motion", "action", "visual"}
VISUAL_VERDICT_DECISIONS = {"pass", "fail", "needs-review"}
VISUAL_REVIEW_SCALES = {
    "actual-runtime-size",
    "actual-runtime-size-plus-detail",
    "enlarged-only",
    "not-reviewed",
}
_GENUINE_VISUAL_REVIEW_SCALES = frozenset(
    VISUAL_REVIEW_SCALES - {"not-reviewed"}
)
_VISUAL_PASS_REVIEW_SCALES = frozenset(
    {"actual-runtime-size", "actual-runtime-size-plus-detail"}
)
VALID_JOB_STATES = (
    "pending",
    "ready",
    "generating",
    "candidate",
    "technical-pass",
    "visual-pass",
    "selected",
    "blocked",
    "superseded",
    "rejected",
)
_ACTIVE_JOB_STATES = frozenset(VALID_JOB_STATES[:7])
_TERMINAL_FAILURE_STATES = frozenset({"blocked", "superseded", "rejected"})
_FORWARD_JOB_TRANSITIONS = {
    "pending": "ready",
    "ready": "generating",
    "generating": "candidate",
    "candidate": "technical-pass",
    "technical-pass": "visual-pass",
    "visual-pass": "selected",
}
_PROP_LIFECYCLE_STAGES = {
    "introduced",
    "acquired",
    "used",
    "released",
    "consumed",
    "absent",
}
_EFFECT_LIFECYCLE_STAGES = {
    "origin",
    "growth",
    "travel",
    "peak",
    "decay",
    "cleanup",
    "absent",
}
_FAILURE_STRATEGY_CLASSIFICATION_BY_CODE = {
    "replace-reference-evidence": "causal-reference-evidence",
    "revise-semantic-key-poses": "causal-key-poses",
    "revise-layout-composition": "causal-layout",
    "change-generation-granularity": "causal-generation-granularity",
    "change-production-route": "causal-production-route",
    "prompt-wording-only": "prompt-wording-only",
}
_FAILURE_STRATEGY_CLASSIFICATIONS = frozenset(
    _FAILURE_STRATEGY_CLASSIFICATION_BY_CODE.values()
)
_IDENTITY_ARTIFACT_STATES = frozenset(
    {"candidate", "technical-pass", "visual-pass", "selected"}
)
_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
MAX_JSON_NESTING_DEPTH = 128
_MAX_UNTRUSTED_IMAGE_PIXELS = 16 * 1024 * 1024
_MATURITY_STAGES = (
    "research-candidate",
    "identity-candidate",
    "identity-selected",
    "storyboard-candidate",
    "production-frames",
    "runtime-valid",
    "installed-test",
    "long-use-candidate",
    "release-candidate",
)
_SCHEDULER_PRIORITY_MIN = -100
_SCHEDULER_PRIORITY_MAX = 100
_RUNTIME_EVIDENCE_KINDS = frozenset({"Registry", "Catalog"})
_USER_ACCEPTANCE_GATES = frozenset({"identity", "motion", "action", "visual"})
_USER_ACCEPTANCE_DECISIONS = frozenset({"pass", "fail", "needs-review"})


@dataclass(frozen=True)
class Issue:
    code: str
    path: str
    message: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_utf8_text(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _validate_untrusted_image_canvas(width: object, height: object) -> None:
    """Reject unsafe decoded-image canvases before any pixel-data operation."""
    if (
        not isinstance(width, int)
        or isinstance(width, bool)
        or not isinstance(height, int)
        or isinstance(height, bool)
        or width <= 0
        or height <= 0
        or width * height > _MAX_UNTRUSTED_IMAGE_PIXELS
    ):
        raise ValueError("image has an unsafe canvas")


def validate_json_structure(value: object, path: str = "value") -> list[Issue]:
    """Iteratively validate a JSON-shaped value with at most 128 container levels.

    The root is level zero. Every nested ``dict`` or ``list`` increases the
    level by one; unknown extension fields are traversed as well. Direct Python
    cycles and shared containers cannot be represented by JSON and are rejected
    instead of being copied or recursively traversed.
    """
    base_path = path if _is_utf8_text(path) and path else "value"
    issues: list[Issue] = []
    stack: list[tuple[object, str, int, bool]] = [(value, base_path, 0, False)]
    seen_containers: set[int] = set()
    active_containers: set[int] = set()
    try:
        while stack:
            current, current_path, depth, leaving = stack.pop()
            if leaving:
                active_containers.discard(id(current))
                continue
            if isinstance(current, str):
                if not _is_utf8_text(current):
                    issues.append(
                        Issue(
                            "JSON_STRUCTURE_TEXT_INVALID",
                            current_path,
                            "JSON text must be UTF-8 encodable.",
                        )
                    )
                continue
            if current is None or isinstance(current, (bool, int)):
                continue
            if isinstance(current, float):
                if not math.isfinite(current):
                    issues.append(
                        Issue(
                            "JSON_STRUCTURE_NUMBER_INVALID",
                            current_path,
                            "JSON numbers must be finite.",
                        )
                    )
                continue
            if not isinstance(current, (dict, list)):
                issues.append(
                    Issue(
                        "JSON_STRUCTURE_VALUE_INVALID",
                        current_path,
                        "JSON values must be scalars, objects, or arrays.",
                    )
                )
                continue
            if depth > MAX_JSON_NESTING_DEPTH:
                issues.append(
                    Issue(
                        "JSON_STRUCTURE_DEPTH_EXCEEDED",
                        current_path,
                        "JSON containers may not nest more than 128 levels below the root.",
                    )
                )
                continue

            container_id = id(current)
            if container_id in active_containers:
                issues.append(
                    Issue(
                        "JSON_STRUCTURE_CYCLE",
                        current_path,
                        "JSON containers must not contain a cycle.",
                    )
                )
                continue
            if container_id in seen_containers:
                issues.append(
                    Issue(
                        "JSON_STRUCTURE_SHARED_CONTAINER",
                        current_path,
                        "JSON containers must not share a mutable container instance.",
                    )
                )
                continue
            seen_containers.add(container_id)
            active_containers.add(container_id)
            stack.append((current, current_path, depth, True))
            if isinstance(current, dict):
                for index, (key, item) in enumerate(current.items()):
                    item_path = f"{current_path}.<key:{index}>"
                    if not _is_utf8_text(key):
                        issues.append(
                            Issue(
                                "JSON_STRUCTURE_KEY_INVALID",
                                item_path,
                                "JSON object keys must be UTF-8 text.",
                            )
                        )
                    stack.append((item, item_path, depth + 1, False))
            else:
                for index, item in enumerate(current):
                    stack.append((item, f"{current_path}[{index}]", depth + 1, False))
    except Exception:
        issues.append(
            Issue(
                "JSON_STRUCTURE_INVALID",
                base_path,
                "JSON structure could not be traversed safely.",
            )
        )
    return issues


def _structural_issues_block_field_validation(issues: list[Issue]) -> bool:
    return any(
        issue.code
        not in {"JSON_STRUCTURE_TEXT_INVALID", "JSON_STRUCTURE_NUMBER_INVALID"}
        for issue in issues
    )


def _string_list(value: object) -> bool:
    return isinstance(value, list) and all(_is_utf8_text(item) for item in value)


def _optional_text(value: object) -> bool:
    return value is None or (_is_utf8_text(value) and bool(value))


def _text_is_one_of(value: object, accepted: set[str] | frozenset[str]) -> bool:
    return isinstance(value, str) and value in accepted


def _reference_supports_role(reference: dict[str, object], role: str) -> bool:
    roles = reference.get("roles")
    if isinstance(roles, list) and "prohibited" in roles:
        return False
    evidence_class = reference.get("evidenceClass")
    approved_for = reference.get("approvedFor", [])
    return (
        _text_is_one_of(evidence_class, AUTHORITATIVE_EVIDENCE_CLASSES)
        or isinstance(approved_for, list) and role in approved_for
    )


def validate_reference_roles(reference: dict[str, object], route: str) -> list[Issue]:
    structural_issues = validate_json_structure(reference, "reference")
    structural_issues.extend(validate_json_structure(route, "route"))
    if _structural_issues_block_field_validation(structural_issues):
        return structural_issues
    if not isinstance(reference, dict):
        return structural_issues + [
            Issue(
                "REFERENCE_INVALID",
                "reference",
                "Reference records must be JSON objects.",
            )
        ]

    issues = structural_issues
    if not _text_is_one_of(route, IDENTITY_ROUTES):
        issues.append(
            Issue(
                "IDENTITY_ROUTE_INVALID",
                "route",
                "identity route must be source-faithful or original-brand.",
            )
        )
    if not _is_utf8_text(reference.get("id")) or not reference.get("id"):
        issues.append(
            Issue("REFERENCE_ID_INVALID", "reference.id", "Reference id must be text.")
        )
    if not _string_list(reference.get("roles")):
        issues.append(
            Issue(
                "REFERENCE_ROLES_INVALID",
                "reference.roles",
                "Reference roles must be a list of text values.",
            )
        )
    if not _string_list(reference.get("allowedUses")):
        issues.append(
            Issue(
                "REFERENCE_ALLOWED_USES_INVALID",
                "reference.allowedUses",
                "allowedUses must be a list of text values.",
            )
        )
    if not _is_utf8_text(reference.get("evidenceClass")) or not reference.get(
        "evidenceClass"
    ):
        issues.append(
            Issue(
                "REFERENCE_EVIDENCE_CLASS_INVALID",
                "reference.evidenceClass",
                "evidenceClass must be text.",
            )
        )
    if "approvedFor" in reference and not _string_list(reference["approvedFor"]):
        issues.append(
            Issue(
                "REFERENCE_APPROVED_FOR_INVALID",
                "reference.approvedFor",
                "approvedFor must be a list of text values.",
            )
        )
    if issues:
        return issues

    roles = reference["roles"]
    allowed_uses = reference["allowedUses"]
    if "prohibited" in roles and allowed_uses:
        issues.append(
            Issue(
                "PROHIBITED_REFERENCE_HAS_ALLOWED_USE",
                "reference.allowedUses",
                "A prohibited reference cannot declare allowed uses.",
            )
        )
    for role in ("identity", "proportion"):
        if role in roles and not _reference_supports_role(reference, role):
            issues.append(
                Issue(
                    f"ROLE_{role.upper()}_UNSUPPORTED",
                    "reference.evidenceClass",
                    f"{role} requires authoritative evidence or explicit approval.",
                )
            )
    return issues


def validate_identity_contract(contract: dict[str, object]) -> list[Issue]:
    structural_issues = validate_json_structure(contract, "contract")
    if _structural_issues_block_field_validation(structural_issues):
        return structural_issues
    if not isinstance(contract, dict):
        return structural_issues + [
            Issue(
                "IDENTITY_CONTRACT_INVALID",
                "contract",
                "Identity contract must be a JSON object.",
            )
        ]

    issues = structural_issues
    route = contract.get("identityRoute")
    if not _text_is_one_of(route, IDENTITY_ROUTES):
        issues.append(
            Issue(
                "IDENTITY_ROUTE_INVALID",
                "contract.identityRoute",
                "identityRoute must be source-faithful or original-brand.",
            )
        )
    if not _string_list(contract.get("referenceIds")):
        issues.append(
            Issue(
                "REFERENCE_IDS_INVALID",
                "contract.referenceIds",
                "referenceIds must be a list of text values.",
            )
        )
    if "uncertainties" in contract and not isinstance(contract["uncertainties"], list):
        issues.append(
            Issue(
                "UNCERTAINTIES_INVALID",
                "contract.uncertainties",
                "uncertainties must be a list when recorded.",
            )
        )
    for field in ("canonicalPath", "canonicalSha256"):
        if field not in contract or not _optional_text(contract.get(field)):
            issues.append(
                Issue(
                    "CANONICAL_FIELD_INVALID",
                    f"contract.{field}",
                    f"{field} must be null or non-empty text.",
                )
            )
    if not _is_utf8_text(contract.get("technicalStatus")) or not contract.get(
        "technicalStatus"
    ):
        issues.append(
            Issue(
                "TECHNICAL_STATUS_INVALID",
                "contract.technicalStatus",
                "technicalStatus must be text.",
            )
        )
    authority = contract.get("authority")
    if not isinstance(authority, dict):
        issues.append(
            Issue(
                "AUTHORITY_INVALID",
                "contract.authority",
                "authority must be an object.",
            )
        )
    elif not isinstance(authority.get("identityUncertaintyApproved"), bool):
        issues.append(
            Issue(
                "IDENTITY_UNCERTAINTY_APPROVAL_INVALID",
                "contract.authority.identityUncertaintyApproved",
                "identityUncertaintyApproved must be true or false.",
            )
        )
    if "projectId" in contract and not _nonempty_text(contract.get("projectId")):
        issues.append(
            Issue(
                "IDENTITY_PROJECT_ID_INVALID",
                "contract.projectId",
                "projectId must be non-empty UTF-8 text when recorded.",
            )
        )
    if "identityGateStatus" in contract and not _is_utf8_text(
        contract.get("identityGateStatus")
    ):
        issues.append(
            Issue(
                "IDENTITY_GATE_STATUS_INVALID",
                "contract.identityGateStatus",
                "identityGateStatus must be text.",
            )
        )
    return issues


def validate_visual_verdict(verdict: dict[str, object]) -> list[Issue]:
    structural_issues = validate_json_structure(verdict, "verdict")
    if _structural_issues_block_field_validation(structural_issues):
        return structural_issues
    if not isinstance(verdict, dict):
        return structural_issues + [
            Issue(
                "VISUAL_VERDICT_INVALID",
                "verdict",
                "Visual verdicts must be JSON objects.",
            )
        ]

    issues = list(structural_issues)
    verdict_id = verdict.get("verdictId")
    if not _optional_text(verdict_id):
        issues.append(
            Issue(
                "VERDICT_ID_INVALID",
                "verdict.verdictId",
                "verdictId must be null or non-empty text.",
            )
        )
    decision = verdict.get("decision")
    gate = verdict.get("gate")
    review_scale = verdict.get("reviewScale")
    if decision == "pass" and not _nonempty_text(verdict_id):
        issues.append(
            Issue(
                "VERDICT_ID_REQUIRED_FOR_PASS",
                "verdict.verdictId",
                "Pass verdicts require an auditable verdict id.",
            )
    )
    for field in ("gate", "decision"):
        if not _is_utf8_text(verdict.get(field)) or not verdict.get(field):
            issues.append(
                Issue(
                    "VERDICT_FIELD_INVALID",
                    f"verdict.{field}",
                    f"{field} must be text.",
                )
            )
    if _is_utf8_text(gate) and gate not in VISUAL_VERDICT_GATES | {"technical"}:
        issues.append(
            Issue(
                "VERDICT_GATE_INVALID",
                "verdict.gate",
                "gate must be technical, identity, motion, action, or visual.",
            )
        )
    legacy_draft = (
        decision == "not-reviewed"
        and gate == "visual"
        and review_scale == "not-reviewed"
        and verdict.get("artifactSha256") is None
    )
    if (
        _is_utf8_text(decision)
        and decision not in VISUAL_VERDICT_DECISIONS
        and not legacy_draft
    ):
        issues.append(
            Issue(
                "VERDICT_DECISION_INVALID",
                "verdict.decision",
                "decision must be pass, fail, or needs-review.",
            )
        )
    if not _is_utf8_text(review_scale) or review_scale not in VISUAL_REVIEW_SCALES:
        issues.append(
            Issue(
                "VERDICT_REVIEW_SCALE_INVALID",
                "verdict.reviewScale",
                "reviewScale must be a supported review scale.",
            )
        )

    artifact_sha256 = verdict.get("artifactSha256")
    if artifact_sha256 is not None and not _valid_sha256(artifact_sha256):
        issues.append(
            Issue(
                "VERDICT_ARTIFACT_SHA256_INVALID",
                "verdict.artifactSha256",
                "artifactSha256 must be null or a 64-character SHA-256 string.",
            )
        )
    terminal_decision = _is_utf8_text(decision) and decision in {"pass", "fail"}
    if terminal_decision and not _valid_sha256(artifact_sha256):
        issues.append(
            Issue(
                "VERDICT_ARTIFACT_SHA256_INVALID",
                "verdict.artifactSha256",
                "Pass and fail verdicts require an artifact SHA-256 string.",
            )
        )
    recorded_hashes: list[str] = []
    if _valid_sha256(artifact_sha256):
        recorded_hashes.append(artifact_sha256)
    for field in ("reviewedArtifactSha256", "canonicalSubjectSha256"):
        if field not in verdict:
            continue
        value = verdict.get(field)
        if value is not None and not _valid_sha256(value):
            issues.append(
                Issue(
                    "VERDICT_ARTIFACT_SHA256_INVALID",
                    f"verdict.{field}",
                    f"{field} must be null or a 64-character SHA-256 string.",
                )
            )
        if _valid_sha256(value):
            recorded_hashes.append(value)
    if len({value.lower() for value in recorded_hashes}) > 1:
        issues.append(
            Issue(
                "VERDICT_ARTIFACT_HASH_MISMATCH",
                "verdict",
                "Recorded artifact hashes must identify the same reviewed subject.",
            )
        )

    reviewer = verdict.get("reviewer")
    if not isinstance(reviewer, dict):
        issues.append(
            Issue(
                "REVIEWER_INVALID",
                "verdict.reviewer",
                "reviewer must be an object.",
            )
        )
    else:
        if not _is_utf8_text(reviewer.get("type")) or not reviewer.get("type"):
            issues.append(
                Issue(
                    "REVIEWER_TYPE_INVALID",
                    "verdict.reviewer.type",
                    "reviewer type must be text.",
                )
            )
        if not _optional_text(reviewer.get("id")):
            issues.append(
                Issue(
                    "REVIEWER_ID_INVALID",
                    "verdict.reviewer.id",
                    "reviewer id must be null or non-empty text.",
                )
            )
    if "artifactPath" in verdict and not _optional_text(verdict.get("artifactPath")):
        issues.append(
            Issue(
                "VERDICT_FIELD_INVALID",
                "verdict.artifactPath",
                "artifactPath must be null or non-empty text.",
            )
        )
    for field in ("observations", "blockingObservations"):
        value = verdict.get(field)
        if field in verdict and (
            not isinstance(value, list) or not all(_nonempty_text(item) for item in value)
        ):
            issues.append(
                Issue(
                    "VERDICT_OBSERVATIONS_INVALID",
                    f"verdict.{field}",
                    f"{field} must be a list.",
                )
            )
    is_visual_gate = _is_utf8_text(gate) and gate in VISUAL_VERDICT_GATES
    reviewer_type = reviewer.get("type") if isinstance(reviewer, dict) else None
    reviewer_id = reviewer.get("id") if isinstance(reviewer, dict) else None
    if decision == "pass" and is_visual_gate:
        if not _text_is_one_of(reviewer_type, VISUAL_REVIEWER_TYPES) or not _nonempty_text(
            reviewer_id
        ):
            issues.append(
                Issue(
                    "VISUAL_PASS_REVIEWER_UNAUTHORIZED",
                    "verdict.reviewer",
                    "Visual passes require a builder, independent, or user reviewer with an id.",
                )
            )
        if gate == "identity" and review_scale != "actual-runtime-size":
            issues.append(
                Issue(
                    "IDENTITY_PASS_REQUIRES_ACTUAL_RUNTIME_SIZE",
                    "verdict.reviewScale",
                    "Identity passes require actual-runtime-size review.",
                )
            )
        elif review_scale not in _VISUAL_PASS_REVIEW_SCALES:
            issues.append(
                Issue(
                    "VISUAL_PASS_REQUIRES_ACTUAL_RUNTIME_OR_DETAIL",
                    "verdict.reviewScale",
                    "Motion, action, and visual passes require actual-size review with optional detail.",
                )
            )
    if (
        terminal_decision
        and is_visual_gate
        and review_scale not in _GENUINE_VISUAL_REVIEW_SCALES
    ):
        issues.append(
            Issue(
                "VISUAL_TERMINAL_REVIEW_SCALE_INVALID",
                "verdict.reviewScale",
                "Visual pass and fail verdicts require a genuine reviewed scale.",
            )
        )
    if (
        terminal_decision
        and gate != "technical"
        and not _nonempty_string_list(verdict.get("observations"))
    ):
        issues.append(
            Issue(
                "VERDICT_EVIDENCE_NOTES_REQUIRED",
                "verdict.observations",
                "Pass and fail visual verdicts require non-empty evidence notes.",
            )
        )
    if decision == "fail" and not _nonempty_string_list(
        verdict.get("blockingObservations")
    ):
        issues.append(
            Issue(
                "VERDICT_BLOCKING_OBSERVATIONS_REQUIRED",
                "verdict.blockingObservations",
                "Fail verdicts require non-empty blocking observations.",
            )
        )
    return issues


def _result(
    status: str,
    issues: list[Issue],
    canonical_sha256: str | None,
    accepted_verdict_ids: list[str],
) -> dict[str, object]:
    return {
        "status": status,
        "blockingIssues": [asdict(issue) for issue in issues],
        "canonicalSha256": canonical_sha256,
        "acceptedVerdictIds": accepted_verdict_ids,
    }


def _accepted_visual_verdict(
    verdict: dict[str, object],
    canonical_sha256: str,
    *,
    reviewer_type: str,
) -> bool:
    reviewer = verdict.get("reviewer")
    return (
        _is_utf8_text(verdict.get("gate"))
        and verdict.get("gate") in {"identity", "visual"}
        and verdict.get("decision") == "pass"
        and _is_utf8_text(verdict.get("verdictId"))
        and bool(verdict.get("verdictId"))
        and verdict.get("reviewScale") == "actual-runtime-size"
        and _is_utf8_text(verdict.get("artifactSha256"))
        and verdict.get("artifactSha256").lower() == canonical_sha256.lower()
        and isinstance(reviewer, dict)
        and reviewer.get("type") == reviewer_type
        and _is_utf8_text(reviewer.get("id"))
        and bool(reviewer.get("id"))
    )


def evaluate_identity_gate(
    contract: dict[str, object],
    references: list[dict[str, object]],
    verdicts: list[dict[str, object]],
) -> dict[str, object]:
    structural_issues = validate_json_structure(contract, "contract")
    structural_issues.extend(validate_json_structure(references, "references"))
    structural_issues.extend(validate_json_structure(verdicts, "verdicts"))
    if structural_issues:
        return _result("blocked", structural_issues, None, [])
    issues = validate_identity_contract(contract)
    if not isinstance(contract, dict):
        return _result("blocked", issues, None, [])
    if not isinstance(references, list):
        issues.append(
            Issue(
                "REFERENCES_INVALID",
                "references",
                "References must be a list of JSON objects.",
            )
        )
        return _result("blocked", issues, None, [])
    if not isinstance(verdicts, list):
        issues.append(
            Issue(
                "VERDICTS_INVALID",
                "verdicts",
                "Verdicts must be a list of JSON objects.",
            )
        )
        return _result("blocked", issues, None, [])

    route = contract.get("identityRoute")
    if isinstance(route, str):
        for reference in references:
            issues.extend(validate_reference_roles(reference, route))
    for verdict in verdicts:
        issues.extend(validate_visual_verdict(verdict))
    if issues:
        return _result("blocked", issues, None, [])

    references_by_id = {reference["id"]: reference for reference in references}
    selected_references: list[dict[str, object]] = []
    for reference_id in contract["referenceIds"]:
        reference = references_by_id.get(reference_id)
        if reference is None:
            issues.append(
                Issue(
                    "REFERENCE_ID_NOT_FOUND",
                    "contract.referenceIds",
                    f"Reference id {reference_id!r} was not supplied.",
                )
            )
        else:
            selected_references.append(reference)
    if issues:
        return _result("blocked", issues, None, [])

    if route == "source-faithful":
        authority = contract["authority"]
        uncertainties = contract.get("uncertainties", [])
        uncertainty_approved = (
            authority["identityUncertaintyApproved"]
            and isinstance(uncertainties, list)
            and bool(uncertainties)
        )
        for role in ("identity", "proportion"):
            has_supported_role = any(
                role in reference["roles"]
                and _reference_supports_role(reference, role)
                for reference in selected_references
            )
            if not has_supported_role and not uncertainty_approved:
                issues.append(
                    Issue(
                        f"SOURCE_FAITHFUL_{role.upper()}_REQUIRED",
                        "contract.referenceIds",
                        f"Source-faithful selection requires {role} evidence.",
                    )
                )
    elif route == "original-brand":
        has_approved_brief = any(
            reference["evidenceClass"] == "approved-original-design"
            and all(
                role in reference["roles"]
                and _reference_supports_role(reference, role)
                for role in ("identity", "proportion")
            )
            for reference in selected_references
        )
        if not has_approved_brief:
            issues.append(
                Issue(
                    "APPROVED_CREATIVE_BRIEF_REQUIRED",
                    "contract.referenceIds",
                    "Original-brand selection requires an approved creative brief.",
                )
            )
    if issues:
        return _result("blocked", issues, None, [])

    canonical_path = contract["canonicalPath"]
    canonical_sha256 = contract["canonicalSha256"]
    if not canonical_path or not canonical_sha256:
        return _result("identity-candidate", [], None, [])
    try:
        actual_sha256 = sha256_file(Path(canonical_path))
    except (OSError, ValueError):
        return _result(
            "blocked",
            [
                Issue(
                    "CANONICAL_FILE_UNAVAILABLE",
                    "contract.canonicalPath",
                    "The canonical file cannot be read.",
                )
            ],
            None,
            [],
        )
    if actual_sha256.lower() != canonical_sha256.lower():
        return _result(
            "blocked",
            [
                Issue(
                    "CANONICAL_SHA256_MISMATCH",
                    "contract.canonicalSha256",
                    "The canonical hash does not match the canonical file.",
                )
            ],
            None,
            [],
        )

    technical_issues = [
        Issue(
            "TECHNICAL_CANNOT_GRANT_VISUAL_PASS",
            f"verdicts[{index}]",
            "Technical verdicts may report diagnostics but cannot grant visual pass.",
        )
        for index, verdict in enumerate(verdicts)
        if verdict["gate"] == "technical" and verdict["decision"] == "pass"
    ]
    if contract["technicalStatus"] != "pass":
        return _result(
            "identity-candidate",
            technical_issues
            + [
                Issue(
                    "TECHNICAL_STATUS_NOT_PASS",
                    "contract.technicalStatus",
                    "Technical status must pass before visual selection.",
                )
            ],
            actual_sha256,
            [],
        )

    matching_indexes = {
        reviewer_type: [
            index
            for index, verdict in enumerate(verdicts)
            if _accepted_visual_verdict(
                verdict,
                actual_sha256,
                reviewer_type=reviewer_type,
            )
        ]
        for reviewer_type in ("builder", "independent", "user")
    }
    builder_indexes = matching_indexes["builder"]
    independent_indexes = matching_indexes["independent"]
    user_indexes = matching_indexes["user"]
    review_pair = next(
        (
            (builder_index, independent_index)
            for independent_index in independent_indexes
            for builder_index in builder_indexes
            if builder_index < independent_index
        ),
        None,
    )
    if not builder_indexes:
        technical_issues.append(
            Issue(
                "BUILDER_SELF_REVIEW_PASS_REQUIRED",
                "verdicts",
                "A matching builder actual-size self-review pass is required.",
            )
        )
    if not independent_indexes:
        technical_issues.append(
            Issue(
                "INDEPENDENT_VISUAL_PASS_REQUIRED_BEFORE_USER_HANDOFF",
                "verdicts",
                "A matching independent internal visual pass is required before user handoff.",
            )
        )
    elif builder_indexes and review_pair is None:
        technical_issues.append(
            Issue(
                "INTERNAL_VISUAL_REVIEW_ORDER_INVALID",
                "verdicts",
                "Builder self-review must pass before independent internal review.",
            )
        )
    if user_indexes and (
        review_pair is None or any(index < review_pair[1] for index in user_indexes)
    ):
        technical_issues.append(
            Issue(
                "USER_HANDOFF_PRECEDED_INTERNAL_VISUAL_PASS",
                f"verdicts[{user_indexes[0]}]",
                "User handoff cannot precede the builder and independent internal visual passes.",
            )
        )
    if review_pair is not None and not any(
        index < review_pair[1] for index in user_indexes
    ):
        accepted_verdict_ids = [
            verdicts[review_pair[0]]["verdictId"],
            verdicts[review_pair[1]]["verdictId"],
        ]
        return _result(
            "identity-selected",
            technical_issues,
            actual_sha256,
            accepted_verdict_ids,
        )
    return _result("visual-candidate", technical_issues, actual_sha256, [])


def _nonempty_text(value: object) -> bool:
    return _is_utf8_text(value) and bool(value.strip())


def _nonempty_string_list(value: object) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(_nonempty_text(item) for item in value)
    )


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256_PATTERN.fullmatch(value) is not None


def _optional_sha256(value: object) -> bool:
    return value is None or _valid_sha256(value)


def _optional_verdict_id(value: object) -> bool:
    return value is None or _nonempty_text(value)


def _lifecycle_values(
    phases: list[dict[str, object]], field: str, accepted: set[str]
) -> list[str]:
    return [
        stage
        for phase in phases
        if isinstance((stage := phase.get(field)), str)
        and stage in accepted
        and stage != "absent"
    ]


def _is_non_decreasing(values: list[str], ranks: dict[str, int]) -> bool:
    return all(
        previous in ranks and current in ranks and ranks[previous] <= ranks[current]
        for previous, current in zip(values, values[1:])
    )


def _is_nonnegative_finite_number(value: object) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value >= 0
    return isinstance(value, float) and math.isfinite(value) and value >= 0


def _is_positive_finite_number(value: object) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value > 0
    return isinstance(value, float) and math.isfinite(value) and value > 0


def _is_nonnegative_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_positive_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_exact_boolean(value: object) -> bool:
    return type(value) is bool


def _selected_contract(contract: dict[str, object]) -> bool:
    return contract.get("selection") == "selected"


def _has_semantic_return_phase(contract: dict[str, object]) -> bool:
    phases = contract.get("phases")
    return isinstance(phases, list) and any(
        isinstance(phase, dict)
        and isinstance(phase.get("id"), str)
        and phase["id"].lower().startswith("return")
        for phase in phases
    )


def _movement_contract_required(
    contract: dict[str, object], behavior: dict[str, object]
) -> bool:
    family = contract.get("family")
    risk_class = contract.get("riskClass")
    world_motion = contract.get("worldMotionPhaseIds")
    labels = " ".join(
        value.lower()
        for value in (family, risk_class)
        if isinstance(value, str)
    )
    return (
        "movement" in labels
        or "locomotion" in labels
        or isinstance(world_motion, list) and bool(world_motion)
        or behavior.get("movement") is not None
    )


def _valid_cooldown_exception(value: object) -> bool:
    return (
        isinstance(value, dict)
        and _nonempty_text(value.get("runtimeRoute"))
        and _nonempty_text(value.get("reason"))
        and _valid_sha256(value.get("evidenceSha256"))
    )


def _validate_behavior_contract_fields(
    contract: dict[str, object], *, require_selected_fields: bool
) -> list[Issue]:
    """Validate one action's scheduler slice after structural preflight.

    Candidate contracts may deliberately retain explicit null/empty draft fields.
    A selected contract must make every applicable scheduler decision explicit.
    """
    issues: list[Issue] = []
    behavior = contract.get("behavior")
    if not isinstance(behavior, dict):
        return [
            Issue(
                "ACTION_BEHAVIOR_INVALID",
                "contract.behavior",
                "behavior must be an object.",
            )
        ]

    manual_eligible = behavior.get("manualEligible")
    autoplay_eligible = behavior.get("autoplayEligible")
    for field, value in (
        ("manualEligible", manual_eligible),
        ("autoplayEligible", autoplay_eligible),
    ):
        if not _is_exact_boolean(value):
            issues.append(
                Issue(
                    "ACTION_BEHAVIOR_BOOLEAN_INVALID",
                    f"contract.behavior.{field}",
                    f"{field} must be true or false.",
                )
            )

    pool = behavior.get("pool")
    weight = behavior.get("weight")
    if autoplay_eligible is True:
        if not _nonempty_text(pool):
            issues.append(
                Issue(
                    "BEHAVIOR_AUTOPLAY_POOL_REQUIRED",
                    "contract.behavior.pool",
                    "Autoplay-eligible actions need a non-empty scheduler pool.",
                )
            )
        if not _is_positive_finite_number(weight):
            issues.append(
                Issue(
                    "ACTION_BEHAVIOR_NUMBER_INVALID",
                    "contract.behavior.weight",
                    "Autoplay-eligible actions need a positive finite weight.",
                )
            )
    elif autoplay_eligible is False:
        if pool is not None:
            issues.append(
                Issue(
                    "BEHAVIOR_AUTOPLAY_POOL_FORBIDDEN",
                    "contract.behavior.pool",
                    "A non-autoplay action must not retain a scheduler pool.",
                )
            )
        if weight is not None:
            issues.append(
                Issue(
                    "BEHAVIOR_AUTOPLAY_WEIGHT_FORBIDDEN",
                    "contract.behavior.weight",
                    "A non-autoplay action must not retain a scheduler weight.",
                )
            )
    else:
        if pool is not None and not _nonempty_text(pool):
            issues.append(
                Issue(
                    "ACTION_BEHAVIOR_TEXT_REQUIRED",
                    "contract.behavior.pool",
                    "pool must be null or non-empty text.",
                )
            )
        if weight is not None and not _is_positive_finite_number(weight):
            issues.append(
                Issue(
                    "ACTION_BEHAVIOR_NUMBER_INVALID",
                    "contract.behavior.weight",
                    "weight must be null or a positive finite number.",
                )
            )

    cooldown = behavior.get("cooldownMs")
    if cooldown is not None and not _is_nonnegative_integer(cooldown):
        issues.append(
            Issue(
                "ACTION_BEHAVIOR_NUMBER_INVALID",
                "contract.behavior.cooldownMs",
                "cooldownMs must be null or a non-negative integer.",
            )
        )
    shared_group = behavior.get("sharedGroup")
    if shared_group is not None and not _nonempty_text(shared_group):
        issues.append(
            Issue(
                "ACTION_BEHAVIOR_TEXT_REQUIRED",
                "contract.behavior.sharedGroup",
                "sharedGroup must be null or non-empty text.",
            )
        )

    repeat_limit = behavior.get("repeatLimit")
    if require_selected_fields and repeat_limit is None:
        issues.append(
            Issue(
                "BEHAVIOR_REPEAT_LIMIT_REQUIRED",
                "contract.behavior.repeatLimit",
                "Selected contracts must record a positive repeatLimit.",
            )
        )
    elif repeat_limit is not None and not _is_positive_integer(repeat_limit):
        issues.append(
            Issue(
                "BEHAVIOR_REPEAT_LIMIT_INVALID",
                "contract.behavior.repeatLimit",
                "repeatLimit must be a positive non-boolean integer.",
            )
        )

    priority = behavior.get("priority")
    if require_selected_fields and priority is None:
        issues.append(
            Issue(
                "BEHAVIOR_PRIORITY_REQUIRED",
                "contract.behavior.priority",
                "Selected contracts must record a bounded priority.",
            )
        )
    elif priority is not None and not (
        isinstance(priority, int)
        and not isinstance(priority, bool)
        and _SCHEDULER_PRIORITY_MIN <= priority <= _SCHEDULER_PRIORITY_MAX
    ):
        issues.append(
            Issue(
                "BEHAVIOR_PRIORITY_INVALID",
                "contract.behavior.priority",
                "priority must be an integer from -100 through 100.",
            )
        )

    environmental_conditions = behavior.get("environmentalConditions")
    if require_selected_fields and environmental_conditions is None:
        issues.append(
            Issue(
                "BEHAVIOR_ENVIRONMENT_REQUIRED",
                "contract.behavior.environmentalConditions",
                "Selected contracts must use an explicit environment list, even when empty.",
            )
        )
    elif environmental_conditions is not None:
        if not isinstance(environmental_conditions, list):
            issues.append(
                Issue(
                    "BEHAVIOR_ENVIRONMENT_INVALID",
                    "contract.behavior.environmentalConditions",
                    "environmentalConditions must be a list of non-empty UTF-8 text.",
                )
            )
        else:
            seen_conditions: set[str] = set()
            for index, condition in enumerate(environmental_conditions):
                path = f"contract.behavior.environmentalConditions[{index}]"
                if not _nonempty_text(condition):
                    issues.append(
                        Issue(
                            "BEHAVIOR_ENVIRONMENT_INVALID",
                            path,
                            "environmentalConditions must contain non-empty UTF-8 text.",
                        )
                    )
                elif condition in seen_conditions:
                    issues.append(
                        Issue(
                            "BEHAVIOR_ENVIRONMENT_DUPLICATE",
                            path,
                            "environmentalConditions must not repeat a condition.",
                        )
                    )
                else:
                    seen_conditions.add(condition)

    cooldown_exception = behavior.get("cooldownException")
    if cooldown_exception is not None and not _valid_cooldown_exception(cooldown_exception):
        issues.append(
            Issue(
                "BEHAVIOR_COOLDOWN_EXCEPTION_INVALID",
                "contract.behavior.cooldownException",
                "cooldownException needs runtimeRoute, concrete reason, and evidenceSha256.",
            )
        )
    if contract.get("riskClass") == "large-effect":
        has_cooldown_or_group = _is_positive_integer(cooldown) or _nonempty_text(
            shared_group
        )
        if not has_cooldown_or_group and not _valid_cooldown_exception(cooldown_exception):
            issues.append(
                Issue(
                    "BEHAVIOR_LARGE_EFFECT_COOLDOWN_REQUIRED",
                    "contract.behavior",
                    "large-effect actions need a positive cooldown, shared group, or hash-bound route exception.",
                )
            )

    movement_required = _movement_contract_required(contract, behavior)
    direction = behavior.get("direction")
    if movement_required and require_selected_fields:
        if direction not in {"left", "right"}:
            issues.append(
                Issue(
                    "BEHAVIOR_MOVEMENT_DIRECTION_INVALID",
                    "contract.behavior.direction",
                    "Movement actions need direction left or right.",
                )
            )
        world_motion = contract.get("worldMotionPhaseIds")
        if not _nonempty_string_list(world_motion):
            issues.append(
                Issue(
                    "BEHAVIOR_MOVEMENT_PHASES_REQUIRED",
                    "contract.worldMotionPhaseIds",
                    "Movement actions need one or more world-motion phases.",
                )
            )

    movement = behavior.get("movement")
    if movement is not None and not isinstance(movement, dict):
        issues.append(
            Issue(
                "BEHAVIOR_MOVEMENT_INVALID",
                "contract.behavior.movement",
                "movement must be null or an object.",
            )
        )
    if movement_required and require_selected_fields and not isinstance(movement, dict):
        issues.append(
            Issue(
                "BEHAVIOR_MOVEMENT_REQUIRED",
                "contract.behavior.movement",
                "Selected movement actions need a movement object.",
            )
        )
    if isinstance(movement, dict):
        basis = movement.get("distanceBasis")
        screen_fraction = movement.get("screenFraction")
        runtime_formula = movement.get("runtimeFormula")
        runtime_evidence = movement.get("runtimeEvidenceSha256")
        boundary_policy = movement.get("boundaryPolicy")
        if movement_required and require_selected_fields and basis not in {
            "usable-screen-relative",
            "runtime-derived",
        }:
            issues.append(
                Issue(
                    "BEHAVIOR_MOVEMENT_DISTANCE_BASIS_INVALID",
                    "contract.behavior.movement.distanceBasis",
                    "distanceBasis must be usable-screen-relative or runtime-derived.",
                )
            )
        if basis == "usable-screen-relative":
            if not (
                _is_positive_finite_number(screen_fraction)
                and screen_fraction <= 1
            ):
                issues.append(
                    Issue(
                        "BEHAVIOR_MOVEMENT_SCREEN_FRACTION_REQUIRED",
                        "contract.behavior.movement.screenFraction",
                        "usable-screen-relative movement needs a screenFraction in (0, 1].",
                    )
                )
            if runtime_formula is not None or runtime_evidence is not None:
                issues.append(
                    Issue(
                        "BEHAVIOR_MOVEMENT_DISTANCE_CONTRADICTORY",
                        "contract.behavior.movement",
                        "A screen-relative distance must not also declare runtime-derived evidence.",
                    )
                )
        elif basis == "runtime-derived":
            if not _nonempty_text(runtime_formula) or not _valid_sha256(runtime_evidence):
                issues.append(
                    Issue(
                        "BEHAVIOR_MOVEMENT_RUNTIME_EVIDENCE_REQUIRED",
                        "contract.behavior.movement",
                        "runtime-derived movement needs a formula and evidenceSha256.",
                    )
                )
            if screen_fraction is not None:
                issues.append(
                    Issue(
                        "BEHAVIOR_MOVEMENT_DISTANCE_CONTRADICTORY",
                        "contract.behavior.movement",
                        "A runtime-derived distance must not also declare screenFraction.",
                    )
                )
        if movement_required and require_selected_fields and not _nonempty_text(
            boundary_policy
        ):
            issues.append(
                Issue(
                    "BEHAVIOR_MOVEMENT_BOUNDARY_REQUIRED",
                    "contract.behavior.movement.boundaryPolicy",
                    "Movement actions need a non-empty boundary policy.",
                )
            )

    if movement_required and require_selected_fields:
        interrupt = contract.get("interrupt")
        safe_phases = interrupt.get("safePhaseIds") if isinstance(interrupt, dict) else None
        if not _nonempty_string_list(safe_phases):
            issues.append(
                Issue(
                    "BEHAVIOR_MOVEMENT_INTERRUPTION_REQUIRED",
                    "contract.interrupt.safePhaseIds",
                    "Movement actions need at least one safe interruption phase.",
                )
            )
        recovery_action = interrupt.get("recoveryAction") if isinstance(interrupt, dict) else None
        if not _nonempty_text(recovery_action) and not _has_semantic_return_phase(contract):
            issues.append(
                Issue(
                    "BEHAVIOR_MOVEMENT_RECOVERY_REQUIRED",
                    "contract.interrupt.recoveryAction",
                    "Movement actions need a recovery action or semantic return phase.",
                )
            )
    return issues


def validate_behavior_contract(contract: dict[str, object]) -> list[Issue]:
    """Validate scheduler policy without deriving target values from past pets."""
    structural_issues = validate_json_structure(contract, "contract")
    if _structural_issues_block_field_validation(structural_issues):
        return structural_issues
    if not isinstance(contract, dict):
        return structural_issues + [
            Issue(
                "BEHAVIOR_CONTRACT_INVALID",
                "contract",
                "Behavior contracts must be JSON objects.",
            )
        ]
    return structural_issues + _validate_behavior_contract_fields(
        contract, require_selected_fields=_selected_contract(contract)
    )


def validate_action_contract(contract: dict[str, object]) -> list[Issue]:
    """Validate semantic action requirements without imposing frame-count quotas."""
    structural_issues = validate_json_structure(contract, "contract")
    if _structural_issues_block_field_validation(structural_issues):
        return structural_issues
    if not isinstance(contract, dict):
        return structural_issues + [
            Issue(
                "ACTION_CONTRACT_INVALID",
                "contract",
                "Action contracts must be JSON objects.",
            )
        ]

    issues = structural_issues
    if type(contract.get("schemaVersion")) is not int or contract.get(
        "schemaVersion"
    ) != 1:
        issues.append(
            Issue(
                "ACTION_SCHEMA_VERSION_INVALID",
                "contract.schemaVersion",
                "schemaVersion must be 1.",
            )
        )
    for field in ("actionId", "family", "riskClass", "desktopRole"):
        if not _nonempty_text(contract.get(field)):
            issues.append(
                Issue(
                    "ACTION_TEXT_FIELD_REQUIRED",
                    f"contract.{field}",
                    f"{field} must be non-empty text.",
                )
            )
    if not _valid_sha256(contract.get("identitySha256")):
        issues.append(
            Issue(
                "ACTION_IDENTITY_SHA256_INVALID",
                "contract.identitySha256",
                "identitySha256 must be a 64-character SHA-256 string.",
            )
        )
    if not _text_is_one_of(contract.get("selection"), {"candidate", "selected"}):
        issues.append(
            Issue(
                "ACTION_SELECTION_INVALID",
                "contract.selection",
                "selection must be candidate or selected.",
            )
        )
    for field in ("stableFeatures", "allowedChanges", "forbiddenChanges"):
        if not _nonempty_string_list(contract.get(field)):
            issues.append(
                Issue(
                    "ACTION_SEMANTIC_LIST_INVALID",
                    f"contract.{field}",
                    f"{field} must be a non-empty list of non-empty text values.",
                )
            )

    phase_value = contract.get("phases")
    phases: list[dict[str, object]] = []
    phase_ids: set[str] = set()
    phase_by_id: dict[str, dict[str, object]] = {}
    if not isinstance(phase_value, list) or not phase_value:
        issues.append(
            Issue(
                "ACTION_PHASES_REQUIRED",
                "contract.phases",
                "phases must contain one or more semantic phase objects.",
            )
        )
    else:
        for index, phase in enumerate(phase_value):
            path = f"contract.phases[{index}]"
            if not isinstance(phase, dict):
                issues.append(
                    Issue(
                        "ACTION_PHASE_INVALID",
                        path,
                        "Each phase must be a JSON object.",
                    )
                )
                continue
            phases.append(phase)
            phase_id = phase.get("id")
            if not _nonempty_text(phase_id):
                issues.append(
                    Issue(
                        "ACTION_PHASE_ID_INVALID",
                        f"{path}.id",
                        "Each phase id must be non-empty text.",
                    )
                )
            elif phase_id in phase_ids:
                issues.append(
                    Issue(
                        "ACTION_PHASE_ID_DUPLICATE",
                        f"{path}.id",
                        "Phase ids must be unique.",
                    )
                )
            else:
                phase_ids.add(phase_id)
                phase_by_id[phase_id] = phase
            for field in (
                "bodyState",
                "faceState",
                "handState",
                "hairGarmentState",
                "propEffectState",
            ):
                if not _nonempty_text(phase.get(field)):
                    issues.append(
                        Issue(
                            "ACTION_PHASE_SEMANTICS_REQUIRED",
                            f"{path}.{field}",
                            f"{field} must be non-empty text.",
                        )
                    )
            for field, accepted in (
                ("propLifecycleStage", _PROP_LIFECYCLE_STAGES),
                ("effectLifecycleStage", _EFFECT_LIFECYCLE_STAGES),
            ):
                stage = phase.get(field)
                if stage is not None and (
                    not isinstance(stage, str) or stage not in accepted
                ):
                    issues.append(
                        Issue(
                            "ACTION_LIFECYCLE_STAGE_INVALID",
                            f"{path}.{field}",
                            f"{field} must be null or one of the structured lifecycle stages.",
                        )
                    )
            if not _text_is_one_of(phase.get("anchor"), {"body", "world"}):
                issues.append(
                    Issue(
                        "ACTION_PHASE_ANCHOR_INVALID",
                        f"{path}.anchor",
                        "anchor must be body or world.",
                    )
                )
            duration = phase.get("durationMs")
            if (
                not isinstance(duration, int)
                or isinstance(duration, bool)
                or duration <= 0
            ):
                issues.append(
                    Issue(
                        "ACTION_PHASE_DURATION_INVALID",
                        f"{path}.durationMs",
                        "durationMs must be a positive integer.",
                    )
                )
            if not isinstance(phase.get("keyPose"), bool):
                issues.append(
                    Issue(
                        "ACTION_PHASE_KEY_POSE_INVALID",
                        f"{path}.keyPose",
                        "keyPose must be true or false.",
                    )
                )

    world_motion = contract.get("worldMotionPhaseIds")
    if not _string_list(world_motion):
        issues.append(
            Issue(
                "WORLD_MOTION_PHASE_IDS_INVALID",
                "contract.worldMotionPhaseIds",
                "worldMotionPhaseIds must be a list of text phase ids.",
            )
        )
    else:
        for phase_id in world_motion:
            phase = phase_by_id.get(phase_id)
            if phase is None:
                issues.append(
                    Issue(
                        "WORLD_MOTION_PHASE_UNKNOWN",
                        "contract.worldMotionPhaseIds",
                        "Every world-motion phase must exist in phases.",
                    )
                )
            elif phase.get("anchor") != "world":
                issues.append(
                    Issue(
                        "WORLD_MOTION_ANCHOR_MISMATCH",
                        "contract.worldMotionPhaseIds",
                        "Every listed world-motion phase must use the world anchor.",
                    )
                )
        for phase_id, phase in phase_by_id.items():
            if phase.get("anchor") == "world" and phase_id not in world_motion:
                issues.append(
                    Issue(
                        "WORLD_MOTION_PHASE_MISSING",
                        "contract.worldMotionPhaseIds",
                        "Every world-anchored phase must be listed as world motion.",
                    )
                )

    interrupt = contract.get("interrupt")
    has_return_phase = any(
        isinstance(phase.get("id"), str)
        and phase["id"].lower().startswith("return")
        for phase in phases
    )
    has_recovery_action = isinstance(interrupt, dict) and _nonempty_text(
        interrupt.get("recoveryAction")
    )
    if not has_return_phase and not has_recovery_action:
        issues.append(
            Issue(
                "RECOVERY_REQUIRED",
                "contract.interrupt",
                "An action needs a semantic return phase or a recovery action.",
            )
        )
    if not isinstance(interrupt, dict) or not _string_list(
        interrupt.get("safePhaseIds")
    ):
        issues.append(
            Issue(
                "INTERRUPT_INVALID",
                "contract.interrupt",
                "interrupt.safePhaseIds must be a list of text phase ids.",
            )
        )
    elif any(phase_id not in phase_by_id for phase_id in interrupt["safePhaseIds"]):
        issues.append(
            Issue(
                "INTERRUPT_SAFE_PHASE_UNKNOWN",
                "contract.interrupt.safePhaseIds",
                "Every safe phase id must exist in phases.",
            )
        )

    issues.extend(
        _validate_behavior_contract_fields(
            contract, require_selected_fields=_selected_contract(contract)
        )
    )

    if "locomotion" in str(contract.get("family", "")) or "locomotion" in str(
        contract.get("riskClass", "")
    ):
        locomotion_key_poses = {
            phase.get("bodyState")
            for phase in phases
            if phase.get("keyPose") is True and _nonempty_text(phase.get("bodyState"))
        }
        if len(locomotion_key_poses) < 2:
            issues.append(
                Issue(
                    "LOCOMOTION_KEY_POSES_REQUIRED",
                    "contract.phases",
                    "Locomotion requires distinct semantic key poses, not repeated standing frames.",
                )
            )

    prop_values = _lifecycle_values(
        phases, "propLifecycleStage", _PROP_LIFECYCLE_STAGES
    )
    if prop_values:
        prop_ranks = {
            "introduced": 0,
            "acquired": 1,
            "used": 2,
            "released": 3,
            "consumed": 3,
        }
        if (
            prop_values[0] != "introduced"
            or prop_values[-1] not in {"released", "consumed"}
            or not _is_non_decreasing(prop_values, prop_ranks)
        ):
            issues.append(
                Issue(
                    "PROP_LIFECYCLE_INCOMPLETE",
                    "contract.phases",
                    "A non-null prop lifecycle must begin with introduced and end coherently.",
                )
            )

    effect_values = _lifecycle_values(
        phases, "effectLifecycleStage", _EFFECT_LIFECYCLE_STAGES
    )
    if effect_values:
        effect_ranks = {
            "origin": 0,
            "growth": 1,
            "travel": 2,
            "peak": 3,
            "decay": 4,
            "cleanup": 5,
        }
        has_peak = "peak" in effect_values
        if (
            effect_values[0] != "origin"
            or effect_values[-1] != "cleanup"
            or not _is_non_decreasing(effect_values, effect_ranks)
            or (has_peak and not {"origin", "decay", "cleanup"}.issubset(effect_values))
        ):
            issues.append(
                Issue(
                    "EFFECT_LIFECYCLE_INCOMPLETE",
                    "contract.phases",
                    "A non-null effect lifecycle must begin, peak, decay, and clean up coherently.",
                )
            )
    return issues


def _maturity_defaults(blockers: set[str] | None = None) -> dict[str, object]:
    return {
        "maturity": _MATURITY_STAGES[0],
        "technicalStatus": "unverified",
        "visualStatus": "not-reviewed",
        "packageStatus": "not-packaged",
        "runtimeStatus": "unverified",
        "installedStatus": "not-authorized",
        "internalVisualPasses": [],
        "userAcceptance": [],
        "authorities": {
            "install": False,
            "integrate": False,
            "commit": False,
            "push": False,
            "publish": False,
        },
        "releaseAuthority": False,
        "blockers": sorted(blockers or set()),
        "unverifiedChecks": ["formal gates", "runtime Registry and Catalog"],
    }


def _authority_value(
    run: dict[str, object],
    *,
    field: str,
    legacy_field: str,
    blockers: set[str],
) -> bool:
    values: list[object] = []
    if field in run:
        values.append(run[field])
    for container_name in ("authorities", "authority"):
        container = run.get(container_name)
        if container is None:
            continue
        if not isinstance(container, dict):
            blockers.add("AUTHORITY_CONTAINER_INVALID")
            continue
        if legacy_field in container:
            values.append(container[legacy_field])
    if not values:
        return False
    if not all(_is_exact_boolean(value) for value in values):
        blockers.add(f"AUTHORITY_TYPE_INVALID:{legacy_field}")
        return False
    if any(value is not values[0] for value in values[1:]):
        blockers.add(f"AUTHORITY_CONFLICT:{legacy_field}")
        return False
    return values[0] is True


def _normalized_artifact_path(value: object) -> str | None:
    if not _nonempty_text(value) or "\\" in value or "\x00" in value:
        return None
    candidate = PurePosixPath(value)
    if (
        candidate.is_absolute()
        or candidate.as_posix() != value
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        return None
    return value


def _verified_artifact_index(
    run: dict[str, object], blockers: set[str]
) -> dict[str, str] | None:
    """Return the caller-proven path-to-hash context, never a syntax-only grant."""
    if "verifiedArtifactIndex" not in run:
        return None
    raw_index = run.get("verifiedArtifactIndex")
    if not isinstance(raw_index, dict):
        blockers.add("VERIFIED_ARTIFACT_CONTEXT_INVALID")
        return None
    index: dict[str, str] = {}
    invalid = False
    for raw_path, raw_hash in raw_index.items():
        path = _normalized_artifact_path(raw_path)
        if path is None or not _valid_sha256(raw_hash):
            blockers.add("VERIFIED_ARTIFACT_CONTEXT_INVALID")
            invalid = True
            continue
        index[path] = raw_hash.lower()
    return None if invalid else index


def _runtime_evidence_state(
    value: object,
    *,
    verified_artifacts: dict[str, str] | None,
    blockers: set[str],
) -> tuple[bool, str | None]:
    if not isinstance(value, list):
        blockers.add("RUNTIME_EVIDENCE_INVALID")
        return False, None
    records_by_kind: dict[str, dict[str, object]] = {}
    evidence_hashes: set[str] = set()
    package_hashes: set[str] = set()
    invalid = False
    for index, record in enumerate(value):
        prefix = f"RUNTIME_EVIDENCE_{index}"
        if not isinstance(record, dict):
            blockers.add(f"{prefix}_INVALID")
            invalid = True
            continue
        kind = record.get("kind")
        status = record.get("status")
        package_sha = record.get("packageSha256")
        evidence_sha = record.get("evidenceSha256")
        if kind not in _RUNTIME_EVIDENCE_KINDS:
            blockers.add(f"{prefix}_KIND_INVALID")
            invalid = True
            continue
        if kind in records_by_kind:
            blockers.add("RUNTIME_EVIDENCE_DUPLICATE")
            invalid = True
            continue
        records_by_kind[kind] = record
        if status != "pass":
            blockers.add(f"{prefix}_STATUS_INVALID")
            invalid = True
        if "stale" in record and not _is_exact_boolean(record.get("stale")):
            blockers.add(f"{prefix}_STALE_INVALID")
            invalid = True
        elif record.get("stale") is True:
            blockers.add(f"{prefix}_STATUS_INVALID")
            invalid = True
        if not _valid_sha256(package_sha) or not _valid_sha256(evidence_sha):
            blockers.add(f"{prefix}_HASH_INVALID")
            invalid = True
            continue
        package_hashes.add(package_sha.lower())
        normalized_evidence = evidence_sha.lower()
        if normalized_evidence in evidence_hashes:
            blockers.add("RUNTIME_EVIDENCE_SHA_DUPLICATE")
            invalid = True
        evidence_hashes.add(normalized_evidence)
    if set(records_by_kind) != _RUNTIME_EVIDENCE_KINDS:
        if records_by_kind:
            blockers.add("RUNTIME_EVIDENCE_PARTIAL")
        return False, None
    if len(package_hashes) != 1:
        blockers.add("RUNTIME_EVIDENCE_PACKAGE_MISMATCH")
        return False, None
    package_sha = next(iter(package_hashes))
    if verified_artifacts is None:
        blockers.add("VERIFIED_ARTIFACT_CONTEXT_REQUIRED")
        return False, None
    verified_hashes = set(verified_artifacts.values())
    for index, record in enumerate(value):
        if not isinstance(record, dict):
            continue
        package = record.get("packageSha256")
        evidence = record.get("evidenceSha256")
        if (
            not _valid_sha256(package)
            or not _valid_sha256(evidence)
            or package.lower() not in verified_hashes
            or evidence.lower() not in verified_hashes
        ):
            blockers.add(f"RUNTIME_EVIDENCE_{index}_HASH_UNVERIFIED")
            invalid = True
    return not invalid, package_sha if not invalid else None


def _installation_evidence_valid(
    value: object,
    package_sha: str,
    verified_artifacts: dict[str, str] | None,
    blockers: set[str],
) -> bool:
    if not isinstance(value, list) or not value:
        return False
    seen_evidence: set[str] = set()
    valid_records = 0
    invalid = False
    if verified_artifacts is None:
        blockers.add("VERIFIED_ARTIFACT_CONTEXT_REQUIRED")
        return False
    verified_hashes = set(verified_artifacts.values())
    for index, record in enumerate(value):
        prefix = f"INSTALLATION_EVIDENCE_{index}"
        if not isinstance(record, dict):
            blockers.add(f"{prefix}_INVALID")
            invalid = True
            continue
        if record.get("kind") != "installation" or record.get("status") != "pass":
            blockers.add(f"{prefix}_STATUS_INVALID")
            invalid = True
            continue
        if "stale" in record and not _is_exact_boolean(record.get("stale")):
            blockers.add(f"{prefix}_STALE_INVALID")
            invalid = True
            continue
        if record.get("stale") is True:
            blockers.add(f"{prefix}_STATUS_INVALID")
            invalid = True
            continue
        evidence_sha = record.get("evidenceSha256")
        record_package = record.get("packageSha256")
        if not _valid_sha256(evidence_sha) or not _valid_sha256(record_package):
            blockers.add(f"{prefix}_HASH_INVALID")
            invalid = True
            continue
        if record_package.lower() != package_sha:
            blockers.add("INSTALLATION_EVIDENCE_PACKAGE_MISMATCH")
            invalid = True
            continue
        if (
            record_package.lower() not in verified_hashes
            or evidence_sha.lower() not in verified_hashes
        ):
            blockers.add(f"{prefix}_HASH_UNVERIFIED")
            invalid = True
            continue
        normalized_evidence = evidence_sha.lower()
        if normalized_evidence in seen_evidence:
            blockers.add("INSTALLATION_EVIDENCE_DUPLICATE")
            invalid = True
            continue
        seen_evidence.add(normalized_evidence)
        valid_records += 1
    return valid_records > 0 and not invalid


def _valid_user_acceptance(
    value: object,
    verified_artifacts: dict[str, str] | None,
    internal_visual_passes: list[dict[str, object]],
    formal_gates_pass: bool,
    blockers: set[str],
) -> list[dict[str, object]]:
    if value is None:
        return []
    if not isinstance(value, list):
        blockers.add("USER_ACCEPTANCE_INVALID")
        return []
    accepted: list[dict[str, object]] = []
    seen: set[tuple[str, str, str, str, str, int]] = set()
    seen_sequences: set[int] = set()
    for index, record in enumerate(value):
        if not isinstance(record, dict):
            blockers.add(f"USER_ACCEPTANCE_{index}_INVALID")
            continue
        artifact_path = record.get("artifactPath")
        artifact_sha = record.get("artifactSha256")
        gate = record.get("gate")
        decision = record.get("decision")
        reviewer = record.get("reviewer")
        review_sequence = record.get("reviewSequence")
        normalized_path = _normalized_artifact_path(artifact_path)
        if not (
            normalized_path is not None
            and _valid_sha256(artifact_sha)
            and _is_utf8_text(gate)
            and gate in _USER_ACCEPTANCE_GATES
            and _is_utf8_text(decision)
            and decision in _USER_ACCEPTANCE_DECISIONS
            and _nonempty_text(reviewer)
            and _is_positive_integer(review_sequence)
        ):
            blockers.add(f"USER_ACCEPTANCE_{index}_INVALID")
            continue
        if verified_artifacts is None:
            blockers.add("VERIFIED_ARTIFACT_CONTEXT_REQUIRED")
            continue
        if verified_artifacts.get(normalized_path) != artifact_sha.lower():
            blockers.add(f"USER_ACCEPTANCE_{index}_ARTIFACT_UNVERIFIED")
            continue
        if not formal_gates_pass:
            blockers.add("INTERNAL_VISUAL_PASS_REQUIRED_BEFORE_USER_ACCEPTANCE")
            continue
        matching_passes = [
            internal_pass
            for internal_pass in internal_visual_passes
            if internal_pass["artifactPath"] == normalized_path
            and internal_pass["artifactSha256"] == artifact_sha.lower()
            and internal_pass["gate"] == gate
        ]
        matching_reviewers = {
            internal_pass["reviewer"] for internal_pass in matching_passes
        }
        if matching_reviewers != {"builder", "independent"}:
            blockers.add(f"USER_ACCEPTANCE_{index}_INTERNAL_PASS_REQUIRED")
            continue
        builder_sequence = next(
            internal_pass["reviewSequence"]
            for internal_pass in matching_passes
            if internal_pass["reviewer"] == "builder"
        )
        independent_sequence = next(
            internal_pass["reviewSequence"]
            for internal_pass in matching_passes
            if internal_pass["reviewer"] == "independent"
        )
        assert isinstance(builder_sequence, int)
        assert isinstance(independent_sequence, int)
        assert isinstance(review_sequence, int)
        if not builder_sequence < independent_sequence < review_sequence:
            blockers.add(f"USER_ACCEPTANCE_{index}_INTERNAL_REVIEW_ORDER_INVALID")
            continue
        item = (
            normalized_path,
            artifact_sha.lower(),
            gate,
            decision,
            reviewer,
            review_sequence,
        )
        if item in seen or review_sequence in seen_sequences:
            blockers.add("USER_ACCEPTANCE_DUPLICATE")
            continue
        seen.add(item)
        seen_sequences.add(review_sequence)
        accepted.append(
            {
                "artifactPath": normalized_path,
                "artifactSha256": artifact_sha.lower(),
                "gate": gate,
                "decision": decision,
                "reviewer": reviewer,
                "reviewSequence": review_sequence,
            }
        )
    return sorted(
        accepted,
        key=lambda item: (
            item["reviewSequence"],
            item["artifactPath"],
            item["artifactSha256"],
            item["gate"],
            item["decision"],
            item["reviewer"],
        ),
    )


def _valid_internal_visual_passes(
    value: object,
    verified_artifacts: dict[str, str] | None,
    blockers: set[str],
) -> list[dict[str, object]]:
    if value is None:
        return []
    if not isinstance(value, list):
        blockers.add("INTERNAL_VISUAL_PASSES_INVALID")
        return []
    accepted: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    seen_records: set[tuple[str, str, str, str]] = set()
    seen_sequences: set[int] = set()
    for index, record in enumerate(value):
        prefix = f"INTERNAL_VISUAL_PASS_{index}"
        if not isinstance(record, dict):
            blockers.add(f"{prefix}_INVALID")
            continue
        verdict_id = record.get("verdictId")
        artifact_path = record.get("artifactPath")
        artifact_sha = record.get("artifactSha256")
        gate = record.get("gate")
        decision = record.get("decision")
        reviewer = record.get("reviewer")
        review_sequence = record.get("reviewSequence")
        normalized_path = _normalized_artifact_path(artifact_path)
        if not (
            _nonempty_text(verdict_id)
            and normalized_path is not None
            and _valid_sha256(artifact_sha)
            and _is_utf8_text(gate)
            and gate in _USER_ACCEPTANCE_GATES
            and decision == "pass"
            and _is_utf8_text(reviewer)
            and reviewer in {"builder", "independent"}
            and _is_positive_integer(review_sequence)
        ):
            blockers.add(f"{prefix}_INVALID")
            continue
        if verified_artifacts is None:
            blockers.add("VERIFIED_ARTIFACT_CONTEXT_REQUIRED")
            continue
        if verified_artifacts.get(normalized_path) != artifact_sha.lower():
            blockers.add(f"{prefix}_ARTIFACT_UNVERIFIED")
            continue
        normalized_id = verdict_id.strip()
        item = (normalized_path, artifact_sha.lower(), gate, reviewer)
        assert isinstance(review_sequence, int)
        if (
            normalized_id in seen_ids
            or item in seen_records
            or review_sequence in seen_sequences
        ):
            blockers.add("INTERNAL_VISUAL_PASS_DUPLICATE")
            continue
        seen_ids.add(normalized_id)
        seen_records.add(item)
        seen_sequences.add(review_sequence)
        accepted.append(
            {
                "verdictId": normalized_id,
                "artifactPath": normalized_path,
                "artifactSha256": artifact_sha.lower(),
                "gate": gate,
                "decision": "pass",
                "reviewer": reviewer,
                "reviewSequence": review_sequence,
            }
        )
    return sorted(
        accepted,
        key=lambda item: (
            item["reviewSequence"],
            item["artifactPath"],
            item["artifactSha256"],
            item["gate"],
            item["reviewer"],
            item["verdictId"],
        ),
    )


def evaluate_maturity(run: dict[str, object]) -> dict[str, object]:
    """Evaluate maturity and authorities from evidenced, non-interchangeable gates.

    The function is pure: it produces only new JSON-compatible containers and
    never treats packaging, user acceptance, or evidence as authority.
    """
    structural_issues = validate_json_structure(run, "run")
    if structural_issues or not isinstance(run, dict):
        blockers = {"RUN_MATURITY_INPUT_INVALID"}
        blockers.update(issue.code for issue in structural_issues)
        return _maturity_defaults(blockers)

    blockers: set[str] = set()
    authorities = {
        "install": _authority_value(
            run,
            field="installAuthority",
            legacy_field="install",
            blockers=blockers,
        ),
        "integrate": _authority_value(
            run,
            field="integrationAuthority",
            legacy_field="integrate",
            blockers=blockers,
        ),
        "commit": _authority_value(
            run,
            field="commitAuthority",
            legacy_field="commit",
            blockers=blockers,
        ),
        "push": _authority_value(
            run,
            field="pushAuthority",
            legacy_field="push",
            blockers=blockers,
        ),
        "publish": _authority_value(
            run,
            field="publicationAuthority",
            legacy_field="publish",
            blockers=blockers,
        ),
    }
    formal_gates_pass = run.get("formalGates") == "pass"
    formal_gate_value = run.get("formalGates")
    package_status = run.get("packageStatus")
    if package_status not in {
        "not-packaged",
        "unverified",
        "partial",
        "local-candidate",
        "release-artifact",
        "pass",
    }:
        package_status = "not-packaged"
    technical_status = (
        "pass"
        if formal_gates_pass
        else "partial"
        if formal_gate_value in {"partial", "needs-review"}
        else "unverified"
    )

    verified_artifacts = _verified_artifact_index(run, blockers)
    internal_visual_passes = _valid_internal_visual_passes(
        run.get("internalVisualPasses"), verified_artifacts, blockers
    )
    user_acceptance = _valid_user_acceptance(
        run.get("userAcceptance"),
        verified_artifacts,
        internal_visual_passes,
        formal_gates_pass,
        blockers,
    )
    visual_status = "pass" if formal_gates_pass else "not-reviewed"
    maturity_index = 0
    identity_gate = run.get("identityGateStatus")
    if identity_gate == "identity-candidate":
        maturity_index = 1
    elif identity_gate == "identity-selected":
        maturity_index = 2
    if maturity_index >= 2 and run.get("storyboardGates") == "pass":
        maturity_index = 3
    if formal_gates_pass:
        maturity_index = 4

    runtime_evidence_valid, runtime_package_sha = _runtime_evidence_state(
        run.get("runtimeEvidence", []),
        verified_artifacts=verified_artifacts,
        blockers=blockers,
    )
    runtime_status = "unverified"
    if formal_gates_pass and runtime_evidence_valid and runtime_package_sha is not None:
        runtime_status = "pass"
        maturity_index = 5
    elif runtime_evidence_valid:
        blockers.add("FORMAL_GATES_REQUIRED_FOR_RUNTIME")

    installed_status = "not-authorized" if not authorities["install"] else "unverified"
    if runtime_status == "pass" and authorities["install"]:
        if _installation_evidence_valid(
            run.get("installationEvidence", []),
            runtime_package_sha or "",
            verified_artifacts,
            blockers,
        ):
            installed_status = "pass"
            maturity_index = 6
    elif authorities["install"] and runtime_status != "pass":
        blockers.add("RUNTIME_EVIDENCE_REQUIRED_FOR_INSTALLATION")

    required_minutes = run.get("requiredSoakMinutes")
    observed_minutes = run.get("observedSoakMinutes")
    soak_verdict = run.get("soakVerdict")
    valid_required_minutes = _is_positive_integer(required_minutes)
    valid_observed_minutes = _is_nonnegative_integer(observed_minutes)
    if required_minutes is not None and not valid_required_minutes:
        blockers.add("SOAK_REQUIRED_DURATION_INVALID")
    if observed_minutes is not None and not valid_observed_minutes:
        blockers.add("SOAK_OBSERVED_DURATION_INVALID")
    soak_passes = (
        installed_status == "pass"
        and valid_required_minutes
        and valid_observed_minutes
        and observed_minutes >= required_minutes
        and soak_verdict == "pass"
    )
    if soak_passes:
        maturity_index = 7

    if maturity_index >= 7 and authorities["integrate"] and authorities["publish"]:
        maturity_index = 8

    unverified_checks: list[str] = []
    if not formal_gates_pass:
        unverified_checks.append("formal gates")
    if runtime_status != "pass":
        unverified_checks.append("runtime Registry and Catalog")
    if installed_status != "pass":
        unverified_checks.append("authorized installation evidence")
    if not soak_passes:
        unverified_checks.append("required passing soak")
    if maturity_index < 8:
        unverified_checks.append("integration and publication authority")
    return {
        "maturity": _MATURITY_STAGES[maturity_index],
        "technicalStatus": technical_status,
        "visualStatus": visual_status,
        "packageStatus": package_status,
        "runtimeStatus": runtime_status,
        "installedStatus": installed_status,
        "internalVisualPasses": internal_visual_passes,
        "userAcceptance": user_acceptance,
        "authorities": authorities,
        "releaseAuthority": maturity_index == len(_MATURITY_STAGES) - 1,
        "blockers": sorted(blockers),
        "unverifiedChecks": sorted(unverified_checks),
    }


def _manifest_jobs(manifest: object) -> list[dict[str, object]] | None:
    if not isinstance(manifest, dict):
        return None
    jobs = manifest.get("jobs")
    if not isinstance(jobs, list) or not all(isinstance(job, dict) for job in jobs):
        return None
    return jobs


def _jobs_by_id(jobs: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for job in jobs:
        job_id = job.get("id")
        if _nonempty_text(job_id) and job_id not in result:
            result[job_id] = job
    return result


def _dependency_graph_has_cycle(jobs_by_id: dict[str, dict[str, object]]) -> bool:
    indegree = {job_id: 0 for job_id in jobs_by_id}
    reverse_dependencies = {job_id: [] for job_id in jobs_by_id}
    for job_id, job in jobs_by_id.items():
        dependencies = job.get("dependsOn")
        if not isinstance(dependencies, list):
            continue
        for dependency_id in dependencies:
            if isinstance(dependency_id, str) and dependency_id in jobs_by_id:
                indegree[job_id] += 1
                reverse_dependencies[dependency_id].append(job_id)

    ready = [job_id for job_id, degree in indegree.items() if degree == 0]
    processed = 0
    while ready:
        job_id = ready.pop()
        processed += 1
        for dependent_id in reverse_dependencies[job_id]:
            indegree[dependent_id] -= 1
            if indegree[dependent_id] == 0:
                ready.append(dependent_id)
    return processed != len(jobs_by_id)


def _dependencies_satisfied(
    job: dict[str, object], jobs_by_id: dict[str, dict[str, object]]
) -> bool:
    dependencies = job.get("dependsOn")
    input_hashes = job.get("inputHashes")
    if not isinstance(dependencies, list) or not isinstance(input_hashes, dict):
        return False
    job_canonical_sha256 = job.get("canonicalIdentitySha256")
    if not _valid_sha256(job_canonical_sha256):
        return False
    for dependency_id in dependencies:
        if not isinstance(dependency_id, str):
            return False
        dependency = jobs_by_id.get(dependency_id)
        if dependency is None or dependency.get("status") != "selected":
            return False
        expected_hash = input_hashes.get(dependency_id)
        if expected_hash is not None:
            dependency_artifact_sha256 = dependency.get("artifactSha256")
            if (
                not _valid_sha256(expected_hash)
                or not _valid_sha256(dependency_artifact_sha256)
                or dependency_artifact_sha256.lower() != expected_hash.lower()
            ):
                return False
        dependency_canonical_sha256 = dependency.get("canonicalIdentitySha256")
        if (
            not _valid_sha256(dependency_canonical_sha256)
            or job_canonical_sha256.lower() != dependency_canonical_sha256.lower()
        ):
            return False
    return True


def _is_imported_identity_root(job: dict[str, object]) -> bool:
    artifact_sha256 = job.get("artifactSha256")
    canonical_sha256 = job.get("canonicalIdentitySha256")
    return (
        job.get("importedIdentityRoot") is True
        and job.get("id") == "identity"
        and job.get("kind") == "identity"
        and job.get("status") == "selected"
        and job.get("dependsOn") == []
        and job.get("inputHashes") == {}
        and _valid_sha256(artifact_sha256)
        and _valid_sha256(canonical_sha256)
        and artifact_sha256.lower() == canonical_sha256.lower()
        and job.get("technicalVerdictId") is None
        and _nonempty_text(job.get("visualVerdictId"))
    )


def _valid_causal_evidence(value: object) -> bool:
    if not isinstance(value, list) or not value:
        return False
    for entry in value:
        if not isinstance(entry, dict):
            return False
        input_id = entry.get("inputId")
        before_sha256 = entry.get("beforeSha256")
        after_sha256 = entry.get("afterSha256")
        if (
            not _nonempty_text(input_id)
            or not _valid_sha256(before_sha256)
            or not _valid_sha256(after_sha256)
            or before_sha256.lower() == after_sha256.lower()
        ):
            return False
    return True


def _failure_record_issues(job: dict[str, object], path: str) -> list[Issue]:
    issues: list[Issue] = []
    required_text = (
        "failureClass",
        "rootCondition",
        "changedVariable",
        "nextStrategy",
    )
    if any(not _nonempty_text(job.get(field)) for field in required_text) or not _nonempty_string_list(
        job.get("preserve")
    ):
        issues.append(
            Issue(
                "FAILURE_RECORD_REQUIRED",
                path,
                "Blocked or rejected jobs require a causal failure record.",
            )
        )

    retry_count = job.get("retryCount")
    history = job.get("failureHistory")
    history_entries_valid = isinstance(history, list) and bool(history)
    if history_entries_valid:
        for entry in history:
            if (
                not isinstance(entry, dict)
                or not _nonempty_text(entry.get("failureClass"))
                or not _nonempty_text(entry.get("rootCondition"))
            ):
                history_entries_valid = False
                break
    if (
        not history_entries_valid
        or not isinstance(retry_count, int)
        or isinstance(retry_count, bool)
        or retry_count < 1
        or len(history) != retry_count
    ):
        issues.append(
            Issue(
                "FAILURE_HISTORY_INVALID",
                f"{path}.failureHistory",
                "failureHistory must record one causal class/root-condition pair per retry.",
            )
        )
    elif (
        history[-1].get("failureClass") != job.get("failureClass")
        or history[-1].get("rootCondition") != job.get("rootCondition")
    ):
        issues.append(
            Issue(
                "FAILURE_HISTORY_INVALID",
                f"{path}.failureHistory",
                "The latest failureHistory entry must match the current causal record.",
            )
        )

    strategy_change = job.get("strategyChange")
    strategy_valid = isinstance(strategy_change, dict)
    classification = (
        strategy_change.get("classification") if strategy_valid else None
    )
    causal_inputs = strategy_change.get("causalInputs") if strategy_valid else None
    causal_evidence = (
        strategy_change.get("causalEvidence") if strategy_valid else None
    )
    next_strategy = job.get("nextStrategy")
    expected_classification = (
        _FAILURE_STRATEGY_CLASSIFICATION_BY_CODE.get(next_strategy)
        if isinstance(next_strategy, str)
        else None
    )
    if (
        expected_classification is None
        or classification != expected_classification
    ):
        strategy_valid = False
    elif expected_classification == "prompt-wording-only":
        strategy_valid = isinstance(causal_inputs, list) and not causal_inputs
    else:
        strategy_valid = _nonempty_string_list(causal_inputs)
    if expected_classification == "prompt-wording-only":
        evidence_valid = isinstance(causal_evidence, list) and not causal_evidence
    elif expected_classification in _FAILURE_STRATEGY_CLASSIFICATIONS:
        evidence_valid = _valid_causal_evidence(causal_evidence)
    else:
        evidence_valid = False
    if not strategy_valid:
        issues.append(
            Issue(
                "FAILURE_STRATEGY_INVALID",
                f"{path}.nextStrategy",
                "nextStrategy must be a controlled strategy code with its exact matching classification and inputs.",
            )
        )
    if not evidence_valid:
        issues.append(
            Issue(
                "FAILURE_CAUSAL_EVIDENCE_INVALID",
                f"{path}.strategyChange.causalEvidence",
                "Causal changes require distinct before/after SHA-256 evidence; prompt-only changes require an empty list.",
            )
        )
    if (
        strategy_valid
        and evidence_valid
        and history_entries_valid
        and expected_classification == "prompt-wording-only"
    ):
        recurrence_count = sum(
            entry.get("failureClass") == job.get("failureClass")
            and entry.get("rootCondition") == job.get("rootCondition")
            for entry in history
        )
        if recurrence_count >= 2:
            issues.append(
                Issue(
                    "RECURRENCE_STRATEGY_INSUFFICIENT",
                    f"{path}.strategyChange.classification",
                    "A repeated causal class/root-condition pair must change causal inputs.",
                )
            )
    return issues


def validate_job_manifest(manifest: dict[str, object]) -> list[Issue]:
    """Validate the immutable job graph and its state-specific prerequisites."""
    structural_issues = validate_json_structure(manifest, "manifest")
    if _structural_issues_block_field_validation(structural_issues):
        return structural_issues
    jobs = _manifest_jobs(manifest)
    if jobs is None:
        return structural_issues + [
            Issue(
                "JOB_MANIFEST_INVALID",
                "manifest.jobs",
                "Job manifests must contain a jobs list of JSON objects.",
            )
        ]

    issues = structural_issues
    if type(manifest.get("schemaVersion")) is not int or manifest.get("schemaVersion") != 1:
        issues.append(
            Issue(
                "JOB_SCHEMA_VERSION_INVALID",
                "manifest.schemaVersion",
                "schemaVersion must be 1.",
            )
        )
    jobs_by_id = _jobs_by_id(jobs)
    all_ids: set[str] = set()
    for index, job in enumerate(jobs):
        path = f"manifest.jobs[{index}]"
        job_id = job.get("id")
        if not _nonempty_text(job_id):
            issues.append(
                Issue("JOB_ID_INVALID", f"{path}.id", "Job id must be non-empty text.")
            )
        elif job_id in all_ids:
            issues.append(
                Issue("JOB_ID_DUPLICATE", f"{path}.id", "Job ids must be unique.")
            )
        else:
            all_ids.add(job_id)
        if not _nonempty_text(job.get("kind")):
            issues.append(
                Issue("JOB_KIND_INVALID", f"{path}.kind", "Job kind must be non-empty text.")
            )
        status = job.get("status")
        if not isinstance(status, str) or status not in VALID_JOB_STATES:
            issues.append(
                Issue(
                    "JOB_STATUS_INVALID",
                    f"{path}.status",
                    "Job status must be a known state.",
                )
            )
        dependencies = job.get("dependsOn")
        if not _string_list(dependencies) or len(set(dependencies or [])) != len(
            dependencies or []
        ):
            issues.append(
                Issue(
                    "JOB_DEPENDENCIES_INVALID",
                    f"{path}.dependsOn",
                    "dependsOn must be a duplicate-free list of job ids.",
                )
            )
        input_hashes = job.get("inputHashes")
        if not isinstance(input_hashes, dict) or not all(
            _nonempty_text(input_id) and _valid_sha256(input_hash)
            for input_id, input_hash in input_hashes.items()
        ):
            issues.append(
                Issue(
                    "JOB_INPUT_HASHES_INVALID",
                    f"{path}.inputHashes",
                    "inputHashes must map non-empty ids to SHA-256 strings.",
                )
            )
        if not _optional_sha256(job.get("artifactSha256")):
            issues.append(
                Issue(
                    "JOB_ARTIFACT_SHA256_INVALID",
                    f"{path}.artifactSha256",
                    "artifactSha256 must be null or a SHA-256 string.",
                )
            )
        if not _valid_sha256(job.get("canonicalIdentitySha256")):
            issues.append(
                Issue(
                    "JOB_CANONICAL_SHA256_INVALID",
                    f"{path}.canonicalIdentitySha256",
                    "canonicalIdentitySha256 must be a SHA-256 string.",
                )
            )
        for field in ("technicalVerdictId", "visualVerdictId"):
            if field not in job or not _optional_verdict_id(job.get(field)):
                issues.append(
                    Issue(
                        "JOB_VERDICT_ID_INVALID",
                        f"{path}.{field}",
                        f"{field} must be null or non-empty text.",
                    )
                )
        retry_count = job.get("retryCount")
        if (
            not isinstance(retry_count, int)
            or isinstance(retry_count, bool)
            or retry_count < 0
        ):
            issues.append(
                Issue(
                    "JOB_RETRY_COUNT_INVALID",
                    f"{path}.retryCount",
                    "retryCount must be a non-negative integer.",
                )
            )
        if "importedIdentityRoot" in job and not isinstance(
            job.get("importedIdentityRoot"), bool
        ):
            issues.append(
                Issue(
                    "IMPORTED_IDENTITY_ROOT_INVALID",
                    f"{path}.importedIdentityRoot",
                    "importedIdentityRoot must be true or false when present.",
                )
            )

    for index, job in enumerate(jobs):
        path = f"manifest.jobs[{index}]"
        dependencies = job.get("dependsOn")
        if isinstance(dependencies, list):
            for dependency_id in dependencies:
                if isinstance(dependency_id, str) and dependency_id not in jobs_by_id:
                    issues.append(
                        Issue(
                            "JOB_DEPENDENCY_NOT_FOUND",
                            f"{path}.dependsOn",
                            f"Dependency {dependency_id!r} does not exist.",
                        )
                    )
                if not isinstance(dependency_id, str):
                    continue
                dependency = jobs_by_id.get(dependency_id)
                if (
                    dependency is not None
                    and job.get("status") != "superseded"
                    and dependency.get("status") != "superseded"
                    and _valid_sha256(job.get("canonicalIdentitySha256"))
                    and _valid_sha256(dependency.get("canonicalIdentitySha256"))
                    and job["canonicalIdentitySha256"].lower()
                    != dependency["canonicalIdentitySha256"].lower()
                ):
                    issues.append(
                        Issue(
                            "JOB_CANONICAL_IDENTITY_MISMATCH",
                            f"{path}.canonicalIdentitySha256",
                            "Non-superseded dependency chains must retain one canonical identity hash.",
                        )
                    )
        if job.get("importedIdentityRoot") is True and not _is_imported_identity_root(
            job
        ):
            issues.append(
                Issue(
                    "IMPORTED_IDENTITY_ROOT_INVALID",
                    path,
                    "Only an externally selected identity root may omit technicalVerdictId.",
                )
            )
        status = job.get("status")
        if (
            isinstance(status, str)
            and status in _IDENTITY_ARTIFACT_STATES
            and job.get("kind") == "identity"
            and job.get("dependsOn") == []
            and _valid_sha256(job.get("artifactSha256"))
            and _valid_sha256(job.get("canonicalIdentitySha256"))
            and job["artifactSha256"].lower()
            != job["canonicalIdentitySha256"].lower()
        ):
            issues.append(
                Issue(
                    "IDENTITY_ROOT_ARTIFACT_CANONICAL_MISMATCH",
                    f"{path}.artifactSha256",
                    "A non-superseded identity root artifact must match its canonical identity hash.",
                )
            )
        if isinstance(status, str) and status in {
            "ready",
            "generating",
            "candidate",
            "technical-pass",
            "visual-pass",
            "selected",
        } and not _dependencies_satisfied(job, jobs_by_id):
            issues.append(
                Issue(
                    (
                        "JOB_READY_PREREQUISITES_UNMET"
                        if status == "ready"
                        else "JOB_DEPENDENCY_PREREQUISITES_UNMET"
                    ),
                    path,
                    "Active jobs require selected dependencies with matching recorded hashes.",
                )
            )
        if isinstance(status, str) and status in {"candidate", "technical-pass", "visual-pass", "selected"} and not _valid_sha256(
            job.get("artifactSha256")
        ):
            issues.append(
                Issue(
                    "JOB_ARTIFACT_REQUIRED",
                    f"{path}.artifactSha256",
                    "Candidate and accepted states require an artifact SHA-256.",
                )
            )
        imported_root = _is_imported_identity_root(job)
        if isinstance(status, str) and status in {"technical-pass", "visual-pass", "selected"} and not imported_root:
            if not _nonempty_text(job.get("technicalVerdictId")):
                issues.append(
                    Issue(
                        "JOB_TECHNICAL_VERDICT_REQUIRED",
                        f"{path}.technicalVerdictId",
                        "Technical-pass and later generated jobs require technicalVerdictId.",
                    )
                )
        if isinstance(status, str) and status in {"visual-pass", "selected"} and not _nonempty_text(
            job.get("visualVerdictId")
        ):
            issues.append(
                Issue(
                    "JOB_VISUAL_VERDICT_REQUIRED",
                    f"{path}.visualVerdictId",
                    "Visual-pass and selected jobs require visualVerdictId.",
                )
            )
        if isinstance(status, str) and status in {"blocked", "rejected"}:
            issues.extend(_failure_record_issues(job, path))
        if status == "superseded" and (
            job.get("technicalVerdictId") is not None
            or job.get("visualVerdictId") is not None
        ):
            issues.append(
                Issue(
                    "SUPERSEDED_VERDICTS_MUST_CLEAR",
                    path,
                    "Superseded jobs cannot retain technical or visual verdict claims.",
                )
            )

    if _dependency_graph_has_cycle(jobs_by_id):
        issues.append(
            Issue(
                "JOB_DEPENDENCY_CYCLE",
                "manifest.jobs",
                "Job dependencies must be acyclic.",
            )
        )
    return issues


def ready_job_ids(manifest: dict[str, object]) -> list[str]:
    """Return pending jobs whose selected dependencies and hashes are current."""
    jobs = _manifest_jobs(manifest)
    if jobs is None:
        return []
    jobs_by_id = _jobs_by_id(jobs)
    return [
        job_id
        for job_id in sorted(jobs_by_id)
        if jobs_by_id[job_id].get("status") == "pending"
        and _dependencies_satisfied(jobs_by_id[job_id], jobs_by_id)
    ]


def transition_job(
    manifest: dict[str, object],
    job_id: str,
    target_state: str,
    artifact_sha256: str | None = None,
    *,
    failure_record: dict[str, object] | None = None,
) -> dict[str, object]:
    """Return a deep-copied manifest after one legal job-state transition."""
    source_issues = validate_job_manifest(manifest)
    if source_issues:
        codes = ", ".join(sorted({issue.code for issue in source_issues}))
        raise ValueError(f"source manifest is invalid: {codes}")
    if failure_record is not None:
        failure_structure_issues = validate_json_structure(
            failure_record, "failure_record"
        )
        if failure_structure_issues:
            codes = ", ".join(
                sorted({issue.code for issue in failure_structure_issues})
            )
            raise ValueError(f"failure_record is structurally invalid: {codes}")
    jobs = _manifest_jobs(manifest)
    if jobs is None:
        raise ValueError("manifest must contain a jobs list of objects")
    jobs_by_id = _jobs_by_id(jobs)
    if not _nonempty_text(job_id):
        raise ValueError("job_id must be non-empty text")
    if job_id not in jobs_by_id:
        raise ValueError(f"job id not found: {job_id}")
    if not isinstance(target_state, str) or target_state not in VALID_JOB_STATES:
        raise ValueError(f"unknown target state: {target_state}")
    source_job = jobs_by_id[job_id]
    current_state = source_job.get("status")
    if not isinstance(current_state, str) or current_state not in VALID_JOB_STATES:
        raise ValueError(f"job {job_id!r} has an invalid current state")
    if current_state in _TERMINAL_FAILURE_STATES:
        raise ValueError(f"terminal failure state cannot transition: {current_state}")
    if target_state in _TERMINAL_FAILURE_STATES:
        allowed = current_state in _ACTIVE_JOB_STATES
    else:
        allowed = _FORWARD_JOB_TRANSITIONS.get(current_state) == target_state
    if not allowed:
        raise ValueError(f"illegal job transition: {current_state} -> {target_state}")
    if target_state == "ready" and job_id not in ready_job_ids(manifest):
        raise ValueError("job dependencies are not ready")
    if artifact_sha256 is not None and not _valid_sha256(artifact_sha256):
        raise ValueError("artifact_sha256 must be a 64-character SHA-256 string")
    if failure_record is not None and target_state not in {"blocked", "rejected"}:
        raise ValueError("failure_record is only valid for blocked or rejected transitions")
    if failure_record is not None and not isinstance(failure_record, dict):
        raise ValueError("failure_record must be a JSON object")

    updated = deepcopy(manifest)
    updated_jobs = _manifest_jobs(updated)
    if updated_jobs is None:
        raise ValueError("manifest deep copy lost jobs")
    updated_job = _jobs_by_id(updated_jobs)[job_id]
    if artifact_sha256 is not None:
        updated_job["artifactSha256"] = artifact_sha256
    if failure_record is not None:
        for field in (
            "failureClass",
            "rootCondition",
            "changedVariable",
            "preserve",
            "nextStrategy",
            "retryCount",
            "failureHistory",
            "strategyChange",
        ):
            if field in failure_record:
                updated_job[field] = deepcopy(failure_record[field])
    if target_state in _TERMINAL_FAILURE_STATES:
        updated_job["importedIdentityRoot"] = False
    if target_state == "superseded":
        updated_job["technicalVerdictId"] = None
        updated_job["visualVerdictId"] = None
    updated_job["status"] = target_state
    validation_issues = validate_job_manifest(updated)
    if validation_issues:
        codes = ", ".join(sorted({issue.code for issue in validation_issues}))
        raise ValueError(f"transition prerequisites are not met: {codes}")
    return updated


def invalidate_descendants(
    manifest: dict[str, object],
    upstream_id: str,
    replacement_sha256: str,
) -> tuple[dict[str, object], list[str]]:
    """Replace one canonical hash and supersede only its transitive descendants."""
    source_issues = validate_job_manifest(manifest)
    if source_issues:
        codes = ", ".join(sorted({issue.code for issue in source_issues}))
        raise ValueError(f"source manifest is invalid: {codes}")
    if not _valid_sha256(replacement_sha256):
        raise ValueError("replacement_sha256 must be a 64-character SHA-256 string")
    jobs = _manifest_jobs(manifest)
    if jobs is None:
        raise ValueError("manifest must contain a jobs list of objects")
    jobs_by_id = _jobs_by_id(jobs)
    if not _nonempty_text(upstream_id):
        raise ValueError("upstream_id must be non-empty text")
    if upstream_id not in jobs_by_id:
        raise ValueError(f"job id not found: {upstream_id}")
    upstream_job = jobs_by_id[upstream_id]
    upstream_kind = upstream_job.get("kind")
    upstream_dependencies = upstream_job.get("dependsOn")
    if (
        not isinstance(upstream_kind, str)
        or upstream_kind != "identity"
        or not isinstance(upstream_dependencies, list)
        or upstream_dependencies != []
    ):
        raise ValueError(
            "canonical identity replacement requires an identity root with no dependencies"
    )
    current_status = upstream_job.get("status")
    if (
        not isinstance(current_status, str)
        or current_status not in _IDENTITY_ARTIFACT_STATES
    ):
        raise ValueError(
            "canonical identity replacement requires a nonterminal candidate-or-later identity root"
        )
    current_canonical_sha256 = upstream_job.get("canonicalIdentitySha256")
    current_artifact_sha256 = upstream_job.get("artifactSha256")
    if not _valid_sha256(current_canonical_sha256):
        raise ValueError("identity root must have a valid current canonical SHA-256")
    if not _valid_sha256(current_artifact_sha256):
        raise ValueError(
            "candidate-or-later identity root must have a valid current artifact SHA-256"
        )
    if current_artifact_sha256.lower() != current_canonical_sha256.lower():
        raise ValueError(
            "identity root artifact must match its current canonical SHA-256 before replacement"
        )

    reverse_dependencies: dict[str, set[str]] = {job_id: set() for job_id in jobs_by_id}
    for job_id, job in jobs_by_id.items():
        dependencies = job.get("dependsOn")
        if isinstance(dependencies, list):
            for dependency_id in dependencies:
                if isinstance(dependency_id, str) and dependency_id in reverse_dependencies:
                    reverse_dependencies[dependency_id].add(job_id)
    pending = list(reverse_dependencies[upstream_id])
    descendants: set[str] = set()
    while pending:
        current_id = pending.pop()
        if current_id in descendants:
            continue
        descendants.add(current_id)
        pending.extend(reverse_dependencies[current_id])

    updated = deepcopy(manifest)
    updated_jobs = _manifest_jobs(updated)
    if updated_jobs is None:
        raise ValueError("manifest deep copy lost jobs")
    updated_by_id = _jobs_by_id(updated_jobs)
    upstream = updated_by_id[upstream_id]
    upstream["artifactSha256"] = replacement_sha256
    upstream["canonicalIdentitySha256"] = replacement_sha256
    upstream["status"] = "candidate"
    upstream["technicalVerdictId"] = None
    upstream["visualVerdictId"] = None
    upstream["importedIdentityRoot"] = False
    for descendant_id in descendants:
        descendant = updated_by_id[descendant_id]
        descendant["status"] = "superseded"
        descendant["technicalVerdictId"] = None
        descendant["visualVerdictId"] = None
        descendant["importedIdentityRoot"] = False
    output_issues = validate_job_manifest(updated)
    if output_issues:
        codes = ", ".join(sorted({issue.code for issue in output_issues}))
        raise ValueError(f"invalidated manifest is invalid: {codes}")
    return updated, sorted(descendants)
