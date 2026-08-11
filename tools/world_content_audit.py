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
from collections import defaultdict
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.content_core import Document, Node, parse_bytes


ROOT = Path(__file__).resolve().parents[1]
MAP_ROOT = ROOT / "maps"
ARCH_ROOT = ROOT / "arch"
LIGHT_REVIEW_NAME = "light-source-review.json"
LIGHT_EVIDENCE_NAME = "light-source-evidence/manifest.json"
LIGHT_COLOR_RE = re.compile(r"^[0-9a-f]{6}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
LIGHT_EVIDENCE_COLUMNS = 5
LIGHT_EVIDENCE_ROWS = 5
LIGHT_EVIDENCE_TILE_WIDTH = 204
LIGHT_EVIDENCE_TILE_HEIGHT = 153
LIGHT_EVIDENCE_WIDTH = LIGHT_EVIDENCE_COLUMNS * LIGHT_EVIDENCE_TILE_WIDTH
LIGHT_EVIDENCE_HEIGHT = LIGHT_EVIDENCE_ROWS * LIGHT_EVIDENCE_TILE_HEIGHT
_ART_INDEX_CACHE = {}
_ART_DIMENSION_CACHE = {}


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


def _light_evidence() -> dict:
    path = MAP_ROOT / LIGHT_EVIDENCE_NAME
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _inventory_semantic_sha256(report: dict) -> str:
    return _semantic_sha256(
        {
            section: [
                (row[identity], row["semantic_sha256"])
                for row in report[section]
            ]
            for section, identity in (
                ("archetypes", "id"),
                ("artifacts", "id"),
                ("color_sources", "id"),
                ("toggle_states", "id"),
                ("maps", "path"),
            )
        }
    )


def _is_review_only_runtime_path(relative: str) -> bool:
    """Return whether a path is review-only or generated runtime noise."""

    return (
        relative == "maps/light-source-review.json"
        or relative.startswith("maps/light-source-review/")
        or relative.startswith("maps/light-source-evidence/")
        or relative.startswith("maps/.light-source-evidence-build-")
        or "__pycache__" in relative.split("/")
        or relative.endswith(".pyc")
    )


def _is_light_review_scene(path: Path) -> bool:
    """Return whether a source path is an allowed non-runtime review scene."""

    try:
        resolved = path.resolve()
        return any(
            resolved.is_relative_to(root.resolve())
            for root in (
                MAP_ROOT / "light-source-review",
                ROOT / "tools" / "light-source-review",
            )
        )
    except OSError:
        return False


def _update_runtime_digest_path(
    digest, relative: str, size: int
) -> None:
    """Add one length-framed runtime path and blob size to a digest."""

    encoded = relative.encode("utf-8")
    digest.update(len(encoded).to_bytes(4, "big"))
    digest.update(encoded)
    digest.update(size.to_bytes(8, "big"))


def _runtime_content_sha256() -> str:
    """Hash the working tree's runtime content, excluding lighting review."""

    digest = hashlib.sha256()
    runtime_paths = []
    for root in (ARCH_ROOT, MAP_ROOT):
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(ROOT).as_posix()
            if _is_review_only_runtime_path(relative):
                continue
            runtime_paths.append((relative, path))
    for relative, path in sorted(runtime_paths):
        data = path.read_bytes()
        _update_runtime_digest_path(digest, relative, len(data))
        digest.update(data)
    return digest.hexdigest()


def _git_runtime_content_sha256(commit: str) -> str:
    """Hash one Git commit's runtime tree using the working-tree framing."""

    if not isinstance(commit, str) or re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise ValueError("content commit does not resolve")
    try:
        verified = subprocess.run(
            ["git", "rev-parse", "--verify", "{}^{{commit}}".format(commit)],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            text=True,
        )
    except OSError as error:
        raise ValueError("content commit does not resolve") from error
    if verified.returncode != 0:
        raise ValueError("content commit does not resolve")
    resolved = verified.stdout.strip()
    try:
        tree = subprocess.run(
            [
                "git",
                "ls-tree",
                "-r",
                "-z",
                "--full-tree",
                resolved,
                "--",
                "arch",
                "maps",
            ],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError as error:
        raise ValueError("content commit runtime tree cannot be read") from error
    if tree.returncode != 0:
        raise ValueError("content commit runtime tree cannot be read")

    blobs = []
    for record in tree.stdout.split(b"\0"):
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        _, object_type, object_id = metadata.split(b" ", 2)
        relative = raw_path.decode("utf-8")
        if _is_review_only_runtime_path(relative):
            continue
        if object_type != b"blob":
            raise ValueError("content commit runtime tree contains a non-file entry")
        blobs.append((relative, object_id))

    digest = hashlib.sha256()
    try:
        process = subprocess.Popen(
            ["git", "cat-file", "--batch"],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError as error:
        raise ValueError("content commit runtime blobs cannot be read") from error
    try:
        if process.stdin is None or process.stdout is None:
            raise ValueError("content commit runtime blobs cannot be read")
        for relative, object_id in sorted(blobs):
            process.stdin.write(object_id + b"\n")
            process.stdin.flush()
            header = process.stdout.readline().rstrip(b"\n").split(b" ")
            if len(header) != 3 or header[1] != b"blob":
                raise ValueError("content commit runtime blob cannot be read")
            size = int(header[2])
            _update_runtime_digest_path(digest, relative, size)
            remaining = size
            while remaining:
                chunk = process.stdout.read(min(remaining, 1024 * 1024))
                if not chunk:
                    raise ValueError("content commit runtime blob is truncated")
                digest.update(chunk)
                remaining -= len(chunk)
            if process.stdout.read(1) != b"\n":
                raise ValueError("content commit runtime blob is malformed")
        process.stdin.close()
        if process.wait() != 0:
            raise ValueError("content commit runtime blobs cannot be read")
    except BaseException:
        if process.stdin is not None and not process.stdin.closed:
            process.stdin.close()
        if process.poll() is None:
            process.kill()
            process.wait()
        raise
    finally:
        if process.stdout is not None:
            process.stdout.close()
    return digest.hexdigest()


def _image_dimensions(path: Path) -> tuple[int, int] | None:
    """Fully decode a deterministic evidence PNG and return its dimensions."""

    try:
        from tools.light_review_evidence import validate_png

        width, height = validate_png(path)
    except (OSError, ValueError, TypeError, zlib.error):
        return None
    return width, height


def _evidence_tile(
    view: dict, sheets: dict, cache: dict[str, tuple[int, int, bytes]]
) -> bytes:
    """Return one decoded 204-by-153 evidence tile without its white edges."""

    from tools.light_review_evidence import read_png

    sheet_id = view["sheet"]
    if sheet_id not in cache:
        cache[sheet_id] = read_png(ROOT / sheets[sheet_id]["artifact"])
    width, height, pixels = cache[sheet_id]
    if (width, height) != (LIGHT_EVIDENCE_WIDTH, LIGHT_EVIDENCE_HEIGHT):
        raise ValueError("invalid evidence sheet geometry")
    tile = view["tile"]
    tile_x = (tile % LIGHT_EVIDENCE_COLUMNS) * LIGHT_EVIDENCE_TILE_WIDTH
    tile_y = (tile // LIGHT_EVIDENCE_COLUMNS) * LIGHT_EVIDENCE_TILE_HEIGHT
    output = bytearray()
    for y in range(1, LIGHT_EVIDENCE_TILE_HEIGHT):
        start = (
            (tile_y + y) * LIGHT_EVIDENCE_WIDTH + tile_x + 1
        ) * 3
        end = start + (LIGHT_EVIDENCE_TILE_WIDTH - 1) * 3
        output.extend(pixels[start:end])
    return bytes(output)


def _has_visible_light_pool(
    active: bytes,
    control: bytes,
    width: int | None = None,
    height: int | None = None,
    sprite_extent: tuple[int, int] | None = None,
) -> bool:
    """Return whether a captured state materially changes its map viewport."""

    viewport_width = None
    if (
        width is not None
        and height is not None
        and len(active) == len(control) == width * height * 3
    ):
        left = width // 4
        right = width * 3 // 4
        top = height // 6
        bottom = height * 2 // 3
        viewport_width = right - left
        row_bytes = width * 3
        active = b"".join(
            active[y * row_bytes + left * 3:y * row_bytes + right * 3]
            for y in range(top, bottom)
        )
        control = b"".join(
            control[y * row_bytes + left * 3:y * row_bytes + right * 3]
            for y in range(top, bottom)
        )

    differences = [
        abs(active_channel - control_channel)
        for active_channel, control_channel in zip(active, control)
    ]
    # The committed contact-sheet tile has about one twenty-fifth of the raw
    # capture's pixels.  Keep a substantial absolute floor so changed sprites
    # cannot pass, while allowing genuine radius-one pools that survive the
    # deterministic nearest-neighbor sampling.
    sampled_tile = (
        width == LIGHT_EVIDENCE_TILE_WIDTH - 1
        and height == LIGHT_EVIDENCE_TILE_HEIGHT - 1
    )
    minimum_channels = 150 if sampled_tile else 300
    minimum_total = 2500 if sampled_tile else 3000
    changed_pixels = [
        index
        for index in range(len(differences) // 3)
        if max(differences[index * 3:index * 3 + 3]) >= 3
    ]
    spatially_spread = True
    if viewport_width is not None and changed_pixels:
        changed_x = [index % viewport_width for index in changed_pixels]
        changed_y = [index // viewport_width for index in changed_pixels]
        spread_width = max(changed_x) - min(changed_x) + 1
        spread_height = max(changed_y) - min(changed_y) + 1
        # Changed object art is not evidence of emitted light.  Require the
        # changed area to extend beyond the source's largest authored face in
        # both axes so surrounding illuminated map pixels are part of the proof.
        raw_sprite_width, raw_sprite_height = sprite_extent or (32, 32)
        if sampled_tile:
            sprite_width = (
                raw_sprite_width * LIGHT_EVIDENCE_TILE_WIDTH + 1023
            ) // 1024
            sprite_height = (
                raw_sprite_height * LIGHT_EVIDENCE_TILE_HEIGHT + 767
            ) // 768
        else:
            sprite_width = raw_sprite_width
            sprite_height = raw_sprite_height
        spatially_spread = (
            spread_width > sprite_width and spread_height > sprite_height
        )
    return (
        len(active) == len(control)
        and sum(value >= 3 for value in differences) >= minimum_channels
        and sum(differences) >= minimum_total
        and spatially_spread
    )


def _rendered_art_extent(row: dict) -> tuple[int, int]:
    """Return the largest raw PNG canvas used by a source's rendered art."""

    if not row.get("visible"):
        return 0, 0
    root_key = str(ARCH_ROOT.resolve())
    cached = _ART_INDEX_CACHE.get(root_key)
    if cached is None:
        faces = defaultdict(list)
        for path in ARCH_ROOT.rglob("*.png"):
            faces[path.stem].append(path)
        animations = defaultdict(list)
        for path in ARCH_ROOT.rglob("*.anim"):
            current = None
            for raw_line in path.read_text(errors="replace").splitlines():
                line = raw_line.strip()
                if line.startswith("anim "):
                    current = line.split(None, 1)[1]
                elif line == "mina":
                    current = None
                elif current and line and not line.startswith(("#", "facings ")):
                    animations[current].append(line.split()[0])
        cached = (faces, animations)
        _ART_INDEX_CACHE[root_key] = cached
    faces, animations = cached
    names = []
    if row.get("face"):
        names.append(row["face"])
    animation = row.get("animation")
    if animation:
        if animation not in animations:
            raise ValueError("rendered animation is unresolved: {}".format(animation))
        names.extend(animations[animation])
    if row.get("visible") and not names:
        raise ValueError("visible rendered source has no face or animation")
    width = height = 0
    for name in names:
        paths = faces.get(name, ())
        if not paths:
            raise ValueError("rendered face is unresolved: {}".format(name))
        for path in paths:
            try:
                face_width, face_height = _validated_art_png_dimensions(path)
            except (OSError, ValueError, TypeError, zlib.error) as error:
                raise ValueError(
                    "rendered face has an invalid PNG: {} ({})".format(
                        name, error
                    )
                ) from error
            width = max(width, face_width)
            height = max(height, face_height)
    return width, height


def _validated_art_png_dimensions(path: Path) -> tuple[int, int]:
    """Fully validate a non-interlaced authored PNG and return its dimensions."""

    cache_key = str(path.resolve())
    if cache_key in _ART_DIMENSION_CACHE:
        return _ART_DIMENSION_CACHE[cache_key]
    from tools.light_review_evidence import _png_chunks

    width = height = depth = color_type = None
    compressed = bytearray()
    palette_seen = False
    idat_seen = False
    idat_closed = False
    for chunk_index, (name, payload) in enumerate(_png_chunks(path.read_bytes())):
        if chunk_index == 0 and name != b"IHDR":
            raise ValueError("PNG IHDR is not first")
        if name == b"IHDR":
            if chunk_index != 0 or width is not None or len(payload) != 13:
                raise ValueError("PNG has an invalid IHDR")
            width = int.from_bytes(payload[0:4], "big")
            height = int.from_bytes(payload[4:8], "big")
            depth, color_type, compression, filtering, interlace = payload[8:13]
            legal_depths = {
                2: {8, 16},
                3: {1, 2, 4, 8},
                4: {8, 16},
                6: {8, 16},
            }
            if (
                width < 1
                or height < 1
                or color_type not in legal_depths
                or depth not in legal_depths.get(color_type, ())
                or (compression, filtering, interlace) != (0, 0, 0)
            ):
                raise ValueError("unsupported authored PNG encoding")
        elif name == b"PLTE":
            if (
                width is None
                or palette_seen
                or idat_seen
                or color_type in {4, 6}
                or not payload
                or len(payload) % 3
                or len(payload) > 256 * 3
                or (color_type == 3 and len(payload) // 3 > 2 ** depth)
            ):
                raise ValueError("PNG has an invalid palette")
            palette_seen = True
        elif name == b"IDAT":
            if width is None or idat_closed:
                raise ValueError("PNG has invalid IDAT ordering")
            idat_seen = True
            compressed.extend(payload)
        elif name == b"IEND":
            if payload or not idat_seen:
                raise ValueError("PNG has an invalid IEND")
        else:
            if name and not (name[0] & 0x20):
                raise ValueError("PNG has an unknown critical chunk")
            if idat_seen:
                idat_closed = True
    if width is None or height is None:
        raise ValueError("PNG has no IHDR")
    if color_type == 3 and not palette_seen:
        raise ValueError("indexed PNG has no palette")
    if not idat_seen or not compressed:
        raise ValueError("PNG has no IDAT")
    channels = {2: 3, 3: 1, 4: 2, 6: 4}[color_type]
    stride = (width * channels * depth + 7) // 8
    expected = (stride + 1) * height
    decoder = zlib.decompressobj()
    raw = decoder.decompress(bytes(compressed), expected + 1)
    raw += decoder.flush(max(0, expected + 1 - len(raw)))
    if not decoder.eof or decoder.unused_data or len(raw) != expected:
        raise ValueError("PNG scanline size mismatch")
    if any(raw[offset] > 4 for offset in range(0, expected, stride + 1)):
        raise ValueError("unsupported PNG scanline filter")
    dimensions = (width, height)
    _ART_DIMENSION_CACHE[cache_key] = dimensions
    return dimensions


def _source_rendered_art_extent(
    report: dict, source_kind: str, row: dict
) -> tuple[int, int]:
    """Return art bounds for the speed-zero object used by the source plan."""

    art_row = row
    if source_kind == "archetype":
        relative = row.get("path")
        object_line = row.get("object_line")
        if isinstance(relative, str) and isinstance(object_line, int):
            path = ROOT / relative
            if path.is_file():
                lines = path.read_text().splitlines()
                cursor = object_line - 1
                runtime_id = row["id"]
                while 0 <= cursor < len(lines):
                    previous = cursor - 1
                    while previous >= 0 and not lines[previous].strip():
                        previous -= 1
                    if previous < 0 or lines[previous].strip() != "More":
                        break
                    previous_object = previous - 1
                    while (
                        previous_object >= 0
                        and not lines[previous_object].startswith("Object ")
                    ):
                        previous_object -= 1
                    if previous_object < 0:
                        break
                    runtime_id = lines[previous_object].removeprefix("Object ").strip()
                    cursor = previous_object
                inventoried = next(
                    (
                        candidate
                        for candidate in report["archetypes"]
                        if candidate["id"] == runtime_id
                    ),
                    None,
                )
                if inventoried is not None:
                    art_row = inventoried
                elif runtime_id != row["id"]:
                    relative = path.relative_to(ROOT).as_posix()
                    document = parse_bytes(
                        path.read_bytes(), path=relative, format_name="archetype"
                    )
                    head = next(
                        (
                            node
                            for node in document.nodes
                            if node.depth == 0 and node.name == runtime_id
                        ),
                        None,
                    )
                    if head is None:
                        raise ValueError(
                            "multipart runtime head is unresolved: {}".format(
                                runtime_id
                            )
                        )
                    attrs, _ = _legacy_archetype_attrs(document, head)
                    effective = {
                        key: values[-1]
                        for key, values in attrs.items()
                        if values
                    }
                    art_row = {
                        "face": effective.get("face"),
                        "animation": effective.get("animation"),
                        "visible": bool(
                            effective.get("face") or effective.get("animation")
                        ),
                    }
    # Continuous source commands freeze animation at speed zero, so the
    # effective initial face—not a later and potentially larger frame—is the
    # complete rendered sprite footprint for this comparison.
    art_row = dict(art_row)
    art_row["animation"] = None
    return _rendered_art_extent(art_row)


def _toggle_render_semantics(row: dict) -> tuple:
    """Return the fields that can change a toggle state's rendered pixels."""

    return tuple(
        row.get(field)
        for field in ("radius", "color", "face", "animation", "visible")
    )


def validate_light_evidence(report: dict) -> list[str]:
    """Validate durable Classic client renders and invisible-emitter coverage."""

    errors = []
    evidence = _light_evidence()
    if evidence.get("schema_version") != 2:
        errors.append("light-source evidence must use schema_version 2")
    context = evidence.get("render_context")
    if not isinstance(context, dict):
        errors.append("light-source evidence render_context must be an object")
        context = {}
    for field in (
        "content_commit",
        "classic_client_commit",
        "classic_server_commit",
        "resources_commit",
    ):
        value = context.get(field)
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}", value) is None:
            errors.append("light-source evidence needs a {} SHA".format(field))
    for field in ("profile", "command", "settings", "ordinary_state"):
        value = context.get(field)
        if not isinstance(value, str) or len(value.strip()) < 12:
            errors.append("light-source evidence needs {}".format(field))
    for field, repository, commit_field in (
        ("content_source", "content", "content_commit"),
        ("classic_client_source", "classic", "classic_client_commit"),
        ("classic_server_source", "classic", "classic_server_commit"),
        ("resources_source", "resources", "resources_commit"),
    ):
        expected_url = "https://github.com/atrinik/{}/tree/{}".format(
            repository, context.get(commit_field)
        )
        if context.get(field) != expected_url:
            errors.append("light-source evidence needs immutable {}".format(field))
    if context.get("inventory_sha256") != _inventory_semantic_sha256(report):
        errors.append("light-source evidence inventory changed since rendered review")
    runtime_digest = context.get("runtime_content_sha256")
    if runtime_digest != _runtime_content_sha256():
        errors.append("light-source evidence runtime content changed since rendered review")
    content_commit = context.get("content_commit")
    if isinstance(content_commit, str) and re.fullmatch(
        r"[0-9a-f]{40}", content_commit
    ) is not None:
        try:
            commit_digest = _git_runtime_content_sha256(content_commit)
        except ValueError as error:
            errors.append("light-source evidence {}".format(error))
        else:
            if runtime_digest != commit_digest:
                errors.append(
                    "light-source evidence content commit runtime tree disagrees "
                    "with rendered review"
                )

    sheets = evidence.get("sheets")
    if not isinstance(sheets, dict):
        errors.append("light-source evidence sheets must be an object")
        sheets = {}
    capacities = {}
    for identifier, entry in sorted(sheets.items()):
        if not isinstance(entry, dict):
            errors.append("light-source evidence sheet {} must be an object".format(identifier))
            continue
        artifact = entry.get("artifact")
        if not isinstance(artifact, str):
            errors.append("light-source evidence sheet {} needs an artifact".format(identifier))
            continue
        path = ROOT / artifact
        expected_parent = (MAP_ROOT / "light-source-evidence").resolve()
        try:
            contained = path.resolve().parent == expected_parent
        except OSError:
            contained = False
        if not contained or path.suffix.lower() != ".png":
            errors.append(
                "light-source evidence sheet {} has an invalid artifact path".format(
                    identifier
                )
            )
        elif not path.is_file():
            errors.append("light-source evidence sheet {} artifact is missing".format(identifier))
        else:
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if entry.get("sha256") != actual:
                errors.append(
                    "light-source evidence sheet {} artifact hash changed".format(
                        identifier
                    )
                )
            dimensions = _image_dimensions(path)
            if dimensions is None:
                errors.append(
                    "light-source evidence sheet {} is not a valid image".format(
                        identifier
                    )
                )
            elif dimensions != (entry.get("pixel_width"), entry.get("pixel_height")):
                errors.append(
                    "light-source evidence sheet {} dimensions changed".format(
                        identifier
                    )
                )
        columns = entry.get("columns")
        rows = entry.get("rows")
        if columns != LIGHT_EVIDENCE_COLUMNS or rows != LIGHT_EVIDENCE_ROWS:
            errors.append(
                "light-source evidence sheet {} must use {} by {} tiles".format(
                    identifier, LIGHT_EVIDENCE_COLUMNS, LIGHT_EVIDENCE_ROWS
                )
            )
        else:
            capacities[identifier] = columns * rows
        if (
            entry.get("pixel_width") != LIGHT_EVIDENCE_WIDTH
            or entry.get("pixel_height") != LIGHT_EVIDENCE_HEIGHT
        ):
            errors.append(
                "light-source evidence sheet {} must declare {} by {} pixels".format(
                    identifier, LIGHT_EVIDENCE_WIDTH, LIGHT_EVIDENCE_HEIGHT
                )
            )
        if entry.get("mode") not in {"smooth", "discrete"}:
            errors.append("light-source evidence sheet {} needs a lighting mode".format(identifier))

    map_rows = {row["path"]: row for row in report["maps"]}
    views = evidence.get("views")
    if not isinstance(views, list):
        errors.append("light-source evidence views must be an array")
        views = []
    view_ids = {}
    occupied = set()
    referenced_sheets = set()
    smooth_by_map: dict[str, list[dict]] = defaultdict(list)
    expected_sources = {
        (source_kind, row["id"]): row
        for source_kind, section in (
            ("archetype", "archetypes"),
            ("artifact", "artifacts"),
        )
        for row in report[section]
    }
    for view in views:
        if not isinstance(view, dict):
            errors.append("light-source evidence view must be an object")
            continue
        identifier = view.get("id")
        if not isinstance(identifier, str) or not identifier:
            errors.append("light-source evidence view needs an id")
            continue
        if identifier in view_ids:
            errors.append("duplicate light-source evidence view: {}".format(identifier))
        view_ids[identifier] = view
        map_path = view.get("map")
        row = map_rows.get(map_path)
        source_fields = (
            "source_kind",
            "source_id",
            "source_semantic_sha256",
        )
        has_source_binding = any(view.get(field) is not None for field in source_fields)
        if row is None:
            scene = ROOT / str(map_path)
            contained = _is_light_review_scene(scene)
            lab_binding = (
                has_source_binding
                or view.get("active_state_id") is not None
                or view.get("review_control_id") is not None
            )
            if not contained or not scene.is_file() or not lab_binding:
                errors.append(
                    "light-source evidence view {} references a stale map".format(
                        identifier
                    )
                )
            elif view.get("map_source_sha256") != hashlib.sha256(
                scene.read_bytes()
            ).hexdigest():
                errors.append(
                    "light-source evidence view {} has stale review-scene source".format(
                        identifier
                    )
                )
        elif view.get("map_semantic_sha256") != row["semantic_sha256"]:
            errors.append(
                "light-source evidence view {} has stale map semantics".format(identifier)
            )
        if (
            not isinstance(view.get("x"), int) or isinstance(view.get("x"), bool)
            or not isinstance(view.get("y"), int) or isinstance(view.get("y"), bool)
        ):
            errors.append(
                "light-source evidence view {} needs integer coordinates".format(
                    identifier
                )
            )
        sheet = view.get("sheet")
        tile = view.get("tile")
        if sheet not in sheets:
            errors.append(
                "light-source evidence view {} references an unknown sheet".format(
                    identifier
                )
            )
        elif (
            not isinstance(tile, int) or isinstance(tile, bool)
            or tile < 0 or tile >= capacities.get(sheet, 0)
        ):
            errors.append(
                "light-source evidence view {} has an invalid sheet tile".format(
                    identifier
                )
            )
        elif (sheet, tile) in occupied:
            errors.append("duplicate light-source evidence sheet tile: {} {}".format(sheet, tile))
        else:
            occupied.add((sheet, tile))
            referenced_sheets.add(sheet)
        mode = view.get("mode")
        if sheet in sheets and mode != sheets[sheet].get("mode"):
            errors.append(
                "light-source evidence view {} mode disagrees with its sheet".format(
                    identifier
                )
            )
        if mode == "smooth" and row is not None:
            smooth_by_map[map_path].append(view)
        if re.fullmatch(r"[0-9a-f]{64}", str(view.get("capture_sha256"))) is None:
            errors.append(
                "light-source evidence view {} needs a capture digest".format(identifier)
            )
        if view.get("content_commit") != context.get("content_commit"):
            errors.append(
                "light-source evidence view {} has a stale content commit".format(
                    identifier
                )
            )
        if has_source_binding:
            source_key = (view.get("source_kind"), view.get("source_id"))
            source = expected_sources.get(source_key)
            if source is None:
                errors.append(
                    "light-source evidence view {} references a stale source".format(
                        identifier
                    )
                )
            elif view.get("source_semantic_sha256") != source["semantic_sha256"]:
                errors.append(
                    "light-source evidence view {} has stale source semantics".format(
                        identifier
                    )
                )
            if mode != "smooth":
                errors.append(
                    "light-source evidence view {} binds a source outside smooth mode".format(
                        identifier
                    )
                )
            command = view.get("runtime_command")
            if not isinstance(command, str) or len(command.strip()) < 12:
                errors.append(
                    "light-source evidence view {} needs a source runtime command".format(
                        identifier
                    )
                )
    for identifier in sorted(set(sheets) - referenced_sheets):
        errors.append("stale light-source evidence sheet: {}".format(identifier))
    expected_artifacts = {
        (ROOT / entry["artifact"]).resolve()
        for entry in sheets.values()
        if isinstance(entry, dict) and isinstance(entry.get("artifact"), str)
    }
    evidence_root = MAP_ROOT / "light-source-evidence"
    if evidence_root.is_dir():
        actual_artifacts = {
            path.resolve()
            for path in evidence_root.iterdir()
            if path.is_file() and path.name != "manifest.json"
        }
        for path in sorted(actual_artifacts - expected_artifacts):
            errors.append(
                "unlisted light-source evidence artifact: {}".format(path.name)
            )

    try:
        from tools.light_review_evidence import source_plan_errors

        errors.extend(source_plan_errors(report, views))
    except (OSError, ValueError, TypeError) as error:
        errors.append("light-source evidence source plan cannot be checked: {}".format(error))

    for map_path, row in sorted(map_rows.items()):
        map_views = smooth_by_map.get(map_path, [])
        invisible = [emitter for emitter in row["emitters"] if not emitter["visible"]]
        targets = invisible or row["emitters"][:1]
        for emitter in targets:
            if not any(
                abs(emitter["x"] - view.get("x", 10**9)) <= 8
                and abs(emitter["y"] - view.get("y", 10**9)) <= 8
                for view in map_views
            ):
                errors.append(
                    "map {} emitter {} at {},{} lacks smooth runtime evidence".format(
                        map_path,
                        emitter["archetype"],
                        emitter["x"],
                        emitter["y"],
                    )
                )

    required_checks = {
        "overlap", "linked-depth", "horizontal-boundary", "dark-interior",
        "outdoor-transition", "fog-roof", "navigation",
    }
    representative = evidence.get("representative_checks")
    if not isinstance(representative, dict):
        errors.append("light-source evidence representative_checks must be an object")
        representative = {}
    for check in sorted(set(representative) - required_checks):
        errors.append("stale light-source evidence representative check: {}".format(check))
    for check in sorted(required_checks):
        entry = representative.get(check)
        if not isinstance(entry, dict):
            errors.append("light-source evidence needs representative {} review".format(check))
            continue
        identifiers = entry.get("views")
        if not isinstance(identifiers, list) or not identifiers:
            errors.append("light-source evidence needs representative {} views".format(check))
            continue
        if not isinstance(entry.get("rationale"), str) or len(entry["rationale"].strip()) < 12:
            errors.append("light-source evidence {} needs a concise rationale".format(check))
        modes = {
            view_ids[identifier].get("mode")
            for identifier in identifiers
            if identifier in view_ids
        }
        if any(identifier not in view_ids for identifier in identifiers):
            errors.append("light-source evidence {} references an unknown view".format(check))
        if modes != {"smooth", "discrete"}:
            errors.append(
                "light-source evidence {} must cover smooth and discrete modes".format(
                    check
                )
            )
    active_states = evidence.get("active_states")
    if not isinstance(active_states, dict):
        errors.append("light-source evidence active_states must be an object")
        active_states = {}
    expected_states = {row["id"]: row for row in report["toggle_states"]}
    active_capture_ids = {}
    tile_cache = {}
    for stale in sorted(set(active_states) - set(expected_states)):
        errors.append("stale active-state lighting evidence: {}".format(stale))
    for identifier, row in sorted(expected_states.items()):
        entry = active_states.get(identifier)
        if not isinstance(entry, dict):
            errors.append("toggle state {} lacks active runtime evidence".format(identifier))
            continue
        if entry.get("semantic_sha256") != row["semantic_sha256"]:
            errors.append("toggle state {} active evidence is stale".format(identifier))
        identifiers = entry.get("views")
        if not isinstance(identifiers, list) or not identifiers:
            errors.append("toggle state {} needs active runtime views".format(identifier))
            continue
        for view_id in identifiers:
            view = view_ids.get(view_id)
            if (
                not isinstance(view, dict)
                or view.get("mode") != "smooth"
                or view.get("active_state_id") != identifier
                or not isinstance(view.get("runtime_command"), str)
                or len(view["runtime_command"].strip()) < 12
            ):
                errors.append(
                    "toggle state {} has invalid active runtime view {}".format(
                        identifier, view_id
                    )
                )
                continue
            capture_sha256 = view.get("capture_sha256")
            render_semantics = _toggle_render_semantics(row)
            previous_state, previous_semantics = active_capture_ids.setdefault(
                capture_sha256, (identifier, render_semantics)
            )
            if previous_semantics != render_semantics:
                errors.append(
                    "renderer-distinct toggle states {} and {} reuse one active "
                    "capture".format(
                        previous_state, identifier
                    )
                )
            control = view_ids.get(view.get("control_view"))
            if (
                not isinstance(control, dict)
                or control.get("mode") != "smooth"
                or control.get("active_state_id") is not None
                or control.get("review_control_id") != view.get("review_control_id")
                or control.get("map") != view.get("map")
                or control.get("x") != view.get("x")
                or control.get("y") != view.get("y")
                or control.get("capture_surface") != view.get("capture_surface")
            ):
                errors.append(
                    "toggle state {} view {} lacks a matched dark control".format(
                        identifier, view_id
                    )
                )
                continue
            try:
                active_pixels = _evidence_tile(view, sheets, tile_cache)
                control_pixels = _evidence_tile(control, sheets, tile_cache)
            except (KeyError, OSError, ValueError, TypeError, zlib.error):
                errors.append(
                    "toggle state {} view {} cannot be pixel-compared".format(
                        identifier, view_id
                    )
                )
                continue
            try:
                art_extent = _rendered_art_extent(row)
            except (OSError, ValueError) as error:
                errors.append(
                    "toggle state {} view {} has unresolved rendered art: {}".format(
                        identifier, view_id, error
                    )
                )
                continue
            if not _has_visible_light_pool(
                active_pixels,
                control_pixels,
                LIGHT_EVIDENCE_TILE_WIDTH - 1,
                LIGHT_EVIDENCE_TILE_HEIGHT - 1,
                art_extent,
            ):
                errors.append(
                    "toggle state {} view {} lacks a visible active light pool".format(
                        identifier, view_id
                    )
                )
        if not isinstance(entry.get("rationale"), str) or len(entry["rationale"].strip()) < 12:
            errors.append("toggle state {} needs an evidence rationale".format(identifier))
    source_states = evidence.get("source_states")
    if not isinstance(source_states, dict):
        errors.append("light-source evidence source_states must be an object")
        source_states = {}
    expected_state_ids = {
        "{}:{}".format(source_kind, source_id): (source_kind, source_id, row)
        for (source_kind, source_id), row in expected_sources.items()
    }
    for stale in sorted(set(source_states) - set(expected_state_ids)):
        errors.append("stale source-state lighting evidence: {}".format(stale))
    for identifier, (source_kind, source_id, row) in sorted(
        expected_state_ids.items()
    ):
        entry = source_states.get(identifier)
        if not isinstance(entry, dict):
            errors.append("light source {} lacks runtime evidence".format(identifier))
            continue
        if (
            entry.get("source_kind") != source_kind
            or entry.get("source_id") != source_id
            or entry.get("semantic_sha256") != row["semantic_sha256"]
        ):
            errors.append("light source {} runtime evidence is stale".format(identifier))
        identifiers = entry.get("views")
        if not isinstance(identifiers, list) or not identifiers:
            errors.append("light source {} needs smooth runtime views".format(identifier))
            continue
        for view_id in identifiers:
            view = view_ids.get(view_id)
            if (
                not isinstance(view, dict)
                or view.get("mode") != "smooth"
                or view.get("source_kind") != source_kind
                or view.get("source_id") != source_id
                or view.get("source_semantic_sha256") != row["semantic_sha256"]
                or not isinstance(view.get("runtime_command"), str)
                or len(view["runtime_command"].strip()) < 12
            ):
                errors.append(
                    "light source {} has invalid runtime view {}".format(
                        identifier, view_id
                    )
                )
                continue
            control = view_ids.get(view.get("control_view"))
            if (
                not isinstance(control, dict)
                or control.get("mode") != "smooth"
                or control.get("active_state_id") is not None
                or control.get("source_kind") is not None
                or control.get("review_control_id") != view.get("review_control_id")
                or control.get("map") != view.get("map")
                or control.get("x") != view.get("x")
                or control.get("y") != view.get("y")
                or control.get("capture_surface") != view.get("capture_surface")
            ):
                errors.append(
                    "light source {} view {} lacks a matched dark control".format(
                        identifier, view_id
                    )
                )
                continue
            try:
                source_pixels = _evidence_tile(view, sheets, tile_cache)
                control_pixels = _evidence_tile(control, sheets, tile_cache)
            except (KeyError, OSError, ValueError, TypeError, zlib.error):
                errors.append(
                    "light source {} view {} cannot be pixel-compared".format(
                        identifier, view_id
                    )
                )
                continue
            try:
                art_extent = _source_rendered_art_extent(
                    report, source_kind, row
                )
            except (OSError, ValueError) as error:
                errors.append(
                    "light source {} view {} has unresolved rendered art: {}".format(
                        identifier, view_id, error
                    )
                )
                continue
            if not _has_visible_light_pool(
                source_pixels,
                control_pixels,
                LIGHT_EVIDENCE_TILE_WIDTH - 1,
                LIGHT_EVIDENCE_TILE_HEIGHT - 1,
                art_extent,
            ):
                errors.append(
                    "light source {} view {} lacks a visible light pool".format(
                        identifier, view_id
                    )
                )
    return errors


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
    archetypes = load_archetypes()
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
            if radius is None:
                continue
            color = _effective_color(one(attrs, "light_color", base.get("light_color")))
            face = one(attrs, "face", base.get("face"))
            animation = one(attrs, "animation", base.get("animation"))
            visible = _visible_emitter(
                face,
                one(attrs, "type", base.get("type")),
                one(attrs, "sys_object", base.get("sys_object")),
            )
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
        "maps": [reviewed_maps[path] for path in sorted(reviewed_maps)],
    }


def validate_light_inventory(report: dict) -> list[str]:
    """Validate the checked review baseline against the current semantic inventory."""

    errors = []
    review = _light_review()
    if review.get("schema_version") != 4:
        errors.append("light-source review must use schema_version 4")
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
    errors.extend(validate_light_evidence(report))
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
        views = entry.get("views")
        if not isinstance(views, list) or not views:
            errors.append("contextual lighting check {} needs evidence views".format(check))
        evidence_entry = _light_evidence().get("representative_checks", {}).get(check)
        if not isinstance(evidence_entry, dict) or views != evidence_entry.get("views"):
            errors.append(
                "contextual lighting check {} disagrees with render evidence".format(
                    check
                )
            )
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
