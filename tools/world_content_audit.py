#!/usr/bin/env python3
"""Read-only exploratory inventory helper for Atrinik world content.

Prints deterministic JSON to stdout and never modifies authored data. This
report complements, but does not replace, tools.validate or content_catalog.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.content_core import Document, Node, parse_bytes


ROOT = Path(__file__).resolve().parents[1]
MAP_ROOT = ROOT / "maps"
ARCH_ROOT = ROOT / "arch"


def fields(lines: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    in_msg = False
    msg: list[str] = []
    for raw in lines:
        line = raw.rstrip("\n")
        if in_msg:
            if line == "endmsg":
                out["msg"].append("\n".join(msg).strip())
                in_msg = False
                msg = []
            else:
                msg.append(line)
            continue
        if line == "msg":
            in_msg = True
            continue
        key, sep, value = line.partition(" ")
        if sep:
            out[key].append(value.strip())
    return dict(out)


def parse_blocks(path: Path) -> dict:
    """Adapt the common lossless model to the audit's historical report shape."""

    relative = path.relative_to(ROOT).as_posix()
    document = parse_bytes(
        path.read_bytes(), path=relative, format_name="map"
    )
    header = _audit_node(document, document.map_header) if document.map_header else None
    objects = [
        _audit_node(document, document.node(handle))
        for handle in document.top_level_handles
        if document.node(handle).kind == "object"
    ]
    return {"header": header, "objects": objects}


def _audit_node(document: Document, node: Node) -> dict:
    attrs: dict[str, list[str]] = defaultdict(list)
    for record in node.fields:
        attrs[record.name].append(record.value)
    return {
        "arch": node.name,
        "attrs": dict(attrs),
        "children": [
            _audit_node(document, document.node(handle))
            for handle in node.child_handles
        ],
        "line": node.opener_span.line,
    }


def map_files() -> list[Path]:
    found = []
    for path in MAP_ROOT.rglob("*"):
        if not path.is_file():
            continue
        try:
            with path.open("rb") as handle:
                if handle.read(9) == b"arch map\n":
                    found.append(path)
        except OSError:
            pass
    return sorted(found)


def load_archetypes() -> dict[str, dict]:
    out = {}
    for path in sorted(ARCH_ROOT.rglob("*.arc")):
        relative = path.relative_to(ROOT).as_posix()
        document = parse_bytes(
            path.read_bytes(), path=relative, format_name="archetype"
        )
        for node in document.nodes:
            if node.depth != 0:
                continue
            attrs: dict[str, list[str]] = defaultdict(list)
            for record in node.fields:
                attrs[record.name].append(record.value)
            out[node.name] = {
                "path": str(path.relative_to(ROOT)),
                "attrs": {key: vals[-1] for key, vals in attrs.items() if vals},
            }
    return out


def one(attrs: dict, key: str, default=None):
    vals = attrs.get(key)
    return vals[-1] if vals else default


def flatten(nodes: list[dict], parent: dict | None = None):
    for node in nodes:
        yield node, parent
        yield from flatten(node["children"], node)


def quest_inventory() -> list[dict]:
    quests = []
    for path in sorted((MAP_ROOT / "interfaces" / "quests").glob("*/quest.xml")):
        root = ET.parse(path).getroot()
        quest = root.find("quest")
        if quest is None:
            continue
        parts = []
        for part in quest.iter("part"):
            info = part.findtext("info", default="").strip()
            items = [dict(elem.attrib) for elem in part.findall("item")]
            objects = [dict(elem.attrib) for elem in part.iter("object")]
            kills = [dict(elem.attrib) for elem in part.findall("kill")]
            npcs = sorted({
                elem.attrib["npc"]
                for elem in part.iter("interface")
                if "npc" in elem.attrib
            })
            actions = [dict(elem.attrib) for elem in part.iter("action")]
            messages = [
                " ".join((elem.text or "").split())
                for elem in part.iter("message")
                if (elem.text or "").strip()
            ]
            parts.append({
                "name": part.attrib.get("name"),
                "uid": part.attrib.get("uid"),
                "info": info,
                "items": items,
                "objects": objects,
                "kills": kills,
                "npcs": npcs,
                "actions": actions,
                "messages": messages,
            })
        quests.append({
            "name": quest.attrib.get("name"),
            "repeat": quest.attrib.get("repeat") == "1",
            "repeat_delay": quest.attrib.get("repeat_delay"),
            "path": str(path.relative_to(ROOT)),
            "parts": parts,
        })
    return quests


def region_registry() -> list[dict]:
    path = MAP_ROOT / "regions.reg"
    regions = []
    current = None
    msg = None
    for raw in path.read_text(errors="replace").splitlines():
        if msg is not None:
            if raw == "endmsg":
                current["msg"] = "\n".join(msg).strip()
                msg = None
            else:
                msg.append(raw)
            continue
        if raw.startswith("region "):
            current = {"id": raw[7:]}
        elif raw == "msg" and current is not None:
            msg = []
        elif raw == "end" and current is not None:
            regions.append(current)
            current = None
        elif current is not None and " " in raw:
            key, val = raw.split(" ", 1)
            current[key] = val
    return regions


