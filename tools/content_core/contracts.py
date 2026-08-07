"""Validation for the versioned lossless-core JSON interchange boundary."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Mapping

from tools.content_contracts.contracts import (
    ContractError,
    confined_file,
    load_json,
    safe_relative_path,
    validate_instance,
    validate_schema,
)


SCHEMA_ROOT = Path("schemas/content-core-v1")
SCHEMA_NAMES = {
    "catalog-search": "core-catalog-search",
    "inspection": "core-inspection",
    "transaction": "core-transaction",
    "transaction-result": "core-transaction-result",
}


def load_core_schemas(root: Path) -> Mapping[str, Mapping[str, Any]]:
    root = root.resolve(strict=True)
    schemas: Dict[str, Mapping[str, Any]] = {}
    for kind, schema_name in SCHEMA_NAMES.items():
        relative = SCHEMA_ROOT / "{}.schema.json".format(kind)
        path = confined_file(root, relative.as_posix(), "content core schema")
        schemas[kind] = validate_schema(load_json(path), schema_name)
    return schemas


def validate_core_document(
    kind: str,
    value: object,
    schemas: Mapping[str, Mapping[str, Any]],
) -> None:
    if kind not in schemas:
        raise ContractError("unknown content core contract: {}".format(kind))
    validate_instance(value, schemas[kind])
    if not isinstance(value, dict):
        raise ContractError("{} content core contract must be an object".format(kind))
    if kind == "inspection":
        document_path = safe_relative_path(
            value["document"]["path"], "inspection path"
        )
        document_size = value["document"]["size"]
        handles = [node["handle"] for node in value["nodes"]]
        if handles != sorted(set(handles)):
            raise ContractError("inspection node handles must be ordered and unique")
        by_handle = {node["handle"]: node for node in value["nodes"]}
        handle_positions = {handle: index for index, handle in enumerate(handles)}
        expected_top_level = [
            node["handle"]
            for node in value["nodes"]
            if node["parent_handle"] is None
        ]
        if value["top_level"] != expected_top_level:
            raise ContractError(
                "inspection top-level handles disagree with node parents"
            )
        previous_start = 0
        for node in value["nodes"]:
            span = node["span"]
            if (
                span["start_byte"] < previous_start
                or span["end_byte"] < span["start_byte"]
                or span["end_byte"] > document_size
            ):
                raise ContractError("inspection nodes have invalid source spans")
            parent = node["parent_handle"]
            if parent is None:
                if node["depth"] != 0:
                    raise ContractError("inspection top-level node has nonzero depth")
            else:
                parent_node = by_handle.get(parent)
                if (
                    parent_node is None
                    or handle_positions[parent] >= handle_positions[node["handle"]]
                ):
                    raise ContractError(
                        "inspection node parent is undefined or not earlier"
                    )
                if node["depth"] != parent_node["depth"] + 1:
                    raise ContractError("inspection node depth disagrees with parent")
                if node["handle"] not in parent_node["children"]:
                    raise ContractError("inspection parent omits its child")
            children = node["children"]
            if children != sorted(set(children)):
                raise ContractError(
                    "inspection child handles must be ordered and unique"
                )
            for child in children:
                child_node = by_handle.get(child)
                if child_node is None or child_node["parent_handle"] != node["handle"]:
                    raise ContractError("inspection child relationship is inconsistent")
            for field in node["properties"]:
                field_span = field["span"]
                value_span = field["value_span"]
                if (
                    field_span["start_byte"] < span["start_byte"]
                    or field_span["end_byte"] > span["end_byte"]
                    or value_span["start_byte"] < field_span["start_byte"]
                    or value_span["end_byte"] > field_span["end_byte"]
                ):
                    raise ContractError("inspection property span escapes its node")
                if (field["field_id"] is None) == (field["custom_id"] is None):
                    raise ContractError(
                        "inspection property must be standard or custom, exclusively"
                    )
            for message in node["messages"]:
                message_span = message["span"]
                if (
                    message_span["start_byte"] < span["start_byte"]
                    or message_span["end_byte"] > span["end_byte"]
                    or message["body_start_byte"] < message_span["start_byte"]
                    or message["body_end_byte"] < message["body_start_byte"]
                    or message["body_end_byte"] > message_span["end_byte"]
                    or len(message["text"].encode("utf-8"))
                    != message["body_end_byte"] - message["body_start_byte"]
                ):
                    raise ContractError("inspection message has invalid source spans")

            body_starts = []
            body_seen = {
                "property": set(),
                "message": set(),
                "comment": set(),
                "child": set(),
            }
            for entry in node["body_order"]:
                entry_kind = entry["kind"]
                if entry_kind == "child":
                    handle = entry["handle"]
                    child = by_handle.get(handle)
                    if handle not in children or handle in body_seen["child"]:
                        raise ContractError(
                            "inspection body has an invalid child reference"
                        )
                    body_seen["child"].add(handle)
                    body_starts.append(child["span"]["start_byte"])
                    continue
                index = entry["index"]
                records = (
                    node["properties"]
                    if entry_kind == "property"
                    else node["messages"]
                    if entry_kind == "message"
                    else value["comments"]
                )
                if index >= len(records) or index in body_seen[entry_kind]:
                    raise ContractError(
                        "inspection body has an invalid {} index".format(
                            entry_kind
                        )
                    )
                record_span = (
                    records[index]
                    if entry_kind == "comment"
                    else records[index]["span"]
                )
                if (
                    record_span["start_byte"] < span["start_byte"]
                    or record_span["end_byte"] > span["end_byte"]
                ):
                    raise ContractError(
                        "inspection body record escapes its node"
                    )
                body_seen[entry_kind].add(index)
                body_starts.append(record_span["start_byte"])
            if body_starts != sorted(body_starts):
                raise ContractError("inspection node body is not source ordered")
            if body_seen["property"] != set(range(len(node["properties"]))) or body_seen[
                "message"
            ] != set(range(len(node["messages"]))) or body_seen["child"] != set(
                children
            ):
                raise ContractError(
                    "inspection node body omits a property, message, or child"
                )
            previous_start = span["start_byte"]
        comment_spans = value["comments"]
        comment_starts = [span["start_byte"] for span in comment_spans]
        if comment_starts != sorted(set(comment_starts)) or any(
            span["end_byte"] < span["start_byte"]
            or span["end_byte"] > document_size
            for span in comment_spans
        ):
            raise ContractError("inspection comments have invalid source spans")
        for item in value["diagnostics"]:
            if (
                safe_relative_path(
                    item["location"]["path"], "inspection diagnostic path"
                )
                != document_path
            ):
                raise ContractError("inspection diagnostic belongs to another document")
            for location in item["related"]:
                safe_relative_path(
                    location["path"], "inspection related diagnostic path"
                )
        has_errors = any(
            item["severity"] == "error" for item in value["diagnostics"]
        )
        if value["document"]["valid"] == has_errors:
            raise ContractError("inspection validity disagrees with diagnostics")
    elif kind == "transaction":
        paths = [item["path"] for item in value["files"]]
        if paths != sorted(set(paths)):
            raise ContractError("transaction paths must be sorted and unique")
        operation_count = 0
        for file_entry in value["files"]:
            safe_relative_path(file_entry["path"], "transaction path")
            operation_count += len(file_entry["operations"])
            for operation in file_entry["operations"]:
                if operation["kind"] == "add-object" and (
                    (operation["parent_handle"] is None)
                    != (operation["parent_fingerprint"] is None)
                ):
                    raise ContractError(
                        "add-object parent preconditions must both be null or both present"
                    )
        if operation_count > 10_000:
            raise ContractError(
                "transaction exceeds the cumulative operation count limit"
            )
    elif kind == "transaction-result":
        if value["dry_run"] == value["applied"]:
            raise ContractError(
                "transaction result must be either dry-run or applied"
            )
        paths = [item["path"] for item in value["files"]]
        if paths != sorted(set(paths)):
            raise ContractError(
                "transaction result paths must be ordered and unique"
            )
        for path in paths:
            safe_relative_path(path, "transaction result path")
    elif kind == "catalog-search":
        if len(value["results"]) > value["query"]["limit"]:
            raise ContractError("catalog results exceed the requested limit")
        results = value["results"]
        keys = [
            (
                item["domain"],
                item["key"],
                item["location"]["path"],
                item["location"]["line"],
                item["location"]["column"],
            )
            for item in results
        ]
        if keys != sorted(set(keys)):
            raise ContractError("catalog results must be ordered and unique")
        for item in results:
            safe_relative_path(item["location"]["path"], "catalog result path")


def validate_core_contracts(root: Path) -> Mapping[str, Mapping[str, Any]]:
    root = root.resolve(strict=True)
    schemas = load_core_schemas(root)
    manifest_path = confined_file(
        root,
        (SCHEMA_ROOT / "examples/manifest.json").as_posix(),
        "content core example manifest",
    )
    manifest = load_json(manifest_path)
    if not isinstance(manifest, dict) or set(manifest) != {"schema_version", "examples"}:
        raise ContractError("content core example manifest is not closed")
    if manifest["schema_version"] != 1:
        raise ContractError("content core example manifest version is unsupported")
    expected = sorted(SCHEMA_NAMES)
    kinds = [entry.get("kind") for entry in manifest["examples"]]
    if kinds != expected:
        raise ContractError("content core examples must cover every contract once")
    for entry in manifest["examples"]:
        if not isinstance(entry, dict) or set(entry) != {"kind", "path"}:
            raise ContractError("content core example entry is not closed")
        relative = SCHEMA_ROOT / entry["path"]
        example = load_json(
            confined_file(root, relative.as_posix(), "content core example")
        )
        validate_core_document(entry["kind"], example, schemas)
    return schemas
