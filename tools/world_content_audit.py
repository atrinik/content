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
LIGHT_REVIEW_NAME = "light-source-review.json"
LIGHT_COLOR_RE = re.compile(r"^[0-9a-f]{6}$")
INVISIBLE_LIGHT_RE = re.compile(r"^light[1-9]$")


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
    attrs = _audit_attrs(node)
    return {
        "arch": node.name,
        "attrs": attrs,
        "children": [
            _audit_node(document, document.node(handle))
            for handle in node.child_handles
        ],
        "line": node.opener_span.line,
    }


def _audit_attrs(node: Node) -> dict[str, list[str]]:
    """Retain the audit's field and multiline-message attribute shape."""

    attrs: dict[str, list[str]] = defaultdict(list)
    for record in node.fields:
        attrs[record.name].append(record.value)
    for message in node.messages:
        if message.terminated:
            attrs["msg"].append(message.text.strip())
    return dict(attrs)


def _legacy_archetype_attrs(
    document: Document, node: Node
) -> dict[str, list[str]]:
    """Adapt the model to the audit's historical first-`end` field window."""

    descendants = []
    pending = [node]
    while pending:
        current = pending.pop()
        descendants.append(current)
        pending.extend(
            document.node(handle) for handle in reversed(current.child_handles)
        )
    closers = [
        current.closer_span.start_byte
        for current in descendants
        if current.closer_span is not None
    ]
    cutoff = min(closers, default=node.span.end_byte)
    events = []
    for current in descendants:
        if current is not node and current.opener_span.start_byte < cutoff:
            events.append((current.opener_span.start_byte, "line", current.opener_span))
        events.extend(
            (record.span.start_byte, "line", record.span)
            for record in current.fields
            if record.span.start_byte < cutoff
        )
        events.extend(
            (message.span.start_byte, "message", message)
            for message in current.messages
            if message.span.start_byte < cutoff and message.terminated
        )
    events.extend(
        (span.start_byte, "line", span)
        for span in document.comments
        if node.opener_span.end_byte <= span.start_byte < cutoff
    )

    attrs: dict[str, list[str]] = defaultdict(list)
    for _, event_kind, record in sorted(events, key=lambda event: event[0]):
        if event_kind == "message":
            attrs["msg"].append(record.text.strip())
            continue
        raw = document.source[record.start_byte : record.end_byte].decode("utf-8")
        line = raw.rstrip("\n")
        key, separator, value = line.partition(" ")
        if separator:
            attrs[key].append(value.strip())
    return dict(attrs)


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
            attrs = _legacy_archetype_attrs(document, node)
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


def _nonzero_radius(value) -> int | None:
    """Return a nonzero Classic light radius, or None for a non-emitter."""

    try:
        radius = int(value or 0)
    except (TypeError, ValueError):
        return None
    return radius if radius != 0 else None


def _effective_color(value) -> str | None:
    """Normalize an authored RGB tint; zero retains Classic neutral lighting."""

    if value is None:
        return None
    color = str(value).lower()
    if color == "000000":
        return None
    return color


def _light_review() -> dict:
    path = MAP_ROOT / LIGHT_REVIEW_NAME
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _review_disposition(review: dict | None, color: str | None) -> tuple[str, str | None]:
    if color is not None:
        return "explicit-color", color
    if review and review.get("uncolored_disposition") == "neutral":
        return "intentional-neutral", None
    return "unreviewed", None


