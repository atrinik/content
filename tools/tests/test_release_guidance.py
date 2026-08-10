"""Regression tests for synchronized dual-release-line guidance."""

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
    "Assess every issue-driven fix against both `main` and `1.x`",
    "a fix discovered on `1.x` must also reach `main` whenever compatible",
    "separate worktrees, validation runs, commits, and linked pull requests",
    "For paired delivery, the canonical `main` pull request is the only one that closes the issue",
    "`1.x` companion links both the issue and canonical pull request",
    "without using a closing keyword",
    "single-line exception must record explicit evidence and rationale",
    "sole applicable pull request is canonical",
    "Never merge branches wholesale or share generated output between worktrees",
)


class ReleaseGuidanceTests(unittest.TestCase):
    def test_every_guidance_surface_preserves_dual_line_delivery_policy(self) -> None:
        for relative_path in GUIDANCE_PATHS:
            with self.subTest(path=str(relative_path)):
                guidance = " ".join(
                    (ROOT / relative_path).read_text(encoding="utf-8").split()
                )
                for policy in REQUIRED_POLICY:
                    self.assertIn(policy, guidance)


if __name__ == "__main__":
    unittest.main()
