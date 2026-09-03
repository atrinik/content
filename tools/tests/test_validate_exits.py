"""Focused tests for deterministic authored-exit validation."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.validate_exits import _load_archetypes, _map_record, validate


class ValidateExitsTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        (self.root / "arch").mkdir()
        (self.root / "maps").mkdir()

        self.write(
            "arch/exit.arc",
            """Object exit
type 66
hp -1
sp -1
end
Object inherited_exit
other_arch exit
end
Object tiled_exit
type 66
last_heal 9
xrays 0
end
Object auto_exit
type 66
sub_type 1
end
Object shop_mat
type 66
sub_type 255
end
Object floor
type 71
is_floor 1
terrain_type 1
end
Object wall
type 77
no_pass 1
end
""",
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def write(self, relative_path: str, contents: str):
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
        return path

    @staticmethod
    def map_source(
        width: int, height: int, body: str = "", header: str = ""
    ) -> str:
        return "arch map\nwidth {}\nheight {}\n{}end\n{}".format(
            width, height, header, body
        )

    @staticmethod
    def object_source(name: str, x: int, y: int, extra: str = "") -> str:
        return "arch {}\nx {}\ny {}\n{}end\n".format(name, x, y, extra)

    def test_valid_forms_and_adjacent_fallback(self):
        target_objects = "".join(
            self.object_source("floor", x, y)
            for x in range(3)
            for y in range(3)
        )
        source_objects = (
            self.object_source("exit", 0, 0, "slaying /target\nhp 1\nsp 1\n")
            + self.object_source("exit", 0, 1, "hp 1\nsp 1\n")
            + self.object_source("tiled_exit", 1, 1)
            + self.object_source("auto_exit", 0, 2)
            + self.object_source("auto_exit", 2, 2)
            + self.object_source("shop_mat", 0, 2)
            + self.object_source("shop_mat", 2, 2)
        )
        source_objects += target_objects
        self.write(
            "maps/source",
            self.map_source(
                3,
                3,
                source_objects,
                header="tile_path_9 /target\n",
            ),
        )
        self.write("maps/target", self.map_source(3, 3, target_objects))

        report = validate(self.root)

        self.assertTrue(report["ok"])
        self.assertEqual([], report["diagnostics"])
        self.assertEqual(
            {
                "explicit": 1,
                "same-map": 1,
                "tiled": 1,
                "automatic-link": 2,
                "shop-mat": 2,
            },
            report["scan"]["forms"],
        )

    def test_other_arch_inheritance_keeps_exit_contract(self):
        target_objects = "".join(
            self.object_source("floor", x, y)
            for x in range(2)
            for y in range(2)
        )
        self.write(
            "maps/source",
            self.map_source(
                2,
                2,
                self.object_source(
                    "inherited_exit", 0, 0, "slaying /target\nhp 0\nsp 0\n"
                ),
            ),
        )
        self.write("maps/target", self.map_source(2, 2, target_objects))

        report = validate(self.root)

        self.assertTrue(report["ok"])
        self.assertEqual(1, report["scan"]["forms"]["explicit"])

    def test_filename_links_match_classic_and_resolve_edge_stairs(self):
        self.write(
            "maps/world_5_5",
            self.map_source(
                3,
                3,
                self.object_source("exit", 1, 2, "last_heal 3\n"),
            ),
        )
        self.write(
            "maps/world_5_6",
            self.map_source(
                3,
                3,
                self.object_source("floor", 1, 2),
                header="celestial_schema 1\n",
            ),
        )
        self.write("maps/world_5_5_1", self.map_source(3, 3))

        self.write(
            "maps/world_4_4",
            self.map_source(
                3,
                3,
                self.object_source("exit", 1, 2, "last_heal 3\n"),
            ),
        )

        self.write(
            "maps/world_3_3",
            self.map_source(
                3,
                3,
                self.object_source("exit", 1, 2, "last_heal 3\n"),
                header="tile_path_3 /override\n",
            ),
        )
        self.write(
            "maps/override",
            self.map_source(3, 3, self.object_source("floor", 1, 2)),
        )
        self.write(
            "maps/world_3_4",
            self.map_source(3, 3, self.object_source("wall", 1, 2)),
        )

        self.write(
            "maps/world_1_50",
            self.map_source(
                24,
                24,
                self.object_source(
                    "exit",
                    19,
                    23,
                    "last_heal 10\nxrays 1\ndirection 5\n",
                ),
                header="tile_path_10 /world_1_50_-1\n",
            ),
        )
        self.write("maps/world_1_50_-1", self.map_source(24, 24))
        self.write(
            "maps/world_1_51_-1",
            self.map_source(24, 24, self.object_source("floor", 19, 0)),
        )

        self.write(
            "maps/world_2_47",
            self.map_source(
                24,
                24,
                self.object_source(
                    "exit",
                    0,
                    15,
                    "last_heal 10\nxrays 1\ndirection 7\n",
                ),
                header="tile_path_10 /world_2_47_-1\n",
            ),
        )
        self.write("maps/world_2_47_-1", self.map_source(24, 24))
        self.write(
            "maps/world_1_47_-1",
            self.map_source(24, 24, self.object_source("floor", 23, 15)),
        )

        archetypes, _, _ = _load_archetypes(self.root)
        derived = _map_record(
            self.root, self.root / "maps/world_5_5", archetypes
        )
        self.assertEqual("/world_5_6", derived.links[3])
        self.assertEqual("/world_5_5_1", derived.links[9])
        missing = _map_record(
            self.root, self.root / "maps/world_4_4", archetypes
        )
        self.assertNotIn(3, missing.links)
        overridden = _map_record(
            self.root, self.root / "maps/world_3_3", archetypes
        )
        self.assertEqual("/override", overridden.links[3])

        report = validate(self.root)

        self.assertTrue(report["ok"])
        self.assertEqual([], report["diagnostics"])
        self.assertEqual(4, report["scan"]["forms"]["tiled"])
        self.assertGreaterEqual(report["excluded"]["unresolved"], 1)

    def test_automatic_link_matches_any_exit_type_peer(self):
        self.write(
            "arch/explicit_peer.arc",
            """Object explicit_peer
