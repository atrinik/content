"""Whole-corpus legacy-to-schema coverage and value validation."""

from __future__ import annotations

import math
from pathlib import Path
import re
from typing import Any, Dict, Mapping

from tools.content_contracts.contracts import ContractError, confined_file, load_json
from tools.content_contracts.corpus import inspect_document

from .model import SchemaError, field_definitions, load_schema_source


INTEGER_RE = re.compile(r"^[+-]?[0-9]+$")
NUMBER_RE = re.compile(
    r"^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$"
)


def _validate_value(
    value: str,
    field: Mapping[str, Any],
    path: str,
    line: int,
) -> None:
    field_id = field["field_id"]
    kind = field["value_kind"]
    if field["status"] == "legacy-ignored":
        if not value:
            raise SchemaError("{}:{}: {} requires a legacy value".format(path, line, field_id))
        return
    if kind == "boolean":
        if value not in ("0", "1"):
            raise SchemaError("{}:{}: {} is not legacy boolean 0/1".format(path, line, field_id))
        parsed: int | float = int(value)
    elif kind == "integer":
        if INTEGER_RE.fullmatch(value) is None:
            raise SchemaError("{}:{}: {} is not a strict integer".format(path, line, field_id))
        parsed = int(value)
    elif kind == "number":
        if NUMBER_RE.fullmatch(value) is None:
            raise SchemaError("{}:{}: {} is not a strict number".format(path, line, field_id))
        parsed = float(value)
        if not math.isfinite(parsed):
            raise SchemaError("{}:{}: {} is not finite".format(path, line, field_id))
    elif kind in ("reference", "string"):
        if not value:
            raise SchemaError("{}:{}: {} is empty".format(path, line, field_id))
        return
    else:
        raise SchemaError("legacy field {} has unsupported value kind".format(field_id))
    minimum = field["constraints"].get("minimum")
    maximum = field["constraints"].get("maximum")
    if minimum is not None and parsed < minimum:
        raise SchemaError("{}:{}: {} is below {}".format(path, line, field_id, minimum))
    if maximum is not None and parsed > maximum:
        raise SchemaError("{}:{}: {} exceeds {}".format(path, line, field_id, maximum))


def _authored_documents(root: Path) -> list[tuple[Path, str]]:
    documents = []
    for tree, format_name in (("arch", "archetype"), ("maps", "map")):
        directory = root / tree
        if directory.is_symlink() or not directory.is_dir():
            raise SchemaError("authored content root is missing or unsafe: {}".format(tree))
        for path in sorted(directory.rglob("*")):
            if path.is_symlink():
                raise SchemaError(
                    "authored content must not contain symbolic links: {}".format(
                        path.relative_to(root)
                    )
                )
            if not path.is_file():
                continue
            if format_name == "archetype":
                if path.suffix == ".arc":
                    documents.append((path, format_name))
                continue
            try:
                with path.open("rb") as source_file:
                    if source_file.read(9) == b"arch map\n":
                        documents.append((path, format_name))
            except OSError as error:
                raise SchemaError(
                    "cannot inspect authored document {}".format(path)
                ) from error
    return documents


def audit_corpus(root: Path) -> Mapping[str, Any]:
    """Prove every current authored record is typed or explicitly migrated."""

    root = root.resolve(strict=True)
    source = load_schema_source(root)
    grammar = load_json(
        confined_file(
            root,
            "contracts/content-v1/grammar-inventory.json",
            "legacy grammar inventory",
        )
    )
    fields = field_definitions(source)
    by_context_name = {
        (field["context"], field["legacy_name"]): field
        for field in fields
        if field["legacy_name"] is not None
    }
    extensions = source["legacy_extensions"]
    extension_counts: Dict[str, int] = {name: 0 for name in extensions}
    field_counts: Dict[str, int] = {}
    file_counts = {"archetype": 0, "map": 0}
    object_count = 0
    property_count = 0

    documents = _authored_documents(root)
    for path, format_name in documents:
        relative = path.relative_to(root).as_posix()
        try:
            inspection, summary = inspect_document(
                root / "contracts/content-v1",
                format_name,
                grammar,
                display_path=relative,
                source_bytes=path.read_bytes(),
            )
        except (OSError, ContractError) as error:
            raise SchemaError(
                "{}: cannot inspect authored content: {}".format(relative, error)
            ) from error
        if not summary["accepted"]:
            raise SchemaError("{} is outside the locked legacy grammar".format(relative))
        file_counts[format_name] += 1
        object_count += summary["objects"]
        for node in inspection["nodes"]:
            context = "map-header" if node["kind"] == "map-header" else "object"
            for record in node["fields"]:
                property_count += 1
                legacy_name = record["name"]
                normalized = legacy_name.casefold()
                field = by_context_name.get((context, normalized))
                if field is None:
                    if context != "object" or legacy_name not in extensions:
                        raise SchemaError(
                            "{}:{}: unexplained legacy field {}".format(
                                relative, record["line"], legacy_name
                            )
                        )
                    extension = extensions[legacy_name]
                    extension_counts[legacy_name] += 1
                    extension_field = {
                        "field_id": "custom." + extension["custom_id"],
                        "value_kind": extension["value_kind"],
                        "status": "active",
                        "constraints": {
                            key: extension[key]
                            for key in ("minimum", "maximum")
                            if key in extension
                        },
                    }
                    _validate_value(
                        record["value"], extension_field, relative, record["line"]
                    )
                    continue
                _validate_value(record["value"], field, relative, record["line"])
                field_counts[field["field_id"]] = field_counts.get(field["field_id"], 0) + 1

    unused_extensions = sorted(
        name for name, count in extension_counts.items() if count == 0
    )
    if unused_extensions:
        raise SchemaError(
            "legacy extension mappings are stale: {}".format(", ".join(unused_extensions))
        )
    return {
        "schema_version": 1,
        "files": dict(sorted(file_counts.items())),
        "objects": object_count,
        "properties": property_count,
        "typed_field_ids_used": len(field_counts),
        "legacy_extensions": dict(sorted(extension_counts.items())),
        "unexplained_fields": [],
    }
