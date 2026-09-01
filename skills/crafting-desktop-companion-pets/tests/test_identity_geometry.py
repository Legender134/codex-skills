from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import warnings

from PIL import Image, ImageDraw


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

import make_identity_review_sheet as review_sheet
from make_identity_review_sheet import build_identity_review_sheet
from measure_identity_geometry import measure_alpha_geometry


class IdentityGeometryTest(unittest.TestCase):
    def _write_candidate(self, path: Path) -> None:
        image = Image.new("RGBA", (100, 200), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((40, 10, 59, 49), fill=(220, 80, 120, 255))
        draw.rectangle((30, 50, 69, 179), fill=(80, 120, 220, 255))
        image.save(path, format="PNG")

    def _write_review_inputs(
        self,
        root: Path,
        candidate_path: Path | None = None,
        identity_reference_path: Path | None = None,
        proportion_reference_path: Path | None = None,
    ) -> tuple[Path, Path, Path]:
        candidate = candidate_path or root / "candidate.png"
        identity_reference = identity_reference_path or root / "identity-reference.png"
        proportion_reference = proportion_reference_path or root / "proportion-reference.png"
        self._write_candidate(candidate)

        identity = Image.new("RGBA", (60, 80), (0, 0, 0, 0))
        ImageDraw.Draw(identity).ellipse((12, 8, 47, 67), fill=(240, 180, 80, 255))
        identity.save(identity_reference, format="PNG")
        proportion = Image.new("RGBA", (80, 120), (0, 0, 0, 0))
        ImageDraw.Draw(proportion).rectangle((20, 10, 59, 109), fill=(90, 190, 140, 255))
        proportion.save(proportion_reference, format="PNG")
        return candidate, identity_reference, proportion_reference

    def _assert_second_publication_failure_restores_pair(
        self, has_prior_pair: bool
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            candidate, identity_reference, proportion_reference = self._write_review_inputs(root)
            output = root / "identity-review.png"
            sidecar = output.with_suffix(output.suffix + ".json")
            prior_png = b"prior PNG bytes"
            prior_sidecar = b'{"prior": true}\n'
            if has_prior_pair:
                output.write_bytes(prior_png)
                sidecar.write_bytes(prior_sidecar)

            real_replace = review_sheet.os.replace
            publication_count = 0

            def fail_second_publication(source: object, destination: object) -> object:
                nonlocal publication_count
                destination_path = Path(destination).resolve()
                if destination_path in {output.resolve(), sidecar.resolve()}:
                    publication_count += 1
                    if publication_count == 2:
                        raise OSError("injected second publication failure")
                return real_replace(source, destination)

            with patch.object(
                review_sheet.os, "replace", side_effect=fail_second_publication
            ):
                with self.assertRaisesRegex(OSError, "injected second publication failure"):
                    build_identity_review_sheet(
                        candidate,
                        identity_reference,
                        proportion_reference,
                        output,
                        runtime_height=85,
                    )

            if has_prior_pair:
                self.assertEqual(output.read_bytes(), prior_png)
                self.assertEqual(sidecar.read_bytes(), prior_sidecar)
            else:
                self.assertFalse(output.exists())
                self.assertFalse(sidecar.exists())
            self.assertEqual(
                [path.name for path in root.iterdir() if path.name.startswith(".identity-review.")],
                [],
            )

    def test_measure_alpha_geometry_reports_hand_derived_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            candidate = Path(raw) / "candidate.png"
            self._write_candidate(candidate)

            with warnings.catch_warnings():
                warnings.simplefilter("error", DeprecationWarning)
                report = measure_alpha_geometry(candidate)

            self.assertEqual(report["canvas"], [100, 200])
            self.assertEqual(report["alphaBoundingBox"], [30, 10, 70, 180])
            self.assertEqual(report["alphaPixels"], 6000)
            self.assertEqual(report["centroid"], [49.5, 103.166667])
            self.assertEqual(report["widthProfile"], [20, 40, 40, 40, 40, 40, 40, 40])
            self.assertEqual(report["maximumWidthSegment"], 1)
            self.assertTrue(report["diagnosticOnly"])
            self.assertNotIn("visualStatus", report)
            self.assertNotIn("pass", report)

    def test_measure_alpha_geometry_rejects_empty_alpha(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            empty = Path(raw) / "empty.png"
            Image.new("RGBA", (100, 200), (0, 0, 0, 0)).save(empty)

            with self.assertRaisesRegex(ValueError, "^image has no visible pixels$"):
                measure_alpha_geometry(empty)

    def test_measure_alpha_geometry_caps_segments_to_visible_height(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            row = Path(raw) / "one-row.png"
            image = Image.new("RGBA", (5, 5), (0, 0, 0, 0))
            ImageDraw.Draw(image).rectangle((0, 2, 4, 2), fill=(40, 80, 120, 255))
            image.save(row)

            report = measure_alpha_geometry(row, segments=8)

            self.assertEqual(report["widthProfile"], [5])
            self.assertEqual(report["maximumWidthSegment"], 0)
            with self.assertRaisesRegex(ValueError, "^segments must be a positive integer$"):
                measure_alpha_geometry(row, segments=0)

    def test_review_sheet_leaves_no_pair_when_second_publication_fails(self) -> None:
        self._assert_second_publication_failure_restores_pair(has_prior_pair=False)

    def test_review_sheet_rejects_output_or_sidecar_collision_with_each_input(self) -> None:
        for collision_target in ("output", "sidecar"):
            for input_role in ("candidate", "identity", "proportion"):
                with self.subTest(target=collision_target, input=input_role):
                    with tempfile.TemporaryDirectory() as raw:
                        root = Path(raw)
                        output = root / "identity-review.png"
                        sidecar = output.with_suffix(output.suffix + ".json")
                        paths = {
                            "candidate": root / "candidate.png",
                            "identity": root / "identity-reference.png",
                            "proportion": root / "proportion-reference.png",
                        }
                        paths[input_role] = (
                            output if collision_target == "output" else sidecar
                        )
                        candidate, identity_reference, proportion_reference = self._write_review_inputs(
                            root,
                            candidate_path=paths["candidate"],
                            identity_reference_path=paths["identity"],
                            proportion_reference_path=paths["proportion"],
                        )
                        source_bytes = {
                            path: path.read_bytes()
                            for path in (candidate, identity_reference, proportion_reference)
                        }

                        with self.assertRaisesRegex(
                            ValueError, "output path or sidecar must not match an input image"
                        ):
                            build_identity_review_sheet(
                                candidate,
                                identity_reference,
                                proportion_reference,
                                output,
                                runtime_height=85,
                            )

                        for path, expected in source_bytes.items():
                            self.assertEqual(path.read_bytes(), expected)
                        if output not in source_bytes:
                            self.assertFalse(output.exists())
                        if sidecar not in source_bytes:
                            self.assertFalse(sidecar.exists())

    def test_review_sheet_restores_existing_pair_when_second_publication_fails(self) -> None:
        self._assert_second_publication_failure_restores_pair(has_prior_pair=True)

    def test_identity_review_sheet_records_all_nine_panels_at_actual_size(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            output = root / "identity-review.png"
            candidate, identity_reference, proportion_reference = self._write_review_inputs(root)

            with warnings.catch_warnings():
                warnings.simplefilter("error", DeprecationWarning)
                result = build_identity_review_sheet(
                    candidate,
                    identity_reference,
                    proportion_reference,
                    output,
                    runtime_height=85,
                )
            sidecar_path = output.with_suffix(output.suffix + ".json")
            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))

            self.assertTrue(output.is_file())
            self.assertEqual(sidecar, result)
            self.assertEqual(
                {panel["name"] for panel in sidecar["panels"]},
                {
                    "identity-reference",
                    "proportion-reference",
                    "candidate-original",
                    "candidate-actual-size",
                    "light",
                    "dark",
                    "checker",
                    "silhouette",
                    "geometry",
                },
            )
            candidate_actual_size = next(
                panel
                for panel in sidecar["panels"]
                if panel["name"] == "candidate-actual-size"
            )
            self.assertEqual(candidate_actual_size["renderedSize"], [42, 85])
            for panel in sidecar["panels"]:
                self.assertIsInstance(panel["source"], str)
                self.assertEqual(len(panel["sha256"]), 64)
                self.assertEqual(len(panel["renderedSize"]), 2)
                self.assertIsInstance(panel["background"], str)
                self.assertIsInstance(panel["role"], str)


if __name__ == "__main__":
    unittest.main()
