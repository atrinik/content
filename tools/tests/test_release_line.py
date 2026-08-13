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

    def test_preserved_main_classic_contract_matches_the_cutover_source(self) -> None:
        contract = json.loads(
            (ROOT / "contracts/release-lines/classic-main.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(contract["branch"], "main")
        self.assertEqual(contract["component"], "content")
        self.assertEqual(
            contract["consumers"],
            ["classic/client", "classic/editor", "classic/server"],
        )
        self.assertFalse(contract["replacement_ready"])
        self.assertFalse(contract["replacement_toolkit_package"])

    def test_semantic_release_is_retired(self) -> None:
        self.assertFalse((ROOT / ".releaserc.json").exists())
        self.assertFalse((ROOT / ".github/workflows/release.yml").exists())

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
