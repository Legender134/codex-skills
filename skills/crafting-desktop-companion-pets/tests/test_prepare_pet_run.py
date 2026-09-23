from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from prepare_pet_run import prepare_pet_run


class PreparePetRunTest(unittest.TestCase):
    def test_creates_complete_draft_run_without_touching_siblings(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            sibling = root / "keep.txt"
            sibling.write_text("user-owned", encoding="utf-8")

            run = prepare_pet_run(root, "cloud-cat", "original-brand", "v3")

            self.assertEqual(sibling.read_text(encoding="utf-8"), "user-owned")
            self.assertEqual(
                {path.relative_to(run).as_posix() for path in run.rglob("*") if path.is_dir()},
                {
                    "evidence",
                    "contracts",
                    "contracts/actions",
                    "references",
                    "references/selected-sources",
                    "decoded",
                    "frames",
                    "atlases",
                    "package",
                    "qa",
                    "qa/identity",
                    "qa/actions",
                    "qa/runtime",
                    "qa/behavior",
                },
            )
            identity = json.loads(
                (run / "contracts" / "identity.json").read_text(encoding="utf-8")
            )
            self.assertEqual(identity["identityRoute"], "original-brand")
            self.assertEqual(identity["formatRoute"], "v3")
            self.assertEqual(identity["selection"], "candidate")
            self.assertEqual(identity["visualStatus"], "not-reviewed")
            sources = json.loads(
                (run / "evidence" / "sources.json").read_text(encoding="utf-8")
            )
            self.assertEqual(sources, {"schemaVersion": 1, "sources": []})

    def test_rejects_unsafe_id_and_existing_run(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with self.assertRaisesRegex(ValueError, "project_id"):
                prepare_pet_run(root, "../escape", "source-faithful", "v3")
            prepare_pet_run(root, "safe-id", "source-faithful", "undecided")
            with self.assertRaises(FileExistsError):
                prepare_pet_run(root, "safe-id", "source-faithful", "undecided")

    def test_resume_index_is_portable_and_does_not_grant_authority(self) -> None:
        for route in ("undecided", "v2", "v3", "v4"):
            with self.subTest(route=route), tempfile.TemporaryDirectory() as raw:
                run = prepare_pet_run(Path(raw), "cloud-cat", "original-brand", route)
                for relative in (
                    "contracts/identity.json",
                    "contracts/actions/action-contract.json",
                    "jobs.json",
                    "qa/visual-verdict.json",
                    "run-summary.json",
                ):
                    with self.subTest(record=relative):
                        record = json.loads((run / relative).read_text(encoding="utf-8"))
                        self.assertEqual(record["formatRoute"], route)
                state = json.loads((run / "production-state.json").read_text(encoding="utf-8"))
                self.assertEqual(state["projectId"], "cloud-cat")
                self.assertEqual(state["identityRoute"], "original-brand")
                self.assertEqual(state["formatRoute"], route)
                self.assertIs(state["diagnosticOnly"], True)
                self.assertEqual(state["approvedDecisions"], [])
                self.assertTrue(all(value is False for value in state["authority"].values()))
                self.assertIsNone(state["execution"]["observedImageModel"])
                self.assertIsNone(state["execution"]["observedAgent"])
                self.assertIsNone(state["execution"]["observedReviewer"])
                self.assertEqual(state["execution"]["imageRoute"], "built-in")
                for relative in state["records"].values():
                    self.assertFalse(Path(relative).is_absolute())
                    self.assertTrue((run / relative).is_file())
                self.assertTrue(state["nextAction"])


if __name__ == "__main__":
    unittest.main()
