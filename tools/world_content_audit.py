#!/usr/bin/env python3
"""Read-only exploratory inventory helper for Atrinik world content.

Prints deterministic JSON to stdout and never modifies authored data. This
report complements, but does not replace, tools.validate or content_catalog.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.content_core import Document, Node, parse_bytes


ROOT = Path(__file__).resolve().parents[1]
MAP_ROOT = ROOT / "maps"
ARCH_ROOT = ROOT / "arch"
LIGHT_REVIEW_NAME = "light-source-review.json"
LIGHT_FIXTURE_CONTRACT_NAME = "light-source-fixture-contract.json"
LIGHT_COLOR_RE = re.compile(r"^[0-9a-f]{6}$")


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
        "field_lines": {
            record.name: record.span.line
            for record in node.fields
        },
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
) -> tuple[dict[str, list[str]], dict[str, int]]:
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
    field_lines = {}
    for _, event_kind, record in sorted(events, key=lambda event: event[0]):
        if event_kind == "message":
            attrs["msg"].append(record.text.strip())
            continue
        raw = document.source[record.start_byte : record.end_byte].decode("utf-8")
        line = raw.rstrip("\n")
        key, separator, value = line.partition(" ")
        if separator:
            attrs[key].append(value.strip())
            field_lines[key] = record.line
    return dict(attrs), field_lines


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
            attrs, field_lines = _legacy_archetype_attrs(document, node)
            out[node.name] = {
                "path": str(path.relative_to(ROOT)),
                "attrs": {key: vals[-1] for key, vals in attrs.items() if vals},
                "field_lines": field_lines,
                "object_line": node.opener_span.line,
            }
    return out


def one(attrs: dict, key: str, default=None):
    vals = attrs.get(key)
    return vals[-1] if vals else default


def flatten(nodes: list[dict], parent: dict | None = None):
    for node in nodes:
        yield node, parent
        yield from flatten(node["children"], node)


def flatten_map_objects(nodes: list[dict]):
    """Yield map objects with their effective containing map coordinates."""

    def descendants(node: dict, parent: dict | None, x: int, y: int):
        yield node, parent, x, y
        for child in node["children"]:
            yield from descendants(child, node, x, y)

    for node in nodes:
        attrs = node["attrs"]
        try:
            x = int(one(attrs, "x", "0"))
        except ValueError:
            x = 0
        try:
            y = int(one(attrs, "y", "0"))
        except ValueError:
            y = 0
        yield from descendants(node, None, x, y)


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
            allowed = "all"
            allowed_line = None
            previous = start - 1
            while previous >= 0:
                raw = lines[previous]
                if raw.startswith("Allowed "):
                    allowed = raw.split(" ", 1)[1]
                    allowed_line = previous + 1
                    break
                if raw == "end" or raw.startswith("artifact "):
                    break
                previous -= 1
            i += 1
            while i < len(lines) and not lines[i].startswith("artifact "):
                i += 1
            chunk = lines[start:i]
            attrs = fields([x + "\n" for x in chunk])
            artifact_field_lines = {}
            for offset, raw in enumerate(chunk, start + 1):
                if raw == "Object":
                    break
                key, separator, _ = raw.partition(" ")
                if separator:
                    artifact_field_lines[key] = offset
            object_attrs = {}
            object_field_lines = {}
            object_line = None
            if "Object" in chunk:
                oi = chunk.index("Object") + 1
                object_line = start + oi
                try:
                    oe = chunk.index("end", oi)
                except ValueError:
                    oe = len(chunk)
                object_attrs = fields([x + "\n" for x in chunk[oi:oe]])
                for offset, raw in enumerate(chunk[oi:oe], start + oi + 1):
                    key, separator, _ = raw.partition(" ")
                    if separator:
                        object_field_lines[key] = offset
            artifacts.append({
                "id": artifact_id,
                "path": str(path.relative_to(ROOT)),
                "artifact_line": start + 1,
                "object_line": object_line,
                "allowed": allowed,
                "allowed_line": allowed_line,
                "def_arch": one(attrs, "def_arch"),
                "chance": one(attrs, "chance"),
                "attrs": {key: vals[-1] for key, vals in object_attrs.items() if vals},
                "artifact_field_lines": artifact_field_lines,
                "field_lines": object_field_lines,
            })
    return artifacts


def _nonzero_radius(value) -> int | None:
    """Return a nonzero Classic light radius, or None for a non-emitter."""

    try:
        radius = int(value or 0)
    except (TypeError, ValueError):
        return None
    return radius if radius != 0 else None


def _effective_radius(attrs: dict, base: dict | None = None):
    """Resolve a continuous radius or the lit state of a toggleable light."""

    base = base or {}
    radius = _nonzero_radius(attrs.get("glow_radius", base.get("glow_radius")))
    if radius is not None:
        return radius, "glow_radius", "continuous"
    type_ = attrs.get("type", base.get("type"))
    if type_ == "74":
        radius = _nonzero_radius(attrs.get("last_sp", base.get("last_sp")))
        if radius is not None:
            return radius, "last_sp", "toggle-active"
    return None, None, None


def _source_location(
    kind: str,
    path: str,
    identity: str,
    object_line: int,
    field: str,
    field_line: int,
) -> dict:
    """Return a stable, source-located field provenance record."""

    return {
        "kind": kind,
        "path": path,
        "object": identity,
        "object_line": object_line,
        "field": field,
        "field_line": field_line,
    }


def _archetype_source(definition: dict, identity: str, field: str) -> dict | None:
    line = definition.get("field_lines", {}).get(field)
    if line is None:
        return None
    return _source_location(
        "archetype",
        definition["path"],
        identity,
        definition["object_line"],
        field,
        line,
    )


def _artifact_source(artifact: dict, field: str) -> dict | None:
    line = artifact.get("field_lines", {}).get(field)
    if line is None:
        return None
    return _source_location(
        "artifact",
        artifact["path"],
        artifact["id"],
        artifact.get("object_line") or artifact["artifact_line"],
        field,
        line,
    )


def _map_source(path: str, node: dict, field: str) -> dict | None:
    line = node.get("field_lines", {}).get(field)
    if line is None:
        return None
    return _source_location(
        "map",
        path,
        node["arch"],
        node["line"],
        field,
        line,
    )


def _archetype_identity_source(definition: dict, identity: str) -> dict | None:
    """Locate the original archetype clone used by Classic activation."""

    line = definition.get("object_line")
    path = definition.get("path")
    if not isinstance(line, int) or not isinstance(path, str):
        return None
    return _source_location("archetype", path, identity, line, "Object", line)


def _artifact_activation_source(artifact: dict) -> dict | None:
    """Locate the runtime archetype clone used by artifact activation."""

    if artifact.get("allowed") == "none":
        return _source_location(
            "artifact",
            artifact["path"],
            artifact["id"],
            artifact["artifact_line"],
            "artifact",
            artifact["artifact_line"],
        )

    line = artifact.get("artifact_field_lines", {}).get("def_arch")
    if line is None:
        return None
    return _source_location(
        "artifact",
        artifact["path"],
        artifact["id"],
        artifact["artifact_line"],
        "def_arch",
        line,
    )


def _artifact_runtime_archetype(artifact: dict) -> str:
    """Return the ID Classic can create for this artifact definition."""

    if artifact.get("allowed") == "none":
        return artifact["id"]
    return artifact["def_arch"]


def _artifact_effective_source(
    artifact: dict, base_definition: dict, field: str
) -> dict | None:
    """Locate a field inherited by or authored on an artifact template."""

    if field in artifact.get("attrs", {}):
        return _artifact_source(artifact, field)
    return _archetype_source(base_definition, artifact["def_arch"], field)


def _map_activation_source(path: str, node: dict) -> dict:
    """Locate the map `arch` opener that selects the activation clone."""

    return _source_location(
        "map", path, node["arch"], node["line"], "arch", node["line"]
    )


def _active_art(
    definition: dict,
    identity: str,
    effective_face,
    effective_face_source,
    effective_animation,
    effective_animation_source,
    anim_speed,
) -> tuple[object, dict | None, object, dict | None]:
    """Resolve art after Classic activates a resting type-74 light.

    `light_apply` restores the animation from `op->arch->clone` whenever the
    effective animation speed is nonzero.  The active rendered face therefore
    comes from that same original clone rather than a resting map or artifact
    override.  A non-animated light retains its effective authored art.
    """

    try:
        animated = int(anim_speed or 0) != 0
    except (TypeError, ValueError):
        animated = False
    if not animated:
        return (
            effective_face,
            effective_face_source,
            effective_animation,
            effective_animation_source,
        )
    attrs = definition.get("attrs", {})
    return (
        attrs.get("face"),
        _archetype_source(definition, identity, "face"),
        attrs.get("animation"),
        _archetype_source(definition, identity, "animation"),
    )


def _effective_color(value) -> str | None:
    """Normalize an authored RGB tint; absence retains Classic neutral white."""

    if value is None:
        return None
    return str(value).lower()


def _visible_emitter(face, type_, sys_object) -> bool:
    """Return whether an effective emitter has independently rendered art."""

    return bool(face and not str(face).startswith("blank.")) and not (
        type_ == "78" and sys_object == "1"
    )


def _semantic_sha256(value) -> str:
    encoded = json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _source_semantic_sha256(row: dict) -> str:
    return _semantic_sha256(
        {
            key: row.get(key)
            for key in (
                "id",
                "path",
                "archetype",
                "runtime_archetype",
                "runtime_archetype_source",
                "activation_archetype",
                "activation_archetype_source",
                "activation",
                "radius",
                "radius_source",
                "color",
                "color_source",
                "visible",
                "face",
                "face_source",
                "animation",
                "animation_source",
                "active_face",
                "active_face_source",
                "active_animation",
                "active_animation_source",
                "active_visible",
            )
        }
    )


def _map_semantic_sha256(row: dict) -> str:
    emitters = [
        {
            key: emitter.get(key)
            for key in (
                "archetype",
                "x",
                "y",
                "radius",
                "radius_source",
                "activation",
                "color",
                "color_source",
                "visible",
                "face",
                "face_source",
                "animation",
                "animation_source",
                "activation_archetype",
                "activation_archetype_source",
                "active_face",
                "active_face_source",
                "active_animation",
                "active_animation_source",
                "active_visible",
                "art_override_fields",
                "review_scope",
            )
        }
        for emitter in row["emitters"]
    ]
    emitters.sort(key=lambda emitter: json.dumps(emitter, sort_keys=True))
    return _semantic_sha256(
        {
            "source_sha256": row.get("source_sha256"),
            "name": row.get("name"),
            "region": row.get("region"),
            "outdoor": row.get("outdoor"),
            "darkness": row.get("darkness"),
            "emitters": emitters,
        }
    )


def _light_review() -> dict:
    path = MAP_ROOT / LIGHT_REVIEW_NAME
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _light_fixture_contract() -> dict:
    """Load the source-independent required fixture inventory contract."""

    path = MAP_ROOT / LIGHT_FIXTURE_CONTRACT_NAME
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _required_context_checks(review: dict, contract: dict) -> set[str]:
    """Return baseline checks plus fixture-specific semantic review checks."""

    checks = {
        "overlap", "linked-depth", "horizontal-boundary", "dark-interior",
        "outdoor-transition", "fog-roof", "navigation",
    }
    for source in (review, contract):
        fixture_groups = source.get("fixture_groups", {})
        if isinstance(fixture_groups, dict):
            for entry in fixture_groups.values():
                if isinstance(entry, dict) and isinstance(entry.get("checks"), list):
                    checks.update(
                        check for check in entry["checks"] if isinstance(check, str)
                    )
    return checks


def _valid_source_location(source: object) -> bool:
    """Return whether a provenance record identifies one exact authored field."""

    return (
        isinstance(source, dict)
        and source.get("kind") in {"archetype", "artifact", "map"}
        and isinstance(source.get("path"), str)
        and isinstance(source.get("object"), str)
        and isinstance(source.get("object_line"), int)
        and source["object_line"] > 0
        and isinstance(source.get("field"), str)
        and isinstance(source.get("field_line"), int)
        and source["field_line"] > 0
    )


def _review_disposition(review: dict | None, color: str | None) -> tuple[str, str | None]:
    if color is not None:
        return "explicit-color", color
    if review and review.get("uncolored_disposition") == "neutral":
        return "intentional-neutral", None
    return "unreviewed", None


def light_inventory() -> dict:
    """Resolve every effective archetype, artifact, and map light emitter."""

    review = _light_review()
    fixture_contract = _light_fixture_contract()
    archetypes = load_archetypes()
    fixture_reviews = review.get("fixture_groups", {})
    if not isinstance(fixture_reviews, dict):
        fixture_reviews = {}
    contract_reviews = fixture_contract.get("fixture_groups", {})
    if not isinstance(contract_reviews, dict):
        contract_reviews = {}
    fixture_archetypes: dict[str, set[str]] = defaultdict(set)
    fixture_rows: dict[str, list[dict]] = defaultdict(list)
    for source in (fixture_reviews, contract_reviews):
        for group_id, entry in sorted(source.items()):
            if not isinstance(entry, dict) or not isinstance(entry.get("archetypes"), list):
                continue
            fixture_archetypes[group_id].update(
                archetype for archetype in entry["archetypes"]
                if isinstance(archetype, str)
            )
    fixture_groups_by_archetype: dict[str, list[str]] = defaultdict(list)
    for group_id, members in sorted(fixture_archetypes.items()):
        for archetype in sorted(members):
            fixture_groups_by_archetype[archetype].append(group_id)
    archetype_rows = []
    for archetype, definition in sorted(archetypes.items()):
        attrs = definition["attrs"]
        radius, radius_field, activation = _effective_radius(attrs)
        if radius is None:
            continue
        color = _effective_color(attrs.get("light_color"))
        disposition, resolved_color = _review_disposition(
            review.get("archetypes", {}).get(archetype), color
        )
        face = attrs.get("face")
        face_source = _archetype_source(definition, archetype, "face")
        animation = attrs.get("animation")
        animation_source = _archetype_source(definition, archetype, "animation")
        activation_archetype = None
        activation_archetype_source = None
        active_face = active_face_source = None
        active_animation = active_animation_source = None
        active_visible = None
        if activation == "toggle-active":
            activation_archetype = archetype
            activation_archetype_source = _archetype_identity_source(
                definition, archetype
            )
            (
                active_face,
                active_face_source,
                active_animation,
                active_animation_source,
            ) = _active_art(
                definition,
                archetype,
                face,
                face_source,
                animation,
                animation_source,
                attrs.get("anim_speed"),
            )
            active_visible = _visible_emitter(
                active_face, attrs.get("type"), attrs.get("sys_object")
            )
        row = {
            "id": archetype,
            "path": definition["path"],
            "object_line": definition["object_line"],
            "activation": activation,
            "activation_archetype": activation_archetype,
            "activation_archetype_source": activation_archetype_source,
            "radius": radius,
            "radius_source": _archetype_source(definition, archetype, radius_field),
            "color": resolved_color,
            "color_source": _archetype_source(definition, archetype, "light_color"),
            "visible": _visible_emitter(
                face, attrs.get("type"), attrs.get("sys_object")
            ),
            "face": face,
            "face_source": face_source,
            "animation": animation,
            "animation_source": animation_source,
            "active_face": active_face,
            "active_face_source": active_face_source,
            "active_animation": active_animation,
            "active_animation_source": active_animation_source,
            "active_visible": active_visible,
            "disposition": disposition,
            "rationale": review.get("archetypes", {}).get(archetype, {}).get(
                "rationale"
            ),
        }
        row["semantic_sha256"] = _source_semantic_sha256(row)
        archetype_rows.append(row)

    artifact_rows = []
    artifacts = artifact_inventory()
    artifacts_by_id = {artifact["id"]: artifact for artifact in artifacts}
    for artifact in artifacts:
        base = archetypes.get(artifact["def_arch"], {}).get("attrs", {})
        base_definition = archetypes.get(artifact["def_arch"], {})
        attrs = artifact["attrs"]
        radius, radius_field, activation = _effective_radius(attrs, base)
        if radius is None:
            continue
        color = _effective_color(attrs.get("light_color", base.get("light_color")))
        disposition, resolved_color = _review_disposition(
            review.get("artifacts", {}).get(artifact["id"]), color
        )
        face = attrs.get("face", base.get("face"))
        animation = attrs.get("animation", base.get("animation"))
        radius_source = (
            _artifact_source(artifact, radius_field)
            if radius_field in attrs
            else _archetype_source(base_definition, artifact["def_arch"], radius_field)
        )
        color_source = (
            _artifact_source(artifact, "light_color")
            if "light_color" in attrs
            else _archetype_source(base_definition, artifact["def_arch"], "light_color")
        )
        face_source = (
            _artifact_source(artifact, "face")
            if "face" in attrs
            else _archetype_source(base_definition, artifact["def_arch"], "face")
        )
        animation_source = (
            _artifact_source(artifact, "animation")
            if "animation" in attrs
            else _archetype_source(
                base_definition, artifact["def_arch"], "animation"
            )
        )
        activation_archetype = None
        activation_archetype_source = None
        active_face = active_face_source = None
        active_animation = active_animation_source = None
        active_visible = None
        if activation == "toggle-active":
            activation_archetype = _artifact_runtime_archetype(artifact)
            activation_archetype_source = _artifact_activation_source(artifact)
            if artifact.get("allowed") != "none":
                (
                    active_face,
                    active_face_source,
                    active_animation,
                    active_animation_source,
                ) = _active_art(
                    base_definition,
                    artifact["def_arch"],
                    face,
                    face_source,
                    animation,
                    animation_source,
                    attrs.get("anim_speed", base.get("anim_speed")),
                )
            else:
                try:
                    animated = int(
                        attrs.get("anim_speed", base.get("anim_speed")) or 0
                    ) != 0
                except (TypeError, ValueError):
                    animated = False
                if animated:
                    active_face = attrs.get("face", base.get("face"))
                    active_face_source = _artifact_effective_source(
                        artifact, base_definition, "face"
                    )
                    active_animation = attrs.get("animation", base.get("animation"))
                    active_animation_source = _artifact_effective_source(
                        artifact, base_definition, "animation"
                    )
                else:
                    active_face, active_face_source = face, face_source
                    active_animation, active_animation_source = (
                        animation,
                        animation_source,
                    )
            active_visible = _visible_emitter(
                active_face,
                attrs.get("type", base.get("type")),
                attrs.get("sys_object", base.get("sys_object")),
            )
        row = {
            "id": artifact["id"],
            "path": artifact["path"],
            "archetype": artifact["def_arch"],
            "runtime_archetype": _artifact_runtime_archetype(artifact),
            "runtime_archetype_source": _artifact_activation_source(artifact),
            "object_line": artifact.get("object_line"),
            "activation": activation,
            "activation_archetype": activation_archetype,
            "activation_archetype_source": activation_archetype_source,
            "radius": radius,
            "radius_source": radius_source,
            "color": resolved_color,
            "color_source": color_source,
            "visible": _visible_emitter(
                face,
                attrs.get("type", base.get("type")),
                attrs.get("sys_object", base.get("sys_object")),
            ),
            "face": face,
            "face_source": face_source,
            "animation": animation,
            "animation_source": animation_source,
            "active_face": active_face,
            "active_face_source": active_face_source,
            "active_animation": active_animation,
            "active_animation_source": active_animation_source,
            "active_visible": active_visible,
            "disposition": disposition,
            "rationale": review.get("artifacts", {}).get(artifact["id"], {}).get(
                "rationale"
            ),
        }
        row["semantic_sha256"] = _source_semantic_sha256(row)
        artifact_rows.append(row)

    map_rows = []
    reviewed_maps = {}
    for path in map_files():
        parsed = parse_blocks(path)
        relative = path.relative_to(ROOT).as_posix()
        map_review = review.get("maps", {}).get(relative)
        emitters = []
        fixture_ordinals: dict[tuple[str, str, int, int], int] = defaultdict(int)
        for node, parent, x, y in flatten_map_objects(parsed["objects"]):
            attrs = node["attrs"]
            # Classic registers every parsed artifact clone as an archetype,
            # regardless of its Allowed selector.  A map can therefore refer
            # directly to either an Allowed-none quest object or a normally
            # artified object by its artifact ID.  In both cases the map
            # object's arch pointer is the registered artifact clone, so an
            # activated type-74 object restores that clone's art rather than
            # the base def_arch art used by ordinary artification.
            registered_artifact = artifacts_by_id.get(node["arch"])
            if registered_artifact is not None:
                definition = archetypes.get(registered_artifact["def_arch"], {})
                base = dict(definition.get("attrs", {}))
                base.update(registered_artifact.get("attrs", {}))

                def definition_source(field):
                    return _artifact_effective_source(
                        registered_artifact, definition, field
                    )
            else:
                registered_artifact = None
                definition = archetypes.get(node["arch"], {})
                base = definition.get("attrs", {})

                def definition_source(field):
                    return _archetype_source(definition, node["arch"], field)
            overrides = {
                field: one(attrs, field)
                for field in ("glow_radius", "last_sp", "type")
                if field in attrs
            }
            radius, radius_field, activation = _effective_radius(overrides, base)
            fixture_group_ids = fixture_groups_by_archetype.get(node["arch"], ())
            if radius is None and not fixture_group_ids:
                continue
            color = _effective_color(one(attrs, "light_color", base.get("light_color")))
            face = one(attrs, "face", base.get("face"))
            animation = one(attrs, "animation", base.get("animation"))
            visible = _visible_emitter(
                face,
                one(attrs, "type", base.get("type")),
                one(attrs, "sys_object", base.get("sys_object")),
            )
            if fixture_group_ids:
                raw_local_radius = one(attrs, "glow_radius")
                try:
                    local_radius = (
                        int(raw_local_radius) if raw_local_radius is not None else None
                    )
                except (TypeError, ValueError):
                    local_radius = None
                fixture_radius_source = (
                    _map_source(relative, node, "glow_radius")
                    if "glow_radius" in attrs
                    else definition_source("glow_radius")
                )
                fixture_color_source = (
                    _map_source(relative, node, "light_color")
                    if "light_color" in attrs
                    else definition_source("light_color")
                )
                for group_id in fixture_group_ids:
                    ordinal_key = (group_id, node["arch"], x, y)
                    fixture_ordinals[ordinal_key] += 1
                    ordinal = fixture_ordinals[ordinal_key]
                    fixture_rows[group_id].append({
                        "id": "{}:{}:{}:{}:{}".format(
                            relative, x, y, node["arch"], ordinal
                        ),
                        "source_id": "{}:{}".format(relative, node["line"]),
                        "path": relative,
                        "line": node["line"],
                        "archetype": node["arch"],
                        "x": x,
                        "y": y,
                        "ordinal": ordinal,
                        "radius": radius,
                        "local_radius": local_radius,
                        "radius_source": fixture_radius_source,
                        "color": color,
                        "color_source": fixture_color_source,
                        "visible": visible,
                        "same_tile_emitters": [],
                    })
            if radius is None:
                continue
            review_scope = "artifact" if registered_artifact else "archetype"
            source_review = (
                review.get("artifacts", {}).get(node["arch"])
                if registered_artifact
                else review.get("archetypes", {}).get(node["arch"])
            )
            art_override_fields = [
                field for field in ("face", "animation") if field in attrs
            ]
            if (
                (node["arch"] not in archetypes and registered_artifact is None)
                or radius_field in attrs
                or art_override_fields
            ):
                review_scope = "map"
                if visible and color is None:
                    rationale = (
                        map_review.get("visible_neutral", {}).get(node["arch"])
                        if map_review else None
                    )
                    source_review = (
                        {"uncolored_disposition": "neutral", "rationale": rationale}
                        if isinstance(rationale, str) else None
                    )
                else:
                    source_review = map_review
            disposition, resolved_color = _review_disposition(source_review, color)
            radius_source = (
                _map_source(relative, node, radius_field)
                if radius_field in attrs
                else definition_source(radius_field)
            )
            color_source = (
                _map_source(relative, node, "light_color")
                if "light_color" in attrs
                else definition_source("light_color")
            )
            color_source_id = (
                registered_artifact["def_arch"]
                if registered_artifact is not None
                else node["arch"]
            )
            color_review = review.get("color_sources", {}).get(color_source_id, {})
            face_source = (
                _map_source(relative, node, "face")
                if "face" in attrs
                else definition_source("face")
            )
            animation_source = (
                _map_source(relative, node, "animation")
                if "animation" in attrs
                else definition_source("animation")
            )
            activation_archetype = None
            activation_archetype_source = None
            active_face = active_face_source = None
            active_animation = active_animation_source = None
            active_visible = None
            if activation == "toggle-active":
                activation_archetype = node["arch"]
                activation_archetype_source = _map_activation_source(relative, node)
                if registered_artifact is None:
                    (
                        active_face,
                        active_face_source,
                        active_animation,
                        active_animation_source,
                    ) = _active_art(
                        definition,
                        node["arch"],
                        face,
                        face_source,
                        animation,
                        animation_source,
                        one(attrs, "anim_speed", base.get("anim_speed")),
                    )
                else:
                    try:
                        animated = int(
                            one(attrs, "anim_speed", base.get("anim_speed")) or 0
                        ) != 0
                    except (TypeError, ValueError):
                        animated = False
                    if animated:
                        active_face = base.get("face")
                        active_face_source = definition_source("face")
                        active_animation = base.get("animation")
                        active_animation_source = definition_source("animation")
                    else:
                        active_face, active_face_source = face, face_source
                        active_animation, active_animation_source = (
                            animation,
                            animation_source,
                        )
                active_visible = _visible_emitter(
                    active_face,
                    one(attrs, "type", base.get("type")),
                    one(attrs, "sys_object", base.get("sys_object")),
                )
            art_rationale = (
                map_review.get("art_overrides", {}).get(str(node["line"]))
                if map_review else None
            )
            emitters.append({
                "id": "{}:{}".format(relative, node["line"]),
                "line": node["line"],
                "archetype": node["arch"],
                "x": x,
                "y": y,
                "activation": activation,
                "activation_archetype": activation_archetype,
                "activation_archetype_source": activation_archetype_source,
                "radius": radius,
                "radius_source": radius_source,
                "color": resolved_color,
                "color_source": color_source,
                "color_rationale": (
                    color_review.get("rationale")
                    if color_source and color_source["kind"] == "archetype"
                    else None
                ),
                "visible": visible,
                "face": face,
                "face_source": face_source,
                "animation": animation,
                "animation_source": animation_source,
                "active_face": active_face,
                "active_face_source": active_face_source,
                "active_animation": active_animation,
                "active_animation_source": active_animation_source,
                "active_visible": active_visible,
                "art_override_fields": art_override_fields,
                "art_rationale": art_rationale,
                "review_scope": review_scope,
                "disposition": disposition,
                "rationale": (
                    art_rationale
                    if art_override_fields
                    else source_review.get("rationale") if source_review else None
                ),
            })
        if not emitters:
            continue
        header = parsed["header"]["attrs"] if parsed["header"] else {}
        row = {
            "path": relative,
            "name": one(header, "name"),
            "region": one(header, "region"),
            "outdoor": one(header, "outdoor") == "1",
            "darkness": one(header, "darkness"),
            "rationale": map_review.get("rationale") if map_review else None,
            "emitters": emitters,
        }
        row["source_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        row["semantic_sha256"] = _map_semantic_sha256(row)
        reviewed_maps[relative] = row
        map_rows.extend(emitters)

    emitters_by_origin: dict[tuple[str, int, int], list[str]] = defaultdict(list)
    for emitter in map_rows:
        emitters_by_origin[(
            emitter["id"].rsplit(":", 1)[0], emitter["x"], emitter["y"]
        )].append(emitter["id"])
    fixture_group_rows = []
    for group_id, placements in sorted(fixture_rows.items()):
        for placement in placements:
            placement["same_tile_emitters"] = sorted(
                identifier
                for identifier in emitters_by_origin.get(
                    (placement["path"], placement["x"], placement["y"]), ()
                )
                if identifier != placement["source_id"]
            )
        group = {
            "id": group_id,
            "archetypes": sorted(fixture_archetypes[group_id]),
            "maps": len({placement["path"] for placement in placements}),
            "placements": placements,
        }
        group["semantic_sha256"] = _semantic_sha256(group)
        fixture_group_rows.append(group)

    rows = archetype_rows + artifact_rows + map_rows
    color_source_ids = {
        row["id"]
        for row in archetype_rows
        if row["color"] is not None
    }
    color_source_ids.update(
        row["color_source"]["object"]
        for row in map_rows
        if row["color"] is not None
        and (row.get("color_source") or {}).get("kind") == "archetype"
    )
    color_source_ids.update(
        row["color_source"]["object"]
        for row in artifact_rows
        if row["color"] is not None
        and (row.get("color_source") or {}).get("kind") == "archetype"
    )
    color_source_rows = []
    for archetype in sorted(color_source_ids):
        definition = archetypes[archetype]
        color = _effective_color(definition["attrs"].get("light_color"))
        row = {
            "id": archetype,
            "path": definition["path"],
            "object_line": definition["object_line"],
            "color": color,
            "color_source": _archetype_source(definition, archetype, "light_color"),
            "rationale": review.get("color_sources", {}).get(archetype, {}).get(
                "rationale"
            ),
        }
        row["semantic_sha256"] = _semantic_sha256({
            key: row[key]
            for key in ("id", "path", "object_line", "color", "color_source")
        })
        color_source_rows.append(row)
    toggle_groups = {}
    for kind, state_rows in (
        ("archetype", archetype_rows),
        ("artifact", artifact_rows),
        ("map", map_rows),
    ):
        for state_row in state_rows:
            if state_row.get("activation") != "toggle-active":
                continue
            state_identity = {
                "activation_archetype": state_row.get("activation_archetype"),
                "radius": state_row.get("radius"),
                "color": state_row.get("color"),
                "face": state_row.get("active_face"),
                "animation": state_row.get("active_animation"),
                "visible": state_row.get("active_visible"),
            }
            identifier = _semantic_sha256(state_identity)
            group = toggle_groups.setdefault(identifier, {
                "id": identifier,
                **state_identity,
                "face_source": state_row.get("active_face_source"),
                "animation_source": state_row.get("active_animation_source"),
                "sources": [],
            })
            group["sources"].append({"kind": kind, "id": state_row["id"]})
    toggle_state_rows = []
    for identifier, row in sorted(toggle_groups.items()):
        row["sources"] = sorted(
            row["sources"], key=lambda item: (item["kind"], item["id"])
        )
        row["semantic_sha256"] = _semantic_sha256(row)
        row["rationale"] = review.get("toggle_states", {}).get(
            identifier, {}
        ).get("rationale")
        toggle_state_rows.append(row)
    colors = sorted({row["color"] for row in rows if row["color"] is not None})
    return {
        "schema_version": 1,
        "kind": "effective-light-source-inventory",
        "palette": review.get("palette", {}),
        "summary": {
            "archetypes": len(archetype_rows),
            "artifacts": len(artifact_rows),
            "color_sources": len(color_source_rows),
            "toggle_states": len(toggle_state_rows),
            "fixture_groups": len(fixture_group_rows),
            "fixture_placements": sum(
                len(group["placements"]) for group in fixture_group_rows
            ),
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
        "color_sources": color_source_rows,
        "toggle_states": toggle_state_rows,
        "fixture_groups": fixture_group_rows,
        "maps": [reviewed_maps[path] for path in sorted(reviewed_maps)],
    }


def validate_light_inventory(report: dict) -> list[str]:
    """Validate the checked review baseline against the current semantic inventory."""

    errors = []
    review = _light_review()
    fixture_contract = _light_fixture_contract()
    if review.get("schema_version") != 6:
        errors.append("light-source review must use schema_version 6")
    if (
        not isinstance(review.get("review_method"), str)
        or len(review["review_method"].strip()) < 12
    ):
        errors.append("light-source review needs a concise review_method")
    expected = {
        "archetypes": {row["id"] for row in report["archetypes"]},
        "artifacts": {row["id"] for row in report["artifacts"]},
        "color_sources": {row["id"] for row in report["color_sources"]},
        "toggle_states": {row["id"] for row in report["toggle_states"]},
        "maps": {row["path"] for row in report["maps"]},
    }
    semantic_rows = {
        "archetypes": {row["id"]: row for row in report["archetypes"]},
        "artifacts": {row["id"]: row for row in report["artifacts"]},
        "color_sources": {row["id"]: row for row in report["color_sources"]},
        "toggle_states": {row["id"]: row for row in report["toggle_states"]},
        "maps": {row["path"]: row for row in report["maps"]},
    }
    fixture_review = review.get("fixture_groups")
    if not isinstance(fixture_review, dict):
        errors.append("light-source review fixture_groups must be an object")
        fixture_review = {}
    fixture_report = {
        row["id"]: row for row in report.get("fixture_groups", ())
    }
    if fixture_contract.get("schema_version") != 1:
        errors.append("light fixture contract must use schema_version 1")
    required_fixtures = fixture_contract.get("fixture_groups")
    if not isinstance(required_fixtures, dict):
        errors.append("light fixture contract fixture_groups must be an object")
        required_fixtures = {}
    for group_id, contract_entry in sorted(required_fixtures.items()):
        if not isinstance(contract_entry, dict):
            errors.append("required fixture group {} must be an object".format(group_id))
            continue
        for field in ("archetypes", "checks"):
            values = contract_entry.get(field)
            if (
                not isinstance(values, list)
                or not values
                or values != sorted(set(values))
                or any(not isinstance(value, str) or not value for value in values)
            ):
                errors.append(
                    "required fixture group {} has invalid {}".format(group_id, field)
                )
        review_entry = fixture_review.get(group_id)
        if not isinstance(review_entry, dict):
            errors.append("required fixture group {} is missing from review".format(group_id))
            continue
        for field in ("archetypes", "checks"):
            if review_entry.get(field) != contract_entry.get(field):
                errors.append(
                    "required fixture group {} {} changed".format(group_id, field)
                )
    for missing in sorted(set(fixture_review) - set(fixture_report)):
        errors.append("fixture group {} has no inventoried placements".format(missing))
    for stale in sorted(set(fixture_report) - set(fixture_review)):
        errors.append("unreviewed fixture group: {}".format(stale))
    archetypes_by_id = {row["id"]: row for row in report["archetypes"]}
    emitter_ids = {
        emitter["id"]
        for map_row in report["maps"]
        for emitter in map_row["emitters"]
    }
    for group_id, entry in sorted(fixture_review.items()):
        if not isinstance(entry, dict):
            errors.append("fixture group {} review must be an object".format(group_id))
            continue
        group = fixture_report.get(group_id)
        if group is None:
            continue
        if not isinstance(entry.get("rationale"), str) or len(
            entry["rationale"].strip()
        ) < 12:
            errors.append("fixture group {} needs a concise rationale".format(group_id))
        reviewed_archetypes = entry.get("archetypes")
        if (
            not isinstance(reviewed_archetypes, list)
            or reviewed_archetypes != sorted(set(reviewed_archetypes))
            or reviewed_archetypes != group["archetypes"]
        ):
            errors.append("fixture group {} has invalid archetype coverage".format(group_id))
            reviewed_archetypes = []
        placement_counts = Counter(
            placement["archetype"] for placement in group["placements"]
        )
        if entry.get("expected_placements") != dict(sorted(placement_counts.items())):
            errors.append("fixture group {} placement counts changed".format(group_id))
        if entry.get("expected_maps") != group["maps"]:
            errors.append("fixture group {} map coverage changed".format(group_id))
        expected_color = entry.get("expected_color")
        if not isinstance(expected_color, str) or LIGHT_COLOR_RE.fullmatch(
            expected_color
        ) is None:
            errors.append("fixture group {} has an invalid expected color".format(group_id))
        default_radii = entry.get("default_radii")
        if not isinstance(default_radii, dict):
            errors.append("fixture group {} default_radii must be an object".format(group_id))
            default_radii = {}
        for archetype in reviewed_archetypes:
            row = archetypes_by_id.get(archetype)
            if row is None or row.get("radius") != default_radii.get(archetype):
                errors.append(
                    "fixture group {} default radius changed for {}".format(
                        group_id, archetype
                    )
                )
            if row is None or row.get("color") != expected_color:
                errors.append(
                    "fixture group {} default color changed for {}".format(
                        group_id, archetype
                    )
                )
        non_emitters = {
            placement["id"]: placement
            for placement in group["placements"]
            if placement["radius"] is None
        }
        reviewed_non_emitters = entry.get("intentional_non_emitters")
        if not isinstance(reviewed_non_emitters, dict):
            errors.append(
                "fixture group {} intentional_non_emitters must be an object".format(
                    group_id
                )
            )
            reviewed_non_emitters = {}
        if set(reviewed_non_emitters) != set(non_emitters):
            errors.append(
                "fixture group {} non-emitting dispositions changed".format(group_id)
            )
        for identifier, rationale in sorted(reviewed_non_emitters.items()):
            if not isinstance(rationale, str) or len(rationale.strip()) < 12:
                errors.append(
                    "fixture {} needs a concise non-emitting rationale".format(
                        identifier
                    )
                )
        for placement in group["placements"]:
            if placement.get("color") != expected_color:
                errors.append(
                    "fixture {} does not resolve the reviewed color".format(
                        placement["id"]
                    )
                )
            same_tile = placement.get("same_tile_emitters")
            if placement["radius"] is None:
                if (
                    placement.get("local_radius") != 0
                    or not isinstance(same_tile, list)
                    or len(same_tile) != 1
                    or same_tile[0] not in emitter_ids
                ):
                    errors.append(
                        "non-emitting fixture {} lacks one reviewed composite source".format(
                            placement["id"]
                        )
                    )
            elif same_tile:
                errors.append(
                    "emitting fixture {} has an accidental same-tile source".format(
                        placement["id"]
                    )
                )
        checks = entry.get("checks")
        if (
            not isinstance(checks, list)
            or not checks
            or checks != sorted(set(checks))
            or any(not isinstance(check, str) or not check for check in checks)
        ):
            errors.append("fixture group {} has invalid review checks".format(group_id))
        if entry.get("semantic_sha256") != group["semantic_sha256"]:
            errors.append("fixture group {} changed since review".format(group_id))
    for section in ("archetypes", "artifacts"):
        for row in report[section]:
            for field in (
                "radius",
                "color",
                "face",
                "animation",
                "active_face",
                "active_animation",
            ):
                source = row.get(field + "_source")
                if (row.get(field) is not None) != _valid_source_location(source):
                    errors.append(
                        "{} {} has invalid {} provenance".format(
                            section[:-1], row["id"], field
                        )
                    )
            if row.get("activation") not in {"continuous", "toggle-active"}:
                errors.append(
                    "{} {} has invalid activation mode".format(
                        section[:-1], row["id"]
                    )
                )
            activation_archetype = row.get("activation_archetype")
            activation_source = row.get("activation_archetype_source")
            if row.get("activation") == "toggle-active":
                if (
                    not isinstance(activation_archetype, str)
                    or not activation_archetype
                    or not _valid_source_location(activation_source)
                    or not isinstance(row.get("active_visible"), bool)
                ):
                    errors.append(
                        "{} {} has invalid active-state provenance".format(
                            section[:-1], row["id"]
                        )
                    )
            elif activation_archetype is not None or activation_source is not None:
                errors.append(
                    "{} {} has unexpected active-state provenance".format(
                        section[:-1], row["id"]
                    )
                )
            if section == "artifacts" and (
                not isinstance(row.get("runtime_archetype"), str)
                or not row["runtime_archetype"]
                or not _valid_source_location(row.get("runtime_archetype_source"))
            ):
                errors.append(
                    "artifact {} has invalid runtime archetype provenance".format(
                        row["id"]
                    )
                )
    for row in report["color_sources"]:
        if not _valid_source_location(row.get("color_source")):
            errors.append(
                "color source {} has invalid field provenance".format(row["id"])
            )
    for map_row in report["maps"]:
        for emitter in map_row["emitters"]:
            for field in (
                "radius",
                "color",
                "face",
                "animation",
                "active_face",
                "active_animation",
            ):
                source = emitter.get(field + "_source")
                if (emitter.get(field) is not None) != _valid_source_location(source):
                    errors.append(
                        "map emitter {} has invalid {} provenance".format(
                            emitter["id"], field
                        )
                    )
            if emitter.get("activation") not in {"continuous", "toggle-active"}:
                errors.append(
                    "map emitter {} has invalid activation mode".format(emitter["id"])
                )
            activation_archetype = emitter.get("activation_archetype")
            activation_source = emitter.get("activation_archetype_source")
            if emitter.get("activation") == "toggle-active":
                if (
                    not isinstance(activation_archetype, str)
                    or not activation_archetype
                    or not _valid_source_location(activation_source)
                    or not isinstance(emitter.get("active_visible"), bool)
                ):
                    errors.append(
                        "map emitter {} has invalid active-state provenance".format(
                            emitter["id"]
                        )
                    )
            elif activation_archetype is not None or activation_source is not None:
                errors.append(
                    "map emitter {} has unexpected active-state provenance".format(
                        emitter["id"]
                    )
                )
    for row in report["toggle_states"]:
        if not isinstance(row.get("activation_archetype"), str) or not row[
            "activation_archetype"
        ]:
            errors.append(
                "toggle state {} lacks an activation archetype".format(row["id"])
            )
        for field in ("face", "animation"):
            source = row.get(field + "_source")
            if (row.get(field) is not None) != _valid_source_location(source):
                errors.append(
                    "toggle state {} has invalid {} provenance".format(
                        row["id"], field
                    )
                )
    required_checks = _required_context_checks(review, fixture_contract)
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
            if (
                section not in {"color_sources", "toggle_states"}
                and entry.get("uncolored_disposition") != "neutral"
            ):
                errors.append(
                    "{} {} must intentionally classify uncolored light as neutral".format(
                        section[:-1], identifier
                    )
                )
            if not isinstance(entry.get("rationale"), str) or len(entry["rationale"].strip()) < 12:
                errors.append("{} {} needs a concise rationale".format(section[:-1], identifier))
            expected_sha256 = semantic_rows[section].get(identifier, {}).get(
                "semantic_sha256"
            )
            if entry.get("semantic_sha256") != expected_sha256:
                errors.append(
                    "{} {} changed since its lighting review".format(
                        section[:-1], identifier
                    )
                )
            if section == "maps":
                expected_visible_neutral = {
                    emitter["archetype"]
                    for emitter in semantic_rows[section].get(identifier, {}).get(
                        "emitters", ()
                    )
                    if emitter["review_scope"] == "map"
                    and emitter["visible"]
                    and emitter["color"] is None
                }
                visible_neutral = entry.get("visible_neutral", {})
                if not isinstance(visible_neutral, dict):
                    errors.append(
                        "map {} visible_neutral must be an object".format(identifier)
                    )
                else:
                    actual_visible_neutral = set(visible_neutral)
                    for missing in sorted(
                        expected_visible_neutral - actual_visible_neutral
                    ):
                        errors.append(
                            "map {} needs a visible-neutral rationale for {}".format(
                                identifier, missing
                            )
                        )
                    for stale in sorted(
                        actual_visible_neutral - expected_visible_neutral
                    ):
                        errors.append(
                            "map {} has stale visible-neutral review for {}".format(
                                identifier, stale
                            )
                        )
                    for archetype, rationale in sorted(visible_neutral.items()):
                        if not isinstance(rationale, str) or len(rationale.strip()) < 12:
                            errors.append(
                                "map {} visible-neutral {} needs a concise rationale".format(
                                    identifier, archetype
                                )
                            )
                expected_art_overrides = {
                    str(emitter["line"])
                    for emitter in semantic_rows[section].get(identifier, {}).get(
                        "emitters", ()
                    )
                    if emitter.get("art_override_fields")
                }
                art_overrides = entry.get("art_overrides", {})
                if not isinstance(art_overrides, dict):
                    errors.append(
                        "map {} art_overrides must be an object".format(identifier)
                    )
                else:
                    for missing in sorted(expected_art_overrides - set(art_overrides)):
                        errors.append(
                            "map {} needs an art-override rationale for line {}".format(
                                identifier, missing
                            )
                        )
                    for stale in sorted(set(art_overrides) - expected_art_overrides):
                        errors.append(
                            "map {} has stale art-override review for line {}".format(
                                identifier, stale
                            )
                        )
                    for line, rationale in sorted(art_overrides.items()):
                        if not isinstance(rationale, str) or len(rationale.strip()) < 12:
                            errors.append(
                                "map {} art override {} needs a concise rationale".format(
                                    identifier, line
                                )
                            )
    context_checks = review.get("context_checks")
    if not isinstance(context_checks, dict):
        errors.append("light-source review context_checks must be an object")
        context_checks = {}
    for stale in sorted(set(context_checks) - required_checks):
        errors.append("stale contextual lighting check: {}".format(stale))
    for check in sorted(required_checks):
        entry = context_checks.get(check)
        if not isinstance(entry, dict) or entry.get("status") != "pass":
            errors.append("contextual lighting check {} must record pass".format(check))
            continue
        if not isinstance(entry.get("rationale"), str) or len(entry["rationale"].strip()) < 12:
            errors.append("contextual lighting check {} needs a rationale".format(check))
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
