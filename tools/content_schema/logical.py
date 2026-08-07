"""Validation for parser-neutral authored-content logical documents."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from tools.content_contracts.contracts import (
    ContractError,
    confined_file,
    load_json,
    validate_instance,
    validate_schema,
)
from tools.syntax_evaluation.limits import (
    DEFAULT_LIMITS,
    PrototypeError,
    decode_bounded_utf8,
    parse_float,
    parse_integer,
    reject_constant,
    reject_duplicate_keys,
    validate_tree,
)

from .model import SchemaError


LOGICAL_SCHEMA_PATH = Path(
    "schemas/authored-content-v1/logical-document.schema.json"
)
MAX_LOGICAL_DEPTH = DEFAULT_LIMITS.max_depth
PATH_TOKEN_RE = re.compile(r"\.([A-Za-z0-9_-]+)|\[([0-9]+)\]")


@lru_cache(maxsize=8)
def _load_logical_schema_cached(
    path_text: str, modified_ns: int, size: int
) -> Mapping[str, Any]:
    del modified_ns, size
    schema = load_json(Path(path_text))
    return validate_schema(schema, "logical-document")


def load_logical_schema(root: Path) -> Mapping[str, Any]:
    root = root.resolve(strict=True)
    path = confined_file(
        root, LOGICAL_SCHEMA_PATH.as_posix(), "logical content schema"
    )
    stat = path.stat()
    return _load_logical_schema_cached(path.as_posix(), stat.st_mtime_ns, stat.st_size)


def _span(
    value: Mapping[str, Any], parent: tuple[int, int] | None, context: str
) -> tuple[int, int]:
    span = value["span"]
    start = span["start_byte"]
    end = span["end_byte"]
    if end < start:
        raise SchemaError("{} has a reversed source span".format(context))
    if parent is not None and (start < parent[0] or end > parent[1]):
        raise SchemaError("{} span escapes its parent".format(context))
    return start, end


def _schema_diagnostic(value: object, error: ContractError) -> str:
    """Attach the nearest source span to a schema-path failure."""

    message = str(error)
    context = message.partition(" ")[0]
    if not context.startswith("$"):
        return message
    current = value
    nearest = None
    if isinstance(current, dict) and isinstance(current.get("span"), dict):
        nearest = current["span"]
    for match in PATH_TOKEN_RE.finditer(context[1:]):
        key, index = match.groups()
        try:
            if key is not None and isinstance(current, dict):
                current = current[key]
            elif index is not None and isinstance(current, list):
                current = current[int(index)]
            else:
                break
        except (IndexError, KeyError):
            break
        if isinstance(current, dict) and isinstance(current.get("span"), dict):
            nearest = current["span"]
    if not isinstance(nearest, dict):
        return message
    required = ("line", "column", "start_byte", "end_byte")
    if any(not isinstance(nearest.get(key), int) for key in required):
        return message
    return "{} at line {}, column {} (bytes {}..{})".format(
        message,
        nearest["line"],
        nearest["column"],
        nearest["start_byte"],
        nearest["end_byte"],
    )


def _ordered_records(
    records: Sequence[Mapping[str, Any]],
    parent: tuple[int, int],
    context: str,
    depth: int,
) -> None:
    previous_end = parent[0]
    standard_ids = set()
    custom_ids = set()
    for index, record in enumerate(records):
        record_context = "{}[{}]".format(context, index)
        record_span = _span(record, parent, record_context)
        if record_span[0] < previous_end:
            raise SchemaError("{} is not in authored source order".format(record_context))
        previous_end = record_span[1]
        kind = record["kind"]
        if kind == "standard-property":
            field_id = record["field_id"]
            if field_id in standard_ids:
                raise SchemaError("{} duplicates {}".format(record_context, field_id))
            standard_ids.add(field_id)
        elif kind == "custom-property":
            custom_id = (record["namespace"], record["name"])
            if custom_id in custom_ids:
                raise SchemaError(
                    "{} duplicates custom property {}.{}".format(
                        record_context, *custom_id
                    )
                )
            custom_ids.add(custom_id)
        elif kind == "nested-object":
            if record["object"]["context"] != "nested-inventory":
                raise SchemaError("{} must use nested-inventory context".format(record_context))
            _object(record["object"], record_span, record_context + ".object", depth + 1)


def _object(
    value: Mapping[str, Any],
    parent: tuple[int, int],
    context: str,
    depth: int,
) -> None:
    if depth > MAX_LOGICAL_DEPTH:
        raise SchemaError("{} exceeds logical object depth {}".format(context, MAX_LOGICAL_DEPTH))
    span = _span(value, parent, context)
    _ordered_records(value["body"], span, context + ".body", depth)


def validate_logical_document(root: Path, value: object) -> None:
    """Validate the generated schema plus ordering, spans, and object contexts."""

    try:
        validate_tree(value)
    except PrototypeError as error:
        raise SchemaError("logical document is outside parser bounds: {}".format(error)) from error
    schema = load_logical_schema(root)
    try:
        if isinstance(value, dict) and value.get("kind") in ("archetype", "map"):
            definition = schema["$defs"]["{}-document".format(value["kind"])]
            validate_instance(value, definition, root_schema=schema)
        else:
            validate_instance(value, schema)
    except ContractError as error:
        raise SchemaError(_schema_diagnostic(value, error)) from error
    if not isinstance(value, dict):
        raise SchemaError("logical document must be an object")
    if value["kind"] == "map":
        header_span = _span(value["header"], None, "$.header")
        _ordered_records(value["header"]["body"], header_span, "$.header.body", 0)
        previous = header_span[1]
        for index, record in enumerate(value["body"]):
            context = "$.body[{}]".format(index)
            span = _span(record, None, context)
            if span[0] < previous:
                raise SchemaError("{} is not in authored source order".format(context))
            previous = span[1]
            if record["kind"] == "placed-object":
                if record["object"]["context"] != "placed-object":
                    raise SchemaError("{} must use placed-object context".format(context))
                _object(record["object"], span, context + ".object", 1)
    else:
        logical_ids = set()
        previous = 0
        for definition_index, definition in enumerate(value["definitions"]):
            context = "$.definitions[{}]".format(definition_index)
            span = _span(definition, None, context)
            if span[0] < previous:
                raise SchemaError("{} is not in authored source order".format(context))
            previous = span[1]
            logical_id = definition["logical_id"]
            if logical_id in logical_ids:
                raise SchemaError("{} duplicates logical ID {}".format(context, logical_id))
            logical_ids.add(logical_id)
            previous_part_end = span[0]
            for part_index, part in enumerate(definition["parts"]):
                expected = "archetype" if part_index == 0 else "multipart-part"
                part_context = "{}.parts[{}]".format(context, part_index)
                part_span = _span(part, span, part_context)
                if part_span[0] < previous_part_end:
                    raise SchemaError(
                        "{} is not in authored source order".format(part_context)
                    )
                previous_part_end = part_span[1]
                if part["context"] != expected:
                    raise SchemaError(
                        "{}.parts[{}] must use {} context".format(
                            context, part_index, expected
                        )
                    )
                _object(part, span, part_context, 1)


def dump_logical_document(root: Path, value: object) -> str:
    """Validate and serialize a logical document as deterministic UTF-8 JSON."""

    validate_logical_document(root, value)
    encoder = json.JSONEncoder(
        allow_nan=False,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    chunks = []
    encoded_bytes = 1
    for chunk in encoder.iterencode(value):
        encoded_bytes += len(chunk.encode("utf-8"))
        if encoded_bytes > DEFAULT_LIMITS.max_input_bytes:
            raise SchemaError("logical document JSON exceeds the input byte limit")
        chunks.append(chunk)
    return "".join(chunks) + "\n"


def load_logical_document(root: Path, source: bytes | str) -> Mapping[str, Any]:
    """Decode bounded strict JSON and validate the parser-neutral document."""

    try:
        text = decode_bounded_utf8(source, DEFAULT_LIMITS)
        value = json.loads(
            text,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_constant,
            parse_float=lambda raw: parse_float(raw, DEFAULT_LIMITS),
            parse_int=lambda raw: parse_integer(raw, DEFAULT_LIMITS),
        )
        validate_logical_document(root, value)
    except (json.JSONDecodeError, PrototypeError, RecursionError) as error:
        raise SchemaError("invalid logical document JSON: {}".format(error)) from error
    if not isinstance(value, dict):
        raise SchemaError("logical document must be an object")
    return value
