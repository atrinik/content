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
""",
        )
        self.write(
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
x 4
y 5
end
""",
        )

        report = audit.light_inventory()
        review = {
            "schema_version": 5,
            "review_method": "Port the pinned Classic semantic review without claiming replacement rendering.",
            "source_review": {
                "branch": "1.x",
                "commit": "958b557650252518b9ea2850200920d07c879bd2",
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
        review_path = self.write(
            "maps/light-source-review.json", json.dumps(review)
        )

        report = audit.light_inventory()
        self.assertEqual(0, report["summary"]["unreviewed"])
        self.assertEqual("ffc080", report["archetypes"][1]["color"])
        self.assertEqual([], audit.validate_light_inventory(report))

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

        self.assertIn("light-source review must use schema_version 5", errors)
        self.assertIn("light-source review must pin its Classic source review", errors)
        self.assertIn(
            "light-source review must record replacement runtime limits", errors
        )
        self.assertIn("1 effective light sources remain unreviewed", errors)


if __name__ == "__main__":
    unittest.main()
