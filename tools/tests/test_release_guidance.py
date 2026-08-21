"""Regression tests for synchronized single-source transition guidance."""

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
    "`main` is the sole authored and released",
    "`1.x` line is immutable rollback and migration evidence",
    "not a supported delivery target",
    "explicit organization-owner decision",
)


class ReleaseGuidanceTests(unittest.TestCase):
    def test_every_guidance_surface_preserves_transition_policy(self) -> None:
        for relative_path in GUIDANCE_PATHS:
            with self.subTest(path=str(relative_path)):
                guidance = " ".join(
                    (ROOT / relative_path).read_text(encoding="utf-8").split()
                )
                for policy in REQUIRED_POLICY:
                    self.assertIn(policy, guidance)

    def test_main_and_maintenance_are_active_release_sources(self) -> None:
        release = (ROOT / ".releaserc.json").read_text(encoding="utf-8")
        self.assertIn(
            '"branches": ["+([0-9]).+([0-9]).x", "main"]',
            release,
        )
        for relative_path in (
            Path(".github/workflows/check.yml"),
            Path(".github/workflows/pr-title.yml"),
            Path(".github/workflows/release.yml"),
        ):
            workflow = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotIn("1.x", workflow)


if __name__ == "__main__":
    unittest.main()
