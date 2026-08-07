"""Generate portable schema, compiler, editor, and documentation projections."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Dict, Mapping, Sequence

from tools.content_contracts.contracts import confined_file

from .model import SOURCE_PATH, SchemaError, field_definitions, load_schema_source


GENERATED_PATHS = (
    Path("schemas/authored-content-v1/FIELDS.md"),
    Path("schemas/authored-content-v1/editor-properties.json"),
    Path("schemas/authored-content-v1/field-ids.h"),
    Path("schemas/authored-content-v1/field-metadata.json"),
    Path("schemas/authored-content-v1/logical-document.schema.json"),
)


def _json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _source_digest(root: Path) -> str:
    path = confined_file(root, SOURCE_PATH.as_posix(), "content schema source")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _projection_path(root: Path, relative: Path, *, must_exist: bool) -> Path:
    """Return a fixed output path without traversing a linked parent."""

    root = root.resolve(strict=True)
    current = root
    for part in relative.parts[:-1]:
        current /= part
        if current.is_symlink() or not current.is_dir():
            raise SchemaError(
                "generated output parent is missing or unsafe: {}".format(relative)
            )
        try:
            current.resolve(strict=True).relative_to(root)
        except (FileNotFoundError, ValueError) as error:
            raise SchemaError(
                "generated output parent escapes its root: {}".format(relative)
            ) from error
    path = current / relative.name
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise SchemaError("generated output path is unsafe: {}".format(relative))
    if must_exist and not path.is_file():
        raise SchemaError("generated output is missing: {}".format(relative))
    return path


def _value_schema(field: Mapping[str, Any]) -> Mapping[str, Any]:
    kind = field["value_kind"]
    constraints = field["constraints"]
    if kind == "boolean":
        return {"type": "boolean"}
    if kind == "integer":
        return {"type": "integer", **constraints}
    if kind == "number":
        return {"type": "number", **constraints}
    if kind in ("string", "reference"):
        return {"type": "string", "minLength": 1}
    if kind == "enum":
        return {"type": "string", "enum": field["enum_values"]}
    if kind in ("string-list", "reference-list"):
        return {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "maxItems": 250000,
        }
    if kind == "object":
        return {"type": "object", "additionalProperties": {}}
    raise SchemaError("cannot generate value schema for {}".format(kind))


def _record_schema(field: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["field_id", "kind", "span", "value"],
        "properties": {
            "field_id": {"const": field["field_id"]},
            "kind": {"const": "standard-property"},
            "span": {"$ref": "#/$defs/source-span"},
            "value": _value_schema(field),
        },
    }


def _logical_schema(
    source: Mapping[str, Any], fields: Sequence[Mapping[str, Any]]
) -> Mapping[str, Any]:
    map_fields = [field for field in fields if field["context"] == "map-header"]
    object_fields = [
        field
        for field in fields
        if field["context"] == "object"
        and field["status"] in ("active", "legacy-ignored", "reserved")
    ]
    if not map_fields or not object_fields:
        raise SchemaError("logical schema has no map or object fields")
    namespace_pattern = source["logical_model"]["custom_namespace_pattern"]
    if not namespace_pattern.startswith("^"):
        raise SchemaError("custom namespace pattern must be anchored")
    reserved = "|".join(
        re.escape(name) for name in source["logical_model"]["reserved_namespaces"]
    )
    custom_pattern = "^(?!(?:{})(?:[.-]|$)){}".format(
        reserved, namespace_pattern[1:]
    )
    integer_min = source["value_limits"]["integer_minimum"]
    integer_max = source["value_limits"]["integer_maximum"]
    max_items = source["value_limits"]["array_max_items"]

    defs: Dict[str, Any] = {
        "source-span": {
            "type": "object",
            "additionalProperties": False,
            "required": ["column", "end_byte", "line", "start_byte"],
            "properties": {
                "column": {"type": "integer", "minimum": 1},
                "end_byte": {"type": "integer", "minimum": 0},
                "line": {"type": "integer", "minimum": 1},
                "start_byte": {"type": "integer", "minimum": 0},
            },
        },
        "comment-record": {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "span", "text"],
            "properties": {
                "kind": {"const": "comment"},
                "span": {"$ref": "#/$defs/source-span"},
                "text": {"type": "string"},
            },
        },
        "message-record": {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "span", "text"],
            "properties": {
                "kind": {"const": "message"},
                "span": {"$ref": "#/$defs/source-span"},
                "text": {"type": "string"},
            },
        },
        "custom-property": {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "name", "namespace", "span", "value"],
            "properties": {
                "kind": {"const": "custom-property"},
                "name": {"type": "string", "pattern": "^[a-z][a-z0-9_]*$"},
                "namespace": {"type": "string", "pattern": custom_pattern},
                "span": {"$ref": "#/$defs/source-span"},
                "value": {},
            },
        },
        "standard-map-property": {
            "oneOf": [_record_schema(field) for field in map_fields]
        },
        "standard-object-property": {
            "oneOf": [_record_schema(field) for field in object_fields]
        },
        "nested-object-record": {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "object", "span"],
            "properties": {
                "kind": {"const": "nested-object"},
                "object": {"$ref": "#/$defs/object-node"},
                "span": {"$ref": "#/$defs/source-span"},
            },
        },
        "object-body-record": {
            "oneOf": [
                {"$ref": "#/$defs/comment-record"},
                {"$ref": "#/$defs/custom-property"},
                {"$ref": "#/$defs/message-record"},
                {"$ref": "#/$defs/nested-object-record"},
                {"$ref": "#/$defs/standard-object-property"},
            ]
        },
        "object-node": {
            "type": "object",
            "additionalProperties": False,
            "required": ["archetype_id", "body", "context", "kind", "span"],
            "properties": {
                "archetype_id": {"type": "string", "minLength": 1},
                "body": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/object-body-record"},
                    "maxItems": max_items,
                },
                "context": {"enum": source["logical_model"]["object_contexts"]},
                "kind": {"const": "object"},
                "span": {"$ref": "#/$defs/source-span"},
            },
        },
        "map-header": {
            "type": "object",
            "additionalProperties": False,
            "required": ["body", "kind", "span"],
            "properties": {
                "body": {
                    "type": "array",
                    "items": {
                        "oneOf": [
                            {"$ref": "#/$defs/comment-record"},
                            {"$ref": "#/$defs/custom-property"},
                            {"$ref": "#/$defs/message-record"},
                            {"$ref": "#/$defs/standard-map-property"},
                        ]
                    },
                    "maxItems": max_items,
                },
                "kind": {"const": "map-header"},
                "span": {"$ref": "#/$defs/source-span"},
            },
        },
        "placed-object-record": {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "object", "span"],
            "properties": {
                "kind": {"const": "placed-object"},
                "object": {"$ref": "#/$defs/object-node"},
                "span": {"$ref": "#/$defs/source-span"},
            },
        },
        "map-body-record": {
            "oneOf": [
                {"$ref": "#/$defs/comment-record"},
                {"$ref": "#/$defs/placed-object-record"},
            ]
        },
        "archetype-definition": {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "logical_id", "parts", "span"],
            "properties": {
                "kind": {"const": "archetype-definition"},
                "logical_id": {
                    "type": "string",
                    "pattern": "^archetype:[a-z0-9][a-z0-9_./-]*$",
                },
                "parts": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/object-node"},
                    "minItems": 1,
                    "maxItems": max_items,
                },
                "span": {"$ref": "#/$defs/source-span"},
            },
        },
        "map-document": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "body",
                "header",
                "kind",
                "logical_id",
                "schema_id",
                "schema_version",
                "source_sha256",
            ],
            "properties": {
                "body": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/map-body-record"},
                    "maxItems": max_items,
                },
                "header": {"$ref": "#/$defs/map-header"},
                "kind": {"const": "map"},
                "logical_id": {
                    "type": "string",
                    "pattern": "^/[a-z0-9][a-z0-9_./-]*$",
                },
                "schema_id": {"const": source["schema_id"]},
                "schema_version": {"const": source["schema_version"]},
                "source_sha256": {
                    "type": "string",
                    "pattern": "^sha256:[0-9a-f]{64}$",
                },
            },
        },
        "archetype-document": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "definitions",
                "kind",
                "logical_id",
                "schema_id",
                "schema_version",
                "source_sha256",
            ],
            "properties": {
                "definitions": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/archetype-definition"},
                    "minItems": 1,
                    "maxItems": max_items,
                },
                "kind": {"const": "archetype"},
                "logical_id": {
                    "type": "string",
                    "pattern": "^archetype-file:[a-z0-9][a-z0-9_./-]*$",
                },
                "schema_id": {"const": source["schema_id"]},
                "schema_version": {"const": source["schema_version"]},
                "source_sha256": {
                    "type": "string",
                    "pattern": "^sha256:[0-9a-f]{64}$",
                },
            },
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://atrinik.org/schema/content/v1/logical-document.schema.json",
        "title": "Atrinik authored-content v1 logical document",
        "description": (
            "Parser-neutral typed documents with ordered records, byte spans, "
            "nested inventory, multipart parts, and explicit custom namespaces."
        ),
        "type": "object",
        "additionalProperties": False,
        "required": ["kind", "logical_id", "schema_id", "schema_version", "source_sha256"],
        "properties": {
            "body": {"type": "array"},
            "definitions": {"type": "array"},
            "header": {"type": "object"},
            "kind": {"enum": source["logical_model"]["document_kinds"]},
            "logical_id": {"type": "string", "minLength": 1},
            "schema_id": {"const": source["schema_id"]},
            "schema_version": {"type": "integer", "minimum": 1},
            "source_sha256": {
                "type": "string",
                "pattern": "^sha256:[0-9a-f]{64}$",
            },
        },
        "oneOf": [
            {"$ref": "#/$defs/archetype-document"},
            {"$ref": "#/$defs/map-document"},
        ],
        "$defs": defs,
    }


def _fnv1a(value: str) -> int:
    result = 0x811C9DC5
    for byte in value.encode("utf-8"):
        result ^= byte
        result = (result * 0x01000193) & 0xFFFFFFFF
    return result


def _macro(field_id: str) -> str:
    return "ATRINIK_CONTENT_FIELD_" + re.sub(r"[^A-Z0-9]+", "_", field_id.upper())


def _header(source_digest: str, fields: Sequence[Mapping[str, Any]]) -> str:
    ids: Dict[int, str] = {}
    macros: Dict[str, str] = {}
    lines = [
        "/* Generated from schemas/authored-content-v1/source.json. Do not edit. */",
        "#ifndef ATRINIK_CONTENT_FIELD_IDS_H",
        "#define ATRINIK_CONTENT_FIELD_IDS_H",
        "",
        "#include <stdint.h>",
        "",
        '#define ATRINIK_CONTENT_SCHEMA_ID "atrinik-authored-content-v1"',
        "#define ATRINIK_CONTENT_SCHEMA_VERSION UINT32_C(1)",
        '#define ATRINIK_CONTENT_SCHEMA_SOURCE_SHA256 "{}"'.format(source_digest),
        "",
    ]
    for field in fields:
        value = _fnv1a(field["field_id"])
        if value == 0 or value in ids:
            raise SchemaError(
                "stable field hash collision: {} and {}".format(
                    ids.get(value, "zero"), field["field_id"]
                )
        )
        ids[value] = field["field_id"]
        macro = _macro(field["field_id"])
        if macro in macros:
            raise SchemaError(
                "C field macro collision: {} and {}".format(
                    macros[macro], field["field_id"]
                )
            )
        macros[macro] = field["field_id"]
        lines.append(
            "#define {} UINT32_C(0x{:08x}) /* {} */".format(
                macro, value, field["field_id"]
            )
        )
    lines.extend(("", "#endif /* ATRINIK_CONTENT_FIELD_IDS_H */", ""))
    return "\n".join(lines)


def _editor_properties(
    source_digest: str, fields: Sequence[Mapping[str, Any]]
) -> Mapping[str, Any]:
    widgets = {
        "boolean": "checkbox",
        "enum": "select",
        "integer": "integer",
        "number": "number",
        "object": "structured",
        "reference": "reference",
        "reference-list": "reference-list",
        "string": "text",
        "string-list": "tag-list",
    }
    result = []
    for order, field in enumerate(fields):
        result.append(
            {
                "field_id": field["field_id"],
                "label": field["field_id"].partition(".")[2].replace("_", " ").title(),
                "group": field["roles"][0],
                "order": order,
                "status": field["status"],
                "widget": widgets[field["value_kind"]],
                "constraints": field["constraints"],
                "enum_values": field.get("enum_values", []),
                "reference_domains": field["reference_domains"],
            }
        )
    return {
        "schema_version": 1,
        "schema_id": "atrinik-authored-content-editor-v1",
        "source_sha256": source_digest,
        "properties": result,
    }


def _metadata(
    source: Mapping[str, Any], source_digest: str, fields: Sequence[Mapping[str, Any]]
) -> Mapping[str, Any]:
    return {
        "schema_version": source["schema_version"],
        "schema_id": source["schema_id"],
        "source_sha256": source_digest,
        "limits": source["value_limits"],
        "logical_model": source["logical_model"],
        "fields": list(fields),
        "legacy_extensions": source["legacy_extensions"],
        "registered_features": [
            {
                "id": feature["id"],
                "owner": feature["owner"],
                "status": feature["status"],
                "field_ids": sorted(field["field_id"] for field in feature["fields"]),
            }
            for feature in sorted(source["registered_features"], key=lambda item: item["id"])
        ],
    }


def _markdown(source_digest: str, fields: Sequence[Mapping[str, Any]]) -> str:
    lines = [
        "# Generated authored-content fields",
        "",
        "Do not edit this file directly. It is generated from",
        "`schemas/authored-content-v1/source.json` (SHA-256 `{}`).".format(source_digest),
        "",
        "| Field ID | Kind | Status | Roles | References |",
        "| --- | --- | --- | --- | --- |",
    ]
    for field in fields:
        lines.append(
            "| `{}` | `{}` | `{}` | {} | {} |".format(
                field["field_id"],
                field["value_kind"],
                field["status"],
                ", ".join("`{}`".format(role) for role in field["roles"]),
                ", ".join("`{}`".format(domain) for domain in field["reference_domains"])
                or "—",
            )
        )
    lines.append("")
    return "\n".join(lines)


def render_outputs(root: Path) -> Mapping[Path, bytes]:
    """Render every committed projection entirely in memory."""

    root = root.resolve(strict=True)
    source = load_schema_source(root)
    fields = field_definitions(source)
    digest = _source_digest(root)
    outputs = {
        Path("schemas/authored-content-v1/FIELDS.md"): _markdown(digest, fields),
        Path("schemas/authored-content-v1/editor-properties.json"): _json(
            _editor_properties(digest, fields)
        ),
        Path("schemas/authored-content-v1/field-ids.h"): _header(digest, fields),
        Path("schemas/authored-content-v1/field-metadata.json"): _json(
            _metadata(source, digest, fields)
        ),
        Path("schemas/authored-content-v1/logical-document.schema.json"): _json(
            _logical_schema(source, fields)
        ),
    }
    if tuple(sorted(outputs)) != tuple(sorted(GENERATED_PATHS)):
        raise SchemaError("generator output inventory drifted")
    return {path: contents.encode("utf-8") for path, contents in outputs.items()}


def check_outputs(root: Path) -> None:
    """Fail when a generated projection is absent, linked, or stale."""

    root = root.resolve(strict=True)
    for relative, expected in render_outputs(root).items():
        path = _projection_path(root, relative, must_exist=True)
        if path.read_bytes() != expected:
            raise SchemaError("generated output is stale: {}".format(relative))


def write_outputs(root: Path) -> None:
    """Atomically replace only the fixed generated projection inventory."""

    root = root.resolve(strict=True)
    for relative, contents in render_outputs(root).items():
        path = _projection_path(root, relative, must_exist=False)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                "wb",
                dir=path.parent,
                prefix=".{}-".format(path.name),
                suffix=".tmp",
                delete=False,
            ) as destination:
                temporary = Path(destination.name)
                destination.write(contents)
                destination.flush()
                os.fsync(destination.fileno())
            os.replace(temporary, path)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
