"""Tests for the authored-content identity catalog."""

import contextlib
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.build_runtime import build as build_runtime
from tools.content_catalog import ContentCatalog, ContentId, load_catalog
from tools.content_catalog.__main__ import main as catalog_main


class ContentCatalogTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        (self.root / "arch").mkdir()
        (self.root / "maps" / "interfaces" / "quests" / "sample_quest").mkdir(
            parents=True
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def write(self, relative_path, contents):
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
        return path

    def create_valid_tree(self):
        self.write(
            "arch/objects.arc",
            """Object base
type 1
end
Object spell_minor_healing
type 29
end
Object skill_literacy
type 43
end
Object wand
type 109
end
Object sample_monster_variant
type 80
race sample_family
end
Object multipart_head
type 1
end
More
Object multipart_tail
type 1
end
""",
        )
        self.write(
            "arch/items.art",
            """Allowed all
artifact special_item
def_arch base
Object
end
""",
        )
        self.write(
            "arch/items.trs",
            """treasure basic_loot
  arch special_item
end
""",
        )
        self.write(
            "maps/world.factions",
            """faction world
  faction citizens
  end
end
""",
        )
        self.write(
            "maps/regions.reg",
            """region world
map_first /start
end
region town
parent world
end
""",
        )
        self.write(
            "maps/start",
            """arch map
region town
tile_path_1 next
end
arch base
end
arch base
end
arch special_item
end
arch wand
spell_id spell_minor_healing
end
""",
        )
        self.write(
            "maps/next",
            """arch map
region town
end
arch base
end
""",
        )
        self.write(
            "maps/interfaces/quests/sample_quest/quest.xml",
            """<?xml version="1.0"?>
<interfaces>
  <quest name="Sample Quest">
    <part uid="first_part">
      <part uid="nested_part"/>
      <interface>
        <action start="first_part::nested_part" cast="minor healing"
                teleport="/start 1 1" region_map="town"/>
        <object arch="special_item"/>
      </interface>
    </part>
  </quest>
</interfaces>
""",
        )

    def test_loads_domain_qualified_definitions_and_references(self):
        self.create_valid_tree()

        catalog = load_catalog(self.root)

        self.assertFalse(catalog.has_errors, [item.format() for item in catalog.diagnostics])
        ids = {definition.content_id for definition in catalog.definitions}
        self.assertIn(ContentId("archetype", "base"), ids)
        self.assertIn(ContentId("artifact", "special_item"), ids)
        self.assertIn(ContentId("spell", "spell_minor_healing"), ids)
        self.assertIn(ContentId("skill", "skill_literacy"), ids)
        self.assertIn(ContentId("archetype", "sample_monster_variant"), ids)
        self.assertIn(ContentId("quest", "sample_quest"), ids)
        self.assertIn(
            ContentId("quest-part", "sample_quest::first_part::nested_part"), ids
        )
        self.assertNotIn(ContentId("archetype", "multipart_tail"), ids)

        map_arch_references = [
            reference
            for reference in catalog.references
            if reference.source == ContentId("map", "/start")
            and reference.field == "map arch"
            and reference.key == "base"
        ]
        self.assertEqual(1, len(map_arch_references))
        self.assertTrue(
            any(
                reference.field == "spell_id"
                and reference.key == "spell_minor_healing"
                for reference in catalog.references
            )
        )

    def test_reports_duplicate_missing_wrong_domain_and_cycles(self):
        catalog = ContentCatalog(self.root)
        first = catalog.location(self.root / "one", 1)
        second = catalog.location(self.root / "two", 2)
        catalog.add_definition("archetype", "shared", first)
        catalog.add_definition("archetype", "shared", second)
        catalog.add_definition("artifact", "shared", second)
        catalog.add_definition("faction", "world", first)
        catalog.add_definition("faction", "town", second)
        catalog.add_reference("shared", ("region",), second, "region parent")
        catalog.add_reference("absent", ("map",), second, "teleport")
        catalog.check_cycles(
            "faction", {"world": ("town", first), "town": ("world", second)}
        )
        catalog.check_shared_namespace(
            "server archetype", ("archetype", "artifact")
        )
        catalog.resolve_references()

        codes = {diagnostic.code for diagnostic in catalog.diagnostics}
        self.assertEqual(
            {
                "duplicate-id",
                "identity-cycle",
                "missing-reference",
                "shared-namespace-collision",
                "wrong-domain-reference",
            },
            codes,
        )

    def test_rejects_quest_part_ids_that_would_be_silently_changed(self):
        self.create_valid_tree()
        quest = self.root / "maps/interfaces/quests/sample_quest/quest.xml"
        quest.write_text(
            """<interfaces><quest name="Sample"><part uid="Not Stable!"/>
</quest></interfaces>
""",
            encoding="utf-8",
        )

        catalog = load_catalog(self.root)

        self.assertIn(
            "invalid-quest-part-id",
            {diagnostic.code for diagnostic in catalog.diagnostics},
        )

    def test_rejects_map_paths_that_escape_the_authored_root(self):
        self.create_valid_tree()
        start = self.root / "maps/start"
        start.write_text(
            start.read_text(encoding="utf-8").replace(
                "tile_path_1 next", "tile_path_1 ../../outside"
            ),
            encoding="utf-8",
        )

        catalog = load_catalog(self.root)

        self.assertIn("invalid-map-path", {item.code for item in catalog.diagnostics})

    def test_reports_unterminated_source_blocks(self):
        self.create_valid_tree()
        self.write(
            "arch/broken.arc",
            """Object broken
type 1
msg
This block never ends.
""",
        )
        self.write(
            "arch/broken.trs",
            """treasure broken_reward
  arch base
""",
        )

        catalog = load_catalog(self.root)

        codes = {item.code for item in catalog.diagnostics}
        self.assertIn("unterminated-message", codes)
        self.assertIn("unterminated-object", codes)
        self.assertIn("unterminated-treasure", codes)

    def test_reports_object_block_terminated_by_a_second_object(self):
        self.create_valid_tree()
        self.write(
            "arch/broken.arc",
            """Object first
type 29
Object second
type 1
end
""",
        )

        catalog = load_catalog(self.root)

        self.assertIn(
            "unterminated-object", {item.code for item in catalog.diagnostics}
        )

    def test_requires_authored_source_roots(self):
        shutil.rmtree(self.root / "maps")

        catalog = load_catalog(self.root)

        diagnostics = [
            item for item in catalog.diagnostics if item.code == "missing-source-root"
        ]
        self.assertEqual(1, len(diagnostics))
        self.assertEqual("maps", diagnostics[0].location.path)

    def test_rejects_symbolic_links_without_disclosing_the_target(self):
        self.create_valid_tree()
        with tempfile.TemporaryDirectory() as external_directory:
            target = Path(external_directory) / "outside.arc"
            target.write_text("Object outside\ntype 1\nend\n", encoding="utf-8")
            (self.root / "arch" / "outside.arc").symlink_to(target)

            catalog = load_catalog(self.root)

        diagnostics = [
            item for item in catalog.diagnostics if item.code == "unsafe-source-link"
        ]
        self.assertEqual(1, len(diagnostics))
        self.assertEqual("arch/outside.arc", diagnostics[0].location.path)
        self.assertNotIn(external_directory, diagnostics[0].format())
        self.assertEqual((), catalog.definitions)

    def test_runtime_staging_does_not_dereference_tool_links(self):
        self.create_valid_tree()
        (self.root / "tools").mkdir()
        output = self.root / "build" / "runtime"
        output.mkdir(parents=True)
        sentinel = output / "preserve-me"
        sentinel.write_text("existing output\n", encoding="utf-8")
        with tempfile.TemporaryDirectory() as external_directory:
            target = Path(external_directory) / "outside.py"
            target.write_text("raise RuntimeError\n", encoding="utf-8")
            (self.root / "tools" / "outside.py").symlink_to(target)

            with self.assertRaisesRegex(ValueError, "links and special files"):
                build_runtime(
                    self.root,
                    output,
                    "0" * 40,
                )
        self.assertEqual("existing output\n", sentinel.read_text(encoding="utf-8"))

    def test_runtime_build_rejects_linked_and_ancestor_outputs(self):
        self.create_valid_tree()
        (self.root / "tools").mkdir()
        with tempfile.TemporaryDirectory() as external_directory:
            target = Path(external_directory) / "target"
            target.mkdir()
            sentinel = target / "preserve-me"
            sentinel.write_text("existing output\n", encoding="utf-8")
            linked_output = self.root / "build" / "runtime"
            linked_output.parent.mkdir()
            linked_output.symlink_to(target, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "must not be a symbolic link"):
                build_runtime(self.root, linked_output, "0" * 40)

            self.assertEqual("existing output\n", sentinel.read_text(encoding="utf-8"))

        with self.assertRaisesRegex(ValueError, "must not replace"):
            build_runtime(self.root, self.root.parent, "0" * 40)

    def test_runtime_build_preserves_output_when_collection_fails(self):
        self.create_valid_tree()
        (self.root / "tools").mkdir()
        self.write("tools/collect.py", "raise SystemExit(1)\n")
        output = self.root / "build" / "runtime"
        output.mkdir(parents=True)
        sentinel = output / "preserve-me"
        sentinel.write_text("existing output\n", encoding="utf-8")

        with self.assertRaises(subprocess.CalledProcessError):
            build_runtime(self.root, output, "0" * 40)

        self.assertEqual("existing output\n", sentinel.read_text(encoding="utf-8"))
        self.assertEqual([], list(output.parent.glob(".runtime-build-*")))

    def test_recognizes_map_after_a_long_comment_preamble(self):
        self.create_valid_tree()
        self.write(
            "maps/long_preamble",
            "# {}\narch map\nregion town\nend\narch base\nend\n".format(
                "x" * 5000
            ),
        )

        catalog = load_catalog(self.root)

        self.assertFalse(catalog.has_errors, [item.format() for item in catalog.diagnostics])
        self.assertIn(
            ContentId("map", "/long_preamble"),
            {definition.content_id for definition in catalog.definitions},
        )

    def test_reports_exact_columns_for_indented_text_fields(self):
        self.create_valid_tree()

        catalog = load_catalog(self.root)

        reference = next(
            item
            for item in catalog.references
            if item.field == "treasure arch" and item.key == "special_item"
        )
        self.assertEqual(8, reference.location.column)

    def test_reports_exact_columns_for_xml_attribute_values(self):
        self.create_valid_tree()

        catalog = load_catalog(self.root)

        reference = next(
            item
            for item in catalog.references
            if item.field == "teleport" and item.key == "/start"
        )
        source_line = (
            self.root / reference.location.path
        ).read_text(encoding="utf-8").splitlines()[reference.location.line - 1]
        self.assertEqual(source_line.index("/start") + 1, reference.location.column)

    def test_serialized_catalog_is_deterministic(self):
        self.create_valid_tree()

        first = json.dumps(load_catalog(self.root).to_dict(), sort_keys=True)
        second = json.dumps(load_catalog(self.root).to_dict(), sort_keys=True)

        self.assertEqual(first, second)

    def test_display_name_changes_do_not_change_identity(self):
        self.create_valid_tree()
        first_ids = {
            definition.content_id for definition in load_catalog(self.root).definitions
        }
        quest = self.root / "maps/interfaces/quests/sample_quest/quest.xml"
        quest.write_text(
            quest.read_text(encoding="utf-8").replace(
                'name="Sample Quest"', 'name="A Translated Display Name"'
            ),
            encoding="utf-8",
        )

        second_ids = {
            definition.content_id for definition in load_catalog(self.root).definitions
        }

        self.assertEqual(first_ids, second_ids)

    def test_runtime_table_display_names_do_not_own_spell_or_skill_ids(self):
        self.create_valid_tree()
        self.write(
            "server/src/include/spellist.h",
            '    {"spell_minor_healing",\n     "Translated Spell Name",\n',
        )
        self.write(
            "server/src/include/skillist.h",
            '    {"skill_literacy", "Translated Skill Name", NULL, 0},\n',
        )

        catalog = load_catalog(self.root)

        self.assertFalse(catalog.has_errors, [item.format() for item in catalog.diagnostics])
        runtime_fields = {reference.field for reference in catalog.references}
        self.assertIn("spell table id", runtime_fields)
        self.assertIn("skill table id", runtime_fields)

        spell_table = self.root / "server/src/include/spellist.h"
        spell_table.write_text(
            '    {"spell_missing",\n     "Translated Spell Name",\n',
            encoding="utf-8",
        )
        catalog = load_catalog(self.root)
        self.assertIn(
            "missing-reference", {item.code for item in catalog.diagnostics}
        )

    def test_emit_does_not_replace_output_with_an_invalid_catalog(self):
        self.create_valid_tree()
        self.write("arch/duplicate.arc", "Object base\ntype 1\nend\n")
        output = self.root / "build" / "catalog.json"
        output.parent.mkdir()
        output.write_text("preserve me\n", encoding="utf-8")

        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
            io.StringIO()
        ):
            result = catalog_main(
                [
                    "emit",
                    "--root",
                    str(self.root),
                    "--output",
                    str(output),
                ]
            )

        self.assertEqual(1, result)
        self.assertEqual("preserve me\n", output.read_text(encoding="utf-8"))
        self.assertEqual([], list(output.parent.glob(".catalog.json-*.tmp")))

    def test_emit_atomically_writes_a_valid_catalog(self):
        self.create_valid_tree()
        output = self.root / "build" / "catalog.json"

        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
            io.StringIO()
        ):
            result = catalog_main(
                [
                    "emit",
                    "--root",
                    str(self.root),
                    "--output",
                    str(output),
                ]
            )

        self.assertEqual(0, result)
        data = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(ContentCatalog.SCHEMA_VERSION, data["schema_version"])
        self.assertEqual([], list(output.parent.glob(".catalog.json-*.tmp")))


if __name__ == "__main__":
    unittest.main()
