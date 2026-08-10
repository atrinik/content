"""Tests for the read-only world content audit."""

import json
import struct
import tempfile
import unittest
from pathlib import Path

from tools import light_review_evidence as evidence_tools
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
                    "schema_version": 4,
                    "review_method": "test semantic and rendered inspection",
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
                        }
                    },
                    "toggle_states": {},
                    "context_checks": {
                        check: {
                            "status": "pass",
                            "views": ["smooth-scene", "discrete-scene"],
                            "rationale": "Compared the scene in both lighting modes.",
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
        review_path.write_text(json.dumps(review))
        report = audit.light_inventory()
        evidence_dir = self.root / "maps/light-source-evidence"
        evidence_dir.mkdir()
        smooth = evidence_dir / "smooth.png"
        discrete = evidence_dir / "discrete.png"
        evidence_tools.write_png(smooth, 1, 1, b"\x00\x00\x00")
        evidence_tools.write_png(discrete, 1, 1, b"\x00\x00\x00")
        image = smooth.read_bytes()
        evidence = {
            "schema_version": 2,
            "render_context": {
                "content_commit": "1" * 40,
                "classic_client_commit": "2" * 40,
                "classic_server_commit": "4" * 40,
                "resources_commit": "3" * 40,
                "content_source": "https://github.com/atrinik/content/tree/" + "1" * 40,
                "classic_client_source": (
                    "https://github.com/atrinik/classic/tree/" + "2" * 40
                ),
                "classic_server_source": (
                    "https://github.com/atrinik/classic/tree/" + "4" * 40
                ),
                "resources_source": "https://github.com/atrinik/resources/tree/" + "3" * 40,
                "inventory_sha256": audit._inventory_semantic_sha256(report),
                "runtime_content_sha256": audit._runtime_content_sha256(),
                "profile": "test-light-review",
                "command": "test Classic client screenshot command",
                "settings": "seventeen by seventeen viewport with frozen lighting modes",
            },
            "sheets": {
                "smooth": {
                    "artifact": "maps/light-source-evidence/smooth.png",
                    "sha256": audit.hashlib.sha256(smooth.read_bytes()).hexdigest(),
                    "columns": 1,
                    "rows": 1,
                    "pixel_width": 1,
                    "pixel_height": 1,
                    "mode": "smooth",
                },
                "discrete": {
                    "artifact": "maps/light-source-evidence/discrete.png",
                    "sha256": audit.hashlib.sha256(discrete.read_bytes()).hexdigest(),
                    "columns": 1,
                    "rows": 1,
                    "pixel_width": 1,
                    "pixel_height": 1,
                    "mode": "discrete",
                },
            },
            "views": [
                {
                    "id": "smooth-scene",
                    "map": "maps/scene",
                    "map_semantic_sha256": report["maps"][0]["semantic_sha256"],
                    "x": 4,
                    "y": 5,
                    "sheet": "smooth",
                    "tile": 0,
                    "mode": "smooth",
                    "capture_sha256": "5" * 64,
                    "content_commit": "1" * 40,
                },
                {
                    "id": "discrete-scene",
                    "map": "maps/scene",
                    "map_semantic_sha256": report["maps"][0]["semantic_sha256"],
                    "x": 4,
                    "y": 5,
                    "sheet": "discrete",
                    "tile": 0,
                    "mode": "discrete",
                    "capture_sha256": "6" * 64,
                    "content_commit": "1" * 40,
                },
            ],
            "representative_checks": {
                check: {
                    "views": ["smooth-scene", "discrete-scene"],
                    "rationale": "Compared the scene in both lighting modes.",
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
            "active_states": {},
        }
        self.write("maps/light-source-evidence/manifest.json", json.dumps(evidence))

        self.assertEqual(
            {
                "archetypes": 2,
                "artifacts": 1,
                "color_sources": 2,
                "toggle_states": 0,
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

        smooth.write_bytes(
            b"\x89PNG\r\n\x1a\n"
            + evidence_tools._chunk(
                b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
            )
            + evidence_tools._chunk(b"IEND", b"")
        )
        errors = audit.validate_light_inventory(report)
        self.assertTrue(
            any("smooth is not a valid image" in error for error in errors), errors
        )
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
        smooth.write_bytes(b"changed evidence")
        self.assertIn(
            "light-source evidence sheet smooth artifact hash changed",
            audit.validate_light_inventory(audit.light_inventory()),
        )

        smooth.write_bytes(image)
        smooth.unlink()
        self.assertIn(
            "light-source evidence sheet smooth artifact is missing",
            audit.validate_light_inventory(audit.light_inventory()),
        )
        smooth.write_bytes(image)

        evidence_path = evidence_dir / "manifest.json"
        broken_evidence = json.loads(evidence_path.read_text())
        broken_evidence["render_context"]["content_commit"] = "not-a-commit"
        broken_evidence["render_context"]["inventory_sha256"] = "0" * 64
        broken_evidence["sheets"]["smooth"]["pixel_width"] = 2
        broken_evidence["views"][0]["x"] = 100
        evidence_path.write_text(json.dumps(broken_evidence))
        evidence_errors = audit.validate_light_inventory(audit.light_inventory())
        self.assertIn("light-source evidence needs a content_commit SHA", evidence_errors)
        self.assertIn(
            "light-source evidence inventory changed since rendered review",
            evidence_errors,
        )
        self.assertIn(
            "light-source evidence sheet smooth dimensions changed",
            evidence_errors,
        )
        self.assertIn(
            "map maps/scene emitter light2 at 4,5 lacks smooth runtime evidence",
            evidence_errors,
        )
        evidence_path.write_text(json.dumps(evidence))

        scene_path = self.root / "maps/scene"
        scene_source = scene_path.read_text()
        scene_path.write_text(scene_source + "# runtime tree changed\n")
        self.assertIn(
            "light-source evidence runtime content changed since rendered review",
            audit.validate_light_inventory(audit.light_inventory()),
        )
        scene_path.write_text(scene_source)

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
face lamp.101
animation lamp
type 74
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
x 3
y 4
end
""",
        )

        report = audit.light_inventory()

        source = report["archetypes"][0]
        self.assertEqual("toggle-active", source["activation"])
        self.assertEqual(5, source["radius"])
        self.assertEqual("last_sp", source["radius_source"]["field"])
        emitter = report["maps"][0]["emitters"][0]
        self.assertEqual("toggle-active", emitter["activation"])
        self.assertEqual((3, 4), (emitter["x"], emitter["y"]))
        self.assertEqual("archetype", emitter["radius_source"]["kind"])
        self.assertEqual("light_color", emitter["color_source"]["field"])
        self.assertEqual("lamp", emitter["animation"])
        self.assertEqual(1, len(report["toggle_states"]))
        self.assertEqual(
            {"archetype", "map"},
            {row["kind"] for row in report["toggle_states"][0]["sources"]},
        )

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

        self.assertIn("light-source review must use schema_version 4", errors)
        self.assertIn("light-source review needs a concise review_method", errors)
        self.assertIn("light-source review archetypes must be an object", errors)
        self.assertIn("1 effective light sources remain unreviewed", errors)


if __name__ == "__main__":
    unittest.main()
