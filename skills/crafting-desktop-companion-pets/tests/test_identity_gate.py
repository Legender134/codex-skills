from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from contracts import evaluate_identity_gate, sha256_file, validate_visual_verdict


class IdentityGateTest(unittest.TestCase):
    def test_source_faithful_contract_without_proportion_evidence_is_blocked(
        self,
    ) -> None:
        contract = {
            "identityRoute": "source-faithful",
            "referenceIds": ["identity-1"],
            "canonicalPath": None,
            "canonicalSha256": None,
            "technicalStatus": "not-run",
            "authority": {"identityUncertaintyApproved": False},
        }
        references = [
            {
                "id": "identity-1",
                "roles": ["identity"],
                "allowedUses": ["canonical-identity"],
                "evidenceClass": "current-official",
            }
        ]

        result = evaluate_identity_gate(contract, references, [])

        self.assertEqual(result["status"], "blocked")

    def test_actual_size_independent_visual_pass_selects_identity(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            canonical = Path(raw) / "canonical.png"
            canonical.write_bytes(b"canonical identity")
            canonical_sha256 = sha256_file(canonical)
            contract = {
                "identityRoute": "source-faithful",
                "referenceIds": ["identity-1", "proportion-1"],
                "canonicalPath": str(canonical),
                "canonicalSha256": canonical_sha256,
                "technicalStatus": "pass",
                "authority": {"identityUncertaintyApproved": False},
            }
            references = [
                {
                    "id": "identity-1",
                    "roles": ["identity"],
                    "allowedUses": ["canonical-identity"],
                    "evidenceClass": "current-official",
                },
                {
                    "id": "proportion-1",
                    "roles": ["proportion"],
                    "allowedUses": ["canonical-identity"],
                    "evidenceClass": "same-character-current",
                },
            ]
            technical_verdict = {
                "verdictId": "technical-1",
                "gate": "technical",
                "decision": "pass",
                "reviewScale": "actual-runtime-size",
                "artifactSha256": canonical_sha256,
                "reviewer": {"type": "independent", "id": "reviewer-1"},
            }

            technical_result = evaluate_identity_gate(
                contract, references, [technical_verdict]
            )

            self.assertEqual(technical_result["status"], "visual-candidate")
            self.assertEqual(technical_result["acceptedVerdictIds"], [])
            self.assertIn(
                "TECHNICAL_CANNOT_GRANT_VISUAL_PASS",
                {issue["code"] for issue in technical_result["blockingIssues"]},
            )

            visual_verdict = {
                "verdictId": "visual-1",
                "gate": "visual",
                "decision": "pass",
                "reviewScale": "actual-runtime-size",
                "artifactSha256": canonical_sha256,
                "reviewer": {"type": "independent", "id": "reviewer-1"},
                "observations": ["Actual-size identity review is recorded."],
            }
            independent_only = evaluate_identity_gate(
                contract, references, [technical_verdict, visual_verdict]
            )

            self.assertEqual(independent_only["status"], "visual-candidate")
            self.assertIn(
                "BUILDER_SELF_REVIEW_PASS_REQUIRED",
                {issue["code"] for issue in independent_only["blockingIssues"]},
            )

            builder_verdict = {
                "verdictId": "builder-visual-1",
                "gate": "visual",
                "decision": "pass",
                "reviewScale": "actual-runtime-size",
                "artifactSha256": canonical_sha256,
                "reviewer": {"type": "builder", "id": "builder-1"},
                "observations": ["Builder actual-size self-review is recorded."],
            }
            selected_result = evaluate_identity_gate(
                contract,
                references,
                [technical_verdict, builder_verdict, visual_verdict],
            )

            self.assertEqual(selected_result["status"], "identity-selected")
            self.assertEqual(selected_result["canonicalSha256"], canonical_sha256)
            self.assertEqual(
                selected_result["acceptedVerdictIds"],
                ["builder-visual-1", "visual-1"],
            )

    def test_user_visual_pass_cannot_replace_independent_internal_review(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            canonical = Path(raw) / "canonical.png"
            canonical.write_bytes(b"canonical identity")
            canonical_sha256 = sha256_file(canonical)
            contract = {
                "identityRoute": "source-faithful",
                "referenceIds": ["identity-1", "proportion-1"],
                "canonicalPath": str(canonical),
                "canonicalSha256": canonical_sha256,
                "technicalStatus": "pass",
                "authority": {"identityUncertaintyApproved": False},
            }
            references = [
                {
                    "id": "identity-1",
                    "roles": ["identity"],
                    "allowedUses": ["canonical-identity"],
                    "evidenceClass": "current-official",
                },
                {
                    "id": "proportion-1",
                    "roles": ["proportion"],
                    "allowedUses": ["canonical-identity"],
                    "evidenceClass": "same-character-current",
                },
            ]
            user_verdict = {
                "verdictId": "user-visual-1",
                "gate": "visual",
                "decision": "pass",
                "reviewScale": "actual-runtime-size",
                "artifactSha256": canonical_sha256,
                "reviewer": {"type": "user", "id": "user-1"},
                "observations": ["The user accepted the candidate."],
            }

            result = evaluate_identity_gate(contract, references, [user_verdict])

            self.assertEqual(result["status"], "visual-candidate")
            self.assertEqual(result["acceptedVerdictIds"], [])
            self.assertIn(
                "INDEPENDENT_VISUAL_PASS_REQUIRED_BEFORE_USER_HANDOFF",
                {issue["code"] for issue in result["blockingIssues"]},
            )

            builder_verdict = {
                "verdictId": "builder-visual-1",
                "gate": "visual",
                "decision": "pass",
                "reviewScale": "actual-runtime-size",
                "artifactSha256": canonical_sha256,
                "reviewer": {"type": "builder", "id": "builder-1"},
                "observations": ["Builder actual-size self-review is recorded."],
            }
            independent_verdict = {
                "verdictId": "independent-visual-1",
                "gate": "visual",
                "decision": "pass",
                "reviewScale": "actual-runtime-size",
                "artifactSha256": canonical_sha256,
                "reviewer": {"type": "independent", "id": "reviewer-1"},
                "observations": ["Independent actual-size review is recorded."],
            }
            early_user_result = evaluate_identity_gate(
                contract,
                references,
                [builder_verdict, user_verdict, independent_verdict],
            )

            self.assertEqual(early_user_result["status"], "visual-candidate")
            self.assertIn(
                "USER_HANDOFF_PRECEDED_INTERNAL_VISUAL_PASS",
                {issue["code"] for issue in early_user_result["blockingIssues"]},
            )

            correctly_ordered = evaluate_identity_gate(
                contract,
                references,
                [builder_verdict, independent_verdict, user_verdict],
            )
            self.assertEqual(correctly_ordered["status"], "identity-selected")
            self.assertEqual(
                correctly_ordered["acceptedVerdictIds"],
                ["builder-visual-1", "independent-visual-1"],
            )

    def test_prohibited_reference_cannot_select_source_faithful_identity(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            canonical = Path(raw) / "canonical.png"
            canonical.write_bytes(b"canonical identity")
            canonical_sha256 = sha256_file(canonical)
            contract = {
                "identityRoute": "source-faithful",
                "referenceIds": ["do-not-derive"],
                "canonicalPath": str(canonical),
                "canonicalSha256": canonical_sha256,
                "technicalStatus": "pass",
                "authority": {"identityUncertaintyApproved": False},
            }
            references = [
                {
                    "id": "do-not-derive",
                    "roles": ["identity", "proportion", "prohibited"],
                    "allowedUses": [],
                    "evidenceClass": "current-official",
                }
            ]
            verdict = {
                "verdictId": "visual-1",
                "gate": "visual",
                "decision": "pass",
                "reviewScale": "actual-runtime-size",
                "artifactSha256": canonical_sha256,
                "reviewer": {"type": "independent", "id": "reviewer-1"},
                "observations": ["Actual-size identity review is recorded."],
            }

            result = evaluate_identity_gate(contract, references, [verdict])

            self.assertEqual(result["status"], "blocked")

    def test_original_brand_style_only_design_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            canonical = Path(raw) / "canonical.png"
            canonical.write_bytes(b"canonical identity")
            canonical_sha256 = sha256_file(canonical)
            contract = {
                "identityRoute": "original-brand",
                "referenceIds": ["style-brief"],
                "canonicalPath": str(canonical),
                "canonicalSha256": canonical_sha256,
                "technicalStatus": "pass",
                "authority": {"identityUncertaintyApproved": False},
            }
            references = [
                {
                    "id": "style-brief",
                    "roles": ["style"],
                    "allowedUses": ["rendering"],
                    "evidenceClass": "approved-original-design",
                }
            ]
            verdict = {
                "verdictId": "visual-1",
                "gate": "visual",
                "decision": "pass",
                "reviewScale": "actual-runtime-size",
                "artifactSha256": canonical_sha256,
                "reviewer": {"type": "independent", "id": "reviewer-1"},
                "observations": ["Actual-size identity review is recorded."],
            }

            result = evaluate_identity_gate(contract, references, [verdict])

            self.assertEqual(result["status"], "blocked")

    def test_uncertainty_approval_requires_a_recorded_uncertainty(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            canonical = Path(raw) / "canonical.png"
            canonical.write_bytes(b"canonical identity")
            canonical_sha256 = sha256_file(canonical)
            contract = {
                "identityRoute": "source-faithful",
                "referenceIds": [],
                "canonicalPath": str(canonical),
                "canonicalSha256": canonical_sha256,
                "technicalStatus": "pass",
                "uncertainties": [],
                "authority": {"identityUncertaintyApproved": True},
            }
            verdict = {
                "verdictId": "visual-1",
                "gate": "visual",
                "decision": "pass",
                "reviewScale": "actual-runtime-size",
                "artifactSha256": canonical_sha256,
                "reviewer": {"type": "independent", "id": "reviewer-1"},
                "observations": ["Actual-size identity review is recorded."],
            }
            builder_verdict = {
                **verdict,
                "verdictId": "builder-visual-1",
                "reviewer": {"type": "builder", "id": "builder-1"},
                "observations": ["Builder actual-size self-review is recorded."],
            }

            without_record = evaluate_identity_gate(
                contract, [], [builder_verdict, verdict]
            )

            self.assertEqual(without_record["status"], "blocked")

            contract["uncertainties"] = [{"subject": "proportion evidence"}]
            with_record = evaluate_identity_gate(contract, [], [builder_verdict, verdict])

            self.assertEqual(with_record["status"], "identity-selected")

    def test_null_verdict_id_is_allowed_only_for_draft(self) -> None:
        draft_verdict = {
            "verdictId": None,
            "gate": "visual",
            "decision": "not-reviewed",
            "reviewScale": "not-reviewed",
            "artifactSha256": None,
            "reviewer": {"type": "unassigned", "id": None},
        }
        self.assertEqual(validate_visual_verdict(draft_verdict), [])

        with tempfile.TemporaryDirectory() as raw:
            canonical = Path(raw) / "canonical.png"
            canonical.write_bytes(b"canonical identity")
            canonical_sha256 = sha256_file(canonical)
            contract = {
                "identityRoute": "source-faithful",
                "referenceIds": ["identity-1", "proportion-1"],
                "canonicalPath": str(canonical),
                "canonicalSha256": canonical_sha256,
                "technicalStatus": "pass",
                "authority": {"identityUncertaintyApproved": False},
            }
            references = [
                {
                    "id": "identity-1",
                    "roles": ["identity"],
                    "allowedUses": ["canonical-identity"],
                    "evidenceClass": "current-official",
                },
                {
                    "id": "proportion-1",
                    "roles": ["proportion"],
                    "allowedUses": ["canonical-identity"],
                    "evidenceClass": "same-character-current",
                },
            ]
            pass_verdict = {
                "verdictId": None,
                "gate": "visual",
                "decision": "pass",
                "reviewScale": "actual-runtime-size",
                "artifactSha256": canonical_sha256,
                "reviewer": {"type": "independent", "id": "reviewer-1"},
                "observations": ["Actual-size identity review is recorded."],
            }

            result = evaluate_identity_gate(contract, references, [pass_verdict])

            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["acceptedVerdictIds"], [])

    def test_non_object_contract_is_blocked(self) -> None:
        result = evaluate_identity_gate([], [], [])

        self.assertEqual(result["status"], "blocked")
        self.assertIn(
            "IDENTITY_CONTRACT_INVALID",
            {issue["code"] for issue in result["blockingIssues"]},
        )

    def test_cli_parse_errors_exit_one(self) -> None:
        command = [
            sys.executable,
            "-B",
            str(SKILL_ROOT / "scripts" / "validate_identity_gate.py"),
        ]
        missing_output = subprocess.run(
            command + ["--identity", "identity.json", "--references", "sources.json"],
            capture_output=True,
            text=True,
        )
        unknown_argument = subprocess.run(
            command
            + [
                "--identity",
                "identity.json",
                "--references",
                "sources.json",
                "--output",
                "identity-gate.json",
                "--unknown",
            ],
            capture_output=True,
            text=True,
        )

        self.assertEqual(missing_output.returncode, 1)
        self.assertEqual(unknown_argument.returncode, 1)


if __name__ == "__main__":
    unittest.main()
