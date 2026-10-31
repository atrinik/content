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
            ["60a60c2bd17846f5cb9269c069eec46e08ea5d59"],
        )
        self.assertEqual(history[0]["changes"][0]["status"], "A")

    def test_merchant_history_reaches_creation_before_rename(self) -> None:
        history = m1_foundations.path_history(ROOT, "maps/python/Merchant.py")
        self.assertEqual(
            [row["revision"] for row in history],
            [
                "07911d6e0df0fb0d4765a6bd12bd5906b144fe0c",
                "aba80985a0b57cda997c00a85a92a20fd3ee8390",
                "1c23943175f0a86f1505746e2e0cbe2bb73f92e9",
                "46d66c077a0d37998d59ff92974f353df6e32ae0",
                "a14c122bca452ec7337699881f258505e4fa92a8",
                "7fde178562662f1e0b697b1844aeec93b813e7ea",
                "d441630c53e06527b67cdab6f2106d4d0e5801f2",
                "085caacf90170ea413294a56ad21460684262463",
                "7b3f46c8a9ce6426210a0647d69f89df5647d644",
                "274380eb23291ffb61c91336fe294e746c4ef7fb",
                "977126c7098e3fcdb95f5f9a4e8789209b935a48",
                "5c26eb4d995eb455709444d4c8ce162787115c56",
                "cc264feeca9bb4dcd74515601ed3649d8b4aadff",
            ],
        )
        self.assertEqual(
            history[-1]["changes"],
            [{"status": "A", "paths": ["maps/python/Seller.py"]}],
        )

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
                "fork_revision": "5a06b026a44ce1437a14eec60faa0ea2f15d44b1",
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