def light_inventory() -> dict:
    """Resolve every effective archetype, artifact, and map light emitter."""

    review = _light_review()
    archetypes = load_archetypes()
    archetype_rows = []
    for archetype, definition in sorted(archetypes.items()):
        attrs = definition["attrs"]
        radius = _nonzero_radius(attrs.get("glow_radius"))
        if radius is None:
            continue
        color = _effective_color(attrs.get("light_color"))
        disposition, resolved_color = _review_disposition(
            review.get("archetypes", {}).get(archetype), color
        )
        archetype_rows.append({
            "id": archetype,
            "path": definition["path"],
            "radius": radius,
            "color": resolved_color,
            "visible": not (
                attrs.get("type") == "78" and attrs.get("sys_object") == "1"
            ),
            "face": attrs.get("face"),
            "disposition": disposition,
            "rationale": review.get("archetypes", {}).get(archetype, {}).get(
                "rationale"
            ),
        })

    artifact_rows = []
    for artifact in artifact_inventory():
        base = archetypes.get(artifact["def_arch"], {}).get("attrs", {})
        attrs = artifact["attrs"]
        radius = _nonzero_radius(attrs.get("glow_radius", base.get("glow_radius")))
        if radius is None:
            continue
        color = _effective_color(attrs.get("light_color", base.get("light_color")))
        disposition, resolved_color = _review_disposition(
            review.get("artifacts", {}).get(artifact["id"]), color
        )
        artifact_rows.append({
            "id": artifact["id"],
            "path": artifact["path"],
            "archetype": artifact["def_arch"],
            "radius": radius,
            "color": resolved_color,
            "visible": not (
                base.get("type") == "78" and base.get("sys_object") == "1"
            ),
            "face": attrs.get("face", base.get("face")),
            "disposition": disposition,
            "rationale": review.get("artifacts", {}).get(artifact["id"], {}).get(
                "rationale"
            ),
        })

    map_rows = []
    reviewed_maps = {}
    for path in map_files():
        parsed = parse_blocks(path)
        relative = path.relative_to(ROOT).as_posix()
        map_review = review.get("maps", {}).get(relative)
        emitters = []
        for node, parent in flatten(parsed["objects"]):
            attrs = node["attrs"]
            base = archetypes.get(node["arch"], {}).get("attrs", {})
            radius = _nonzero_radius(one(attrs, "glow_radius", base.get("glow_radius")))
            if radius is None:
                continue
            color = _effective_color(one(attrs, "light_color", base.get("light_color")))
            source_review = review.get("archetypes", {}).get(node["arch"])
            if node["arch"] not in archetypes or "glow_radius" in attrs:
                source_review = map_review
            disposition, resolved_color = _review_disposition(source_review, color)
            x = one(attrs, "x", one(parent["attrs"], "x") if parent else None)
            y = one(attrs, "y", one(parent["attrs"], "y") if parent else None)
            emitters.append({
                "id": "{}:{}".format(relative, node["line"]),
                "line": node["line"],
                "archetype": node["arch"],
                "x": int(x) if x is not None else None,
                "y": int(y) if y is not None else None,
                "radius": radius,
                "color": resolved_color,
                "visible": not (
                    INVISIBLE_LIGHT_RE.fullmatch(node["arch"]) is not None
                    or (base.get("type") == "78" and base.get("sys_object") == "1")
                ),
                "face": one(attrs, "face", base.get("face")),
                "disposition": disposition,
                "rationale": (
                    source_review.get("rationale") if source_review else None
                ),
            })
        if not emitters:
            continue
        header = parsed["header"]["attrs"] if parsed["header"] else {}
        reviewed_maps[relative] = {
            "path": relative,
            "name": one(header, "name"),
            "region": one(header, "region"),
            "outdoor": one(header, "outdoor") == "1",
            "darkness": one(header, "darkness"),
            "rendered_batch": map_review.get("rendered_batch") if map_review else None,
            "rationale": map_review.get("rationale") if map_review else None,
            "emitters": emitters,
        }
        map_rows.extend(emitters)

    rows = archetype_rows + artifact_rows + map_rows
    colors = sorted({row["color"] for row in rows if row["color"] is not None})
    return {
        "schema_version": 1,
        "kind": "effective-light-source-inventory",
        "palette": review.get("palette", {}),
        "summary": {
            "archetypes": len(archetype_rows),
            "artifacts": len(artifact_rows),
            "maps": len(reviewed_maps),
            "map_instances": len(map_rows),
            "visible_map_instances": sum(row["visible"] for row in map_rows),
            "invisible_map_instances": sum(not row["visible"] for row in map_rows),
            "explicit_color": sum(
                row["disposition"] == "explicit-color" for row in rows
            ),
            "intentional_neutral": sum(
                row["disposition"] == "intentional-neutral" for row in rows
            ),
            "unreviewed": sum(row["disposition"] == "unreviewed" for row in rows),
            "colors": colors,
        },
        "archetypes": archetype_rows,
        "artifacts": artifact_rows,
        "maps": [reviewed_maps[path] for path in sorted(reviewed_maps)],
    }


