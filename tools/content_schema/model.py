"""Strict loading and normalization for the authoritative field source."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from tools.content_contracts.contracts import confined_file, load_json
from tools.syntax_evaluation.limits import DEFAULT_LIMITS


SOURCE_PATH = Path("schemas/authored-content-v1/source.json")
GRAMMAR_PATH = Path("contracts/content-v1/grammar-inventory.json")
FIELD_ID_RE = re.compile(r"^[a-z][a-z0-9-]*\.[a-z][a-z0-9_]*$")
NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
DOMAIN_RE = re.compile(r"^[a-z][a-z0-9-]*$")
VALUE_KINDS = {
    "boolean",
    "enum",
    "integer",
    "number",
    "object",
    "reference",
    "reference-list",
    "string",
    "string-list",
}


class SchemaError(ValueError):
    """The source schema, generated metadata, or corpus is inconsistent."""


def _closed(value: object, keys: Iterable[str], context: str) -> Mapping[str, Any]:
    expected = set(keys)
    if not isinstance(value, dict) or set(value) != expected:
        raise SchemaError(
            "{} must contain exactly: {}".format(context, ", ".join(sorted(expected)))
        )
    return value


def _sorted_text(
    value: object, context: str, *, pattern: re.Pattern[str] | None = None
) -> List[str]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item for item in value)
        or value != sorted(set(value))
    ):
        raise SchemaError("{} must be sorted unique non-empty text".format(context))
    if pattern is not None and any(pattern.fullmatch(item) is None for item in value):
        raise SchemaError("{} contains a non-portable identifier".format(context))
    return value


def _number(value: object, context: str) -> int | float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or (isinstance(value, float) and not math.isfinite(value))
    ):
        raise SchemaError("{} must be numeric".format(context))
    return value


def _field_groups(
    source: Mapping[str, Any], context: str
) -> tuple[Dict[str, str], Dict[str, Sequence[str]], set[str]]:
    value = source["{}_fields".format(context)]
    expected = {"boolean", "integer", "references", "string"}
    if context == "object":
        expected.update(("legacy_ignored", "number"))
    else:
        expected.add("patterns")
    value = _closed(value, expected, "{} fields".format(context))
    kinds: Dict[str, str] = {}
    references: Dict[str, Sequence[str]] = {}
    legacy = set()
    for kind in ("boolean", "integer", "number", "string"):
        if kind not in value:
            continue
        names = _sorted_text(value[kind], "{}.{}".format(context, kind), pattern=NAME_RE)
        for name in names:
            if name in kinds:
                raise SchemaError("{} is assigned more than one value kind".format(name))
            kinds[name] = kind
    reference_map = value["references"]
    if not isinstance(reference_map, dict) or not reference_map:
        raise SchemaError("{}.references must be a non-empty object".format(context))
    if list(reference_map) != sorted(reference_map):
        raise SchemaError("{}.references must be sorted".format(context))
    for name, domains in reference_map.items():
        if NAME_RE.fullmatch(name) is None or name in kinds:
            raise SchemaError("invalid or duplicate reference field {}".format(name))
        references[name] = tuple(
            _sorted_text(domains, "{}.{} domains".format(context, name), pattern=DOMAIN_RE)
        )
        kinds[name] = "reference"
    if context == "object":
        for name in _sorted_text(
            value["legacy_ignored"], "object.legacy_ignored", pattern=NAME_RE
        ):
            if name in kinds:
                raise SchemaError("{} is both active and legacy ignored".format(name))
            kinds[name] = "string"
            legacy.add(name)
    return kinds, references, legacy


def _validate_registered_features(
    source: Mapping[str, Any], occupied: set[str]
) -> List[Mapping[str, Any]]:
    features = source["registered_features"]
    if not isinstance(features, list) or not features:
        raise SchemaError("registered_features must be a non-empty array")
    ids = []
    normalized = []
    for index, feature in enumerate(features):
        feature = _closed(
            feature,
            {"fields", "id", "owner", "status"},
            "registered feature {}".format(index),
        )
        if (
            not isinstance(feature["id"], str)
            or NAME_RE.fullmatch(feature["id"].replace("-", "_")) is None
            or not isinstance(feature["owner"], str)
            or not feature["owner"]
            or feature["status"] != "reserved"
        ):
            raise SchemaError("registered feature {} has invalid identity".format(index))
        ids.append(feature["id"])
        fields = feature["fields"]
        if not isinstance(fields, list) or not fields:
            raise SchemaError("registered feature {} has no fields".format(feature["id"]))
        feature_field_ids = set()
        for field_index, field in enumerate(fields):
            if not isinstance(field, dict):
                raise SchemaError("registered field must be an object")
            required = {"field_id", "role", "value_kind"}
            allowed = required | {
                "maximum",
                "minimum",
                "reference_domains",
                "values",
            }
            if not required <= set(field) or set(field) - allowed:
                raise SchemaError("registered field {} has unexpected keys".format(field_index))
            field_id = field["field_id"]
            if (
                not isinstance(field_id, str)
                or FIELD_ID_RE.fullmatch(field_id) is None
                or field_id in feature_field_ids
                or field_id in occupied
            ):
                raise SchemaError("registered field IDs must be unique and portable")
            feature_field_ids.add(field_id)
            occupied.add(field_id)
            kind = field["value_kind"]
            if kind not in VALUE_KINDS:
                raise SchemaError("registered field {} has invalid value kind".format(field_id))
            if not isinstance(field["role"], str) or not field["role"]:
                raise SchemaError("registered field {} has no role".format(field_id))
            if kind == "enum":
                values = field.get("values")
                if (
                    not isinstance(values, list)
                    or not values
                    or any(not isinstance(value, str) or not value for value in values)
                    or len(values) != len(set(values))
                ):
                    raise SchemaError("{} values must be unique non-empty text".format(field_id))
            elif "values" in field:
                raise SchemaError("only enum fields may declare values")
            if kind in ("reference", "reference-list"):
                _sorted_text(
                    field.get("reference_domains"),
                    "{} reference domains".format(field_id),
                    pattern=DOMAIN_RE,
                )
            elif "reference_domains" in field:
                raise SchemaError("non-reference field declares reference domains")
            minimum = field.get("minimum")
            maximum = field.get("maximum")
            if minimum is not None:
                _number(minimum, "{} minimum".format(field_id))
            if maximum is not None:
                _number(maximum, "{} maximum".format(field_id))
            if minimum is not None and maximum is not None and minimum > maximum:
                raise SchemaError("{} has reversed bounds".format(field_id))
            if (
                (
                    minimum is not None
                    and minimum < source["value_limits"]["integer_minimum"]
                )
                or (
                    maximum is not None
                    and maximum > source["value_limits"]["integer_maximum"]
                )
            ):
                raise SchemaError("{} exceeds cross-language numeric limits".format(field_id))
        normalized.append(feature)
    if len(ids) != len(set(ids)):
        raise SchemaError("registered feature IDs must be unique")
    return normalized


def load_schema_source(root: Path) -> Mapping[str, Any]:
    """Load, close, and cross-check the single declarative field authority."""

    root = root.resolve(strict=True)
    source = load_json(
        confined_file(root, SOURCE_PATH.as_posix(), "content schema source")
    )
    root_keys = {
        "authority",
        "field_constraints",
        "legacy_extensions",
        "logical_model",
        "map_header_fields",
        "object_fields",
        "registered_features",
        "role_constraints",
        "roles",
        "schema_id",
        "schema_version",
        "value_limits",
    }
    source = _closed(source, root_keys, "schema source")
    if source["schema_version"] != 1 or source["schema_id"] != "atrinik-authored-content-v1":
        raise SchemaError("schema source has unsupported identity")
    authority = _closed(
        source["authority"],
        {"identity_contract", "issue", "legacy_grammar", "syntax_contract"},
        "authority",
    )
    expected_authority = {
        "identity_contract": "docs/CONTENT_IDENTITIES.md",
        "issue": "atrinik/content#15",
        "legacy_grammar": GRAMMAR_PATH.as_posix(),
        "syntax_contract": "docs/AUTHORED_SYNTAX_DECISION.md",
    }
    if authority != expected_authority:
        raise SchemaError("schema authority paths or ownership drifted")
    logical = _closed(
        source["logical_model"],
        {
            "custom_namespace_pattern",
            "document_kinds",
            "object_contexts",
            "ordered_body_records",
            "reserved_namespaces",
        },
        "logical model",
    )
    _sorted_text(logical["document_kinds"], "document kinds", pattern=NAME_RE)
    _sorted_text(logical["object_contexts"], "object contexts")
    _sorted_text(logical["ordered_body_records"], "ordered body records")
    _sorted_text(logical["reserved_namespaces"], "reserved namespaces", pattern=NAME_RE)
    if logical["document_kinds"] != ["archetype", "map"]:
        raise SchemaError("logical document kinds drift from generator support")
    if logical["object_contexts"] != [
        "archetype",
        "multipart-part",
        "nested-inventory",
        "placed-object",
    ]:
        raise SchemaError("logical object contexts drift from generator support")
    if logical["ordered_body_records"] != [
        "comment",
        "custom-property",
        "message",
        "nested-object",
        "standard-property",
    ]:
        raise SchemaError("logical body records drift from generator support")
    if logical["reserved_namespaces"] != ["atrinik"]:
        raise SchemaError("reserved custom namespaces drift from generator support")
    if not isinstance(logical["custom_namespace_pattern"], str):
        raise SchemaError("custom namespace pattern must be text")
    try:
        namespace_re = re.compile(logical["custom_namespace_pattern"])
    except re.error as error:
        raise SchemaError("custom namespace pattern is invalid") from error

    limits = _closed(
        source["value_limits"],
        {
            "array_max_items",
            "integer_maximum",
            "integer_minimum",
            "object_max_properties",
            "string_max_bytes",
        },
        "value limits",
    )
    for key, value in limits.items():
        if not isinstance(value, int) or isinstance(value, bool):
            raise SchemaError("{} must be an integer".format(key))
    if limits["integer_minimum"] >= 0 or limits["integer_maximum"] <= 0:
        raise SchemaError("integer limits must span zero")
    if any(
        limits[key] <= 0
        for key in ("array_max_items", "object_max_properties", "string_max_bytes")
    ):
        raise SchemaError("collection and string limits must be positive")
    expected_limits = {
        "array_max_items": DEFAULT_LIMITS.max_collection_items,
        "integer_maximum": DEFAULT_LIMITS.max_safe_integer,
        "integer_minimum": -DEFAULT_LIMITS.max_safe_integer,
        "object_max_properties": DEFAULT_LIMITS.max_object_keys,
        "string_max_bytes": DEFAULT_LIMITS.max_string_bytes,
    }
    if limits != expected_limits:
        raise SchemaError("schema value limits drift from the #16 parser limits")

    map_kinds, map_references, _ = _field_groups(source, "map_header")
    object_kinds, object_references, legacy_ignored = _field_groups(source, "object")

    patterns = source["map_header_fields"]["patterns"]
    if not isinstance(patterns, list) or len(patterns) != 1:
        raise SchemaError("map-header patterns must declare the one tiled-map family")
    pattern = _closed(
        patterns[0],
        {
            "field_id",
            "index_maximum",
            "index_minimum",
            "legacy_pattern",
            "reference_domains",
            "role",
            "value_kind",
        },
        "map-header field pattern",
    )
    if (
        pattern["field_id"] != "map-header.tile_path"
        or pattern["value_kind"] != "reference"
        or not isinstance(pattern["legacy_pattern"], str)
        or not isinstance(pattern["index_minimum"], int)
        or not isinstance(pattern["index_maximum"], int)
        or pattern["index_minimum"] < 1
        or pattern["index_maximum"] < pattern["index_minimum"]
    ):
        raise SchemaError("map-header tile pattern is malformed")
    try:
        re.compile(pattern["legacy_pattern"])
    except re.error as error:
        raise SchemaError("map-header tile pattern is invalid") from error
    _sorted_text(pattern["reference_domains"], "tile reference domains", pattern=DOMAIN_RE)

    grammar = load_json(
        confined_file(root, GRAMMAR_PATH.as_posix(), "legacy grammar inventory")
    )
    expected_map = sorted(map_kinds)
    expected_object = sorted(object_kinds)
    if grammar["map_header_grammar"]["known_fields"] != expected_map:
        raise SchemaError("map-header schema fields drift from the #17 grammar inventory")
    if grammar["object_grammar"]["known_fields"] != expected_object:
        raise SchemaError("object schema fields drift from the #17 grammar inventory")
    if grammar["map_header_grammar"]["tile_field_pattern"] != pattern["legacy_pattern"]:
        raise SchemaError("tile pattern drifts from the #17 grammar inventory")

    roles = source["roles"]
    if not isinstance(roles, dict) or list(roles) != sorted(roles):
        raise SchemaError("roles must be a sorted object")
    for role, names in roles.items():
        if NAME_RE.fullmatch(role) is None:
            raise SchemaError("invalid field role")
        for name in _sorted_text(names, "{} role".format(role), pattern=NAME_RE):
            if name not in object_kinds:
                raise SchemaError("role {} names unknown field {}".format(role, name))

    constraints = source["field_constraints"]
    if not isinstance(constraints, dict) or list(constraints) != sorted(constraints):
        raise SchemaError("field constraints must be sorted")
    valid_ids = {"map-header." + name for name in map_kinds} | {
        "object." + name for name in object_kinds
    }
    kinds_by_id = {
        **{"map-header." + name: kind for name, kind in map_kinds.items()},
        **{"object." + name: kind for name, kind in object_kinds.items()},
    }
    for field_id, value in constraints.items():
        if field_id not in valid_ids:
            raise SchemaError("constraint names unknown field {}".format(field_id))
        value = _closed(value, set(value), "{} constraints".format(field_id))
        if set(value) - {
            "maximum",
            "maxLength",
            "minimum",
            "minLength",
            "pattern",
        } or not value:
            raise SchemaError("{} has invalid constraints".format(field_id))
        kind = kinds_by_id[field_id]
        minimum = value.get("minimum")
        maximum = value.get("maximum")
        minimum_length = value.get("minLength")
        maximum_length = value.get("maxLength")
        pattern_value = value.get("pattern")
        if kind in ("integer", "number"):
            if any(
                item is not None
                for item in (minimum_length, maximum_length, pattern_value)
            ):
                raise SchemaError(
                    "{} applies text constraints to a number".format(field_id)
                )
        elif kind in ("reference", "string"):
            if (
                minimum is not None
                or maximum is not None
                or all(
                    item is None
                    for item in (minimum_length, maximum_length, pattern_value)
                )
            ):
                raise SchemaError("{} has invalid text constraints".format(field_id))
            for name, length in (
                ("minLength", minimum_length),
                ("maxLength", maximum_length),
            ):
                if length is not None and (
                    not isinstance(length, int) or isinstance(length, bool) or length < 0
                ):
                    raise SchemaError(
                        "{} {} must be a non-negative integer".format(field_id, name)
                    )
                if length is not None and length > limits["string_max_bytes"]:
                    raise SchemaError(
                        "{} {} exceeds the parser string limit".format(field_id, name)
                    )
            if (
                minimum_length is not None
                and maximum_length is not None
                and minimum_length > maximum_length
            ):
                raise SchemaError("{} has reversed text lengths".format(field_id))
            if pattern_value is not None:
                if (
                    not isinstance(pattern_value, str)
                    or not pattern_value.startswith("^")
                    or not pattern_value.endswith("$")
                ):
                    raise SchemaError("{} pattern must be anchored text".format(field_id))
                try:
                    re.compile(pattern_value)
                except re.error as error:
                    raise SchemaError("{} pattern is invalid".format(field_id)) from error
        else:
            raise SchemaError("{} has constraints for an unsupported kind".format(field_id))
        if minimum is not None:
            _number(minimum, "{} minimum".format(field_id))
        if maximum is not None:
            _number(maximum, "{} maximum".format(field_id))
        if minimum is not None and maximum is not None and minimum > maximum:
            raise SchemaError("{} has reversed constraints".format(field_id))
        if (
            (minimum is not None and minimum < limits["integer_minimum"])
            or (maximum is not None and maximum > limits["integer_maximum"])
        ):
            raise SchemaError("{} exceeds cross-language numeric limits".format(field_id))
    role_constraints = source["role_constraints"]
    if not isinstance(role_constraints, dict) or list(role_constraints) != sorted(
        role_constraints
    ):
        raise SchemaError("role constraints must be sorted")
    for role, value in role_constraints.items():
        if role not in roles or set(value) != {"maximum", "minimum"}:
            raise SchemaError("invalid role constraint {}".format(role))
        if _number(value["minimum"], role) > _number(value["maximum"], role):
            raise SchemaError("{} role constraints are reversed".format(role))
        if any(object_kinds[name] not in ("integer", "number") for name in roles[role]):
            raise SchemaError("{} applies numeric bounds to a non-number role".format(role))
        if (
            value["minimum"] < limits["integer_minimum"]
            or value["maximum"] > limits["integer_maximum"]
        ):
            raise SchemaError("{} role exceeds cross-language numeric limits".format(role))

    extensions = source["legacy_extensions"]
    if not isinstance(extensions, dict) or list(extensions) != sorted(extensions):
        raise SchemaError("legacy extensions must be a sorted object")
    custom_ids = set()
    for legacy_name, value in extensions.items():
        if not isinstance(legacy_name, str) or not legacy_name:
            raise SchemaError("legacy extension name is invalid")
        required = {"custom_id", "owner", "status", "value_kind"}
        optional = {"minimum", "maximum", "reference_domains"}
        if (
            not isinstance(value, dict)
            or not required <= set(value)
            or set(value) - required - optional
        ):
            raise SchemaError("legacy extension {} is malformed".format(legacy_name))
        custom_id = value["custom_id"]
        if (
            not isinstance(custom_id, str)
            or custom_id in custom_ids
            or "." not in custom_id
        ):
            raise SchemaError("legacy custom IDs must be unique qualified text")
        namespace, _, name = custom_id.rpartition(".")
        if (
            namespace_re.fullmatch(namespace) is None
            or namespace in logical["reserved_namespaces"]
            or NAME_RE.fullmatch(name) is None
        ):
            raise SchemaError("legacy extension {} has invalid namespace".format(legacy_name))
        custom_ids.add(custom_id)
        if value["value_kind"] not in VALUE_KINDS:
            raise SchemaError("legacy extension has invalid value kind")
        if value["value_kind"] == "reference":
            _sorted_text(
                value.get("reference_domains"),
                "legacy reference domains",
                pattern=DOMAIN_RE,
            )
        elif "reference_domains" in value:
            raise SchemaError("non-reference legacy extension has reference domains")
        minimum = value.get("minimum")
        maximum = value.get("maximum")
        if minimum is not None:
            _number(minimum, "{} minimum".format(legacy_name))
        if maximum is not None:
            _number(maximum, "{} maximum".format(legacy_name))
        if minimum is not None and maximum is not None and minimum > maximum:
            raise SchemaError("legacy extension {} has reversed bounds".format(legacy_name))
        if (
            (minimum is not None and minimum < limits["integer_minimum"])
            or (maximum is not None and maximum > limits["integer_maximum"])
        ):
            raise SchemaError(
                "legacy extension {} exceeds numeric limits".format(legacy_name)
            )
        if not isinstance(value["owner"], str) or not value["owner"]:
            raise SchemaError("legacy extension has no owner")
        if value["status"] not in ("migrate", "remove-after-migration"):
            raise SchemaError("legacy extension has invalid status")

    occupied = set(valid_ids)
    for index in range(pattern["index_minimum"], pattern["index_maximum"] + 1):
        occupied.add("map-header.tile_path_{}".format(index))
    _validate_registered_features(source, occupied)

    # Attach normalized data for internal consumers without changing the
    # serialized declarative authority.
    return {
        **source,
        "_normalized": {
            "legacy_ignored": legacy_ignored,
            "map_kinds": map_kinds,
            "map_references": map_references,
            "object_kinds": object_kinds,
            "object_references": object_references,
        },
    }


def field_definitions(source: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Expand the compact source groups into stable generated field records."""

    normalized = source["_normalized"]
    roles_by_field: Dict[str, List[str]] = {}
    for role, names in source["roles"].items():
        for name in names:
            roles_by_field.setdefault(name, []).append(role)
    definitions: List[Dict[str, Any]] = []

    def add(
        field_id: str,
        context: str,
        legacy_name: str | None,
        kind: str,
        *,
        status: str = "active",
        roles: Sequence[str] = (),
        references: Sequence[str] = (),
        constraints: Mapping[str, Any] | None = None,
        feature: str | None = None,
        enum_values: Sequence[str] = (),
    ) -> None:
        merged_constraints: Dict[str, Any] = {}
        if kind in ("integer", "number"):
            merged_constraints.update(
                {
                    "minimum": source["value_limits"]["integer_minimum"],
                    "maximum": source["value_limits"]["integer_maximum"],
                }
            )
        for role in roles:
            merged_constraints.update(source["role_constraints"].get(role, {}))
        merged_constraints.update(source["field_constraints"].get(field_id, {}))
        merged_constraints.update(constraints or {})
        entry: Dict[str, Any] = {
            "field_id": field_id,
            "context": context,
            "legacy_name": legacy_name,
            "status": status,
            "value_kind": kind,
            "roles": sorted(set(roles) or {"general"}),
            "constraints": dict(sorted(merged_constraints.items())),
            "reference_domains": list(references),
        }
        if feature is not None:
            entry["feature"] = feature
        if enum_values:
            entry["enum_values"] = list(enum_values)
        definitions.append(entry)

    for name, kind in sorted(normalized["map_kinds"].items()):
        roles = []
        if kind == "boolean":
            roles.append("flag")
        if kind == "reference":
            roles.append("reference")
        if name in ("enter_x", "enter_y", "height", "width"):
            roles.append("placement")
        if name in ("bg_music", "name", "weather"):
            roles.append("presentation")
        add(
            "map-header." + name,
            "map-header",
            name,
            kind,
            roles=roles,
            references=normalized["map_references"].get(name, ()),
        )
    pattern = source["map_header_fields"]["patterns"][0]
    for index in range(pattern["index_minimum"], pattern["index_maximum"] + 1):
        name = "tile_path_{}".format(index)
        add(
            "map-header." + name,
            "map-header",
            name,
            "reference",
            roles=("reference", pattern["role"]),
            references=pattern["reference_domains"],
        )
    for name, kind in sorted(normalized["object_kinds"].items()):
        roles = list(roles_by_field.get(name, ()))
        if kind == "boolean":
            roles.append("flag")
        if kind == "reference":
            roles.append("reference")
        status = "legacy-ignored" if name in normalized["legacy_ignored"] else "active"
        if status != "active":
            roles.append("legacy")
        add(
            "object." + name,
            "object",
            name,
            kind,
            status=status,
            roles=roles,
            references=normalized["object_references"].get(name, ()),
        )
    for feature in source["registered_features"]:
        for field in feature["fields"]:
            context, _, _ = field["field_id"].partition(".")
            add(
                field["field_id"],
                context,
                None,
                field["value_kind"],
                status="reserved",
                roles=(field["role"],),
                references=field.get("reference_domains", ()),
                constraints={
                    key: field[key]
                    for key in ("minimum", "maximum")
                    if key in field
                },
                feature=feature["id"],
                enum_values=field.get("values", ()),
            )
    result = sorted(definitions, key=lambda field: field["field_id"])
    ids = [field["field_id"] for field in result]
    if len(ids) != len(set(ids)):
        raise SchemaError("expanded field IDs are not unique")
    return result
