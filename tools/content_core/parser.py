"""Bounded byte-lossless parser for legacy Atrinik map and archetype ADS."""

from __future__ import annotations

from functools import lru_cache
import math
from pathlib import Path
import re
from typing import Any, Dict, Mapping, Optional, Sequence

from tools.content_contracts.contracts import (
    ContractError,
    confined_file,
    safe_relative_path,
)
from tools.content_constraints import text_constraint_violation
from tools.syntax_evaluation.limits import DEFAULT_LIMITS

from .authority import load_field_authority
from .errors import ContentSafetyError, ContentSyntaxError
from .model import (
    Document,
    FieldRecord,
    MessageRecord,
    Node,
    PhysicalLine,
    SourceSpan,
    diagnostic,
)


FORMAT_NAMES = {"archetype", "map"}
INTEGER_RE = re.compile(r"^[+-]?[0-9]+$")
NUMBER_RE = re.compile(
    r"^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$"
)
PORTABLE_CUSTOM_RE = re.compile(r"^[a-z][a-z0-9_]*$")
TILE_FIELD_RE = re.compile(r"^tile_path_[0-9]{1,2}$")
PACKAGE_ROOT = Path(__file__).parents[2].resolve()


def _physical_lines(source: bytes) -> Sequence[PhysicalLine]:
    lines = []
    start = 0
    number = 1
    while start < len(source):
        newline = source.find(b"\n", start)
        if newline < 0:
            lines.append(
                PhysicalLine(number, start, len(source), source[start:], b"")
            )
            break
        content = source[start:newline]
        ending = b"\n"
        if content.endswith(b"\r"):
            content = content[:-1]
            ending = b"\r\n"
        lines.append(
            PhysicalLine(number, start, newline + 1, content, ending)
        )
        start = newline + 1
        number += 1
    return tuple(lines)


def _logical_id(path: str, format_name: str) -> str:
    if format_name == "map":
        suffix = path.removeprefix("maps/")
        return "/" + suffix
    return "archetype-file:" + path.removeprefix("arch/")


