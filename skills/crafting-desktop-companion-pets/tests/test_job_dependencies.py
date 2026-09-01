from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from contracts import (
    Issue,
    invalidate_descendants,
    ready_job_ids,
    transition_job,
    validate_action_contract,
    validate_identity_contract,
    validate_job_manifest,
    validate_reference_roles,
    validate_visual_verdict,
)
from prepare_generation_jobs import InputError, _write_json_atomically


HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
JSON_NESTING_LIMIT = 128
JSON_SHAPED_VALUES = (
    ("null", None),
    ("bool", True),
    ("integer", 1),
    ("float", 1.5),
    ("text", "text"),
    ("list", []),
    ("object", {}),
)


def action_contract(action_id: str = "walk-right") -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "actionId": action_id,
        "family": "ordinary-locomotion",
        "riskClass": "cyclic-locomotion",
        "identitySha256": HASH_A,
        "desktopRole": "ordinary-right-movement",
        "phases": [
            {
                "id": "entry",
                "bodyState": "right foot loads",
                "faceState": "forward",
                "handState": "balanced",
                "hairGarmentState": "settled",
                "propEffectState": "absent",
                "propLifecycleStage": None,
                "effectLifecycleStage": None,
                "anchor": "body",
                "durationMs": 120,
                "keyPose": True,
            },
            {
                "id": "development",
                "bodyState": "left leg passes and torso leans",
                "faceState": "forward",
                "handState": "counter-swing",
                "hairGarmentState": "trails motion",
                "propEffectState": "absent",
                "propLifecycleStage": None,
                "effectLifecycleStage": None,
                "anchor": "world",
                "durationMs": 90,
                "keyPose": True,
            },
            {
                "id": "return",
                "bodyState": "right foot contacts",
                "faceState": "forward",
                "handState": "counter-swing reverses",
                "hairGarmentState": "settles",
                "propEffectState": "absent",
                "propLifecycleStage": None,
                "effectLifecycleStage": None,
                "anchor": "world",
                "durationMs": 120,
                "keyPose": True,
            },
        ],
        "worldMotionPhaseIds": ["development", "return"],
        "stableFeatures": ["identity", "body occupancy"],
        "allowedChanges": ["limbs", "cloth response"],
        "forbiddenChanges": ["head scale", "costume structure"],
        "interrupt": {"safePhaseIds": ["entry", "return"], "recoveryAction": "idle"},
        "behavior": {
            "manualEligible": True,
            "autoplayEligible": True,
            "pool": "movement",
            "weight": 1,
            "cooldownMs": 0,
            "sharedGroup": "ordinary-move",
        },
        "selection": "candidate",
    }


def job_manifest() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "jobs": [
            {
                "id": "identity",
                "kind": "identity",
                "status": "selected",
                "dependsOn": [],
                "inputHashes": {},
                "artifactSha256": HASH_A,
                "canonicalIdentitySha256": HASH_A,
                "technicalVerdictId": "identity-tech",
                "visualVerdictId": "identity-visual",
                "retryCount": 0,
            },
            {
                "id": "walk-key-poses",
                "kind": "semantic-key-poses",
                "status": "pending",
                "dependsOn": ["identity"],
                "inputHashes": {"identity": HASH_A},
                "artifactSha256": None,
                "canonicalIdentitySha256": HASH_A,
                "technicalVerdictId": None,
                "visualVerdictId": None,
                "retryCount": 0,
            },
            {
                "id": "walk-atlas",
                "kind": "atlas",
                "status": "pending",
                "dependsOn": ["walk-key-poses"],
                "inputHashes": {},
                "artifactSha256": None,
                "canonicalIdentitySha256": HASH_A,
                "technicalVerdictId": None,
                "visualVerdictId": None,
                "retryCount": 0,
            },
        ],
    }


def issue_codes(issues: list[object]) -> set[str]:
    return {issue.code for issue in issues}


def nested_lists(depth: int) -> object:
    value: object = "leaf"
    for _ in range(depth):
        value = [value]
    return value


