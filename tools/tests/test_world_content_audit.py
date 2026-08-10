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
glow_radius 3
light_color 4060ff
end
""",
        )
        review_path = self.write(
            "maps/light-source-review.json",
            json.dumps(
                {
                    "schema_version": 2,
                    "review_method": "test semantic and rendered inspection",
                    "render_context": {
                        "content_commit": "1" * 40,
                        "classic_commit": "2" * 40,
                        "resources_commit": "3" * 40,
                        "profile": "test-light-review",
                        "command": "test worldmaker command",
                        "settings": "test pixel size and regional roots",
                    },
                    "rendered_batches": {
                        "sample-interior": {
                            "artifact": "sample.png",
                            "method": "test renderer",
                            "sha256": "0" * 64,
                        }
                    },
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
                        }
                    },
                    "maps": {
                        "maps/scene": {
                            "uncolored_disposition": "neutral",
                            "rationale": "Rendered room keeps neutral fill around colored accents.",
                            "rendered_batch": "sample-interior",
                            "visible_neutral": {},
                            "checks": [
                                "overlap",
                                "linked-depth",
                                "horizontal-boundary",
                                "dark-interior",
                                "outdoor-transition",
                                "fog-roof",
                                "navigation",
                            ],
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
            ("maps", "path"),
        ):
            for row in report[section]:
                review[section][row[identity]]["semantic_sha256"] = row[
                    "semantic_sha256"
                ]
        review_path.write_text(json.dumps(review))
        report = audit.light_inventory()

        self.assertEqual(
            {
                "archetypes": 2,
                "artifacts": 1,
                "maps": 1,
                "map_instances": 3,
                "visible_map_instances": 2,
                "invisible_map_instances": 1,
                "explicit_color": 3,
                "intentional_neutral": 3,
                "unreviewed": 0,
                "colors": ["4060ff", "ff8040"],
            },
            report["summary"],
        )
        self.assertEqual([], audit.validate_light_inventory(report))
        scene = report["maps"][0]
        self.assertEqual("3", scene["darkness"])
        self.assertEqual("intentional-neutral", scene["emitters"][1]["disposition"])
        self.assertFalse(scene["emitters"][1]["visible"])
        artifact = report["artifacts"][0]
        self.assertTrue(artifact["visible"])
        self.assertEqual("reward.101", artifact["face"])

        review = json.loads(review_path.read_text())
        review["maps"]["maps/scene"]["checks"] = None
        review_path.write_text(json.dumps(review))
        self.assertIn(
            "map maps/scene must record every contextual lighting check",
            audit.validate_light_inventory(audit.light_inventory()),
        )

        review["maps"]["maps/scene"]["checks"] = [
            "overlap",
            "linked-depth",
            "horizontal-boundary",
            "dark-interior",
            "outdoor-transition",
            "fog-roof",
            "navigation",
        ]
        review["rendered_batches"]["sample-interior"]["sha256"] = "invalid"
        review_path.write_text(json.dumps(review))
        self.assertIn(
            "rendered batch sample-interior needs an artifact SHA-256",
            audit.validate_light_inventory(audit.light_inventory()),
        )

        review["rendered_batches"]["sample-interior"]["sha256"] = "0" * 64
        review_path.write_text(json.dumps(review))
        archetype_path = self.root / "arch/lights.arc"
        archetype_source = archetype_path.read_text()
        archetype_path.write_text(archetype_source.replace("glow_radius 4", "glow_radius 5"))
        self.assertIn(
            "archetype colored_lamp changed since its lighting review",
            audit.validate_light_inventory(audit.light_inventory()),
        )
        archetype_path.write_text(archetype_source)

        scene_path = self.root / "maps/scene"
        scene_path.write_text(
            scene_path.read_text()
            .replace("x 6\n", "x 8\n")
            .replace("light_color 4060ff\n", "")
        )
        errors = audit.validate_light_inventory(audit.light_inventory())
        self.assertIn(
            "map maps/scene changed since its lighting review",
            errors,
        )
        self.assertIn(
            "map maps/scene needs a visible-neutral rationale for inert",
            errors,
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

        report = audit.light_inventory()
        rows = {row["id"]: row for row in report["archetypes"]}

        self.assertEqual("000000", rows["black_light"]["color"])
        self.assertEqual("explicit-color", rows["black_light"]["disposition"])
        self.assertFalse(rows["faceless_satellite"]["visible"])

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

        self.assertIn("light-source review must use schema_version 2", errors)
        self.assertIn("light-source review needs a concise review_method", errors)
        self.assertIn("light-source review archetypes must be an object", errors)
        self.assertIn("1 effective light sources remain unreviewed", errors)


if __name__ == "__main__":
    unittest.main()
