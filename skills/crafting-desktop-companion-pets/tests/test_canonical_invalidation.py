from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from contracts import invalidate_descendants, validate_job_manifest


HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64
HASH_E = "e" * 64


def canonical_identity_manifest() -> dict[str, object]:
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
        ],
    }


def reverse_chain_manifest(job_count: int, *, add_back_edge: bool = False) -> dict[str, object]:
    root = canonical_identity_manifest()["jobs"][0]
    jobs: list[dict[str, object]] = []
    for index in range(job_count - 1, 0, -1):
        dependency_id = "identity" if index == 1 else f"chain-{index - 1:04d}"
        if add_back_edge and index == 1:
            dependency_id = f"chain-{job_count - 1:04d}"
        jobs.append(
            {
                "id": f"chain-{index:04d}",
                "kind": "atlas",
                "status": "pending",
                "dependsOn": [dependency_id],
                "inputHashes": {},
                "artifactSha256": None,
                "canonicalIdentitySha256": HASH_A,
                "technicalVerdictId": None,
                "visualVerdictId": None,
                "retryCount": 0,
            }
        )
    jobs.append(root)
    return {"schemaVersion": 1, "jobs": jobs}


class CanonicalInvalidationTest(unittest.TestCase):
    def test_iterative_graph_validation_and_invalidation_handle_a_large_dag(
        self,
    ) -> None:
        manifest = reverse_chain_manifest(1000)
        original = json.dumps(manifest, sort_keys=True)

        self.assertEqual(validate_job_manifest(manifest), [])
        updated, invalidated_ids = invalidate_descendants(manifest, "identity", HASH_B)

        self.assertEqual(len(invalidated_ids), 999)
        self.assertEqual(updated["jobs"][-1]["status"], "candidate")
        self.assertEqual(validate_job_manifest(updated), [])
        self.assertEqual(json.dumps(manifest, sort_keys=True), original)

    def test_iterative_graph_validation_reports_a_large_back_edge_cycle(self) -> None:
        manifest = reverse_chain_manifest(1000, add_back_edge=True)

        self.assertIn(
            "JOB_DEPENDENCY_CYCLE",
            {issue.code for issue in validate_job_manifest(manifest)},
        )

    def test_replacement_rejects_invalid_source_graphs_without_mutating_input(
        self,
    ) -> None:
        technical_pass = canonical_identity_manifest()
        technical_pass["jobs"][0].update(
            {
                "status": "technical-pass",
                "technicalVerdictId": None,
                "visualVerdictId": None,
            }
        )
        visual_pass = canonical_identity_manifest()
        visual_pass["jobs"][0].update(
            {
                "status": "visual-pass",
                "visualVerdictId": None,
            }
        )
        selected = canonical_identity_manifest()
        selected["jobs"][0]["technicalVerdictId"] = None
        imported_candidate = canonical_identity_manifest()
        imported_candidate["jobs"][0].update(
            {
                "status": "candidate",
                "technicalVerdictId": None,
                "visualVerdictId": None,
                "importedIdentityRoot": True,
            }
        )
        malformed_status = canonical_identity_manifest()
        malformed_status["jobs"][0]["status"] = []
        cycle = canonical_identity_manifest()
        cycle["jobs"][1].update({"dependsOn": ["loop"], "inputHashes": {}})
        cycle["jobs"].append(
            {
                "id": "loop",
                "kind": "atlas",
                "status": "pending",
                "dependsOn": ["walk-key-poses"],
                "inputHashes": {},
                "artifactSha256": None,
                "canonicalIdentitySha256": HASH_A,
                "technicalVerdictId": None,
                "visualVerdictId": None,
                "retryCount": 0,
            }
        )
        unknown_dependency = canonical_identity_manifest()
        unknown_dependency["jobs"][1].update(
            {"dependsOn": ["missing"], "inputHashes": {}}
        )
        duplicate_id = canonical_identity_manifest()
        duplicate_id["jobs"][1]["id"] = "identity"
        cases = (
            ("technical-pass", technical_pass, "JOB_TECHNICAL_VERDICT_REQUIRED"),
            ("visual-pass", visual_pass, "JOB_VISUAL_VERDICT_REQUIRED"),
            ("selected", selected, "JOB_TECHNICAL_VERDICT_REQUIRED"),
            ("imported-candidate", imported_candidate, "IMPORTED_IDENTITY_ROOT_INVALID"),
            ("malformed-status", malformed_status, "JOB_STATUS_INVALID"),
            ("cycle", cycle, "JOB_DEPENDENCY_CYCLE"),
            ("unknown-dependency", unknown_dependency, "JOB_DEPENDENCY_NOT_FOUND"),
            ("duplicate-id", duplicate_id, "JOB_ID_DUPLICATE"),
        )
        for label, manifest, expected_code in cases:
            with self.subTest(label=label):
                original = json.dumps(manifest, sort_keys=True)

                self.assertIn(expected_code, {issue.code for issue in validate_job_manifest(manifest)})
                with self.assertRaisesRegex(ValueError, expected_code):
                    invalidate_descendants(manifest, "identity", HASH_B)

                self.assertEqual(json.dumps(manifest, sort_keys=True), original)

    def test_replacing_terminal_or_nonaccepted_identity_roots_is_rejected_without_mutating_input(
        self,
    ) -> None:
        failure_record = {
            "failureClass": "identity",
            "rootCondition": "reference does not preserve the approved silhouette",
            "changedVariable": "approved full-body reference",
            "preserve": ["approved face"],
            "nextStrategy": "replace-reference-evidence",
            "retryCount": 1,
            "failureHistory": [
                {
                    "failureClass": "identity",
                    "rootCondition": "reference does not preserve the approved silhouette",
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
        for status in (
            "blocked",
            "rejected",
            "superseded",
            "pending",
            "ready",
            "generating",
        ):
            with self.subTest(status=status):
                root = {
                    "id": "identity",
                    "kind": "identity",
                    "status": status,
                    "dependsOn": [],
                    "inputHashes": {},
                    "artifactSha256": HASH_A,
                    "canonicalIdentitySha256": HASH_A,
                    "technicalVerdictId": "identity-tech",
                    "visualVerdictId": "identity-visual",
                    "retryCount": 0,
                }
                if status in {"blocked", "rejected"}:
                    root.update(deepcopy(failure_record))
                elif status == "superseded":
                    root["technicalVerdictId"] = None
                    root["visualVerdictId"] = None
                else:
                    root["artifactSha256"] = None
                    root["technicalVerdictId"] = None
                    root["visualVerdictId"] = None
                manifest = {"schemaVersion": 1, "jobs": [root]}
                original = json.dumps(manifest, sort_keys=True)

                self.assertEqual(validate_job_manifest(manifest), [])
                with self.assertRaisesRegex(ValueError, "candidate-or-later"):
                    invalidate_descendants(manifest, "identity", HASH_C)

                self.assertEqual(json.dumps(manifest, sort_keys=True), original)
                self.assertEqual(validate_job_manifest(manifest), [])

    def test_replacing_a_non_root_upstream_is_rejected_without_mutating_input(
        self,
    ) -> None:
        manifest = {
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
                    "status": "selected",
                    "dependsOn": ["identity"],
                    "inputHashes": {"identity": HASH_A},
                    "artifactSha256": HASH_C,
                    "canonicalIdentitySha256": HASH_A,
                    "technicalVerdictId": "walk-tech",
                    "visualVerdictId": "walk-visual",
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
        original = json.dumps(manifest, sort_keys=True)

        self.assertEqual(validate_job_manifest(manifest), [])
        with self.assertRaisesRegex(ValueError, "identity root"):
            invalidate_descendants(manifest, "walk-key-poses", HASH_D)

        self.assertEqual(json.dumps(manifest, sort_keys=True), original)
        self.assertEqual(validate_job_manifest(manifest), [])

    def test_replacing_canonical_identity_supersedes_only_descendants_without_mutating_input(
        self,
    ) -> None:
        manifest = {
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
                    "importedIdentityRoot": True,
                    "technicalVerdictId": None,
                    "visualVerdictId": "identity-visual",
                    "retryCount": 0,
                },
                {
                    "id": "walk-key-poses",
                    "kind": "semantic-key-poses",
                    "status": "selected",
                    "dependsOn": ["identity"],
                    "inputHashes": {"identity": HASH_A},
                    "artifactSha256": HASH_C,
                    "canonicalIdentitySha256": HASH_A,
                    "technicalVerdictId": "walk-tech",
                    "visualVerdictId": "walk-visual",
                    "retryCount": 0,
                },
                {
                    "id": "walk-atlas",
                    "kind": "atlas",
                    "status": "visual-pass",
                    "dependsOn": ["walk-key-poses"],
                    "inputHashes": {"walk-key-poses": HASH_C},
                    "artifactSha256": HASH_D,
                    "canonicalIdentitySha256": HASH_A,
                    "technicalVerdictId": "atlas-tech",
                    "visualVerdictId": "atlas-visual",
                    "retryCount": 0,
                },
                {
                    "id": "unrelated",
                    "kind": "identity",
                    "status": "selected",
                    "dependsOn": [],
                    "inputHashes": {},
                    "artifactSha256": HASH_E,
                    "canonicalIdentitySha256": HASH_E,
                    "technicalVerdictId": "other-tech",
                    "visualVerdictId": "other-visual",
                    "retryCount": 0,
                },
            ],
        }
        original = json.dumps(manifest, sort_keys=True)
        unrelated = manifest["jobs"][3]

        self.assertEqual(validate_job_manifest(manifest), [])

        updated, invalidated_ids = invalidate_descendants(manifest, "identity", HASH_B)

        self.assertEqual(invalidated_ids, ["walk-atlas", "walk-key-poses"])
        self.assertEqual(updated["jobs"][0]["status"], "candidate")
        self.assertEqual(updated["jobs"][0]["artifactSha256"], HASH_B)
        self.assertEqual(updated["jobs"][0]["canonicalIdentitySha256"], HASH_B)
        self.assertFalse(updated["jobs"][0]["importedIdentityRoot"])
        self.assertIsNone(updated["jobs"][0]["technicalVerdictId"])
        self.assertIsNone(updated["jobs"][0]["visualVerdictId"])
        for index in (1, 2):
            self.assertEqual(updated["jobs"][index]["status"], "superseded")
            self.assertIsNone(updated["jobs"][index]["technicalVerdictId"])
            self.assertIsNone(updated["jobs"][index]["visualVerdictId"])
        self.assertEqual(updated["jobs"][3], unrelated)
        self.assertEqual(json.dumps(manifest, sort_keys=True), original)
        self.assertEqual(validate_job_manifest(updated), [])

        updated["jobs"][3]["inputHashes"]["new"] = HASH_A
        self.assertNotIn("new", manifest["jobs"][3]["inputHashes"])


if __name__ == "__main__":
    unittest.main()
