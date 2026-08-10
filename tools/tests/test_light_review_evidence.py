"""Tests for deterministic Classic client light-review evidence generation."""

import hashlib
import json
import tempfile
from types import SimpleNamespace
import unittest
from pathlib import Path

from tools import light_review_evidence as evidence


class LightReviewEvidenceTest(unittest.TestCase):
    def test_capture_plan_covers_invisible_emitters_and_representative_maps(self):
        report = {
            "maps": [
                {
                    "path": "maps/invisible",
                    "semantic_sha256": "1" * 64,
                    "emitters": [
                        {"x": 0, "y": 0, "visible": False},
                        {"x": 8, "y": 8, "visible": False},
                        {"x": 20, "y": 20, "visible": False},
                    ],
                },
                {
                    "path": "maps/visible",
                    "semantic_sha256": "2" * 64,
                    "emitters": [{"x": 4, "y": 5, "visible": True}],
                },
            ]
        }

        plan = evidence.capture_plan(report)

        self.assertEqual(
            [
                ("maps/invisible", 0, 0),
                ("maps/invisible", 20, 20),
                ("maps/visible", 4, 5),
            ],
            [(row["map"], row["x"], row["y"]) for row in plan],
        )

    def test_png_round_trip_is_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.png"
            second = Path(directory) / "second.png"
            pixels = bytes((255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 255))

            evidence.write_png(first, 2, 2, pixels)
            evidence.write_png(second, 2, 2, pixels)

            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual((2, 2, pixels), evidence.read_png(first))

    def test_build_validates_captures_and_replaces_stale_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "maps" / "light-source-evidence"
            output.mkdir(parents=True)
            (output / "stale.png").write_bytes(b"stale")
            captures = root / "captures"
            captures.mkdir()
            screenshot = captures / "scene.png"
            evidence.write_png(screenshot, 1024, 768, bytes(1024 * 768 * 3))
            digest = hashlib.sha256(screenshot.read_bytes()).hexdigest()
            semantic = "a" * 64
            commit = "b" * 40
            inventory = {
                "archetypes": [],
                "artifacts": [],
                "color_sources": [],
                "toggle_states": [],
                "maps": [{
                    "path": "maps/scene",
                    "semantic_sha256": semantic,
                    "emitters": [{"x": 1, "y": 2, "visible": True}],
                }],
            }
            inventory_path = root / "inventory.json"
            inventory_path.write_text(json.dumps(inventory))
            context_path = root / "context.json"
            context_path.write_text(json.dumps({"content_commit": commit}))
            representatives_path = root / "representatives.json"
            representatives_path.write_text("{}")
            rows = [{
                "artifact": "scene.png",
                "map": "maps/scene",
                "map_semantic_sha256": semantic,
                "content_commit": commit,
                "sha256": digest,
                "x": 1,
                "y": 2,
            }]
            smooth = captures / "smooth.json"
            discrete = captures / "discrete.json"
            smooth.write_text(json.dumps(rows))
            discrete.write_text(json.dumps(rows))
            args = SimpleNamespace(
                inventory=inventory_path,
                smooth_manifest=smooth,
                discrete_manifest=discrete,
                context=context_path,
                representatives=representatives_path,
                output=output,
                dry_run=False,
            )
            original_root = evidence.audit.ROOT
            evidence.audit.ROOT = root
            try:
                result = evidence.build_evidence(args)
            finally:
                evidence.audit.ROOT = original_root

            self.assertEqual(2, result["sheets"])
            self.assertFalse((output / "stale.png").exists())
            self.assertTrue((output / "smooth-001.png").is_file())
            self.assertEqual(2, json.loads((output / "manifest.json").read_text())["schema_version"])


if __name__ == "__main__":
    unittest.main()
