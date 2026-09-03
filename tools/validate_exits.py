"""Validate statically resolvable authored exits against Classic landing rules."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import posixpath
import re
import sys
from typing import Optional


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.content_core import Node, parse_bytes


EXIT_TYPE = "66"
PLAYER_TERRAIN = 65
TILED_UP = 9
TILED_SLOTS = tuple(range(1, 11))
FILENAME_TILE_OFFSETS = (
    (0, -1, 0),
    (1, 0, 0),
    (0, 1, 0),
    (-1, 0, 0),
    (1, -1, 0),
    (1, 1, 0),
    (-1, 1, 0),
    (-1, -1, 0),
    (0, 0, 1),
    (0, 0, -1),
)
SIGNED_INTEGER_RE = re.compile(r"^-?[0-9]+$")
LANDING_OFFSETS = (
    (0, -1),
    (1, -1),
    (1, 0),
    (1, 1),
    (0, 1),
    (-1, 1),
    (-1, 0),
    (-1, -1),
)
FORMS = ("explicit", "same-map", "tiled", "automatic-link", "shop-mat")
BASELINE_PATH = ROOT / "tools" / "exit-validation-baseline.json"


@dataclass
class Archetype:
    name: str
    attributes: dict[str, str]


@dataclass
class MapObject:
    map_path: str
    source_path: str
    node: Node
    attributes: dict[str, str]


@dataclass
class MapRecord:
    logical_path: str
    source_path: str
    width: Optional[int]
    height: Optional[int]
    links: dict[int, str]
    objects: list[MapObject]
    cells: dict[tuple[int, int], list[MapObject]]


@dataclass
class ExitCandidate:
    source: MapObject
    form: str
    target_path: Optional[str]
    target_x: Optional[int]
    target_y: Optional[int]
    pre_reason: Optional[str] = None


def _schema_root(root: Path) -> Path:
    """Use fixture-local schemas when present, otherwise the repository schema."""

    metadata = root / "schemas" / "authored-content-v1" / "field-metadata.json"
    return root if metadata.is_file() else ROOT


def _field_values(node: Node) -> dict[str, str]:
    """Return the last authored value for each field, case-insensitively."""

    values: dict[str, str] = {}
    for field in node.fields:
        values[field.name.casefold()] = field.value
    return values


def _integer(value: Optional[str], default: Optional[int] = None) -> Optional[int]:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _logical_path(relative_path: str) -> str:
    return "/" + relative_path.removeprefix("maps/")


def _normalize_path(source_map: str, value: str) -> str:
    if value.startswith("/"):
        candidate = value
    else:
        candidate = posixpath.join(posixpath.dirname(source_map), value)
    return "/" + posixpath.normpath(candidate).lstrip("/")


def _is_dynamic_path(value: str) -> bool:
    lowered = value.casefold()
    return (
        lowered.startswith("/!")
        or lowered.startswith("/random/")
        or lowered in {"!", "random", "/random"}
    )


def _path_for_logical(root: Path, logical_path: str) -> Optional[Path]:
    maps_root = (root / "maps").resolve()
    candidate = maps_root / logical_path.lstrip("/")
    if candidate.is_symlink():
        return None
    try:
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(maps_root)
    except (OSError, ValueError):
        return None
    if not resolved.is_file():
        return None
    return resolved


def _filename_coordinates(logical_path: str) -> Optional[tuple[str, tuple[int, int, int]]]:
    """Parse the signed coordinate suffix using Classic's filename rules."""

    basename = posixpath.basename(logical_path)
    coordinates: list[int] = []
    coordinates_length = 0
    for token in basename.split("_"):
        if len(token) > 3:
            continue
        if SIGNED_INTEGER_RE.fullmatch(token):
            coordinates_length += len(token) + 1
            coordinates.append(int(token))
        if len(coordinates) >= 3:
            break
    if len(coordinates) < 2:
        return None
    z = coordinates[2] if len(coordinates) == 3 else 0
    return logical_path[:-coordinates_length], (coordinates[0], coordinates[1], z)


