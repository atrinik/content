"""Tests for the authoritative content schema and generated projections."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tools.content_contracts.contracts import load_json, validate_schema
from tools.content_schema import (
    SchemaError,
    audit_corpus,
    check_outputs,
    dump_logical_document,
    field_definitions,
    load_logical_document,
    load_logical_schema,
    load_schema_source,
    render_outputs,
    validate_logical_document,
)
from tools.content_schema.audit import _audit_artifact_text_constraints


ROOT = Path(__file__).parents[2].resolve()
SCHEMA_ROOT = ROOT / "schemas" / "authored-content-v1"


def span(start, end, line=1, column=1):
    return {
        "start_byte": start,
        "end_byte": end,
        "line": line,
        "column": column,
    }


def standard(field_id, value, start, end):
    return {
        "kind": "standard-property",
        "field_id": field_id,
        "value": value,
        "span": span(start, end),
    }


class ContentSchemaTest(unittest.TestCase):
    def valid_map(self):
        nested = {
            "kind": "object",
            "context": "nested-inventory",
            "archetype_id": "base",
            "body": [standard("object.name", "Nested", 160, 170)],
            "span": span(150, 240),
        }
        placed = {
            "kind": "object",
            "context": "placed-object",
            "archetype_id": "base",
            "body": [
                standard("object.layer", 3, 110, 120),
                standard("object.applied", False, 121, 130),
                standard("object.item_rarity", "rare", 131, 140),
                {
                    "kind": "nested-object",
                    "object": nested,
                    "span": span(150, 240),
                },
            ],
            "span": span(100, 260),
        }
        return {
            "schema_version": 1,
            "schema_id": "atrinik-authored-content-v1",
            "kind": "map",
            "logical_id": "/tests/example",
            "source_sha256": "sha256:" + "0" * 64,
            "header": {
                "kind": "map-header",
                "body": [
                    standard("map-header.name", "Example", 10, 20),
                    standard("map-header.tile_path_1", "/tests/next", 21, 30),
                    {
                        "kind": "custom-property",
                        "namespace": "plugin.example",
                        "name": "weather_hint",
                        "value": {"enabled": True},
                        "span": span(31, 50),
                    },
                ],
                "span": span(0, 90),
            },
            "body": [
                {
                    "kind": "placed-object",
                    "object": placed,
                    "span": span(100, 260),
                }
            ],
        }

    def valid_archetype(self):
        return {
            "schema_version": 1,
            "schema_id": "atrinik-authored-content-v1",
            "kind": "archetype",
            "logical_id": "archetype-file:tests/example",
            "source_sha256": "sha256:" + "0" * 64,
            "definitions": [
                {
                    "kind": "archetype-definition",
                    "logical_id": "archetype:tests/example",
                    "parts": [
                        {
                            "kind": "object",
                            "context": "archetype",
                            "archetype_id": "example",
                            "body": [standard("object.name", "Example", 10, 20)],
                            "span": span(0, 40),
                        },
                        {
                            "kind": "object",
                            "context": "multipart-part",
                            "archetype_id": "example_part",
                            "body": [standard("object.mpart_id", 1, 60, 70)],
                            "span": span(50, 90),
                        },
                    ],
                    "span": span(0, 100),
                }
            ],
        }

    def test_source_covers_the_locked_legacy_grammar_exactly(self):
        source = load_schema_source(ROOT)
        fields = field_definitions(source)
        grammar = load_json(ROOT / "contracts/content-v1/grammar-inventory.json")
        legacy = {
            (field["context"], field["legacy_name"])
            for field in fields
            if field["legacy_name"] is not None
            and not field["legacy_name"].startswith("tile_path_")
        }
        expected = {
            ("map-header", name)
            for name in grammar["map_header_grammar"]["known_fields"]
        } | {
            ("object", name)
            for name in grammar["object_grammar"]["known_fields"]
        }

        self.assertEqual(expected, legacy)
        expected_count = len(expected) + 10 + sum(
            len(feature["fields"]) for feature in source["registered_features"]
        )
        self.assertEqual(expected_count, len(fields))
        self.assertEqual(len(fields), len({field["field_id"] for field in fields}))
        self.assertTrue(
            all(field["constraints"] for field in fields if field["value_kind"] == "integer")
        )

    def test_generated_projections_are_deterministic_and_current(self):
        first = render_outputs(ROOT)
        second = render_outputs(ROOT)

        self.assertEqual(first, second)
        self.assertEqual(
            {
                "FIELDS.md",
                "editor-properties.json",
                "field-ids.h",
                "field-metadata.json",
                "logical-document.schema.json",
            },
            {path.name for path in first},
        )
        check_outputs(ROOT)

        metadata = load_json(SCHEMA_ROOT / "field-metadata.json")
        editor = load_json(SCHEMA_ROOT / "editor-properties.json")
        self.assertEqual(metadata["source_sha256"], editor["source_sha256"])
        self.assertEqual(
            [field["field_id"] for field in metadata["fields"]],
            [field["field_id"] for field in editor["properties"]],
        )

    def test_logical_schema_is_closed_parser_neutral_and_recursive(self):
        schema = load_logical_schema(ROOT)
        self.assertEqual(schema, validate_schema(schema, "logical-document"))
        serialized = json.dumps(schema, sort_keys=True)
        self.assertNotIn("parser_node", serialized)
        self.assertNotIn("tree_sitter", serialized)

        value = self.valid_map()
        validate_logical_document(ROOT, value)
        encoded = dump_logical_document(ROOT, value)
        self.assertEqual(encoded, dump_logical_document(ROOT, value))
        decoded = load_logical_document(ROOT, encoded.encode("utf-8"))
        self.assertEqual(value, decoded)
        self.assertEqual(
            value["header"]["body"][2], decoded["header"]["body"][2]
        )

        with self.assertRaisesRegex(SchemaError, "duplicate mapping key"):
            load_logical_document(ROOT, '{"kind":"map","kind":"map"}')

        deeply_nested_json = "[" * 1100 + "0" + "]" * 1100
        with self.assertRaisesRegex(
            SchemaError, "parser bounds|invalid logical document JSON"
        ):
            load_logical_document(ROOT, deeply_nested_json)

        validate_logical_document(ROOT, self.valid_archetype())

        unknown = copy.deepcopy(value)
        unknown["body"][0]["object"]["body"][0]["field_id"] = "object.layer_typo"
        with self.assertRaises(ValueError):
            validate_logical_document(ROOT, unknown)

        wrong_type = copy.deepcopy(value)
        wrong_type["body"][0]["object"]["body"][1]["value"] = 1
        with self.assertRaisesRegex(
            SchemaError, r"line 1, column 1 \(bytes 100\.\.260\)"
        ):
            validate_logical_document(ROOT, wrong_type)

        reserved_namespace = copy.deepcopy(value)
        reserved_namespace["header"]["body"][2]["namespace"] = "atrinik"
        with self.assertRaises(ValueError):
            validate_logical_document(ROOT, reserved_namespace)

        hostile = copy.deepcopy(value)
        nested = {}
        hostile["header"]["body"][2]["value"] = nested
        for _ in range(70):
            child = {}
            nested["child"] = child
            nested = child
        with self.assertRaisesRegex(SchemaError, "parser bounds"):
            validate_logical_document(ROOT, hostile)

    def test_semantic_validation_rejects_duplicate_order_span_and_context_errors(self):
        duplicate = self.valid_map()
        body = duplicate["body"][0]["object"]["body"]
        body.insert(1, standard("object.layer", 4, 120, 121))
        with self.assertRaisesRegex(SchemaError, "duplicates object.layer"):
            validate_logical_document(ROOT, duplicate)

        reversed_span = self.valid_map()
        reversed_span["header"]["body"][0]["span"] = span(20, 10)
        with self.assertRaisesRegex(SchemaError, "reversed source span"):
            validate_logical_document(ROOT, reversed_span)

        wrong_order = self.valid_map()
        wrong_order["header"]["body"][1]["span"] = span(5, 9)
        with self.assertRaisesRegex(SchemaError, "source order"):
            validate_logical_document(ROOT, wrong_order)

        wrong_context = self.valid_map()
        wrong_context["body"][0]["object"]["context"] = "archetype"
        with self.assertRaisesRegex(SchemaError, "placed-object context"):
            validate_logical_document(ROOT, wrong_context)

        multipart_order = self.valid_archetype()
        multipart_order["definitions"][0]["parts"][1]["span"] = span(20, 30)
        with self.assertRaisesRegex(SchemaError, "source order"):
            validate_logical_document(ROOT, multipart_order)

    def test_whole_corpus_has_no_unexplained_or_untyped_fields(self):
        report = audit_corpus(ROOT)

        self.assertEqual([], report["unexplained_fields"])
        self.assertGreater(report["files"]["archetype"], 0)
        self.assertGreater(report["files"]["map"], 0)
        self.assertGreater(report["objects"], 0)
        self.assertGreater(report["properties"], 0)
        self.assertEqual(
            {
                "Wis",
                "faction",
                "faction_kill_penalty",
                "faction_rep",
                "notification_action",
                "notification_delay",
                "notification_message",
                "notification_shortcut",
                "spawn_time",
                "stock",
            },
            set(report["legacy_extensions"]),
        )
        self.assertTrue(all(report["legacy_extensions"].values()))

    def test_incuna_tonic_glow_is_classic_wire_compatible(self):
        source = load_schema_source(ROOT)
        glow = next(
            field
            for field in field_definitions(source)
            if field["field_id"] == "object.glow"
        )
        self.assertEqual(
            {
                "maxLength": 6,
                "minLength": 6,
                "pattern": "^[0-9A-Fa-f]{6}$",
            },
            glow["constraints"],
        )

        report = _audit_artifact_text_constraints(ROOT)
        self.assertGreater(report["files"], 0)
        self.assertGreater(report["checks"], 0)

        logical = self.valid_map()
        logical["body"][0]["object"]["body"].append(
            standard("object.glow", "dbce3b", 241, 250)
        )
        validate_logical_document(ROOT, logical)
        for malformed in (
            "#dbce3b",
            "0dbce3b",
            "dbce3",
            "dbce3b\n",
            "gggggg",
        ):
            logical["body"][0]["object"]["body"][-1]["value"] = malformed
            with self.assertRaisesRegex(
                SchemaError, "must match exactly one schema alternative"
            ):
                validate_logical_document(ROOT, logical)

        with tempfile.TemporaryDirectory() as temporary:
            fixture_root = Path(temporary)
            fixture = (
                fixture_root
                / "maps"
                / "shattered_islands"
                / "incuna"
                / "artifacts.art"
            )
            fixture.parent.mkdir(parents=True)
            fixture.write_text(
                "Allowed none\n"
                "artifact incuna_angelas_tonic\n"
                "def_arch potion_generic\n"
                "Object\n"
                "glow #dbce3b\n"
                "end\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                SchemaError,
                r"maps/shattered_islands/incuna/artifacts\.art:5: "
                r"object\.glow is longer than 6",
            ):
                _audit_artifact_text_constraints(fixture_root, schema_root=ROOT)

    def test_schema_source_rejects_a_linked_parent_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            repository = temporary_root / "repository"
            external = temporary_root / "external"
            repository.mkdir()
            (external / "schemas" / "authored-content-v1").mkdir(parents=True)
            shutil.copy2(
                SCHEMA_ROOT / "source.json",
                external / "schemas" / "authored-content-v1" / "source.json",
            )
            try:
                (repository / "schemas").symlink_to(
                    external / "schemas", target_is_directory=True
                )
            except OSError as error:
                self.skipTest("directory symlinks are unavailable: {}".format(error))
            with self.assertRaisesRegex(ValueError, "must not traverse a symlink"):
                load_schema_source(repository)

    @unittest.skipUnless(shutil.which("cc"), "a C compiler is not available")
    def test_generated_compiler_field_ids_are_valid_c_and_stable(self):
        header = (SCHEMA_ROOT / "field-ids.h").read_text(encoding="utf-8")
        self.assertIn(
            "ATRINIK_CONTENT_FIELD_OBJECT_NAME UINT32_C(0xe09794f7)", header
        )
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "field_ids.c"
            executable = Path(temporary) / "field_ids"
            source.write_text(
                """#include "schemas/authored-content-v1/field-ids.h"
_Static_assert(ATRINIK_CONTENT_FIELD_OBJECT_NAME != 0, "field ID");
int main(void) { return ATRINIK_CONTENT_SCHEMA_VERSION == 1 ? 0 : 1; }
""",
                encoding="utf-8",
            )
            subprocess.run(
                [
                    shutil.which("cc"),
                    "-std=c11",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-I",
                    str(ROOT),
                    str(source),
                    "-o",
                    str(executable),
                ],
                check=True,
            )
            subprocess.run([str(executable)], check=True)


if __name__ == "__main__":
    unittest.main()
