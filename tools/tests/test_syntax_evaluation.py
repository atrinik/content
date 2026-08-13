"""Tests for the bounded YAML/JSONC authored-syntax prototypes."""

from __future__ import annotations

from dataclasses import asdict, replace
import json
from pathlib import Path
import unittest

from tools.content_contracts.contracts import load_json
from tools.content_contracts.corpus import inspect_document
from tools.syntax_evaluation import SELECTED_SYNTAX
from tools.syntax_evaluation import jsonc, yaml12
from tools.syntax_evaluation.benchmark import (
    _implementation_digest,
    _parse_server_output,
    _summary,
    _topology_input_components,
    select_representative_maps,
)
from tools.syntax_evaluation.evaluation import evaluate_corpus, validate_baseline_lock
from tools.syntax_evaluation.limits import DEFAULT_LIMITS, PrototypeError
from tools.syntax_evaluation.model import from_legacy, validate as validate_model


ROOT = Path(__file__).parents[2].resolve()
CONTRACT_ROOT = ROOT / "contracts" / "content-v1"


class SyntaxEvaluationTest(unittest.TestCase):
    def test_topology_inputs_accept_role_and_provider_component_keys(self):
        content = {
            "head": "1" * 40,
            "dirty": False,
            "path": "/worktrees/content",
        }
        server = {
            "head": "2" * 40,
            "dirty": False,
            "path": "/worktrees/server",
        }
        expected = {
            "content": {
                "commit": content["head"],
                "dirty": False,
                "path": content["path"],
            },
            "server": {
                "commit": server["head"],
                "dirty": False,
                "path": server["path"],
            },
        }
        role_keyed = {
            "components": {"content": content, "server": server},
            "dependencies": ["server", "content"],
        }
        provider_keyed = {
            "components": {
                "content-1x": content,
                "classic-server": server,
                "resources": content,
            },
            "dependencies": ["server", "resources", "content"],
            "providers": {
                "content": "content-1x",
                "resources": "resources",
                "server": "classic-server",
            },
        }
        provider_expected = {
            **expected,
            "resources": expected["content"],
        }

        self.assertEqual(expected, _topology_input_components(role_keyed))
        self.assertEqual(provider_expected, _topology_input_components(provider_keyed))

    def test_topology_inputs_fail_closed_on_invalid_provider_mappings(self):
        component = {
            "head": "1" * 40,
            "dirty": False,
            "path": "/worktrees/component",
        }
        provider_keyed = {
            "components": {
                "content-1x": component,
                "classic-server": component,
            },
            "dependencies": ["content", "server"],
            "providers": {
                "content": "content-1x",
                "server": "classic-server",
            },
        }
        invalid = (
            {**provider_keyed, "providers": {"content": "content-1x"}},
            {**provider_keyed, "providers": {"content": "content-1x", "server": 7}},
            {
                **provider_keyed,
                "providers": {"content": "content-1x", "server": "missing"},
            },
            {**provider_keyed, "providers": []},
            {
                "components": {"content": component, "server": component},
                "dependencies": ["content", "server"],
                "providers": None,
            },
            {
                "components": {
                    "content": component,
                    "server": component,
                    "different-server": component,
                },
                "dependencies": ["content", "server"],
                "providers": {
                    "content": "content",
                    "server": "different-server",
                },
            },
            {
                "components": {
                    "content": component,
                    "content-1x": component,
                    "classic-server": component,
                },
                "dependencies": ["content", "server"],
                "providers": {
                    "content": "content-1x",
                    "server": "classic-server",
                },
            },
        )

        for topology in invalid:
            with self.subTest(topology=topology), self.assertRaises(PrototypeError):
                _topology_input_components(topology)

    def test_topology_inputs_fail_closed_on_invalid_component_metadata(self):
        component = {
            "head": "1" * 40,
            "dirty": False,
            "path": "/worktrees/component",
        }
        invalid = (
            {**component, "head": None},
            {**component, "dirty": "false"},
            {**component, "path": None},
        )
        for bad_component in invalid:
            with self.subTest(component=bad_component), self.assertRaises(
                PrototypeError
            ):
                _topology_input_components(
                    {
                        "components": {
                            "content": component,
                            "server": bad_component,
                        },
                        "dependencies": ["content", "server"],
                    }
                )

    def test_locked_corpus_roundtrips_both_surfaces_deterministically(self):
        first = evaluate_corpus(ROOT)
        second = evaluate_corpus(ROOT)

        self.assertEqual(first, second)
        self.assertEqual(14, first["summary"]["fixtures"])
        self.assertEqual(4, first["summary"]["malformed_fixtures"])
        self.assertEqual(28, first["summary"]["byte_exact_roundtrips"])
        self.assertEqual(28, first["summary"]["semantic_roundtrips"])
        self.assertEqual(["jsonc", "yaml12"], first["summary"]["formats"])

    def test_baseline_lock_covers_the_fixed_grammar_inventory_and_corpus(self):
        snapshot = validate_baseline_lock(ROOT)
        paths = {entry["path"] for entry in snapshot["files"]}

        self.assertIn("contracts/content-v1/grammar-inventory.json", paths)
        self.assertIn("contracts/content-v1/consumer-inventory.json", paths)
        self.assertIn("contracts/content-v1/corpus/manifest.json", paths)
        self.assertIn(
            "contracts/content-v1/corpus/fixtures/tiled-stacked-exit.map", paths
        )
        self.assertEqual(14, len(paths))

    def test_selected_syntax_is_jsonc(self):
        self.assertEqual("jsonc", SELECTED_SYNTAX)

    def test_neutral_model_preserves_comments_spans_crlf_and_terminal_state(self):
        grammar = load_json(CONTRACT_ROOT / "grammar-inventory.json")
        source = b"arch map\n# note\r\nwidth 1\nend"
        inspection, _ = inspect_document(
            CONTRACT_ROOT,
            "map",
            grammar,
            source_bytes=source,
        )
        model = from_legacy(source, "map", "/tests/comment-crlf", inspection["comments"])

        self.assertEqual(
            ["source", "comment", "source", "source"],
            [record["kind"] for record in model["records"]],
        )
        self.assertEqual(
            ["lf", "crlf", "lf", "none"],
            [record["ending"] for record in model["records"]],
        )
        self.assertEqual(source, validate_model(model))
        self.assertEqual(source, validate_model(jsonc.decode(jsonc.encode(model))))
        self.assertEqual(source, validate_model(yaml12.decode(yaml12.encode(model))))

    def test_machine_limits_match_the_implementation(self):
        document = load_json(
            ROOT / "prototypes" / "authored-syntax-v1" / "limits.json"
        )
        expected = {
            "schema_version": 1,
            **asdict(DEFAULT_LIMITS),
            "jsonc": {
                "comments": ["line", "block"],
                "trailing_commas": False,
                "non_json_numbers": False,
                "duplicate_keys": False,
            },
            "yaml12": {
                "aliases": False,
                "anchors": False,
                "custom_tags": False,
                "directives": False,
                "document_streams": False,
                "duplicate_keys": False,
                "flow_collections": False,
                "implicit_scalars": False,
                "indent_spaces": 2,
                "mapping_keys": "^[a-z][a-z0-9_]*$",
            },
        }
        self.assertEqual(expected, document)

    def test_jsonc_rejects_ambiguity_and_unbounded_inputs(self):
        invalid = (
            '{"duplicate": 1, "duplicate": 2}',
            '{"trailing": [1,]}',
            '{"number": NaN}',
            '{"integer": 9007199254740992}',
            '{"nul\\u0000key": true}',
            '{"comment": true /* unterminated}',
            '{"missing": [1, 2}',
            "\ud800",
        )
        for source in invalid:
            with self.subTest(source=source):
                with self.assertRaises(PrototypeError):
                    jsonc.decode(source)

        limits = replace(DEFAULT_LIMITS, max_input_bytes=8)
        with self.assertRaisesRegex(PrototypeError, "byte limit"):
            jsonc.decode('{"long": 1}', limits)

        limits = replace(DEFAULT_LIMITS, max_depth=2)
        with self.assertRaisesRegex(PrototypeError, "depth"):
            jsonc.decode('[[[]]]', limits)

        limits = replace(DEFAULT_LIMITS, max_comments=1)
        with self.assertRaisesRegex(PrototypeError, "comment count"):
            jsonc.decode('// one\n// two\n{}', limits)

    def test_jsonc_comment_scanner_ignores_comment_markers_in_strings(self):
        value = jsonc.decode(
            '// header\n{"url": "https://example.invalid/a/*b*/", "ok": true}'
        )
        self.assertEqual("https://example.invalid/a/*b*/", value["url"])

    def test_yaml_rejects_implicit_types_aliases_tags_duplicates_and_dialects(self):
        invalid = (
            "value: yes\n",
            "value: 01\n",
            "value: 2026-08-07\n",
            "value: 9007199254740992\n",
            "value: &anchor \"x\"\n",
            "value: *anchor\n",
            "value: !custom \"x\"\n",
            "value: \"one\"\nvalue: \"two\"\n",
            "value: [1,2]\n",
            "---\nvalue: \"x\"\n",
            " value: \"odd indent\"\n",
            "value:\n    nested: \"too deep for parent\"\n",
        )
        for source in invalid:
            with self.subTest(source=source):
                with self.assertRaises(PrototypeError):
                    yaml12.decode(source)

    def test_yaml_bounds_comments_lines_depth_and_collections(self):
        limits = replace(DEFAULT_LIMITS, max_input_bytes=8)
        with self.assertRaisesRegex(PrototypeError, "byte limit"):
            yaml12.decode('value: "long"\n', limits)

        limits = replace(DEFAULT_LIMITS, max_comments=1)
        with self.assertRaisesRegex(PrototypeError, "comments"):
            yaml12.decode('# one\n# two\nvalue: "ok"\n', limits)

        limits = replace(DEFAULT_LIMITS, max_depth=2)
        with self.assertRaisesRegex(PrototypeError, "indentation"):
            yaml12.decode("one:\n  two:\n    three: 3\n", limits)

        limits = replace(DEFAULT_LIMITS, max_collection_items=1)
        with self.assertRaisesRegex(PrototypeError, "item count"):
            yaml12.decode("values:\n  - 1\n  - 2\n", limits)

    def test_model_rejects_digest_span_and_identity_tampering(self):
        model = from_legacy(
            b"Object safe\nend\n",
            "archetype",
            "archetype:tests/safe",
            [],
        )
        variants = []
        digest = json.loads(json.dumps(model))
        digest["source_sha256"] = "sha256:" + "0" * 64
        variants.append(digest)
        span = json.loads(json.dumps(model))
        span["records"][0]["span"]["start_byte"] = 1
        variants.append(span)
        identity = json.loads(json.dumps(model))
        identity["logical_id"] = "archetype:../escape"
        variants.append(identity)
        extra = json.loads(json.dumps(model))
        extra["unexpected"] = True
        variants.append(extra)
        source_kind = json.loads(json.dumps(model))
        source_kind["source_kind"] = []
        variants.append(source_kind)
        record_kind = json.loads(json.dumps(model))
        record_kind["records"][0]["kind"] = {}
        variants.append(record_kind)
        ending = json.loads(json.dumps(model))
        ending["records"][0]["ending"] = []
        variants.append(ending)
        boolean_span = json.loads(json.dumps(model))
        boolean_span["records"][0]["span"]["line"] = True
        variants.append(boolean_span)

        for variant in variants:
            with self.assertRaises(PrototypeError):
                validate_model(variant)

        with self.assertRaises(PrototypeError):
            from_legacy(
                b"Object safe\nend\n",
                "archetype",
                "archetype:tests/safe",
                [3],
            )
        with self.assertRaises(PrototypeError):
            from_legacy(
                b"Object safe\nend\n",
                "archetype",
                "archetype:tests/safe",
                [1, 1],
            )

    def test_representative_map_selection_is_deterministic_and_size_ordered(self):
        first = select_representative_maps(ROOT)
        second = select_representative_maps(ROOT)

        public = lambda entries: [
            {key: value for key, value in entry.items() if not key.startswith("_")}
            for entry in entries
        ]
        self.assertEqual(public(first), public(second))
        self.assertEqual(["p10", "p50", "p90", "max"], [entry["size_class"] for entry in first])
        self.assertEqual(
            sorted(entry["bytes"] for entry in first),
            [entry["bytes"] for entry in first],
        )
        self.assertEqual(4, len({entry["logical_id"] for entry in first}))
        self.assertTrue(all(entry["objects"] > 0 for entry in first))

    def test_committed_measurement_baseline_preserves_captured_inputs(self):
        report = load_json(
            ROOT
            / "prototypes"
            / "authored-syntax-v1"
            / "measurement-baseline.json"
        )
        self.assertEqual(1, report["schema_version"])
        self.assertEqual("Linux", report["environment"]["system"])
        # Measurements are immutable historical evidence. Grammar evolution
        # advances the current baseline lock without relabelling the inputs
        # used by this already-captured benchmark.
        self.assertEqual(
            "126102873f5356eae0114d6876df25b54cb616719387f0bb466279bb6ecd460d",
            report["inputs"]["content_v1_baseline_sha256"],
        )
        self.assertEqual(
            "354c41e56846e95c0a6d1e39750e15f67dd33c16",
            report["inputs"]["content_commit"],
        )
        self.assertEqual(
            _implementation_digest(ROOT),
            report["inputs"]["syntax_implementation_sha256"],
        )
        representatives = report["representative_maps"]
        self.assertEqual(
            [
                {
                    "size_class": "p10",
                    "corpus_index": 365,
                    "corpus_count": 3651,
                    "path": "maps/shattered_islands/world_5_65_2",
                    "logical_id": "/shattered_islands/world_5_65_2",
                    "bytes": 8400,
                    "objects": 259,
                    "comments": 0,
                    "source_sha256": (
                        "83b460efae5cf5d1ae89a3cd21b7a2ef9c5d00a51da7d20e24a1ccf6e7ca1e89"
                    ),
                },
                {
                    "size_class": "p50",
                    "corpus_index": 1825,
                    "corpus_count": 3651,
                    "path": "maps/shattered_islands/world_-4_65",
                    "logical_id": "/shattered_islands/world_-4_65",
                    "bytes": 16002,
                    "objects": 576,
                    "comments": 0,
                    "source_sha256": (
                        "3a4bcfbf72daa8e654831c76a66990ad83b56eb2bedd80c1ac16e435d1cf0748"
                    ),
                },
                {
                    "size_class": "p90",
                    "corpus_index": 3285,
                    "corpus_count": 3651,
                    "path": "maps/shattered_islands/world_-8_54",
                    "logical_id": "/shattered_islands/world_-8_54",
                    "bytes": 23908,
                    "objects": 848,
                    "comments": 0,
                    "source_sha256": (
                        "876fea7b67e08ab433f1087cb14bb0e3d2e453f525c64a25b74645558eae4f6e"
                    ),
                },
                {
                    "size_class": "max",
                    "corpus_index": 3650,
                    "corpus_count": 3651,
                    "path": (
                        "maps/shattered_islands/strakewood_island/greyton/house/"
                        "luxury_house_0_0"
                    ),
                    "logical_id": (
                        "/shattered_islands/strakewood_island/greyton/house/"
                        "luxury_house_0_0"
                    ),
                    "bytes": 95618,
                    "objects": 2778,
                    "comments": 0,
                    "source_sha256": (
                        "2485aeab1aa727e8e001985806e33922cee79df5e765d7636dac4920a7406cb7"
                    ),
                },
            ],
            representatives,
        )
        measured = report["prototype"]["maps"]
        self.assertEqual(
            [
                (entry["size_class"], entry["logical_id"], entry["bytes"])
                for entry in representatives
            ],
            [
                (entry["size_class"], entry["logical_id"], entry["legacy_bytes"])
                for entry in measured
            ],
        )
        for entry in measured:
            for result in entry["formats"].values():
                self.assertEqual(
                    round(result["encoded_bytes"] / entry["legacy_bytes"], 6),
                    result["expansion_ratio"],
                )
        for section in ("checker", "server"):
            self.assertEqual(
                [
                    (entry["size_class"], entry["logical_id"])
                    for entry in representatives
                ],
                [
                    (entry["size_class"], entry["logical_id"])
                    for entry in report[section]["maps"]
                ],
            )
        self.assertTrue(
            all(
                not component["dirty"]
                for component in report["inputs"]["topology_components"].values()
            )
        )
        self.assertEqual(20, report["prototype"]["iterations_per_map"])
        self.assertEqual(3, report["collection"]["iterations"])
        self.assertEqual(5, report["checker"]["iterations_per_map"])

    def test_changed_live_map_does_not_relabel_historical_measurements(self):
        report = load_json(
            ROOT
            / "prototypes"
            / "authored-syntax-v1"
            / "measurement-baseline.json"
        )
        captured = {
            entry["logical_id"]: entry
            for entry in report["representative_maps"]
        }
        live = {
            entry["logical_id"]: entry
            for entry in select_representative_maps(ROOT)
        }

        logical_id = "/shattered_islands/world_-8_54"
        self.assertEqual(23908, captured[logical_id]["bytes"])
        self.assertEqual(
            "876fea7b67e08ab433f1087cb14bb0e3d2e453f525c64a25b74645558eae4f6e",
            captured[logical_id]["source_sha256"],
        )
        self.assertEqual(23907, live[logical_id]["bytes"])
        self.assertNotEqual(
            captured[logical_id]["source_sha256"],
            live[logical_id]["source_sha256"],
        )
        self.assertEqual(5, report["server"]["process_runs"])
        self.assertEqual(9, report["server"]["iterations_per_map_per_run"])

        def check_summaries(value):
            if isinstance(value, dict):
                if "raw" in value:
                    self.assertEqual(_summary(value["raw"]), value)
                for child in value.values():
                    check_summaries(child)
            elif isinstance(value, list):
                for child in value:
                    check_summaries(child)

        check_summaries(report)

    def test_measurement_summaries_and_server_records_fail_closed(self):
        self.assertEqual(
            {"samples": 4, "min": 1, "median": 2.5, "p95": 4, "max": 4, "raw": [4, 1, 2, 3]},
            _summary([4, 1, 2, 3]),
        )
        output = "\n".join(
            (
                "ATRINIK_CONTENT_BENCHMARK\tformat\t1",
                "ATRINIK_CONTENT_BENCHMARK\tmode\toffline-authored-content",
                "ATRINIK_CONTENT_BENCHMARK\titerations\t1",
                "ATRINIK_CONTENT_BENCHMARK\tstartup_us\t10",
                "ATRINIK_CONTENT_BENCHMARK\tarchetype_init_us\t5",
                "ATRINIK_CONTENT_BENCHMARK\tstartup_peak_rss_kib\t100",
                "ATRINIK_CONTENT_BENCHMARK\tmap\t/safe\t0\t4\t1\t3\t4",
            )
        )
        parsed = _parse_server_output(output, {"/safe"})
        self.assertEqual(4, parsed["samples"][0]["cold_original_us"])

        with self.assertRaises(PrototypeError):
            _parse_server_output(output.replace("/safe", "/unexpected"), {"/safe"})
        with self.assertRaises(PrototypeError):
            _parse_server_output(output + "\nATRINIK_CONTENT_BENCHMARK\tformat\t1", {"/safe"})
        with self.assertRaises(PrototypeError):
            _parse_server_output(
                output + "\nATRINIK_CONTENT_BENCHMARK\tmap\t/safe\t0\t4\t1\t3\t4",
                {"/safe"},
            )
        with self.assertRaises(PrototypeError):
            _parse_server_output(output.replace("\t0\t4\t", "\t1\t4\t"), {"/safe"})


if __name__ == "__main__":
    unittest.main()
