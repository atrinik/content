"""Tests for the read-only world content audit."""

import json
import tempfile
import unittest
from pathlib import Path

from tools import world_content_audit as audit


class WorldContentAuditTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.original_roots = (audit.ROOT, audit.MAP_ROOT, audit.ARCH_ROOT)
        audit.ROOT = self.root
        audit.MAP_ROOT = self.root / "maps"
        audit.ARCH_ROOT = self.root / "arch"
        audit.MAP_ROOT.mkdir()
        audit.ARCH_ROOT.mkdir()

    def tearDown(self):
        audit.ROOT, audit.MAP_ROOT, audit.ARCH_ROOT = self.original_roots
        self.temporary_directory.cleanup()

    def write(self, relative_path, contents):
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
        return path

    def test_inventories_are_structured_and_json_serializable(self):
        self.write(
            "arch/monsters.arc",
            """Object sample_monster
name sample monster
type 80
level 3
end
""",
        )
        self.write(
            "arch/items.art",
            """artifact sample_artifact
def_arch sample_monster
chance 10
Object
name sample reward
end
""",
        )
        self.write(
            "maps/regions.reg",
            """region sample
name Sample Region
msg
Sample description.
endmsg
end
""",
        )
        self.write(
            "maps/world_2_1",
            """arch map
name Sample Map
region sample
width 24
height 24
outdoor 1
end
arch sample_monster
name named sample
x 4
y 5
end
""",
        )
        self.write(
            "maps/interfaces/quests/sample/quest.xml",
            """<dialog><quest name="sample"><part name="first" uid="1">
<info>Find the sample.</info><kill arch="sample_monster" />
</part></quest></dialog>
""",
        )

        report = {
            "quests": audit.quest_inventory(),
            "regions": audit.region_registry(),
            "artifacts": audit.artifact_inventory(),
            "world": audit.world_inventory(),
        }

        self.assertEqual("sample", report["quests"][0]["name"])
        self.assertEqual("Sample description.", report["regions"][0]["msg"])
        self.assertEqual("sample_artifact", report["artifacts"][0]["id"])
        self.assertEqual([2, 1, 0], report["world"]["maps"][0]["world_coord"])
        self.assertEqual("named sample", report["world"]["named_monsters"][0]["name"])
        json.dumps(report)

    def test_map_discovery_is_deterministic_and_ignores_non_maps(self):
        later = self.write("maps/z_map", "arch map\nend\n")
        earlier = self.write("maps/a_map", "arch map\nend\n")
        self.write("maps/readme.txt", "not a map\n")

        self.assertEqual([earlier, later], audit.map_files())

    def test_light_inventory_enforces_reviewed_main_semantics(self):
        self.write(
            "arch/lights.arc",
            """Object warm_lamp
face lamp.101
glow_radius 4
light_color ffc080
end
Object neutral_fill
glow_radius 2
sys_object 1
type 78
end
Object alternate_fill
glow_radius 3
sys_object 1
type 78
end
""",
        )
        map_path = self.write(
            "maps/scene",
            """arch map
name Reviewed Scene
darkness 3
end
arch warm_lamp
x 2
y 3
end
arch neutral_fill
x 2
y 3
end
""",
        )
        contract_path = self.write(
            "maps/light-source-fixture-contract.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "fixture_groups": {
                        "warm-fixtures": {
                            "archetypes": ["warm_lamp"],
                            "checks": ["overlap"],
                            "same_tile_review": "exact",
                        }
                    },
                }
            ),
        )

        report = audit.light_inventory()
        review = {
            "schema_version": 7,
            "review_method": "Port the pinned Classic semantic review without claiming replacement rendering.",
            "source_review": {
                "branch": "1.x",
                "commit": "cdc6c57b0ef3d4739c99e846eb2054e4eafdce26",
                "pull_request": "https://github.com/atrinik/content/pull/67",
            },
            "runtime_verification": {
                "status": "unavailable",
                "rationale": "Replacement runtime adapters do not yet consume authored lighting.",
                "tracked_by": [
                    "https://github.com/atrinik/atrinik/issues/266",
                    "https://github.com/atrinik/atrinik/issues/269",
                    "https://github.com/atrinik/atrinik/issues/270",
                ],
            },
            "palette": {
                "ffc080": {
                    "rationale": "Warm amber follows the visible lamp flame."
                }
            },
            "archetypes": {
                "alternate_fill": {
                    "uncolored_disposition": "neutral",
                    "rationale": "The alternate invisible fill intentionally remains neutral.",
                },
                "warm_lamp": {
                    "uncolored_disposition": "neutral",
                    "rationale": "The explicit amber follows the visible lamp flame.",
                },
                "neutral_fill": {
                    "uncolored_disposition": "neutral",
                    "rationale": "The invisible fill intentionally remains neutral.",
                },
            },
            "artifacts": {},
            "color_sources": {
                "warm_lamp": {
                    "rationale": "The source owns the reviewed warm amber color."
                }
            },
            "toggle_states": {},
            "fixture_groups": {
                "warm-fixtures": {
                    "archetypes": ["warm_lamp"],
                    "default_radii": {"warm_lamp": 4},
                    "expected_color": "ffc080",
                    "expected_maps": 1,
                    "expected_placements": {"warm_lamp": 1},
                    "expected_emitting_overlaps": 1,
                    "intentional_non_emitters": {},
                    "intentional_same_tile_emitters": {
                        "maps/scene:2:3:warm_lamp:1": "The independent neutral fill deliberately shares the fixture tile."
                    },
                    "checks": ["overlap"],
                    "rationale": "Tracks every required warm fixture placement.",
                }
            },
            "maps": {
                "maps/scene": {
                    "uncolored_disposition": "neutral",
                    "rationale": "The inherited source decisions preserve this scene.",
                    "visible_neutral": {},
                    "art_overrides": {},
                }
            },
            "context_checks": {
                check: {
                    "status": "pass",
                    "rationale": "The pinned Classic review covers this contextual risk.",
                }
                for check in (
                    "overlap",
                    "linked-depth",
                    "horizontal-boundary",
                    "dark-interior",
                    "outdoor-transition",
                    "fog-roof",
                    "navigation",
                )
            },
        }
        for section, identity in (
            ("archetypes", "id"),
            ("artifacts", "id"),
            ("color_sources", "id"),
            ("toggle_states", "id"),
            ("maps", "path"),
        ):
            for row in report[section]:
                review[section][row[identity]]["semantic_sha256"] = row[
                    "semantic_sha256"
                ]
        review["fixture_groups"]["warm-fixtures"]["semantic_sha256"] = report[
            "fixture_groups"
        ][0]["semantic_sha256"]
        review_path = self.write(
            "maps/light-source-review.json", json.dumps(review)
        )

        report = audit.light_inventory()
        self.assertEqual(0, report["summary"]["unreviewed"])
        warm_row = next(row for row in report["archetypes"] if row["id"] == "warm_lamp")
        self.assertEqual("ffc080", warm_row["color"])
        self.assertEqual([], audit.validate_light_inventory(report))

        fixture_group = report["fixture_groups"][0]
        self.assertEqual("warm-fixtures", fixture_group["id"])
        self.assertEqual(["warm_lamp"], fixture_group["archetypes"])
        self.assertEqual(1, fixture_group["maps"])
        self.assertEqual(1, fixture_group["emitting_overlaps"])
        self.assertEqual("maps/scene:5", fixture_group["placements"][0]["source_id"])
        self.assertEqual(
            ["maps/scene:9"],
            [
                emitter["id"]
                for emitter in fixture_group["placements"][0][
                    "same_tile_emitters"
                ]
            ],
        )
        self.assertNotIn("views", review["fixture_groups"]["warm-fixtures"])

        original_map = map_path.read_text()
        map_path.write_text(
            original_map.replace("arch neutral_fill\n", "\narch neutral_fill\n")
        )
        replaced_same_tile_errors = audit.validate_light_inventory(
            audit.light_inventory()
        )
        self.assertIn(
            "fixture group warm-fixtures changed since review",
            replaced_same_tile_errors,
        )
        map_path.write_text(original_map)

        missing_same_tile = json.loads(review_path.read_text())
        del missing_same_tile["fixture_groups"]["warm-fixtures"][
            "intentional_same_tile_emitters"
        ]
        review_path.write_text(json.dumps(missing_same_tile))
        missing_same_tile_errors = audit.validate_light_inventory(
            audit.light_inventory()
        )
        self.assertIn(
            "fixture group warm-fixtures same-tile source dispositions changed",
            missing_same_tile_errors,
        )
        self.assertIn(
            "emitting fixture maps/scene:2:3:warm_lamp:1 has an accidental same-tile source",
            missing_same_tile_errors,
        )
        review_path.write_text(json.dumps(review))

        deleted_review = json.loads(review_path.read_text())
        del deleted_review["fixture_groups"]["warm-fixtures"]
        del deleted_review["context_checks"]["overlap"]
        review_path.write_text(json.dumps(deleted_review))
        deleted_report = audit.light_inventory()
        self.assertEqual(1, deleted_report["summary"]["fixture_placements"])
        deleted_errors = audit.validate_light_inventory(deleted_report)
        self.assertIn(
            "required fixture group warm-fixtures is missing from review",
            deleted_errors,
        )
        self.assertIn("unreviewed fixture group: warm-fixtures", deleted_errors)
        self.assertIn(
            "contextual lighting check overlap must record pass",
            deleted_errors,
        )
        review_path.write_text(json.dumps(review))
        self.assertTrue(contract_path.is_file())

        changed_overlap = json.loads(review_path.read_text())
        changed_overlap["fixture_groups"]["warm-fixtures"][
            "expected_emitting_overlaps"
        ] = 0
        review_path.write_text(json.dumps(changed_overlap))
        self.assertIn(
            "fixture group warm-fixtures emitting overlap count changed",
            audit.validate_light_inventory(audit.light_inventory()),
        )
        review_path.write_text(json.dumps(review))

        original_fixture_sha = fixture_group["semantic_sha256"]
        scene_path = self.root / "maps/scene"
        scene_path.write_text(
            scene_path.read_text().replace("arch neutral_fill", "arch alternate_fill")
        )
        swapped_report = audit.light_inventory()
        swapped_fixture = swapped_report["fixture_groups"][0]
        self.assertNotEqual(original_fixture_sha, swapped_fixture["semantic_sha256"])
        self.assertIn(
            "fixture group warm-fixtures changed since review",
            audit.validate_light_inventory(swapped_report),
        )
        scene_path.write_text(
            scene_path.read_text().replace("arch alternate_fill", "arch neutral_fill")
        )

        changed = json.loads(review_path.read_text())
        changed["archetypes"]["warm_lamp"]["semantic_sha256"] = "0" * 64
        review_path.write_text(json.dumps(changed))
        self.assertIn(
            "archetype warm_lamp changed since its lighting review",
            audit.validate_light_inventory(audit.light_inventory()),
        )

    def test_light_review_requires_replacement_runtime_boundary(self):
        self.write(
            "arch/light.arc",
            "Object light1\nglow_radius 1\nsys_object 1\ntype 78\nend\n",
        )

        errors = audit.validate_light_inventory(audit.light_inventory())

        self.assertIn("light-source review must use schema_version 7", errors)
        self.assertIn("light-source review must pin its Classic source review", errors)
        self.assertIn(
            "light-source review must record replacement runtime limits", errors
        )
        self.assertIn("light-source review needs a concise review_method", errors)
        self.assertIn("light-source review archetypes must be an object", errors)
        self.assertIn("1 effective light sources remain unreviewed", errors)


if __name__ == "__main__":
    unittest.main()
