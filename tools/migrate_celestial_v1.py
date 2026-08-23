#!/usr/bin/env python3
"""Apply the deterministic authored side of the celestial-v1 migration.

This is intentionally a content-owned migration helper.  It only edits the
authored ``arch`` and map roots, never generated runtime output or mutable
Classic state, and records the exact predecessor/target decisions in the
checked migration inventory.
"""

from __future__ import annotations

import hashlib
import json
import posixpath
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAPS = ROOT / "maps"
ARCH = ROOT / "arch"
SOURCE_COMMIT = "c9cc206f220316603115b15394926095de8ad324"
CLASSIC_SHA = "12b1211dd44690476c3f060d7395ccc1250c85b4"
GREYTON_LOWER = "/shattered_islands/strakewood_island/greyton/house/luxury_house_0_0"
GREYTON_UPPER = "/shattered_islands/strakewood_island/greyton/house/luxury_house_0_0_1"
REVERSE = {
    "tile_path_1": "tile_path_3",
    "tile_path_2": "tile_path_4",
    "tile_path_3": "tile_path_1",
    "tile_path_4": "tile_path_2",
    "tile_path_5": "tile_path_7",
    "tile_path_6": "tile_path_8",
    "tile_path_7": "tile_path_5",
    "tile_path_8": "tile_path_6",
    "tile_path_9": "tile_path_10",
    "tile_path_10": "tile_path_9",
}
LEGACY_LIGHT = {-1: 0, 1: 20, 2: 40, 3: 80, 4: 160, 5: 320, 6: 640, 7: 1280}
DYNAMIC_VARIANTS = {
    name: f"celestial_{name}"
    for name in (
        "gate_open", "gate_closed", "grate_open", "grate_closed", "piston_down",
        "piston_up", "portcullis_open", "portcullis_closed", "door_bar1", "curtain1",
        "gate1_locked", "door1_locked", "door_wood1", "door_wood2",
    )
}
STATIC_VARIANTS = {"ship_rail_e_high": "celestial_ship_rail_e_high", "ship_rail_ne_high": "celestial_ship_rail_ne_high"}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(source: str, target: str) -> str:
    path = posixpath.normpath(posixpath.join(posixpath.dirname(source), target))
    return path if path.startswith("/") else "/" + path


def map_files() -> list[Path]:
    result = []
    for path in sorted(MAPS.rglob("*")):
        if not path.is_file():
            continue
        if MAPS / "styles" in path.parents:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        except UnicodeDecodeError:
            continue
        if lines and lines[0].rstrip("\r\n") == "arch map":
            result.append(path)
    return result


def header(lines: list[str]) -> tuple[int, dict[str, str]]:
    end = next(i for i, line in enumerate(lines[1:], 1) if line.rstrip("\r\n") == "end")
    values: dict[str, str] = {}
    for line in lines[1:end]:
        raw = line.rstrip("\r\n")
        if " " in raw:
            key, value = raw.split(" ", 1)
            values[key] = value
    return end, values


def map_index(paths: list[Path]) -> dict[str, tuple[Path, dict[str, str]]]:
    result = {}
    for path in paths:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        _, values = header(lines)
        result["/" + path.relative_to(MAPS).as_posix()] = (path, values)
    return result


def inferred_links(logical: str, values: dict[str, str], index: dict[str, tuple[Path, dict[str, str]]]) -> dict[str, str]:
    """Materialize Classic's filename topology before v1 disables inference."""
    basename = logical.rsplit("/", 1)[-1]
    tokens = basename.split("_")
    coords: list[int] = []
    coords_len = 0
    old_style_z = 0
    for token in tokens:
        numeric = token.lstrip("-").isdigit()
        if len(token) == 1:
            old_style_z = int(token) if numeric else ord("a") - ord(token) - 1
        elif len(token) > 3:
            continue
        if numeric:
            coords_len += len(token) + 1
            coords.append(int(token))
        if len(coords) >= 3:
            break
    if len(coords) < 2:
        return {}
    z = coords[2] if len(coords) > 2 else 0
    prefix = logical[:-coords_len]
    deltas = {
        "1": (0, -1, 0), "2": (1, 0, 0), "3": (0, 1, 0), "4": (-1, 0, 0),
        "5": (1, -1, 0), "6": (1, 1, 0), "7": (-1, 1, 0), "8": (-1, -1, 0),
        "9": (0, 0, 1), "10": (0, 0, -1),
    }
    result = {}
    for tile, (dx, dy, dz) in deltas.items():
        if f"tile_path_{tile}" in values:
            continue
        if tile not in {"9", "10"} and z < 0:
            continue
        if tile == "9" and z >= 0:
            # Match Classic's path_exists guard for an upward link.
            pass
        target = f"{prefix}_{coords[0] + dx}_{coords[1] + dy}"
        target_z = z + dz
        if target_z != 0:
            target += f"_{target_z}"
        if target in index:
            result[tile] = target
    return result


