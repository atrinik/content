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

    def test_light_inventory_resolves_inheritance_overrides_and_reviews(self):
        self.write(
            "arch/lights.arc",
            """Object colored_lamp
name colored lamp
face lamp.101
animation lamp
glow_radius 4
light_color ff8040
end
Object light2
name light
face light_bulb_2.111
glow_radius 2
no_pick 1
sys_object 1
type 78
end
Object inert
name inert
animation inert
light_color 4060ff
end
""",
        )
        self.write(
            "arch/lights.art",
            """artifact glowing_reward
def_arch inert
Object
glow_radius 1
face reward.101
end
""",
        )
        self.write(
            "maps/scene",
            """arch map
name Reviewed Scene
region sample
darkness 3
end
arch colored_lamp
x 2
y 3
end
arch light2
x 4
y 5
end
arch inert
x 6
y 7
face orb.101
animation orb
glow_radius 3
light_color 4060ff
end
""",
        )
        review_path = self.write(
            "maps/light-source-review.json",
            json.dumps(
                {
                    "schema_version": 6,
                    "review_method": "test semantic inventory and art-direction review",
                    "palette": {
                        "4060ff": {"rationale": "focused blue magic"},
                        "ff8040": {"rationale": "warm lamp flame"},
                    },
                    "archetypes": {
                        "colored_lamp": {
                            "uncolored_disposition": "neutral",
                            "rationale": "Warm visible lamp flame.",
                        },
                        "light2": {
                            "uncolored_disposition": "neutral",
                            "rationale": "Neutral invisible composition light.",
                        },
                    },
                    "artifacts": {
                        "glowing_reward": {
                            "uncolored_disposition": "neutral",
                            "rationale": "Neutral reward glow preserves its art.",
                        },
                    },
                    "color_sources": {
                        "colored_lamp": {
                            "rationale": "Warm orange follows this lamp's flame art."
                        },
                        "inert": {
                            "rationale": "Blue follows the inherited inert crystal art."
                        },
                    },
                    "toggle_states": {},
                    "fixture_groups": {
                        "warm-fixtures": {
                            "archetypes": ["colored_lamp"],
                            "default_radii": {"colored_lamp": 4},
                            "expected_color": "ff8040",
                            "expected_maps": 1,
                            "expected_placements": {"colored_lamp": 1},
                            "intentional_non_emitters": {},
                            "checks": ["overlap"],
                            "rationale": "Tracks every warm fixture placement.",
                        }
                    },
                    "context_checks": {
                        check: {
                            "status": "pass",
                            "rationale": "The reviewed scene preserves this lighting relationship.",
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
                    "maps": {
                        "maps/scene": {
                            "uncolored_disposition": "neutral",
                            "rationale": "Rendered room keeps neutral fill around colored accents.",
                            "visible_neutral": {},
                            "art_overrides": {
                                "14": "Blue orb art intentionally overrides the inert base."
                            },
                        }
                    },
                }
            ),
        )
        contract_path = self.write(
            "maps/light-source-fixture-contract.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "fixture_groups": {
                        "warm-fixtures": {
                            "archetypes": ["colored_lamp"],
                            "checks": ["overlap"],
                        }
                    },
                }
            ),
        )

        report = audit.light_inventory()
        review = json.loads(review_path.read_text())
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
        review_path.write_text(json.dumps(review))
        report = audit.light_inventory()

        self.assertEqual(
            {
                "archetypes": 2,
                "artifacts": 1,
                "color_sources": 2,
                "toggle_states": 0,
                "fixture_groups": 1,
                "fixture_placements": 1,
                "maps": 1,
                "map_instances": 3,
                "visible_map_instances": 2,
                "invisible_map_instances": 1,
                "explicit_color": 4,
                "intentional_neutral": 2,
                "unreviewed": 0,
                "colors": ["4060ff", "ff8040"],
            },
            report["summary"],
        )
        self.assertEqual([], audit.validate_light_inventory(report))

        fixture_group = report["fixture_groups"][0]
        self.assertEqual("warm-fixtures", fixture_group["id"])
        self.assertEqual(["colored_lamp"], fixture_group["archetypes"])
        self.assertEqual(1, fixture_group["maps"])
        self.assertEqual("maps/scene:6", fixture_group["placements"][0]["source_id"])
        self.assertNotIn("views", review["fixture_groups"]["warm-fixtures"])

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

        scene = report["maps"][0]
        self.assertEqual("3", scene["darkness"])
        self.assertEqual("intentional-neutral", scene["emitters"][1]["disposition"])
        self.assertFalse(scene["emitters"][1]["visible"])
        artifact = report["artifacts"][0]
        self.assertTrue(artifact["visible"])
        self.assertEqual("reward.101", artifact["face"])
        self.assertEqual("4060ff", artifact["color"])
        self.assertEqual("inert", artifact["color_source"]["object"])
        self.assertEqual("artifact", artifact["radius_source"]["kind"])
        self.assertEqual("glow_radius", artifact["radius_source"]["field"])
        lamp = report["archetypes"][0]
        self.assertEqual("glow_radius", lamp["radius_source"]["field"])
        self.assertEqual(5, lamp["radius_source"]["field_line"])
        self.assertEqual("archetype", scene["emitters"][0]["color_source"]["kind"])
        override = scene["emitters"][2]
        self.assertEqual("map", override["radius_source"]["kind"])
        self.assertEqual("maps/scene", override["radius_source"]["path"])
        self.assertEqual("light_color", override["color_source"]["field"])
        self.assertEqual("orb", override["animation"])
        self.assertEqual("map", override["animation_source"]["kind"])
        self.assertEqual(["face", "animation"], override["art_override_fields"])

        broken_report = audit.light_inventory()
        broken_report["maps"][0]["emitters"][0]["radius_source"] = None
        self.assertIn(
            "map emitter maps/scene:6 has invalid radius provenance",
            audit.validate_light_inventory(broken_report),
        )

        review = json.loads(review_path.read_text())
        review["context_checks"]["overlap"]["status"] = "not-applicable"
        review_path.write_text(json.dumps(review))
        self.assertIn(
            "contextual lighting check overlap must record pass",
            audit.validate_light_inventory(audit.light_inventory()),
        )
        review["context_checks"]["overlap"]["status"] = "pass"
        review_path.write_text(json.dumps(review))

        scene_path = self.root / "maps/scene"
        scene_source = scene_path.read_text()
        scene_path.write_text(scene_source + "# semantic source changed\n")
        self.assertIn(
            "map maps/scene changed since its lighting review",
            audit.validate_light_inventory(audit.light_inventory()),
        )
        scene_path.write_text(scene_source)

        archetype_path = self.root / "arch/lights.arc"
        archetype_source = archetype_path.read_text()
        archetype_path.write_text(
            archetype_source.replace("glow_radius 4", "glow_radius 5")
        )
        self.assertIn(
            "archetype colored_lamp changed since its lighting review",
            audit.validate_light_inventory(audit.light_inventory()),
        )
        archetype_path.write_text(archetype_source)

        scene_path.write_text(
            scene_source.replace("x 6\n", "x 8\n").replace(
                "light_color 4060ff\n", ""
            )
        )
        self.assertIn(
            "map maps/scene changed since its lighting review",
            audit.validate_light_inventory(audit.light_inventory()),
        )

    def test_light_inventory_preserves_black_and_marks_faceless_emitters_invisible(self):
        self.write(
            "arch/lights.arc",
            """Object black_light
face black_light.101
glow_radius 2
light_color 000000
end
Object faceless_satellite
glow_radius 2
end
""",
        )
        self.write(
            "maps/coordinates",
            """arch map
name Coordinate Defaults
end
arch black_light
end
arch black_light
x 2
end
arch black_light
y 3
end
arch inert
x 7
y 8
arch black_light
end
end
""",
        )

        report = audit.light_inventory()
        rows = {row["id"]: row for row in report["archetypes"]}

        self.assertEqual("000000", rows["black_light"]["color"])
        self.assertEqual("explicit-color", rows["black_light"]["disposition"])
        self.assertFalse(rows["faceless_satellite"]["visible"])
        self.assertEqual(
            [(0, 0), (2, 0), (0, 3), (7, 8)],
            [(row["x"], row["y"]) for row in report["maps"][0]["emitters"]],
        )

    def test_light_inventory_includes_toggle_active_type_74_state(self):
        self.write(
            "arch/toggle.arc",
            """Object toggle_lamp
face lamp_lit.101
animation lamp_lit
type 74
anim_speed 4
last_sp 5
light_color ffc080
end
Object toggle_lamp_unlit
face lamp_unlit.101
animation lamp_unlit
type 74
anim_speed 4
last_sp 5
light_color ffc080
end
""",
        )
        self.write(
            "maps/toggle",
            """arch map
name Toggle Lamp
end
arch toggle_lamp
face lamp_unlit.101
animation lamp_unlit
x 3
y 4
end
""",
        )
        self.write(
            "arch/toggle.art",
            """artifact toggle_prize
def_arch toggle_lamp
Object
face prize_unlit.101
animation prize_unlit
end
""",
        )

        report = audit.light_inventory()

        source = report["archetypes"][0]
        self.assertEqual("toggle-active", source["activation"])
        self.assertEqual(5, source["radius"])
        self.assertEqual("last_sp", source["radius_source"]["field"])
        self.assertEqual("toggle_lamp", source["activation_archetype"])
        self.assertEqual("lamp_lit.101", source["active_face"])
        self.assertEqual("lamp_lit", source["active_animation"])
        self.assertEqual("archetype", source["active_animation_source"]["kind"])
        emitter = report["maps"][0]["emitters"][0]
        self.assertEqual("toggle-active", emitter["activation"])
        self.assertEqual((3, 4), (emitter["x"], emitter["y"]))
        self.assertEqual("archetype", emitter["radius_source"]["kind"])
        self.assertEqual("light_color", emitter["color_source"]["field"])
        self.assertEqual("lamp_unlit.101", emitter["face"])
        self.assertEqual("lamp_unlit", emitter["animation"])
        self.assertEqual("lamp_lit.101", emitter["active_face"])
        self.assertEqual("lamp_lit", emitter["active_animation"])
        self.assertEqual("archetype", emitter["active_animation_source"]["kind"])
        self.assertEqual("map", emitter["activation_archetype_source"]["kind"])
        self.assertEqual("arch", emitter["activation_archetype_source"]["field"])
        artifact = report["artifacts"][0]
        self.assertEqual("prize_unlit.101", artifact["face"])
        self.assertEqual("prize_unlit", artifact["animation"])
        self.assertEqual("lamp_lit.101", artifact["active_face"])
        self.assertEqual("lamp_lit", artifact["active_animation"])
        self.assertEqual(
            "artifact", artifact["activation_archetype_source"]["kind"]
        )
        self.assertEqual(
            "def_arch", artifact["activation_archetype_source"]["field"]
        )
        self.assertEqual(2, len(report["toggle_states"]))
        states = {
            row["activation_archetype"]: row for row in report["toggle_states"]
        }
        active_lamp = states["toggle_lamp"]
        self.assertEqual("lamp_lit.101", active_lamp["face"])
        self.assertEqual("lamp_lit", active_lamp["animation"])
        self.assertEqual("archetype", active_lamp["animation_source"]["kind"])
        self.assertEqual(
            {"archetype", "artifact", "map"},
            {row["kind"] for row in active_lamp["sources"]},
        )
        standalone = states["toggle_lamp_unlit"]
        self.assertEqual("lamp_unlit.101", standalone["face"])
        self.assertEqual("lamp_unlit", standalone["animation"])
        self.assertEqual(
            [{"kind": "archetype", "id": "toggle_lamp_unlit"}],
            standalone["sources"],
        )

        clean_errors = audit.validate_light_inventory(report)
        self.assertFalse(
            [error for error in clean_errors if "provenance" in error],
            clean_errors,
        )
        broken = json.loads(json.dumps(report))
        broken["maps"][0]["emitters"][0]["active_animation_source"] = None
        broken["toggle_states"][0]["activation_archetype"] = None
        errors = audit.validate_light_inventory(broken)
        self.assertIn(
            "map emitter maps/toggle:4 has invalid active_animation provenance",
            errors,
        )
        self.assertTrue(
            any(error.endswith("lacks an activation archetype") for error in errors),
            errors,
        )

    def test_allowed_none_artifact_is_a_registered_runtime_archetype(self):
        self.write(
            "arch/toggle.arc",
            """Object toggle_lamp
face lamp_lit.101
animation lamp_lit
type 74
anim_speed 4
last_sp 5
light_color ffc080
end
""",
        )
        self.write(
            "maps/quest.art",
            """Allowed none
chance 1
artifact quest_lamp
def_arch toggle_lamp
Object
face quest_lamp.101
animation quest_lamp
end
""",
        )
        self.write(
            "maps/quest",
            """arch map
name Quest Lamp
end
arch quest_lamp
x 6
y 7
end
""",
        )

        report = audit.light_inventory()

        artifact = report["artifacts"][0]
        self.assertEqual("quest_lamp", artifact["runtime_archetype"])
        self.assertEqual("artifact", artifact["runtime_archetype_source"]["field"])
        self.assertEqual("quest_lamp", artifact["activation_archetype"])
        self.assertEqual("quest_lamp.101", artifact["active_face"])
        emitter = report["maps"][0]["emitters"][0]
        self.assertEqual("quest_lamp", emitter["archetype"])
        self.assertEqual((6, 7), (emitter["x"], emitter["y"]))
        self.assertEqual("artifact", emitter["face_source"]["kind"])
        self.assertEqual("quest_lamp", emitter["activation_archetype"])
        self.assertEqual("quest_lamp.101", emitter["active_face"])
        state = next(
            row for row in report["toggle_states"]
            if row["activation_archetype"] == "quest_lamp"
        )
        self.assertEqual(
            {("artifact", "quest_lamp"), ("map", "maps/quest:4")},
            {(row["kind"], row["id"]) for row in state["sources"]},
        )

    def test_allowed_artifact_is_also_a_registered_map_archetype(self):
        self.write(
            "arch/toggle.arc",
            """Object toggle_lamp
face lamp_lit.101
animation lamp_lit
type 74
anim_speed 4
last_sp 5
light_color ffc080
end
""",
        )
        self.write(
            "maps/quest.art",
            """Allowed toggle_lamp
chance 1
artifact quest_lamp
def_arch toggle_lamp
Object
face quest_lamp.101
animation quest_lamp
end
""",
        )
        self.write(
            "maps/quest",
            """arch map
name Quest Lamp
end
arch quest_lamp
x 6
y 7
end
""",
        )

        report = audit.light_inventory()

        artifact = report["artifacts"][0]
        self.assertEqual("toggle_lamp", artifact["runtime_archetype"])
        self.assertEqual("def_arch", artifact["runtime_archetype_source"]["field"])
        self.assertEqual("toggle_lamp", artifact["activation_archetype"])
        self.assertEqual("lamp_lit.101", artifact["active_face"])

        emitter = report["maps"][0]["emitters"][0]
        self.assertEqual("quest_lamp", emitter["archetype"])
        self.assertEqual((6, 7), (emitter["x"], emitter["y"]))
        self.assertEqual("artifact", emitter["face_source"]["kind"])
        self.assertEqual("quest_lamp.101", emitter["face"])
        self.assertEqual("quest_lamp", emitter["activation_archetype"])
        self.assertEqual("quest_lamp.101", emitter["active_face"])
        self.assertEqual("artifact", emitter["active_face_source"]["kind"])
        self.assertEqual("map", emitter["activation_archetype_source"]["kind"])

        states = {
            row["activation_archetype"]: row for row in report["toggle_states"]
        }
        self.assertEqual(
            {
                ("archetype", "toggle_lamp"),
                ("artifact", "quest_lamp"),
            },
            {
                (row["kind"], row["id"])
                for row in states["toggle_lamp"]["sources"]
            },
        )
        self.assertEqual("lamp_lit.101", states["toggle_lamp"]["face"])
        self.assertEqual(
            [{"kind": "map", "id": "maps/quest:4"}],
            states["quest_lamp"]["sources"],
        )
        self.assertEqual("quest_lamp.101", states["quest_lamp"]["face"])

    def test_light_review_check_rejects_missing_baseline_rows(self):
        self.write(
            "arch/light.arc",
            """Object light1
glow_radius 1
sys_object 1
type 78
end
""",
        )

        report = audit.light_inventory()
        errors = audit.validate_light_inventory(report)

        self.assertIn("light-source review must use schema_version 6", errors)
        self.assertIn("light-source review needs a concise review_method", errors)
        self.assertIn("light-source review archetypes must be an object", errors)
        self.assertIn("1 effective light sources remain unreviewed", errors)


if __name__ == "__main__":
    unittest.main()