type 66
sub_type 42
slaying /target
hp 0
sp 0
end
""",
        )
        target_objects = "".join(
            self.object_source("floor", x, y)
            for x in range(2)
            for y in range(2)
        )
        self.write(
            "maps/source",
            self.map_source(
                2,
                2,
                self.object_source("auto_exit", 0, 0, "sub_type 42\n")
                + self.object_source("explicit_peer", 1, 0)
                + target_objects,
            ),
        )
        self.write("maps/target", self.map_source(2, 2, target_objects))

        report = validate(self.root)

        self.assertTrue(report["ok"])
        self.assertEqual(0, report["excluded"]["automatic-without-peer"])

    def test_invalid_forms_report_reason_and_source(self):
        self.write(
            "maps/source",
            self.map_source(
                3,
                3,
                self.object_source("tiled_exit", 1, 1)
                + self.object_source(
                    "exit", 0, 0, "slaying /missing\nhp 1\nsp 1\n"
                )
                + self.object_source(
                    "exit", 0, 1, "slaying /roof\nhp 99\nsp 99\n"
                ),
                header="tile_path_9 /roof\n",
            ),
        )
        self.write(
            "maps/roof",
            self.map_source(
                3,
                3,
                "".join(self.object_source("wall", x, y) for x in range(3) for y in range(3)),
            ),
        )

        first = validate(self.root)
        second = validate(self.root)

        self.assertEqual(first, second)
        self.assertFalse(first["ok"])
        self.assertEqual(3, len(first["diagnostics"]))
        self.assertEqual(
            {
                "invalid-destination-coordinates",
                "missing-target-map",
                "no-usable-landing",
            },
            {item["reason_code"] for item in first["diagnostics"]},
        )
        self.assertTrue(
            any(
                item["source"]["path"] == "maps/source"
                and item["source"]["coordinate"] == {"x": 1, "y": 1}
                and item["exit_form"] == "tiled"
                for item in first["diagnostics"]
            )
        )

    def test_baseline_approves_exact_findings_and_rejects_new_findings(self):
        self.write(
            "maps/source",
            self.map_source(
                2,
                2,
                self.object_source(
                    "exit", 0, 0, "slaying /missing\nhp 0\nsp 0\n"
                ),
            ),
        )
        initial = validate(self.root)
        baseline_path = self.root / "baseline.json"
        baseline_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "authored-exit-validation-baseline",
                    "finding_ids": [initial["diagnostics"][0]["id"]],
                }
            ),
            encoding="utf-8",
        )
        approved = validate(self.root, baseline_path)
        self.assertTrue(approved["ok"])
        self.assertEqual([], approved["unapproved_diagnostics"])

        self.write(
            "maps/source",
            self.map_source(
                2,
                2,
                self.object_source(
                    "exit", 0, 0, "slaying /missing\nhp 0\nsp 0\n"
                )
                + self.object_source(
                    "exit", 1, 1, "slaying /also-missing\nhp 0\nsp 0\n"
                ),
            ),
        )
        changed = validate(self.root, baseline_path)
        self.assertFalse(changed["ok"])
        self.assertEqual(1, len(changed["unapproved_diagnostics"]))

    def test_dynamic_and_unresolved_forms_are_explicitly_excluded(self):
        self.write(
            "maps/source",
            self.map_source(
                1,
                1,
                self.object_source("exit", 0, 0, "slaying /random/foo\n")
                + self.object_source("exit", 0, 0)
                + self.object_source("tiled_exit", 0, 0),
            ),
        )
        report = validate(self.root)
        self.assertTrue(report["ok"])
        self.assertEqual(1, report["excluded"]["dynamic"])
        self.assertGreaterEqual(report["excluded"]["unresolved"], 1)


if __name__ == "__main__":
    unittest.main()