def dynamic_archetypes() -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    for path in sorted(ARCH.rglob("*.arc")):
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        start = None
        for index, line in enumerate(lines + ["Object __end__\n"]):
            if line.startswith("Object "):
                if start is not None:
                    block = lines[start:index]
                    name = block[0].split(maxsplit=1)[1].strip()
                    fields = {
                        item.split(" ", 1)[0]: item.split(" ", 1)[1].strip()
                        for item in block[1:]
                        if " " in item and item.split(" ", 1)[0] not in {"Object"}
                    }
                    if fields.get("type") in {"20", "91"} and name in DYNAMIC_VARIANTS.values():
                        base_name = name.removeprefix("celestial_")
                        if base_name == "curtain1":
                            result[base_name] = ("glass", "open")
                        elif base_name in {"door_bar1", "grate_open", "grate_closed", "portcullis_open", "portcullis_closed"}:
                            result[base_name] = ("grate", "open")
                        else:
                            result[base_name] = ("opaque", "open")
                start = index
    return result


def update_dynamic_archetypes(dynamic: dict[str, tuple[str, str]]) -> None:
    for path in sorted(ARCH.rglob("*.arc")):
        original = path.read_text(encoding="utf-8")
        lines = original.splitlines(keepends=True)
        output: list[str] = []
        index = 0
        changed = False
        while index < len(lines):
            if not lines[index].startswith("Object "):
                output.append(lines[index])
                index += 1
                continue
            start = index
            index += 1
            while index < len(lines) and not lines[index].startswith("Object "):
                index += 1
            block = lines[start:index]
            name = block[0].split(maxsplit=1)[1].strip()
            if name not in DYNAMIC_VARIANTS.values():
                output.extend(block)
                continue
            present = {line.split(" ", 1)[0] for line in block if " " in line}
            closed, opened = dynamic[name.removeprefix("celestial_")]
            additions = []
            if "celestial_transmission_closed" not in present:
                additions.append(f"celestial_transmission_closed {closed}\n")
            if "celestial_transmission_open" not in present:
                additions.append(f"celestial_transmission_open {opened}\n")
            if additions:
                end = next(i for i, line in enumerate(block) if line.rstrip("\r\n") == "end")
                block[end:end] = additions
                changed = True
            output.extend(block)
        if changed:
            path.write_text("".join(output), encoding="utf-8", newline="")


def update_static_variants(paths: list[Path]) -> None:
    for path in paths:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        output: list[str] = []
        i = 0
        while i < len(lines):
            if lines[i].startswith("arch ") and lines[i].split(maxsplit=1)[1].strip() in STATIC_VARIANTS:
                name = lines[i].split(maxsplit=1)[1].strip()
                j = i + 1
                while j < len(lines) and lines[j].rstrip("\r\n") != "end":
                    j += 1
                block = lines[i:j + 1]
                fields = {line.split(" ", 1)[0] for line in block if " " in line}
                if "blocksview" in fields or "no_pass" in fields:
                    block[0] = f"arch {STATIC_VARIANTS[name]}\n"
                output.extend(block)
                i = j + 1
            else:
                output.append(lines[i])
                i += 1
        path.write_text("".join(output), encoding="utf-8", newline="")


def repair_structural_overrides(paths: list[Path]) -> None:
    """Remove legacy map-level view overrides from v1 map objects.

    Celestial-v1 derives structural roles from archetypes.  A map-local
    ``blocksview`` field is therefore neither a portable exposure exception
    nor a safe way to repair an archetype; retaining it would make the
    Classic parser reject otherwise valid maps.  The authoritative archetype
    definitions remain unchanged and carry their own structural roles.
    """
    for path in paths:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        output: list[str] = []
        i = 0
        while i < len(lines):
            if lines[i].startswith("arch "):
                j = i + 1
                while j < len(lines) and lines[j].rstrip("\r\n") != "end":
                    j += 1
                block = lines[i:j + 1]
                if any(line.startswith("blocksview ") for line in block):
                    block = [line for line in block if not line.startswith("blocksview ")]
                output.extend(block)
                i = j + 1
            else:
                output.append(lines[i])
                i += 1
        path.write_text("".join(output), encoding="utf-8", newline="")


