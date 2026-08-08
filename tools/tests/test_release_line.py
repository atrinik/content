from __future__ import annotations

import json
from pathlib import Path
import unittest

from tools import build_runtime


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


if __name__ == "__main__":
    unittest.main()
