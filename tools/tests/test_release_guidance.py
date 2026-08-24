"""Regression tests for synchronized single-source transition guidance."""

from __future__ import annotations

import json
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

    def test_release_success_does_not_resolve_historical_local_issues(self) -> None:
        release = json.loads((ROOT / ".releaserc.json").read_text(encoding="utf-8"))
        plugins = {plugin[0]: plugin[1] for plugin in release["plugins"]}
        self.assertIs(
            plugins["@semantic-release/github"]["successCommentCondition"], False
        )
        self.assertEqual(
            plugins["@semantic-release/exec"]["successCmd"],
            "node scripts/release/verify-release.cjs ${nextRelease.version} ${nextRelease.gitHead}",
        )
        fixture = (
            ROOT / "scripts" / "release" / "fixtures" / "unavailable-local-issues.md"
        ).read_text(encoding="utf-8")
        for reference in ("#308", "#287", "atrinik/atrinik#266"):
            self.assertIn(reference, fixture)
        self.assertIn("https://github.com/atrinik/atrinik/issues/266", fixture)


if __name__ == "__main__":
    unittest.main()
