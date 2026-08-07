"""Tests for versioned grammar contracts and the legacy parity corpus."""

from __future__ import annotations

import contextlib
import copy
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from tools.content_contracts.__main__ import main as contracts_main
from tools.content_contracts.contracts import (
    ContractError,
    apply_byte_patch,
    confined_file,
    load_json,
    safe_relative_path,
    validate_contract_document,
    validate_contracts,
    validate_instance,
    validate_schema,
)
from tools.content_contracts.corpus import inspect_document, validate_corpus


ROOT = Path(__file__).parents[2].resolve()
CONTRACT_ROOT = ROOT / "contracts" / "content-v1"


class ContentContractTest(unittest.TestCase):
    def setUp(self):
        self.schemas = validate_contracts(ROOT)
        self.grammar = load_json(CONTRACT_ROOT / "grammar-inventory.json")

    def test_committed_contracts_and_corpus_validate_deterministically(self):
        first = validate_corpus(ROOT, self.schemas)
        second = validate_corpus(ROOT, self.schemas)

        self.assertEqual(first, second)
        self.assertEqual(21, first["consumer_count"])
        self.assertEqual(14, len(first["fixtures"]))
        self.assertEqual(16, first["feature_count"])
        self.assertEqual(9, first["load_mode_count"])
        self.assertTrue(
            all(
                report["inspection"]["document"]["byte_sha256"].startswith(
                    "sha256:"
                )
                for report in first["fixtures"]
            )
        )

    def test_grammar_inventory_is_complete_and_canonical(self):
        object_fields = self.grammar["object_grammar"]["known_fields"]
        header_fields = self.grammar["map_header_grammar"]["known_fields"]

        self.assertGreater(len(object_fields), 250)
        self.assertEqual(object_fields, sorted(set(object_fields)))
        self.assertEqual(header_fields, sorted(set(header_fields)))
        self.assertIn("spell_id", object_fields)
        self.assertIn("skill_id", object_fields)
        self.assertIn("sub_layer", object_fields)
        self.assertIn("tile_field_pattern", self.grammar["map_header_grammar"])
        self.assertEqual(10, self.grammar["object_grammar"]["maximum_nesting_depth"])
        self.assertEqual(
            {
                "MAP_ARTIFACT",
                "MAP_ORIGINAL",
                "MAP_STYLE",
                "flex-buffer-mode",
                "line-mode",
                "map-header-mode",
                "map-single-variable-mode",
                "nul-string-mode",
                "object-single-variable-mode",
            },
            {entry["name"] for entry in self.grammar["load_modes"]},
        )

    def test_consumer_inventory_covers_every_legacy_role_and_repository(self):
        inventory = load_json(CONTRACT_ROOT / "consumer-inventory.json")
        entries = inventory["consumers"]
        roles = {role for entry in entries for role in entry["roles"]}
        repositories = {entry["repository"] for entry in entries}

        self.assertEqual(
            {"analyzer", "checker", "collector", "loader", "writer"}, roles
        )
        self.assertTrue(
            {
                "atrinik/content",
                "atrinik/server",
                "atrinik/tools",
                "external/Gridarta",
            }
            <= repositories
        )
        ordered_ids = [entry["id"] for entry in entries]
        self.assertEqual(ordered_ids, sorted(ordered_ids))
        ids = set(ordered_ids)
        self.assertIn("server/object-loader", ids)
        self.assertIn("server/map-writer", ids)
        self.assertIn("tools/classic-map-checker", ids)
        self.assertIn("tools/map-checker-qt", ids)
        self.assertIn("tools/worldviewer", ids)
        map_maker = next(entry for entry in entries if entry["id"] == "tools/map-maker")
        self.assertEqual(["collector"], map_maker["roles"])
        self.assertEqual(["all-authored-content"], map_maker["formats"])

    def test_json_schema_examples_reject_wrong_types_and_extra_fields(self):
        diagnostic = load_json(CONTRACT_ROOT / "examples" / "diagnostic.json")
        validate_instance(diagnostic, self.schemas["diagnostic"])

        wrong_line = copy.deepcopy(diagnostic)
        wrong_line["location"]["line"] = True
        with self.assertRaisesRegex(ContractError, "must be integer"):
            validate_instance(wrong_line, self.schemas["diagnostic"])

        extra = copy.deepcopy(diagnostic)
        extra["unexpected"] = True
        with self.assertRaisesRegex(ContractError, "unexpected keys"):
            validate_instance(extra, self.schemas["diagnostic"])

        wrong_severity = copy.deepcopy(diagnostic)
        wrong_severity["severity"] = "fatal"
        with self.assertRaisesRegex(ContractError, "allowed value"):
            validate_instance(wrong_severity, self.schemas["diagnostic"])

        inspection = load_json(CONTRACT_ROOT / "examples" / "inspection.json")
        inspection["nodes"][0]["fields"][0]["line"] = 999
        with self.assertRaisesRegex(ContractError, "out-of-range fields"):
            validate_contract_document("inspection", inspection, self.schemas)

    def test_schema_subset_fails_closed_for_unknown_keywords_and_refs(self):
        schema = load_json(CONTRACT_ROOT / "schemas" / "diagnostic.schema.json")
        unknown = copy.deepcopy(schema)
        unknown["unevaluatedProperties"] = False
        with self.assertRaisesRegex(ContractError, "unsupported keywords"):
            validate_schema(unknown, "diagnostic")

        bad_reference = copy.deepcopy(schema)
        bad_reference["properties"]["location"] = {"$ref": "https://example.com"}
        with self.assertRaisesRegex(ContractError, "non-local"):
            validate_schema(bad_reference, "diagnostic")

        sibling_reference = copy.deepcopy(schema)
        sibling_reference["properties"]["location"]["description"] = "ignored"
        with self.assertRaisesRegex(ContractError, "sibling keywords"):
            validate_schema(sibling_reference, "diagnostic")

        malformed_children = copy.deepcopy(schema)
        malformed_children["properties"]["location"] = []
        with self.assertRaisesRegex(ContractError, "object schemas"):
            validate_schema(malformed_children, "diagnostic")

        malformed_one_of = copy.deepcopy(schema)
        malformed_one_of["oneOf"] = []
        with self.assertRaisesRegex(ContractError, "oneOf"):
            validate_schema(malformed_one_of, "diagnostic")

        malformed_pattern = copy.deepcopy(schema)
        malformed_pattern["properties"]["code"]["pattern"] = "["
        with self.assertRaisesRegex(ContractError, "pattern is invalid"):
            validate_schema(malformed_pattern, "diagnostic")

        missing_reference = copy.deepcopy(schema)
        missing_reference["properties"]["location"] = {"$ref": "#/$defs/missing"}
        validated = validate_schema(missing_reference, "diagnostic")
        with self.assertRaisesRegex(ContractError, "does not exist"):
            validate_instance(
                load_json(CONTRACT_ROOT / "examples" / "diagnostic.json"),
                validated,
            )

    def test_strict_json_rejects_duplicates_links_and_oversize_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            duplicate = root / "duplicate.json"
            duplicate.write_text('{"key": 1, "key": 2}', encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "duplicate JSON key"):
                load_json(duplicate)

            non_standard = root / "non-standard.json"
            non_standard.write_text('{"value": NaN}', encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "non-standard JSON constant"):
                load_json(non_standard)

            target = root / "target.json"
            target.write_text("{}", encoding="utf-8")
            linked = root / "linked.json"
            linked.symlink_to(target)
            with self.assertRaisesRegex(ContractError, "non-symlink"):
                load_json(linked)

            with mock.patch("tools.content_contracts.contracts.MAX_JSON_BYTES", 1):
                with self.assertRaisesRegex(ContractError, "size limit"):
                    load_json(target)

    def test_repository_relative_paths_are_confined(self):
        self.assertEqual("maps/example", safe_relative_path("maps/example", "path"))
        for value in (
            "",
            " /maps",
            "/maps",
            "maps/../outside",
            "maps//noncanonical",
            "maps/./noncanonical",
            "maps/trailing/",
            "maps\\windows",
            "maps/has\x00nul",
        ):
            with self.subTest(value=value):
                with self.assertRaises(ContractError):
                    safe_relative_path(value, "path")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = root / "source"
            source.write_text("ok", encoding="utf-8")
            self.assertEqual(source, confined_file(root, "source", "fixture"))
            with self.assertRaisesRegex(ContractError, "missing or escapes"):
                confined_file(root, "missing", "fixture")

    def test_inspection_preserves_comments_messages_and_custom_fields(self):
        path = CONTRACT_ROOT / "corpus" / "fixtures" / "comments-custom.arc"
        inspection, summary = inspect_document(
            path,
            "archetype",
            self.grammar,
            display_path="corpus/fixtures/comments-custom.arc",
        )

        self.assertTrue(summary["accepted"])
        self.assertEqual([1], inspection["comments"])
        self.assertEqual(["plugin_owned_field"], inspection["unknown_fields"])
        self.assertEqual(
            "opaque value with spaces", inspection["nodes"][0]["fields"][-1]["value"]
        )

        message = CONTRACT_ROOT / "corpus" / "fixtures" / "multiline-message.arc"
        _, message_summary = inspect_document(message, "archetype", self.grammar)
        self.assertEqual(1, message_summary["messages"])
        self.assertEqual(0, message_summary["comments"])

    def test_inspection_requires_comment_and_delimiter_tokens_at_column_one(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "indented.arc"
            source.write_text(
                "Object indented\n  # extension data\n  end\nend\n",
                encoding="utf-8",
            )
            inspection, summary = inspect_document(source, "archetype", self.grammar)

        self.assertTrue(summary["accepted"])
        self.assertEqual(0, summary["comments"])
        self.assertEqual(["#", "end"], summary["unknown_fields"])
        self.assertEqual(4, inspection["nodes"][0]["end_line"])

    def test_inspection_reports_structure_without_writing_source(self):
        path = CONTRACT_ROOT / "corpus" / "fixtures" / "nested-inventory.map"
        before = (path.read_bytes(), path.stat().st_mtime_ns)

        inspection, summary = inspect_document(path, "map", self.grammar)

        after = (path.read_bytes(), path.stat().st_mtime_ns)
        self.assertEqual(before, after)
        self.assertEqual(3, summary["objects"])
        self.assertEqual(3, summary["maximum_depth"])
        self.assertEqual([0, 1, 2], [node["depth"] for node in inspection["nodes"][1:]])

    def test_inspection_rejects_bad_encoding_nul_size_and_format(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            invalid = root / "invalid"
            invalid.write_bytes(b"\xff")
            with self.assertRaisesRegex(ContractError, "not UTF-8"):
                inspect_document(invalid, "map", self.grammar)

            nul = root / "nul"
            nul.write_bytes(b"arch map\n\x00end\n")
            with self.assertRaisesRegex(ContractError, "contains NUL"):
                inspect_document(nul, "map", self.grammar)

            with mock.patch("tools.content_contracts.corpus.MAX_FIXTURE_BYTES", 1):
                with self.assertRaisesRegex(ContractError, "size limit"):
                    inspect_document(nul, "map", self.grammar)

            with self.assertRaisesRegex(ContractError, "unsupported corpus format"):
                inspect_document(nul, "artifact", self.grammar)

    def test_inline_fixtures_cover_exact_line_endings_and_terminal_byte(self):
        manifest = load_json(CONTRACT_ROOT / "corpus" / "manifest.json")
        expected = {entry["id"]: entry["expected"] for entry in manifest["fixtures"]}

        self.assertEqual("crlf", expected["crlf-map"]["line_endings"])
        self.assertEqual("mixed", expected["mixed-line-endings"]["line_endings"])
        self.assertFalse(expected["no-terminal-newline"]["terminal_newline"])

        with tempfile.TemporaryDirectory() as temporary:
            bare_cr = Path(temporary) / "bare-cr.arc"
            bare_cr.write_bytes(b"Object one\rtype 1\rend\r")
            inspection, summary = inspect_document(
                bare_cr, "archetype", self.grammar
            )
        self.assertEqual("none", summary["line_endings"])
        self.assertFalse(summary["terminal_newline"])
        self.assertFalse(summary["accepted"])
        self.assertEqual(1, len(inspection["nodes"]))

    def test_byte_patch_is_digest_bound_and_preserves_every_no_op_fixture(self):
        reports = validate_corpus(ROOT, self.schemas)["fixtures"]
        self.assertTrue(
            all(
                report["no_op_sha256"]
                == report["inspection"]["document"]["byte_sha256"]
                for report in reports
            )
        )

        schema = self.schemas["patch"]
        source = b"abc"
        patch = {
            "schema_version": 1,
            "path": "maps/example",
            "base_sha256": (
                "sha256:ba7816bf8f01cfea414140de5dae2223"
                "b00361a396177a9cb410ff61f20015ad"
            ),
            "result_sha256": (
                "sha256:703a1b35f8e398e5ff9af9b0179718e"
                "6abee86d42beb55192d0d5b5e93c8cb50"
            ),
            "operations": [
                {
                    "kind": "replace",
                    "start": 1,
                    "end": 2,
                    "replacement_base64": "Wg==",
                }
            ],
        }
        self.assertEqual(b"aZc", apply_byte_patch(source, patch, schema))

        bad_base = dict(patch, base_sha256="sha256:" + "0" * 64)
        with self.assertRaisesRegex(ContractError, "base digest"):
            apply_byte_patch(source, bad_base, schema)

        out_of_range = copy.deepcopy(patch)
        out_of_range["operations"][0]["end"] = 4
        with self.assertRaisesRegex(ContractError, "exceeds source size"):
            apply_byte_patch(source, out_of_range, schema)

    def test_corpus_detects_manifest_hash_and_observation_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(CONTRACT_ROOT, root / "contracts" / "content-v1")
            schemas = validate_contracts(root)
            manifest_path = root / "contracts" / "content-v1" / "corpus" / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["fixtures"][0]["byte_sha256"] = "sha256:" + "0" * 64
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "byte hash differs"):
                validate_corpus(root, schemas)

            manifest = load_json(CONTRACT_ROOT / "corpus" / "manifest.json")
            manifest["fixtures"][0]["expected"]["objects"] = 99
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "observation drifted"):
                validate_corpus(root, schemas)

            manifest = load_json(CONTRACT_ROOT / "corpus" / "manifest.json")
            manifest["fixtures"][0], manifest["fixtures"][1] = (
                manifest["fixtures"][1],
                manifest["fixtures"][0],
            )
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "IDs must be sorted"):
                validate_corpus(root, schemas)

    def test_cli_validates_and_emits_machine_readable_inspection(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            result = contracts_main(["validate", "--root", str(ROOT)])
        self.assertEqual(0, result)
        self.assertIn(
            "21 consumers, 14 fixtures, 16 features, 9 load modes",
            stdout.getvalue(),
        )

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            result = contracts_main(
                [
                    "inspect",
                    "--root",
                    str(ROOT),
                    "--format",
                    "map",
                    "contracts/content-v1/corpus/fixtures/nested-inventory.map",
                ]
            )
        self.assertEqual(0, result)
        self.assertEqual(1, json.loads(stdout.getvalue())["schema_version"])

    def test_cli_rejects_inputs_outside_the_repository(self):
        with tempfile.NamedTemporaryFile() as source:
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                result = contracts_main(
                    [
                        "inspect",
                        "--root",
                        str(ROOT),
                        "--format",
                        "map",
                        source.name,
                    ]
                )
        self.assertEqual(1, result)
        self.assertIn("error:", stderr.getvalue())

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            result = contracts_main(["validate", "--root", "/missing-contract-root"])
        self.assertEqual(1, result)
        self.assertIn("error:", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