def validate_light_inventory(report: dict) -> list[str]:
    """Validate the checked review baseline against the current semantic inventory."""

    errors = []
    review = _light_review()
    if review.get("schema_version") != 1:
        errors.append("light-source review must use schema_version 1")
    if (
        not isinstance(review.get("review_method"), str)
        or len(review["review_method"].strip()) < 12
    ):
        errors.append("light-source review needs a concise review_method")
    expected = {
        "archetypes": {row["id"] for row in report["archetypes"]},
        "artifacts": {row["id"] for row in report["artifacts"]},
        "maps": {row["path"] for row in report["maps"]},
    }
    batches = review.get("rendered_batches")
    if not isinstance(batches, dict):
        errors.append("light-source rendered_batches must be an object")
        batches = {}
    for identifier, entry in sorted(batches.items()):
        if not isinstance(entry, dict):
            errors.append("rendered batch {} must be an object".format(identifier))
            continue
        if not isinstance(entry.get("artifact"), str) or not entry["artifact"].endswith(
            ".png"
        ):
            errors.append("rendered batch {} needs a PNG artifact".format(identifier))
        if not isinstance(entry.get("method"), str) or len(entry["method"].strip()) < 12:
            errors.append("rendered batch {} needs a concise method".format(identifier))
    required_checks = {
        "overlap",
        "linked-depth",
        "horizontal-boundary",
        "dark-interior",
        "outdoor-transition",
        "fog-roof",
        "navigation",
    }
    for section, expected_ids in expected.items():
        entries = review.get(section)
        if not isinstance(entries, dict):
            errors.append("light-source review {} must be an object".format(section))
            continue
        actual_ids = set(entries)
        for missing in sorted(expected_ids - actual_ids):
            errors.append("unreviewed {} light source: {}".format(section[:-1], missing))
        for stale in sorted(actual_ids - expected_ids):
            errors.append("stale {} light-source review: {}".format(section[:-1], stale))
        for identifier, entry in sorted(entries.items()):
            if not isinstance(entry, dict):
                errors.append("{} {} review must be an object".format(section[:-1], identifier))
                continue
            if entry.get("uncolored_disposition") != "neutral":
                errors.append(
                    "{} {} must intentionally classify uncolored light as neutral".format(
                        section[:-1], identifier
                    )
                )
            if not isinstance(entry.get("rationale"), str) or len(entry["rationale"].strip()) < 12:
                errors.append("{} {} needs a concise rationale".format(section[:-1], identifier))
            if section == "maps" and not isinstance(entry.get("rendered_batch"), str):
                errors.append("map {} needs rendered_batch evidence".format(identifier))
            elif section == "maps" and entry["rendered_batch"] not in batches:
                errors.append("map {} references an unknown rendered batch".format(identifier))
            if section == "maps":
                checks = entry.get("checks")
                if not isinstance(checks, list) or set(checks) != required_checks:
                    errors.append(
                        "map {} must record every contextual lighting check".format(
                            identifier
                        )
                    )
    map_entries = review.get("maps")
    referenced_batches = {
        entry.get("rendered_batch")
        for entry in map_entries.values()
        if isinstance(entry, dict) and isinstance(entry.get("rendered_batch"), str)
    } if isinstance(map_entries, dict) else set()
    for identifier in sorted(set(batches) - referenced_batches):
        errors.append("stale rendered light-review batch: {}".format(identifier))
    palette = review.get("palette")
    if not isinstance(palette, dict):
        errors.append("light-source review palette must be an object")
        palette = {}
    for color in report["summary"]["colors"]:
        entry = palette.get(color)
        if (
            LIGHT_COLOR_RE.fullmatch(color) is None
            or not isinstance(entry, dict)
            or not isinstance(entry.get("rationale"), str)
        ):
            errors.append("explicit light color {} needs a palette rationale".format(color))
    for color in sorted(set(palette) - set(report["summary"]["colors"])):
        errors.append("stale explicit light-color palette entry: {}".format(color))
    if report["summary"]["unreviewed"]:
        errors.append(
            "{} effective light sources remain unreviewed".format(
                report["summary"]["unreviewed"]
            )
        )
    return errors


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
            is_monster = (
                obj_type in {"80", "83"}
                or base.get("is_male") == "1"
                or base.get("is_female") == "1"
            )
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
            elif (
                explicit_name
                and obj_type
                and obj_type not in {"0", "1", "2", "8", "20", "21", "66"}
            ):
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
        choices=("quests", "regions", "artifacts", "world", "lights", "all"),
        default="all",
        nargs="?",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail when the effective light-source review baseline is incomplete",
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
    if args.section in ("lights", "all"):
        result["lights"] = light_inventory()
    if args.check:
        if args.section not in ("lights", "all"):
            parser.error("--check requires the lights or all section")
        errors = validate_light_inventory(result["lights"])
        if errors:
            for error in errors:
                print(error, file=sys.stderr)
            raise SystemExit(1)
        summary = result["lights"]["summary"]
        print(
            "Effective light-source review: {archetypes} archetypes, "
            "{artifacts} artifacts, {map_instances} instances across {maps} maps; "
            "{explicit_color} explicit colors, {intentional_neutral} intentional "
            "neutral, zero unreviewed.".format(**summary)
        )
        return
    print(json.dumps(result if args.section == "all" else result[args.section], indent=2))


if __name__ == "__main__":
    main()