def insert_before_end(block: list[str], additions: list[str]) -> list[str]:
    end = next(i for i, line in enumerate(block) if line.rstrip("\r\n") == "end")
    return block[:end] + additions + block[end:]


def migrate_maps(
    paths: list[Path],
    index: dict[str, tuple[Path, dict[str, str]]],
    dynamic: dict[str, tuple[str, str]],
    previous: dict[str, dict[str, object]],
) -> list[dict[str, object]]:
    inventory = []
    for path in paths:
        logical = "/" + path.relative_to(MAPS).as_posix()
        before = path.read_bytes()
        lines = before.decode("utf-8").splitlines(keepends=True)
        end, values = header(lines)
        prior = previous.get(logical, {})
        legacy_darkness = prior.get("legacy_darkness", values.get("darkness"))
        if legacy_darkness is not None:
            legacy_darkness = int(legacy_darkness)
        legacy_outdoor = bool(prior.get("legacy_outdoor", values.get("outdoor") == "1"))
        existing_light = int(values.get("light", "0"))
        source_region = str(prior.get("region", values.get("region") or "world"))
        inferred = inferred_links(logical, values, index)
        if logical == GREYTON_LOWER:
            sky = "linked"
        elif logical == GREYTON_UPPER:
            sky = "open"
        elif values.get("sky_above") in {"open", "linked", "sealed"}:
            sky = values["sky_above"]
        else:
            sky = "open" if legacy_outdoor else "sealed"
        if "9" in inferred:
            sky = "linked"
        target_light = int(prior.get("target_light", existing_light))
        if not legacy_outdoor and legacy_darkness is not None:
            target_light = LEGACY_LIGHT.get(legacy_darkness, 0)

        original_header = lines[1:end]
        rewritten = []
        for line in original_header:
            raw = line.rstrip("\r\n")
            key = raw.split(" ", 1)[0] if " " in raw else raw
            if key in {
                "celestial_schema",
                "sky_above",
                "darkness",
                "outdoor",
                "light",
                "region",
            }:
                continue
            if key.startswith("celestial_boundary_"):
                continue
            if logical == GREYTON_LOWER and key == "tile_path_9":
                continue
            if logical == GREYTON_UPPER and key == "tile_path_10":
                continue
            rewritten.append(line)
        prefix = ["celestial_schema 1\n", f"sky_above {sky}\n"]
        if target_light > 0:
            prefix.append(f"light {target_light}\n")
        rewritten = prefix + rewritten
        for tile, target in inferred.items():
            rewritten.append(f"tile_path_{tile} {target}\n")
        rewritten.append(f"region {source_region}\n")

        # Existing horizontal links are already reciprocal and all resolve to
        # authored maps.  A region boundary is discontinuous; equal regions
        # retain the continuous transport semantics.
        final_header: list[str] = []
        for line in rewritten:
            raw = line.rstrip("\r\n")
            if raw.startswith("tile_path_"):
                key, target = raw.split(" ", 1)
                target_id = canonical(logical, target)
                if target_id not in index:
                    raise SystemExit(f"missing celestial tile target {logical} {key} {target_id}")
                final_header.append(f"{key} {target_id}\n")
                target_region = index[target_id][1].get("region") or "world"
                boundary = "continuous" if source_region == target_region else "discontinuous"
                final_header.append(f"celestial_boundary_{key.split('_')[-1]} {boundary}\n")
            else:
                final_header.append(line)
        if logical == GREYTON_LOWER:
            final_header.extend([
                f"tile_path_9 {GREYTON_UPPER}\n",
                "celestial_boundary_9 continuous\n",
            ])
        elif logical == GREYTON_UPPER:
            final_header.extend([
                f"tile_path_10 {GREYTON_LOWER}\n",
                "celestial_boundary_10 continuous\n",
            ])
        lines = [lines[0]] + final_header + lines[end:]

        # Add stable explicit IDs and the inherited closed/open classes to
        # every placed DOOR/GATE object.  The ordinal is map-local and the
        # locator digest retains the authored identity used by upgrade tooling.
        aperture_rows = []
        ordinal = 0
        body_start = next(i for i, line in enumerate(lines) if line.rstrip("\r\n") == "end") + 1
        output = lines[:body_start]
        i = body_start
        while i < len(lines):
            line = lines[i]
            raw = line.rstrip("\r\n")
            if raw.startswith("arch ") and (
                raw.split(maxsplit=1)[1] in dynamic
                or raw.split(maxsplit=1)[1] in DYNAMIC_VARIANTS.values()
            ):
                name = raw.split(maxsplit=1)[1].removeprefix("celestial_")
                block = [line]
                i += 1
                while i < len(lines):
                    block.append(lines[i])
                    if lines[i].rstrip("\r\n") == "end":
                        i += 1
                        break
                    i += 1
                fields = {}
                for item in block[1:]:
                    item_raw = item.rstrip("\r\n")
                    if " " in item_raw:
                        key, value = item_raw.split(" ", 1)
                        fields.setdefault(key, value)
                block[0] = f"arch {DYNAMIC_VARIANTS[name]}\n"
                if "celestial_aperture_id" not in fields:
                    ordinal += 1
                    closed, opened = dynamic[name]
                    x = fields.get("x", "0")
                    y = fields.get("y", "0")
                    aperture_id = f"{ordinal:016x}"
                    locator = f"{logical}\t{name}\t{x}\t{y}\t{closed}\t{opened}"
                    aperture_rows.append({
                        "id": aperture_id,
                        "archetype": name,
                        "x": int(x),
                        "y": int(y),
                        "closed": closed,
                        "open": opened,
                        "locator_sha256": digest(locator.encode("utf-8")),
                    })
                    additions = [
                        f"celestial_transmission_closed {closed}\n",
                        f"celestial_transmission_open {opened}\n",
                        f"celestial_aperture_id {aperture_id}\n",
                    ]
                    block = insert_before_end(block, additions)
                else:
                    closed, opened = dynamic[name]
                    aperture_id = fields["celestial_aperture_id"]
                    x = fields.get("x", "0")
                    y = fields.get("y", "0")
                    locator = f"{logical}\t{name}\t{x}\t{y}\t{closed}\t{opened}"
                    aperture_rows.append({
                        "id": aperture_id,
                        "archetype": name,
                        "x": int(x),
                        "y": int(y),
                        "closed": closed,
                        "open": opened,
                        "locator_sha256": digest(locator.encode("utf-8")),
                    })
                output.extend(block)
            else:
                output.append(line)
                i += 1
        path.write_text("".join(output), encoding="utf-8", newline="")
        after = path.read_bytes()
        disposition = "ignored-outdoor" if legacy_outdoor else "translated-darkness" if legacy_darkness is not None else "absent-zero"
        inventory.append({
            "path": logical,
            "predecessor_sha256": digest(before),
            "migrated_sha256": digest(after),
            "region": source_region,
            "sky_above": sky,
            "legacy_outdoor": legacy_outdoor,
            "legacy_darkness": legacy_darkness,
            "legacy_disposition": disposition,
            "target_light": target_light,
            "horizontal_boundaries": sum(1 for line in final_header if line.startswith("celestial_boundary_")),
            "apertures": aperture_rows,
        })
    return inventory


