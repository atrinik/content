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
    "`main` is the sole forward authoring line",
    "`1.x` is frozen rollback and migration evidence",
    "Reconciliation changes require separate worktrees, validation, commits, and linked pull requests",
    "canonical `main` PR owns closing only after downstream integration and branch-specific release machinery have retired",
    "Never merge histories wholesale or share generated output between worktrees",
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


if __name__ == "__main__":
    unittest.main()
