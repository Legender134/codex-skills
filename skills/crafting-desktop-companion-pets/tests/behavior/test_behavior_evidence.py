from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

if __package__:
    from .campaign import load_campaign_summary, validate_campaign
else:
    from campaign import load_campaign_summary, validate_campaign


ROOT = Path(__file__).resolve().parent
SKILL_ROOT = ROOT.parents[1]
VARIANTS = (
    "identity-and-reference",
    "visual-versus-technical",
    "motion-and-repair",
    "format-runtime-authority",
)
SCENARIO_SEQUENCE = {
    "identity-and-reference": ("B01", "B03", "B04", "B05", "B06"),
    "visual-versus-technical": ("B02", "B08", "B02", "B08", "B02"),
    "motion-and-repair": ("B07", "B09", "B07", "B09", "B07"),
    "format-runtime-authority": ("B10", "B11", "B12", "B10", "B11"),
}
CURRENT_SKILL_HASH = hashlib.sha256(
    (SKILL_ROOT / "SKILL.md").read_bytes()
).hexdigest()


class BehaviorEvidenceTest(unittest.TestCase):
    def _record(self, variant: str, rep: int) -> dict[str, object]:
        scenario_id = SCENARIO_SEQUENCE[variant][rep - 1]
        return {
            "schemaVersion": 1,
            "scenarioId": scenario_id,
            "variant": variant,
            "rep": rep,
            "skillEntrypointSha256": CURRENT_SKILL_HASH,
            "responsePath": f"responses/{scenario_id}-rep{rep}.md",
            "reviewed": True,
            "pass": True,
            "observedChoices": ["manual choice"],
            "rationalizations": ["manual rationale"],
            "reviewerNotes": "manual notes",
        }

    def _write_campaign(
        self,
        campaign_root: Path,
        *,
        omitted: set[tuple[str, int]] | None = None,
        mutate: object | None = None,
        variants: tuple[str, ...] = VARIANTS,
        write_responses: bool = True,
    ) -> None:
        omitted = omitted or set()
        for variant in variants:
            variant_root = campaign_root / variant
            variant_root.mkdir(parents=True)
            for rep in range(1, 6):
                if (variant, rep) in omitted:
                    continue
                record = self._record(variant, rep)
                if mutate is not None:
                    mutate(variant, rep, record)
                (variant_root / f"{rep:02d}.json").write_text(
                    json.dumps(record), encoding="utf-8"
                )
                if write_responses:
                    response_path = variant_root / str(record["responsePath"])
                    response_path.parent.mkdir(parents=True, exist_ok=True)
                    response_path.write_text("manual rationale\n", encoding="utf-8")

    def test_campaign_has_exact_scenarios_and_four_variants(self) -> None:
        scenarios = json.loads((ROOT / "scenarios.json").read_text(encoding="utf-8"))
        self.assertEqual(
            [item["id"] for item in scenarios],
            [f"B{number:02d}" for number in range(1, 13)],
        )
        self.assertEqual(
            {item["variant"] for item in scenarios},
            {
                "identity-and-reference",
                "visual-versus-technical",
                "motion-and-repair",
                "format-runtime-authority",
            },
        )
        for item in scenarios:
            self.assertNotIn("expected", item)
            self.assertGreaterEqual(len(item["pressures"]), 3)

    def test_rubric_is_separate_from_neutral_prompts(self) -> None:
        scenarios = json.loads((ROOT / "scenarios.json").read_text(encoding="utf-8"))
        rubric = json.loads((ROOT / "rubric.json").read_text(encoding="utf-8"))
        self.assertEqual(
            {item["id"] for item in scenarios},
            set(rubric["criteriaByScenario"]),
        )
        self.assertEqual(rubric["repetitionsPerVariant"], 5)
        self.assertTrue(rubric["manualReadRequired"])

    def test_campaign_loader_returns_five_runs_for_each_variant(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            campaign_root = Path(temporary_directory)
            self._write_campaign(campaign_root)

            summary = validate_campaign(campaign_root, require_pass=True)

            self.assertEqual(
                {
                    variant: sum(
                        run["variant"] == variant for run in summary["runs"]
                    )
                    for variant in VARIANTS
                },
                {variant: 5 for variant in VARIANTS},
            )
            self.assertEqual(set(summary["variants"]), set(VARIANTS))
            self.assertEqual(load_campaign_summary(campaign_root), summary)

    def test_campaign_loader_requires_exact_variant_set(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            campaign_root = Path(temporary_directory)
            self._write_campaign(campaign_root, variants=VARIANTS[:-1])

            with self.assertRaises(ValueError):
                load_campaign_summary(campaign_root)

    def test_campaign_loader_requires_exact_scenario_distribution(self) -> None:
        def change_scenario(
            variant: str, rep: int, record: dict[str, object]
        ) -> None:
            if variant == VARIANTS[0] and rep == 1:
                record["scenarioId"] = "B02"

        with tempfile.TemporaryDirectory() as temporary_directory:
            campaign_root = Path(temporary_directory)
            self._write_campaign(campaign_root, mutate=change_scenario)

            with self.assertRaises(ValueError):
                load_campaign_summary(campaign_root)

    def test_campaign_loader_binds_records_to_raw_responses(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            campaign_root = Path(temporary_directory)
            self._write_campaign(campaign_root, write_responses=False)

            with self.assertRaises(ValueError):
                load_campaign_summary(campaign_root)

        def replace_rationale(
            variant: str, rep: int, record: dict[str, object]
        ) -> None:
            if variant == VARIANTS[0] and rep == 1:
                record["rationalizations"] = ["not present in raw response"]

        with tempfile.TemporaryDirectory() as temporary_directory:
            campaign_root = Path(temporary_directory)
            self._write_campaign(campaign_root, mutate=replace_rationale)

            with self.assertRaises(ValueError):
                load_campaign_summary(campaign_root)

    def test_campaign_loader_rejects_response_path_escape(self) -> None:
        def escape_variant(
            variant: str, rep: int, record: dict[str, object]
        ) -> None:
            if variant == VARIANTS[0] and rep == 1:
                record["responsePath"] = "../outside.md"

        with tempfile.TemporaryDirectory() as temporary_directory:
            campaign_root = Path(temporary_directory)
            self._write_campaign(campaign_root, mutate=escape_variant)

            with self.assertRaises(ValueError):
                load_campaign_summary(campaign_root)

    def test_campaign_loader_rejects_self_or_cross_run_response_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            campaign_root = Path(temporary_directory)
            self._write_campaign(campaign_root)
            record_path = campaign_root / VARIANTS[0] / "01.json"
            record = json.loads(record_path.read_text(encoding="utf-8"))
            record["responsePath"] = "01.json"
            record_path.write_text(json.dumps(record), encoding="utf-8")

            with self.assertRaises(ValueError):
                load_campaign_summary(campaign_root)

        with tempfile.TemporaryDirectory() as temporary_directory:
            campaign_root = Path(temporary_directory)
            self._write_campaign(campaign_root)
            variant_root = campaign_root / VARIANTS[0]
            first = json.loads((variant_root / "01.json").read_text(encoding="utf-8"))
            second_path = variant_root / "02.json"
            second = json.loads(second_path.read_text(encoding="utf-8"))
            second["responsePath"] = first["responsePath"]
            second_path.write_text(json.dumps(second), encoding="utf-8")

            with self.assertRaises(ValueError):
                load_campaign_summary(campaign_root)

    def test_campaign_loader_rejects_response_leaf_hardlinks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            campaign_root = Path(temporary_directory)
            self._write_campaign(campaign_root)
            variant_root = campaign_root / VARIANTS[0]
            record_path = variant_root / "01.json"
            record = json.loads(record_path.read_text(encoding="utf-8"))
            response_path = variant_root / str(record["responsePath"])
            response_path.unlink()
            try:
                os.link(record_path, response_path)
            except OSError as error:
                self.skipTest(f"hardlink unavailable: {error}")

            with self.assertRaises(ValueError):
                load_campaign_summary(campaign_root)

        with tempfile.TemporaryDirectory() as temporary_directory:
            campaign_root = Path(temporary_directory)
            self._write_campaign(campaign_root)
            variant_root = campaign_root / VARIANTS[0]
            first = json.loads((variant_root / "01.json").read_text(encoding="utf-8"))
            second = json.loads((variant_root / "02.json").read_text(encoding="utf-8"))
            first_response = variant_root / str(first["responsePath"])
            second_response = variant_root / str(second["responsePath"])
            second_response.unlink()
            os.link(first_response, second_response)

            with self.assertRaises(ValueError):
                load_campaign_summary(campaign_root)

    def test_campaign_loader_rejects_response_leaf_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            campaign_root = Path(temporary_directory)
            self._write_campaign(campaign_root)
            variant_root = campaign_root / VARIANTS[0]
            record_path = variant_root / "01.json"
            record = json.loads(record_path.read_text(encoding="utf-8"))
            response_path = variant_root / str(record["responsePath"])
            response_path.unlink()
            try:
                os.symlink(record_path, response_path)
            except OSError as error:
                self.skipTest(f"file symlink unavailable: {error}")

            with self.assertRaises(ValueError):
                load_campaign_summary(campaign_root)

    def test_campaign_loader_rejects_variant_directory_links(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temporary_directory,
            tempfile.TemporaryDirectory() as external_directory,
        ):
            campaign_root = Path(temporary_directory)
            external_root = Path(external_directory)
            self._write_campaign(campaign_root, variants=VARIANTS[1:])
            self._write_campaign(external_root, variants=(VARIANTS[0],))
            try:
                os.symlink(
                    external_root / VARIANTS[0],
                    campaign_root / VARIANTS[0],
                    target_is_directory=True,
                )
            except OSError as error:
                self.skipTest(f"directory symlink unavailable: {error}")

            with self.assertRaises(ValueError):
                load_campaign_summary(campaign_root)

    def test_campaign_loader_requires_integer_schema_version_one(self) -> None:
        for invalid_version in (True, 1.0):
            with self.subTest(schemaVersion=invalid_version):
                def change_version(
                    variant: str, rep: int, record: dict[str, object]
                ) -> None:
                    if variant == VARIANTS[0] and rep == 1:
                        record["schemaVersion"] = invalid_version

                with tempfile.TemporaryDirectory() as temporary_directory:
                    campaign_root = Path(temporary_directory)
                    self._write_campaign(campaign_root, mutate=change_version)

                    with self.assertRaises(ValueError):
                        load_campaign_summary(campaign_root)

    def test_campaign_loader_rejects_malformed_or_mixed_skill_hashes(self) -> None:
        def malformed_hash(
            variant: str, rep: int, record: dict[str, object]
        ) -> None:
            if variant == VARIANTS[0] and rep == 1:
                record["skillEntrypointSha256"] = "not-a-sha256"

        with tempfile.TemporaryDirectory() as temporary_directory:
            campaign_root = Path(temporary_directory)
            self._write_campaign(campaign_root, mutate=malformed_hash)

            with self.assertRaises(ValueError):
                load_campaign_summary(campaign_root)

        def mixed_hash(variant: str, rep: int, record: dict[str, object]) -> None:
            if variant == VARIANTS[0] and rep == 1:
                record["skillEntrypointSha256"] = "b" * 64

        with tempfile.TemporaryDirectory() as temporary_directory:
            campaign_root = Path(temporary_directory)
            self._write_campaign(campaign_root, mutate=mixed_hash)

            with self.assertRaises(ValueError):
                load_campaign_summary(campaign_root)

    def test_require_pass_binds_records_to_current_skill_hash(self) -> None:
        def stale_hash(variant: str, rep: int, record: dict[str, object]) -> None:
            record["skillEntrypointSha256"] = "b" * 64

        with tempfile.TemporaryDirectory() as temporary_directory:
            campaign_root = Path(temporary_directory)
            self._write_campaign(campaign_root, mutate=stale_hash)

            summary = validate_campaign(campaign_root, require_pass=False)
            self.assertEqual(len(summary["runs"]), 20)
            with self.assertRaises(ValueError):
                validate_campaign(campaign_root, require_pass=True)

    def test_campaign_loader_rejects_duplicate_variant_rep_pairs(self) -> None:
        def duplicate_rep(variant: str, rep: int, record: dict[str, object]) -> None:
            if variant == VARIANTS[0] and rep == 2:
                record["rep"] = 1

        with tempfile.TemporaryDirectory() as temporary_directory:
            campaign_root = Path(temporary_directory)
            self._write_campaign(campaign_root, mutate=duplicate_rep)

            with self.assertRaises(ValueError):
                load_campaign_summary(campaign_root)

    def test_campaign_loader_rejects_missing_or_incomplete_records(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            campaign_root = Path(temporary_directory)
            self._write_campaign(campaign_root, omitted={(VARIANTS[0], 5)})

            with self.assertRaises(ValueError):
                load_campaign_summary(campaign_root)

        def remove_manual_verdict(
            variant: str, rep: int, record: dict[str, object]
        ) -> None:
            if variant == VARIANTS[0] and rep == 1:
                record.pop("pass")

        with tempfile.TemporaryDirectory() as temporary_directory:
            campaign_root = Path(temporary_directory)
            self._write_campaign(campaign_root, mutate=remove_manual_verdict)

            with self.assertRaises(ValueError):
                load_campaign_summary(campaign_root)

    def test_campaign_loader_rejects_unreviewed_records(self) -> None:
        def make_unreviewed(
            variant: str, rep: int, record: dict[str, object]
        ) -> None:
            if variant == VARIANTS[0] and rep == 1:
                record["reviewed"] = False

        with tempfile.TemporaryDirectory() as temporary_directory:
            campaign_root = Path(temporary_directory)
            self._write_campaign(campaign_root, mutate=make_unreviewed)

            with self.assertRaises(ValueError):
                load_campaign_summary(campaign_root)

    def test_validate_campaign_requires_every_manual_verdict_to_pass(self) -> None:
        def make_manual_failure(
            variant: str, rep: int, record: dict[str, object]
        ) -> None:
            if variant == VARIANTS[0] and rep == 1:
                record["pass"] = False

        with tempfile.TemporaryDirectory() as temporary_directory:
            campaign_root = Path(temporary_directory)
            self._write_campaign(campaign_root, mutate=make_manual_failure)

            summary = validate_campaign(campaign_root, require_pass=False)
            failed_run = next(
                run
                for run in summary["runs"]
                if run["variant"] == VARIANTS[0] and run["rep"] == 1
            )
            self.assertFalse(failed_run["pass"])
            with self.assertRaises(ValueError):
                validate_campaign(campaign_root, require_pass=True)


if __name__ == "__main__":
    unittest.main()
