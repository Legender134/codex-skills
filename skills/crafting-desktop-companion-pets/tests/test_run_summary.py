from __future__ import annotations

import contextlib
from copy import deepcopy
import ctypes
import errno
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from contracts import evaluate_maturity, validate_action_contract, validate_behavior_contract
import make_run_summary
from make_run_summary import InputError, _hash_regular_file, build_run_summary


HASH_A = "a" * 64
HASH_B = "b" * 64


def issue_codes(issues: list[object]) -> set[str]:
    return {issue.code for issue in issues}


def scheduler_contract() -> dict[str, object]:
    return {
        "selection": "selected",
        "family": "ordinary-movement",
        "riskClass": "cyclic-locomotion",
        "worldMotionPhaseIds": ["travel", "return"],
        "interrupt": {"safePhaseIds": ["travel"], "recoveryAction": "idle"},
        "behavior": {
            "manualEligible": True,
            "autoplayEligible": True,
            "pool": "rare-movement",
            "weight": 0.1,
            "cooldownMs": 1200,
            "sharedGroup": "movement",
            "repeatLimit": 1,
            "priority": 10,
            "environmentalConditions": [],
            "direction": "right",
            "movement": {
                "distanceBasis": "usable-screen-relative",
                "screenFraction": 0.25,
                "boundaryPolicy": "clamp destination inside usable screen",
            },
            "cooldownException": None,
        },
    }


def runtime_evidence(package_sha: str = HASH_A) -> list[dict[str, object]]:
    return [
        {
            "kind": "Registry",
            "status": "pass",
            "packageSha256": package_sha,
            "evidenceSha256": HASH_B,
        },
        {
            "kind": "Catalog",
            "status": "pass",
            "packageSha256": package_sha,
            "evidenceSha256": "c" * 64,
        },
    ]


def installation_evidence(package_sha: str = HASH_A) -> list[dict[str, object]]:
    return [
        {
            "kind": "installation",
            "status": "pass",
            "packageSha256": package_sha,
            "evidenceSha256": "d" * 64,
        }
    ]


def verified_artifact_context(package_sha: str = HASH_A) -> dict[str, str]:
    return {
        "package.bin": package_sha,
        "evidence/registry.json": HASH_B,
        "evidence/catalog.json": "c" * 64,
        "evidence/installation.json": "d" * 64,
        "qa/preview.webp": "e" * 64,
    }


def internal_visual_passes() -> list[dict[str, object]]:
    return [
        {
            "verdictId": "builder-visual-1",
            "artifactPath": "qa/preview.webp",
            "artifactSha256": "e" * 64,
            "gate": "visual",
            "decision": "pass",
            "reviewer": "builder",
            "reviewSequence": 1,
        },
        {
            "verdictId": "independent-visual-1",
            "artifactPath": "qa/preview.webp",
            "artifactSha256": "e" * 64,
            "gate": "visual",
            "decision": "pass",
            "reviewer": "independent",
            "reviewSequence": 2,
        },
    ]


def write_bound_evidence(
    root: Path, package_sha: str, *, include_installation: bool = False
) -> dict[str, object]:
    """Create inventory-backed evidence records for an end-to-end run test."""
    payloads = {
        "evidence/registry.json": b"Registry evidence\n",
        "evidence/catalog.json": b"Catalog evidence\n",
    }
    if include_installation:
        payloads["evidence/installation.json"] = b"installation evidence\n"
    hashes: dict[str, str] = {}
    for relative, contents in payloads.items():
        path = root / Path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
        hashes[relative] = hashlib.sha256(contents).hexdigest()
    verified = [{"path": "package.bin", "expectedSha256": package_sha}]
    verified.extend(
        {"path": relative, "expectedSha256": digest}
        for relative, digest in sorted(hashes.items())
    )
    result: dict[str, object] = {
        "runtimeEvidence": [
            {
                "kind": "Registry",
                "status": "pass",
                "packageSha256": package_sha,
                "evidenceSha256": hashes["evidence/registry.json"],
            },
            {
                "kind": "Catalog",
                "status": "pass",
                "packageSha256": package_sha,
                "evidenceSha256": hashes["evidence/catalog.json"],
            },
        ],
        "verifiedArtifacts": verified,
        "paths": ["package.bin", *sorted(hashes)],
    }
    if include_installation:
        result["installationEvidence"] = [
            {
                "kind": "installation",
                "status": "pass",
                "packageSha256": package_sha,
                "evidenceSha256": hashes["evidence/installation.json"],
            }
        ]
    return result


def draft_summary() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "formalGates": "pass",
        "runtimeEvidence": [],
        "installAuthority": False,
        "installationEvidence": [],
        "integrationAuthority": False,
        "commitAuthority": False,
        "pushAuthority": False,
        "publicationAuthority": False,
        "requiredSoakMinutes": 30,
        "observedSoakMinutes": 0,
        "soakVerdict": "not-run",
        "userAcceptance": [],
        "verifiedArtifacts": [],
        "localState": {
            "keep": [],
            "archiveCandidate": [],
            "cleanupCandidate": [],
            "uncertainUserOwned": [],
        },
    }


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


class BehaviorContractTest(unittest.TestCase):
    def test_iconic_manual_rare_autoplay_and_observed_frequency_are_independent(self) -> None:
        contract = scheduler_contract()

        self.assertEqual(validate_behavior_contract(contract), [])

        contract["behavior"]["observedFrequency"] = 999  # type: ignore[index]
        self.assertEqual(validate_behavior_contract(contract), [])

    def test_autoplay_false_cannot_keep_pool_or_weight(self) -> None:
        contract = scheduler_contract()
        contract["behavior"]["autoplayEligible"] = False  # type: ignore[index]

        self.assertIn(
            "BEHAVIOR_AUTOPLAY_POOL_FORBIDDEN",
            issue_codes(validate_behavior_contract(contract)),
        )
        self.assertIn(
            "BEHAVIOR_AUTOPLAY_WEIGHT_FORBIDDEN",
            issue_codes(validate_behavior_contract(contract)),
        )

        contract["behavior"]["pool"] = None  # type: ignore[index]
        contract["behavior"]["weight"] = None  # type: ignore[index]
        self.assertEqual(validate_behavior_contract(contract), [])

    def test_selected_movement_needs_direction_distance_boundary_interruption_and_recovery(self) -> None:
        contract = scheduler_contract()
        contract["behavior"]["direction"] = "up"  # type: ignore[index]
        contract["behavior"]["movement"] = {"distanceBasis": "runtime-derived"}  # type: ignore[index]
        contract["interrupt"] = {"safePhaseIds": [], "recoveryAction": None}

        codes = issue_codes(validate_behavior_contract(contract))

        self.assertIn("BEHAVIOR_MOVEMENT_DIRECTION_INVALID", codes)
        self.assertIn("BEHAVIOR_MOVEMENT_RUNTIME_EVIDENCE_REQUIRED", codes)
        self.assertIn("BEHAVIOR_MOVEMENT_BOUNDARY_REQUIRED", codes)
        self.assertIn("BEHAVIOR_MOVEMENT_INTERRUPTION_REQUIRED", codes)
        self.assertIn("BEHAVIOR_MOVEMENT_RECOVERY_REQUIRED", codes)

    def test_movement_rejects_contradictory_distance_fields(self) -> None:
        contract = scheduler_contract()
        movement = contract["behavior"]["movement"]  # type: ignore[index]
        movement["runtimeFormula"] = "runtime width * 0.25"  # type: ignore[index]
        movement["runtimeEvidenceSha256"] = HASH_A  # type: ignore[index]

        self.assertIn(
            "BEHAVIOR_MOVEMENT_DISTANCE_CONTRADICTORY",
            issue_codes(validate_behavior_contract(contract)),
        )

    def test_large_effect_needs_cooldown_group_or_hash_bound_exception(self) -> None:
        contract = scheduler_contract()
        contract["riskClass"] = "large-effect"
        contract["behavior"]["cooldownMs"] = None  # type: ignore[index]
        contract["behavior"]["sharedGroup"] = None  # type: ignore[index]

        self.assertIn(
            "BEHAVIOR_LARGE_EFFECT_COOLDOWN_REQUIRED",
            issue_codes(validate_behavior_contract(contract)),
        )

        contract["behavior"]["cooldownException"] = {
            "runtimeRoute": "legacy-v2",
            "reason": "The route exposes no cooldown or grouping slot.",
            "evidenceSha256": HASH_A,
        }
        self.assertEqual(validate_behavior_contract(contract), [])

    def test_boolean_numeric_duplicates_and_malformed_json_shape_return_issues(self) -> None:
        contract = scheduler_contract()
        contract["behavior"]["repeatLimit"] = True  # type: ignore[index]
        contract["behavior"]["priority"] = float("nan")  # type: ignore[index]
        contract["behavior"]["environmentalConditions"] = ["night", "night"]  # type: ignore[index]

        codes = issue_codes(validate_behavior_contract(contract))
        self.assertIn("BEHAVIOR_REPEAT_LIMIT_INVALID", codes)
        self.assertIn("BEHAVIOR_PRIORITY_INVALID", codes)
        self.assertIn("BEHAVIOR_ENVIRONMENT_DUPLICATE", codes)

        cyclic: dict[str, object] = {}
        cyclic["self"] = cyclic
        self.assertIn(
            "JSON_STRUCTURE_CYCLE",
            issue_codes(validate_behavior_contract(cyclic)),
        )

        deeply_nested: object = "extension"
        for _ in range(130):
            deeply_nested = [deeply_nested]
        deep_contract = scheduler_contract()
        deep_contract["untrustedExtension"] = deeply_nested
        self.assertIn(
            "JSON_STRUCTURE_DEPTH_EXCEEDED",
            issue_codes(validate_behavior_contract(deep_contract)),
        )

    def test_generic_action_validator_uses_the_same_scheduler_rules(self) -> None:
        action = {
            "schemaVersion": 1,
            "actionId": "rare-travel",
            "family": "ordinary-movement",
            "riskClass": "cyclic-locomotion",
            "identitySha256": HASH_A,
            "desktopRole": "travel",
            "phases": [
                {
                    "id": "entry",
                    "bodyState": "leans",
                    "faceState": "forward",
                    "handState": "balanced",
                    "hairGarmentState": "settled",
                    "propEffectState": "absent",
                    "propLifecycleStage": None,
                    "effectLifecycleStage": None,
                    "anchor": "body",
                    "durationMs": 100,
                    "keyPose": True,
                },
                {
                    "id": "travel",
                    "bodyState": "step passes",
                    "faceState": "forward",
                    "handState": "swings",
                    "hairGarmentState": "trails",
                    "propEffectState": "absent",
                    "propLifecycleStage": None,
                    "effectLifecycleStage": None,
                    "anchor": "world",
                    "durationMs": 100,
                    "keyPose": True,
                },
                {
                    "id": "return",
                    "bodyState": "lands",
                    "faceState": "forward",
                    "handState": "settles",
                    "hairGarmentState": "settles",
                    "propEffectState": "absent",
                    "propLifecycleStage": None,
                    "effectLifecycleStage": None,
                    "anchor": "world",
                    "durationMs": 100,
                    "keyPose": True,
                },
            ],
            "worldMotionPhaseIds": ["travel", "return"],
            "stableFeatures": ["identity"],
            "allowedChanges": ["limbs"],
            "forbiddenChanges": ["head scale"],
            "interrupt": {"safePhaseIds": ["travel"], "recoveryAction": "idle"},
            "selection": "selected",
            "behavior": scheduler_contract()["behavior"],
        }

        self.assertEqual(validate_action_contract(action), [])
        action["behavior"]["autoplayEligible"] = False  # type: ignore[index]
        self.assertIn(
            "BEHAVIOR_AUTOPLAY_POOL_FORBIDDEN", issue_codes(validate_action_contract(action))
        )


