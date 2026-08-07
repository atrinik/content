"""Primitive digest- and fingerprint-bound lossless document operations."""

from __future__ import annotations

from dataclasses import dataclass
import difflib
import hashlib
import math
from pathlib import Path
import re
from typing import Any, Mapping, Optional, Sequence

from tools.syntax_evaluation.limits import DEFAULT_LIMITS

from .authority import load_field_authority
from .errors import ContentConflictError, ContentCoreError, ContentSyntaxError
from .model import Document, Node


FIELD_ID_RE = re.compile(r"^[a-z][a-z0-9-]*\.[a-z][a-z0-9_]*$")
ARCHETYPE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(frozen=True, order=True)
class ByteEdit:
    """One half-open replacement against the original document bytes."""

    start: int
    end: int
    replacement: bytes
    description: str
    sequence: int = 0


class FieldRegistry:
    """Read the generated field metadata used by all semantic operations."""

    def __init__(self, root: Path):
        self._fields = load_field_authority(root).by_id

    def legacy_field(
        self, field_id: object, context: str
    ) -> Mapping[str, Any]:
        if not isinstance(field_id, str) or FIELD_ID_RE.fullmatch(field_id) is None:
            raise ContentCoreError(
                "property field_id is not portable",
                code="invalid-field-id",
            )
        field = self._fields.get(field_id)
        if field is None:
            raise ContentCoreError(
                "unknown standard field {}".format(field_id),
                code="unknown-standard-field",
            )
        if field["context"] != context:
            raise ContentCoreError(
                "{} is not valid in {} context".format(field_id, context),
                code="field-context-mismatch",
            )
        if field["legacy_name"] is None:
            raise ContentCoreError(
                "{} is reserved and has no legacy serialization".format(field_id),
                code="reserved-field-not-writable",
            )
        return field

    def encode(self, field: Mapping[str, Any], value: object) -> bytes:
        kind = field["value_kind"]
        if kind == "boolean":
            if not isinstance(value, bool):
                self._wrong_type(field, "boolean")
            text = "1" if value else "0"
        elif kind == "integer":
            if not isinstance(value, int) or isinstance(value, bool):
                self._wrong_type(field, "integer")
            if abs(value) > DEFAULT_LIMITS.max_safe_integer:
                raise ContentCoreError(
                    "{} exceeds the cross-language safe range".format(
                        field["field_id"]
                    ),
                    code="integer-out-of-range",
                )
            text = str(value)
        elif kind == "number":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                self._wrong_type(field, "number")
            if not math.isfinite(value):
                raise ContentCoreError(
                    "{} must be finite".format(field["field_id"]),
                    code="non-finite-field-value",
                )
            text = str(value)
        elif kind in ("reference", "string"):
            if (
                not isinstance(value, str)
                or not value
                or value != value.strip()
            ):
                self._wrong_type(field, "a non-empty trimmed string")
            text = value
        else:
            raise ContentCoreError(
                "{} cannot be represented by the legacy writer".format(
                    field["field_id"]
                ),
                code="unsupported-legacy-value-kind",
            )
        if "\n" in text or "\r" in text or "\x00" in text:
            raise ContentCoreError(
                "single-line property values cannot contain CR, LF, or NUL",
                code="invalid-property-text",
            )
        number = (
            value
            if isinstance(value, (int, float)) and not isinstance(value, bool)
            else None
        )
        minimum = field["constraints"].get("minimum")
        maximum = field["constraints"].get("maximum")
        if number is not None and minimum is not None and number < minimum:
            raise ContentCoreError(
                "{} is below {}".format(field["field_id"], minimum),
                code="field-below-minimum",
            )
        if number is not None and maximum is not None and number > maximum:
            raise ContentCoreError(
                "{} exceeds {}".format(field["field_id"], maximum),
                code="field-above-maximum",
            )
        try:
            encoded = text.encode("utf-8")
        except UnicodeEncodeError as error:
            raise ContentCoreError(
                "property value must be valid Unicode",
                code="invalid-property-text",
            ) from error
        if len(encoded) > DEFAULT_LIMITS.max_line_bytes:
            raise ContentCoreError(
                "property value exceeds the line byte limit",
                code="property-size-limit",
            )
        return encoded

    @staticmethod
    def _wrong_type(field: Mapping[str, Any], expected: str) -> None:
        raise ContentCoreError(
            "{} requires {}".format(field["field_id"], expected),
            code="field-value-type",
        )


def _checked_node(
    document: Document,
    handle: object,
    fingerprint: object,
    *,
    object_only: bool = False,
) -> Node:
    if not isinstance(handle, str) or not isinstance(fingerprint, str):
        raise ContentConflictError(
            "node handle and fingerprint are required",
            code="missing-node-precondition",
        )
    try:
        node = document.node(handle)
    except KeyError as error:
        raise ContentConflictError(
            "node handle no longer exists: {}".format(handle),
            code="stale-node-handle",
        ) from error
    if node.fingerprint != fingerprint:
        raise ContentConflictError(
            "node fingerprint does not match {}".format(handle),
            code="stale-node-fingerprint",
        )
    if object_only and node.kind != "object":
        raise ContentCoreError(
            "operation requires an object node",
            code="object-node-required",
        )
    return node