def main() -> None:
    paths = map_files()
    index = map_index(paths)
    dynamic = dynamic_archetypes()
    update_dynamic_archetypes(dynamic)
    repair_structural_overrides(paths)
    inventory_path = MAPS / "celestial-migration-index.json"
    previous_data = json.loads(inventory_path.read_text(encoding="utf-8")) if inventory_path.exists() else {}
    previous = {row["path"]: row for row in previous_data.get("maps", [])}
    inventory = migrate_maps(paths, index, dynamic, previous)
    update_static_variants(paths)
    summary = {
        "maps": len(inventory),
        "open_maps": sum(row["sky_above"] == "open" for row in inventory),
        "linked_maps": sum(row["sky_above"] == "linked" for row in inventory),
        "sealed_maps": sum(row["sky_above"] == "sealed" for row in inventory),
        "horizontal_boundaries": sum(row["horizontal_boundaries"] for row in inventory),
        "dynamic_apertures": sum(len(row["apertures"]) for row in inventory),
        "legacy_outdoor_removed": sum(row["legacy_outdoor"] for row in inventory),
        "legacy_darkness_translated": sum(row["legacy_disposition"] == "translated-darkness" for row in inventory),
        "regionless_maps_explicit_world": sum(row["region"] == "world" for row in inventory),
    }
    result = {
        "schema_version": 1,
        "migration": "celestial-v1",
        "source_commit": SOURCE_COMMIT,
        "classic_compatible_sha": CLASSIC_SHA,
        "legacy_light_table": {str(key): value for key, value in LEGACY_LIGHT.items()},
        "summary": summary,
        "maps": inventory,
    }
    inventory_path.write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8", newline=""
    )
    print(json.dumps({"summary": summary, "dynamic_archetypes": len(dynamic)}, sort_keys=True))


if __name__ == "__main__":
    main()
