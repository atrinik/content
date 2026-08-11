from __future__ import annotations

import json
from pathlib import Path
import unittest

from tools import build_runtime
from tools import check_pr_title


ROOT = Path(__file__).parents[2]


class ReleaseLineTests(unittest.TestCase):
    def test_classic_contract_is_exact_and_replacement_excluded(self) -> None:
        contract = build_runtime.load_release_contract(ROOT)
        self.assertEqual(contract["branch"], "1.x")
        self.assertEqual(contract["fork_revision"], "01b1fdb65c2243df4bafe9c8109fc93229df0121")
        self.assertEqual(
            contract["consumers"],
            ["classic/client", "classic/editor", "classic/server"],
        )
        self.assertFalse(contract["replacement_ready"])
        self.assertFalse(contract["replacement_toolkit_package"])

    def test_semantic_release_has_bounded_maintenance_channel(self) -> None:
        configuration = json.loads((ROOT / ".releaserc.json").read_text(encoding="utf-8"))
        maintenance = [
            branch
            for branch in configuration["branches"]
            if isinstance(branch, dict) and branch.get("name") == "1.x"
        ]
        self.assertEqual(
            maintenance,
            [{"name": "1.x", "range": "1.x", "channel": "1.x"}],
        )
        self.assertEqual(configuration["branches"], [maintenance[0], "main"])
        analyzer = configuration["plugins"][0]
        self.assertEqual(analyzer[0], "@semantic-release/commit-analyzer")
        historical_rules = [
            rule
            for rule in analyzer[1]["releaseRules"]
            if rule.get("type") == "feat" and rule.get("release") == "patch"
        ]
        self.assertEqual(
            historical_rules,
            [
                {
                    "type": "feat",
                    "scope": "release",
                    "subject": "establish classic content maintenance line*",
                    "release": "patch",
                },
                {
                    "type": "feat",
                    "scope": "lighting",
                    "subject": "author colored light sources (#64)",
                    "release": "patch",
                },
                {
                    "type": "feat",
                    "scope": "maps",
                    "subject": "persist the Incuna Sam objective (#63)",
                    "release": "patch",
                },
                {
                    "type": "feat",
                    "scope": "lighting",
                    "subject": "audit effective light-source colors (#67)",
                    "release": "patch",
                },
                {
                    "type": "feat",
                    "scope": "quests",
                    "subject": "teach the Incuna apartment flow on 1.x (#112)",
                    "release": "patch",
                },
                {
                    "type": "feat",
                    "scope": "archetypes",
                    "subject": "make fire fixtures emit light (#115)",
                    "release": "patch",
                },
                {
                    "type": "feat",
                    "scope": "maps",
                    "subject": "transfer crystal light ownership (#116)",
                    "release": "patch",
                },
                {
                    "type": "feat",
                    "scope": "maps",
                    "subject": "give Rockforge teleporter a focal glow (#117)",
                    "release": "patch",
                },
                {
                    "type": "feat",
                    "scope": "archetypes",
                    "subject": "make toxic pools emit matching light (#118)",
                    "release": "patch",
                },
            ],
        )
        self.assertNotIn(
            {"type": "feat", "release": "minor"}, analyzer[1]["releaseRules"]
        )
        github = configuration["plugins"][-1]
        self.assertEqual(github[0], "@semantic-release/github")
        self.assertIs(github[1]["failComment"], False)

    def test_pull_request_title_policy_preserves_main_and_bounds_1x(self) -> None:
        self.assertIsNone(check_pr_title.validation_error("main", "feat: add content"))
        self.assertIsNone(
            check_pr_title.validation_error("main", "fix!: migrate content")
        )
        self.assertIsNone(
            check_pr_title.validation_error("1.x", "fix: repair content")
        )
        self.assertIsNotNone(
            check_pr_title.validation_error("1.x", "feat(lighting): add content")
        )
        self.assertIsNotNone(
            check_pr_title.validation_error("1.x", "fix(content)!: migrate content")
        )
        self.assertIsNotNone(check_pr_title.validation_error("1.x", "not conventional"))

    def test_pull_request_workflow_uses_release_line_policy(self) -> None:
        workflow = (ROOT / ".github/workflows/pr-title.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("PR_BASE: ${{ github.event.pull_request.base.ref }}", workflow)
        self.assertIn("ref: ${{ github.event.pull_request.base.sha }}", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertIn(
            'python3 tools/check_pr_title.py --base "${PR_BASE}" "${PR_TITLE}"',
            workflow,
        )


if __name__ == "__main__":
    unittest.main()
