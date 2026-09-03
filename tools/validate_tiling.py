#!/usr/bin/env python3
"""Validate filename-derived authored map tiling metadata."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
import posixpath
import re
import sys
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.content_core import ContentCoreError, parse_bytes
from tools.validate_exits import (
    FILENAME_TILE_OFFSETS,
    _filename_coordinates,
    _normalize_path,
    _path_for_logical,
    _schema_root,
)


TILE_FIELD_RE = re.compile(r"^tile_path_([0-9]{1,2})$", re.IGNORECASE)
BOUNDARY_FIELD_RE = re.compile(
    r"^celestial_boundary_([0-9]{1,2})$", re.IGNORECASE
)
HORIZONTAL_SLOTS = tuple(range(1, 9))
VERTICAL_SLOTS = (9, 10)
CONTINUOUS_BOUNDARY = "continuous"


@dataclass(frozen=True)
class RemovalSpan:
    """One lossless source span that belongs to a removable tile record."""

    path: str
    start_byte: int
    end_byte: int
    slot: int
    kind: str


@dataclass(frozen=True)
class _Scan:
    report: dict[str, Any]
    removals: tuple[RemovalSpan, ...]


def _map_files(
    root: Path,
) -> tuple[tuple[tuple[Path, bytes], ...], frozenset[str]]:
    maps_root = root / "maps"
    if not maps_root.is_dir() or maps_root.is_symlink():
        return (), frozenset()

    found: list[tuple[Path, bytes]] = []
    available: set[str] = set()
    for path in sorted(maps_root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            source = path.read_bytes()
        except OSError:
            continue
        logical = "/" + path.relative_to(maps_root).as_posix()
        available.add(logical)
        if source.startswith(b"arch map\n"):
            found.append((path, source))
    return tuple(found), frozenset(available)


def _has_tiling_fields(source: bytes) -> bool:
    folded = source.lower()
    return b"tile_path_" in folded or b"celestial_boundary_" in folded


def _derived_target(
    root: Path,
    logical_path: str,
    slot: int,
    available_paths: Optional[frozenset[str]] = None,
) -> Optional[str]:
    parsed = _filename_coordinates(logical_path)
    if parsed is None:
        return None
    prefix, (x, y, z) = parsed
    dx, dy, dz = FILENAME_TILE_OFFSETS[slot - 1]
    target = "{}_{}_{}".format(prefix, x + dx, y + dy)
    target_z = z + dz
    if target_z != 0:
        target += "_{}".format(target_z)
    target = "/" + posixpath.normpath(target).lstrip("/")
    if available_paths is None:
        if _path_for_logical(root, target) is None:
            return None
    elif target not in available_paths:
        return None
    return target


def _source(
    path: str, line: int, slot: Optional[int] = None
) -> dict[str, Any]:
    result: dict[str, Any] = {"path": path, "line": line}
    if slot is not None:
        result["slot"] = slot
    return result


def _diagnostic(
    code: str,
    message: str,
    path: str,
    line: int,
    *,
    slot: Optional[int] = None,
    target: Optional[str] = None,
    boundary: Optional[str] = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "code": code,
        "severity": "error",
        "message": message,
        "source": _source(path, line, slot),
    }
    if target is not None:
        result["target"] = target
    if boundary is not None:
        result["boundary"] = boundary
    return result


def _sort_diagnostic(item: dict[str, Any]) -> tuple:
    source = item["source"]
    return (
        source["path"],
        source["line"],
        source.get("slot", 0),
        item["code"],
        item["message"],
    )


def _scan(root: Path, *, fast: bool = False) -> _Scan:
    root = root.resolve(strict=True)
    maps_root = root / "maps"
    diagnostics: list[dict[str, Any]] = []
    removals: list[RemovalSpan] = []
    counts: Counter[str] = Counter()
    preserved: Counter[str] = Counter()
    boundary_values: Counter[str] = Counter()
    match_by_slot: Counter[int] = Counter()
    deferred_vertical: list[dict[str, Any]] = []
    maps_with_tiles: set[str] = set()
    maps_with_matches: set[str] = set()
    maps_with_removals: set[str] = set()

    if not maps_root.is_dir() or maps_root.is_symlink():
        diagnostics.append(
            _diagnostic(
                "missing-map-root",
                "authored maps root is missing or is a symbolic link",
                "maps",
                1,
            )
        )

    map_entries, available_paths = _map_files(root)
    counts["map_files"] = len(map_entries)
    schema_root = _schema_root(root)

    for path, source in map_entries:
        relative = path.relative_to(root).as_posix()
        has_tiling_fields = _has_tiling_fields(source)
        if has_tiling_fields:
            counts["candidate_maps"] += 1
        elif fast:
            continue
        logical = "/" + path.relative_to(maps_root).as_posix()
        try:
            document = parse_bytes(
                source,
                path=relative,
                format_name="map",
                schema_root=schema_root,
            )
        except (ContentCoreError, OSError, UnicodeError, ValueError) as error:
            counts["invalid_maps"] += 1
            diagnostics.append(
                _diagnostic(
                    "invalid-map",
                    str(error),
                    relative,
                    1,
                )
            )
            continue

        if not document.valid:
            counts["invalid_maps"] += 1
            for item in document.diagnostics:
                if item["severity"] == "error":
                    diagnostics.append(
                        _diagnostic(
                            item["code"],
                            item["message"],
                            relative,
                            item["location"]["line"],
                        )
                    )
            continue

        counts["parsed_maps"] += 1
        header = document.map_header
        if header is None:
            counts["invalid_maps"] += 1
            diagnostics.append(
                _diagnostic(
                    "missing-map-header",
                    "map has no parsed header",
                    relative,
                    1,
                )
            )
            continue

        tile_records: dict[int, list[Any]] = {}
        boundary_records: dict[int, list[Any]] = {}
        for record in header.fields:
            tile_match = TILE_FIELD_RE.fullmatch(record.name)
            if tile_match:
                slot = int(tile_match.group(1))
                tile_records.setdefault(slot, []).append(record)
                counts["tile_records"] += 1
                maps_with_tiles.add(relative)
            boundary_match = BOUNDARY_FIELD_RE.fullmatch(record.name)
            if boundary_match:
                slot = int(boundary_match.group(1))
                boundary_records.setdefault(slot, []).append(record)
                counts["boundary_records"] += 1

        for slot, records in sorted(boundary_records.items()):
            if slot < 1 or slot > 10:
                for record in records:
                    diagnostics.append(
                        _diagnostic(
                            "boundary-index-out-of-range",
                            "celestial boundary index must be between 1 and 10",
                            relative,
                            record.span.line,
                            slot=slot,
                        )
                    )
                continue
            if slot not in tile_records:
                for record in records:
                    diagnostics.append(
                        _diagnostic(
                            "orphan-celestial-boundary",
                            "celestial boundary has no authored tile path",
                            relative,
                            record.span.line,
                            slot=slot,
                        )
                    )

        for slot, records in sorted(tile_records.items()):
            if slot < 1 or slot > 10:
                for record in records:
                    diagnostics.append(
                        _diagnostic(
                            "tile-index-out-of-range",
                            "tile path index must be between 1 and 10",
                            relative,
                            record.span.line,
                            slot=slot,
                        )
                    )
                continue
            if len(records) != 1:
                preserved["duplicate-tile-path"] += len(records)
                diagnostics.append(
                    _diagnostic(
                        "duplicate-tile-path",
                        "tile path slot must occur exactly once",
                        relative,
                        records[0].span.line,
                        slot=slot,
                    )
                )
                continue

            record = records[0]
            target = _derived_target(root, logical, slot, available_paths)
            normalized = _normalize_path(logical, record.value)
            if target is None:
                preserved["no-existing-filename-neighbor"] += 1
                continue
            if normalized != target:
                preserved["explicit-override"] += 1
                continue

            counts["filename_matches"] += 1
            match_by_slot[slot] += 1
            maps_with_matches.add(relative)
            boundaries = boundary_records.get(slot, [])
            if len(boundaries) > 1:
                preserved["duplicate-celestial-boundary"] += len(boundaries)
                diagnostics.append(
                    _diagnostic(
                        "duplicate-celestial-boundary",
                        "celestial boundary slot must occur at most once",
                        relative,
                        boundaries[0].span.line,
                        slot=slot,
                        target=normalized,
                    )
                )
                continue

            boundary_value = (
                boundaries[0].value.strip().casefold()
                if boundaries
                else None
            )
            boundary_values[boundary_value or "<missing>"] += 1
            if slot in VERTICAL_SLOTS:
                counts["deferred_vertical_matches"] += 1
                preserved["vertical-runtime-contract-open"] += 1
                if len(deferred_vertical) < 20:
                    deferred_vertical.append(
                        {
                            "path": relative,
                            "line": record.span.line,
                            "slot": slot,
                            "target": normalized,
                            "boundary": boundary_value,
                        }
                    )
                continue

            if boundary_value not in (None, CONTINUOUS_BOUNDARY):
                counts["protected_horizontal_matches"] += 1
                preserved["boundary-policy"] += 1
                continue

            counts["redundant_horizontal"] += 1
            maps_with_removals.add(relative)
            diagnostics.append(
                _diagnostic(
                    "filename-redundant-horizontal-tiling",
                    "horizontal tile path is supplied by the existing filename neighbor",
                    relative,
                    record.span.line,
                    slot=slot,
                    target=normalized,
                    boundary=boundary_value,
                )
            )
            removals.append(
                RemovalSpan(
                    relative,
                    record.span.start_byte,
                    record.span.end_byte,
                    slot,
                    "tile_path",
                )
            )
            if boundaries:
                boundary = boundaries[0]
                removals.append(
                    RemovalSpan(
                        relative,
                        boundary.span.start_byte,
                        boundary.span.end_byte,
                        slot,
                        "celestial_boundary",
                    )
                )

    counts["horizontal_matches"] = sum(
        match_by_slot[slot] for slot in HORIZONTAL_SLOTS
    )
    counts["vertical_matches"] = sum(
        match_by_slot[slot] for slot in VERTICAL_SLOTS
    )
    counts["maps_with_tiles"] = len(maps_with_tiles)
    counts["maps_with_filename_matches"] = len(maps_with_matches)
    counts["maps_with_removable_horizontal"] = len(maps_with_removals)

    scan_keys = (
        "boundary_records",
        "candidate_maps",
        "deferred_vertical_matches",
        "filename_matches",
        "horizontal_matches",
        "invalid_maps",
        "map_files",
        "maps_with_filename_matches",
        "maps_with_removable_horizontal",
        "maps_with_tiles",
        "parsed_maps",
        "protected_horizontal_matches",
        "redundant_horizontal",
        "tile_records",
        "vertical_matches",
    )
    scan = {key: counts.get(key, 0) for key in scan_keys}
    diagnostics = sorted(diagnostics, key=_sort_diagnostic)
    report = {
        "schema_version": 1,
        "kind": "authored-tiling-validation",
        "status": "pass" if not diagnostics else "fail",
        "ok": not diagnostics,
        "policy": {
            "removable_horizontal_boundary": CONTINUOUS_BOUNDARY,
            "preserved_horizontal_boundary": "any non-continuous value",
            "vertical_slots": list(VERTICAL_SLOTS),
            "vertical_status": "deferred until classic/issues/530",
        },
        "scan": scan,
        "match_by_slot": {
            str(slot): match_by_slot[slot]
            for slot in sorted(match_by_slot)
            if match_by_slot[slot]
        },
        "boundary_values": {
            value: boundary_values[value]
            for value in sorted(boundary_values)
        },
        "preserved": dict(sorted(preserved.items())),
        "deferred": {"vertical_samples": deferred_vertical},
        "diagnostics": diagnostics,
    }
    return _Scan(report, tuple(sorted(removals, key=lambda item: (
        item.path, item.start_byte, item.end_byte, item.kind
    ))))


def audit(root: Path) -> dict[str, Any]:
    """Return a deterministic report for authored filename-derived tiling."""

    return _scan(root).report


def validate(root: Path, *, fast: bool = False) -> dict[str, Any]:
    """Return the guard report, optionally relying on prior content validation."""

    return _scan(root, fast=fast).report


def removable_spans(root: Path) -> tuple[RemovalSpan, ...]:
    """Return lossless spans that the one-time cleanup may remove."""

    return _scan(root).removals


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate authored filename-derived map tiling metadata."
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--json", action="store_true")
    options = parser.parse_args(argv)
    report = audit(options.root)
    if options.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        scan = report["scan"]
        print(
            "Authored tiling: {} maps, {} horizontal redundant records, "
            "{} vertical matches deferred.".format(
                scan.get("parsed_maps", 0),
                scan.get("redundant_horizontal", 0),
                scan.get("deferred_vertical_matches", 0),
            )
        )
        for item in report["diagnostics"]:
            source = item["source"]
            print(
                "{}:{}:{} {}".format(
                    source["path"],
                    source["line"],
                    source.get("slot", 0),
                    item["message"],
                ),
                file=sys.stderr,
            )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