def _multipart_separator(document: Document, node: Node):
    """Find the one top-level More record adjacent to an archetype part."""

    if document.format != "archetype" or node.depth != 0:
        return None

    def significant(line) -> bool:
        return bool(line.content.strip()) and not line.content.startswith(b"#")

    for line in reversed(document.lines):
        if line.end_byte > node.opener_span.start_byte or not significant(line):
            continue
        if (
            not line.content.startswith((b" ", b"\t"))
            and line.content.strip().lower() == b"more"
        ):
            return line.span
        break
    for line in document.lines:
        if line.start_byte < node.span.end_byte or not significant(line):
            continue
        if (
            not line.content.startswith((b" ", b"\t"))
            and line.content.strip().lower() == b"more"
        ):
            return line.span
        break
    return None


def operation_edits(
    document: Document,
    operations: Sequence[Mapping[str, Any]],
    registry: FieldRegistry,
) -> Sequence[ByteEdit]:
    """Compile semantic primitive operations to minimal original-byte edits."""

    edits = []
    for sequence, operation in enumerate(operations):
        if not isinstance(operation, dict) or not isinstance(
            operation.get("kind"), str
        ):
            raise ContentCoreError(
                "transaction operation must be a closed object",
                code="invalid-operation",
            )
        kind = operation["kind"]
        if kind == "set-property":
            node = _checked_node(
                document,
                operation.get("node_handle"),
                operation.get("node_fingerprint"),
            )
            expected = {
                "kind",
                "node_handle",
                "node_fingerprint",
                "field_id",
                "value",
            }
            _closed_operation(operation, expected)
            field = registry.legacy_field(operation["field_id"], node.context)
            replacement = registry.encode(field, operation["value"])
            matches = node.field_ids(field["field_id"])
            if len(matches) > 1:
                raise ContentConflictError(
                    "{} occurs more than once in {}".format(
                        field["field_id"], node.handle
                    ),
                    code="ambiguous-property-target",
                )
            if matches:
                target = matches[0].value_span
                edits.append(
                    ByteEdit(
                        target.start_byte,
                        target.end_byte,
                        replacement,
                        "set {}".format(field["field_id"]),
                        sequence,
                    )
                )
            else:
                if node.closer_span is None:
                    raise ContentConflictError(
                        "cannot insert into an unterminated node",
                        code="unterminated-operation-target",
                    )
                line = (
                    field["legacy_name"].encode("ascii")
                    + b" "
                    + replacement
                    + document.preferred_line_ending()
                )
                edits.append(
                    ByteEdit(
                        node.closer_span.start_byte,
                        node.closer_span.start_byte,
                        line,
                        "insert {}".format(field["field_id"]),
                        sequence,
                    )
                )
        elif kind == "unset-property":
            expected = {
                "kind",
                "node_handle",
                "node_fingerprint",
                "field_id",
            }
            _closed_operation(operation, expected)
            node = _checked_node(
                document,
                operation["node_handle"],
                operation["node_fingerprint"],
            )
            field = registry.legacy_field(operation["field_id"], node.context)
            matches = node.field_ids(field["field_id"])
            if len(matches) != 1:
                raise ContentConflictError(
                    "{} must occur exactly once in {}".format(
                        field["field_id"], node.handle
                    ),
                    code="property-target-count",
                )
            target = matches[0].span
            edits.append(
                ByteEdit(
                    target.start_byte,
                    target.end_byte,
                    b"",
                    "unset {}".format(field["field_id"]),
                    sequence,
                )
            )
        elif kind == "remove-object":
            expected = {"kind", "node_handle", "node_fingerprint"}
            _closed_operation(operation, expected)
            node = _checked_node(
                document,
                operation["node_handle"],
                operation["node_fingerprint"],
                object_only=True,
            )
            edits.append(
                ByteEdit(
                    node.span.start_byte,
                    node.span.end_byte,
                    b"",
                    "remove {}".format(node.handle),
                    sequence,
                )
            )
            separator = _multipart_separator(document, node)
            if separator is not None:
                edits.append(
                    ByteEdit(
                        separator.start_byte,
                        separator.end_byte,
                        b"",
                        "remove multipart separator for {}".format(
                            node.handle
                        ),
                        sequence,
                    )
                )
        elif kind == "add-object":
            expected = {
                "kind",
                "parent_handle",
                "parent_fingerprint",
                "archetype_id",
                "properties",
            }
            _closed_operation(operation, expected)
            archetype_id = operation["archetype_id"]
            if (
                not isinstance(archetype_id, str)
                or ARCHETYPE_ID_RE.fullmatch(archetype_id) is None
            ):
                raise ContentCoreError(
                    "add-object archetype_id is not portable",
                    code="invalid-archetype-id",
                )
            parent = None
            if operation["parent_handle"] is not None:
                parent = _checked_node(
                    document,
                    operation["parent_handle"],
                    operation["parent_fingerprint"],
                    object_only=True,
                )
                if parent.closer_span is None:
                    raise ContentConflictError(
                        "cannot add inventory to an unterminated object",
                        code="unterminated-operation-target",
                    )
            elif operation["parent_fingerprint"] is not None:
                raise ContentCoreError(
                    "top-level add-object must use a null parent fingerprint",
                    code="unexpected-parent-fingerprint",
                )
            properties = operation["properties"]
            if not isinstance(properties, dict):
                raise ContentCoreError(
                    "add-object properties must be an object",
                    code="invalid-object-properties",
                )
            if (
                len(properties) > DEFAULT_LIMITS.max_object_keys
                or any(not isinstance(field_id, str) for field_id in properties)
            ):
                raise ContentCoreError(
                    "add-object properties must use at most {} string field IDs".format(
                        DEFAULT_LIMITS.max_object_keys
                    ),
                    code="invalid-object-properties",
                )
            ending = document.preferred_line_ending()
            opener = b"arch " if parent is not None or document.format == "map" else b"Object "
            block = bytearray(opener + archetype_id.encode("ascii") + ending)
            for field_id in sorted(properties):
                field = registry.legacy_field(field_id, "object")
                block.extend(field["legacy_name"].encode("ascii"))
                block.extend(b" ")
                block.extend(registry.encode(field, properties[field_id]))
                block.extend(ending)
            block.extend(b"end" + ending)
            position = (
                parent.closer_span.start_byte
                if parent is not None
                else len(document.source)
            )
            if position and parent is None and not document.source.endswith((b"\n", b"\r")):
                block = bytearray(ending) + block
            edits.append(
                ByteEdit(
                    position,
                    position,
                    bytes(block),
                    "add object {}".format(archetype_id),
                    sequence,
                )
            )
        else:
            raise ContentCoreError(
                "unsupported primitive operation {}".format(kind),
                code="unsupported-operation",
            )
    return tuple(edits)


