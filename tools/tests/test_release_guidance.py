"""Regression tests for the retired 1.x release-line boundary."""

from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).parents[2]
GUIDANCE_PATHS = (
    Path("AGENTS.md"),
    Path("CONTRIBUTING.md"),
    Path("docs/RELEASE_LINES.md"),
)
REQUIRED_POLICY = (
    "This `1.x` branch is immutable rollback and migration evidence",
    "not an authored source, maintenance line, or release channel",
    "`main` is the sole authored and released content source",
    "explicit organization-owner decision",
)


class ReleaseGuidanceTests(unittest.TestCase):
    def test_every_guidance_surface_preserves_retirement_policy(self) -> None:
        for relative_path in GUIDANCE_PATHS:
            with self.subTest(path=str(relative_path)):
                guidance = " ".join(
                    (ROOT / relative_path).read_text(encoding="utf-8").split()
                )
                for policy in REQUIRED_POLICY:
                    self.assertIn(policy, guidance)

    def test_release_automation_is_absent_but_branch_validation_remains(self) -> None:
        self.assertFalse((ROOT / ".releaserc.json").exists())
        self.assertFalse((ROOT / ".github/workflows/release.yml").exists())
        for relative_path in (
            Path(".github/workflows/check.yml"),
            Path(".github/workflows/pr-title.yml"),
        ):
            workflow = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertIn("1.x", workflow)


if __name__ == "__main__":
    unittest.main()
