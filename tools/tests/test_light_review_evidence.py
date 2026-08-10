"""Tests for deterministic Classic client light-review evidence generation."""

import tempfile
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


if __name__ == "__main__":
    unittest.main()
