from __future__ import annotations

from pathlib import Path
import json
import unittest

from tools import m1_foundations


ROOT = Path(__file__).parents[2]


class M1FoundationTests(unittest.TestCase):
    def test_static_observations_are_bounded_and_sorted(self) -> None:
        observations = m1_foundations.static_observations(
            "import zeta\nfrom alpha.beta import thing\n"
            "# import ignored\n"
            "def public_name():\n"
            "    ignored = 'Atrinik.Fake() EVENT_FAKE'\n"
            "    Atrinik.Map()\n"
            "    return EVENT_LOGIN\n"
        )
        self.assertEqual(observations["imports"], ["alpha", "zeta"])
        self.assertEqual(observations["public_symbols"], ["public_name"])
        self.assertEqual(observations["engine_calls"], ["Map"])
        self.assertEqual(observations["event_tokens"], ["EVENT_LOGIN"])

    def test_capability_profile_is_evidence_bounded(self) -> None:
        profile = m1_foundations.capability_profile(
            "maps/python/quests/example.py",
            {
                "imports": ["QuestManager"],
                "public_symbols": [],
                "engine_calls": ["WhoAmI", "PlayerMessage"],
                "event_tokens": ["EVENT_SAY"],
            },
        )
        self.assertIn("quest", profile["state_domains"])
        self.assertIn("player", profile["state_domains"])
        self.assertIn("diagnostic-or-player-output", profile["observable_effect_classes"])

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

    def test_classic_release_line_is_bounded_and_configured(self) -> None:
        contract = json.loads(
            (ROOT / "contracts/release-lines/classic-1x.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            {
                "schema_version": 1,
                "component": "content-1x",
                "repository": "atrinik/content",
                "branch": "1.x",
                "fork_tag": "v1.8.1",
                "fork_revision": "01b1fdb65c2243df4bafe9c8109fc93229df0121",
                "content_format": "classic-ads-v1",
                "artifact_format": "atrinik-classic-runtime-content-v1",
                "compatible_classic_releases": ">=5.10.1 <6.0.0",
                "consumers": [
                    "classic/client",
                    "classic/editor",
                    "classic/server",
                ],
                "replacement_ready": False,
                "replacement_toolkit_package": False,
            },
            contract,
        )
        release = json.loads((ROOT / ".releaserc.json").read_text(encoding="utf-8"))
        self.assertEqual(
            ["+([0-9]).+([0-9]).x", "main"],
            release["branches"],
        )

    def test_main_establishes_the_replacement_major_boundary(self) -> None:
        self.assertEqual(
            (ROOT / "release-line.txt").read_text(encoding="utf-8"),
            "2.0\n",
        )


if __name__ == "__main__":
    unittest.main()
