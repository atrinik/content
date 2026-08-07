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


if __name__ == "__main__":
    unittest.main()
