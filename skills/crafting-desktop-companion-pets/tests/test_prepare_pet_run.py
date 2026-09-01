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


if __name__ == "__main__":
    unittest.main()
