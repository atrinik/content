"""Read-only characterization probes for the legacy ADS parity corpus.

This is deliberately not an authored-content parser or writer.  It records the
observable block structure needed to keep fixtures and expected legacy results
honest until the later lossless core replaces the duplicated consumers.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
from pathlib import Path
import re
from typing import Any, Dict, List, Mapping, MutableMapping, Tuple

from .contracts import (
    ContractError,
    apply_byte_patch,
    confined_file,
    load_json,
    safe_relative_path,
    validate_contract_document,
)


MAX_FIXTURE_BYTES = 1024 * 1024
FORMATS = {"archetype", "map"}


def _diagnostic(
    path: str,
    line: int,
    code: str,
    message: str,
    *,
    severity: str = "error",
) -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "code": code,
        "severity": severity,
        "message": message,
        "location": {"path": path, "line": line, "column": 1},
        "related": [],
    }


def _line_endings(raw: bytes) -> str:
    crlf = raw.count(b"\r\n")
    lf = raw.count(b"\n") - crlf
    if crlf and lf:
        return "mixed"
    if crlf:
        return "crlf"
    if lf:
        return "lf"
    return "none"


def _physical_lines(text: str) -> List[str]:
    """Split only on the LF byte recognized by the legacy record grammars."""

    parts = text.split("\n")
    lines = [part + "\n" for part in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    return lines


def inspect_document(
    path: Path,
    format_name: str,
    grammar: Mapping[str, Any],
    *,
    display_path: str | None = None,
    source_bytes: bytes | None = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Return a contract-shaped inspection plus a stable parity summary."""

    if format_name not in FORMATS:
        raise ContractError("unsupported corpus format: {}".format(format_name))
    if source_bytes is None:
        if path.is_symlink() or not path.is_file():
            raise ContractError(
                "corpus input must be a regular non-symlink file: {}".format(path)
            )
        if path.stat().st_size > MAX_FIXTURE_BYTES:
            raise ContractError("corpus input exceeds size limit: {}".format(path))
        raw = path.read_bytes()
    else:
        if not isinstance(source_bytes, bytes):
            raise ContractError("inline corpus input must be bytes")
        raw = source_bytes
    if len(raw) > MAX_FIXTURE_BYTES:
        raise ContractError("corpus input exceeds size limit: {}".format(path))
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ContractError("corpus input is not UTF-8: {}".format(path)) from error
    if "\x00" in text:
        raise ContractError("corpus input contains NUL: {}".format(path))

    relative = display_path or path.as_posix()
    object_fields = set(grammar["object_grammar"]["known_fields"])
    header_fields = set(grammar["map_header_grammar"]["known_fields"])
    diagnostics: List[Dict[str, Any]] = []
    nodes: List[MutableMapping[str, Any]] = []
    stack: List[MutableMapping[str, Any]] = []
    comments: List[int] = []
    unknown_fields = set()
    message_start = None
    message_count = 0
    multipart_count = 0
    maximum_depth = 0
    saw_map_header = False

    lines = _physical_lines(text)
    if format_name == "map" and (not lines or lines[0] != "arch map\n"):
        diagnostics.append(
            _diagnostic(
                relative,
                1,
                "invalid-map-sentinel",
                "first physical line must be exactly arch map followed by LF",
            )
        )
    for line_number, raw_line in enumerate(lines, 1):
        if raw_line.endswith("\n"):
            line = raw_line[:-1]
            if line.endswith("\r"):
                line = line[:-1]
        else:
            line = raw_line
        stripped = line.strip()
        anchored = line == line.lstrip(" \t")
        if message_start is not None:
            if anchored and stripped.casefold() == "endmsg":
                message_start = None
                message_count += 1
            continue
        if not stripped:
            continue
        if line.startswith("#"):
            comments.append(line_number)
            continue
        folded = stripped.casefold()
        if anchored and folded == "msg":
            if not stack:
                diagnostics.append(
                    _diagnostic(
                        relative,
                        line_number,
                        "message-outside-block",
                        "msg appears outside a block",
                    )
                )
            message_start = line_number
            continue
        if anchored and folded == "endmsg":
            diagnostics.append(
                _diagnostic(
                    relative,
                    line_number,
                    "unexpected-endmsg",
                    "endmsg has no matching msg",
                )
            )
            continue

        opener = None
        name = ""
        parts = stripped.split(None, 1)
        token = parts[0].casefold()
        value = parts[1].strip() if len(parts) == 2 else ""
        if anchored and format_name == "archetype" and token == "object" and value:
            opener = "object"
            name = value
        elif anchored and format_name == "archetype" and token == "arch" and value and stack:
            opener = "object"
            name = value
        elif anchored and format_name == "map" and token == "arch" and value:
            if not saw_map_header:
                if (
                    line_number != 1
                    or raw_line != "arch map\n"
                    or value.casefold() != "map"
                    or stack
                ):
                    diagnostics.append(
                        _diagnostic(
                            relative,
                            line_number,
                            "invalid-map-header",
                            "first significant record must be arch map",
                        )
                    )
                else:
                    opener = "map-header"
                    name = "map"
                    saw_map_header = True
            else:
                opener = "object"
                name = value

        if opener is not None:
            node: MutableMapping[str, Any] = {
                "kind": opener,
                "name": name,
                "start_line": line_number,
                "end_line": None,
                "depth": len(stack),
                "fields": [],
            }
            nodes.append(node)
            stack.append(node)
            maximum_depth = max(maximum_depth, len(stack))
            if (
                format_name == "archetype"
                and len(stack)
                > grammar["object_grammar"]["maximum_nesting_depth"]
            ):
                diagnostics.append(
                    _diagnostic(
                        relative,
                        line_number,
                        "nesting-depth",
                        "object nesting exceeds the server loader limit",
                    )
                )
            continue

        if anchored and folded == "more":
            multipart_count += 1
            if format_name != "archetype" or stack:
                diagnostics.append(
                    _diagnostic(
                        relative,
                        line_number,
                        "misplaced-more",
                        "More must separate top-level archetype parts",
                    )
                )
            continue
        if anchored and folded == "end":
            if not stack:
                diagnostics.append(
                    _diagnostic(relative, line_number, "unexpected-end", "end has no open block")
                )
            else:
                stack.pop()["end_line"] = line_number
            continue

        if not stack:
            diagnostics.append(
                _diagnostic(
                    relative,
                    line_number,
                    "field-outside-block",
                    "field appears outside a block",
                )
            )
            continue
        field_name = parts[0]
        field_value = parts[1].strip() if len(parts) == 2 else ""
        stack[-1]["fields"].append(
            {"name": field_name, "value": field_value, "line": line_number}
        )
        is_header = stack[-1]["kind"] == "map-header"
        known = header_fields if is_header else object_fields
        normalized_field = field_name.casefold()
        if not anchored or (
            normalized_field not in known
            and not (
                is_header
                and re.fullmatch(r"tile_path_[0-9]{1,2}", normalized_field)
            )
        ):
            unknown_fields.add(field_name)
            if is_header:
                diagnostics.append(
                    _diagnostic(
                        relative,
                        line_number,
                        "unknown-map-header-field",
                        "the server logs and ignores an unknown map-header record",
                        severity="warning",
                    )
                )

    if message_start is not None:
        diagnostics.append(
            _diagnostic(relative, message_start, "unterminated-message", "msg block has no endmsg")
        )
    for node in reversed(stack):
        diagnostics.append(
            _diagnostic(
                relative,
                int(node["start_line"]),
                "unterminated-block",
                "{} block has no end".format(node["kind"]),
            )
        )
    if format_name == "map" and not saw_map_header:
        diagnostics.append(
            _diagnostic(relative, 1, "missing-map-header", "map has no arch map header")
        )

    object_nodes = [node for node in nodes if node["kind"] == "object"]
    top_level = (
        [node for node in object_nodes if node["depth"] == 0]
        if format_name == "map"
        else []
    )
    coordinates: Dict[Tuple[int, int], int] = {}
    exits = 0
    for node in top_level:
        values = {field["name"].casefold(): field["value"] for field in node["fields"]}
        if str(node["name"]).casefold() == "exit":
            exits += 1
        try:
            coordinate = (int(values.get("x", "0")), int(values.get("y", "0")))
        except ValueError:
            continue
        coordinates[coordinate] = coordinates.get(coordinate, 0) + 1
    stacked_coordinates = sorted(
        "{},{}".format(x, y)
        for (x, y), count in coordinates.items()
        if count > 1
    )
    tile_links = sorted(
        field["value"]
        for node in nodes
        if node["kind"] == "map-header"
        for field in node["fields"]
        if re.fullmatch(r"tile_path_[0-9]{1,2}", field["name"].casefold())
    )

    digest = hashlib.sha256(raw).hexdigest()
    inspection: Dict[str, Any] = {
        "schema_version": 1,
        "document": {
            "path": relative,
            "format": format_name,
            "byte_sha256": "sha256:" + digest,
            "size": len(raw),
            "line_endings": _line_endings(raw),
            "terminal_newline": raw.endswith(b"\n"),
        },
        "nodes": nodes,
        "comments": comments,
        "unknown_fields": sorted(unknown_fields),
        "diagnostics": diagnostics,
    }
    summary = {
        "accepted": not any(
            diagnostic["severity"] == "error" for diagnostic in diagnostics
        ),
        "comments": len(comments),
        "diagnostic_codes": sorted(item["code"] for item in diagnostics),
        "exits": exits,
        "line_endings": inspection["document"]["line_endings"],
        "maximum_depth": maximum_depth,
        "messages": message_count,
        "multipart_continuations": multipart_count,
        "objects": len(object_nodes),
        "stacked_coordinates": stacked_coordinates,
        "terminal_newline": inspection["document"]["terminal_newline"],
        "tile_links": tile_links,
        "unknown_fields": sorted(unknown_fields),
    }
    return inspection, summary


