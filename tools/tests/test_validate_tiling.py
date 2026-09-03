from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.validate_tiling import audit, removable_spans, validate


class ValidateTilingTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        (self.root / "maps").mkdir()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def write(self, relative: str, source: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")

    @staticmethod
    def map_source(header: str = "") -> str:
        return "arch map\n{}end\n".format(header)

    def test_continuous_filename_match_is_reported_with_lossless_spans(self):
        self.write(
            "maps/world_1_1",
            self.map_source(
                "tile_path_2 /world_2_1\n"
                "celestial_boundary_2 continuous\n"
            ),
        )
        self.write("maps/world_2_1", self.map_source())

        report = audit(self.root)

        self.assertFalse(report["ok"])
        self.assertEqual(2, report["scan"]["map_files"])
        self.assertEqual(1, report["scan"]["tile_records"])
        self.assertEqual(1, report["scan"]["boundary_records"])
        self.assertEqual(1, report["scan"]["filename_matches"])
        self.assertEqual(1, report["scan"]["horizontal_matches"])
        self.assertEqual(1, report["scan"]["redundant_horizontal"])
        self.assertEqual(
            "filename-redundant-horizontal-tiling",
            report["diagnostics"][0]["code"],
        )
        self.assertEqual(
            {
                "path": "maps/world_1_1",
                "line": 2,
                "slot": 2,
            },
            report["diagnostics"][0]["source"],
        )
        self.assertEqual(
            [
                ("maps/world_1_1", "tile_path", 2),
                ("maps/world_1_1", "celestial_boundary", 2),
            ],
            [
                (item.path, item.kind, item.slot)
                for item in removable_spans(self.root)
            ],
        )

    def test_fast_validation_only_parses_tiling_candidates(self):
        self.write("maps/world_0_0", self.map_source())
        self.write(
            "maps/world_1_0",
            self.map_source(
                "tile_path_2 /world_2_0\n"
                "celestial_boundary_2 continuous\n"
            ),
        )
        self.write("maps/world_2_0", self.map_source())

        report = validate(self.root, fast=True)

        self.assertFalse(report["ok"])
        self.assertEqual(3, report["scan"]["map_files"])
        self.assertEqual(1, report["scan"]["candidate_maps"])
        self.assertEqual(1, report["scan"]["parsed_maps"])

    def test_signed_filename_coordinates_use_classic_offsets(self):
        self.write(
            "maps/world_-1_-2",
            self.map_source(
                "tile_path_2 /world_0_-2\n"
                "celestial_boundary_2 continuous\n"
            ),
        )
        self.write("maps/world_0_-2", self.map_source())

        report = audit(self.root)

        self.assertFalse(report["ok"])
        self.assertEqual(1, report["scan"]["redundant_horizontal"])
        self.assertEqual("/world_0_-2", report["diagnostics"][0]["target"])
        self.assertEqual(
            [
                ("maps/world_-1_-2", "tile_path", 2),
                ("maps/world_-1_-2", "celestial_boundary", 2),
            ],
            [
                (item.path, item.kind, item.slot)
                for item in removable_spans(self.root)
            ],
        )

    def test_policy_overrides_vertical_and_missing_neighbors_are_preserved(self):
        self.write(
            "maps/world_0_0",
            self.map_source(
                "tile_path_2 /world_1_0\n"
                "celestial_boundary_2 discontinuous\n"
            ),
        )
        self.write("maps/world_1_0", self.map_source())

        self.write(
            "maps/world_2_2",
            self.map_source(
                "tile_path_9 /world_2_2_1\n"
                "celestial_boundary_9 continuous\n"
            ),
        )
        self.write("maps/world_2_2_1", self.map_source())

        self.write(
            "maps/world_3_3",
            self.map_source(
                "tile_path_2 /override\n"
                "celestial_boundary_2 continuous\n"
            ),
        )
        self.write("maps/world_4_3", self.map_source())
        self.write("maps/override", self.map_source())

        self.write(
            "maps/world_5_5",
            self.map_source(
                "tile_path_2 /world_6_5\n"
                "celestial_boundary_2 continuous\n"
            ),
        )

        report = audit(self.root)

        self.assertTrue(report["ok"])
        self.assertEqual(2, report["scan"]["filename_matches"])
        self.assertEqual(1, report["scan"]["protected_horizontal_matches"])
        self.assertEqual(1, report["scan"]["deferred_vertical_matches"])
        self.assertEqual(0, report["scan"]["redundant_horizontal"])
        self.assertEqual(
            {
                "boundary-policy": 1,
                "explicit-override": 1,
                "no-existing-filename-neighbor": 1,
                "vertical-runtime-contract-open": 1,
            },
            report["preserved"],
        )
        self.assertEqual((), removable_spans(self.root))

    def test_orphan_and_duplicate_boundary_metadata_fails_closed(self):
        self.write(
            "maps/orphan",
            self.map_source("celestial_boundary_2 discontinuous\n"),
        )
        self.write(
            "maps/world_1_0",
            self.map_source(
                "tile_path_2 /world_2_0\n"
                "tile_path_2 /world_2_0\n"
                "celestial_boundary_2 continuous\n"
            ),
        )
        self.write("maps/world_2_0", self.map_source())

        report = audit(self.root)

        self.assertFalse(report["ok"])
        self.assertEqual(
            {
                "duplicate-tile-path",
                "orphan-celestial-boundary",
            },
            {item["code"] for item in report["diagnostics"]},
        )
        self.assertEqual((), removable_spans(self.root))


if __name__ == "__main__":
    unittest.main()
