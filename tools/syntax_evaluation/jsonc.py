"""Strict JSON-with-comments prototype with bounded lexical preprocessing."""

from __future__ import annotations

import json
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


HEADER_COMMENT = "// Atrinik authored-syntax prototype; persistent comments are model nodes.\n"


def _without_comments(text: str, limits: ParserLimits) -> str:
    output = list(text)
    index = 0
    depth = 0
    tokens = 0
    comments = 0
    comment_bytes = 0
    in_string = False
    escaped = False

    while index < len(text):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue

        if char == '"':
            in_string = True
            tokens += 1
            index += 1
            continue
        if char in "[{":
            depth += 1
            tokens += 1
            if depth > limits.max_depth:
                raise PrototypeError("JSONC nesting depth exceeds limit")
            index += 1
            continue
        if char in "]}":
            depth -= 1
            tokens += 1
            if depth < 0:
                raise PrototypeError("JSONC closing delimiter has no opener")
            index += 1
            continue
        if char in ",:":
            tokens += 1
            index += 1
            continue
        if char != "/" or index + 1 >= len(text) or text[index + 1] not in "/*":
            index += 1
            continue

        comments += 1
        if comments > limits.max_comments:
            raise PrototypeError("JSONC comment count exceeds limit")
        start = index
        if text[index + 1] == "/":
            index += 2
            while index < len(text) and text[index] not in "\r\n":
                index += 1
        else:
            index += 2
            while index + 1 < len(text) and text[index : index + 2] != "*/":
                index += 1
            if index + 1 >= len(text):
                raise PrototypeError("unterminated JSONC block comment")
            index += 2
        comment_bytes += len(text[start:index].encode("utf-8"))
        if comment_bytes > limits.max_comment_bytes:
            raise PrototypeError("JSONC comment bytes exceed limit")
        for position in range(start, index):
            if output[position] not in "\r\n":
                output[position] = " "

    if in_string:
        raise PrototypeError("unterminated JSONC string")
    if depth != 0:
        raise PrototypeError("unterminated JSONC collection")
    if tokens > limits.max_nodes * 3:
        raise PrototypeError("JSONC lexical token count exceeds limit")
    return "".join(output)


def decode(source: bytes | str, limits: ParserLimits = DEFAULT_LIMITS) -> Any:
    text = decode_bounded_utf8(source, limits)
    stripped = _without_comments(text, limits)
    try:
        value = json.loads(
            stripped,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_constant,
            parse_float=lambda number: parse_float(number, limits),
            parse_int=lambda number: parse_integer(number, limits),
        )
    except (json.JSONDecodeError, RecursionError, ValueError) as error:
        raise PrototypeError("invalid JSONC: {}".format(error)) from error
    validate_tree(value, limits)
    return value


def encode(value: Any, limits: ParserLimits = DEFAULT_LIMITS) -> str:
    validate_tree(value, limits)
    encoded = HEADER_COMMENT + json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    ) + "\n"
    decode_bounded_utf8(encoded, limits)
    return encoded