class ActionContractTest(unittest.TestCase):
    def test_action_contract_requires_semantic_locomotion_recovery_and_lifecycle(self) -> None:
        action = action_contract()

        self.assertEqual(validate_action_contract(action), [])

        repeated_body_states = deepcopy(action)
        for phase in repeated_body_states["phases"]:
            phase["bodyState"] = "standing"
        self.assertIn(
            "LOCOMOTION_KEY_POSES_REQUIRED",
            issue_codes(validate_action_contract(repeated_body_states)),
        )

        body_anchored_motion = deepcopy(action)
        body_anchored_motion["worldMotionPhaseIds"] = ["entry"]
        self.assertIn(
            "WORLD_MOTION_ANCHOR_MISMATCH",
            issue_codes(validate_action_contract(body_anchored_motion)),
        )

        no_return_or_recovery = deepcopy(action)
        no_return_or_recovery["phases"] = [
            phase for phase in no_return_or_recovery["phases"] if phase["id"] != "return"
        ]
        no_return_or_recovery["interrupt"]["recoveryAction"] = None
        self.assertIn(
            "RECOVERY_REQUIRED",
            issue_codes(validate_action_contract(no_return_or_recovery)),
        )

        incomplete_effect = deepcopy(action)
        incomplete_effect["phases"][1]["effectLifecycleStage"] = "peak"
        self.assertIn(
            "EFFECT_LIFECYCLE_INCOMPLETE",
            issue_codes(validate_action_contract(incomplete_effect)),
        )

    def test_action_contract_rejects_empty_semantic_lists_and_unlisted_world_motion(
        self,
    ) -> None:
        action = action_contract()
        action["stableFeatures"] = []
        action["allowedChanges"] = []
        action["forbiddenChanges"] = []
        action["worldMotionPhaseIds"] = ["return"]

        codes = issue_codes(validate_action_contract(action))

        self.assertIn("ACTION_SEMANTIC_LIST_INVALID", codes)
        self.assertIn("WORLD_MOTION_PHASE_MISSING", codes)

    def test_action_contract_returns_issues_for_malformed_lifecycle_values(self) -> None:
        action = action_contract()
        action["phases"][0]["propLifecycleStage"] = []
        action["phases"][1]["effectLifecycleStage"] = "not-a-lifecycle-stage"

        self.assertIn(
            "ACTION_LIFECYCLE_STAGE_INVALID",
            issue_codes(validate_action_contract(action)),
        )

    def test_action_contract_requires_an_exact_integer_schema_version(self) -> None:
        action = action_contract()
        action["schemaVersion"] = True

        self.assertIn(
            "ACTION_SCHEMA_VERSION_INVALID",
            issue_codes(validate_action_contract(action)),
        )

    def test_action_contract_rejects_nonfinite_behavior_numbers(self) -> None:
        for field in ("weight", "cooldownMs"):
            for value in (True, float("nan"), float("inf"), float("-inf")):
                with self.subTest(field=field, value=value):
                    action = action_contract()
                    action["behavior"][field] = value

                    self.assertIn(
                        "ACTION_BEHAVIOR_NUMBER_INVALID",
                        issue_codes(validate_action_contract(action)),
                    )

    def test_action_contract_accepts_arbitrarily_large_finite_integers(self) -> None:
        action = action_contract()
        action["behavior"]["weight"] = int("9" * 1000)
        action["behavior"]["cooldownMs"] = int("8" * 1000)

        self.assertEqual(validate_action_contract(action), [])

    def test_public_validators_return_issue_lists_for_json_type_matrix(self) -> None:
        validator_cases = (
            (
                "reference-route",
                lambda value: validate_reference_roles(
                    {
                        "id": "reference",
                        "roles": ["identity"],
                        "allowedUses": ["canonical-identity"],
                        "evidenceClass": "current-official",
                    },
                    value,
                ),
            ),
            (
                "identity-route",
                lambda value: validate_identity_contract(
                    {
                        "identityRoute": value,
                        "referenceIds": [],
                        "canonicalPath": None,
                        "canonicalSha256": None,
                        "technicalStatus": "not-run",
                        "authority": {"identityUncertaintyApproved": False},
                    }
                ),
            ),
            (
                "visual-decision",
                lambda value: validate_visual_verdict(
                    {
                        "verdictId": None,
                        "gate": "visual",
                        "decision": value,
                        "reviewScale": "not-reviewed",
                        "artifactSha256": None,
                        "reviewer": {"type": "unassigned", "id": None},
                    }
                ),
            ),
            (
                "action-selection",
                lambda value: validate_action_contract(
                    {**action_contract(), "selection": value}
                ),
            ),
            (
                "action-anchor",
                lambda value: validate_action_contract(
                    {
                        **action_contract(),
                        "phases": [
                            {
                                **action_contract()["phases"][0],
                                "anchor": value,
                            },
                            *action_contract()["phases"][1:],
                        ],
                    }
                ),
            ),
            (
                "job-status",
                lambda value: validate_job_manifest(
                    {
                        **job_manifest(),
                        "jobs": [
                            {**job_manifest()["jobs"][0], "status": value},
                            *job_manifest()["jobs"][1:],
                        ],
                    }
                ),
            ),
        )
        for field, validator in validator_cases:
            for value_name, value in JSON_SHAPED_VALUES:
                with self.subTest(field=field, value=value_name):
                    issues = validator(value)

                    self.assertIsInstance(issues, list)
                    self.assertTrue(all(isinstance(issue, Issue) for issue in issues))

    def test_text_validators_reject_lone_surrogates(self) -> None:
        action = action_contract()
        action["actionId"] = "\ud800"
        self.assertIn(
            "ACTION_TEXT_FIELD_REQUIRED",
            issue_codes(validate_action_contract(action)),
        )

        identity = {
            "projectId": "\ud800",
            "identityRoute": "source-faithful",
            "referenceIds": [],
            "canonicalPath": None,
            "canonicalSha256": None,
            "technicalStatus": "not-run",
            "authority": {"identityUncertaintyApproved": False},
        }
        self.assertIn(
            "IDENTITY_PROJECT_ID_INVALID",
            issue_codes(validate_identity_contract(identity)),
        )

    def test_public_validators_preflight_unknown_nested_extensions(self) -> None:
        within_limit = action_contract()
        within_limit["extension"] = nested_lists(JSON_NESTING_LIMIT)
        self.assertEqual(validate_action_contract(within_limit), [])

        validator_cases = (
            (
                "reference",
                lambda: validate_reference_roles(
                    {
                        "id": "reference",
                        "roles": ["identity"],
                        "allowedUses": ["canonical-identity"],
                        "evidenceClass": "current-official",
                        "extension": nested_lists(JSON_NESTING_LIMIT + 1),
                    },
                    "source-faithful",
                ),
            ),
            (
                "identity",
                lambda: validate_identity_contract(
                    {
                        "identityRoute": "source-faithful",
                        "referenceIds": [],
                        "canonicalPath": None,
                        "canonicalSha256": None,
                        "technicalStatus": "not-run",
                        "authority": {"identityUncertaintyApproved": False},
                        "extension": nested_lists(JSON_NESTING_LIMIT + 1),
                    }
                ),
            ),
            (
                "visual",
                lambda: validate_visual_verdict(
                    {
                        "verdictId": None,
                        "gate": "visual",
                        "decision": "not-reviewed",
                        "reviewScale": "not-reviewed",
                        "artifactSha256": None,
                        "reviewer": {"type": "unassigned", "id": None},
                        "extension": nested_lists(JSON_NESTING_LIMIT + 1),
                    }
                ),
            ),
            (
                "action",
                lambda: validate_action_contract(
                    {
                        **action_contract(),
                        "extension": nested_lists(JSON_NESTING_LIMIT + 1),
                    }
                ),
            ),
            (
                "manifest",
                lambda: validate_job_manifest(
                    {
                        **job_manifest(),
                        "extension": nested_lists(JSON_NESTING_LIMIT + 1),
                    }
                ),
            ),
        )
        for label, validator in validator_cases:
            with self.subTest(validator=label):
                self.assertIn(
                    "JSON_STRUCTURE_DEPTH_EXCEEDED",
                    issue_codes(validator()),
                )

    def test_json_structure_preflight_rejects_aliases_and_cycles(self) -> None:
        invalid_keys = job_manifest()
        invalid_keys["extension"] = {1: "non-text", "\ud800": "surrogate"}
        self.assertIn(
            "JSON_STRUCTURE_KEY_INVALID",
            issue_codes(validate_job_manifest(invalid_keys)),
        )

        shared: list[object] = []
        aliased = job_manifest()
        aliased["extension"] = {"first": shared, "second": shared}

        self.assertIn(
            "JSON_STRUCTURE_SHARED_CONTAINER",
            issue_codes(validate_job_manifest(aliased)),
        )
        self.assertIs(aliased["extension"]["first"], shared)

        cyclic: list[object] = []
        cyclic.append(cyclic)
        cyclic_manifest = job_manifest()
        cyclic_manifest["extension"] = cyclic
        self.assertIn(
            "JSON_STRUCTURE_CYCLE",
            issue_codes(validate_job_manifest(cyclic_manifest)),
        )


