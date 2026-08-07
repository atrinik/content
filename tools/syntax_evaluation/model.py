"""Neutral byte-lossless model used only to compare authored surfaces."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable

from .limits import DEFAULT_LIMITS, ParserLimits, PrototypeError, validate_tree


MODEL_FORMAT = "atrinik-lossless-syntax-prototype/v1"
SOURCE_KINDS = {"archetype", "map"}
LINE_ENDINGS = {"none": b"", "lf": b"\n", "crlf": b"\r\n"}
RECORD_KINDS = {"blank", "comment", "source"}
HEX_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
LOGICAL_ID_COMPONENT = re.compile(r"^[A-Za-z0-9_.-]+$")


def _logical_id_valid(value: str, kind: str) -> bool:
    if not value or value != value.strip() or len(value.encode("utf-8")) > 1024:
        return False
    if "\\" in value or "\x00" in value:
        return False
    if kind == "map":
        if not value.startswith("/") or value.endswith("/") or "//" in value:
            return False
        parts = value[1:].split("/")
    else:
        if not value.startswith("archetype:"):
            return False
        parts = value.removeprefix("archetype:").split("/")
    return bool(parts) and all(
        part not in ("", ".", "..") and LOGICAL_ID_COMPONENT.fullmatch(part)
        for part in parts
    )


def _physical_records(raw: bytes) -> Iterable[tuple[bytes, str, int, int]]:
    start = 0
    while start < len(raw):
        newline = raw.find(b"\n", start)
        if newline < 0:
            yield raw[start:], "none", start, len(raw)
            return
        content = raw[start:newline]
        ending = "lf"
        if content.endswith(b"\r"):
            content = content[:-1]
            ending = "crlf"
        yield content, ending, start, newline + 1
        start = newline + 1


def from_legacy(
    raw: bytes,
    source_kind: str,
    logical_id: str,
    comment_lines: Iterable[int],
    limits: ParserLimits = DEFAULT_LIMITS,
) -> dict[str, Any]:
    if source_kind not in SOURCE_KINDS:
        raise PrototypeError("unsupported source kind")
    if not _logical_id_valid(logical_id, source_kind):
        raise PrototypeError("logical ID is not canonical")
    if not raw:
        raise PrototypeError("legacy source must not be empty")
    if len(raw) > limits.max_input_bytes:
        raise PrototypeError("legacy source exceeds byte limit")
    comment_list = list(comment_lines)
    if any(type(line) is not int or line < 1 for line in comment_list):
        raise PrototypeError("comment line annotations must be positive integers")
    comment_set = set(comment_list)
    if len(comment_set) != len(comment_list):
        raise PrototypeError("comment line annotations must be unique")
    records = []
    for line_number, (content, ending, start, end) in enumerate(_physical_records(raw), 1):
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise PrototypeError("legacy source must be valid UTF-8") from error
        if line_number in comment_set:
            kind = "comment"
        elif not text.strip():
            kind = "blank"
        else:
            kind = "source"
        records.append(
            {
                "kind": kind,
                "text": text,
                "ending": ending,
                "span": {
                    "line": line_number,
                    "start_byte": start,
                    "end_byte": end,
                },
            }
        )
    if comment_set and max(comment_set) > len(records):
        raise PrototypeError("comment line annotation is outside the legacy source")
    model = {
        "format": MODEL_FORMAT,
        "logical_id": logical_id,
        "source_kind": source_kind,
        "source_sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
        "records": records,
    }
    validate(model, limits)
    return model


def validate(model: Any, limits: ParserLimits = DEFAULT_LIMITS) -> bytes:
    validate_tree(model, limits)
    if not isinstance(model, dict) or set(model) != {
        "format",
        "logical_id",
        "source_kind",
        "source_sha256",
        "records",
    }:
        raise PrototypeError("prototype root is not the closed lossless model")
    if model["format"] != MODEL_FORMAT:
        raise PrototypeError("prototype format identity is unsupported")
    kind = model["source_kind"]
    if not isinstance(kind, str) or kind not in SOURCE_KINDS:
        raise PrototypeError("prototype source kind is unsupported")
    if not isinstance(model["logical_id"], str) or not _logical_id_valid(model["logical_id"], kind):
        raise PrototypeError("prototype logical ID is not canonical")
    if not isinstance(model["source_sha256"], str) or not HEX_SHA256.fullmatch(
        model["source_sha256"]
    ):
        raise PrototypeError("prototype source digest is invalid")
    records = model["records"]
    if not isinstance(records, list) or not records or len(records) > limits.max_lines:
        raise PrototypeError("prototype physical record count is invalid")

    output = bytearray()
    for index, record in enumerate(records, 1):
        if not isinstance(record, dict) or set(record) != {"kind", "text", "ending", "span"}:
            raise PrototypeError("prototype physical record is not closed")
        record_kind = record["kind"]
        if (
            not isinstance(record_kind, str)
            or record_kind not in RECORD_KINDS
            or not isinstance(record["text"], str)
        ):
            raise PrototypeError("prototype physical record type is invalid")
        ending_name = record["ending"]
        if not isinstance(ending_name, str):
            raise PrototypeError("prototype line ending is invalid")
        ending = LINE_ENDINGS.get(ending_name)
        if ending is None:
            raise PrototypeError("prototype line ending is invalid")
        if "\n" in record["text"]:
            raise PrototypeError("prototype physical record contains LF")
        encoded = record["text"].encode("utf-8") + ending
        if len(encoded) > limits.max_line_bytes:
            raise PrototypeError("prototype physical record exceeds line limit")
        span = record["span"]
        if not isinstance(span, dict) or set(span) != {"line", "start_byte", "end_byte"}:
            raise PrototypeError("prototype source span is not closed")
        if any(type(span[field]) is not int for field in ("line", "start_byte", "end_byte")):
            raise PrototypeError("prototype source span values must be integers")
        if (
            span["line"] != index
            or span["start_byte"] != len(output)
            or span["end_byte"] != len(output) + len(encoded)
        ):
            raise PrototypeError("prototype source spans are not contiguous and exact")
        if index != len(records) and not ending:
            raise PrototypeError("only the final physical record may omit a line ending")
        output.extend(encoded)
        if len(output) > limits.max_input_bytes:
            raise PrototypeError("reconstructed legacy source exceeds byte limit")

    raw = bytes(output)
    if "sha256:" + hashlib.sha256(raw).hexdigest() != model["source_sha256"]:
        raise PrototypeError("prototype source digest does not match records")
    return raw
