"""Tests for the lossless authored-content core and headless CLI."""

from __future__ import annotations

import base64
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from tools import world_content_audit
from tools.content_catalog import ContentCatalog, SourceLocation
from tools.content_contracts.contracts import (
    load_json,
    validate_contract_document,
    validate_contracts,
)
from tools.content_core import (
    ContentConflictError,
    ContentCoreError,
    ContentSafetyError,
    ContentSyntaxError,
    ProjectIndex,
    apply_transaction,
    audit_project,
    parse_bytes,
    prepare_transaction,
    publish_transaction,
    result_digest,
    semantic_comparison,
)
from tools.content_core.cli import (
    EXIT_CONFLICT,
    EXIT_DIFFERENT,
    EXIT_SUCCESS,
    EXIT_SYNTAX,
    main,
)
from tools.content_core.contracts import (
    validate_core_contracts,
    validate_core_document,
)
from tools.syntax_evaluation.limits import ParserLimits


ROOT = Path(__file__).parents[2].resolve()
CORPUS_ROOT = ROOT / "contracts" / "content-v1"


class ContentCoreTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schemas = validate_core_contracts(ROOT)

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        (self.root / "arch").mkdir()
        (self.root / "maps").mkdir()
        (self.root / "tools").mkdir()
        authored_schema = self.root / "schemas" / "authored-content-v1"
        authored_schema.mkdir(parents=True)
        for relative in (
            "arch/COPYING",
            "maps/COPYING",
            "schemas/authored-content-v1/source.json",
            "tools/COPYING",
        ):
            (self.root / relative).write_text("test source marker\n", encoding="utf-8")

    def tearDown(self):
        self.temporary_directory.cleanup()

    def write(self, relative: str, source: bytes) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(source)
        return path

    def document(self, relative: str, format_name: str):
        return parse_bytes(
            (self.root / relative).read_bytes(),
            path=relative,
            format_name=format_name,
            schema_root=ROOT,
        )

    @staticmethod
    def set_property(document, field_id, value):
        node = document.nodes[0]
        return {
            "kind": "set-property",
            "node_handle": node.handle,
            "node_fingerprint": node.fingerprint,
            "field_id": field_id,
            "value": value,
        }

    @staticmethod
    def transaction(entries):
        return {
            "schema_version": 1,
            "kind": "content-transaction",
            "files": entries,
        }

    @staticmethod
    def entry(relative, format_name, source, operations):
        return {
            "path": relative,
            "format": format_name,
            "base_sha256": result_digest(source),
            "operations": operations,
        }

    def test_contracts_and_examples_are_deterministic_and_valid(self):
        first = validate_core_contracts(ROOT)
        second = validate_core_contracts(ROOT)

        self.assertEqual(first, second)
        self.assertEqual(
            {"catalog-search", "inspection", "transaction", "transaction-result"},
            set(first),
        )

    def test_field_authority_refuses_stale_generated_metadata(self):
        shutil.copy2(
            ROOT / "schemas" / "authored-content-v1" / "field-metadata.json",
            self.root
            / "schemas"
            / "authored-content-v1"
            / "field-metadata.json",
        )

        with self.assertRaises(ContentCoreError) as caught:
            parse_bytes(
                b"Object example\ntype 1\nend\n",
                path="arch/example.arc",
                format_name="archetype",
                schema_root=self.root,
            )
        self.assertEqual("stale-field-metadata", caught.exception.code)

    def test_every_legacy_fixture_is_exact_and_matches_the_parity_oracle(self):
        manifest = load_json(CORPUS_ROOT / "corpus" / "manifest.json")

        for fixture in manifest["fixtures"]:
            with self.subTest(fixture=fixture["id"]):
                source_spec = fixture["source"]
                if "base64" in source_spec:
                    source = base64.b64decode(source_spec["base64"])
                else:
                    source = (CORPUS_ROOT / source_spec["path"]).read_bytes()
                document = parse_bytes(
                    source,
                    path="fixtures/{}".format(fixture["id"]),
                    format_name=fixture["format"],
                    schema_root=ROOT,
                )

                self.assertEqual(source, document.serialize())
                self.assertEqual(fixture["expected"], document.summary())
                inspection = document.inspection()
                validate_core_document("inspection", inspection, self.schemas)
                self.assertEqual(
                    json.dumps(inspection, sort_keys=True),
                    json.dumps(document.inspection(), sort_keys=True),
                )

    def test_typed_views_retain_spans_custom_fields_messages_and_nesting(self):
        source = (
            b"Object parent\n"
            b"name Parent\n"
            b"plugin_owned_field  exact custom  \n"
            b"msg\n"
            b"# raw message content\n"
            b"field like text\n"
            b"endmsg\n"
            b"arch child\n"
            b"type 1\n"
            b"end\n"
            b"end\n"
        )
        document = parse_bytes(
            source,
            path="arch/example.arc",
            format_name="archetype",
            schema_root=ROOT,
        )

        parent, child = document.nodes
        custom = parent.fields[1]
        self.assertTrue(document.valid)
        self.assertEqual("Parent", parent.fields[0].typed_value)
        self.assertEqual("legacy-extension.plugin_owned_field", custom.custom_id)
        self.assertEqual("exact custom", custom.typed_value)
        self.assertEqual(
            b"exact custom",
            source[custom.value_span.start_byte : custom.value_span.end_byte],
        )
        self.assertEqual("# raw message content\nfield like text\n", parent.messages[0].text)
        self.assertEqual(parent.handle, child.parent_handle)
        self.assertEqual([child.handle], parent.child_handles)
        inspected_parent = document.inspection()["nodes"][0]
        self.assertEqual(parent.messages[0].text, inspected_parent["messages"][0]["text"])
        self.assertEqual(
            ["property", "property", "message", "child"],
            [entry["kind"] for entry in inspected_parent["body_order"]],
        )
        self.assertEqual(source, document.serialize())

    def test_patterned_tile_links_are_typed_and_invalid_indices_fail_closed(self):
        source = b"arch map\ntile_path_01 /next\ntile_path_99 /bad\nend\n"
        document = parse_bytes(
            source,
            path="maps/example",
            format_name="map",
            schema_root=ROOT,
        )

        self.assertEqual(
            ["map-header.tile_path_1", "map-header.tile_path"],
            [field.field_id for field in document.map_header.fields],
        )
        self.assertEqual(
            ["tile-index-out-of-range"],
            [item["code"] for item in document.diagnostics],
        )
        self.assertFalse(document.valid)

    def test_indented_standard_field_retains_legacy_unknown_behavior(self):
        document = parse_bytes(
            b"arch map\n name Indented\nend\n",
            path="maps/indented",
            format_name="map",
            schema_root=ROOT,
        )

        field = document.map_header.fields[0]
        self.assertIsNone(field.field_id)
        self.assertEqual("legacy-extension.name", field.custom_id)
        self.assertEqual(
            ["unknown-map-header-field"],
            [item["code"] for item in document.diagnostics],
        )
        self.assertTrue(document.valid)

    def test_legacy_duplicate_properties_warn_but_remain_edit_ambiguous(self):
        source = b"Object example\nname First\nname Second\nend\n"
        path = self.write("arch/duplicate.arc", source)
        document = self.document("arch/duplicate.arc", "archetype")

        self.assertTrue(document.valid)
        self.assertEqual("warning", document.diagnostics[0]["severity"])
        transaction = self.transaction(
            [
                self.entry(
                    "arch/duplicate.arc",
                    "archetype",
                    source,
                    [self.set_property(document, "object.name", "Replacement")],
                )
            ]
        )
        with self.assertRaises(ContentConflictError):
            apply_transaction(self.root, transaction, schema_root=ROOT)
        self.assertEqual(source, path.read_bytes())

    def test_targeted_edit_changes_only_the_value_bytes(self):
        source = (
            b"arch map\n"
            b"name  Keep me  \n"
            b"width 1   \n"
            b"# keep this comment\n"
            b"plugin_header  raw value  \n"
            b"end\n"
            b"arch base\n"
            b"name Hero\n"
            b"msg\n"
            b"line # exact\n"
            b"endmsg\n"
            b"x 2\n"
            b"y 3\n"
            b"end\n"
        )
        path = self.write("maps/example", source)
        document = self.document("maps/example", "map")
        transaction = self.transaction(
            [
                self.entry(
                    "maps/example",
                    "map",
                    source,
                    [self.set_property(document, "map-header.width", 24)],
                )
            ]
        )

        dry_run = apply_transaction(
            self.root, transaction, schema_root=ROOT
        )
        self.assertTrue(dry_run["dry_run"])
        self.assertEqual(source, path.read_bytes())
        validate_core_document("transaction-result", dry_run, self.schemas)

        applied = apply_transaction(
            self.root, transaction, apply=True, schema_root=ROOT
        )
        expected = source.replace(b"width 1", b"width 24", 1)
        self.assertEqual(expected, path.read_bytes())
        self.assertIn("-width 1   ", applied["files"][0]["diff"])
        self.assertIn("+width 24   ", applied["files"][0]["diff"])
        self.assertEqual(
            source.replace(b"width 1", b"width 24", 1),
            self.document("maps/example", "map").serialize(),
        )

    def test_semantic_noop_validates_without_replacing_the_file(self):
        source = b"arch map\nwidth 1\nheight 1\nend\n"
        path = self.write("maps/noop", source)
        document = self.document("maps/noop", "map")
        transaction = self.transaction(
            [
                self.entry(
                    "maps/noop",
                    "map",
                    source,
                    [self.set_property(document, "map-header.width", 1)],
                )
            ]
        )

        with mock.patch("tools.content_core.transaction.os.replace") as replace:
            result = apply_transaction(
                self.root, transaction, apply=True, schema_root=ROOT
            )
        replace.assert_not_called()
        self.assertEqual("", result["files"][0]["diff"])
        self.assertEqual(source, path.read_bytes())

    def test_targeted_edit_never_churns_adjacent_attribution(self):
        source = b"Object example\nname Before\ntype 1\nend\n"
        path = self.write("arch/example/object.arc", source)
        license_path = self.write(
            "arch/example/LICENSE", b"Original attribution bytes\r\n"
        )
        document = self.document("arch/example/object.arc", "archetype")
        transaction = self.transaction(
            [
                self.entry(
                    "arch/example/object.arc",
                    "archetype",
                    source,
                    [self.set_property(document, "object.name", "After")],
                )
            ]
        )

        apply_transaction(
            self.root, transaction, apply=True, schema_root=ROOT
        )
        self.assertEqual(
            b"Object example\nname After\ntype 1\nend\n", path.read_bytes()
        )
        self.assertEqual(b"Original attribution bytes\r\n", license_path.read_bytes())

    def test_property_writes_reject_lossy_or_non_unicode_text(self):
        source = b"Object example\nname Before\ntype 1\nend\n"
        path = self.write("arch/text.arc", source)
        document = self.document("arch/text.arc", "archetype")

        for value in (" After ", "\ud800"):
            with self.subTest(value=repr(value)):
                transaction = self.transaction(
                    [
                        self.entry(
                            "arch/text.arc",
                            "archetype",
                            source,
                            [self.set_property(document, "object.name", value)],
                        )
                    ]
                )
                with self.assertRaises(ContentCoreError):
                    apply_transaction(self.root, transaction, schema_root=ROOT)
                self.assertEqual(source, path.read_bytes())

    def test_primitive_add_remove_and_unset_preserve_unrelated_content(self):
        source = (
            b"arch map\nwidth 1\nheight 1\nend\n"
            b"arch base\nname Parent\nx 0\ny 0\n"
            b"arch item\nname Existing child\nend\n"
            b"end\n"
            b"arch base\nname Remove me\nx 0\ny 0\nend\n"
        )
        path = self.write("maps/primitives", source)
        document = self.document("maps/primitives", "map")
        parent = document.nodes[1]
        removed = document.nodes[3]
        operations = [
            {
                "kind": "unset-property",
                "node_handle": parent.handle,
                "node_fingerprint": parent.fingerprint,
                "field_id": "object.name",
            },
            {
                "kind": "add-object",
                "parent_handle": parent.handle,
                "parent_fingerprint": parent.fingerprint,
                "archetype_id": "coin",
                "properties": {"object.name": "New child", "object.nrof": 2},
            },
            {
                "kind": "remove-object",
                "node_handle": removed.handle,
                "node_fingerprint": removed.fingerprint,
            },
        ]
        transaction = self.transaction(
            [self.entry("maps/primitives", "map", source, operations)]
        )

        apply_transaction(
            self.root, transaction, apply=True, schema_root=ROOT
        )
        result = path.read_bytes()
        self.assertNotIn(b"name Parent\n", result)
        self.assertIn(b"arch item\nname Existing child\nend\n", result)
        self.assertIn(b"arch coin\nname New child\nnrof 2\nend\n", result)
        self.assertNotIn(b"Remove me", result)
        self.assertTrue(self.document("maps/primitives", "map").valid)

    def test_removing_multipart_archetype_part_removes_one_separator_only(self):
        source = (
            b"Object head\ntype 1\nend\n"
            b"More\n"
            b"# attribution for the surviving part\n"
            b"Object tail\ntype 1\nend\n"
        )
        path = self.write("arch/multipart.arc", source)
        document = self.document("arch/multipart.arc", "archetype")
        head = document.nodes[0]
        transaction = self.transaction(
            [
                self.entry(
                    "arch/multipart.arc",
                    "archetype",
                    source,
                    [
                        {
                            "kind": "remove-object",
                            "node_handle": head.handle,
                            "node_fingerprint": head.fingerprint,
                        }
                    ],
                )
            ]
        )

        apply_transaction(
            self.root, transaction, apply=True, schema_root=ROOT
        )
        self.assertEqual(
            b"# attribution for the surviving part\n"
            b"Object tail\ntype 1\nend\n",
            path.read_bytes(),
        )

    def test_stale_digest_or_node_precondition_never_changes_any_file(self):
        first = b"arch map\nwidth 1\nheight 1\nend\n"
        second = b"arch map\nwidth 2\nheight 2\nend\n"
        first_path = self.write("maps/a", first)
        second_path = self.write("maps/b", second)
        first_doc = self.document("maps/a", "map")
        second_doc = self.document("maps/b", "map")
        stale = self.set_property(second_doc, "map-header.width", 4)
        stale["node_fingerprint"] = "sha256:" + "0" * 64
        transaction = self.transaction(
            [
                self.entry(
                    "maps/a",
                    "map",
                    first,
                    [self.set_property(first_doc, "map-header.width", 3)],
                ),
                self.entry("maps/b", "map", second, [stale]),
            ]
        )

        with self.assertRaises(ContentConflictError):
            apply_transaction(
                self.root, transaction, apply=True, schema_root=ROOT
            )
        self.assertEqual(first, first_path.read_bytes())
        self.assertEqual(second, second_path.read_bytes())

    def test_invalid_multifile_result_fails_before_the_first_write(self):
        first = b"arch map\nwidth 1\nheight 1\nend\n"
        second = b"arch map\nwidth 2\nheight 2\nend\n"
        first_path = self.write("maps/a-valid", first)
        second_path = self.write("maps/z-invalid", second)
        first_doc = self.document("maps/a-valid", "map")
        second_doc = self.document("maps/z-invalid", "map")
        transaction = self.transaction(
            [
                self.entry(
                    "maps/a-valid",
                    "map",
                    first,
                    [self.set_property(first_doc, "map-header.width", 3)],
                ),
                self.entry(
                    "maps/z-invalid",
                    "map",
                    second,
                    [
                        self.set_property(
                            second_doc, "map-header.width", "not-an-integer"
                        )
                    ],
                ),
            ]
        )

        with self.assertRaises(ContentCoreError):
            apply_transaction(
                self.root, transaction, apply=True, schema_root=ROOT
            )
        self.assertEqual(first, first_path.read_bytes())
        self.assertEqual(second, second_path.read_bytes())

        transaction["files"][1]["base_sha256"] = "sha256:" + "f" * 64
        with self.assertRaises(ContentConflictError):
            apply_transaction(
                self.root, transaction, apply=True, schema_root=ROOT
            )
        self.assertEqual(first, first_path.read_bytes())
        self.assertEqual(second, second_path.read_bytes())

    def test_publication_failure_rolls_back_every_file_and_cleans_staging(self):
        sources = {
            "maps/a": b"arch map\nwidth 1\nheight 1\nend\n",
            "maps/b": b"arch map\nwidth 2\nheight 2\nend\n",
        }
        entries = []
        for index, (relative, source) in enumerate(sorted(sources.items()), 3):
            self.write(relative, source)
            document = self.document(relative, "map")
            entries.append(
                self.entry(
                    relative,
                    "map",
                    source,
                    [self.set_property(document, "map-header.width", index)],
                )
            )
        prepared = prepare_transaction(
            self.root, self.transaction(entries), schema_root=ROOT
        )

        with self.assertRaisesRegex(ContentCoreError, "rolled back"):
            publish_transaction(self.root, prepared, failure_after=1)
        for relative, source in sources.items():
            self.assertEqual(source, (self.root / relative).read_bytes())
        self.assertEqual([], list(self.root.rglob(".*-content-*-*.tmp")))

    def test_transactions_refuse_non_authored_and_symlink_targets(self):
        source = b"arch map\nwidth 1\nheight 1\nend\n"
        original = self.write("maps/original", source)
        operation = self.set_property(
            self.document("maps/original", "map"), "map-header.width", 2
        )

        outside = self.transaction(
            [self.entry("build/generated", "map", source, [operation])]
        )
        with self.assertRaises(ContentSafetyError):
            prepare_transaction(self.root, outside, schema_root=ROOT)

        if os.name != "nt":
            link = self.root / "maps" / "link"
            link.symlink_to(original)
            linked = self.transaction(
                [self.entry("maps/link", "map", source, [operation])]
            )
            with self.assertRaises(ContentSafetyError):
                prepare_transaction(self.root, linked, schema_root=ROOT)
        self.assertEqual(source, original.read_bytes())

        (self.root / "tools" / "COPYING").unlink()
        with self.assertRaises(ContentSafetyError) as caught:
            prepare_transaction(
                self.root,
                self.transaction(
                    [
                        self.entry(
                            "maps/original", "map", source, [operation]
                        )
                    ]
                ),
                schema_root=ROOT,
            )
        self.assertEqual("non-authored-content-root", caught.exception.code)

    def test_semantic_diff_ignores_only_declared_representation(self):
        left = parse_bytes(
            b"# comment\nObject example\nname Same   \nend\n",
            path="arch/left.arc",
            format_name="archetype",
            schema_root=ROOT,
        )
        right = parse_bytes(
            b"Object example\r\nname Same\r\nend\r\n",
            path="arch/right.arc",
            format_name="archetype",
            schema_root=ROOT,
        )
        changed = parse_bytes(
            b"Object example\nname Different\nend\n",
            path="arch/changed.arc",
            format_name="archetype",
            schema_root=ROOT,
        )

        equivalent = semantic_comparison(left, right)
        self.assertTrue(equivalent["equivalent"])
        self.assertFalse(semantic_comparison(left, changed)["equivalent"])

        invalid = parse_bytes(
            b"Object example\nname Missing end\n",
            path="arch/invalid.arc",
            format_name="archetype",
            schema_root=ROOT,
        )
        with self.assertRaises(ContentSyntaxError):
            semantic_comparison(left, invalid)

    def test_project_cache_invalidation_and_catalog_search(self):
        source = b"Object example\nname Example\nend\n"
        self.write("arch/example.arc", source)
        project = ProjectIndex(self.root, schema_root=ROOT)

        first = project.document("arch/example.arc")
        self.assertIs(first, project.document("arch/example.arc"))
        wrong_format = project.document("arch/example.arc", format_name="map")
        self.assertEqual("map", wrong_format.format)
        self.assertIsNot(first, wrong_format)
        project.invalidate(["arch/example.arc"])
        self.assertIsNot(first, project.document("arch/example.arc"))

        catalog = ContentCatalog(self.root)
        catalog.add_definition(
            "archetype",
            "green_orc",
            SourceLocation("arch/example.arc", 1),
            {"name": "Green Orc"},
        )
        project._catalog = catalog
        result = project.search(kind="archetype", text="green", limit=1)
        validate_core_document("catalog-search", result, self.schemas)
        self.assertEqual("green_orc", result["results"][0]["key"])

    def test_project_audit_discovers_maps_and_archetypes_without_retaining_outputs(self):
        self.write("arch/example.arc", b"Object example\ntype 1\nend\n")
        self.write("maps/example", b"arch map\nwidth 1\nheight 1\nend\n")
        self.write("maps/not-a-map.txt", b"supporting authored data\n")

        result = audit_project(self.root, schema_root=ROOT)

        self.assertEqual(2, result["documents"])
        self.assertEqual(1, result["archetypes"])
        self.assertEqual(1, result["maps"])
        self.assertEqual([], result["invalid_files"])

    def test_parser_rejects_hostile_encoding_and_bounded_input(self):
        cases = (
            (b"\xff", "invalid-content-encoding"),
            (b"Object x\nname a\x00b\nend\n", "content-nul-byte"),
            (b"\xef\xbb\xbfObject x\nend\n", "content-byte-order-mark"),
        )
        for source, code in cases:
            with self.subTest(code=code):
                with self.assertRaises(ContentSyntaxError) as caught:
                    parse_bytes(
                        source,
                        path="arch/hostile.arc",
                        format_name="archetype",
                        schema_root=ROOT,
                    )
                self.assertEqual(code, caught.exception.code)

        limits = ParserLimits(max_lines=2)
        with mock.patch("tools.content_core.parser.DEFAULT_LIMITS", limits):
            with self.assertRaises(ContentSyntaxError) as caught:
                parse_bytes(
                    b"Object x\nname x\nend\n",
                    path="arch/large.arc",
                    format_name="archetype",
                    schema_root=ROOT,
                )
        self.assertEqual("content-line-limit", caught.exception.code)

        oversized_integer = parse_bytes(
            b"Object x\ntype " + b"9" * 129 + b"\nend\n",
            path="arch/number.arc",
            format_name="archetype",
            schema_root=ROOT,
        )
        self.assertIn(
            "invalid-integer",
            [item["code"] for item in oversized_integer.diagnostics],
        )

    def test_cli_output_is_deterministic_and_invalid_content_has_syntax_exit(self):
        relative = "contracts/content-v1/corpus/fixtures/nested-inventory.map"
        outputs = []
        for _ in range(2):
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(
                    [
                        "--root",
                        str(ROOT),
                        "inspect",
                        relative,
                        "--format",
                        "map",
                        "--json",
                    ]
                )
            self.assertEqual(EXIT_SUCCESS, exit_code)
            outputs.append(output.getvalue())
        self.assertEqual(outputs[0], outputs[1])

        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main(
                [
                    "--root",
                    str(ROOT),
                    "validate",
                    "contracts/content-v1/corpus/fixtures/malformed-header.map",
                    "--format",
                    "map",
                    "--json",
                ]
            )
        self.assertEqual(EXIT_SYNTAX, exit_code)
        self.assertFalse(json.loads(output.getvalue())["document"]["valid"])

        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main(
                [
                    "--root",
                    str(ROOT),
                    "diff",
                    "contracts/content-v1/corpus/fixtures/comments-custom.arc",
                    "contracts/content-v1/corpus/fixtures/multiline-message.arc",
                    "--format",
                    "archetype",
                    "--semantic",
                    "--json",
                ]
            )
        self.assertEqual(EXIT_DIFFERENT, exit_code)
        self.assertFalse(json.loads(output.getvalue())["equivalent"])

    def test_cli_apply_is_a_dry_run_unless_explicitly_published(self):
        shutil.copytree(
            ROOT / "schemas" / "content-core-v1",
            self.root / "schemas" / "content-core-v1",
        )
        authored = self.root / "schemas" / "authored-content-v1"
        shutil.copy2(
            ROOT / "schemas" / "authored-content-v1" / "field-metadata.json",
            authored / "field-metadata.json",
        )
        shutil.copy2(
            ROOT / "schemas" / "authored-content-v1" / "source.json",
            authored / "source.json",
        )
        source = b"arch map\nname Caf\xc3\xa9\nwidth 1\nheight 1\nend\n"
        path = self.write("maps/cli", source)
        document = self.document("maps/cli", "map")
        transaction = self.transaction(
            [
                self.entry(
                    "maps/cli",
                    "map",
                    source,
                    [self.set_property(document, "map-header.width", 2)],
                )
            ]
        )
        (self.root / "patch.json").write_text(
            json.dumps(transaction), encoding="utf-8"
        )

        output = io.StringIO()
        error = io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            exit_code = main(
                [
                    "--root",
                    str(self.root),
                    "apply",
                    "--patch",
                    "patch.json",
                    "--json",
                ]
            )
        self.assertEqual(EXIT_SUCCESS, exit_code, error.getvalue())
        self.assertTrue(json.loads(output.getvalue())["dry_run"])
        self.assertIn("Caf\\u00e9", output.getvalue())
        self.assertEqual(source, path.read_bytes())

        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            exit_code = main(
                [
                    "--root",
                    str(self.root),
                    "apply",
                    "--patch",
                    "patch.json",
                    "--apply",
                    "--json",
                ]
            )
        self.assertEqual(EXIT_SUCCESS, exit_code)
        self.assertEqual(
            b"arch map\nname Caf\xc3\xa9\nwidth 2\nheight 1\nend\n",
            path.read_bytes(),
        )

        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(io.StringIO()):
            exit_code = main(
                [
                    "--root",
                    str(self.root),
                    "apply",
                    "--patch",
                    "patch.json",
                    "--json",
                ]
            )
        self.assertEqual(EXIT_CONFLICT, exit_code)
        error_payload = json.loads(output.getvalue())
        self.assertEqual("conflict", error_payload["kind"])
        validate_contract_document(
            "error", error_payload, validate_contracts(ROOT)
        )

    def test_world_audit_uses_the_common_parser_without_report_churn(self):
        source = (
            b"arch map\nname Example\nwidth 1\nheight 1\nmsg\n"
            b"Header message.\nendmsg\nend\n"
            b"arch base\nname Placed\nx 0\ny 0\nmsg\n"
            b"Object message.\nendmsg\n"
            b"arch item\nname Nested\nend\nend\n"
        )
        path = self.write("maps/audit", source)

        with mock.patch.object(world_content_audit, "ROOT", self.root), mock.patch.object(
            world_content_audit, "parse_bytes", wraps=parse_bytes
        ) as common_parser:
            result = world_content_audit.parse_blocks(path)

        common_parser.assert_called_once()
        self.assertEqual("map", result["header"]["arch"])
        self.assertEqual("Header message.", result["header"]["attrs"]["msg"][-1])
        self.assertEqual("Placed", result["objects"][0]["attrs"]["name"][-1])
        self.assertEqual(
            "Object message.", result["objects"][0]["attrs"]["msg"][-1]
        )
        self.assertEqual("Nested", result["objects"][0]["children"][0]["attrs"]["name"][-1])

    def test_world_audit_retains_historical_archetype_attribute_window(self):
        self.write(
            "arch/nested.arc",
            b"Object parent\n"
            b"name Parent\n"
            b"# Child override.\n"
            b"arch child\n"
            b"name Child\n"
            b"race nested\n"
            b"end\n"
            b"hp 5\n"
            b"end\n",
        )

        with mock.patch.object(world_content_audit, "ROOT", self.root), mock.patch.object(
            world_content_audit, "ARCH_ROOT", self.root / "arch"
        ):
            result = world_content_audit.load_archetypes()["parent"]["attrs"]

        self.assertEqual("Child", result["name"])
        self.assertEqual("child", result["arch"])
        self.assertEqual("nested", result["race"])
        self.assertEqual("Child override.", result["#"])
        self.assertNotIn("hp", result)


if __name__ == "__main__":
    unittest.main()