def _add_filename_links(
    root: Path,
    logical_path: str,
    links: dict[int, str],
) -> None:
    """Mirror Classic's existing-file coordinate tiling lookup."""

    parsed = _filename_coordinates(logical_path)
    if parsed is None:
        return
    prefix, (x, y, z) = parsed
    for slot, (dx, dy, dz) in enumerate(FILENAME_TILE_OFFSETS, start=1):
        if slot in links:
            continue
        target = "{}_{}_{}".format(prefix, x + dx, y + dy)
        target_z = z + dz
        if target_z != 0:
            target += "_{}".format(target_z)
        target = "/" + posixpath.normpath(target).lstrip("/")
        if _path_for_logical(root, target) is not None:
            links[slot] = target


def _load_archetypes(root: Path) -> tuple[dict[str, Archetype], set[str], int]:
    raw_archetypes: dict[str, Archetype] = {}
    files = 0
    schema_root = _schema_root(root)
    for path in sorted((root / "arch").rglob("*.arc")):
        if path.is_symlink() or not path.is_file():
            continue
        files += 1
        relative = path.relative_to(root).as_posix()
        document = parse_bytes(
            path.read_bytes(),
            path=relative,
            format_name="archetype",
            schema_root=schema_root,
        )
        for node in document.nodes:
            if node.kind != "object" or node.depth != 0:
                continue
            attributes = _field_values(node)
            raw_archetypes[node.name.casefold()] = Archetype(node.name, attributes)

    resolved: dict[str, Archetype] = {}

    def resolve(name: str, active: set[str]) -> Archetype:
        if name in resolved:
            return resolved[name]
        archetype = raw_archetypes[name]
        attributes: dict[str, str] = {}
        parent = archetype.attributes.get("other_arch", "").casefold()
        if parent and parent in raw_archetypes and parent not in active:
            attributes.update(resolve(parent, active | {name}).attributes)
        attributes.update(archetype.attributes)
        result = Archetype(archetype.name, attributes)
        resolved[name] = result
        return result

    archetypes = {
        name: resolve(name, set()) for name in sorted(raw_archetypes)
    }
    exit_names = {
        name
        for name, archetype in archetypes.items()
        if archetype.attributes.get("type") == EXIT_TYPE
    }
    return archetypes, exit_names, files


