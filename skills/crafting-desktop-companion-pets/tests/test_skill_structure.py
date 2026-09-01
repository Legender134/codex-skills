from __future__ import annotations

import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
WORD = re.compile(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*")
REQUIRED_REFERENCES = {
    "identity-and-evidence.md",
    "canonical-identity-and-proportions.md",
    "actions-and-motion.md",
    "generation-job-graph.md",
    "visual-qa.md",
    "repair-and-convergence.md",
    "behavior-and-soak.md",
    "format-v2.md",
    "format-v3.md",
    "format-v4.md",
    "nangong-wan-calibration-case.md",
}
RECOVERED_RULE_MARKERS = {
    "generation-job-graph.md": (
        "one passing representative pilot for every planned risk class",
        "`identity/idle`",
        "`prop interaction`",
        "`cyclic locomotion`",
        "`burst/transformation`",
        "`large/layered effect`",
        "`form/sequence`",
        "does not authorize another risk class",
        "selected IDs",
        "selected masters/pilots",
        "maximum candidates per action",
        "maximum targeted-repair attempts",
        "checkpoints",
        "wall-time/task budget",
        "forced-stop rules",
    ),
    "canonical-identity-and-proportions.md": (
        "Preserve high-salience recognition before tertiary texture.",
        "Simplify tiny decoration before shrinking the body or blurring the face.",
        "A stylized or chibi route must preserve target age impression and target-specific proportions.",
    ),
    "visual-qa.md": (
        "Review every generated cell/frame in manifest order; sampling is not permitted.",
        "Reject halos, destructive cutouts, clipped pixels, accidental empties,",
        "normalization that removes intended motion.",
    ),
}
FIX_1_OWNER_MARKERS = {
    "references/behavior-and-soak.md": (
        "stable weighted pool",
        "at least five deterministic seeds",
        "lowest-probability candidate to have at least 100 expected selections",
        "Pearson multinomial goodness-of-fit at `alpha=0.01`",
        "Bonferroni-adjusted two-sided 99% binomial intervals",
        "no defensible expected distribution exists",
        "distribution `UNVERIFIED`",
    ),
    "references/generation-job-graph.md": (
        "Every generation or edit request records:",
        "task type and the role of every reference",
        "exact era/form and identity locks",
        "transparent canvas/cell geometry",
        "exact grid order and per-cell semantic phase",
        "stable features and permitted changes",
        "anatomy, prop, occlusion, effect, and anchor state",
        "effect whitelist/blacklist",
        "text, borders, unrelated characters/props, opaque backgrounds, clipping, and body-scale changes",
        "preservation of unaffected cells for a targeted repair",
        "fresh-context second review",
        "recorded limitation",
    ),
    "templates/project-brief.md": (
        "## Capability decision record",
        "Required capabilities and evidence",
        "Alternatives considered",
        "Fidelity preserved",
        "Fidelity omitted by each alternative",
        "Limitations",
        "Complexity/extensibility",
        "Route-changing uncertainty",
        "Explicit post-research confirmation",
    ),
    "references/format-runtime-core.md": (
        "New package or migration capability decision",
        "[Project brief](../templates/project-brief.md)",
    ),
}


def parse_yaml_scalar(value: str) -> object:
    if value == "true":
        return True
    if value == "false":
        return False
    if value.startswith('"') and value.endswith('"'):
        return json.loads(value)
    return value


def parse_simple_yaml(text: str) -> dict[str, object]:
    parsed: dict[str, object] = {}
    current_mapping: dict[str, object] | None = None
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indentation = len(line) - len(line.lstrip(" "))
        key, separator, raw_value = line.strip().partition(":")
        if not separator:
            raise ValueError(f"Unsupported YAML line: {line}")
        value = raw_value.strip()
        if indentation == 0:
            if value:
                parsed[key] = parse_yaml_scalar(value)
                current_mapping = None
            else:
                current_mapping = {}
                parsed[key] = current_mapping
        elif indentation == 2 and current_mapping is not None:
            current_mapping[key] = parse_yaml_scalar(value)
        else:
            raise ValueError(f"Unsupported YAML indentation: {line}")
    return parsed


def parse_frontmatter_and_body(path: Path) -> tuple[dict[str, object], str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        raise ValueError(f"Missing frontmatter in {path}")
    try:
        closing_index = lines.index("---", 1)
    except ValueError as error:
        raise ValueError(f"Unterminated frontmatter in {path}") from error
    return parse_simple_yaml("\n".join(lines[1:closing_index])), "\n".join(
        lines[closing_index + 1 :]
    )


def body_word_count(body: str) -> int:
    non_table_body = "\n".join(
        line for line in body.splitlines() if not line.lstrip().startswith("|")
    )
    return len(WORD.findall(non_table_body))


class SkillStructureTest(unittest.TestCase):
    def test_entrypoint_frontmatter_and_ui_metadata(self) -> None:
        frontmatter, _ = parse_frontmatter_and_body(ROOT / "SKILL.md")
        openai = parse_simple_yaml(
            (ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        )

        self.assertEqual(frontmatter["name"], "crafting-desktop-companion-pets")
        self.assertEqual(
            frontmatter["description"],
            "Use when creating, repairing, reviewing, validating, or packaging any "
            "character, animal, mascot, object, mechanical, flying, or abstract "
            "pet for this user's DesktopCompanion software; excludes generic Codex "
            "animated pets handled by hatch-pet.",
        )
        self.assertTrue(frontmatter["description"].startswith("Use when "))
        self.assertLessEqual(len(frontmatter["description"]), 500)
        self.assertEqual(
            openai["interface"]["display_name"],
            "DesktopCompanion Pet Studio",
        )
        self.assertEqual(
            openai["interface"]["short_description"],
            "Evidence-led DesktopCompanion pets across v2, v3, and v4",
        )
        self.assertEqual(
            openai["interface"]["default_prompt"],
            "Use $crafting-desktop-companion-pets to create or repair this "
            "DesktopCompanion pet with the correct identity route, format, visual "
            "QA, runtime checks, and authority gates.",
        )
        self.assertIn(
            "$crafting-desktop-companion-pets",
            openai["interface"]["default_prompt"],
        )
        self.assertIs(openai["policy"]["allow_implicit_invocation"], True)

    def test_entrypoint_body_stays_within_word_budget(self) -> None:
        _, body = parse_frontmatter_and_body(ROOT / "SKILL.md")
        self.assertLessEqual(body_word_count(body), 650)

    def test_required_focused_references_exist(self) -> None:
        actual = {
            path.name for path in (ROOT / "references").glob("*.md")
        }
        self.assertTrue(REQUIRED_REFERENCES.issubset(actual))

    def test_all_relative_markdown_links_resolve_inside_skill(self) -> None:
        failures: list[str] = []
        for source in ROOT.rglob("*.md"):
            text = source.read_text(encoding="utf-8")
            for raw in LINK.findall(text):
                target_text = raw.split("#", 1)[0]
                if not target_text or "://" in target_text:
                    continue
                target = (source.parent / target_text).resolve()
                try:
                    target.relative_to(ROOT.resolve())
                except ValueError:
                    failures.append(f"{source}: link escapes skill: {raw}")
                    continue
                if not target.exists():
                    failures.append(f"{source}: missing link: {raw}")
        self.assertEqual(failures, [])

    def test_recovered_legacy_rules_have_focused_owners(self) -> None:
        for reference, markers in RECOVERED_RULE_MARKERS.items():
            text = (ROOT / "references" / reference).read_text(encoding="utf-8")
            normalized_text = re.sub(r"\s+", " ", text)
            for marker in markers:
                normalized_marker = re.sub(r"\s+", " ", marker)
                self.assertIn(
                    normalized_marker,
                    normalized_text,
                    f"{reference} must own: {marker}",
                )

    def test_fix_1_rules_have_single_focused_owners(self) -> None:
        for relative_path, markers in FIX_1_OWNER_MARKERS.items():
            text = (ROOT / relative_path).read_text(encoding="utf-8")
            normalized_text = re.sub(r"\s+", " ", text)
            for marker in markers:
                normalized_marker = re.sub(r"\s+", " ", marker)
                self.assertIn(
                    normalized_marker,
                    normalized_text,
                    f"{relative_path} must own: {marker}",
                )


if __name__ == "__main__":
    unittest.main()
