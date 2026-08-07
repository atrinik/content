"""Strict, dependency-free validation for the content interchange contracts.

The contract files are portable JSON Schema Draft 2020-12 documents.  Atrinik's
baseline CI deliberately has no Python package installation step, so this module
implements the closed JSON Schema subset used by those documents.  Unknown
schema keywords fail validation instead of being silently ignored.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Dict, Iterable, Mapping, Sequence, Tuple


SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
SCHEMA_ID_PREFIX = "https://atrinik.org/schema/content/v1/"
SCHEMA_NAMES = (
    "diagnostic",
    "error",
    "inspection",
    "patch",
    "semantic-comparison",
)
MAX_JSON_BYTES = 4 * 1024 * 1024
SUPPORTED_SCHEMA_KEYS = {
    "$defs",
    "$id",
    "$ref",
    "$schema",
    "additionalProperties",
    "const",
    "description",
    "enum",
    "items",
    "maxItems",
    "maximum",
    "minItems",
    "minimum",
    "minLength",
    "oneOf",
    "pattern",
    "properties",
    "required",
    "title",
    "type",
}


class ContractError(ValueError):
    """A malformed schema, contract document, corpus, or inventory."""


def _reject_constant(value: str) -> None:
    raise ContractError("non-standard JSON constant: {}".format(value))


def _reject_duplicate_keys(pairs: Sequence[Tuple[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError("duplicate JSON key: {}".format(key))
        result[key] = value
    return result


def load_json(path: Path) -> Any:
    """Read bounded UTF-8 JSON and reject duplicate object keys."""

    if path.is_symlink() or not path.is_file():
        raise ContractError("contract input must be a regular non-symlink file: {}".format(path))
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ContractError("contract input exceeds size limit: {}".format(path))
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ContractError("cannot read contract JSON {}: {}".format(path, error)) from error


def safe_relative_path(value: object, context: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ContractError("{} must be a non-empty trimmed path".format(context))
    if "\\" in value or "\x00" in value:
        raise ContractError("{} must use portable POSIX path separators".format(context))
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in ("", ".", "..") for part in path.parts)
    ):
        raise ContractError("{} must be repository-relative and confined".format(context))
    return path.as_posix()


def confined_file(root: Path, relative: object, context: str) -> Path:
    """Resolve a manifest path without permitting missing files or links."""

    root = root.resolve(strict=True)
    relative_path = safe_relative_path(relative, context)
    path = root.joinpath(*PurePosixPath(relative_path).parts)
    current = root
    for part in PurePosixPath(relative_path).parts:
        current /= part
        if current.is_symlink():
            raise ContractError(
                "{} must not traverse a symlink: {}".format(context, current)
            )
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (FileNotFoundError, ValueError) as error:
        raise ContractError(
            "{} is missing or escapes its root: {}".format(context, path)
        ) from error
    if not resolved.is_file():
        raise ContractError("{} must be a regular non-symlink file: {}".format(context, path))
    return resolved


def _schema_children(schema: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    for key in ("properties", "$defs"):
        value = schema.get(key, {})
        if isinstance(value, dict):
            for child in value.values():
                if isinstance(child, dict):
                    yield child
    items = schema.get("items")
    if isinstance(items, dict):
        yield items
    additional = schema.get("additionalProperties")
    if isinstance(additional, dict):
        yield additional
    one_of = schema.get("oneOf", [])
    if isinstance(one_of, list):
        for child in one_of:
            if isinstance(child, dict):
                yield child


def validate_schema(schema: object, expected_name: str) -> Mapping[str, Any]:
    """Validate the closed schema authoring subset and stable schema identity."""

    if not isinstance(schema, dict):
        raise ContractError("{} schema root must be an object".format(expected_name))
    if schema.get("$schema") != SCHEMA_DIALECT:
        raise ContractError("{} schema must use Draft 2020-12".format(expected_name))
    expected_id = SCHEMA_ID_PREFIX + expected_name + ".schema.json"
    if schema.get("$id") != expected_id:
        raise ContractError("{} schema has unexpected $id".format(expected_name))
    if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
        raise ContractError("{} schema root must be a closed object".format(expected_name))

    pending = [(schema, expected_name)]
    while pending:
        current, context = pending.pop()
        unknown = set(current) - SUPPORTED_SCHEMA_KEYS
        if unknown:
            raise ContractError(
                "{} schema uses unsupported keywords: {}".format(
                    context, ", ".join(sorted(unknown))
                )
            )
        type_name = current.get("type")
        if type_name is not None and type_name not in (
            "array",
            "boolean",
            "integer",
            "null",
            "number",
            "object",
            "string",
        ):
            raise ContractError("{} schema has unsupported type".format(context))
        for key in ("title", "description"):
            if key in current and not isinstance(current[key], str):
                raise ContractError("{} schema {} must be text".format(context, key))
        for key in ("properties", "$defs"):
            if key not in current:
                continue
            children = current[key]
            if not isinstance(children, dict) or any(
                not isinstance(name, str) or not isinstance(child, dict)
                for name, child in children.items()
            ):
                raise ContractError(
                    "{} schema {} must contain object schemas".format(context, key)
                )
        if "items" in current and not isinstance(current["items"], dict):
            raise ContractError("{} schema items must be an object".format(context))
        additional = current.get("additionalProperties")
        if "additionalProperties" in current and not isinstance(
            additional, (bool, dict)
        ):
            raise ContractError(
                "{} schema additionalProperties must be boolean or an object".format(
                    context
                )
            )
        alternatives = current.get("oneOf")
        if alternatives is not None and (
            not isinstance(alternatives, list)
            or not alternatives
            or any(not isinstance(candidate, dict) for candidate in alternatives)
        ):
            raise ContractError(
                "{} schema oneOf must contain object schemas".format(context)
            )
        required = current.get("required")
        if required is not None and (
            not isinstance(required, list)
            or any(not isinstance(item, str) for item in required)
            or len(required) != len(set(required))
        ):
            raise ContractError(
                "{} schema required must be unique text keys".format(context)
            )
        enumeration = current.get("enum")
        if enumeration is not None and (
            not isinstance(enumeration, list) or not enumeration
        ):
            raise ContractError("{} schema enum must be non-empty".format(context))
        if isinstance(enumeration, list) and len(
            {json.dumps(item, sort_keys=True) for item in enumeration}
        ) != len(enumeration):
            raise ContractError("{} schema enum must be unique".format(context))
        for key in ("minItems", "maxItems", "minLength"):
            if key in current and (
                not isinstance(current[key], int)
                or isinstance(current[key], bool)
                or current[key] < 0
            ):
                raise ContractError(
                    "{} schema {} must be a non-negative integer".format(context, key)
                )
        for key in ("minimum", "maximum"):
            if key in current and (
                not isinstance(current[key], (int, float))
                or isinstance(current[key], bool)
            ):
                raise ContractError(
                    "{} schema {} must be numeric".format(context, key)
                )
        if (
            isinstance(current.get("minItems"), int)
            and isinstance(current.get("maxItems"), int)
            and current["minItems"] > current["maxItems"]
        ):
            raise ContractError("{} schema item bounds are reversed".format(context))
        if (
            isinstance(current.get("minimum"), (int, float))
            and isinstance(current.get("maximum"), (int, float))
            and current["minimum"] > current["maximum"]
        ):
            raise ContractError("{} schema numeric bounds are reversed".format(context))
        pattern = current.get("pattern")
        if pattern is not None:
            if not isinstance(pattern, str):
                raise ContractError("{} schema pattern must be text".format(context))
            try:
                re.compile(pattern)
            except re.error as error:
                raise ContractError(
                    "{} schema pattern is invalid".format(context)
                ) from error
        reference = current.get("$ref")
        if reference is not None and (
            not isinstance(reference, str) or not reference.startswith("#/$defs/")
        ):
            raise ContractError("{} schema has a non-local $ref".format(context))
        if reference is not None and set(current) != {"$ref"}:
            raise ContractError(
                "{} schema reference cannot have ignored sibling keywords".format(
                    context
                )
            )
        for child in _schema_children(current):
            pending.append((child, context))
    return schema


def _resolve_reference(root_schema: Mapping[str, Any], reference: str) -> Mapping[str, Any]:
    current: Any = root_schema
    for part in reference.removeprefix("#/").split("/"):
        if not isinstance(current, dict) or part not in current:
            raise ContractError("schema reference does not exist: {}".format(reference))
        current = current[part]
    if not isinstance(current, dict):
        raise ContractError("schema reference is not an object: {}".format(reference))
    return current


def _matches_type(value: object, type_name: str) -> bool:
    if type_name == "null":
        return value is None
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "array":
        return isinstance(value, list)
    if type_name == "object":
        return isinstance(value, dict)
    return False


def validate_instance(
    value: object,
    schema: Mapping[str, Any],
    *,
    root_schema: Mapping[str, Any] | None = None,
    context: str = "$",
) -> None:
    """Validate an instance against the supported closed JSON Schema subset."""

    root_schema = root_schema or schema
    reference = schema.get("$ref")
    if isinstance(reference, str):
        validate_instance(
            value,
            _resolve_reference(root_schema, reference),
            root_schema=root_schema,
            context=context,
        )
        return

    alternatives = schema.get("oneOf")
    if isinstance(alternatives, list):
        matches = 0
        for candidate in alternatives:
            try:
                validate_instance(
                    value, candidate, root_schema=root_schema, context=context
                )
            except ContractError:
                continue
            matches += 1
        if matches != 1:
            raise ContractError("{} must match exactly one schema alternative".format(context))

    if "const" in schema and value != schema["const"]:
        raise ContractError("{} must equal {!r}".format(context, schema["const"]))
    if "enum" in schema and value not in schema["enum"]:
        raise ContractError("{} is not an allowed value".format(context))

    type_name = schema.get("type")
    if isinstance(type_name, str) and not _matches_type(value, type_name):
        raise ContractError("{} must be {}".format(context, type_name))

    if isinstance(value, dict):
        required = schema.get("required", [])
        if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
            raise ContractError("{} schema required list is invalid".format(context))
        missing = sorted(set(required) - set(value))
        if missing:
            raise ContractError("{} is missing required keys: {}".format(context, missing))
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            raise ContractError("{} schema properties must be an object".format(context))
        extras = set(value) - set(properties)
        additional = schema.get("additionalProperties", True)
        if extras and additional is False:
            raise ContractError("{} has unexpected keys: {}".format(context, sorted(extras)))
        for key, item in value.items():
            child = properties.get(key)
            if child is None and isinstance(additional, dict):
                child = additional
            if isinstance(child, dict):
                validate_instance(
                    item,
                    child,
                    root_schema=root_schema,
                    context="{}.{}".format(context, key),
                )

    if isinstance(value, list):
        minimum = schema.get("minItems")
        maximum = schema.get("maxItems")
        if isinstance(minimum, int) and len(value) < minimum:
            raise ContractError("{} has too few items".format(context))
        if isinstance(maximum, int) and len(value) > maximum:
            raise ContractError("{} has too many items".format(context))
        items = schema.get("items")
        if isinstance(items, dict):
            for index, item in enumerate(value):
                validate_instance(
                    item,
                    items,
                    root_schema=root_schema,
                    context="{}[{}]".format(context, index),
                )

    if isinstance(value, str):
        minimum = schema.get("minLength")
        if isinstance(minimum, int) and len(value) < minimum:
            raise ContractError("{} is shorter than permitted".format(context))
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.search(pattern, value) is None:
            raise ContractError("{} does not match its required pattern".format(context))

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, (int, float)) and value < minimum:
            raise ContractError("{} is below its minimum".format(context))
        if isinstance(maximum, (int, float)) and value > maximum:
            raise ContractError("{} exceeds its maximum".format(context))


def _decode_replacement(operation: Mapping[str, Any], index: int) -> bytes:
    try:
        return base64.b64decode(operation["replacement_base64"], validate=True)
    except (binascii.Error, ValueError) as error:
        raise ContractError(
            "patch operation {} has invalid base64".format(index)
        ) from error


def _validate_contract_semantics(kind: str, value: Mapping[str, Any]) -> None:
    """Enforce relationships that are awkward or unsafe to express in JSON Schema."""

    if kind == "patch":
        safe_relative_path(value["path"], "patch.path")
        previous_end = 0
        for index, operation in enumerate(value["operations"]):
            start = operation["start"]
            end = operation["end"]
            if start > end or start < previous_end:
                raise ContractError("patch operations must be ordered and non-overlapping")
            if operation["kind"] == "insert" and start != end:
                raise ContractError("insert patch operations must have an empty source range")
            if operation["kind"] != "insert" and start == end:
                raise ContractError(
                    "delete and replace operations require a non-empty source range"
                )
            replacement = _decode_replacement(operation, index)
            if operation["kind"] == "delete" and replacement:
                raise ContractError("delete patch operations cannot contain replacement bytes")
            if operation["kind"] != "delete" and not replacement:
                raise ContractError(
                    "insert and replace operations require replacement bytes"
                )
            previous_end = end
    elif kind in ("diagnostic", "error"):
        diagnostics = [value] if kind == "diagnostic" else value["diagnostics"]
        for diagnostic in diagnostics:
            safe_relative_path(diagnostic["location"]["path"], "diagnostic path")
            for location in diagnostic["related"]:
                safe_relative_path(location["path"], "related diagnostic path")
    elif kind == "inspection":
        safe_relative_path(value["document"]["path"], "inspection path")
        if value["comments"] != sorted(set(value["comments"])):
            raise ContractError("inspection comment lines must be sorted and unique")
        if value["unknown_fields"] != sorted(set(value["unknown_fields"])):
            raise ContractError("inspection unknown fields must be sorted and unique")
        previous_start = 0
        for index, node in enumerate(value["nodes"]):
            start = node["start_line"]
            end = node["end_line"]
            if start < previous_start or (end is not None and end < start):
                raise ContractError(
                    "inspection nodes must be source-ordered with valid ranges"
                )
            field_lines = [field["line"] for field in node["fields"]]
            if field_lines != sorted(field_lines) or any(
                line < start or (end is not None and line > end)
                for line in field_lines
            ):
                raise ContractError(
                    "inspection node {} has unordered or out-of-range fields".format(
                        index
                    )
                )
            previous_start = start
    elif kind == "semantic-comparison":
        ignored = value["ignored_representation"]
        if ignored != sorted(set(ignored)):
            raise ContractError(
                "semantic ignored representations must be sorted and unique"
            )
        if value["equivalent"] != (not value["differences"]):
            raise ContractError(
                "semantic equivalence must agree with the difference list"
            )


def apply_byte_patch(
    source: bytes,
    patch: Mapping[str, Any],
    schema: Mapping[str, Any],
) -> bytes:
    """Apply a validated, digest-bound patch without touching the filesystem."""

    if not isinstance(source, bytes):
        raise ContractError("patch source must be bytes")
    validate_instance(patch, schema)
    _validate_contract_semantics("patch", patch)
    source_digest = "sha256:" + hashlib.sha256(source).hexdigest()
    if patch["base_sha256"] != source_digest:
        raise ContractError("patch base digest does not match source bytes")

    result = bytearray()
    cursor = 0
    for index, operation in enumerate(patch["operations"]):
        start = operation["start"]
        end = operation["end"]
        if end > len(source):
            raise ContractError(
                "patch operation {} exceeds source size".format(index)
            )
        result.extend(source[cursor:start])
        if operation["kind"] != "delete":
            result.extend(_decode_replacement(operation, index))
        cursor = end
    result.extend(source[cursor:])
    output = bytes(result)
    result_digest = "sha256:" + hashlib.sha256(output).hexdigest()
    if patch["result_sha256"] != result_digest:
        raise ContractError("patch result digest does not match output bytes")
    return output


def validate_contract_document(
    kind: str,
    value: object,
    schemas: Mapping[str, Mapping[str, Any]],
) -> None:
    """Validate one public contract document and its semantic relationships."""

    if kind not in schemas:
        raise ContractError("unknown contract kind: {}".format(kind))
    validate_instance(value, schemas[kind])
    if not isinstance(value, dict):
        raise ContractError("{} contract must be an object".format(kind))
    _validate_contract_semantics(kind, value)
    if kind in ("error", "inspection"):
        for diagnostic in value["diagnostics"]:
            validate_instance(diagnostic, schemas["diagnostic"])
            _validate_contract_semantics("diagnostic", diagnostic)


def validate_contracts(root: Path) -> Dict[str, Mapping[str, Any]]:
    """Load schemas and validate every committed example document."""

    contract_root = (root / "contracts" / "content-v1").resolve(strict=True)
    schemas: Dict[str, Mapping[str, Any]] = {}
    for name in SCHEMA_NAMES:
        path = contract_root / "schemas" / "{}.schema.json".format(name)
        schemas[name] = validate_schema(load_json(path), name)

    examples = load_json(contract_root / "examples" / "manifest.json")
    if not isinstance(examples, dict) or set(examples) != {"schema_version", "examples"}:
        raise ContractError("contract example manifest must have exact root keys")
    if examples["schema_version"] != 1 or not isinstance(examples["examples"], list):
        raise ContractError("contract example manifest is unsupported")
    seen = set()
    example_kinds = []
    for index, entry in enumerate(examples["examples"]):
        context = "contract example {}".format(index)
        if not isinstance(entry, dict) or set(entry) != {"kind", "path"}:
            raise ContractError("{} must contain kind and path".format(context))
        kind = entry["kind"]
        if kind not in schemas:
            raise ContractError("{} has unknown kind".format(context))
        example_kinds.append(kind)
        path = confined_file(contract_root, entry["path"], context)
        relative = path.relative_to(contract_root).as_posix()
        if relative in seen:
            raise ContractError("duplicate contract example: {}".format(relative))
        seen.add(relative)
        value = load_json(path)
        validate_contract_document(kind, value, schemas)
    if example_kinds != sorted(set(example_kinds)) or set(example_kinds) != set(
        SCHEMA_NAMES
    ):
        raise ContractError(
            "every contract schema requires one canonically ordered example"
        )
    return schemas