class MaturityTest(unittest.TestCase):
    def test_literal_formal_gate_boundary(self) -> None:
        result = evaluate_maturity(
            {
                "formalGates": "pass",
                "runtimeEvidence": [],
                "installAuthority": False,
                "installationEvidence": [],
                "requiredSoakMinutes": 30,
                "observedSoakMinutes": 0,
                "soakVerdict": "not-run",
                "publicationAuthority": False,
            }
        )

        self.assertEqual(result["maturity"], "production-frames")
        self.assertEqual(result["runtimeStatus"], "unverified")
        self.assertEqual(result["installedStatus"], "not-authorized")
        self.assertFalse(result["releaseAuthority"])

    def test_schema_or_package_pass_cannot_imply_runtime(self) -> None:
        result = evaluate_maturity(
            {"formalGates": "pass", "packageStatus": "pass", "runtimeEvidence": []}
        )
        self.assertEqual(result["maturity"], "production-frames")
        self.assertEqual(result["runtimeStatus"], "unverified")

    def test_runtime_install_soak_and_release_are_strictly_ordered(self) -> None:
        runtime = runtime_evidence()
        verified_context = verified_artifact_context()
        runtime_result = evaluate_maturity(
            {
                "formalGates": "pass",
                "runtimeEvidence": runtime,
                "installAuthority": False,
                "verifiedArtifactIndex": verified_context,
            }
        )
        self.assertEqual(runtime_result["maturity"], "runtime-valid")
        self.assertEqual(runtime_result["installedStatus"], "not-authorized")

        short_soak = evaluate_maturity(
            {
                "formalGates": "pass",
                "runtimeEvidence": runtime,
                "installAuthority": True,
                "installationEvidence": installation_evidence(),
                "requiredSoakMinutes": 30,
                "observedSoakMinutes": 29,
                "soakVerdict": "pass",
                "verifiedArtifactIndex": verified_context,
            }
        )
        self.assertEqual(short_soak["maturity"], "installed-test")

        release = evaluate_maturity(
            {
                "formalGates": "pass",
                "runtimeEvidence": runtime,
                "installAuthority": True,
                "installationEvidence": installation_evidence(),
                "requiredSoakMinutes": 30,
                "observedSoakMinutes": 30,
                "soakVerdict": "pass",
                "integrationAuthority": True,
                "publicationAuthority": True,
                "commitAuthority": False,
                "pushAuthority": False,
                "verifiedArtifactIndex": verified_context,
            }
        )
        self.assertEqual(release["maturity"], "release-candidate")
        self.assertTrue(release["releaseAuthority"])
        self.assertFalse(release["authorities"]["commit"])
        self.assertFalse(release["authorities"]["push"])

    def test_malformed_duplicate_stale_and_truthy_authority_do_not_advance(self) -> None:
        malformed = runtime_evidence()
        malformed.append(deepcopy(malformed[0]))
        result = evaluate_maturity(
            {
                "formalGates": "pass",
                "runtimeEvidence": malformed,
                "installAuthority": 1,
                "publicationAuthority": "yes",
                "verifiedArtifactIndex": verified_artifact_context(),
            }
        )

        self.assertEqual(result["runtimeStatus"], "unverified")
        self.assertEqual(result["installedStatus"], "not-authorized")
        self.assertFalse(result["releaseAuthority"])

    def test_user_acceptance_cannot_replace_internal_visual_pass(self) -> None:
        result = evaluate_maturity(
            {
                "formalGates": "not-run",
                "internalVisualPasses": internal_visual_passes(),
                "userAcceptance": [
                    {
                        "artifactPath": "qa/preview.webp",
                        "artifactSha256": "e" * 64,
                        "gate": "visual",
                        "decision": "pass",
                        "reviewer": "user",
                        "reviewSequence": 3,
                    }
                ],
                "installAuthority": False,
                "verifiedArtifactIndex": verified_artifact_context(),
            }
        )
        self.assertEqual(result["visualStatus"], "not-reviewed")
        self.assertEqual(result["userAcceptance"], [])
        self.assertIn(
            "INTERNAL_VISUAL_PASS_REQUIRED_BEFORE_USER_ACCEPTANCE",
            result["blockers"],
        )
        self.assertEqual(result["maturity"], "research-candidate")
        self.assertFalse(result["authorities"]["install"])

        result["authorities"]["install"] = True
        again = evaluate_maturity({"formalGates": "pass", "installAuthority": False})
        self.assertFalse(again["authorities"]["install"])

    def test_user_acceptance_requires_matching_builder_and_independent_passes(
        self,
    ) -> None:
        acceptance = {
            "artifactPath": "qa/preview.webp",
            "artifactSha256": "e" * 64,
            "gate": "visual",
            "decision": "pass",
            "reviewer": "user",
            "reviewSequence": 3,
        }
        complete = evaluate_maturity(
            {
                "formalGates": "pass",
                "internalVisualPasses": internal_visual_passes(),
                "userAcceptance": [acceptance],
                "verifiedArtifactIndex": verified_artifact_context(),
            }
        )

        self.assertEqual(complete["visualStatus"], "pass")
        self.assertEqual(len(complete["userAcceptance"]), 1)
        self.assertEqual(len(complete["internalVisualPasses"]), 2)

        incomplete = evaluate_maturity(
            {
                "formalGates": "pass",
                "internalVisualPasses": internal_visual_passes()[:1],
                "userAcceptance": [acceptance],
                "verifiedArtifactIndex": verified_artifact_context(),
            }
        )

        self.assertEqual(incomplete["userAcceptance"], [])
        self.assertIn(
            "USER_ACCEPTANCE_0_INTERNAL_PASS_REQUIRED",
            incomplete["blockers"],
        )

        reversed_order = internal_visual_passes()
        reversed_order[0]["reviewSequence"] = 2
        reversed_order[1]["reviewSequence"] = 1
        reversed_result = evaluate_maturity(
            {
                "formalGates": "pass",
                "internalVisualPasses": reversed_order,
                "userAcceptance": [acceptance],
                "verifiedArtifactIndex": verified_artifact_context(),
            }
        )
        self.assertEqual(reversed_result["userAcceptance"], [])
        self.assertIn(
            "USER_ACCEPTANCE_0_INTERNAL_REVIEW_ORDER_INVALID",
            reversed_result["blockers"],
        )

        early_acceptance = dict(acceptance, reviewSequence=2)
        late_independent = internal_visual_passes()
        late_independent[1]["reviewSequence"] = 3
        early_result = evaluate_maturity(
            {
                "formalGates": "pass",
                "internalVisualPasses": late_independent,
                "userAcceptance": [early_acceptance],
                "verifiedArtifactIndex": verified_artifact_context(),
            }
        )
        self.assertEqual(early_result["userAcceptance"], [])
        self.assertIn(
            "USER_ACCEPTANCE_0_INTERNAL_REVIEW_ORDER_INVALID",
            early_result["blockers"],
        )

    def test_every_authority_requires_an_exact_boolean(self) -> None:
        for field in (
            "installAuthority",
            "integrationAuthority",
            "commitAuthority",
            "pushAuthority",
            "publicationAuthority",
        ):
            for invalid in (1, 0, "true", None):
                with self.subTest(field=field, invalid=invalid):
                    result = evaluate_maturity({"formalGates": "pass", field: invalid})
                    output_key = {
                        "installAuthority": "install",
                        "integrationAuthority": "integrate",
                        "commitAuthority": "commit",
                        "pushAuthority": "push",
                        "publicationAuthority": "publish",
                    }[field]
                    self.assertFalse(result["authorities"][output_key])
                    self.assertIn(
                        f"AUTHORITY_TYPE_INVALID:{output_key}", result["blockers"]
                    )

    def test_claimed_maturity_and_later_evidence_cannot_skip_earlier_gates(self) -> None:
        run = {
            "maturity": "release-candidate",
            "runtimeEvidence": runtime_evidence(),
            "installAuthority": True,
            "installationEvidence": installation_evidence(),
            "requiredSoakMinutes": 30,
            "observedSoakMinutes": 30,
            "soakVerdict": "pass",
            "integrationAuthority": True,
            "publicationAuthority": True,
            "verifiedArtifactIndex": verified_artifact_context(),
        }

        result = evaluate_maturity(run)

        self.assertEqual(result["maturity"], "research-candidate")
        self.assertEqual(result["runtimeStatus"], "unverified")
        self.assertFalse(result["releaseAuthority"])

    def test_result_does_not_share_input_acceptance_or_evidence_containers(self) -> None:
        run = {
            "formalGates": "pass",
            "runtimeEvidence": runtime_evidence(),
            "verifiedArtifactIndex": verified_artifact_context(),
            "internalVisualPasses": internal_visual_passes(),
            "userAcceptance": [
                {
                    "artifactPath": "qa/preview.webp",
                    "artifactSha256": "e" * 64,
                    "gate": "visual",
                    "decision": "pass",
                    "reviewer": "user",
                    "reviewSequence": 3,
                }
            ],
        }
        result = evaluate_maturity(run)
        run["runtimeEvidence"][0]["kind"] = "unknown"  # type: ignore[index]
        run["internalVisualPasses"][0]["reviewer"] = "changed"  # type: ignore[index]
        run["userAcceptance"][0]["reviewer"] = "changed"  # type: ignore[index]
        run["verifiedArtifactIndex"]["package.bin"] = "f" * 64  # type: ignore[index]

        self.assertEqual(result["runtimeStatus"], "pass")
        self.assertEqual(result["internalVisualPasses"][0]["reviewer"], "builder")
        self.assertEqual(result["userAcceptance"][0]["reviewer"], "user")

    def test_runtime_evidence_without_a_verified_inventory_context_cannot_advance(self) -> None:
        result = evaluate_maturity(
            {
                "formalGates": "pass",
                "runtimeEvidence": runtime_evidence(),
            }
        )

        self.assertEqual(result["runtimeStatus"], "unverified")
        self.assertEqual(result["maturity"], "production-frames")
        self.assertIn("VERIFIED_ARTIFACT_CONTEXT_REQUIRED", result["blockers"])

    def test_stale_evidence_must_use_an_exact_boolean_and_verified_hashes(self) -> None:
        evidence = runtime_evidence()
        evidence[0]["stale"] = "false"
        result = evaluate_maturity(
            {
                "formalGates": "pass",
                "runtimeEvidence": evidence,
                "verifiedArtifactIndex": verified_artifact_context(),
            }
        )

        self.assertEqual(result["runtimeStatus"], "unverified")
        self.assertIn("RUNTIME_EVIDENCE_0_STALE_INVALID", result["blockers"])

    def test_invalid_verified_artifact_context_cannot_promote_runtime(self) -> None:
        context = verified_artifact_context()
        context["../outside"] = HASH_A
        result = evaluate_maturity(
            {
                "formalGates": "pass",
                "runtimeEvidence": runtime_evidence(),
                "verifiedArtifactIndex": context,
            }
        )

        self.assertEqual(result["runtimeStatus"], "unverified")
        self.assertEqual(result["maturity"], "production-frames")
        self.assertIn("VERIFIED_ARTIFACT_CONTEXT_INVALID", result["blockers"])

    def test_nonpassing_runtime_evidence_cannot_promote_runtime(self) -> None:
        evidence = runtime_evidence()
        evidence[1]["status"] = "fail"
        result = evaluate_maturity(
            {
                "formalGates": "pass",
                "runtimeEvidence": evidence,
                "verifiedArtifactIndex": verified_artifact_context(),
            }
        )

        self.assertEqual(result["runtimeStatus"], "unverified")
        self.assertEqual(result["maturity"], "production-frames")
        self.assertIn("RUNTIME_EVIDENCE_1_STATUS_INVALID", result["blockers"])