def artifact_inventory() -> list[dict]:
    artifacts = []
    paths = sorted(set(ARCH_ROOT.rglob("*.art")) | set(MAP_ROOT.rglob("*.art")))
    for path in paths:
        lines = path.read_text(errors="replace").splitlines()
        i = 0
        while i < len(lines):
            if not lines[i].startswith("artifact "):
                i += 1
                continue
            artifact_id = lines[i].split(" ", 1)[1]
            start = i
            i += 1
            while i < len(lines) and not lines[i].startswith("artifact "):
                i += 1
            chunk = lines[start:i]
            attrs = fields([x + "\n" for x in chunk])
            object_attrs = {}
            if "Object" in chunk:
                oi = chunk.index("Object") + 1
                try:
                    oe = chunk.index("end", oi)
                except ValueError:
                    oe = len(chunk)
                object_attrs = fields([x + "\n" for x in chunk[oi:oe]])
            artifacts.append({
                "id": artifact_id,
                "path": str(path.relative_to(ROOT)),
                "def_arch": one(attrs, "def_arch"),
                "chance": one(attrs, "chance"),
                "attrs": {key: vals[-1] for key, vals in object_attrs.items() if vals},
            })
    return artifacts


def world_inventory() -> dict:
    archetypes = load_archetypes()
    maps = []
    named_monsters = []
    named_items = []
    arch_locations: dict[str, set[str]] = defaultdict(set)
    for path in map_files():
        parsed = parse_blocks(path)
        header = parsed["header"]
        if not header:
            continue
        hattrs = header["attrs"]
        rel = str(path.relative_to(ROOT))
        record = {
            "path": rel,
            "name": one(hattrs, "name"),
            "region": one(hattrs, "region"),
            "width": one(hattrs, "width"),
            "height": one(hattrs, "height"),
            "difficulty": one(hattrs, "difficulty"),
            "outdoor": one(hattrs, "outdoor") == "1",
        }
        match = re.fullmatch(r"world_(-?\d+)_(-?\d+)(?:_(-?\d+))?", path.name)
        if match:
            record["world_coord"] = [int(v or 0) for v in match.groups()]
        maps.append(record)
        for node, parent in flatten(parsed["objects"]):
            attrs = node["attrs"]
            arch = node["arch"]
            arch_locations[arch].add(rel)
            base = archetypes.get(arch, {}).get("attrs", {})
            obj_type = one(attrs, "type", base.get("type"))
            explicit_name = one(attrs, "name")
            base_name = base.get("name")
            is_monster = obj_type in {"80", "83"} or base.get("is_male") == "1" or base.get("is_female") == "1"
            entry = {
                "name": explicit_name,
                "arch": arch,
                "base_name": base_name,
                "path": rel,
                "line": node["line"],
                "x": one(attrs, "x", one(parent["attrs"], "x") if parent else None),
                "y": one(attrs, "y", one(parent["attrs"], "y") if parent else None),
                "randomitems": one(attrs, "randomitems", base.get("randomitems")),
                "level": one(attrs, "level", base.get("level")),
                "children": [
                    {
                        "arch": child["arch"],
                        "name": one(child["attrs"], "name"),
                        "race": one(child["attrs"], "race"),
                        "chance": one(child["attrs"], "chance"),
                    }
                    for child in node["children"]
                ],
                "special_drops": [
                    {
                        "kind": child["arch"],
                        "denominator": one(child["attrs"], "container"),
                        "container_name": one(child["attrs"], "name"),
                        "label": one(child["attrs"], "race"),
                        "items": [
                            {
                                "arch": grandchild["arch"],
                                "name": one(grandchild["attrs"], "name"),
                                "title": one(grandchild["attrs"], "title"),
                                "nrof": one(grandchild["attrs"], "nrof"),
                            }
                            for grandchild in child["children"]
                        ],
                    }
                    for child in node["children"]
                    if child["arch"] in {"rand_drop", "quest_container"}
                ],
            }
            if is_monster and explicit_name and explicit_name != base_name:
                named_monsters.append(entry)
            elif explicit_name and obj_type and obj_type not in {"0", "1", "2", "8", "20", "21", "66"}:
                named_items.append(entry)
    region_stats = {}
    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in maps:
        grouped[item["region"] or "(none)"].append(item)
    for region, items in grouped.items():
        coords = [item["world_coord"] for item in items if "world_coord" in item]
        region_stats[region] = {
            "maps": len(items),
            "outdoor_maps": sum(item["outdoor"] for item in items),
            "world_tiles": len(coords),
            "coord_bounds": (
                {
                    "x": [min(x[0] for x in coords), max(x[0] for x in coords)],
                    "y": [min(x[1] for x in coords), max(x[1] for x in coords)],
                    "z": [min(x[2] for x in coords), max(x[2] for x in coords)],
                }
                if coords else None
            ),
            "map_names": sorted({item["name"] for item in items if item["name"]}),
            "paths": sorted(item["path"] for item in items),
        }
    return {
        "maps": maps,
        "region_stats": region_stats,
        "named_monsters": named_monsters,
        "named_items": named_items,
        "arch_locations": {key: sorted(vals) for key, vals in arch_locations.items()},
        "archetypes": archetypes,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "section",
        choices=("quests", "regions", "artifacts", "world", "all"),
        default="all",
        nargs="?",
    )
    args = parser.parse_args()
    result = {}
    if args.section in ("quests", "all"):
        result["quests"] = quest_inventory()
    if args.section in ("regions", "all"):
        result["regions"] = region_registry()
    if args.section in ("artifacts", "all"):
        result["artifacts"] = artifact_inventory()
    if args.section in ("world", "all"):
        result["world"] = world_inventory()
    print(json.dumps(result if args.section == "all" else result[args.section], indent=2))


if __name__ == "__main__":
    main()