def _validate_inventory(root: Path, name: str) -> Mapping[str, Any]:
    path = root / "contracts" / "content-v1" / "{}.json".format(name)
    value = load_json(path)
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ContractError("{} inventory has unsupported schema".format(name))
    return value


def validate_corpus(root: Path, schemas: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    """Validate inventory coverage, fixtures, observations, and no-op hashes."""

    contract_root = (root / "contracts" / "content-v1").resolve(strict=True)
    grammar = _validate_inventory(root, "grammar-inventory")
    consumers = _validate_inventory(root, "consumer-inventory")
    grammar_keys = {
        "authority",
        "encoding",
        "grammar_id",
        "load_modes",
        "map_header_grammar",
        "object_grammar",
        "required_corpus_features",
        "schema_version",
    }
    if set(grammar) != grammar_keys:
        raise ContractError("grammar inventory has unexpected root keys")
    authority = grammar["authority"]
    if not isinstance(authority, dict) or set(authority) != {
        "map_header_loader",
        "map_writer",
        "object_loader",
        "object_writer",
    }:
        raise ContractError("grammar authority inventory is incomplete")
    if any(not isinstance(value, str) or not value.strip() for value in authority.values()):
        raise ContractError("grammar authority locations must be non-empty text")
    if not isinstance(grammar.get("object_grammar", {}).get("known_fields"), list):
        raise ContractError("grammar inventory has no object field list")
    if not isinstance(grammar.get("map_header_grammar", {}).get("known_fields"), list):
        raise ContractError("grammar inventory has no map-header field list")
    if grammar["object_grammar"]["known_fields"] != sorted(
        set(grammar["object_grammar"]["known_fields"])
    ):
        raise ContractError("object grammar fields must be sorted and unique")
    if grammar["map_header_grammar"]["known_fields"] != sorted(
        set(grammar["map_header_grammar"]["known_fields"])
    ):
        raise ContractError("map-header grammar fields must be sorted and unique")
    load_modes = grammar["load_modes"]
    load_mode_keys = {"entry_point", "name", "observable_difference"}
    if (
        not isinstance(load_modes, list)
        or not load_modes
        or any(
            not isinstance(entry, dict)
            or set(entry) != load_mode_keys
            or any(not isinstance(value, str) or not value.strip() for value in entry.values())
            for entry in load_modes
        )
    ):
        raise ContractError("grammar load-mode inventory is malformed")
    load_mode_names = [entry["name"] for entry in load_modes]
    if load_mode_names != sorted(set(load_mode_names)):
        raise ContractError("grammar load-mode names must be sorted and unique")
    required_features = grammar["required_corpus_features"]
    if (
        not isinstance(required_features, list)
        or required_features != sorted(set(required_features))
    ):
        raise ContractError("required corpus features must be sorted and unique")
    if set(consumers) != {
        "consumers",
        "reviewed_non_consumers",
        "schema_version",
        "survey",
    }:
        raise ContractError("consumer inventory has unexpected root keys")
    survey = consumers["survey"]
    if not isinstance(survey, dict) or set(survey) != {
        "method",
        "reviewed_repositories",
        "scope",
    }:
        raise ContractError("consumer survey is malformed")
    if any(
        not isinstance(survey[field], str) or not survey[field].strip()
        for field in ("method", "scope")
    ):
        raise ContractError("consumer survey descriptions must be non-empty text")
    reviewed_repositories = survey["reviewed_repositories"]
    if (
        not isinstance(reviewed_repositories, list)
        or reviewed_repositories != sorted(set(reviewed_repositories))
    ):
        raise ContractError("reviewed repositories must be sorted and unique")
    non_consumers = consumers["reviewed_non_consumers"]
    if not isinstance(non_consumers, list) or not non_consumers:
        raise ContractError("reviewed non-consumer inventory must be non-empty")
    non_consumer_ids = []
    for index, entry in enumerate(non_consumers):
        if not isinstance(entry, dict) or set(entry) != {"reason", "repository"}:
            raise ContractError(
                "reviewed non-consumer {} is malformed".format(index)
            )
        if any(not isinstance(value, str) or not value.strip() for value in entry.values()):
            raise ContractError(
                "reviewed non-consumer {} must contain non-empty text".format(index)
            )
        non_consumer_ids.append(entry["repository"])
    if non_consumer_ids != sorted(set(non_consumer_ids)):
        raise ContractError("reviewed non-consumers must be sorted and unique")
    entries = consumers.get("consumers")
    if not isinstance(entries, list) or not entries:
        raise ContractError("consumer inventory must be non-empty")
    consumer_keys = {
        "behavior",
        "formats",
        "id",
        "locations",
        "parity_requirement",
        "repository",
        "roles",
        "status",
    }
    for index, entry in enumerate(entries):
        context = "consumer inventory entry {}".format(index)
        if not isinstance(entry, dict) or set(entry) != consumer_keys:
            raise ContractError("{} has unexpected keys".format(context))
        for field in ("behavior", "id", "parity_requirement", "repository", "status"):
            if not isinstance(entry[field], str) or not entry[field].strip():
                raise ContractError("{}.{} must be non-empty text".format(context, field))
        for field in ("formats", "locations", "roles"):
            if (
                not isinstance(entry[field], list)
                or not entry[field]
                or entry[field] != sorted(set(entry[field]))
            ):
                raise ContractError("{}.{} must be sorted and unique".format(context, field))
        for location in entry["locations"]:
            if "#" in location:
                path, _, symbol = location.partition("#")
                safe_path = path
                if not symbol:
                    raise ContractError("{} has an empty location symbol".format(context))
            else:
                safe_path = location
            safe_relative_path(safe_path, "{} location".format(context))
    consumer_ids = [entry["id"] for entry in entries]
    if consumer_ids != sorted(set(consumer_ids)):
        raise ContractError("consumer inventory IDs must be sorted and unique")
    required_roles = {"analyzer", "checker", "collector", "loader", "writer"}
    actual_roles = {role for entry in entries for role in entry["roles"]}
    if not required_roles <= actual_roles:
        raise ContractError("consumer inventory omits required roles")

    manifest = load_json(contract_root / "corpus" / "manifest.json")
    if not isinstance(manifest, dict) or set(manifest) != {"schema_version", "fixtures"}:
        raise ContractError("corpus manifest must have exact root keys")
    if manifest["schema_version"] != 1 or not isinstance(manifest["fixtures"], list):
        raise ContractError("corpus manifest has unsupported schema")
    seen = set()
    fixture_ids = []
    reports = []
    feature_coverage = set()
    load_mode_coverage = set()
    known_load_modes = set(load_mode_names)
    for index, entry in enumerate(manifest["fixtures"]):
        context = "corpus fixture {}".format(index)
        required = {
            "byte_sha256",
            "expected",
            "features",
            "format",
            "id",
            "legacy_baselines",
            "load_modes",
            "source",
        }
        if not isinstance(entry, dict) or set(entry) != required:
            raise ContractError("{} has unexpected keys".format(context))
        identifier = entry["id"]
        if (
            not isinstance(identifier, str)
            or re.fullmatch(r"[a-z0-9][a-z0-9-]*", identifier) is None
        ):
            raise ContractError("{} has invalid ID".format(context))
        if identifier in seen:
            raise ContractError("duplicate corpus fixture ID: {}".format(identifier))
        seen.add(identifier)
        fixture_ids.append(identifier)
        if entry["format"] not in FORMATS:
            raise ContractError("{} has unsupported format".format(context))
        if not isinstance(entry["features"], list) or entry["features"] != sorted(
            set(entry["features"])
        ):
            raise ContractError("{} features must be sorted and unique".format(context))
        feature_coverage.update(entry["features"])
        if (
            not isinstance(entry["load_modes"], list)
            or not entry["load_modes"]
            or entry["load_modes"] != sorted(set(entry["load_modes"]))
            or not set(entry["load_modes"]) <= known_load_modes
        ):
            raise ContractError(
                "{} load modes must be known, sorted, and unique".format(context)
            )
        load_mode_coverage.update(entry["load_modes"])
        source = entry["source"]
        if not isinstance(source, dict) or len(source) != 1:
            raise ContractError("{} source must select exactly one representation".format(context))
        path = None
        if set(source) == {"path"}:
            path = confined_file(contract_root, source["path"], context)
            if path.stat().st_size > MAX_FIXTURE_BYTES:
                raise ContractError("{} source exceeds size limit".format(context))
            raw = path.read_bytes()
            display_path = path.relative_to(contract_root).as_posix()
            before = (
                "sha256:" + hashlib.sha256(raw).hexdigest(),
                path.stat().st_mtime_ns,
            )
        elif set(source) == {"base64"} and isinstance(source["base64"], str):
            try:
                raw = base64.b64decode(source["base64"], validate=True)
            except (binascii.Error, ValueError) as error:
                raise ContractError("{} has invalid base64 source".format(context)) from error
            display_path = "corpus/inline/{}.ads".format(identifier)
            before = ("sha256:" + hashlib.sha256(raw).hexdigest(), None)
        else:
            raise ContractError("{} source must be path or base64".format(context))
        digest = "sha256:" + hashlib.sha256(raw).hexdigest()
        if entry["byte_sha256"] != digest:
            raise ContractError("{} byte hash differs from manifest".format(context))
        if "attribution" in entry["features"]:
            if path is None:
                raise ContractError(
                    "{} attribution fixture must use a source path".format(context)
                )
            license_path = path.parent / "LICENSE"
            if (
                license_path.is_symlink()
                or not license_path.is_file()
                or license_path.stat().st_size == 0
                or license_path.stat().st_size > MAX_FIXTURE_BYTES
            ):
                raise ContractError("{} has no adjacent non-empty LICENSE".format(context))
        inspection, summary = inspect_document(
            path or Path(display_path),
            entry["format"],
            grammar,
            display_path=display_path,
            source_bytes=raw if path is None else None,
        )
        validate_contract_document("inspection", inspection, schemas)
        no_op_patch = {
            "schema_version": 1,
            "path": display_path,
            "base_sha256": digest,
            "result_sha256": digest,
            "operations": [],
        }
        if apply_byte_patch(raw, no_op_patch, schemas["patch"]) != raw:
            raise ContractError("{} no-op patch changed source bytes".format(context))
        if summary != entry["expected"]:
            raise ContractError(
                "{} observation drifted:\nexpected={!r}\nactual={!r}".format(
                    context, entry["expected"], summary
                )
            )
        baselines = entry["legacy_baselines"]
        if not isinstance(baselines, dict) or set(baselines) != {"map-checker", "server"}:
            raise ContractError("{} must record server and map-checker baselines".format(context))
        for consumer, baseline in baselines.items():
            if not isinstance(baseline, dict) or set(baseline) != {"accepted", "notes"}:
                raise ContractError("{} {} baseline is malformed".format(context, consumer))
            if not isinstance(baseline["accepted"], bool) or not isinstance(
                baseline["notes"], str
            ):
                raise ContractError("{} {} baseline has invalid values".format(context, consumer))
        if path is None:
            after = ("sha256:" + hashlib.sha256(raw).hexdigest(), None)
        else:
            after = (
                "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
                path.stat().st_mtime_ns,
            )
        if before != after:
            raise ContractError("{} was modified by read-only inspection".format(context))
        reports.append(
            {
                "id": identifier,
                "inspection": inspection,
                "load_modes": entry["load_modes"],
                "no_op_sha256": digest,
            }
        )

    if fixture_ids != sorted(fixture_ids):
        raise ContractError("corpus fixture IDs must be sorted")
    required_feature_set = set(required_features)
    if not required_feature_set <= feature_coverage:
        raise ContractError(
            "corpus is missing required features: {}".format(
                sorted(required_feature_set - feature_coverage)
            )
        )
    if load_mode_coverage != known_load_modes:
        raise ContractError(
            "corpus load-mode coverage differs from inventory: {}".format(
                sorted(known_load_modes - load_mode_coverage)
            )
        )
    return {
        "schema_version": 1,
        "fixtures": reports,
        "consumer_count": len(entries),
        "feature_count": len(feature_coverage),
        "load_mode_count": len(load_mode_coverage),
    }
