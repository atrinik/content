"""Regression tests for pull-request metadata release policy."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github" / "scripts" / "check_pr_metadata.py"
SPEC = importlib.util.spec_from_file_location("check_pr_metadata", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
POLICY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POLICY)


class PullRequestMetadataTests(unittest.TestCase):
    def test_accepts_full_url_for_nonclosing_cross_repository_link(self) -> None:
        body = "Part of https://github.com/atrinik/atrinik/issues/357"
        self.assertEqual([], POLICY.validation_errors("fix: keep links honest", body))

    def test_rejects_v3_release_reference_regression(self) -> None:
        for prefix in ("Part of", "Refs", "Related:"):
            with self.subTest(prefix=prefix):
                errors = POLICY.validation_errors(
                    "fix: keep links honest",
                    "{} atrinik/atrinik#357".format(prefix),
                )
                self.assertEqual(1, len(errors))
                self.assertIn("ambiguous nonclosing reference", errors[0])

    def test_allows_explicit_closing_shorthand_and_local_references(self) -> None:
        body = "Closes atrinik/content#191, atrinik/atrinik#357\nRefs #191"
        self.assertEqual([], POLICY.validation_errors("fix: keep links honest", body))

    def test_rejects_nonconventional_title(self) -> None:
        errors = POLICY.validation_errors("Keep links honest", "")
        self.assertEqual(1, len(errors))
        self.assertIn("Conventional Commits", errors[0])

    def test_rejects_cross_repository_shorthand_in_squash_subject(self) -> None:
        errors = POLICY.validation_errors("fix: follow atrinik/atrinik#357", "")
        self.assertEqual(1, len(errors))
        self.assertIn("PR title uses ambiguous", errors[0])

    def test_workflow_uses_trusted_policy_and_aggregate_runs_tests(self) -> None:
        policy_workflow = (ROOT / ".github" / "workflows" / "pr-title.yml").read_text(
            encoding="utf-8"
        )
        check_workflow = (ROOT / ".github" / "workflows" / "check.yml").read_text(
            encoding="utf-8"
        )
        aggregate = (ROOT / "tools" / "validate.py").read_text(encoding="utf-8")
        self.assertIn("github.event.repository.default_branch", policy_workflow)
        self.assertIn("persist-credentials: false", policy_workflow)
        self.assertIn("lfs: false", policy_workflow)
        self.assertNotIn("lfs: true", policy_workflow)
        self.assertIn("PR_BODY", policy_workflow)
        self.assertIn(".github/scripts/check_pr_metadata.py", policy_workflow)
        self.assertIn("python3 tools/validate.py", check_workflow)
        self.assertIn("tools.tests.test_pr_metadata", aggregate)


if __name__ == "__main__":
    unittest.main()
