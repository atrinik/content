"""Regression tests for the machine-readable release-line parity ledger."""

from __future__ import annotations

import copy
import unittest
from pathlib import Path

from tools.content_contracts.contracts import (
    ContractError,
    load_json,
    validate_instance,
    validate_schema,
)
from tools.release_line_parity import (
    LEDGER_PATH,
    SCHEMA_NAME,
    SCHEMA_PATH,
    ParityError,
    load_and_validate,
    validate_document,
)


ROOT = Path(__file__).parents[2].resolve()


class ReleaseLineParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.document = load_json(ROOT / LEDGER_PATH)
        cls.schema = validate_schema(load_json(ROOT / SCHEMA_PATH), SCHEMA_NAME)

    def mutate(self):
        return copy.deepcopy(self.document)

    def test_committed_ledger_covers_the_current_horizon(self):
        report = load_and_validate(ROOT)
        self.assertEqual(61, report["commits"])
        self.assertEqual({"main": 29, "1.x": 32}, report["commits_by_line"])
        self.assertEqual(32, report["outcomes"])
        self.assertEqual(43, report["tree_exceptions"])

    def test_schema_rejects_unknown_classification(self):
        document = self.mutate()
        document["outcomes"][0]["classification"] = "similar"
        with self.assertRaisesRegex(ContractError, "allowed value"):
            validate_instance(document, self.schema)

    def test_duplicate_commit_is_rejected(self):
        document = self.mutate()
        document["outcomes"][1]["source"].append(
            copy.deepcopy(document["outcomes"][0]["source"][0])
        )
        with self.assertRaisesRegex(ParityError, "occurs in both"):
            validate_document(document, check_history=False)

    def test_missing_commit_fails_history_coverage(self):
        document = self.mutate()
        line = "main" if (ROOT / "release-line.txt").read_text().strip() == "2.0" else "1.x"
        removed = False
        for outcome in document["outcomes"]:
            for side in ("source", "destination"):
                for index, endpoint in enumerate(outcome[side]):
                    if endpoint["line"] == line:
                        del outcome[side][index]
                        removed = True
                        break
                if removed:
                    break
            if removed:
                break
        self.assertTrue(removed)
        with self.assertRaisesRegex(ParityError, "history coverage mismatch"):
            validate_document(document, root=ROOT)

    def test_exempt_destination_is_contradictory(self):
        document = self.mutate()
        document["outcomes"][0]["destination"] = [
            copy.deepcopy(document["outcomes"][1]["destination"][0])
        ]
        with self.assertRaisesRegex(ParityError, "exempt outcome has a destination"):
            validate_document(document, check_history=False)

    def test_paired_outcome_requires_a_destination(self):
        document = self.mutate()
        document["outcomes"][1]["destination"] = []
        with self.assertRaisesRegex(ParityError, "paired outcome has no destination"):
            validate_document(document, check_history=False)

    def test_pending_outcome_is_stale_at_delivered_horizons(self):
        document = self.mutate()
        document["outcomes"][1]["classification"] = "pending"
        document["outcomes"][1]["destination"] = []
        with self.assertRaisesRegex(ParityError, "cannot retain pending"):
            validate_document(document, check_history=False)

    def test_prepublication_plan_cannot_guess_pull_requests(self):
        document = self.mutate()
        document["terminal_plan"]["state"] = "prepublication"
        document["terminal_plan"]["main"]["commits"][0]["pull_request"] = 999
        with self.assertRaisesRegex(ParityError, "must not name pull requests"):
            validate_document(document, check_history=False)

    def test_declared_plan_requires_every_pull_request(self):
        document = self.mutate()
        document["terminal_plan"]["state"] = "declared"
        document["terminal_plan"]["main"]["commits"][0]["pull_request"] = None
        with self.assertRaisesRegex(ParityError, "require pull requests"):
            validate_document(document, check_history=False)

    def test_terminal_paths_are_exact_sorted_sets(self):
        document = self.mutate()
        paths = document["terminal_plan"]["1.x"]["commits"][0]["paths"]
        paths.append(paths[0])
        with self.assertRaisesRegex(ParityError, "sorted and unique"):
            validate_document(document, check_history=False)

    def test_retired_evidence_paths_are_forbidden(self):
        for path in (
            "maps/light-source-evidence/contact-sheet.png",
            "maps/light-source-evidence-manifest.json",
            "tools/light-source-review/dark-lab",
            "tools/light_review_evidence.py",
            "tools/tests/test_light_review_evidence.py",
        ):
            with self.subTest(path=path):
                document = self.mutate()
                document["terminal_plan"]["main"]["commits"][0]["paths"] = [path]
                with self.assertRaisesRegex(ParityError, "forbidden"):
                    validate_document(document, check_history=False)

    def test_exception_paths_are_deterministic(self):
        document = self.mutate()
        document["tree_exceptions"].reverse()
        with self.assertRaisesRegex(ParityError, "sorted and unique"):
            validate_document(document, check_history=False)


if __name__ == "__main__":
    unittest.main()