def _closed_operation(operation: Mapping[str, Any], keys: set[str]) -> None:
    if set(operation) != keys:
        raise ContentCoreError(
            "{} operation must contain exactly: {}".format(
                operation.get("kind", "unknown"), ", ".join(sorted(keys))
            ),
            code="operation-shape",
        )


def apply_edits(source: bytes, edits: Sequence[ByteEdit]) -> bytes:
    """Apply ordered non-overlapping edits to original bytes."""

    ordered = sorted(edits, key=lambda edit: (edit.start, edit.end, edit.sequence))
    cursor = 0
    result = bytearray()
    for edit in ordered:
        if edit.start < cursor or edit.end < edit.start or edit.end > len(source):
            raise ContentConflictError(
                "semantic operations overlap or escape the source",
                code="overlapping-operations",
            )
        result.extend(source[cursor : edit.start])
        result.extend(edit.replacement)
        cursor = edit.end
    result.extend(source[cursor:])
    if len(result) > DEFAULT_LIMITS.max_input_bytes:
        raise ContentCoreError(
            "edited document exceeds the input byte limit",
            code="content-size-limit",
        )
    return bytes(result)


def unified_diff(path: str, before: bytes, after: bytes) -> str:
    """Return a deterministic review diff without decoding replacement bytes loosely."""

    before_lines = before.decode("utf-8").splitlines(keepends=True)
    after_lines = after.decode("utf-8").splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile="a/" + path,
            tofile="b/" + path,
            lineterm="\n",
        )
    )


def semantic_comparison(left: Document, right: Document) -> Mapping[str, Any]:
    """Compare typed ordered trees while ignoring documented representation."""

    if not left.valid or not right.valid:
        raise ContentSyntaxError(
            "semantic comparison requires two valid documents",
            code="invalid-semantic-comparison-input",
            diagnostics=tuple(left.diagnostics) + tuple(right.diagnostics),
        )

    left_tree = left.semantic_tree()
    right_tree = right.semantic_tree()
    differences = []
    if left_tree != right_tree:
        differences.append(
            {
                "path": "$.nodes",
                "category": "structure",
                "before": left_tree,
                "after": right_tree,
            }
        )
    return {
        "schema_version": 1,
        "left_sha256": left.byte_sha256,
        "right_sha256": right.byte_sha256,
        "equivalent": not differences,
        "ignored_representation": [
            "comment",
            "line-ending",
            "trailing-whitespace",
        ],
        "differences": differences,
    }


def result_digest(source: bytes) -> str:
    return "sha256:" + hashlib.sha256(source).hexdigest()