class RunSummaryTest(unittest.TestCase):
    def test_templates_make_scheduler_and_authority_drafts_explicit(self) -> None:
        action_template = json.loads(
            (SKILL_ROOT / "templates" / "action-contract.json").read_text(
                encoding="utf-8"
            )
        )
        run_template = json.loads(
            (SKILL_ROOT / "templates" / "run-summary.json").read_text(
                encoding="utf-8"
            )
        )
        brief = (SKILL_ROOT / "templates" / "project-brief.md").read_text(
            encoding="utf-8"
        )

        self.assertEqual(action_template["behavior"]["repeatLimit"], None)
        self.assertEqual(action_template["behavior"]["environmentalConditions"], [])
        self.assertEqual(action_template["behavior"]["movement"]["screenFraction"], None)
        self.assertEqual(run_template["localState"]["keep"], [])
        self.assertIs(run_template["installAuthority"], False)
        self.assertIn("Maturity and authorities", brief)
        self.assertIn("Run-summary publication", brief)

    def _classified_draft(self, root: Path) -> dict[str, object]:
        draft = draft_summary()
        draft["localState"]["keep"] = ["run-summary.json", "artifact.bin"]  # type: ignore[index]
        return draft

    def _write_release_ready_draft(self, root: Path) -> Path:
        """Create the smallest fully evidenced run needed for an exit-zero probe."""
        package = root / "package.bin"
        package.write_bytes(b"release package")
        package_sha = hashlib.sha256(package.read_bytes()).hexdigest()
        bound = write_bound_evidence(root, package_sha, include_installation=True)
        draft = draft_summary()
        draft.update(
            {
                "installAuthority": True,
                "integrationAuthority": True,
                "publicationAuthority": True,
                "requiredSoakMinutes": 30,
                "observedSoakMinutes": 30,
                "soakVerdict": "pass",
            }
        )
        draft.update(bound)
        draft["localState"]["keep"] = [  # type: ignore[index]
            "run-summary.json",
            *bound["paths"],  # type: ignore[index]
        ]
        write_json(root / "run-summary.json", draft)
        return package

    def _serialized_summary(self, root: Path) -> bytes:
        return (
            json.dumps(
                build_run_summary(root),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")

    def test_inventory_hashes_every_regular_file_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            artifact = root / "artifact.bin"
            artifact.write_bytes(b"artifact bytes\n")
            write_json(root / "run-summary.json", self._classified_draft(root))
            before = {path.name: path.read_bytes() for path in root.iterdir()}

            summary = build_run_summary(root)

            self.assertTrue(summary["finalSummary"] is False)
            self.assertEqual(
                [entry["path"] for entry in summary["inventory"]],
                ["artifact.bin", "run-summary.json"],
            )
            artifact_record = next(
                entry for entry in summary["inventory"] if entry["path"] == "artifact.bin"
            )
            self.assertEqual(
                artifact_record["sha256"], hashlib.sha256(b"artifact bytes\n").hexdigest()
            )
            self.assertEqual({path.name: path.read_bytes() for path in root.iterdir()}, before)

    def test_unclassified_duplicate_and_traversal_paths_block_final_summary(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "artifact.bin").write_bytes(b"x")
            draft = draft_summary()
            draft["localState"]["keep"] = ["run-summary.json", "artifact.bin"]  # type: ignore[index]
            draft["localState"]["archiveCandidate"] = ["artifact.bin", "../outside"]  # type: ignore[index]
            write_json(root / "run-summary.json", draft)

            summary = build_run_summary(root)
            blockers = set(summary["blockers"])
            self.assertIn("LOCAL_STATE_CLASSIFICATION_DUPLICATE", blockers)
            self.assertIn("LOCAL_STATE_PATH_INVALID", blockers)
            self.assertFalse(summary["finalSummary"])

    def test_verified_artifacts_cross_check_hashes_and_hardlinks_are_both_listed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            original = root / "artifact.bin"
            alias = root / "artifact-alias.bin"
            original.write_bytes(b"same bytes")
            try:
                alias.hardlink_to(original)
            except OSError as error:
                self.skipTest(f"hard links unavailable: {error}")
            draft = draft_summary()
            draft["runtimeEvidence"] = runtime_evidence()
            draft["verifiedArtifacts"] = [
                {"path": "artifact.bin", "expectedSha256": HASH_A}
            ]
            draft["localState"]["keep"] = [  # type: ignore[index]
                "run-summary.json",
                "artifact.bin",
                "artifact-alias.bin",
            ]
            write_json(root / "run-summary.json", draft)

            summary = build_run_summary(root)
            self.assertEqual(len(summary["inventory"]), 3)
            self.assertIn("VERIFIED_ARTIFACT_HASH_MISMATCH", set(summary["blockers"]))
            self.assertEqual(summary["runtimeStatus"], "unverified")

    def test_verified_artifact_hash_can_bind_runtime_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            artifact = root / "artifact.bin"
            artifact.write_bytes(b"runtime package")
            artifact_sha = hashlib.sha256(artifact.read_bytes()).hexdigest()
            draft = draft_summary()
            bound = write_bound_evidence(root, artifact_sha)
            draft.update(bound)
            draft["verifiedArtifacts"] = [  # type: ignore[index]
                {"path": "artifact.bin", "expectedSha256": artifact_sha},
                *bound["verifiedArtifacts"][1:],  # type: ignore[index]
            ]
            draft["localState"]["keep"] = [  # type: ignore[index]
                "run-summary.json",
                "artifact.bin",
                *bound["paths"][1:],  # type: ignore[index]
            ]
            write_json(root / "run-summary.json", draft)

            summary = build_run_summary(root)

            self.assertEqual(summary["runtimeStatus"], "pass")
            self.assertEqual(summary["maturity"], "runtime-valid")
            self.assertEqual(summary["verifiedArtifacts"][0]["status"], "verified")

    def test_linked_directory_is_recorded_without_following_it(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            root = parent / "run"
            root.mkdir()
            external = parent / "external"
            external.mkdir()
            (external / "outside.bin").write_bytes(b"must not be inventoried")
            try:
                (root / "linked-directory").symlink_to(external, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"directory links unavailable: {error}")
            draft = draft_summary()
            draft["localState"]["keep"] = ["run-summary.json"]  # type: ignore[index]
            write_json(root / "run-summary.json", draft)

            summary = build_run_summary(root)

            self.assertIn("RUN_LINK_REJECTED:linked-directory", summary["blockers"])
            self.assertEqual([record["path"] for record in summary["inventory"]], ["run-summary.json"])
            self.assertEqual((external / "outside.bin").read_bytes(), b"must not be inventoried")

    def test_hashing_detects_post_open_identity_change(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "artifact.bin"
            path.write_bytes(b"stable input")
            metadata = path.stat()
            real_lstat = make_run_summary.os.lstat

            def changed_lstat(target: object) -> os.stat_result:
                result = real_lstat(target)
                fields = list(result)
                fields[8] += 1
                return os.stat_result(fields)

            with patch.object(make_run_summary.os, "lstat", side_effect=changed_lstat):
                with self.assertRaises(InputError):
                    _hash_regular_file(path, metadata)
            self.assertEqual(path.read_bytes(), b"stable input")

    @unittest.skipUnless(os.name == "nt", "requires Windows live-handle metadata")
    def test_windows_live_handle_ctime_transient_keeps_bounded_reads_running(self) -> None:
        """A live Windows fstat ctime transient is not a pathname/input mutation."""
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "artifact.bin"
            contents = b"bounded Windows handle content\n"
            path.write_bytes(contents)
            expected = path.stat()
            real_fstat = make_run_summary.os.fstat

            class CtimeTransient:
                def __init__(self, original: os.stat_result) -> None:
                    self._original = original

                def __getattr__(self, name: str) -> object:
                    if name == "st_ctime_ns":
                        return self._original.st_ctime_ns + 1
                    if name == "st_ctime":
                        return self._original.st_ctime + 1
                    return getattr(self._original, name)

            def ctime_transient(descriptor: int) -> CtimeTransient:
                observed = real_fstat(descriptor)
                return CtimeTransient(observed)

            with patch.object(make_run_summary.os, "fstat", side_effect=ctime_transient):
                digest, size = _hash_regular_file(path, expected)
                bounded, *_ = make_run_summary._read_bounded_regular_file(
                    path,
                    expected,
                    len(contents),
                    subject="Windows live-handle ctime test",
                )

            self.assertEqual(digest, hashlib.sha256(contents).hexdigest())
            self.assertEqual(size, len(contents))
            self.assertEqual(bounded, contents)
            self.assertEqual(path.read_bytes(), contents)

    def test_posix_live_handle_ctime_transient_still_fails_closed(self) -> None:
        """POSIX retains strict ctime identity checks for a protected file descriptor."""
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "artifact.bin"
            path.write_bytes(b"strict POSIX ctime\n")
            expected = path.stat()
            real_fstat = make_run_summary.os.fstat

            def open_descriptor(*_: object, **__: object) -> tuple[int, None]:
                return os.open(path, os.O_RDONLY), None

            class CtimeTransient:
                def __init__(self, original: os.stat_result) -> None:
                    self._original = original

                def __getattr__(self, name: str) -> object:
                    if name == "st_ctime_ns":
                        return self._original.st_ctime_ns + 1
                    if name == "st_ctime":
                        return self._original.st_ctime + 1
                    return getattr(self._original, name)

            def ctime_transient(descriptor: int) -> CtimeTransient:
                observed = real_fstat(descriptor)
                return CtimeTransient(observed)

            with (
                patch.object(make_run_summary, "_using_windows", return_value=False),
                patch.object(
                    make_run_summary,
                    "_open_regular_file_descriptor",
                    side_effect=open_descriptor,
                ),
                patch.object(make_run_summary.os, "fstat", side_effect=ctime_transient),
            ):
                with self.assertRaisesRegex(InputError, "changed before hashing"):
                    _hash_regular_file(path, expected)

    def test_draft_snapshot_mutation_between_parse_and_inventory_fails_closed(self) -> None:
        """The parsed draft must be the exact draft recorded in inventory."""
        for mutation in ("replacement", "same-size-rewrite"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as raw:
                parent = Path(raw)
                root = parent / "run"
                root.mkdir()
                (root / "artifact.bin").write_bytes(b"artifact")
                draft_path = root / "run-summary.json"
                write_json(draft_path, self._classified_draft(root))
                original = draft_path.read_bytes()
                changed = original.replace(b'"pass"', b'"fail"', 1)
                self.assertEqual(len(changed), len(original))
                output = parent / "summary.json"
                replacement = parent / "replacement.json"
                if mutation == "replacement":
                    replacement.write_bytes(changed)
                replacement_blocked: list[bool] = []

                real_walk = make_run_summary._walk_run_root

                def mutate_before_inventory(*args: object, **kwargs: object) -> object:
                    try:
                        if mutation == "replacement":
                            os.replace(replacement, draft_path)
                        else:
                            draft_path.write_bytes(changed)
                    except OSError as error:
                        replacement_blocked.append(True)
                        raise InputError("protected draft mutation was blocked") from error
                    return real_walk(*args, **kwargs)

                with (
                    patch.object(
                        make_run_summary,
                        "_walk_run_root",
                        side_effect=mutate_before_inventory,
                    ),
                    contextlib.redirect_stderr(io.StringIO()),
                ):
                    result = make_run_summary.main(
                        ["--run-root", str(root), "--output", str(output)]
                    )

                self.assertEqual(result, 1)
                self.assertFalse(output.exists())
                expected_parent = {"run"}
                if mutation == "replacement" and replacement_blocked:
                    expected_parent.add("replacement.json")
                self.assertEqual({path.name for path in parent.iterdir()}, expected_parent)

    def test_growing_file_never_reads_past_its_expected_byte_budget(self) -> None:
        """A one-byte input may not cause an unbounded chunk read after growth."""
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "artifact.bin"
            path.write_bytes(b"x")
            expected = path.stat()
            stable_samples = 0
            for _ in range(200):
                time.sleep(0.001)
                current = path.stat()
                if make_run_summary._same_regular_identity(expected, current):
                    stable_samples += 1
                    if stable_samples >= 4:
                        break
                else:
                    expected = current
                    stable_samples = 0
            else:
                self.fail("Windows fixture metadata did not stabilize before hashing")
            real_fdopen = make_run_summary.os.fdopen
            requests: list[int] = []
            returned: list[int] = []
            appended = False

            class TrackingReader:
                def __init__(self, source: object) -> None:
                    self._source = source

                def __enter__(self) -> object:
                    return self

                def __exit__(self, *args: object) -> None:
                    self._source.close()  # type: ignore[attr-defined]

                def read(self, size: int = -1) -> bytes:
                    nonlocal appended
                    requests.append(size)
                    if not appended:
                        appended = True
                        path.write_bytes(b"x" + b"y" * 100)
                    chunk = self._source.read(size)  # type: ignore[attr-defined]
                    returned.append(len(chunk))
                    return chunk

            def tracked_fdopen(*args: object, **kwargs: object) -> TrackingReader:
                return TrackingReader(real_fdopen(*args, **kwargs))

            with patch.object(
                make_run_summary.os, "fdopen", side_effect=tracked_fdopen
            ):
                with self.assertRaises(InputError):
                    _hash_regular_file(path, expected)

            self.assertTrue(requests)
            self.assertLessEqual(max(requests), expected.st_size)
            self.assertLessEqual(sum(returned), expected.st_size)

    def test_inventory_hashing_enforces_the_aggregate_actual_read_budget(self) -> None:
        """Actual reads must stay within the aggregate limit fixed at inventory time."""
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            root = parent / "run"
            root.mkdir()
            artifact = root / "artifact.bin"
            artifact.write_bytes(b"x")
            write_json(root / "run-summary.json", self._classified_draft(root))
            expected_total = sum(
                path.stat().st_size for path in root.iterdir() if path.is_file()
            )
            artifact_identity = (artifact.stat().st_dev, artifact.stat().st_ino)
            real_fdopen = make_run_summary.os.fdopen
            returned: list[int] = []
            appended = False
            output = parent / "summary.json"

            class TrackingReader:
                def __init__(self, descriptor: int, source: object) -> None:
                    self._descriptor = descriptor
                    self._source = source

                def __enter__(self) -> object:
                    return self

                def __exit__(self, *args: object) -> None:
                    self._source.close()  # type: ignore[attr-defined]

                def read(self, size: int = -1) -> bytes:
                    nonlocal appended
                    identity = (os.fstat(self._descriptor).st_dev, os.fstat(self._descriptor).st_ino)
                    if identity == artifact_identity and not appended:
                        appended = True
                        artifact.write_bytes(b"x" + b"y" * 100)
                    chunk = self._source.read(size)  # type: ignore[attr-defined]
                    returned.append(len(chunk))
                    return chunk

            def tracked_fdopen(descriptor: int, *args: object, **kwargs: object) -> TrackingReader:
                return TrackingReader(
                    descriptor, real_fdopen(descriptor, *args, **kwargs)
                )

            with (
                patch.object(make_run_summary, "MAX_RUN_TOTAL_BYTES", expected_total),
                patch.object(
                    make_run_summary.os, "fdopen", side_effect=tracked_fdopen
                ),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                result = make_run_summary.main(
                    ["--run-root", str(root), "--output", str(output)]
                )

            self.assertEqual(result, 1)
            self.assertFalse(output.exists())
            self.assertLessEqual(sum(returned), expected_total)

    def test_identical_existing_output_is_an_idempotent_no_write(self) -> None:
        """Deterministic reruns retain an identical output's bytes and metadata."""
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            root = parent / "run"
            root.mkdir()
            (root / "artifact.bin").write_bytes(b"artifact")
            write_json(root / "run-summary.json", self._classified_draft(root))
            output = parent / "summary.json"
            output.write_bytes(self._serialized_summary(root))
            before = output.stat()
            before_bytes = output.read_bytes()
            time.sleep(0.02)

            result = make_run_summary.main(
                ["--run-root", str(root), "--output", str(output)]
            )

            after = output.stat()
            self.assertEqual(result, 2)
            self.assertEqual(output.read_bytes(), before_bytes)
            self.assertEqual(after.st_size, before.st_size)
            self.assertEqual(after.st_mtime_ns, before.st_mtime_ns)

    def test_different_existing_output_is_an_immutable_collision(self) -> None:
        """A pre-existing different file is never overwritten by publication."""
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            root = parent / "run"
            root.mkdir()
            (root / "artifact.bin").write_bytes(b"artifact")
            write_json(root / "run-summary.json", self._classified_draft(root))
            output = parent / "summary.json"
            original = b"different pre-existing output\n"
            output.write_bytes(original)
            before = output.stat()

            with contextlib.redirect_stderr(io.StringIO()):
                result = make_run_summary.main(
                    ["--run-root", str(root), "--output", str(output)]
                )

            after = output.stat()
            self.assertEqual(result, 1)
            self.assertEqual(output.read_bytes(), original)
            self.assertEqual(after.st_mtime_ns, before.st_mtime_ns)

    @unittest.skipUnless(os.name == "nt", "requires Windows metadata semantics")
    def test_windows_summary_read_routes_preserve_all_metadata(self) -> None:
        """Every protected read leaves draft, inventory, and existing-output metadata intact."""
        def prime(path: Path) -> tuple[bytes, os.stat_result]:
            expected = path.read_bytes()
            current = path.stat()
            old_atime = time.time_ns() - 7 * 24 * 60 * 60 * 1_000_000_000
            os.utime(path, ns=(old_atime, current.st_mtime_ns))
            return expected, path.stat()

        def assert_unchanged(path: Path, expected: bytes, before: os.stat_result) -> None:
            after = path.stat()
            self.assertEqual(after.st_atime_ns, before.st_atime_ns, path)
            self.assertEqual(after.st_mtime_ns, before.st_mtime_ns, path)
            self.assertEqual(after.st_ctime_ns, before.st_ctime_ns, path)
            self.assertEqual(path.read_bytes(), expected, path)

        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            root = parent / "run"
            root.mkdir()
            artifact = root / "artifact.bin"
            artifact.write_bytes(b"ordinary inventory bytes\n")
            draft = root / "run-summary.json"
            write_json(draft, self._classified_draft(root))

            build_records = {path: prime(path) for path in (draft, artifact)}
            build_run_summary(root)
            for path, (expected, before) in build_records.items():
                assert_unchanged(path, expected, before)

            partial_output = parent / "partial-summary.json"
            partial_records = {path: prime(path) for path in (draft, artifact)}
            self.assertEqual(
                make_run_summary.main(
                    ["--run-root", str(root), "--output", str(partial_output)]
                ),
                2,
            )
            for path, (expected, before) in partial_records.items():
                assert_unchanged(path, expected, before)

        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            root = parent / "run"
            root.mkdir()
            artifact = root / "artifact.bin"
            artifact.write_bytes(b"ordinary inventory bytes\n")
            draft = root / "run-summary.json"
            write_json(draft, self._classified_draft(root))
            output = parent / "summary.json"
            output.write_bytes(self._serialized_summary(root))

            records = {path: prime(path) for path in (draft, artifact, output)}
            self.assertEqual(
                make_run_summary.main(
                    ["--run-root", str(root), "--output", str(output)]
                ),
                2,
            )
            for path, (expected, before) in records.items():
                assert_unchanged(path, expected, before)

        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            root = parent / "run"
            root.mkdir()
            artifact = root / "artifact.bin"
            artifact.write_bytes(b"ordinary inventory bytes\n")
            draft = root / "run-summary.json"
            write_json(draft, self._classified_draft(root))
            output = parent / "summary.json"
            output.write_bytes(b"different immutable output\n")

            records = {path: prime(path) for path in (draft, artifact, output)}
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(
                    make_run_summary.main(
                        ["--run-root", str(root), "--output", str(output)]
                    ),
                    1,
                )
            for path, (expected, before) in records.items():
                assert_unchanged(path, expected, before)

    @unittest.skipUnless(os.name == "nt", "requires Windows metadata-update ownership")
    def test_windows_metadata_suppression_failure_closes_and_returns_input_error(self) -> None:
        """A metadata-suppression failure closes the raw handle with a controlled error."""
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            root = parent / "run"
            root.mkdir()
            draft = root / "run-summary.json"
            write_json(draft, self._classified_draft(root))
            output = parent / "summary.json"
            replacement = parent / "replacement.json"
            stderr = io.StringIO()

            with (
                patch.object(
                    make_run_summary,
                    "_windows_suppress_metadata_updates",
                    side_effect=OSError(5, "FileBasicInfo denied"),
                    create=True,
                ),
                contextlib.redirect_stderr(stderr),
            ):
                result = make_run_summary.main(
                    ["--run-root", str(root), "--output", str(output)]
                )

            self.assertEqual(result, 1)
            self.assertFalse(output.exists())
            self.assertNotIn("Traceback", stderr.getvalue())
            os.replace(draft, replacement)
            self.assertTrue(replacement.exists())

    @unittest.skipUnless(os.name == "nt", "requires Windows FileBasicInfo")
    def test_windows_metadata_suppression_uses_file_basic_info_sentinel(self) -> None:
        """The native suppression ABI freezes all I/O-updated file times per handle."""
        self.assertEqual(make_run_summary._FILE_BASIC_INFO_CLASS, 0)
        information_type = make_run_summary._FileBasicInformation
        self.assertEqual(ctypes.sizeof(information_type), 40)
        captured: dict[str, int] = {}

        def capture_basic_info(
            _: object, information_class: int, pointer: object, size: int
        ) -> int:
            information = ctypes.cast(
                pointer, ctypes.POINTER(information_type)
            ).contents
            captured.update(
                {
                    "informationClass": information_class,
                    "size": size,
                    "creation": information.CreationTime,
                    "access": information.LastAccessTime,
                    "write": information.LastWriteTime,
                    "change": information.ChangeTime,
                    "attributes": information.FileAttributes,
                }
            )
            return 1

        descriptor: int | None = None
        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw) / "input.bin"
            source.write_bytes(b"metadata suppression ABI\n")
            try:
                with patch.object(
                    make_run_summary,
                    "_set_file_information",
                    side_effect=capture_basic_info,
                ) as set_information:
                    descriptor = make_run_summary._windows_open_descriptor(
                        source,
                        directory=False,
                        share_mode=make_run_summary._FILE_SHARE_READ,
                        desired_access=make_run_summary._GENERIC_READ,
                        suppress_metadata_updates=True,
                    )
                self.assertEqual(set_information.call_count, 1)
                self.assertEqual(
                    captured,
                    {
                        "informationClass": 0,
                        "size": 40,
                        "creation": 0,
                        "access": -1,
                        "write": -1,
                        "change": -1,
                        "attributes": 0,
                    },
                )
            finally:
                if descriptor is not None:
                    make_run_summary._close_descriptor(
                        descriptor, subject="metadata suppression test"
                    )

    def test_posix_final_existing_output_alias_after_reverify_fails_closed(self) -> None:
        """A final idempotent-output alias substitution is rejected without path cleanup."""
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            root = parent / "run"
            root.mkdir()
            artifact = root / "artifact.bin"
            artifact_bytes = b"run input stays untouched\n"
            artifact.write_bytes(artifact_bytes)
            output = parent / "summary.json"
            summary = {"schemaVersion": 1, "finalSummary": False, "inventory": []}
            encoded = make_run_summary._encode_summary(summary)
            output.write_bytes(encoded)
            injected: dict[str, os.stat_result] = {}
            stderr = io.StringIO()

            class ParentLock:
                def __init__(self, path: Path) -> None:
                    self.path = path.resolve()
                    self.descriptor = 73

                def assert_stable(self) -> None:
                    return None

                def assert_path_matches_handle(self) -> None:
                    return None

            class Locks:
                def __init__(self, _: Path) -> None:
                    self.root = ParentLock(root)

                def __enter__(self) -> "Locks":
                    return self

                def _close_all(self) -> None:
                    return None

                def open(self, path: Path) -> ParentLock:
                    return ParentLock(path)

            class Snapshot:
                path = "artifact.bin"
                metadata = artifact.stat()

                def close(self) -> None:
                    return None

            class Existing:
                metadata = output.stat()

                def assert_path_stable(self) -> None:
                    current = os.lstat(output)
                    if not make_run_summary._same_regular_path_binding(
                        self.metadata, current
                    ):
                        raise InputError("output path changed during stable comparison")

                def require_identical_bytes(self, actual: bytes) -> None:
                    self.assert_path_stable()
                    if output.read_bytes() != actual:
                        raise InputError("output collision: existing bytes differ")

                def close(self) -> None:
                    return None

            def inject_alias_after_reverify(_: object) -> None:
                os.unlink(output)
                os.link(artifact, output)
                injected["artifact"] = artifact.stat()
                injected["output"] = output.stat()

            with (
                patch.object(make_run_summary, "_using_windows", return_value=False),
                patch.object(make_run_summary, "_RunDirectoryLocks", Locks),
                patch.object(
                    make_run_summary,
                    "_build_run_summary_locked",
                    return_value=(summary, [Snapshot()]),
                ),
                patch.object(make_run_summary, "_open_existing_output", return_value=Existing()),
                patch.object(
                    make_run_summary,
                    "_reverify_input_snapshots",
                    side_effect=inject_alias_after_reverify,
                ),
                contextlib.redirect_stderr(stderr),
            ):
                result = make_run_summary.main(
                    ["--run-root", str(root), "--output", str(output)]
                )

            self.assertEqual(result, 1)
            self.assertIn("output path changed", stderr.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())
            self.assertEqual(set(injected), {"artifact", "output"})
            self.assertTrue(os.path.samefile(artifact, output))
            artifact_after = artifact.stat()
            output_after = output.stat()
            self.assertEqual(artifact_after.st_size, injected["artifact"].st_size)
            self.assertEqual(artifact_after.st_atime_ns, injected["artifact"].st_atime_ns)
            self.assertEqual(artifact_after.st_mtime_ns, injected["artifact"].st_mtime_ns)
            self.assertEqual(artifact_after.st_ctime_ns, injected["artifact"].st_ctime_ns)
            self.assertEqual(output_after.st_size, injected["output"].st_size)
            self.assertEqual(output_after.st_atime_ns, injected["output"].st_atime_ns)
            self.assertEqual(output_after.st_mtime_ns, injected["output"].st_mtime_ns)
            self.assertEqual(output_after.st_ctime_ns, injected["output"].st_ctime_ns)
            self.assertEqual(artifact.read_bytes(), artifact_bytes)
            self.assertEqual(output.read_bytes(), artifact_bytes)
            self.assertEqual({path.name for path in parent.iterdir()}, {"run", "summary.json"})

    def test_hardlink_injected_at_publication_seam_is_not_overwritten(self) -> None:
        """A race-created input alias makes no-replace publication fail closed."""
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            root = parent / "run"
            root.mkdir()
            artifact = root / "artifact.bin"
            original = b"run input must remain untouched"
            artifact.write_bytes(original)
            write_json(root / "run-summary.json", self._classified_draft(root))
            output = parent / "summary.json"

            real_identity_check = make_run_summary._output_identity_is_stable

            def inject_alias(path: Path, expected: object) -> None:
                real_identity_check(path, expected)  # type: ignore[arg-type]
                try:
                    output.hardlink_to(artifact)
                except OSError as error:
                    self.skipTest(f"hard links unavailable: {error}")

            with (
                patch.object(
                    make_run_summary,
                    "_output_identity_is_stable",
                    side_effect=inject_alias,
                ),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                result = make_run_summary.main(
                    ["--run-root", str(root), "--output", str(output)]
                )

            self.assertEqual(result, 1)
            self.assertTrue(os.path.samefile(output, artifact))
            self.assertEqual(artifact.read_bytes(), original)
            self.assertEqual(
                {path.name for path in parent.iterdir()}, {"run", "summary.json"}
            )

    def test_concurrent_initial_output_creation_is_not_overwritten(self) -> None:
        """No-replace publication leaves a racing creator's file untouched."""
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            root = parent / "run"
            root.mkdir()
            (root / "artifact.bin").write_bytes(b"artifact")
            write_json(root / "run-summary.json", self._classified_draft(root))
            output = parent / "summary.json"
            competing = b"concurrent creator\n"

            real_identity_check = make_run_summary._output_identity_is_stable

            def create_competing(path: Path, expected: object) -> None:
                real_identity_check(path, expected)  # type: ignore[arg-type]
                output.write_bytes(competing)

            with (
                patch.object(
                    make_run_summary,
                    "_output_identity_is_stable",
                    side_effect=create_competing,
                ),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                result = make_run_summary.main(
                    ["--run-root", str(root), "--output", str(output)]
                )

            self.assertEqual(result, 1)
            self.assertEqual(output.read_bytes(), competing)
            self.assertEqual(
                {path.name for path in parent.iterdir()}, {"run", "summary.json"}
            )

    def test_parent_rename_before_commit_is_rejected_without_writing_competing_directory(self) -> None:
        """A POSIX path-name mismatch must stop before the no-replace commit."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            requested_parent = root / "requested-parent"
            competing_parent = root / "competing-parent"
            requested_parent.mkdir()
            competing_parent.mkdir()
            sentinel = competing_parent / "sentinel.txt"
            sentinel_bytes = b"competing directory must not receive output"
            sentinel.write_bytes(sentinel_bytes)

            class ParentLock:
                def assert_stable(self) -> None:
                    self.fail("path-name validation must not use only fstat")

                def assert_path_matches_handle(self) -> None:
                    raise InputError("requested parent path changed")

            with self.assertRaisesRegex(InputError, "parent path changed"):
                make_run_summary._before_atomic_replace(ParentLock())  # type: ignore[arg-type]

            self.assertFalse((requested_parent / "summary.json").exists())
            self.assertFalse((competing_parent / "summary.json").exists())
            self.assertEqual(sentinel.read_bytes(), sentinel_bytes)

    def test_parent_rename_after_commit_retains_output_and_downgrades_exit(self) -> None:
        """A post-commit parent mismatch retains the committed immutable output."""
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            root = parent / "run"
            root.mkdir()
            package = self._write_release_ready_draft(root)
            output = parent / "summary.json"
            stderr = io.StringIO()

            with (
                patch.object(
                    make_run_summary,
                    "_after_atomic_no_replace_commit",
                    side_effect=InputError("requested parent path changed"),
                ),
                contextlib.redirect_stderr(stderr),
            ):
                result = make_run_summary.main(
                    ["--run-root", str(root), "--output", str(output)]
                )

            self.assertEqual(result, 2)
            self.assertTrue(output.exists())
            self.assertTrue(json.loads(output.read_text(encoding="utf-8"))["finalSummary"])
            self.assertEqual(package.read_bytes(), b"release package")
            self.assertIn("post-commit requested output parent mismatch", stderr.getvalue())
            self.assertIn("retained", stderr.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())
            self.assertEqual({path.name for path in parent.iterdir()}, {"run", "summary.json"})

    def test_posix_parent_path_check_compares_requested_name_to_held_descriptor(self) -> None:
        """The path-name check supplements, rather than replaces, the held fd."""
        held = os.stat_result(
            (stat.S_IFDIR | 0o700, 17, 23, 1, 0, 0, 0, 0, 0, 0)
        )
        rebound = os.stat_result(
            (stat.S_IFDIR | 0o700, 19, 23, 1, 0, 0, 0, 0, 0, 0)
        )
        lock = make_run_summary._DirectoryLock(
            Path("/requested-parent"), held, 91, None
        )
        with (
            patch.object(make_run_summary, "_using_windows", return_value=False),
            patch.object(make_run_summary.os, "fstat", return_value=held),
            patch.object(make_run_summary.os, "lstat", return_value=rebound) as lstat,
        ):
            with self.assertRaisesRegex(InputError, "directory path changed"):
                lock.assert_path_matches_handle()

        self.assertEqual(lstat.call_args.args, (Path("/requested-parent"),))

    def test_post_observation_competing_entry_is_never_deleted_or_modified(self) -> None:
        """No pathname operation follows the final post-commit identity observation."""
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            root = parent / "run"
            root.mkdir()
            artifact = root / "artifact.bin"
            artifact.write_bytes(b"input stays unchanged")
            write_json(root / "run-summary.json", self._classified_draft(root))
            output = parent / "summary.json"
            probe = parent / "hardlink-probe"
            try:
                probe.hardlink_to(artifact)
            except OSError as error:
                self.skipTest(f"hard links unavailable: {error}")
            probe.unlink()

            real_unlink = os.unlink
            observed = False
            mutations_after_observation: list[tuple[tuple[object, ...], dict[str, object]]] = []

            def inject_competing_entry() -> None:
                nonlocal observed
                self.assertTrue(output.exists())
                observed = True
                real_unlink(os.fspath(output))
                os.link(os.fspath(artifact), os.fspath(output))

            def track_unlink(*args: object, **kwargs: object) -> None:
                if observed:
                    mutations_after_observation.append((args, kwargs))
                real_unlink(*args, **kwargs)  # type: ignore[arg-type]

            with (
                patch.object(
                    make_run_summary,
                    "_after_post_commit_parent_observation",
                    side_effect=inject_competing_entry,
                ),
                patch.object(
                    make_run_summary.os,
                    "unlink",
                    side_effect=track_unlink,
                ),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                result = make_run_summary.main(
                    ["--run-root", str(root), "--output", str(output)]
                )

            self.assertEqual(result, 2)
            self.assertFalse(hasattr(make_run_summary, "_rollback_published_output"))
            self.assertEqual(mutations_after_observation, [])
            self.assertTrue(os.path.samefile(output, artifact))
            self.assertEqual(artifact.read_bytes(), b"input stays unchanged")
            self.assertEqual(output.read_bytes(), b"input stays unchanged")
            self.assertEqual({path.name for path in parent.iterdir()}, {"run", "summary.json"})

    def test_postcommit_cleanup_diagnostic_downgrades_final_summary_to_partial(self) -> None:
        """A committed cleanup uncertainty turns only exit zero into exit two."""
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            root = parent / "run"
            root.mkdir()
            self._write_release_ready_draft(root)
            output = parent / "summary.json"
            stderr = io.StringIO()
            real_commit = make_run_summary._commit_output_no_replace

            def commit_then_report(*args: object, **kwargs: object) -> str:
                self.assertIsNone(real_commit(*args, **kwargs))  # type: ignore[arg-type]
                return "post-commit temporary cleanup uncertainty"

            with (
                patch.object(
                    make_run_summary,
                    "_commit_output_no_replace",
                    side_effect=commit_then_report,
                ),
                contextlib.redirect_stderr(stderr),
            ):
                result = make_run_summary.main(
                    ["--run-root", str(root), "--output", str(output)]
                )

            self.assertEqual(result, 2)
            self.assertTrue(json.loads(output.read_text(encoding="utf-8"))["finalSummary"])
            self.assertIn("post-commit temporary cleanup uncertainty", stderr.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())

    def test_native_commit_boundary_preserves_a_successful_output_when_postcommit_handle_check_fails(self) -> None:
        """A failure after FileRenameInfo cannot be misreported as no publication."""
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            root = parent / "run"
            root.mkdir()
            self._write_release_ready_draft(root)
            output = parent / "summary.json"
            real_assert = make_run_summary._TemporaryOutput._assert_live_object
            stderr = io.StringIO()

            def fail_only_after_native_commit(
                temporary: object, *, allow_metadata_change: bool = False
            ) -> os.stat_result:
                if allow_metadata_change:
                    raise InputError("postcommit live-handle verification uncertainty")
                return real_assert(temporary, allow_metadata_change=allow_metadata_change)  # type: ignore[arg-type]

            with (
                patch.object(
                    make_run_summary._TemporaryOutput,
                    "_assert_live_object",
                    new=fail_only_after_native_commit,
                ),
                contextlib.redirect_stderr(stderr),
            ):
                result = make_run_summary.main(
                    ["--run-root", str(root), "--output", str(output)]
                )

            self.assertEqual(result, 2)
            self.assertTrue(output.exists())
            self.assertTrue(json.loads(output.read_text(encoding="utf-8"))["finalSummary"])
            self.assertIn("publication committed", stderr.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())

    def test_postcommit_close_failure_keeps_the_committed_exit_status(self) -> None:
        """A committed close uncertainty turns only an exit-zero result into two."""
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            root = parent / "run"
            root.mkdir()
            self._write_release_ready_draft(root)
            output = parent / "summary.json"
            real_close = make_run_summary._DirectoryLock.close

            def close_then_report(lock: object) -> None:
                real_close(lock)  # type: ignore[arg-type]
                if getattr(lock, "path", None) == parent:
                    raise InputError("post-commit close diagnostic")

            stderr = io.StringIO()
            with (
                patch.object(
                    make_run_summary._DirectoryLock,
                    "close",
                    new=close_then_report,
                ),
                contextlib.redirect_stderr(stderr),
            ):
                result = make_run_summary.main(
                    ["--run-root", str(root), "--output", str(output)]
                )

            self.assertEqual(result, 2)
            self.assertTrue(output.exists())
            self.assertTrue(json.loads(output.read_text(encoding="utf-8"))["finalSummary"])
            self.assertNotIn("Traceback", stderr.getvalue())
            self.assertIn("post-commit close diagnostic", stderr.getvalue())

    def test_resource_and_strict_json_bounds_leave_output_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            root = parent / "run"
            root.mkdir()
            output = parent / "summary.json"
            original_output = b"existing summary\n"
            output.write_bytes(original_output)
            (root / "artifact.bin").write_bytes(b"too large for patched cap")
            draft = draft_summary()
            draft["localState"]["keep"] = ["run-summary.json", "artifact.bin"]  # type: ignore[index]
            write_json(root / "run-summary.json", draft)
            with patch.object(make_run_summary, "MAX_RUN_FILE_BYTES", 1):
                with self.assertRaises(InputError):
                    build_run_summary(root)
            self.assertEqual(output.read_bytes(), original_output)

            cases = {
                "nan": b'{"formalGates":NaN}',
                "surrogate": b'{"text":"\\ud800"}',
                "deep": b'{"extension":' + b"[" * 500 + b"0" + b"]" * 500 + b"}",
            }
            command = [
                sys.executable,
                "-B",
                str(SKILL_ROOT / "scripts" / "make_run_summary.py"),
                "--run-root",
                str(root),
                "--output",
                str(output),
            ]
            for label, contents in cases.items():
                with self.subTest(label=label):
                    (root / "run-summary.json").write_bytes(contents)
                    rejected = subprocess.run(command, capture_output=True, text=True)
                    self.assertEqual(rejected.returncode, 1)
                    self.assertNotIn("Traceback", rejected.stderr)
                    self.assertEqual(output.read_bytes(), original_output)
                    self.assertEqual(
                        {path.name for path in parent.iterdir()}, {"run", "summary.json"}
                    )

    def test_duplicate_json_keys_at_every_object_level_leave_old_output_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            root = parent / "run"
            root.mkdir()
            output = parent / "summary.json"
            original = b"old output\n"
            output.write_bytes(original)
            command = [
                sys.executable,
                "-B",
                str(SKILL_ROOT / "scripts" / "make_run_summary.py"),
                "--run-root",
                str(root),
                "--output",
                str(output),
            ]
            cases = {
                "top-level": b'{"formalGates":"pass","formalGates":"pass"}',
                "nested": b'{"localState":{"keep":[],"keep":[]}}',
            }
            for label, draft in cases.items():
                with self.subTest(label=label):
                    (root / "run-summary.json").write_bytes(draft)
                    rejected = subprocess.run(command, capture_output=True, text=True)
                    self.assertEqual(rejected.returncode, 1, rejected.stderr)
                    self.assertNotIn("Traceback", rejected.stderr)
                    self.assertEqual(output.read_bytes(), original)
                    self.assertEqual(
                        {path.name for path in parent.iterdir()}, {"run", "summary.json"}
                    )

    def test_entry_cap_counts_empty_directories_before_sorting(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "first").mkdir()
            (root / "second").mkdir()
            draft = draft_summary()
            draft["localState"]["keep"] = ["run-summary.json"]  # type: ignore[index]
            write_json(root / "run-summary.json", draft)

            with patch.object(make_run_summary, "MAX_RUN_ENTRIES", 2, create=True):
                with self.assertRaises(InputError):
                    build_run_summary(root)

    def test_fabricated_evidence_artifacts_cannot_produce_a_final_summary(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            root = parent / "run"
            root.mkdir()
            package = root / "package.bin"
            package.write_bytes(b"package only")
            package_sha = hashlib.sha256(package.read_bytes()).hexdigest()
            draft = draft_summary()
            draft.update(
                {
                    "runtimeEvidence": runtime_evidence(package_sha),
                    "installAuthority": True,
                    "installationEvidence": installation_evidence(package_sha),
                    "integrationAuthority": True,
                    "publicationAuthority": True,
                    "requiredSoakMinutes": 30,
                    "observedSoakMinutes": 30,
                    "soakVerdict": "pass",
                    "userAcceptance": [
                        {
                            "artifactPath": "qa/preview.webp",
                            "artifactSha256": "e" * 64,
                            "gate": "visual",
                            "decision": "pass",
                            "reviewer": "user",
                            "reviewSequence": 3,
                        }
                    ],
                    "verifiedArtifacts": [
                        {"path": "package.bin", "expectedSha256": package_sha}
                    ],
                }
            )
            draft["localState"]["keep"] = ["run-summary.json", "package.bin"]  # type: ignore[index]
            write_json(root / "run-summary.json", draft)
            output = parent / "summary.json"

            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SKILL_ROOT / "scripts" / "make_run_summary.py"),
                    "--run-root",
                    str(root),
                    "--output",
                    str(output),
                ],
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 2, result.stderr)
            rendered = json.loads(output.read_text(encoding="utf-8"))
            self.assertFalse(rendered["finalSummary"])
            self.assertEqual(rendered["runtimeStatus"], "unverified")
            self.assertIn("RUNTIME_EVIDENCE_0_HASH_UNVERIFIED", rendered["blockers"])

    def test_atomic_writer_cleans_temporary_file_after_precommit_no_replace_failure(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            output = root / "summary.json"
            with patch.object(
                make_run_summary,
                "_commit_output_no_replace",
                side_effect=InputError("cannot publish summary without replacement: denied"),
            ):
                with self.assertRaisesRegex(InputError, "without replacement: denied"):
                    make_run_summary._write_json_atomically(output, {"schemaVersion": 1})
            self.assertFalse(output.exists())
            self.assertEqual(list(root.iterdir()), [])

    def test_atomic_writer_rejects_partial_zero_and_invalid_write_results(self) -> None:
        """A temporary writer must prove it wrote every encoded byte before commit."""
        for result_kind in ("partial", "zero", "invalid"):
            with self.subTest(result_kind=result_kind), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                output = root / "summary.json"
                real_fdopen = make_run_summary.os.fdopen

                class ShortWriter:
                    def __init__(self, source: object) -> None:
                        self._source = source
                        self._writes = 0

                    def __enter__(self) -> object:
                        return self

                    def __exit__(self, *args: object) -> None:
                        self._source.close()  # type: ignore[attr-defined]

                    def write(self, data: bytes) -> object:
                        self._writes += 1
                        if result_kind == "partial":
                            if self._writes == 1:
                                self._source.write(data[:1])  # type: ignore[attr-defined]
                                return 1
                            return 0
                        if result_kind == "zero":
                            return 0
                        return None

                    def flush(self) -> None:
                        self._source.flush()  # type: ignore[attr-defined]

                    def fileno(self) -> int:
                        return self._source.fileno()  # type: ignore[attr-defined]

                def short_fdopen(
                    descriptor: int, mode: str, *args: object, **kwargs: object
                ) -> object:
                    source = real_fdopen(descriptor, mode, *args, **kwargs)
                    return ShortWriter(source) if "w" in mode else source

                with patch.object(
                    make_run_summary.os, "fdopen", side_effect=short_fdopen
                ):
                    with self.assertRaisesRegex(InputError, "temporary summary output"):
                        make_run_summary._write_json_atomically(
                            output, {"schemaVersion": 1}
                        )

                self.assertFalse(output.exists())

    def test_temporary_path_tamper_cannot_publish_same_length_attacker_bytes(self) -> None:
        """A mutable temporary pathname must never select the committed object."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            output = root / "summary.json"
            payload = {"schemaVersion": 1}
            encoded = make_run_summary._encode_summary(payload)
            attacker = root / "attacker.bin"
            attacker_bytes = b"A" * len(encoded)
            attacker.write_bytes(attacker_bytes)
            replaced: list[Path] = []
            real_before = make_run_summary._before_atomic_replace

            def replace_temporary(parent_lock: object) -> None:
                real_before(parent_lock)  # type: ignore[arg-type]
                temporary_paths = list(root.glob(".summary.json.*.tmp"))
                if not temporary_paths:
                    return
                self.assertEqual(len(temporary_paths), 1)
                temporary = temporary_paths[0]
                try:
                    os.replace(attacker, temporary)
                except OSError:
                    return
                replaced.append(temporary)

            with patch.object(
                make_run_summary,
                "_before_atomic_replace",
                side_effect=replace_temporary,
            ):
                try:
                    publication = make_run_summary._write_json_atomically(output, payload)
                except InputError:
                    publication = None

            if replaced:
                self.assertIsNone(publication)
                self.assertFalse(output.exists())
                self.assertTrue(replaced[0].exists())
                self.assertEqual(replaced[0].read_bytes(), attacker_bytes)
            else:
                self.assertIsNotNone(publication)
                self.assertTrue(publication.committed)  # type: ignore[union-attr]
                self.assertEqual(output.read_bytes(), encoded)

    def test_precommit_cleanup_never_unlinks_a_replaced_temporary_path(self) -> None:
        """An injected competitor must not be removed through stale temp pathname cleanup."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            output = root / "summary.json"
            victim = root / "competitor.bin"
            victim_bytes = b"competitor must survive precommit cleanup"
            victim.write_bytes(victim_bytes)
            replaced: list[Path] = []
            unlinked: list[Path] = []
            real_before = make_run_summary._before_atomic_replace
            real_unlink = os.unlink

            def replace_then_fail(parent_lock: object) -> None:
                real_before(parent_lock)  # type: ignore[arg-type]
                temporary_paths = list(root.glob(".summary.json.*.tmp"))
                if temporary_paths:
                    self.assertEqual(len(temporary_paths), 1)
                    temporary = temporary_paths[0]
                    try:
                        os.replace(victim, temporary)
                    except OSError:
                        pass
                    else:
                        replaced.append(temporary)
                raise InputError("synthetic precommit failure")

            def tracked_unlink(path: object, *args: object, **kwargs: object) -> None:
                unlinked.append(Path(os.fspath(path)))
                real_unlink(path, *args, **kwargs)  # type: ignore[arg-type]

            with (
                patch.object(
                    make_run_summary,
                    "_before_atomic_replace",
                    side_effect=replace_then_fail,
                ),
                patch.object(make_run_summary.os, "unlink", side_effect=tracked_unlink),
            ):
                with self.assertRaisesRegex(InputError, "synthetic precommit failure"):
                    make_run_summary._write_json_atomically(
                        output, {"schemaVersion": 1}
                    )

            self.assertFalse(output.exists())
            if replaced:
                self.assertTrue(replaced[0].exists())
                self.assertEqual(replaced[0].read_bytes(), victim_bytes)
                self.assertNotIn(replaced[0], unlinked)
            else:
                self.assertTrue(victim.exists())
                self.assertEqual(victim.read_bytes(), victim_bytes)

    @unittest.skipUnless(os.name == "nt", "requires Windows live-handle link count")
    def test_windows_temporary_hardlink_injection_is_detected_from_the_live_handle(self) -> None:
        """A link added after write changes nNumberOfLinks and blocks precommit."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            output = root / "summary.json"
            alias = root / "temporary-alias.bin"
            injected: list[bool] = []
            real_before = make_run_summary._before_atomic_replace

            def inject_hardlink(parent_lock: object) -> None:
                real_before(parent_lock)  # type: ignore[arg-type]
                temporary_paths = list(root.glob(".summary.json.*.tmp"))
                self.assertEqual(len(temporary_paths), 1)
                try:
                    os.link(temporary_paths[0], alias)
                except OSError as error:
                    self.skipTest(f"hard-link injection unavailable: {error}")
                injected.append(True)

            with patch.object(
                make_run_summary,
                "_before_atomic_replace",
                side_effect=inject_hardlink,
            ):
                with self.assertRaisesRegex(InputError, "link count"):
                    make_run_summary._write_json_atomically(
                        output, {"schemaVersion": 1}
                    )

            self.assertEqual(injected, [True])
            self.assertFalse(output.exists())
            self.assertTrue(alias.exists())

    @unittest.skipUnless(os.name == "nt", "requires Windows file-share enforcement")
    def test_windows_retained_input_denies_same_length_rewrite_until_commit(self) -> None:
        """A protected input must deny a writer after final rehash through commit."""
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            root = parent / "run"
            root.mkdir()
            package = self._write_release_ready_draft(root)
            original = package.read_bytes()
            output = parent / "summary.json"
            blocked: list[OSError] = []
            unexpectedly_written: list[bool] = []
            real_commit = make_run_summary._commit_output_no_replace

            def attempt_rewrite_after_final_rehash(*args: object, **kwargs: object) -> str | None:
                try:
                    with package.open("r+b") as source:
                        source.write(b"Z" * len(original))
                        source.flush()
                except OSError as error:
                    blocked.append(error)
                else:
                    unexpectedly_written.append(True)
                return real_commit(*args, **kwargs)  # type: ignore[arg-type]

            with patch.object(
                make_run_summary,
                "_commit_output_no_replace",
                side_effect=attempt_rewrite_after_final_rehash,
            ):
                result = make_run_summary.main(
                    ["--run-root", str(root), "--output", str(output)]
                )

            self.assertEqual(result, 0)
            self.assertEqual(len(blocked), 1)
            self.assertEqual(unexpectedly_written, [])
            self.assertEqual(package.read_bytes(), original)
            self.assertTrue(output.exists())

    def test_every_inventory_snapshot_is_rechecked_after_the_final_precommit_seam(self) -> None:
        """No parsed or hashed input may drift after evaluation but before publication."""
        sensitive_relatives = (
            "run-summary.json",
            "package.bin",
            "evidence/registry.json",
            "evidence/catalog.json",
            "evidence/installation.json",
            "qa/user-acceptance.json",
            "other-inventory.bin",
        )
        for mutation in ("replacement", "same-size-rewrite"):
            for relative in sensitive_relatives:
                with self.subTest(mutation=mutation, relative=relative), tempfile.TemporaryDirectory() as raw:
                    parent = Path(raw)
                    root = parent / "run"
                    root.mkdir()
                    contents = {
                        "package.bin": b"package input\n",
                        "evidence/registry.json": b"registry input\n",
                        "evidence/catalog.json": b"catalog input\n",
                        "evidence/installation.json": b"installation input\n",
                        "qa/user-acceptance.json": b"acceptance input\n",
                        "other-inventory.bin": b"generic inventory input\n",
                    }
                    for input_relative, initial in contents.items():
                        path = root / input_relative
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(initial)
                    draft = self._classified_draft(root)
                    draft["localState"]["keep"] = [  # type: ignore[index]
                        "run-summary.json",
                        *sorted(contents),
                    ]
                    draft_path = root / "run-summary.json"
                    write_json(draft_path, draft)
                    target = root / relative
                    original = target.read_bytes()
                    replacement_bytes = b"Z" * len(original)
                    replacement = parent / "replacement.bin"
                    if mutation == "replacement":
                        replacement.write_bytes(replacement_bytes)
                    output = parent / "summary.json"
                    real_before = make_run_summary._before_atomic_replace
                    mutated: list[Path] = []
                    blocked: list[Path] = []

                    def mutate_after_evaluation(parent_lock: object) -> None:
                        real_before(parent_lock)  # type: ignore[arg-type]
                        try:
                            if mutation == "replacement":
                                os.replace(replacement, target)
                            else:
                                target.write_bytes(replacement_bytes)
                        except OSError:
                            blocked.append(target)
                            raise InputError("protected input mutation was blocked")
                        else:
                            mutated.append(target)

                    with (
                        patch.object(
                            make_run_summary,
                            "_before_atomic_replace",
                            side_effect=mutate_after_evaluation,
                        ),
                        contextlib.redirect_stderr(io.StringIO()),
                    ):
                        result = make_run_summary.main(
                            ["--run-root", str(root), "--output", str(output)]
                        )

                    self.assertEqual(mutated or blocked, [target])
                    self.assertEqual(result, 1)
                    self.assertFalse(output.exists())

    @unittest.skipUnless(os.name == "nt", "requires Windows component-chain locking")
    def test_windows_component_chain_blocks_run_root_ancestor_swap_before_inventory(self) -> None:
        """A resolved run-root path must not be rebound through an unlocked ancestor."""
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            requested_parent = workspace / "requested-parent"
            requested_parent.mkdir()
            root = requested_parent / "run"
            root.mkdir()
            (root / "good.bin").write_bytes(b"good input")
            draft = self._classified_draft(root)
            draft["localState"]["keep"] = [  # type: ignore[index]
                "run-summary.json",
                "good.bin",
            ]
            write_json(root / "run-summary.json", draft)
            attacker_parent = workspace / "attacker-parent"
            attacker_root = attacker_parent / "run"
            attacker_root.mkdir(parents=True)
            outside = attacker_root / "outside-sentinel.bin"
            outside_bytes = b"outside contents must not be read"
            outside.write_bytes(outside_bytes)
            attacker_draft = self._classified_draft(attacker_root)
            attacker_draft["localState"]["keep"] = ["run-summary.json"]  # type: ignore[index]
            write_json(attacker_root / "run-summary.json", attacker_draft)
            parked = workspace / "parked-parent"
            attempted: list[bool] = []
            outside_reads: list[Path] = []
            real_before_open = make_run_summary._before_regular_file_open

            def swap_requested_ancestor(parent_path: Path, component: str) -> None:
                if attempted or parent_path != requested_parent or component != "run":
                    return
                attempted.append(True)
                try:
                    os.replace(requested_parent, parked)
                    os.replace(attacker_parent, requested_parent)
                except OSError:
                    return
                self.fail("component ancestry was not protected against replacement")

            def record_outside_read(path: Path, expected: os.stat_result) -> None:
                if path == outside:
                    outside_reads.append(path)
                real_before_open(path, expected)

            with (
                patch.object(
                    make_run_summary,
                    "_before_directory_component_open",
                    side_effect=swap_requested_ancestor,
                ),
                patch.object(
                    make_run_summary,
                    "_before_regular_file_open",
                    side_effect=record_outside_read,
                ),
            ):
                summary = build_run_summary(root)

            self.assertEqual(attempted, [True])
            self.assertEqual(outside_reads, [])
            self.assertEqual(outside.read_bytes(), outside_bytes)
            self.assertEqual(
                [record["path"] for record in summary["inventory"]],
                ["good.bin", "run-summary.json"],
            )

    @unittest.skipUnless(os.name == "nt", "requires Windows component-chain locking")
    def test_windows_component_chain_blocks_output_parent_ancestor_swap_before_publish(self) -> None:
        """An output parent descendant must remain rooted in its held ancestors."""
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            run_parent = workspace / "run-parent"
            root = run_parent / "run"
            root.mkdir(parents=True)
            (root / "artifact.bin").write_bytes(b"input stays unchanged")
            draft = self._classified_draft(root)
            draft["localState"]["keep"] = [  # type: ignore[index]
                "run-summary.json",
                "artifact.bin",
            ]
            write_json(root / "run-summary.json", draft)
            requested_parent = workspace / "requested-output-parent"
            requested_inner = requested_parent / "inner"
            requested_inner.mkdir(parents=True)
            attacker_parent = workspace / "attacker-output-parent"
            attacker_inner = attacker_parent / "inner"
            attacker_inner.mkdir(parents=True)
            sentinel = attacker_inner / "outside-sentinel.bin"
            sentinel_bytes = b"attacker output parent must stay untouched"
            sentinel.write_bytes(sentinel_bytes)
            parked = workspace / "parked-output-parent"
            output = requested_inner / "summary.json"
            attempted: list[bool] = []

            def swap_requested_parent(parent_path: Path, component: str) -> None:
                if (
                    attempted
                    or parent_path != requested_parent
                    or component != "inner"
                ):
                    return
                attempted.append(True)
                try:
                    os.replace(requested_parent, parked)
                    os.replace(attacker_parent, requested_parent)
                except OSError:
                    return
                self.fail("output-parent component ancestry was not protected")

            with patch.object(
                make_run_summary,
                "_before_directory_component_open",
                side_effect=swap_requested_parent,
            ):
                result = make_run_summary.main(
                    ["--run-root", str(root), "--output", str(output)]
                )

            self.assertEqual(result, 2)
            self.assertEqual(attempted, [True])
            self.assertTrue(output.exists())
            self.assertEqual(sentinel.read_bytes(), sentinel_bytes)

    def test_posix_missing_descriptor_safety_capability_fails_closed(self) -> None:
        """Missing O_DIRECTORY/O_NOFOLLOW support must not silently become path opens."""
        with (
            patch.object(make_run_summary, "_using_windows", return_value=False),
            patch.object(make_run_summary.os, "O_DIRECTORY", 0, create=True),
        ):
            with self.assertRaisesRegex(InputError, "O_DIRECTORY"):
                make_run_summary._open_posix_directory_descriptor(".")

    def test_posix_fd_scandir_typeerror_is_converted_to_a_controlled_input_error(self) -> None:
        """A host without descriptor scandir support must not fall back to a path scan."""
        root = Path("/display-only-root")

        class LockedDirectory:
            path = root
            descriptor = 73

            def assert_stable(self) -> None:
                return None

        class Locks:
            root = LockedDirectory()

        with (
            patch.object(make_run_summary, "_using_windows", return_value=False),
            patch.object(make_run_summary.os, "scandir", side_effect=TypeError("no fd")),
        ):
            with self.assertRaisesRegex(InputError, "descriptor scandir"):
                make_run_summary._walk_run_root(root, Locks())  # type: ignore[arg-type]

    def test_posix_dirfd_stat_typeerror_is_converted_to_a_controlled_input_error(self) -> None:
        """A missing dir_fd stat route is a controlled unsafe-input failure."""
        with (
            patch.object(make_run_summary, "_using_windows", return_value=False),
            patch.object(make_run_summary.os, "stat", side_effect=TypeError("no dir_fd")),
        ):
            with self.assertRaisesRegex(InputError, "descriptor-rooted stat"):
                make_run_summary._stat_unfollowed(
                    Path("display-only"), parent_descriptor=73, entry_name="input.bin"
                )

    def test_posix_unnamed_linkat_publication_is_descriptor_bound_and_no_replace(self) -> None:
        """The POSIX publication primitive receives only live source/destination fds."""
        calls: list[tuple[object, ...]] = []

        class LinkAt:
            argtypes: object = None
            restype: object = None

            def __call__(self, *args: object) -> int:
                calls.append(args)
                return 0

        class LibC:
            linkat = LinkAt()

        with (
            patch.object(make_run_summary, "_using_windows", return_value=False),
            patch.object(make_run_summary.ctypes, "CDLL", return_value=LibC()),
        ):
            make_run_summary._posix_link_unnamed_temporary_no_replace(
                41, "summary.json", 73
            )

        self.assertEqual(calls, [(41, b"", 73, b"summary.json", 0x1000)])

    def test_posix_temporary_link_count_is_state_aware_at_commit_boundary(self) -> None:
        """An unnamed temporary has nlink 0 before linkat and exactly 1 after it."""
        def regular_metadata(nlink: int) -> os.stat_result:
            return os.stat_result((stat.S_IFREG | 0o600, 7, 11, nlink, 0, 0, 0, 0, 0, 0))

        class ParentLock:
            descriptor = 73

        temporary = make_run_summary._TemporaryOutput(
            Path("/display-only/(unnamed temporary)"),
            41,
            ParentLock(),  # type: ignore[arg-type]
            False,
            metadata=regular_metadata(0),
        )
        with (
            patch.object(make_run_summary, "_using_windows", return_value=False),
            patch.object(
                make_run_summary._TemporaryOutput, "reverify_contents", return_value=None
            ),
            patch.object(
                make_run_summary,
                "_posix_link_unnamed_temporary_no_replace",
                return_value=None,
            ),
            patch.object(make_run_summary.os, "fstat", return_value=regular_metadata(1)),
        ):
            temporary.commit_no_replace(Path("/display-only/summary.json"))
            self.assertTrue(temporary.committed)
            self.assertEqual(
                temporary._assert_live_object(allow_metadata_change=True).st_nlink,
                1,
            )

        with (
            patch.object(make_run_summary, "_using_windows", return_value=False),
            patch.object(make_run_summary.os, "fstat", return_value=regular_metadata(2)),
        ):
            with self.assertRaisesRegex(InputError, "link count"):
                temporary._assert_live_object(allow_metadata_change=True)

        precommit = make_run_summary._TemporaryOutput(
            Path("/display-only/(unnamed temporary)"),
            41,
            ParentLock(),  # type: ignore[arg-type]
            False,
            metadata=regular_metadata(0),
        )
        with (
            patch.object(make_run_summary, "_using_windows", return_value=False),
            patch.object(make_run_summary.os, "fstat", return_value=regular_metadata(1)),
        ):
            with self.assertRaisesRegex(InputError, "link count"):
                precommit._assert_live_object()

    def test_posix_linkat_capability_fallback_uses_the_live_proc_descriptor(self) -> None:
        """A capability-blocked AT_EMPTY_PATH call retries through /proc/self/fd."""
        calls: list[tuple[object, ...]] = []

        class LinkAt:
            argtypes: object = None
            restype: object = None

            def __call__(self, *args: object) -> int:
                calls.append(args)
                if len(calls) == 1:
                    ctypes.set_errno(errno.ENOENT)
                    return -1
                return 0

        class LibC:
            linkat = LinkAt()

        with (
            patch.object(make_run_summary, "_using_windows", return_value=False),
            patch.object(make_run_summary.ctypes, "CDLL", return_value=LibC()),
        ):
            make_run_summary._posix_link_unnamed_temporary_no_replace(
                41, "summary.json", 73
            )

        self.assertEqual(
            calls,
            [
                (41, b"", 73, b"summary.json", 0x1000),
                (-100, b"/proc/self/fd/41", 73, b"summary.json", 0x400),
            ],
        )

    def test_posix_linkat_collision_and_missing_procfs_fail_closed(self) -> None:
        """No fallback overwrites an existing name, and unavailable procfs is an error."""
        for direct_errno, fallback_errno, expected_calls in (
            (errno.EEXIST, None, 1),
            (errno.ENOENT, errno.ENOENT, 2),
        ):
            with self.subTest(direct_errno=direct_errno, fallback_errno=fallback_errno):
                calls: list[tuple[object, ...]] = []

                class LinkAt:
                    argtypes: object = None
                    restype: object = None

                    def __call__(self, *args: object) -> int:
                        calls.append(args)
                        ctypes.set_errno(
                            direct_errno if len(calls) == 1 else fallback_errno  # type: ignore[arg-type]
                        )
                        return -1

                class LibC:
                    linkat = LinkAt()

                with (
                    patch.object(make_run_summary, "_using_windows", return_value=False),
                    patch.object(make_run_summary.ctypes, "CDLL", return_value=LibC()),
                ):
                    with self.assertRaises(OSError) as raised:
                        make_run_summary._posix_link_unnamed_temporary_no_replace(
                            41, "summary.json", 73
                        )

                self.assertEqual(raised.exception.errno, fallback_errno or direct_errno)
                self.assertEqual(len(calls), expected_calls)

    def test_posix_missing_otmpfile_capability_fails_closed(self) -> None:
        """A named-path fallback is forbidden when O_TMPFILE is unavailable."""

        class ParentLock:
            descriptor = 73

            def assert_path_matches_handle(self) -> None:
                return None

        with (
            patch.object(make_run_summary, "_using_windows", return_value=False),
            patch.object(make_run_summary.os, "O_TMPFILE", 0, create=True),
        ):
            with self.assertRaisesRegex(InputError, "O_TMPFILE"):
                make_run_summary._create_output_temporary(
                    Path("/display-only/summary.json"), ParentLock()  # type: ignore[arg-type]
                )

    def test_atomic_writer_fails_closed_when_temporary_cleanup_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            root = parent / "run"
            root.mkdir()
            artifact = root / "artifact.bin"
            artifact.write_bytes(b"artifact")
            draft = root / "run-summary.json"
            write_json(draft, self._classified_draft(root))
            output = parent / "summary.json"
            draft_before = draft.read_bytes()
            artifact_before = artifact.read_bytes()
            competitor = b"concurrent immutable output\n"
            original_cleanup = make_run_summary._cleanup_temporary_output

            def concurrent_no_replace_failure(
                temporary_path: Path,
                temporary_name: str | None,
                destination: Path,
                parent_lock: object,
            ) -> str | None:
                self.assertEqual(destination, output)
                destination.write_bytes(competitor)
                raise InputError(
                    "cannot publish summary without replacement: output appeared"
                )

            def cleanup_then_report(
                temporary_path: Path,
                temporary_name: str | None,
                parent_lock: object,
            ) -> None:
                original_cleanup(temporary_path, temporary_name, parent_lock)  # type: ignore[arg-type]
                raise InputError("cannot clean temporary summary output: cleanup reported")

            captured_stderr = io.StringIO()
            with (
                patch.object(
                    make_run_summary,
                    "_commit_output_no_replace",
                    side_effect=concurrent_no_replace_failure,
                ),
                patch.object(
                    make_run_summary,
                    "_cleanup_temporary_output",
                    side_effect=cleanup_then_report,
                ),
                contextlib.redirect_stderr(captured_stderr),
            ):
                result = make_run_summary.main(
                    ["--run-root", str(root), "--output", str(output)]
                )

            self.assertEqual(result, 1)
            self.assertIn("output appeared", captured_stderr.getvalue())
            self.assertIn("cleanup reported", captured_stderr.getvalue())
            self.assertNotIn("Traceback", captured_stderr.getvalue())
            self.assertEqual(output.read_bytes(), competitor)
            self.assertEqual(draft.read_bytes(), draft_before)
            self.assertEqual(artifact.read_bytes(), artifact_before)
            self.assertEqual(
                {path.name for path in parent.iterdir()}, {"run", "summary.json"}
            )

    def test_atomic_writer_chains_cleanup_error_to_precommit_failure(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            output = root / "summary.json"
            original_cleanup = make_run_summary._cleanup_temporary_output

            def cleanup_then_report(
                temporary_path: Path,
                temporary_name: str | None,
                parent_lock: object,
            ) -> None:
                original_cleanup(temporary_path, temporary_name, parent_lock)  # type: ignore[arg-type]
                raise InputError("cannot clean temporary summary output: cleanup reported")

            with (
                patch.object(
                    make_run_summary,
                    "_commit_output_no_replace",
                    side_effect=InputError("cannot publish summary without replacement: denied"),
                ),
                patch.object(
                    make_run_summary,
                    "_cleanup_temporary_output",
                    side_effect=cleanup_then_report,
                ),
            ):
                with self.assertRaisesRegex(
                    InputError, "without replacement: denied"
                ) as raised:
                    make_run_summary._write_json_atomically(
                        output, {"schemaVersion": 1}
                    )

            self.assertIsInstance(raised.exception.__cause__, InputError)
            self.assertIn("cleanup reported", str(raised.exception.__cause__))
            self.assertFalse(output.exists())
            self.assertEqual(list(root.iterdir()), [])

    def test_existing_output_identity_uncertainty_fails_closed_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            root = parent / "run"
            root.mkdir()
            (root / "artifact.bin").write_bytes(b"artifact")
            write_json(root / "run-summary.json", self._classified_draft(root))
            output = parent / "summary.json"
            original = b"old output\n"
            output.write_bytes(original)

            with patch.object(
                make_run_summary._ExistingOutput,
                "assert_path_stable",
                side_effect=InputError("output identity unavailable"),
            ), contextlib.redirect_stderr(io.StringIO()):
                result = make_run_summary.main(
                    ["--run-root", str(root), "--output", str(output)]
                )

            self.assertEqual(result, 1)
            self.assertEqual(output.read_bytes(), original)
            self.assertEqual({path.name for path in parent.iterdir()}, {"run", "summary.json"})

    def test_directory_lock_hook_failure_releases_the_opened_lock(self) -> None:
        """A test seam failure during __enter__ must not leak a live lock."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "run"
            root.mkdir()
            closed: list[str] = []

            class RecordingLock:
                def close(self) -> None:
                    closed.append("closed")

            lock = RecordingLock()
            with (
                patch.object(
                    make_run_summary, "_open_directory_lock", return_value=lock
                ),
                patch.object(
                    make_run_summary,
                    "_after_directory_lock_open",
                    side_effect=InputError("simulated seam failure"),
                ),
            ):
                with self.assertRaisesRegex(InputError, "simulated seam failure"):
                    with make_run_summary._RunDirectoryLocks(root):
                        self.fail("the hook should have raised before entering")

            self.assertEqual(closed, ["closed"])

    def test_nth_directory_lock_hook_failure_closes_once_in_reverse_order(self) -> None:
        """Current and previously acquired locks release exactly once on failure."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "run"
            root.mkdir()
            closed: list[str] = []

            class RecordingLock:
                def __init__(self, name: str) -> None:
                    self.name = name

                def close(self) -> None:
                    closed.append(self.name)

            first = RecordingLock("first")
            second = RecordingLock("second")
            third = RecordingLock("third")

            def fail_on_third(lock: object) -> None:
                if lock is third:
                    raise InputError("simulated third-lock seam failure")

            with (
                patch.object(
                    make_run_summary,
                    "_open_directory_lock",
                    side_effect=[first, second, third],
                ),
                patch.object(
                    make_run_summary,
                    "_after_directory_lock_open",
                    side_effect=fail_on_third,
                ),
            ):
                with self.assertRaisesRegex(InputError, "third-lock"):
                    with make_run_summary._RunDirectoryLocks(root) as locks:
                        locks.open(root / "child")
                        locks.open(root / "child" / "grandchild")

            self.assertEqual(closed, ["third", "second", "first"])

    def test_posix_descriptor_helpers_use_parent_file_descriptors(self) -> None:
        """The non-Windows seams keep child opens rooted at the held parent fd."""
        with (
            patch.object(make_run_summary.os, "O_DIRECTORY", 0x2000, create=True),
            patch.object(make_run_summary.os, "O_NOFOLLOW", 0x1000, create=True),
            patch.object(make_run_summary.os, "open", return_value=41) as opening,
        ):
            directory_descriptor = make_run_summary._open_posix_directory_descriptor(
                "child", parent_descriptor=17
            )
        self.assertEqual(directory_descriptor, 41)
        directory_args, directory_kwargs = opening.call_args
        self.assertEqual(directory_args[0], "child")
        self.assertEqual(directory_kwargs["dir_fd"], 17)
        self.assertTrue(directory_args[1] & 0x2000)
        self.assertTrue(directory_args[1] & 0x1000)

        with (
            patch.object(make_run_summary, "_using_windows", return_value=False),
            patch.object(make_run_summary.os, "O_NOFOLLOW", 0x1000, create=True),
            patch.object(make_run_summary.os, "O_NOATIME", 0x4000, create=True),
            patch.object(make_run_summary.os, "open", return_value=43) as opening,
        ):
            file_descriptor, native_information = (
                make_run_summary._open_regular_file_descriptor(
                    Path("display-only"),
                    parent_descriptor=17,
                    entry_name="child.bin",
                )
            )
        self.assertEqual(file_descriptor, 43)
        self.assertIsNone(native_information)
        file_args, file_kwargs = opening.call_args
        self.assertEqual(file_args[0], "child.bin")
        self.assertEqual(file_kwargs["dir_fd"], 17)
        self.assertTrue(file_args[1] & 0x1000)
        self.assertTrue(file_args[1] & 0x4000)

    def test_posix_regular_file_open_requires_no_follow_and_no_atime(self) -> None:
        """Unsafe or unavailable no-follow/no-atime flags fail before opening."""
        for attribute in ("O_NOFOLLOW", "O_NOATIME"):
            with (
                self.subTest(attribute=attribute),
                patch.object(make_run_summary, "_using_windows", return_value=False),
                patch.object(make_run_summary.os, "O_NOFOLLOW", 0x1000, create=True),
                patch.object(make_run_summary.os, "O_NOATIME", 0x4000, create=True),
                patch.object(make_run_summary.os, attribute, 0, create=True),
                patch.object(make_run_summary.os, "open", return_value=43) as opening,
            ):
                with self.assertRaisesRegex(InputError, attribute):
                    make_run_summary._open_regular_file_descriptor(
                        Path("display-only"),
                        parent_descriptor=17,
                        entry_name="child.bin",
                    )
                opening.assert_not_called()

    def test_posix_regular_file_open_noatime_errors_fail_closed(self) -> None:
        """Capability and permission failures never fall back to pathname timestamp repair."""
        flags = {"O_NOFOLLOW": 0x1000, "O_NOATIME": 0x4000}
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            source = parent / "input.bin"
            output = parent / "summary.json"
            source.write_bytes(b"input bytes must remain unchanged\n")
            expected = source.read_bytes()
            before = source.stat()
            for error in (TypeError("unsupported flags"), PermissionError(1, "denied")):
                with (
                    self.subTest(error=type(error).__name__),
                    patch.object(make_run_summary, "_using_windows", return_value=False),
                    patch.multiple(make_run_summary.os, create=True, **flags),
                    patch.object(make_run_summary.os, "open", side_effect=error),
                    patch.object(make_run_summary.os, "utime") as restore_time,
                ):
                    with self.assertRaises(InputError):
                        make_run_summary._open_regular_file_descriptor(
                            source,
                            parent_descriptor=17,
                            entry_name="child.bin",
                        )
                    restore_time.assert_not_called()
                after = source.stat()
                self.assertEqual(after.st_atime_ns, before.st_atime_ns)
                self.assertEqual(after.st_mtime_ns, before.st_mtime_ns)
                self.assertEqual(after.st_ctime_ns, before.st_ctime_ns)
                self.assertFalse(output.exists())
            self.assertEqual(source.read_bytes(), expected)

    def test_posix_walk_enumerates_from_the_locked_directory_descriptor(self) -> None:
        """A non-Windows scan must not reopen its directory by a mutable path."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            metadata = os.stat_result(
                (stat.S_IFREG | 0o600, 0, 0, 1, 0, 0, 4, 0, 0, 0)
            )

            class LockedDirectory:
                path = root
                descriptor = 73

                def assert_stable(self) -> None:
                    return None

            class Locks:
                root = LockedDirectory()

                def open(self, *args: object, **kwargs: object) -> object:
                    raise AssertionError("a regular file must not open a child lock")

            class Entry:
                name = "artifact.bin"

            class Scan:
                def __enter__(self) -> object:
                    return iter([Entry()])

                def __exit__(self, *args: object) -> None:
                    return None

            locks = Locks()
            with (
                patch.object(make_run_summary, "_using_windows", return_value=False),
                patch.object(make_run_summary.os, "scandir", return_value=Scan()) as scan,
                patch.object(
                    make_run_summary, "_stat_unfollowed", return_value=metadata
                ) as stat_unfollowed,
            ):
                files, blockers = make_run_summary._walk_run_root(root, locks)  # type: ignore[arg-type]

            self.assertEqual(blockers, set())
            self.assertEqual([entry[0] for entry in files], ["artifact.bin"])
            self.assertEqual(scan.call_args.args, (73,))
            self.assertEqual(
                stat_unfollowed.call_args.kwargs,
                {"parent_descriptor": 73, "entry_name": "artifact.bin"},
            )

    @unittest.skipUnless(os.name == "nt", "requires Windows handle sharing")
    def test_windows_directory_lock_rejects_rename_until_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            root = parent / "run"
            moved = parent / "moved"
            root.mkdir()

            with make_run_summary._open_directory_lock(root):
                with self.assertRaises(OSError) as blocked:
                    os.replace(root, moved)
                self.assertEqual(blocked.exception.winerror, 32)

            os.replace(root, moved)
            self.assertTrue(moved.is_dir())

    @unittest.skipUnless(os.name == "nt", "requires Windows handle sharing")
    def test_windows_open_failure_surfaces_close_handle_failure(self) -> None:
        with (
            patch.object(make_run_summary, "_create_file", return_value=123),
            patch.object(
                make_run_summary.msvcrt,
                "open_osfhandle",
                side_effect=OSError("descriptor conversion failed"),
            ),
            patch.object(make_run_summary, "_close_handle", return_value=0),
            patch.object(make_run_summary.ctypes, "get_last_error", return_value=6),
        ):
            with self.assertRaisesRegex(OSError, "CloseHandle"):
                make_run_summary._windows_open_descriptor(
                    Path("C:/untrusted/path"), directory=False
                )

    @unittest.skipUnless(os.name == "nt", "requires Windows handle sharing")
    def test_windows_root_lock_blocks_external_directory_swap_before_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            root = parent / "run"
            root.mkdir()
            write_json(root / "run-summary.json", self._classified_draft(root))
            external = parent / "external"
            external.mkdir()
            sentinel = external / "outside.bin"
            sentinel.write_bytes(b"external sentinel must not be read")
            parked = parent / "parked"
            blocked: list[bool] = []

            def attempt_swap(lock: object) -> None:
                if getattr(lock, "path", None) != root:
                    return
                try:
                    os.replace(root, parked)
                except OSError as error:
                    self.assertEqual(error.winerror, 32)
                    blocked.append(True)
                else:
                    self.fail("root directory lock allowed a replacement")

            with patch.object(
                make_run_summary,
                "_after_directory_lock_open",
                side_effect=attempt_swap,
            ):
                summary = build_run_summary(root)

            self.assertEqual(blocked, [True])
            self.assertEqual(sentinel.read_bytes(), b"external sentinel must not be read")
            self.assertEqual(
                [record["path"] for record in summary["inventory"]], ["run-summary.json"]
            )

    @unittest.skipUnless(os.name == "nt", "requires Windows handle sharing")
    def test_windows_file_replacement_before_handle_hash_fails_without_output_change(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            root = parent / "run"
            root.mkdir()
            artifact = root / "artifact.bin"
            artifact.write_bytes(b"expected artifact")
            write_json(root / "run-summary.json", self._classified_draft(root))
            replacement = parent / "replacement.bin"
            replacement.write_bytes(b"replacement must not be hashed")
            output = parent / "summary.json"
            original = b"old output\n"
            output.write_bytes(original)
            replaced: list[Path] = []

            def replace_before_open(path: Path, expected: os.stat_result) -> None:
                if path == artifact:
                    os.replace(replacement, artifact)
                    replaced.append(path)

            with patch.object(
                make_run_summary,
                "_before_regular_file_open",
                side_effect=replace_before_open,
            ), contextlib.redirect_stderr(io.StringIO()):
                result = make_run_summary.main(
                    ["--run-root", str(root), "--output", str(output)]
                )

            self.assertEqual(replaced, [artifact])
            self.assertEqual(result, 1)
            self.assertEqual(output.read_bytes(), original)
            self.assertEqual(
                {path.name for path in parent.iterdir()}, {"run", "summary.json"}
            )

    @unittest.skipUnless(os.name == "nt", "requires Windows output-parent lock")
    def test_windows_output_parent_instability_cleans_temp_before_initial_publish(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            root = parent / "run"
            root.mkdir()
            (root / "artifact.bin").write_bytes(b"artifact")
            write_json(root / "run-summary.json", self._classified_draft(root))
            output = parent / "summary.json"

            with patch.object(
                make_run_summary,
                "_before_atomic_replace",
                side_effect=InputError("output parent changed"),
            ), contextlib.redirect_stderr(io.StringIO()):
                result = make_run_summary.main(
                    ["--run-root", str(root), "--output", str(output)]
                )

            self.assertEqual(result, 1)
            self.assertFalse(output.exists())
            self.assertEqual({path.name for path in parent.iterdir()}, {"run"})

    def test_cli_is_atomic_rejects_output_inside_or_aliasing_run_root_and_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            root = parent / "run"
            root.mkdir()
            artifact = root / "artifact.bin"
            artifact.write_bytes(b"artifact")
            write_json(root / "run-summary.json", self._classified_draft(root))
            before = {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}
            output = parent / "summary.json"
            command = [
                sys.executable,
                "-B",
                str(SKILL_ROOT / "scripts" / "make_run_summary.py"),
                "--run-root",
                str(root),
                "--output",
                str(output),
            ]

            first = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(first.returncode, 2, first.stderr)
            first_bytes = output.read_bytes()
            repeated = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(repeated.returncode, 2, repeated.stderr)
            self.assertEqual(output.read_bytes(), first_bytes)
            self.assertEqual(
                {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()},
                before,
            )

            inside = root / "new-summary.json"
            rejected = subprocess.run(
                [*command[:-1], str(inside)], capture_output=True, text=True
            )
            self.assertEqual(rejected.returncode, 1)
            self.assertFalse(inside.exists())

            original = artifact.read_bytes()
            alias = parent / "artifact-output.json"
            try:
                alias.hardlink_to(artifact)
            except OSError as error:
                self.skipTest(f"hard links unavailable: {error}")
            alias_rejected = subprocess.run(
                [*command[:-1], str(alias)], capture_output=True, text=True
            )
            self.assertEqual(alias_rejected.returncode, 1)
            self.assertEqual(artifact.read_bytes(), original)

    def test_release_summary_is_final_only_after_hash_bound_evidence_and_authorities(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            root = parent / "run"
            root.mkdir()
            artifact = root / "package.bin"
            artifact.write_bytes(b"release package")
            artifact_sha = hashlib.sha256(artifact.read_bytes()).hexdigest()
            draft = draft_summary()
            bound = write_bound_evidence(
                root, artifact_sha, include_installation=True
            )
            draft.update(
                {
                    "installAuthority": True,
                    "integrationAuthority": True,
                    "publicationAuthority": True,
                    "requiredSoakMinutes": 30,
                    "observedSoakMinutes": 30,
                    "soakVerdict": "pass",
                }
            )
            draft.update(bound)
            draft["localState"]["keep"] = [  # type: ignore[index]
                "run-summary.json",
                *bound["paths"],  # type: ignore[index]
            ]
            write_json(root / "run-summary.json", draft)
            output = parent / "summary.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SKILL_ROOT / "scripts" / "make_run_summary.py"),
                    "--run-root",
                    str(root),
                    "--output",
                    str(output),
                ],
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            rendered = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(rendered["finalSummary"])
            self.assertEqual(rendered["maturity"], "release-candidate")

    def test_invalid_verified_artifact_declaration_invalidates_the_entire_context(self) -> None:
        """One bad declaration must not leave enough trusted hashes to release."""
        cases = {
            "valid-then-duplicate": lambda root, draft: draft["verifiedArtifacts"].append(  # type: ignore[index]
                deepcopy(draft["verifiedArtifacts"][0])  # type: ignore[index]
            ),
            "malformed": lambda root, draft: draft["verifiedArtifacts"].append(  # type: ignore[index]
                {"path": "malformed.bin", "expectedSha256": "not-a-sha"}
            ),
            "traversal": lambda root, draft: draft["verifiedArtifacts"].append(  # type: ignore[index]
                {"path": "../outside.bin", "expectedSha256": "f" * 64}
            ),
            "missing": lambda root, draft: draft["verifiedArtifacts"].append(  # type: ignore[index]
                {"path": "missing.bin", "expectedSha256": "f" * 64}
            ),
            "mismatch": lambda root, draft: (
                (root / "qa").mkdir(exist_ok=True),
                (root / "qa" / "preview.webp").write_bytes(b"real preview"),
                draft["localState"]["keep"].append("qa/preview.webp"),  # type: ignore[index]
                draft["verifiedArtifacts"].append(  # type: ignore[index]
                    {"path": "qa/preview.webp", "expectedSha256": "f" * 64}
                ),
            ),
        }
        for label, corrupt in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                package = root / "package.bin"
                package.write_bytes(b"release package")
                package_sha = hashlib.sha256(package.read_bytes()).hexdigest()
                draft = draft_summary()
                bound = write_bound_evidence(
                    root, package_sha, include_installation=True
                )
                draft.update(bound)
                draft.update(
                    {
                        "installAuthority": True,
                        "integrationAuthority": True,
                        "publicationAuthority": True,
                        "requiredSoakMinutes": 30,
                        "observedSoakMinutes": 30,
                        "soakVerdict": "pass",
                    }
                )
                draft["localState"]["keep"] = [  # type: ignore[index]
                    "run-summary.json", *bound["paths"]  # type: ignore[index]
                ]
                corrupt(root, draft)
                write_json(root / "run-summary.json", draft)

                summary = build_run_summary(root)

                self.assertEqual(summary["runtimeStatus"], "unverified")
                self.assertEqual(summary["installedStatus"], "unverified")
                self.assertNotEqual(summary["maturity"], "release-candidate")
                self.assertFalse(summary["releaseAuthority"])
                self.assertFalse(summary["finalSummary"])


if __name__ == "__main__":
    unittest.main()
