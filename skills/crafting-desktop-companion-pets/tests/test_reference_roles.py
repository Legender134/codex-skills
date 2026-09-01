from __future__ import annotations

from pathlib import Path
import sys
import unittest


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from contracts import validate_reference_roles


class ReferenceRoleTest(unittest.TestCase):
    def test_style_and_calibration_cannot_govern_proportion(self) -> None:
        style = {
            "id": "style-1",
            "roles": ["style", "proportion"],
            "allowedUses": ["rendering", "head-body-ratio"],
            "evidenceClass": "unrelated-artwork",
        }
        calibration = {
            "id": "nangong-calibration",
            "roles": ["desktop-calibration", "proportion"],
            "allowedUses": ["actual-size-readability", "total-width"],
            "evidenceClass": "other-character",
        }
        self.assertEqual(
            {issue.code for issue in validate_reference_roles(style, "source-faithful")},
            {"ROLE_PROPORTION_UNSUPPORTED"},
        )
        self.assertEqual(
            {
                issue.code
                for issue in validate_reference_roles(
                    calibration, "source-faithful"
                )
            },
            {"ROLE_PROPORTION_UNSUPPORTED"},
        )

    def test_original_route_accepts_an_approved_design_brief(self) -> None:
        brief = {
            "id": "cloud-cat-brief",
            "roles": ["identity", "proportion", "costume", "style"],
            "allowedUses": ["canonical-identity"],
            "evidenceClass": "approved-original-design",
        }
        self.assertEqual(
            validate_reference_roles(brief, "original-brand"),
            [],
        )

    def test_prohibited_reference_cannot_govern_identity_or_proportion(self) -> None:
        prohibited = {
            "id": "do-not-derive",
            "roles": ["identity", "proportion", "prohibited"],
            "allowedUses": [],
            "evidenceClass": "current-official",
        }

        self.assertEqual(
            {
                issue.code
                for issue in validate_reference_roles(prohibited, "source-faithful")
            },
            {"ROLE_IDENTITY_UNSUPPORTED", "ROLE_PROPORTION_UNSUPPORTED"},
        )


if __name__ == "__main__":
    unittest.main()
