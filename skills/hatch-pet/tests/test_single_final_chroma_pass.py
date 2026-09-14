import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]


class SingleFinalChromaPassTest(unittest.TestCase):
    def test_cleanup_runs_only_after_v2_assembly(self) -> None:
        entrypoint = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("references/generation-workflow.md", entrypoint)
        self.assertIn("references/look-direction-workflow.md", entrypoint)
        instructions = "\n".join(
            (SKILL_DIR / relative).read_text(encoding="utf-8")
            for relative in (
                "SKILL.md",
                "references/generation-workflow.md",
                "references/look-direction-workflow.md",
            )
        )

        self.assertEqual(instructions.count("scripts/despill_chroma_edges.py"), 1)
        self.assertNotIn("chroma-despill-standard.json", instructions)
        self.assertLess(
            instructions.index("scripts/assemble_extended_atlas.py"),
            instructions.index("scripts/despill_chroma_edges.py"),
        )


if __name__ == "__main__":
    unittest.main()