class JobDependencyTest(unittest.TestCase):
    def test_job_mutators_reject_json_type_matrix_with_controlled_errors(
        self,
    ) -> None:
        for value_name, value in JSON_SHAPED_VALUES:
            with self.subTest(value=value_name):
                manifest = job_manifest()
                original = json.dumps(manifest, sort_keys=True)

                with self.assertRaises(ValueError):
                    transition_job(manifest, value, "ready")
                with self.assertRaises(ValueError):
                    invalidate_descendants(manifest, value, HASH_B)

                self.assertEqual(json.dumps(manifest, sort_keys=True), original)

    def test_mutators_preflight_deep_extensions_before_copying(self) -> None:
        manifest = job_manifest()
        manifest["extension"] = nested_lists(500)
        original = json.dumps(manifest, sort_keys=True)

        self.assertIn(
            "JSON_STRUCTURE_DEPTH_EXCEEDED",
            issue_codes(validate_job_manifest(manifest)),
        )
        with self.assertRaisesRegex(ValueError, "JSON_STRUCTURE_DEPTH_EXCEEDED"):
            transition_job(manifest, "walk-key-poses", "ready")
        with self.assertRaisesRegex(ValueError, "JSON_STRUCTURE_DEPTH_EXCEEDED"):
            invalidate_descendants(manifest, "identity", HASH_B)
        self.assertEqual(json.dumps(manifest, sort_keys=True), original)

        failure_record = {"extension": nested_lists(500)}
        failure_original = json.dumps(failure_record, sort_keys=True)
        with self.assertRaisesRegex(ValueError, "JSON_STRUCTURE_DEPTH_EXCEEDED"):
            transition_job(
                job_manifest(),
                "walk-key-poses",
                "blocked",
                failure_record=failure_record,
            )
        self.assertEqual(json.dumps(failure_record, sort_keys=True), failure_original)

    def test_ready_jobs_transition_in_order_without_mutating_the_source(self) -> None:
        manifest = job_manifest()
        original = json.dumps(manifest, sort_keys=True)

        self.assertEqual(validate_job_manifest(manifest), [])
        self.assertEqual(ready_job_ids(manifest), ["walk-key-poses"])
        with self.assertRaises(ValueError):
            transition_job(manifest, "walk-key-poses", "selected")

        ready = transition_job(manifest, "walk-key-poses", "ready")
        generating = transition_job(ready, "walk-key-poses", "generating")
        candidate = transition_job(
            generating,
            "walk-key-poses",
            "candidate",
            artifact_sha256=HASH_B,
        )
        candidate["jobs"][1]["technicalVerdictId"] = "walk-tech"
        technical_pass = transition_job(
            candidate,
            "walk-key-poses",
            "technical-pass",
        )
        technical_pass["jobs"][1]["visualVerdictId"] = "walk-visual"
        visual_pass = transition_job(
            technical_pass,
            "walk-key-poses",
            "visual-pass",
        )
        selected = transition_job(visual_pass, "walk-key-poses", "selected")

        self.assertEqual(ready_job_ids(selected), ["walk-atlas"])
        self.assertEqual(json.dumps(manifest, sort_keys=True), original)
        selected["jobs"][1]["inputHashes"]["identity"] = HASH_B
        self.assertEqual(manifest["jobs"][1]["inputHashes"]["identity"], HASH_A)

    def test_dependency_hashes_are_case_insensitive_for_readiness_and_transition(
        self,
    ) -> None:
        manifest = job_manifest()
        manifest["jobs"][0]["artifactSha256"] = HASH_A.upper()

        self.assertEqual(validate_job_manifest(manifest), [])
        self.assertEqual(ready_job_ids(manifest), ["walk-key-poses"])

        ready = deepcopy(manifest)
        ready["jobs"][1]["status"] = "ready"
        self.assertEqual(validate_job_manifest(ready), [])
        generating = transition_job(ready, "walk-key-poses", "generating")
        self.assertEqual(generating["jobs"][1]["status"], "generating")
        self.assertEqual(generating["jobs"][0]["artifactSha256"], HASH_A.upper())
        self.assertEqual(generating["jobs"][1]["inputHashes"]["identity"], HASH_A)

    def test_failure_records_require_controlled_causal_change_after_second_recurrence(
        self,
    ) -> None:
        blocked = job_manifest()
        blocked["jobs"][1]["status"] = "blocked"
        self.assertIn(
            "FAILURE_RECORD_REQUIRED",
            issue_codes(validate_job_manifest(blocked)),
        )

        blocked["jobs"][1].update(
            {
                "failureClass": "identity",
                "rootCondition": "actual-size silhouette remains top-heavy",
                "changedVariable": "proportion-governing full-body reference",
                "preserve": ["approved face", "approved costume palette"],
                "nextStrategy": "replace-reference-evidence",
                "retryCount": 2,
                "failureHistory": [
                    {
                        "failureClass": "identity",
                        "rootCondition": "actual-size silhouette remains top-heavy",
                    },
                    {
                        "failureClass": "identity",
                        "rootCondition": "actual-size silhouette remains top-heavy",
                    },
                ],
                "strategyChange": {
                    "classification": "causal-reference-evidence",
                    "causalInputs": ["target-specific full-body evidence"],
                    "causalEvidence": [
                        {
                            "inputId": "target-full-body-reference",
                            "beforeSha256": HASH_A,
                            "afterSha256": HASH_B,
                        }
                    ],
                },
            }
        )
        self.assertEqual(validate_job_manifest(blocked), [])

        wording_only = deepcopy(blocked)
        wording_only["jobs"][1]["nextStrategy"] = "prompt-wording-only"
        wording_only["jobs"][1]["strategyChange"] = {
            "classification": "prompt-wording-only",
            "causalInputs": [],
            "causalEvidence": [],
        }
        self.assertIn(
            "RECURRENCE_STRATEGY_INSUFFICIENT",
            issue_codes(validate_job_manifest(wording_only)),
        )

        empty_preserve = deepcopy(blocked)
        empty_preserve["jobs"][1]["preserve"] = []
        self.assertIn(
            "FAILURE_RECORD_REQUIRED",
            issue_codes(validate_job_manifest(empty_preserve)),
        )

        history_length_mismatch = deepcopy(blocked)
        history_length_mismatch["jobs"][1]["failureHistory"] = [
            {
                "failureClass": "identity",
                "rootCondition": "actual-size silhouette remains top-heavy",
            }
        ]
        self.assertIn(
            "FAILURE_HISTORY_INVALID",
            issue_codes(validate_job_manifest(history_length_mismatch)),
        )

        cloaked_prompt_only = deepcopy(blocked)
        cloaked_prompt_only["jobs"][1]["nextStrategy"] = (
            "rewrite only the generator instructions"
        )
        self.assertIn(
            "FAILURE_STRATEGY_INVALID",
            issue_codes(validate_job_manifest(cloaked_prompt_only)),
        )

        request_text_only = deepcopy(blocked)
        request_text_only["jobs"][1]["nextStrategy"] = "edit only the request text"
        self.assertIn(
            "FAILURE_STRATEGY_INVALID",
            issue_codes(validate_job_manifest(request_text_only)),
        )

        wrong_code_classification = deepcopy(blocked)
        wrong_code_classification["jobs"][1]["nextStrategy"] = (
            "revise-layout-composition"
        )
        self.assertIn(
            "FAILURE_STRATEGY_INVALID",
            issue_codes(validate_job_manifest(wrong_code_classification)),
        )

        claimed_causal_inputs_only = deepcopy(blocked)
        del claimed_causal_inputs_only["jobs"][1]["strategyChange"][
            "causalEvidence"
        ]
        self.assertIn(
            "FAILURE_CAUSAL_EVIDENCE_INVALID",
            issue_codes(validate_job_manifest(claimed_causal_inputs_only)),
        )

        equal_evidence_hashes = deepcopy(blocked)
        equal_evidence_hashes["jobs"][1]["strategyChange"]["causalEvidence"][0][
            "afterSha256"
        ] = HASH_A
        self.assertIn(
            "FAILURE_CAUSAL_EVIDENCE_INVALID",
            issue_codes(validate_job_manifest(equal_evidence_hashes)),
        )

        malformed_evidence = deepcopy(blocked)
        malformed_evidence["jobs"][1]["strategyChange"]["causalEvidence"] = [
            {"inputId": [], "beforeSha256": [], "afterSha256": {}}
        ]
        self.assertIn(
            "FAILURE_CAUSAL_EVIDENCE_INVALID",
            issue_codes(validate_job_manifest(malformed_evidence)),
        )

    def test_failure_record_malformed_strategy_shapes_return_issues(self) -> None:
        blocked = job_manifest()
        blocked["jobs"][1].update(
            {
                "status": "blocked",
                "failureClass": "identity",
                "rootCondition": "approved silhouette does not converge",
                "changedVariable": "approved full-body reference",
                "preserve": ["approved face"],
                "nextStrategy": "replace-reference-evidence",
                "retryCount": 1,
                "failureHistory": [
                    {
                        "failureClass": "identity",
                        "rootCondition": "approved silhouette does not converge",
                    }
                ],
                "strategyChange": {
                    "classification": "causal-reference-evidence",
                    "causalInputs": ["approved full-body reference"],
                    "causalEvidence": [
                        {
                            "inputId": "approved-full-body-reference",
                            "beforeSha256": HASH_A,
                            "afterSha256": HASH_B,
                        }
                    ],
                },
            }
        )
        for next_strategy, strategy_change in (
            ([], []),
            ("replace-reference-evidence", {"classification": []}),
            ("replace-reference-evidence", None),
        ):
            with self.subTest(
                next_strategy=next_strategy,
                strategy_change=strategy_change,
            ):
                malformed = deepcopy(blocked)
                malformed["jobs"][1]["nextStrategy"] = next_strategy
                malformed["jobs"][1]["strategyChange"] = strategy_change

                issues = validate_job_manifest(malformed)
                self.assertIsInstance(issues, list)
                self.assertIn("FAILURE_STRATEGY_INVALID", issue_codes(issues))

    def test_active_jobs_can_enter_each_terminal_state_with_audited_evidence(
        self,
    ) -> None:
        manifest = job_manifest()
        manifest["jobs"][0].update(
            {
                "importedIdentityRoot": True,
                "technicalVerdictId": None,
            }
        )
        original = json.dumps(manifest, sort_keys=True)
        failure_record = {
            "failureClass": "composition",
            "rootCondition": "hand silhouette obscures the approved face",
            "changedVariable": "semantic key-pose layout",
            "preserve": ["approved face", "approved costume palette"],
            "nextStrategy": "revise-semantic-key-poses",
            "retryCount": 1,
            "failureHistory": [
                {
                    "failureClass": "composition",
                    "rootCondition": "hand silhouette obscures the approved face",
                }
            ],
            "strategyChange": {
                "classification": "causal-key-poses",
                "causalInputs": ["semantic key-pose layout"],
                "causalEvidence": [
                    {
                        "inputId": "semantic-key-pose-layout",
                        "beforeSha256": HASH_A,
                        "afterSha256": HASH_B,
                    }
                ],
            },
        }

        superseded = transition_job(manifest, "identity", "superseded")
        blocked = transition_job(
            manifest,
            "walk-key-poses",
            "blocked",
            failure_record=failure_record,
        )
        rejected = transition_job(
            manifest,
            "walk-atlas",
            "rejected",
            failure_record=failure_record,
        )

        self.assertEqual(superseded["jobs"][0]["status"], "superseded")
        self.assertIsNone(superseded["jobs"][0]["technicalVerdictId"])
        self.assertIsNone(superseded["jobs"][0]["visualVerdictId"])
        self.assertFalse(superseded["jobs"][0]["importedIdentityRoot"])
        self.assertEqual(blocked["jobs"][1]["status"], "blocked")
        self.assertEqual(rejected["jobs"][2]["status"], "rejected")
        self.assertEqual(json.dumps(manifest, sort_keys=True), original)

        with self.assertRaises(ValueError):
            transition_job(manifest, "walk-key-poses", "blocked")
        with self.assertRaises(ValueError):
            transition_job(
                manifest,
                "walk-key-poses",
                "blocked",
                failure_record={"failureClass": "composition"},
            )

    def test_later_job_states_require_selected_dependencies(self) -> None:
        manifest = job_manifest()
        manifest["jobs"][0]["status"] = "candidate"
        manifest["jobs"][1]["status"] = "candidate"
        manifest["jobs"][1]["artifactSha256"] = HASH_B

        self.assertIn(
            "JOB_DEPENDENCY_PREREQUISITES_UNMET",
            issue_codes(validate_job_manifest(manifest)),
        )

    def test_manifest_schema_and_canonical_identity_must_match_active_dependencies(
        self,
    ) -> None:
        wrong_schema = job_manifest()
        wrong_schema["schemaVersion"] = "1"
        self.assertIn(
            "JOB_SCHEMA_VERSION_INVALID",
            issue_codes(validate_job_manifest(wrong_schema)),
        )

        mismatched_canonical = job_manifest()
        mismatched_canonical["jobs"][1].update(
            {
                "status": "selected",
                "artifactSha256": HASH_B,
                "canonicalIdentitySha256": HASH_C,
                "technicalVerdictId": "walk-tech",
                "visualVerdictId": "walk-visual",
            }
        )
        self.assertIn(
            "JOB_CANONICAL_IDENTITY_MISMATCH",
            issue_codes(validate_job_manifest(mismatched_canonical)),
        )

        preserved_superseded_provenance = deepcopy(mismatched_canonical)
        preserved_superseded_provenance["jobs"][1].update(
            {
                "status": "superseded",
                "technicalVerdictId": None,
                "visualVerdictId": None,
            }
        )
        self.assertNotIn(
            "JOB_CANONICAL_IDENTITY_MISMATCH",
            issue_codes(validate_job_manifest(preserved_superseded_provenance)),
        )

    def test_identity_root_artifact_must_equal_canonical_identity(self) -> None:
        manifest = job_manifest()
        manifest["jobs"][0]["canonicalIdentitySha256"] = HASH_B
        manifest["jobs"][1].update(
            {
                "status": "selected",
                "artifactSha256": HASH_C,
                "canonicalIdentitySha256": HASH_B,
                "technicalVerdictId": "walk-tech",
                "visualVerdictId": "walk-visual",
            }
        )
        manifest["jobs"][2]["canonicalIdentitySha256"] = HASH_B

        self.assertIn(
            "IDENTITY_ROOT_ARTIFACT_CANONICAL_MISMATCH",
            issue_codes(validate_job_manifest(manifest)),
        )

        candidate_root = deepcopy(manifest)
        candidate_root["jobs"][0].update(
            {
                "status": "candidate",
                "technicalVerdictId": None,
                "visualVerdictId": None,
            }
        )
        candidate_root["jobs"][1]["status"] = "pending"
        self.assertIn(
            "IDENTITY_ROOT_ARTIFACT_CANONICAL_MISMATCH",
            issue_codes(validate_job_manifest(candidate_root)),
        )

    def test_job_cli_rejects_unselected_identity_and_writes_deterministic_output(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            identity_path = root / "identity.json"
            actions_path = root / "actions"
            actions_path.mkdir()
            output_path = root / "jobs.json"
            action_paths = [
                actions_path / "zeta.json",
                actions_path / "alpha.json",
            ]
            for path, action_id in zip(action_paths, ("zeta", "alpha"), strict=True):
                path.write_text(
                    json.dumps(action_contract(action_id), indent=2) + "\n",
                    encoding="utf-8",
                )
            unselected_identity = {
                "selection": "candidate",
                "canonicalSha256": None,
                "technicalStatus": "not-run",
                "visualVerdictIds": [],
            }
            identity_path.write_text(
                json.dumps(unselected_identity, indent=2) + "\n", encoding="utf-8"
            )
            input_hashes = {
                path: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in [identity_path, *action_paths]
            }
            command = [
                sys.executable,
                "-B",
                str(SKILL_ROOT / "scripts" / "prepare_generation_jobs.py"),
                "--identity",
                str(identity_path),
                "--actions",
                str(actions_path),
                "--output",
                str(output_path),
            ]

            rejected = subprocess.run(command, capture_output=True, text=True)

            self.assertNotEqual(rejected.returncode, 0)
            self.assertFalse(output_path.exists())
            self.assertEqual(
                {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in input_hashes},
                input_hashes,
            )

            selected_identity = {
                "identityGateStatus": "identity-selected",
                "selection": "selected",
                "canonicalSha256": HASH_A,
                "technicalStatus": "pass",
                "visualVerdictIds": ["identity-visual-z", "identity-visual-a"],
            }
            identity_path.write_text(
                json.dumps(selected_identity, indent=2) + "\n", encoding="utf-8"
            )
            selected = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(selected.returncode, 0, selected.stderr)
            first_output = output_path.read_bytes()
            generated = json.loads(first_output)
            generated_ids = [job["id"] for job in generated["jobs"]]
            self.assertEqual(
                generated_ids,
                [
                    "identity",
                    "alpha-key-poses",
                    "alpha-atlas",
                    "zeta-key-poses",
                    "zeta-atlas",
                ],
            )
            self.assertIsNone(generated["jobs"][0]["technicalVerdictId"])
            self.assertEqual(generated["jobs"][0]["visualVerdictId"], "identity-visual-a")
            self.assertEqual(validate_job_manifest(generated), [])
            self.assertEqual(
                {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in input_hashes if path != identity_path},
                {path: input_hashes[path] for path in input_hashes if path != identity_path},
            )

            repeated = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            self.assertEqual(output_path.read_bytes(), first_output)
            self.assertEqual(
                {path.name for path in root.iterdir()},
                {"actions", "identity.json", "jobs.json"},
            )

    def test_job_cli_rejects_output_aliases_and_action_directory_writes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            identity_path = root / "identity.json"
            actions_path = root / "actions"
            actions_path.mkdir()
            action_path = actions_path / "walk.json"
            identity_path.write_text(
                json.dumps(
                    {
                        "identityGateStatus": "identity-selected",
                        "selection": "selected",
                        "canonicalSha256": HASH_A,
                        "technicalStatus": "pass",
                        "visualVerdictIds": ["identity-visual"],
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            action_path.write_text(
                json.dumps(action_contract(), indent=2) + "\n", encoding="utf-8"
            )
            identity_bytes = identity_path.read_bytes()
            action_bytes = action_path.read_bytes()

            cases = {
                "identity-alias": Path(str(root) + "\\actions\\..\\identity.json"),
                "action-input": action_path,
                "inside-actions": actions_path / "generated-jobs.json",
            }
            for label, output_path in cases.items():
                with self.subTest(label=label):
                    identity_path.write_bytes(identity_bytes)
                    action_path.write_bytes(action_bytes)
                    if output_path.exists() and output_path.resolve(
                        strict=False
                    ) not in {identity_path.resolve(), action_path.resolve()}:
                        output_path.unlink()
                    command = [
                        sys.executable,
                        "-B",
                        str(SKILL_ROOT / "scripts" / "prepare_generation_jobs.py"),
                        "--identity",
                        str(identity_path),
                        "--actions",
                        str(actions_path),
                        "--output",
                        str(output_path),
                    ]

                    rejected = subprocess.run(command, capture_output=True, text=True)

                    self.assertNotEqual(rejected.returncode, 0, rejected.stderr)
                    self.assertEqual(identity_path.read_bytes(), identity_bytes)
                    self.assertEqual(action_path.read_bytes(), action_bytes)
                    if output_path.resolve(strict=False) not in {
                        identity_path.resolve(),
                        action_path.resolve(),
                    }:
                        self.assertFalse(output_path.exists())

            inside_actions_output = actions_path / "generated-jobs.json"
            second_rejected = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SKILL_ROOT / "scripts" / "prepare_generation_jobs.py"),
                    "--identity",
                    str(identity_path),
                    "--actions",
                    str(actions_path),
                    "--output",
                    str(inside_actions_output),
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(second_rejected.returncode, 0, second_rejected.stderr)
            self.assertFalse(inside_actions_output.exists())
            self.assertEqual(identity_path.read_bytes(), identity_bytes)
            self.assertEqual(action_path.read_bytes(), action_bytes)

    def test_job_cli_rejects_nonstandard_json_constants_without_writing_inputs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            identity_path = root / "identity.json"
            actions_path = root / "actions"
            actions_path.mkdir()
            action_path = actions_path / "walk.json"
            identity_path.write_text(
                json.dumps(
                    {
                        "identityGateStatus": "identity-selected",
                        "selection": "selected",
                        "canonicalSha256": HASH_A,
                        "technicalStatus": "pass",
                        "visualVerdictIds": ["identity-visual"],
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            command_prefix = [
                sys.executable,
                "-B",
                str(SKILL_ROOT / "scripts" / "prepare_generation_jobs.py"),
                "--identity",
                str(identity_path),
                "--actions",
                str(actions_path),
            ]

            for label, value in (
                ("nan", float("nan")),
                ("positive-infinity", float("inf")),
                ("negative-infinity", float("-inf")),
            ):
                with self.subTest(label=label):
                    invalid_action = action_contract()
                    invalid_action["behavior"]["weight"] = value
                    action_path.write_text(
                        json.dumps(invalid_action, indent=2) + "\n",
                        encoding="utf-8",
                    )
                    output_path = root / f"jobs-{label}.json"
                    inputs_before = {
                        path: path.read_bytes() for path in (identity_path, action_path)
                    }

                    rejected = subprocess.run(
                        [*command_prefix, "--output", str(output_path)],
                        capture_output=True,
                        text=True,
                    )

                    self.assertNotEqual(rejected.returncode, 0, rejected.stderr)
                    self.assertNotIn("Traceback", rejected.stderr)
                    self.assertFalse(output_path.exists())
                    self.assertEqual(
                        {path: path.read_bytes() for path in inputs_before},
                        inputs_before,
                    )

    def test_job_cli_accepts_large_standard_integer_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            identity_path = root / "identity.json"
            actions_path = root / "actions"
            actions_path.mkdir()
            action_path = actions_path / "walk.json"
            output_path = root / "jobs.json"
            identity_path.write_text(
                json.dumps(
                    {
                        "identityGateStatus": "identity-selected",
                        "selection": "selected",
                        "canonicalSha256": HASH_A,
                        "technicalStatus": "pass",
                        "visualVerdictIds": ["identity-visual"],
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            action = action_contract()
            action["behavior"]["weight"] = int("9" * 1000)
            action_path.write_text(
                json.dumps(action, indent=2) + "\n", encoding="utf-8"
            )

            generated = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SKILL_ROOT / "scripts" / "prepare_generation_jobs.py"),
                    "--identity",
                    str(identity_path),
                    "--actions",
                    str(actions_path),
                    "--output",
                    str(output_path),
                ],
                capture_output=True,
                text=True,
            )

            self.assertEqual(generated.returncode, 0, generated.stderr)
            self.assertNotIn("Traceback", generated.stderr)
            self.assertTrue(output_path.exists())

    def test_job_cli_rejects_lone_surrogate_strings_and_keys_without_writes(
        self,
    ) -> None:
        for label in ("action-id", "identity-project", "action-key"):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                identity_path = root / "identity.json"
                actions_path = root / "actions"
                actions_path.mkdir()
                action_path = actions_path / "walk.json"
                output_path = root / "jobs.json"
                identity = {
                    "identityGateStatus": "identity-selected",
                    "selection": "selected",
                    "canonicalSha256": HASH_A,
                    "technicalStatus": "pass",
                    "visualVerdictIds": ["identity-visual"],
                    "projectId": "draft-pet",
                }
                action = action_contract()
                if label == "action-id":
                    action["actionId"] = "\ud800"
                elif label == "identity-project":
                    identity["projectId"] = "\ud800"
                else:
                    action["\ud800"] = "invalid key"
                identity_path.write_text(
                    json.dumps(identity, indent=2) + "\n", encoding="utf-8"
                )
                action_path.write_text(
                    json.dumps(action, indent=2) + "\n", encoding="utf-8"
                )
                input_bytes = {
                    path: path.read_bytes() for path in (identity_path, action_path)
                }

                rejected = subprocess.run(
                    [
                        sys.executable,
                        "-B",
                        str(SKILL_ROOT / "scripts" / "prepare_generation_jobs.py"),
                        "--identity",
                        str(identity_path),
                        "--actions",
                        str(actions_path),
                        "--output",
                        str(output_path),
                    ],
                    capture_output=True,
                    text=True,
                )

                self.assertNotEqual(rejected.returncode, 0, rejected.stderr)
                self.assertNotIn("Traceback", rejected.stderr)
                self.assertFalse(output_path.exists())
                self.assertEqual(
                    {path: path.read_bytes() for path in input_bytes}, input_bytes
                )

    def test_job_cli_rejects_structural_and_parser_depth_without_writes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            identity_path = root / "identity.json"
            actions_path = root / "actions"
            actions_path.mkdir()
            action_path = actions_path / "walk.json"
            action_path.write_text(
                json.dumps(action_contract(), indent=2) + "\n", encoding="utf-8"
            )
            command_prefix = [
                sys.executable,
                "-B",
                str(SKILL_ROOT / "scripts" / "prepare_generation_jobs.py"),
                "--identity",
                str(identity_path),
                "--actions",
                str(actions_path),
            ]
            selected_prefix = (
                '{"identityGateStatus":"identity-selected","selection":"selected",'
                f'"canonicalSha256":"{HASH_A}","technicalStatus":"pass",'
                '"visualVerdictIds":["identity-visual"],"extension":'
            )
            cases = {
                "structural-depth": selected_prefix
                + "[" * 500
                + "0"
                + "]" * 500
                + "}",
                "parser-depth": '{"extension":' + "[" * 1500 + "0" + "]" * 1500 + "}",
            }
            for label, identity_json in cases.items():
                with self.subTest(label=label):
                    output_path = root / f"jobs-{label}.json"
                    identity_path.write_text(identity_json + "\n", encoding="utf-8")
                    input_bytes = {
                        path: path.read_bytes() for path in (identity_path, action_path)
                    }

                    rejected = subprocess.run(
                        [*command_prefix, "--output", str(output_path)],
                        capture_output=True,
                        text=True,
                    )

                    self.assertNotEqual(rejected.returncode, 0, rejected.stderr)
                    self.assertNotIn("Traceback", rejected.stderr)
                    self.assertFalse(output_path.exists())
                    self.assertEqual(
                        {path: path.read_bytes() for path in input_bytes}, input_bytes
                    )

    def test_atomic_job_writer_converts_unicode_failure_to_input_error(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output_path = Path(raw) / "jobs.json"
            original = b"existing output\n"
            output_path.write_bytes(original)

            with self.assertRaises(InputError):
                _write_json_atomically(output_path, {"text": "\ud800"})

            self.assertEqual(output_path.read_bytes(), original)
            self.assertEqual(
                {path.name for path in output_path.parent.iterdir()}, {"jobs.json"}
            )

    def test_job_manifest_template_declares_audited_failure_defaults(self) -> None:
        template = json.loads(
            (SKILL_ROOT / "templates" / "job-manifest.json").read_text(encoding="utf-8")
        )

        self.assertEqual(template["jobDefaults"]["failureHistory"], [])
        self.assertIsNone(template["jobDefaults"]["nextStrategy"])
        self.assertEqual(
            template["jobDefaults"]["strategyChange"],
            {
                "classification": None,
                "causalInputs": [],
                "causalEvidence": [],
            },
        )


if __name__ == "__main__":
    unittest.main()