def _candidate_map_paths(root: Path, exit_names: set[str]) -> tuple[list[Path], int]:
    candidates: list[Path] = []
    map_files = 0
    for path in sorted((root / "maps").rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            source = path.read_bytes()
        except OSError:
            continue
        if not source.startswith(b"arch map\n"):
            continue
        map_files += 1
        found = False
        for raw_line in source.splitlines():
            line = raw_line.strip()
            folded = line.lower()
            if folded == b"type 66":
                found = True
                break
            if folded.startswith(b"arch "):
                name = folded[5:].strip().decode("utf-8", errors="ignore")
                if name in exit_names:
                    found = True
                    break
        if found:
            candidates.append(path)
    return candidates, map_files


def _map_record(
    root: Path,
    path: Path,
    archetypes: dict[str, Archetype],
) -> MapRecord:
    source_path = path.relative_to(root).as_posix()
    logical_path = _logical_path(source_path)
    schema_root = _schema_root(root)
    document = parse_bytes(
        path.read_bytes(),
        path=source_path,
        format_name="map",
        schema_root=schema_root,
    )
    header = document.map_header
    header_values = _field_values(header) if header is not None else {}
    width = _integer(header_values.get("width"))
    height = _integer(header_values.get("height"))
    links: dict[int, str] = {}
    for slot in TILED_SLOTS:
        value = header_values.get("tile_path_{}".format(slot))
        if value:
            links[slot] = _normalize_path(logical_path, value)
    _add_filename_links(root, logical_path, links)

    objects: list[MapObject] = []
    cells: dict[tuple[int, int], list[MapObject]] = {}
    for node in document.objects:
        if node.depth != 0:
            continue
        attributes = dict(
            archetypes.get(node.name.casefold(), Archetype(node.name, {})).attributes
        )
        attributes.update(_field_values(node))
        map_object = MapObject(logical_path, source_path, node, attributes)
        objects.append(map_object)
        x = _integer(attributes.get("x"), 0)
        y = _integer(attributes.get("y"), 0)
        if x is not None and y is not None:
            cells.setdefault((x, y), []).append(map_object)
    return MapRecord(
        logical_path,
        source_path,
        width,
        height,
        links,
        objects,
        cells,
    )


def _load_maps(
    root: Path,
    archetypes: dict[str, Archetype],
    candidates: list[Path],
) -> tuple[dict[str, MapRecord], list[str]]:
    pending = {
        _logical_path(path.relative_to(root).as_posix()) for path in candidates
    }
    records: dict[str, MapRecord] = {}
    missing_references: set[str] = set()
    while pending:
        logical_path = min(pending)
        pending.remove(logical_path)
        if logical_path in records:
            continue
        path = _path_for_logical(root, logical_path)
        if path is None:
            missing_references.add(logical_path)
            continue
        record = _map_record(root, path, archetypes)
        records[logical_path] = record
        pending.update(record.links.values())
        for map_object in record.objects:
            if map_object.attributes.get("type") != EXIT_TYPE:
                continue
            path_value = map_object.attributes.get("slaying", "").strip()
            if path_value and not _is_dynamic_path(path_value):
                pending.add(_normalize_path(logical_path, path_value))
            else:
                tiled = _integer(map_object.attributes.get("last_heal"))
                if tiled in record.links:
                    pending.add(record.links[tiled])
    return records, sorted(missing_references)


def _candidate(
    map_object: MapObject,
    form: str,
    target_path: Optional[str],
    target_x: Optional[int],
    target_y: Optional[int],
    pre_reason: Optional[str] = None,
) -> ExitCandidate:
    return ExitCandidate(
        map_object,
        form,
        target_path,
        target_x,
        target_y,
        pre_reason,
    )


def _classify_exit(
    record: MapRecord,
    map_object: MapObject,
    exclusions: dict[str, int],
) -> Optional[ExitCandidate]:
    attributes = map_object.attributes
    source_x = _integer(attributes.get("x"), 0)
    source_y = _integer(attributes.get("y"), 0)
    path_value = attributes.get("slaying", "").strip()
    if path_value:
        if _is_dynamic_path(path_value):
            exclusions["dynamic"] += 1
            return None
        return _candidate(
            map_object,
            "explicit",
            _normalize_path(record.logical_path, path_value),
            _integer(attributes.get("hp"), -1),
            _integer(attributes.get("sp"), -1),
        )

    tiled = _integer(attributes.get("last_heal"))
    if tiled is not None and 1 <= tiled <= 10:
        target_path = record.links.get(tiled)
        if target_path is None:
            exclusions["unresolved"] += 1
            return None
        target_x, target_y = source_x, source_y
        if attributes.get("xrays") == "1":
            direction = _integer(attributes.get("direction"))
            if direction is None or not 1 <= direction <= 8:
                return _candidate(
                    map_object,
                    "tiled",
                    target_path,
                    target_x,
                    target_y,
                    "invalid-tiled-direction",
                )
            if tiled == TILED_UP:
                direction = ((direction + 3) % 8) + 1
            dx, dy = LANDING_OFFSETS[direction - 1]
            target_x = None if target_x is None else target_x + dx
            target_y = None if target_y is None else target_y + dy
        return _candidate(map_object, "tiled", target_path, target_x, target_y)

    target_x = _integer(attributes.get("hp"), -1)
    target_y = _integer(attributes.get("sp"), -1)
    if target_x != -1 or target_y != -1:
        return _candidate(
            map_object, "same-map", record.logical_path, target_x, target_y
        )

    subtype = _integer(attributes.get("sub_type"), 0)
    if subtype == 255 or map_object.node.name.casefold() == "shop_mat":
        return _candidate(
            map_object,
            "shop-mat",
            record.logical_path,
            source_x,
            source_y,
        )
    if subtype not in (None, 0):
        return _candidate(
            map_object,
            "automatic-link",
            record.logical_path,
            source_x,
            source_y,
        )
    exclusions["unresolved"] += 1
    return None


def _resolve_coordinate(
    records: dict[str, MapRecord],
    logical_path: str,
    x: Optional[int],
    y: Optional[int],
) -> Optional[tuple[str, int, int]]:
    if x is None or y is None:
        return None
    visited: set[tuple[str, int, int]] = set()
    for _ in range(128):
        key = (logical_path, x, y)
        if key in visited:
            return None
        visited.add(key)
        record = records.get(logical_path)
        if record is None or record.width is None or record.height is None:
            return None
        if record.width <= 0 or record.height <= 0:
            return None
        if 0 <= x < record.width and 0 <= y < record.height:
            return logical_path, x, y

        if x < 0:
            if y < 0:
                slot = 8
                next_y_delta = None
                next_x_delta = None
            elif y >= record.height:
                slot = 7
                next_y_delta = -record.height
                next_x_delta = None
            else:
                slot = 4
                next_y_delta = None
                next_x_delta = None
        elif x >= record.width:
            if y < 0:
                slot = 5
                next_y_delta = None
                next_x_delta = -record.width
            elif y >= record.height:
                slot = 6
                next_y_delta = -record.height
                next_x_delta = -record.width
            else:
                slot = 2
                next_y_delta = None
                next_x_delta = -record.width
        elif y < 0:
            slot = 1
            next_y_delta = None
            next_x_delta = None
        else:
            slot = 3
            next_y_delta = -record.height
            next_x_delta = None

        next_path = record.links.get(slot)
        next_record = records.get(next_path) if next_path is not None else None
        if next_record is None or next_record.width is None or next_record.height is None:
            return None
        if x < 0 and y < 0:
            x += next_record.width
            y += next_record.height
        elif x < 0 and y >= record.height:
            x += next_record.width
            y += next_y_delta or 0
        elif x < 0:
            x += next_record.width
        elif x >= record.width and y < 0:
            x += next_x_delta or 0
            y += next_record.height
        elif x >= record.width and y >= record.height:
            x += next_x_delta or 0
            y += next_y_delta or 0
        elif x >= record.width:
            x += next_x_delta or 0
        elif y < 0:
            y += next_record.height
        else:
            y += next_y_delta or 0
        logical_path = next_path
    return None


def _cell_status(
    records: dict[str, MapRecord], logical_path: str, x: int, y: int
) -> str:
    record = records.get(logical_path)
    if record is None or record.width is None or record.height is None:
        return "outside"
    if not (0 <= x < record.width and 0 <= y < record.height):
        return "outside"
    objects = record.cells.get((x, y), ())
    floors = [obj for obj in objects if obj.attributes.get("is_floor") == "1"]
    if not floors:
        return "no-floor"
    if any(
        obj.attributes.get("no_pass") == "1"
        or obj.attributes.get("door_closed") == "1"
        for obj in objects
    ):
        return "blocked"
    for floor in floors:
        terrain = _integer(floor.attributes.get("terrain_type"), 0)
        if terrain is not None and terrain >= 0 and terrain & ~PLAYER_TERRAIN == 0:
            return "usable"
    return "unsupported-terrain"


def _landing(
    records: dict[str, MapRecord],
    target_path: Optional[str],
    target_x: Optional[int],
    target_y: Optional[int],
    fixed: bool,
) -> dict:
    if target_path is None:
        return {
            "reason_code": "missing-target-map",
            "reason": "the resolved destination map is missing",
            "resolved": None,
        }
    if target_path not in records:
        return {
            "reason_code": "missing-target-map",
            "reason": "the target map is missing",
            "resolved": None,
        }
    resolved = _resolve_coordinate(records, target_path, target_x, target_y)
    if resolved is None:
        return {
            "reason_code": "invalid-destination-coordinates",
            "reason": "the destination coordinates are invalid or outside linked map bounds",
            "resolved": None,
        }
    resolved_path, resolved_x, resolved_y = resolved
    requested_status = _cell_status(records, resolved_path, resolved_x, resolved_y)
    if requested_status == "usable":
        return {"reason_code": None, "reason": None, "resolved": resolved}
    if not fixed:
        for dx, dy in LANDING_OFFSETS:
            adjacent = _resolve_coordinate(
                records, resolved_path, resolved_x + dx, resolved_y + dy
            )
            if adjacent is None:
                continue
            adjacent_status = _cell_status(records, *adjacent)
            if adjacent_status == "usable":
                return {"reason_code": None, "reason": None, "resolved": resolved}
    fixed_text = "; fixed-position exits do not use adjacent fallback" if fixed else ""
    return {
        "reason_code": "no-usable-landing",
        "reason": (
            "the target cell is {} and neither it nor the adjacent cells provide "
            "a usable player landing{}"
        ).format(requested_status, fixed_text),
        "resolved": resolved,
    }


def _automatic_landing(
    records: dict[str, MapRecord], path: str, x: Optional[int], y: Optional[int]
) -> dict:
    if path not in records:
        return {
            "reason_code": "missing-target-map",
            "reason": "the automatic-link target map is missing",
            "resolved": None,
        }
    if x is None or y is None:
        return {
            "reason_code": "invalid-destination-coordinates",
            "reason": "the automatic-link target coordinates are invalid",
            "resolved": None,
        }
    for dx, dy in LANDING_OFFSETS:
        adjacent = _resolve_coordinate(records, path, x + dx, y + dy)
        if adjacent is None:
            continue
        if _cell_status(records, *adjacent) == "usable":
            return {"reason_code": None, "reason": None, "resolved": adjacent}
    resolved = _resolve_coordinate(records, path, x, y)
    return {
        "reason_code": "no-usable-landing",
        "reason": "no adjacent cell provides a usable player landing",
        "resolved": resolved,
    }


def _identity(candidate: ExitCandidate, reason_code: str) -> str:
    source = candidate.source
    identity = {
        "source_coordinate": [
            _integer(source.attributes.get("x"), 0),
            _integer(source.attributes.get("y"), 0),
        ],
        "source_line": source.node.opener_span.line,
        "source_path": source.source_path,
        "target_coordinate": [candidate.target_x, candidate.target_y],
        "target_path": candidate.target_path,
        "exit_form": candidate.form,
        "reason_code": reason_code,
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    return "exit:" + hashlib.sha256(encoded).hexdigest()


def _diagnostic(
    candidate: ExitCandidate,
    result: dict,
    target_path: Optional[str] = None,
    target_x: Optional[int] = None,
    target_y: Optional[int] = None,
) -> dict:
    target_path = candidate.target_path if target_path is None else target_path
    target_x = candidate.target_x if target_x is None else target_x
    target_y = candidate.target_y if target_y is None else target_y
    source = candidate.source
    source_x = _integer(source.attributes.get("x"), 0)
    source_y = _integer(source.attributes.get("y"), 0)
    resolved = result.get("resolved")
    diagnostic = {
        "code": "non-enterable-exit",
        "severity": "error",
        "id": _identity(
            ExitCandidate(source, candidate.form, target_path, target_x, target_y),
            result["reason_code"],
        ),
        "source": {
            "path": source.source_path,
            "map": source.map_path,
            "line": source.node.opener_span.line,
            "coordinate": {"x": source_x, "y": source_y},
            "archetype": source.node.name,
        },
        "exit_form": candidate.form,
        "target": {
            "path": target_path,
            "coordinate": {"x": target_x, "y": target_y},
        },
        "resolved_target": None,
        "reason_code": result["reason_code"],
        "reason": result["reason"],
    }
    if resolved is not None:
        diagnostic["resolved_target"] = {
            "path": resolved[0],
            "coordinate": {"x": resolved[1], "y": resolved[2]},
        }
    return diagnostic


def _sort_diagnostic(item: dict) -> tuple:
    source = item["source"]
    coordinate = source["coordinate"]
    target = item["target"]
    target_coordinate = target["coordinate"]
    return (
        source["path"],
        source["line"],
        coordinate["x"] if coordinate["x"] is not None else -1,
        coordinate["y"] if coordinate["y"] is not None else -1,
        item["exit_form"],
        target["path"] or "",
        target_coordinate["x"] if target_coordinate["x"] is not None else -1,
        target_coordinate["y"] if target_coordinate["y"] is not None else -1,
        item["reason_code"],
    )


def _automatic_candidates(
    records: dict[str, MapRecord], candidates: list[ExitCandidate]
) -> tuple[list[dict], dict[str, int]]:
    by_key = {
        (map_path, map_object.node.handle): map_object
        for map_path, record in records.items()
        for map_object in record.objects
        if map_object.attributes.get("type") == EXIT_TYPE
    }
    diagnostics: list[dict] = []
    without_peer = 0
    for candidate in sorted(
        (
            candidate
            for candidate in candidates
            if candidate.form in {"automatic-link", "shop-mat"}
        ),
        key=lambda item: (item.source.source_path, item.source.node.opener_span.line),
    ):
        source_x = _integer(candidate.source.attributes.get("x"), 0)
        source_y = _integer(candidate.source.attributes.get("y"), 0)
        subtype = _integer(candidate.source.attributes.get("sub_type"), 0)
        if source_x is None or source_y is None or subtype is None:
            without_peer += 1
            continue
        peers: dict[tuple[str, str], MapObject] = {}
        for dx in range(-5, 6):
            for dy in range(-5, 6):
                if dx == 0 and dy == 0:
                    continue
                location = _resolve_coordinate(
                    records,
                    candidate.source.map_path,
                    source_x + dx,
                    source_y + dy,
                )
                if location is None:
                    continue
                map_path, x, y = location
                for map_object in records[map_path].cells.get((x, y), ()):
                    peer = by_key.get((map_path, map_object.node.handle))
                    if peer is None or peer is candidate.source:
                        continue
                    if _integer(peer.attributes.get("sub_type"), 0) != subtype:
                        continue
                    peers[(map_path, map_object.node.handle)] = peer
        if not peers:
            without_peer += 1
            continue
        for peer in peers.values():
            peer_x = _integer(peer.attributes.get("x"), 0)
            peer_y = _integer(peer.attributes.get("y"), 0)
            result = _automatic_landing(
                records, peer.map_path, peer_x, peer_y
            )
            if result["reason_code"]:
                diagnostics.append(
                    _diagnostic(
                        candidate,
                        result,
                        peer.map_path,
                        peer_x,
                        peer_y,
                    )
                )
    return diagnostics, {"automatic-without-peer": without_peer}


def _load_baseline(path: Optional[Path]) -> tuple[Optional[str], set[str]]:
    if path is None:
        return None, set()
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or data.get("kind") != "authored-exit-validation-baseline":
        raise ValueError("invalid authored-exit-validation baseline schema")
    finding_ids = data.get("finding_ids")
    if not isinstance(finding_ids, list) or not all(
        isinstance(item, str) for item in finding_ids
    ):
        raise ValueError("baseline finding_ids must be a list of strings")
    if finding_ids != sorted(set(finding_ids)):
        raise ValueError("baseline finding_ids must be unique and sorted")
    return path.as_posix(), set(finding_ids)


def _display_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def validate(root: Path, baseline: Optional[Path] = None) -> dict:
    """Return a deterministic report for one authored-content root."""

    root = root.resolve()
    archetypes, exit_names, archetype_files = _load_archetypes(root)
    candidate_paths, map_files = _candidate_map_paths(root, exit_names)
    records, unresolved_references = _load_maps(root, archetypes, candidate_paths)
    exclusions = {"dynamic": 0, "unresolved": 0}
    candidates: list[ExitCandidate] = []
    total_exit_objects = 0
    for logical_path in sorted(records):
        record = records[logical_path]
        for map_object in sorted(
            record.objects,
            key=lambda item: (item.node.opener_span.line, item.node.handle),
        ):
            if map_object.attributes.get("type") != EXIT_TYPE:
                continue
            total_exit_objects += 1
            candidate = _classify_exit(record, map_object, exclusions)
            if candidate is not None:
                candidates.append(candidate)

    diagnostics: list[dict] = []
    for candidate in candidates:
        if candidate.form not in {"explicit", "same-map", "tiled"}:
            continue
        if candidate.pre_reason:
            diagnostics.append(
                _diagnostic(
                    candidate,
                    {
                        "reason_code": candidate.pre_reason,
                        "reason": "the tiled exit has an invalid direction",
                        "resolved": None,
                    },
                )
            )
            continue
        result = _landing(
            records,
            candidate.target_path,
            candidate.target_x,
            candidate.target_y,
            candidate.source.attributes.get("use_fix_pos") == "1",
        )
        if result["reason_code"]:
            diagnostics.append(_diagnostic(candidate, result))
    automatic_diagnostics, automatic_exclusions = _automatic_candidates(
        records, candidates
    )
    diagnostics.extend(automatic_diagnostics)
    exclusions.update(automatic_exclusions)
    diagnostics = sorted(
        {item["id"]: item for item in diagnostics}.values(), key=_sort_diagnostic
    )

    baseline_path, baseline_ids = _load_baseline(baseline)
    actual_ids = {item["id"] for item in diagnostics}
    stale_ids = sorted(baseline_ids - actual_ids)
    unapproved = [item for item in diagnostics if item["id"] not in baseline_ids]
    form_counts = {form: 0 for form in FORMS}
    for candidate in candidates:
        if candidate.form in form_counts:
            form_counts[candidate.form] += 1
    return {
        "schema_version": 1,
        "kind": "authored-exit-validation",
        "status": "pass" if not stale_ids and not unapproved else "fail",
        "ok": not stale_ids and not unapproved,
        "scan": {
            "archetype_files": archetype_files,
            "archetypes": len(archetypes),
            "exit_objects": total_exit_objects,
            "map_files": map_files,
            "candidate_maps": len(candidate_paths),
            "parsed_maps": len(records),
            "forms": form_counts,
        },
        "baseline": {
            "path": _display_path(root, baseline) if baseline is not None else baseline_path,
            "count": len(baseline_ids),
            "stale_ids": stale_ids,
        },
        "excluded": dict(sorted(exclusions.items())),
        "diagnostics": diagnostics,
        "unapproved_diagnostics": unapproved,
        "unresolved_references": unresolved_references,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--baseline",
        type=Path,
        help="reviewed finding baseline (defaults to the repository baseline)",
    )
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = _parser().parse_args(argv)
    root = args.root.resolve()
    baseline = (
        args.baseline.resolve()
        if args.baseline is not None
        else BASELINE_PATH if root == ROOT else None
    )
    try:
        report = validate(root, baseline)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print("authored exit validation failed to run: {}".format(error), file=sys.stderr)
        return 2
    if args.as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            "Authored exits: {} findings across {} parsed maps ({}).".format(
                len(report["diagnostics"]),
                report["scan"]["parsed_maps"],
                report["status"],
            )
        )
        for item in report["unapproved_diagnostics"]:
            print(
                "{}:{}: {}".format(
                    item["source"]["path"],
                    item["source"]["line"],
                    item["reason"],
                )
            )
        for finding_id in report["baseline"]["stale_ids"]:
            print("stale baseline finding: {}".format(finding_id))
    return 1 if args.check and not report["ok"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
