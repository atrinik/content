"""Shared fail-closed limits for both authored-syntax prototypes."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any


class PrototypeError(ValueError):
    """A prototype document is malformed, ambiguous, or out of bounds."""


@dataclass(frozen=True)
class ParserLimits:
    max_input_bytes: int = 64 * 1024 * 1024
    max_depth: int = 64
    max_nodes: int = 1_000_000
    max_collection_items: int = 250_000
    max_object_keys: int = 256
    max_string_bytes: int = 1 * 1024 * 1024
    max_number_bytes: int = 128
    max_safe_integer: int = 9_007_199_254_740_991
    max_comments: int = 100_000
    max_comment_bytes: int = 4 * 1024 * 1024
    max_line_bytes: int = 1 * 1024 * 1024
    max_lines: int = 250_000


DEFAULT_LIMITS = ParserLimits()


def utf8_size(value: str, description: str) -> int:
    try:
        return len(value.encode("utf-8"))
    except UnicodeEncodeError as error:
        raise PrototypeError("{} must be valid Unicode".format(description)) from error


def decode_bounded_utf8(source: bytes | str, limits: ParserLimits) -> str:
    if isinstance(source, str):
        try:
            encoded = source.encode("utf-8")
        except UnicodeEncodeError as error:
            raise PrototypeError("input text must be valid Unicode") from error
        text = source
    elif isinstance(source, bytes):
        encoded = source
        try:
            text = source.decode("utf-8")
        except UnicodeDecodeError as error:
            raise PrototypeError("input must be valid UTF-8") from error
    else:
        raise PrototypeError("input must be bytes or text")
    if len(encoded) > limits.max_input_bytes:
        raise PrototypeError("input exceeds byte limit")
    if encoded.startswith(b"\xef\xbb\xbf"):
        raise PrototypeError("UTF-8 byte-order marks are not allowed")
    if "\x00" in text:
        raise PrototypeError("NUL is not allowed")
    return text


def reject_constant(value: str) -> None:
    raise PrototypeError("non-JSON scalar is not allowed: {}".format(value))


def parse_integer(value: str, limits: ParserLimits) -> int:
    if len(value) > limits.max_number_bytes:
        raise PrototypeError("integer lexeme exceeds byte limit")
    parsed = int(value)
    if abs(parsed) > limits.max_safe_integer:
        raise PrototypeError("integer exceeds the cross-language safe range")
    return parsed


def parse_float(value: str, limits: ParserLimits) -> float:
    if len(value) > limits.max_number_bytes:
        raise PrototypeError("floating-point lexeme exceeds byte limit")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise PrototypeError("non-finite numbers are not allowed")
    return parsed


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PrototypeError("duplicate mapping key: {}".format(key))
        result[key] = value
    return result


def validate_tree(value: Any, limits: ParserLimits = DEFAULT_LIMITS) -> None:
    """Bound the decoded tree without recursive Python calls."""

    pending: list[tuple[Any, int]] = [(value, 1)]
    nodes = 0
    while pending:
        current, depth = pending.pop()
        nodes += 1
        if nodes > limits.max_nodes:
            raise PrototypeError("decoded node count exceeds limit")
        if depth > limits.max_depth:
            raise PrototypeError("decoded nesting depth exceeds limit")

        if current is None or isinstance(current, bool):
            continue
        if isinstance(current, int):
            if abs(current) > limits.max_safe_integer:
                raise PrototypeError("integer exceeds the cross-language safe range")
            continue
        if isinstance(current, float):
            if not math.isfinite(current):
                raise PrototypeError("non-finite numbers are not allowed")
            continue
        if isinstance(current, str):
            if utf8_size(current, "decoded string") > limits.max_string_bytes:
                raise PrototypeError("decoded string exceeds byte limit")
            if "\x00" in current:
                raise PrototypeError("decoded strings must not contain NUL")
            continue
        if isinstance(current, list):
            if len(current) > limits.max_collection_items:
                raise PrototypeError("sequence item count exceeds limit")
            pending.extend((item, depth + 1) for item in reversed(current))
            continue
        if isinstance(current, dict):
            if len(current) > limits.max_object_keys:
                raise PrototypeError("mapping key count exceeds limit")
            for key, child in reversed(tuple(current.items())):
                if not isinstance(key, str):
                    raise PrototypeError("mapping keys must be strings")
                if utf8_size(key, "mapping key") > limits.max_string_bytes:
                    raise PrototypeError("mapping key exceeds byte limit")
                if "\x00" in key:
                    raise PrototypeError("mapping keys must not contain NUL")
                pending.append((child, depth + 1))
            continue
        raise PrototypeError("unsupported decoded value type: {}".format(type(current).__name__))
