from __future__ import annotations

from pathlib import Path
import unittest

from tools import m1_foundations


ROOT = Path(__file__).parents[2]


class M1FoundationTests(unittest.TestCase):
    def test_static_observations_are_bounded_and_sorted(self) -> None:
        observations = m1_foundations.static_observations(
            "import zeta\nfrom alpha.beta import thing\n"
            "def public_name():\n    Atrinik.Map()\n    return EVENT_LOGIN\n"
        )
        self.assertEqual(observations["imports"], ["alpha", "zeta"])
        self.assertEqual(observations["public_symbols"], ["public_name"])
        self.assertEqual(observations["engine_calls"], ["Map"])
        self.assertEqual(observations["event_tokens"], ["EVENT_LOGIN"])

    def test_every_assignment_is_explicit(self) -> None:
        for path in (
            "tools/build_runtime.py",
            "maps/python/tests/Interface.py",
            "maps/python/commands/roll.py",
            "maps/python/Bank.py",
            "maps/example/scripts/trigger.py",
        ):
            assignment = m1_foundations.assignment(path)
            self.assertTrue(assignment["kind"])
            self.assertTrue(assignment["owner"])
            self.assertTrue(assignment["issue"].startswith("https://github.com/atrinik/"))

    def test_selected_history_tracks_rename_status(self) -> None:
        history = m1_foundations.path_history(
            ROOT, "prototypes/authored-syntax-v1/limits.json"
        )
        self.assertEqual(
            [row["revision"] for row in history],
            ["4aa4aebc5c88dffdf57657a34ae20306a57fbebd"],
        )
        self.assertEqual(history[0]["changes"][0]["status"], "A")


if __name__ == "__main__":
    unittest.main()