class LegacyParser:
    """Parse legacy ADS while retaining every input byte and semantic span."""

    def __init__(self, schema_root: Path = PACKAGE_ROOT):
        authority = load_field_authority(schema_root)
        self._fields = authority.by_legacy
        self._extensions = authority.legacy_extensions

    def parse(
        self,
        source: bytes,
        *,
        path: str,
        format_name: str,
    ) -> Document:
        try:
            path = safe_relative_path(path, "content path")
        except ContractError as error:
            raise ContentSafetyError(str(error)) from error
        if format_name not in FORMAT_NAMES:
            raise ContentSyntaxError(
                "unsupported content format: {}".format(format_name),
                code="unsupported-content-format",
            )
        if not isinstance(source, bytes):
            raise ContentSyntaxError("content source must be bytes")
        if len(source) > DEFAULT_LIMITS.max_input_bytes:
            raise ContentSyntaxError(
                "content source exceeds the {} byte limit".format(
                    DEFAULT_LIMITS.max_input_bytes
                ),
                code="content-size-limit",
            )
        try:
            source.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ContentSyntaxError(
                "content source is not valid UTF-8",
                code="invalid-content-encoding",
            ) from error
        if b"\x00" in source:
            raise ContentSyntaxError(
                "content source contains NUL", code="content-nul-byte"
            )
        if source.startswith(b"\xef\xbb\xbf"):
            raise ContentSyntaxError(
                "content source starts with a UTF-8 byte-order mark",
                code="content-byte-order-mark",
            )

        lines = _physical_lines(source)
        if len(lines) > DEFAULT_LIMITS.max_lines:
            raise ContentSyntaxError(
                "content source exceeds the {} line limit".format(
                    DEFAULT_LIMITS.max_lines
                ),
                code="content-line-limit",
            )
        for line in lines:
            if len(line.raw) > DEFAULT_LIMITS.max_line_bytes:
                raise ContentSyntaxError(
                    "content line {} exceeds the {} byte limit".format(
                        line.number, DEFAULT_LIMITS.max_line_bytes
                    ),
                    code="content-line-size-limit",
                )
        diagnostics = []
        comments = []
        comment_bytes = 0
        nodes: list[Node] = []
        top_level = []
        stack: list[Node] = []
        message: Optional[tuple[Optional[Node], PhysicalLine, int]] = None
        multipart = 0
        saw_map_header = False

        if format_name == "map" and (
            not lines or lines[0].raw != b"arch map\n"
        ):
            diagnostics.append(
                diagnostic(
                    path,
                    SourceSpan(0, 0, 1),
                    "invalid-map-sentinel",
                    "first physical line must be exactly arch map followed by LF",
                )
            )

        for line in lines:
            text = line.content.decode("utf-8")
            stripped = text.strip()
            anchored = not line.content.startswith((b" ", b"\t"))

            if message is not None:
                owner, opener, body_start = message
                if anchored and stripped.casefold() == "endmsg":
                    if owner is not None:
                        body = source[body_start:line.start_byte]
                        if len(body) > DEFAULT_LIMITS.max_string_bytes:
                            raise ContentSyntaxError(
                                "message body exceeds the {} byte limit".format(
                                    DEFAULT_LIMITS.max_string_bytes
                                ),
                                code="content-message-size-limit",
                            )
                        owner.messages.append(
                            MessageRecord(
                                SourceSpan(
                                    opener.start_byte,
                                    line.end_byte,
                                    opener.number,
                                ),
                                body_start,
                                line.start_byte,
                                body.decode("utf-8"),
                                True,
                            )
                        )
                        owner.body_order.append(("message", len(owner.messages) - 1))
                    message = None
                continue

            if not stripped:
                continue
            if line.content.startswith(b"#"):
                comments.append(line.span)
                comment_bytes += len(line.raw)
                if (
                    len(comments) > DEFAULT_LIMITS.max_comments
                    or comment_bytes > DEFAULT_LIMITS.max_comment_bytes
                ):
                    raise ContentSyntaxError(
                        "content comments exceed the shared parser limit",
                        code="content-comment-limit",
                    )
                if stack:
                    stack[-1].body_order.append(("comment", len(comments) - 1))
                continue

            folded = stripped.casefold()
            if anchored and folded == "msg":
                owner = stack[-1] if stack else None
                if owner is None:
                    diagnostics.append(
                        diagnostic(
                            path,
                            line.span,
                            "message-outside-block",
                            "msg appears outside a block",
                        )
                    )
                message = (owner, line, line.end_byte)
                continue
            if anchored and folded == "endmsg":
                diagnostics.append(
                    diagnostic(
                        path,
                        line.span,
                        "unexpected-endmsg",
                        "endmsg has no matching msg",
                    )
                )
                continue

            parts = stripped.split(None, 1)
            token = parts[0].casefold()
            value = parts[1].strip() if len(parts) == 2 else ""
            opener_kind = None
            opener_name = ""
            if (
                anchored
                and format_name == "archetype"
                and token == "object"
                and value
            ):
                opener_kind = "object"
                opener_name = value
            elif (
                anchored
                and format_name == "archetype"
                and token == "arch"
                and value
                and stack
            ):
                opener_kind = "object"
                opener_name = value
            elif anchored and format_name == "map" and token == "arch" and value:
                if not saw_map_header:
                    if (
                        line.number != 1
                        or line.raw != b"arch map\n"
                        or value.casefold() != "map"
                        or stack
                    ):
                        diagnostics.append(
                            diagnostic(
                                path,
                                line.span,
                                "invalid-map-header",
                                "first significant record must be arch map",
                            )
                        )
                    else:
                        opener_kind = "map-header"
                        opener_name = "map"
                        saw_map_header = True
                else:
                    opener_kind = "object"
                    opener_name = value

            if opener_kind is not None:
                if len(nodes) >= DEFAULT_LIMITS.max_nodes:
                    raise ContentSyntaxError(
                        "content node count exceeds the shared parser limit",
                        code="content-node-limit",
                    )
                handle = "node-{:06d}".format(len(nodes) + 1)
                parent_handle = stack[-1].handle if stack else None
                node = Node(
                    handle=handle,
                    kind=opener_kind,
                    name=opener_name,
                    depth=len(stack),
                    parent_handle=parent_handle,
                    opener_span=line.span,
                    span=line.span,
                )
                nodes.append(node)
                if stack:
                    stack[-1].child_handles.append(handle)
                    stack[-1].body_order.append(("child", handle))
                else:
                    top_level.append(handle)
                stack.append(node)
                if len(stack) > DEFAULT_LIMITS.max_depth:
                    raise ContentSyntaxError(
                        "content nesting exceeds the shared parser limit",
                        code="content-depth-limit",
                    )
                if len(stack) > 10:
                    diagnostics.append(
                        diagnostic(
                            path,
                            line.span,
                            "nesting-depth",
                            "object nesting exceeds the server loader limit",
                        )
                    )
                continue

            if anchored and folded == "more":
                multipart += 1
                if format_name != "archetype" or stack:
                    diagnostics.append(
                        diagnostic(
                            path,
                            line.span,
                            "misplaced-more",
                            "More must separate top-level archetype parts",
                        )
                    )
                continue
            if anchored and folded == "end":
                if not stack:
                    diagnostics.append(
                        diagnostic(
                            path,
                            line.span,
                            "unexpected-end",
                            "end has no open block",
                        )
                    )
                else:
                    node = stack.pop()
                    node.closer_span = line.span
                    node.span = SourceSpan(
                        node.opener_span.start_byte,
                        line.end_byte,
                        node.opener_span.line,
                    )
                continue

            if not stack:
                diagnostics.append(
                    diagnostic(
                        path,
                        line.span,
                        "field-outside-block",
                        "field appears outside a block",
                    )
                )
                continue

            record = self._field_record(line, stack[-1], path, diagnostics)
            if len(stack[-1].fields) >= DEFAULT_LIMITS.max_object_keys:
                raise ContentSyntaxError(
                    "{} has more than {} properties".format(
                        stack[-1].handle, DEFAULT_LIMITS.max_object_keys
                    ),
                    code="content-property-limit",
                )
            stack[-1].fields.append(record)
            stack[-1].body_order.append(("property", len(stack[-1].fields) - 1))

        if message is not None:
            owner, opener, body_start = message
            if owner is not None:
                if len(source) - body_start > DEFAULT_LIMITS.max_string_bytes:
                    raise ContentSyntaxError(
                        "message body exceeds the {} byte limit".format(
                            DEFAULT_LIMITS.max_string_bytes
                        ),
                        code="content-message-size-limit",
                    )
                owner.messages.append(
                    MessageRecord(
                        SourceSpan(opener.start_byte, len(source), opener.number),
                        body_start,
                        len(source),
                        source[body_start:].decode("utf-8"),
                        False,
                    )
                )
                owner.body_order.append(("message", len(owner.messages) - 1))
            diagnostics.append(
                diagnostic(
                    path,
                    opener.span,
                    "unterminated-message",
                    "msg block has no endmsg",
                )
            )
        final_line = lines[-1].number if lines else 1
        for node in reversed(stack):
            node.span = SourceSpan(
                node.opener_span.start_byte,
                len(source),
                node.opener_span.line,
            )
            diagnostics.append(
                diagnostic(
                    path,
                    node.opener_span,
                    "unterminated-block",
                    "{} block has no end".format(node.kind),
                )
            )
        if format_name == "map" and not saw_map_header:
            diagnostics.append(
                diagnostic(
                    path,
                    SourceSpan(0, 0, 1),
                    "missing-map-header",
                    "map has no arch map header",
                )
            )
        if not source:
            diagnostics.append(
                diagnostic(
                    path,
                    SourceSpan(0, 0, final_line),
                    "empty-document",
                    "authored document is empty",
                )
            )

        self._duplicate_diagnostics(nodes, path, diagnostics)
        if len(diagnostics) > DEFAULT_LIMITS.max_collection_items:
            raise ContentSyntaxError(
                "content diagnostics exceed the shared parser limit",
                code="content-diagnostic-limit",
            )
        return Document(
            path=path,
            format=format_name,
            logical_id=_logical_id(path, format_name),
            source=source,
            lines=lines,
            nodes=nodes,
            top_level_handles=top_level,
            comments=comments,
            diagnostics=diagnostics,
            multipart_continuations=multipart,
        )

    def _field_record(
        self,
        line: PhysicalLine,
        node: Node,
        path: str,
        diagnostics: list[Mapping[str, Any]],
    ) -> FieldRecord:
        content = line.content
        leading = len(content) - len(content.lstrip(b" \t"))
        name_end = leading
        while name_end < len(content) and content[name_end : name_end + 1] not in (
            b" ",
            b"\t",
        ):
            name_end += 1
        value_start = name_end
        while value_start < len(content) and content[value_start : value_start + 1] in (
            b" ",
            b"\t",
        ):
            value_start += 1
        value_end = len(content.rstrip(b" \t"))
        if value_end < value_start:
            value_end = value_start
        name = content[leading:name_end].decode("utf-8")
        value = content[value_start:value_end].decode("utf-8")
        name_span = SourceSpan(
            line.start_byte + leading,
            line.start_byte + name_end,
            line.number,
            leading + 1,
        )
        value_span = SourceSpan(
            line.start_byte + value_start,
            line.start_byte + value_end,
            line.number,
            value_start + 1,
        )
        field = (
            self._fields.get((node.context, name.casefold()))
            if leading == 0
            else None
        )
        custom_id = None
        if field is None:
            if (
                leading == 0
                and node.context == "map-header"
                and TILE_FIELD_RE.fullmatch(name.casefold())
            ):
                index = int(name.rsplit("_", 1)[1])
                if not 1 <= index <= 10:
                    diagnostics.append(
                        diagnostic(
                            path,
                            name_span,
                            "tile-index-out-of-range",
                            "tile path index must be between 1 and 10",
                        )
                    )
                field_id = (
                    "map-header.tile_path_{}".format(index)
                    if 1 <= index <= 10
                    else "map-header.tile_path"
                )
                typed = self._typed_value(
                    value,
                    "reference",
                    {},
                    path,
                    value_span,
                    field_id,
                    diagnostics,
                )
                return FieldRecord(
                    name,
                    value,
                    line.span,
                    name_span,
                    value_span,
                    field_id=field_id,
                    value_kind="reference",
                    typed_value=typed,
                    status="active",
                )
            extension = self._extensions.get(name) if leading == 0 else None
            if extension is not None and node.context == "object":
                custom_id = extension["custom_id"]
                kind = extension["value_kind"]
                constraints = {
                    key: extension[key]
                    for key in ("minimum", "maximum")
                    if key in extension
                }
                status = extension["status"]
            else:
                normalized = name.casefold()
                custom_name = (
                    normalized
                    if PORTABLE_CUSTOM_RE.fullmatch(normalized)
                    else "raw-" + name.encode("utf-8").hex()
                )
                custom_id = "legacy-extension." + custom_name
                kind = "string"
                constraints = {}
                status = "custom"
                if node.context == "map-header":
                    diagnostics.append(
                        diagnostic(
                            path,
                            name_span,
                            "unknown-map-header-field",
                            "the server logs and ignores an unknown map-header record",
                            severity="warning",
                        )
                    )
            typed = self._typed_value(
                value,
                kind,
                constraints,
                path,
                value_span,
                name,
                diagnostics,
            )
            return FieldRecord(
                name,
                value,
                line.span,
                name_span,
                value_span,
                custom_id=custom_id,
                value_kind=kind,
                typed_value=typed,
                status=status,
            )

        typed = self._typed_value(
            value,
            field["value_kind"],
            field["constraints"],
            path,
            value_span,
            field["field_id"],
            diagnostics,
        )
        return FieldRecord(
            name,
            value,
            line.span,
            name_span,
            value_span,
            field_id=field["field_id"],
            value_kind=field["value_kind"],
            typed_value=typed,
            status=field["status"],
        )

    @staticmethod
    def _typed_value(
        value: str,
        kind: str,
        constraints: Mapping[str, Any],
        path: str,
        span: SourceSpan,
        label: str,
        diagnostics: list[Mapping[str, Any]],
    ) -> Any:
        parsed: Any = value
        code = None
        message = None
        if kind == "boolean":
            if value not in ("0", "1"):
                code = "invalid-boolean"
                message = "{} must use legacy boolean 0 or 1".format(label)
            else:
                parsed = value == "1"
        elif kind == "integer":
            if (
                len(value.encode("utf-8")) > DEFAULT_LIMITS.max_number_bytes
                or INTEGER_RE.fullmatch(value) is None
            ):
                code = "invalid-integer"
                message = "{} must be a strict integer".format(label)
            else:
                parsed = int(value)
                if abs(parsed) > DEFAULT_LIMITS.max_safe_integer:
                    code = "integer-out-of-range"
                    message = "{} exceeds the cross-language safe range".format(
                        label
                    )
        elif kind == "number":
            if (
                len(value.encode("utf-8")) > DEFAULT_LIMITS.max_number_bytes
                or NUMBER_RE.fullmatch(value) is None
            ):
                code = "invalid-number"
                message = "{} must be a strict finite number".format(label)
            else:
                parsed = float(value)
                if not math.isfinite(parsed):
                    code = "invalid-number"
                    message = "{} must be a strict finite number".format(label)
        elif kind in ("reference", "string"):
            if not value:
                code = "empty-field-value"
                message = "{} requires a value".format(label)
            else:
                violation = text_constraint_violation(value, constraints, label)
                if violation is not None:
                    code, message = violation

        if code is None and isinstance(parsed, (int, float)) and not isinstance(
            parsed, bool
        ):
            minimum = constraints.get("minimum")
            maximum = constraints.get("maximum")
            if minimum is not None and parsed < minimum:
                code = "field-below-minimum"
                message = "{} is below {}".format(label, minimum)
            elif maximum is not None and parsed > maximum:
                code = "field-above-maximum"
                message = "{} exceeds {}".format(label, maximum)
        if code is not None:
            diagnostics.append(diagnostic(path, span, code, message or code))
            return value
        return parsed

    @staticmethod
    def _duplicate_diagnostics(
        nodes: Sequence[Node],
        path: str,
        diagnostics: list[Mapping[str, Any]],
    ) -> None:
        for node in nodes:
            seen: Dict[str, FieldRecord] = {}
            for record in node.fields:
                identity = record.field_id or record.custom_id or record.name
                if identity == "map-header.tile_path":
                    identity = record.name.casefold()
                previous = seen.get(identity)
                if previous is None:
                    seen[identity] = record
                    continue
                diagnostics.append(
                    diagnostic(
                        path,
                        record.name_span,
                        "duplicate-property",
                        "{} duplicates a property at line {}".format(
                            identity, previous.span.line
                        ),
                        related=(
                            {
                                "path": path,
                                "line": previous.span.line,
                                "column": previous.name_span.column,
                            },
                        ),
                        severity="warning",
                    )
                )


def parse_bytes(
    source: bytes,
    *,
    path: str,
    format_name: str,
    schema_root: Path = PACKAGE_ROOT,
) -> Document:
    return _cached_parser(schema_root.resolve(strict=True)).parse(
        source, path=path, format_name=format_name
    )


@lru_cache(maxsize=8)
def _cached_parser(schema_root: Path) -> LegacyParser:
    """Reuse immutable field metadata across project-scale parsing."""

    return LegacyParser(schema_root)


def parse_file(
    root: Path,
    relative: str,
    *,
    format_name: str,
    schema_root: Path = PACKAGE_ROOT,
) -> Document:
    root = root.resolve(strict=True)
    path = confined_file(root, relative, "authored content input")
    return parse_bytes(
        path.read_bytes(),
        path=relative,
        format_name=format_name,
        schema_root=schema_root,
    )
