"""Prototype for a deliberately small, JSON-scalar YAML 1.2 profile."""

from __future__ import annotations

import json
import re
from typing import Any

from .limits import (
    DEFAULT_LIMITS,
    ParserLimits,
    PrototypeError,
    decode_bounded_utf8,
    parse_float,
    parse_integer,
    reject_constant,
    reject_duplicate_keys,
    validate_tree,
)


HEADER_COMMENT = "# Atrinik constrained-YAML prototype; persistent comments are model nodes.\n"
KEY = re.compile(r"^[a-z][a-z0-9_]*$")
KEY_PRIORITY = {
    "format": 0,
    "logical_id": 1,
    "source_kind": 2,
    "source_sha256": 3,
    "records": 4,
    "kind": 5,
    "text": 6,
    "ending": 7,
    "span": 8,
    "line": 9,
    "start_byte": 10,
    "end_byte": 11,
}


def _ordered_keys(value: dict[str, Any]) -> list[str]:
    return sorted(value, key=lambda key: (KEY_PRIORITY.get(key, 100), key))


def _scalar(value: Any) -> str:
    if isinstance(value, (dict, list)):
        raise PrototypeError("flow collections are not in the constrained YAML profile")
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _emit(value: Any, indent: int, output: list[str]) -> None:
    prefix = " " * indent
    if isinstance(value, dict):
        if not value:
            raise PrototypeError("empty mappings are not in the constrained YAML prototype")
        for key in _ordered_keys(value):
            if not KEY.fullmatch(key):
                raise PrototypeError("YAML prototype key is not canonical: {}".format(key))
            child = value[key]
            if isinstance(child, (dict, list)):
                output.append("{}{}:\n".format(prefix, key))
                _emit(child, indent + 2, output)
            else:
                output.append("{}{}: {}\n".format(prefix, key, _scalar(child)))
        return
    if isinstance(value, list):
        if not value:
            raise PrototypeError("empty sequences are not in the constrained YAML prototype")
        for child in value:
            if isinstance(child, (dict, list)):
                output.append("{}-\n".format(prefix))
                _emit(child, indent + 2, output)
            else:
                output.append("{}- {}\n".format(prefix, _scalar(child)))
        return
    raise PrototypeError("YAML document root must be a mapping or sequence")


def encode(value: Any, limits: ParserLimits = DEFAULT_LIMITS) -> str:
    validate_tree(value, limits)
    output = [HEADER_COMMENT]
    _emit(value, 0, output)
    encoded = "".join(output)
    decode_bounded_utf8(encoded, limits)
    return encoded


def _strip_comment(line: str) -> tuple[str, int]:
    in_string = False
    escaped = False
    for index, char in enumerate(line):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "#":
            return line[:index].rstrip(), len(line[index:].encode("utf-8"))
    return line.rstrip(), 0


def _scalar_decode(text: str, limits: ParserLimits) -> Any:
    if not text:
        raise PrototypeError("missing constrained YAML scalar")
    try:
        value = json.loads(
            text,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_constant,
            parse_float=lambda number: parse_float(number, limits),
            parse_int=lambda number: parse_integer(number, limits),
        )
    except (json.JSONDecodeError, ValueError) as error:
        raise PrototypeError(
            "YAML scalars must use quoted strings or canonical JSON null/boolean/number syntax"
        ) from error
    if isinstance(value, (dict, list)):
        raise PrototypeError("YAML flow collections are not allowed")
    return value


def _prepare(text: str, limits: ParserLimits) -> list[tuple[int, int, str]]:
    physical = text.splitlines()
    if len(physical) > limits.max_lines:
        raise PrototypeError("YAML line count exceeds limit")
    prepared: list[tuple[int, int, str]] = []
    comments = 0
    comment_bytes = 0
    for line_number, raw in enumerate(physical, 1):
        if len(raw.encode("utf-8")) > limits.max_line_bytes:
            raise PrototypeError("YAML line exceeds byte limit")
        if "\t" in raw:
            raise PrototypeError("tabs are not allowed in constrained YAML")
        content, found_comment_bytes = _strip_comment(raw)
        if found_comment_bytes:
            comments += 1
            comment_bytes += found_comment_bytes
            if comments > limits.max_comments or comment_bytes > limits.max_comment_bytes:
                raise PrototypeError("YAML comments exceed limit")
        if not content.strip():
            continue
        indent = len(content) - len(content.lstrip(" "))
        if indent % 2 != 0 or indent // 2 + 1 > limits.max_depth:
            raise PrototypeError("YAML indentation is not a bounded two-space level")
        token = content[indent:]
        if token.startswith(("%", "---", "...")):
            raise PrototypeError("YAML directives and document markers are not allowed")
        prepared.append((line_number, indent, token))
    if not prepared:
        raise PrototypeError("YAML document is empty")
    return prepared


def _parse_block(
    lines: list[tuple[int, int, str]],
    index: int,
    indent: int,
    limits: ParserLimits,
) -> tuple[Any, int]:
    if index >= len(lines) or lines[index][1] != indent:
        raise PrototypeError("YAML nested value is missing")
    sequence = lines[index][2] == "-" or lines[index][2].startswith("- ")
    value: Any = [] if sequence else {}

    while index < len(lines):
        line_number, current_indent, token = lines[index]
        if current_indent < indent:
            break
        if current_indent > indent:
            raise PrototypeError("unexpected YAML indentation at line {}".format(line_number))
        is_item = token == "-" or token.startswith("- ")
        if is_item != sequence:
            raise PrototypeError("YAML mapping and sequence entries cannot be mixed")

        if sequence:
            if len(value) >= limits.max_collection_items:
                raise PrototypeError("YAML sequence item count exceeds limit")
            if token == "-":
                child, index = _parse_block(lines, index + 1, indent + 2, limits)
                value.append(child)
            else:
                value.append(_scalar_decode(token[2:], limits))
                index += 1
            continue

        if ":" not in token:
            raise PrototypeError("YAML mapping entry is missing a colon")
        key, remainder = token.split(":", 1)
        if not KEY.fullmatch(key):
            raise PrototypeError("YAML mapping key is not a canonical string")
        if key in value:
            raise PrototypeError("duplicate mapping key: {}".format(key))
        if len(value) >= limits.max_object_keys:
            raise PrototypeError("YAML mapping key count exceeds limit")
        if remainder == "":
            child, index = _parse_block(lines, index + 1, indent + 2, limits)
            value[key] = child
        elif remainder.startswith(" ") and remainder[1:]:
            value[key] = _scalar_decode(remainder[1:], limits)
            index += 1
        else:
            raise PrototypeError("YAML mapping colon must be followed by one space")

    return value, index


def decode(source: bytes | str, limits: ParserLimits = DEFAULT_LIMITS) -> Any:
    text = decode_bounded_utf8(source, limits)
    lines = _prepare(text, limits)
    value, index = _parse_block(lines, 0, 0, limits)
    if index != len(lines):
        raise PrototypeError("YAML document has trailing content")
    validate_tree(value, limits)
    return value
