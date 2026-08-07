"""Lossless physical records and typed semantic views for authored content."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence


@dataclass(frozen=True)
class SourceSpan:
    """A half-open byte span with a one-based source location."""

    start_byte: int
    end_byte: int
    line: int
    column: int = 1

    def to_dict(self) -> Mapping[str, int]:
        return {
            "start_byte": self.start_byte,
            "end_byte": self.end_byte,
            "line": self.line,
            "column": self.column,
        }


@dataclass(frozen=True)
class PhysicalLine:
    """One exact physical record, including its original line ending."""

    number: int
    start_byte: int
    end_byte: int
    content: bytes
    ending: bytes

    @property
    def span(self) -> SourceSpan:
        return SourceSpan(self.start_byte, self.end_byte, self.number)

    @property
    def raw(self) -> bytes:
        return self.content + self.ending


@dataclass
class FieldRecord:
    """One property record with exact name/value byte ranges."""

    name: str
    value: str
    span: SourceSpan
    name_span: SourceSpan
    value_span: SourceSpan
    field_id: Optional[str] = None
    custom_id: Optional[str] = None
    value_kind: str = "string"
    typed_value: Any = None
    status: str = "custom"

    def to_dict(self) -> Mapping[str, Any]:
        return {
            "name": self.name,
            "field_id": self.field_id,
            "custom_id": self.custom_id,
            "raw_value": self.value,
            "typed_value": self.typed_value,
            "value_kind": self.value_kind,
            "status": self.status,
            "span": self.span.to_dict(),
            "value_span": self.value_span.to_dict(),
        }


@dataclass
class MessageRecord:
    """A raw multiline message delimited by msg/endmsg."""

    span: SourceSpan
    body_start_byte: int
    body_end_byte: int
    text: str
    terminated: bool

    def to_dict(self) -> Mapping[str, Any]:
        return {
            "span": self.span.to_dict(),
            "body_start_byte": self.body_start_byte,
            "body_end_byte": self.body_end_byte,
            "text": self.text,
            "terminated": self.terminated,
        }


@dataclass
class Node:
    """A map header or object block in source order."""

    handle: str
    kind: str
    name: str
    depth: int
    parent_handle: Optional[str]
    opener_span: SourceSpan
    span: SourceSpan
    closer_span: Optional[SourceSpan] = None
    fields: list[FieldRecord] = field(default_factory=list)
    messages: list[MessageRecord] = field(default_factory=list)
    child_handles: list[str] = field(default_factory=list)
    body_order: list[tuple[str, str | int]] = field(default_factory=list)
    fingerprint: str = ""

    @property
    def context(self) -> str:
        return "map-header" if self.kind == "map-header" else "object"

    def fields_named(self, name: str) -> Sequence[FieldRecord]:
        folded = name.casefold()
        return tuple(field for field in self.fields if field.name.casefold() == folded)

    def field_ids(self, field_id: str) -> Sequence[FieldRecord]:
        return tuple(field for field in self.fields if field.field_id == field_id)

    def last_value(self, name: str, default: Any = None) -> Any:
        records = self.fields_named(name)
        return records[-1].value if records else default

    def to_dict(self) -> Mapping[str, Any]:
        body_order = []
        for kind, target in self.body_order:
            if kind == "child":
                body_order.append({"kind": kind, "handle": target})
            else:
                body_order.append({"kind": kind, "index": target})
        return {
            "handle": self.handle,
            "fingerprint": self.fingerprint,
            "kind": self.kind,
            "name": self.name,
            "depth": self.depth,
            "parent_handle": self.parent_handle,
            "span": self.span.to_dict(),
            "properties": [record.to_dict() for record in self.fields],
            "messages": [message.to_dict() for message in self.messages],
            "children": list(self.child_handles),
            "body_order": body_order,
        }


@dataclass
class Document:
    """One byte-lossless document and its typed, source-located view."""

    path: str
    format: str
    logical_id: str
    source: bytes
    lines: Sequence[PhysicalLine]
    nodes: list[Node]
    top_level_handles: list[str]
    comments: list[SourceSpan]
    diagnostics: list[Mapping[str, Any]]
    multipart_continuations: int = 0

    def __post_init__(self) -> None:
        self._by_handle = {node.handle: node for node in self.nodes}
        for node in self.nodes:
            raw = self.source[node.span.start_byte : node.span.end_byte]
            identity = "{}\0{}\0{}\0".format(
                node.kind, node.name, node.parent_handle or ""
            ).encode("utf-8")
            node.fingerprint = "sha256:" + hashlib.sha256(identity + raw).hexdigest()

    @property
    def byte_sha256(self) -> str:
        return "sha256:" + hashlib.sha256(self.source).hexdigest()

    @property
    def valid(self) -> bool:
        return not any(item["severity"] == "error" for item in self.diagnostics)

    @property
    def map_header(self) -> Optional[Node]:
        return next((node for node in self.nodes if node.kind == "map-header"), None)

    @property
    def objects(self) -> Sequence[Node]:
        return tuple(node for node in self.nodes if node.kind == "object")

    def node(self, handle: str) -> Node:
        return self._by_handle[handle]

    def serialize(self) -> bytes:
        """Return the exact source bytes for an unchanged document."""

        return self.source

    def line_endings(self) -> str:
        crlf = self.source.count(b"\r\n")
        lf = self.source.count(b"\n") - crlf
        if crlf and lf:
            return "mixed"
        if crlf:
            return "crlf"
        if lf:
            return "lf"
        return "none"

    def preferred_line_ending(self) -> bytes:
        endings = [line.ending for line in self.lines if line.ending]
        if not endings:
            return b"\n"
        crlf = sum(ending == b"\r\n" for ending in endings)
        return b"\r\n" if crlf > len(endings) // 2 else b"\n"

    def summary(self) -> Mapping[str, Any]:
        coordinates: Dict[tuple[int, int], int] = {}
        exits = 0
        tile_links = []
        maximum_depth = 0
        messages = 0
        unknown = set()
        for node in self.nodes:
            maximum_depth = max(maximum_depth, node.depth + 1)
            messages += sum(message.terminated for message in node.messages)
            for record in node.fields:
                if record.field_id is None:
                    unknown.add(record.name)
            if node.kind == "map-header":
                tile_links.extend(
                    record.value
                    for record in node.fields
                    if record.name.casefold().startswith("tile_path_")
                )
            elif self.format == "map" and node.depth == 0:
                if node.name.casefold() == "exit":
                    exits += 1
                try:
                    coordinate = (
                        int(node.last_value("x", "0")),
                        int(node.last_value("y", "0")),
                    )
                except ValueError:
                    continue
                coordinates[coordinate] = coordinates.get(coordinate, 0) + 1
        return {
            "accepted": self.valid,
            "comments": len(self.comments),
            "diagnostic_codes": sorted(item["code"] for item in self.diagnostics),
            "exits": exits,
            "line_endings": self.line_endings(),
            "maximum_depth": maximum_depth,
            "messages": messages,
            "multipart_continuations": self.multipart_continuations,
            "objects": len(self.objects),
            "stacked_coordinates": sorted(
                "{},{}".format(x, y)
                for (x, y), count in coordinates.items()
                if count > 1
            ),
            "terminal_newline": self.source.endswith(b"\n"),
            "tile_links": sorted(tile_links),
            "unknown_fields": sorted(unknown),
        }

    def inspection(self) -> Mapping[str, Any]:
        return {
            "schema_version": 1,
            "kind": "document-inspection",
            "document": {
                "path": self.path,
                "format": self.format,
                "logical_id": self.logical_id,
                "byte_sha256": self.byte_sha256,
                "size": len(self.source),
                "line_endings": self.line_endings(),
                "terminal_newline": self.source.endswith(b"\n"),
                "valid": self.valid,
            },
            "nodes": [node.to_dict() for node in self.nodes],
            "top_level": list(self.top_level_handles),
            "multipart_continuations": self.multipart_continuations,
            "comments": [span.to_dict() for span in self.comments],
            "diagnostics": list(self.diagnostics),
        }

    def semantic_tree(self) -> Sequence[Mapping[str, Any]]:
        """Return a representation-neutral ordered tree for semantic diffs."""

        def convert(node: Node) -> Mapping[str, Any]:
            properties = [
                {
                    "id": field.field_id or field.custom_id or field.name,
                    "value": field.typed_value,
                }
                for field in node.fields
            ]
            return {
                "kind": node.kind,
                "name": node.name,
                "properties": properties,
                "messages": [
                    "\n".join(line.rstrip() for line in message.text.splitlines())
                    for message in node.messages
                ],
                "children": [convert(self.node(handle)) for handle in node.child_handles],
            }

        return tuple(convert(self.node(handle)) for handle in self.top_level_handles)


def diagnostic(
    path: str,
    span: SourceSpan,
    code: str,
    message: str,
    *,
    severity: str = "error",
    related: Iterable[Mapping[str, Any]] = (),
) -> Mapping[str, Any]:
    """Construct the shared v1 diagnostic contract."""

    return {
        "schema_version": 1,
        "code": code,
        "severity": severity,
        "message": message,
        "location": {
            "path": path,
            "line": span.line,
            "column": span.column,
        },
        "related": list(related),
    }
