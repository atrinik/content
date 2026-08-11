#!/usr/bin/env python3
"""Plan and build deterministic Classic client light-review evidence sheets."""

from __future__ import annotations

import argparse
import binascii
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import world_content_audit as audit


COLUMNS = audit.LIGHT_EVIDENCE_COLUMNS
ROWS = audit.LIGHT_EVIDENCE_ROWS
TILE_WIDTH = audit.LIGHT_EVIDENCE_TILE_WIDTH
TILE_HEIGHT = audit.LIGHT_EVIDENCE_TILE_HEIGHT
SHEET_CAPACITY = COLUMNS * ROWS
SOURCE_REVIEW_MAP = "tools/light-source-review/dark-lab"
SOURCE_REVIEW_RUNTIME_MAP = "/light-source-review/dark-lab"
SOURCE_REVIEW_X = 9
SOURCE_REVIEW_Y = 9
SOURCE_PLAN_FIELDS = (
    "map",
    "map_source_sha256",
    "x",
    "y",
    "review_control_id",
    "source_kind",
    "source_id",
    "source_semantic_sha256",
    "active_state_id",
    "capture_surface",
    "runtime_command",
)


def review_centers(emitters: list[dict]) -> list[tuple[int, int]]:
    """Return a deterministic 17x17 cover of invisible emitter coordinates."""

    points = sorted({(row["x"], row["y"]) for row in emitters if not row["visible"]})
    if not points:
        row = emitters[0]
        return [(row["x"], row["y"])]
    centers = []
    while points:
        center = max(
            points,
            key=lambda candidate: sum(
                abs(x - candidate[0]) <= 8 and abs(y - candidate[1]) <= 8
                for x, y in points
            ),
        )
        centers.append(center)
        points = [
            (x, y)
            for x, y in points
            if not (abs(x - center[0]) <= 8 and abs(y - center[1]) <= 8)
        ]
    return centers


def capture_plan(report: dict) -> list[dict]:
    """Build the stable map/coordinate capture plan for an inventory."""

    plan = []
    for map_row in report["maps"]:
        for index, (x, y) in enumerate(review_centers(map_row["emitters"]), 1):
            plan.append({
                "number": len(plan) + 1,
                "map": map_row["path"],
                "map_semantic_sha256": map_row["semantic_sha256"],
                "view": index,
                "x": x,
                "y": y,
            })
    return plan


def runtime_archetype_id(row: dict) -> str:
    """Return the spawnable head ID for an archetype or multipart part."""

    relative = row.get("path")
    object_line = row.get("object_line")
    if not isinstance(relative, str) or not isinstance(object_line, int):
        return row["id"]
    path = audit.ROOT / relative
    if not path.is_file():
        return row["id"]
    lines = path.read_text().splitlines()
    cursor = object_line - 1
    if cursor < 0 or cursor >= len(lines):
        return row["id"]
    runtime_id = row["id"]
    while cursor > 0:
        previous = cursor - 1
        while previous >= 0 and not lines[previous].strip():
            previous -= 1
        if previous < 0 or lines[previous].strip() != "More":
            break
        previous_object = previous - 1
        while previous_object >= 0 and not lines[previous_object].startswith("Object "):
            previous_object -= 1
        if previous_object < 0:
            break
        runtime_id = lines[previous_object].removeprefix("Object ").strip()
        cursor = previous_object
    return runtime_id


def _console(command: str) -> str:
    """Return one copy-pasteable Classic Python-console command."""

    # Classic consumes one leading quote to preserve whitespace through the
    # command protocol. A closing quote would become part of the Python input.
    return '/console "{}'.format(command)


def _continuous_source_command(source_kind: str, row: dict) -> str:
    """Return the exact dark-lab placement command for a continuous source."""

    if source_kind == "artifact" and row.get("runtime_archetype") != row["id"]:
        command = (
            "noinf::obj=activator.map.CreateObject({!r},activator.x+1,activator.y); "
            "obj.Remove(); obj.Artificate({!r}); obj.speed=0; "
            "obj=activator.map.Insert(obj,activator.x+1,activator.y); obj.Update()"
        ).format(row["archetype"], row["id"])
    else:
        runtime_id = (
            row["runtime_archetype"]
            if source_kind == "artifact"
            else runtime_archetype_id(row)
        )
        command = (
            "noinf::obj=activator.map.CreateObject({!r},activator.x+1,activator.y); "
            "obj.speed=0; obj.Update()"
        ).format(runtime_id)
    return _console(command)


def _active_source_command(create_command: str) -> str:
    """Return the exact ordered command transcript for a toggle source."""

    apply_command = _console(
        "noinf::obj=activator.FindObject(name='issue65_capture'); "
        "activator.Apply(obj)"
    )
    return "{} name issue65_capture; {}".format(create_command, apply_command)


def source_capture_plan(
    report: dict, map_path: str, map_source_sha256: str, x: int, y: int
) -> list[dict]:
    """Build a deterministic dark-lab plan for every source definition."""

    state_by_source = {
        (source["kind"], source["id"]): state["id"]
        for state in report["toggle_states"]
        for source in state["sources"]
        if source["kind"] in {"archetype", "artifact"}
    }
    if map_path != SOURCE_REVIEW_MAP:
        raise ValueError(
            "source review map must be {}".format(SOURCE_REVIEW_MAP)
        )
    if (x, y) != (SOURCE_REVIEW_X, SOURCE_REVIEW_Y):
        raise ValueError(
            "source review coordinates must be {},{}".format(
                SOURCE_REVIEW_X, SOURCE_REVIEW_Y
            )
        )
    toggle_control_id = "toggle-full-control"
    map_control_id = "source-map-control"
    plan = [{
        "number": 1,
        "map": map_path,
        "map_source_sha256": map_source_sha256,
        "x": x,
        "y": y,
        "review_control_id": toggle_control_id,
        "capture_surface": "window",
        "runtime_command": (
            "/tpto {} {} {}; verify no carried emitted light; capture full window"
        ).format(SOURCE_REVIEW_RUNTIME_MAP, x, y),
    }]
    for source_kind, section in (
        ("archetype", "archetypes"),
        ("artifact", "artifacts"),
    ):
        for row in report[section]:
            state_id = state_by_source.get((source_kind, row["id"]))
            if source_kind == "artifact":
                if row.get("runtime_archetype") == row["id"]:
                    create_command = "/create {}".format(row["id"])
                else:
                    create_command = "/create {} of {}".format(
                        row["archetype"], row["id"]
                    )
            else:
                create_command = "/create {}".format(runtime_archetype_id(row))
            command = (
                _active_source_command(create_command)
                if state_id
                else _continuous_source_command(source_kind, row)
            )
            capture_surface = "window" if state_id else "map"
            plan.append({
                "number": len(plan) + 1,
                "map": map_path,
                "map_source_sha256": map_source_sha256,
                "x": x,
                "y": y,
                "source_kind": source_kind,
                "source_id": row["id"],
                "source_semantic_sha256": row["semantic_sha256"],
                "runtime_command": command,
                "review_control_id": (
                    toggle_control_id if state_id else map_control_id
                ),
                "capture_surface": capture_surface,
                **(
                    {
                        "active_state_id": state_id,
                    }
                    if state_id else {}
                ),
            })
    covered_states = {
        row["active_state_id"] for row in plan if row.get("active_state_id")
    }
    map_emitters = {
        emitter["id"]: emitter
        for map_row in report["maps"]
        for emitter in map_row["emitters"]
    }
    for state in report["toggle_states"]:
        if state["id"] in covered_states:
            continue
        source = next(
            (source for source in state["sources"] if source["kind"] == "map"),
            None,
        )
        if source is None or source["id"] not in map_emitters:
            raise ValueError("toggle state has no reproducible source")
        emitter = map_emitters[source["id"]]
        create_command = "/create {} last_sp {}".format(
            emitter["activation_archetype"], state["radius"]
        )
        if state["color"] is not None:
            create_command += " light_color {}".format(state["color"])
        if emitter.get("face"):
            create_command += " face {}".format(emitter["face"])
        if emitter.get("animation"):
            create_command += " animation {}".format(emitter["animation"])
        plan.append({
            "number": len(plan) + 1,
            "map": map_path,
            "map_source_sha256": map_source_sha256,
            "x": x,
            "y": y,
            "active_state_id": state["id"],
            "review_control_id": toggle_control_id,
            "capture_surface": "window",
            "runtime_command": _active_source_command(create_command),
        })
    plan.append({
        "number": len(plan) + 1,
        "map": map_path,
        "map_source_sha256": map_source_sha256,
        "x": x,
        "y": y,
        "review_control_id": map_control_id,
        "capture_surface": "map",
        "runtime_command": (
            "/tpto {} {} {}; verify no carried emitted light; /screenshot map"
        ).format(SOURCE_REVIEW_RUNTIME_MAP, x, y),
    })
    return plan


def source_plan_errors(report: dict, rows: list[dict]) -> list[str]:
    """Return capture/manifest drift from the authoritative source plan."""

    scene = audit.ROOT / SOURCE_REVIEW_MAP
    if not scene.is_file():
        return ["source review map is missing: {}".format(SOURCE_REVIEW_MAP)]
    expected_rows = source_capture_plan(
        report,
        SOURCE_REVIEW_MAP,
        hashlib.sha256(scene.read_bytes()).hexdigest(),
        SOURCE_REVIEW_X,
        SOURCE_REVIEW_Y,
    )

    def key(row: dict):
        if row.get("source_kind") is not None or row.get("source_id") is not None:
            return ("source", row.get("source_kind"), row.get("source_id"))
        if row.get("active_state_id") is not None:
            return ("active", row.get("active_state_id"))
        if row.get("review_control_id") is not None:
            return ("control", row.get("review_control_id"))
        return None

    expected = {key(row): row for row in expected_rows}
    actual: dict[tuple, dict] = {}
    errors = []
    for row in rows:
        identifier = key(row)
        if identifier is None:
            continue
        if identifier in actual:
            errors.append("duplicate source-plan row: {}".format(identifier))
            continue
        actual[identifier] = row
    for identifier in sorted(set(expected) - set(actual), key=str):
        errors.append("missing source-plan row: {}".format(identifier))
    for identifier in sorted(set(actual) - set(expected), key=str):
        errors.append("stale source-plan row: {}".format(identifier))
    for identifier in sorted(set(expected) & set(actual), key=str):
        wanted = expected[identifier]
        found = actual[identifier]
        for field in SOURCE_PLAN_FIELDS:
            if found.get(field) != wanted.get(field):
                errors.append(
                    "source-plan row {} has stale {}".format(identifier, field)
                )
    return errors


def _png_chunks(data: bytes):
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("capture is not a PNG")
    offset = 8
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        name = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        crc = data[offset + 8 + length:offset + 12 + length]
        if len(payload) != length or len(crc) != 4:
            raise ValueError("truncated PNG chunk")
        expected = binascii.crc32(name + payload) & 0xffffffff
        if struct.unpack(">I", crc)[0] != expected:
            raise ValueError("PNG chunk checksum mismatch")
        yield name, payload
        offset += 12 + length
        if name == b"IEND":
            if offset != len(data):
                raise ValueError("trailing PNG data")
            return
    raise ValueError("PNG has no terminal IEND chunk")


def read_png(path: Path) -> tuple[int, int, bytes]:
    """Decode a non-interlaced eight-bit RGB/RGBA Classic screenshot."""

    width = height = color_type = None
    compressed = bytearray()
    for name, payload in _png_chunks(path.read_bytes()):
        if name == b"IHDR":
            width, height, depth, color_type, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", payload
            )
            unsupported = (compression, filtering, interlace) != (0, 0, 0)
            if depth != 8 or color_type not in {2, 6} or unsupported:
                raise ValueError("unsupported Classic screenshot PNG encoding")
        elif name == b"IDAT":
            compressed.extend(payload)
    if width is None or height is None:
        raise ValueError("PNG has no IHDR")
    channels = 3 if color_type == 2 else 4
    stride = width * channels
    raw = zlib.decompress(bytes(compressed))
    if len(raw) != (stride + 1) * height:
        raise ValueError("PNG scanline size mismatch")
    previous = bytearray(stride)
    rgb = bytearray(width * height * 3)
    for y in range(height):
        start = y * (stride + 1)
        filter_type = raw[start]
        scanline = bytearray(raw[start + 1:start + stride + 1])
        for x in range(stride):
            left = scanline[x - channels] if x >= channels else 0
            above = previous[x]
            upper_left = previous[x - channels] if x >= channels else 0
            if filter_type == 1:
                scanline[x] = (scanline[x] + left) & 0xff
            elif filter_type == 2:
                scanline[x] = (scanline[x] + above) & 0xff
            elif filter_type == 3:
                scanline[x] = (scanline[x] + ((left + above) // 2)) & 0xff
            elif filter_type == 4:
                estimate = left + above - upper_left
                distances = (
                    abs(estimate - left),
                    abs(estimate - above),
                    abs(estimate - upper_left),
                )
                predictor = (left, above, upper_left)[distances.index(min(distances))]
                scanline[x] = (scanline[x] + predictor) & 0xff
            elif filter_type != 0:
                raise ValueError("unsupported PNG scanline filter")
        for x in range(width):
            source = x * channels
            target = (y * width + x) * 3
            if channels == 4:
                alpha = scanline[source + 3]
                rgb[target:target + 3] = bytes(
                    (scanline[source + component] * alpha + 127) // 255
                    for component in range(3)
                )
            else:
                rgb[target:target + 3] = scanline[source:source + 3]
        previous = scanline
    return width, height, bytes(rgb)


def validate_png(path: Path) -> tuple[int, int]:
    """Validate a screenshot PNG without materializing its decoded pixels."""

    width = height = color_type = None
    compressed = bytearray()
    idat_seen = False
    for name, payload in _png_chunks(path.read_bytes()):
        if name == b"IHDR":
            if width is not None or len(payload) != 13:
                raise ValueError("PNG has an invalid IHDR")
            width, height, depth, color_type, compression, filtering, interlace = (
                struct.unpack(">IIBBBBB", payload)
            )
            unsupported = (compression, filtering, interlace) != (0, 0, 0)
            if (
                width < 1
                or height < 1
                or depth != 8
                or color_type not in {2, 6}
                or unsupported
            ):
                raise ValueError("unsupported Classic screenshot PNG encoding")
        elif name == b"IDAT":
            idat_seen = True
            compressed.extend(payload)
    if width is None or height is None:
        raise ValueError("PNG has no IHDR")
    if not idat_seen:
        raise ValueError("PNG has no IDAT")
    channels = 3 if color_type == 2 else 4
    stride = width * channels
    expected = (stride + 1) * height
    decoder = zlib.decompressobj()
    raw = decoder.decompress(bytes(compressed), expected + 1)
    if len(raw) > expected:
        raise ValueError("PNG scanline size mismatch")
    raw += decoder.flush(expected + 1 - len(raw))
    if not decoder.eof or decoder.unused_data or len(raw) != expected:
        raise ValueError("PNG scanline size mismatch")
    for offset in range(0, expected, stride + 1):
        if raw[offset] > 4:
            raise ValueError("unsupported PNG scanline filter")
    return width, height


def _chunk(name: bytes, payload: bytes) -> bytes:
    checksum = binascii.crc32(name + payload) & 0xffffffff
    return struct.pack(">I", len(payload)) + name + payload + struct.pack(">I", checksum)


def write_png(path: Path, width: int, height: int, pixels: bytes) -> None:
    """Write deterministic RGB PNG bytes with filter zero and zlib level nine."""

    stride = width * 3
    raw = b"".join(
        b"\x00" + pixels[y * stride:(y + 1) * stride]
        for y in range(height)
    )
    data = b"\x89PNG\r\n\x1a\n"
    data += _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    data += _chunk(b"IDAT", zlib.compress(raw, 9))
    data += _chunk(b"IEND", b"")
    path.write_bytes(data)


def _place_tile(canvas: bytearray, source: tuple[int, int, bytes], tile: int) -> None:
    width, height, pixels = source
    tile_x = (tile % COLUMNS) * TILE_WIDTH
    tile_y = (tile // COLUMNS) * TILE_HEIGHT
    sheet_width = COLUMNS * TILE_WIDTH
    for y in range(TILE_HEIGHT):
        source_y = y * height // TILE_HEIGHT
        for x in range(TILE_WIDTH):
            target = ((tile_y + y) * sheet_width + tile_x + x) * 3
            if x == 0 or y == 0:
                canvas[target:target + 3] = b"\xff\xff\xff"
                continue
            source_x = x * width // TILE_WIDTH
            origin = (source_y * width + source_x) * 3
            canvas[target:target + 3] = pixels[origin:origin + 3]


def _load_captures(path: Path, mode: str) -> list[dict]:
    rows = json.loads(path.read_text())
    for row in rows:
        artifact = path.parent / row["artifact"]
        if not artifact.is_file():
            raise ValueError("missing {} capture: {}".format(mode, artifact))
        row["_path"] = artifact
        row["_mode"] = mode
    return rows


def _render_sheet(job: tuple[str, list[str]]) -> tuple[str, str]:
    """Render one sheet and return its artifact digest."""

    artifact_name, captures = job
    canvas = bytearray(COLUMNS * TILE_WIDTH * ROWS * TILE_HEIGHT * 3)
    for tile, capture in enumerate(captures):
        _place_tile(canvas, read_png(Path(capture)), tile)
    artifact = Path(artifact_name)
    write_png(artifact, COLUMNS * TILE_WIDTH, ROWS * TILE_HEIGHT, bytes(canvas))
    return artifact_name, hashlib.sha256(artifact.read_bytes()).hexdigest()


def build_evidence(args) -> dict:
    expected_output = (audit.ROOT / "maps" / "light-source-evidence").resolve()
    if args.output.is_symlink() or args.output.resolve() != expected_output:
        raise ValueError("output must be maps/light-source-evidence in this checkout")
    report = json.loads(args.inventory.read_text())
    map_rows = {row["path"]: row for row in report["maps"]}
    toggle_states = {row["id"]: row for row in report["toggle_states"]}
    source_rows = {
        (source_kind, row["id"]): row
        for source_kind, section in (
            ("archetype", "archetypes"),
            ("artifact", "artifacts"),
        )
        for row in report[section]
    }
    context = json.loads(args.context.read_text())
    runtime_digest = audit._runtime_content_sha256()
    try:
        commit_digest = audit._git_runtime_content_sha256(
            context.get("content_commit")
        )
    except ValueError as error:
        raise ValueError("render-context {}".format(error)) from error
    if commit_digest != runtime_digest:
        raise ValueError(
            "render-context content_commit runtime tree disagrees with captures"
        )
    modes = {
        "smooth": _load_captures(args.smooth_manifest, "smooth"),
        "discrete": _load_captures(args.discrete_manifest, "discrete"),
    }
    plan_errors = source_plan_errors(
        report, [row for rows in modes.values() for row in rows]
    )
    if plan_errors:
        raise ValueError(plan_errors[0])
    sheet_count = sum(
        (len(rows) + SHEET_CAPACITY - 1) // SHEET_CAPACITY
        for rows in modes.values()
    )
    bound_sources: set[tuple[str, str]] = set()
    controls: dict[str, dict] = {}
    for mode, rows in modes.items():
        for row in rows:
            map_row = map_rows.get(row["map"])
            if map_row is not None:
                if row.get("map_semantic_sha256") != map_row["semantic_sha256"]:
                    raise ValueError(
                        "capture references stale map semantics: {}".format(row["map"])
                    )
            else:
                scene = audit.ROOT / row["map"]
                contained = audit._is_light_review_scene(scene)
                if not contained or not scene.is_file():
                    raise ValueError("capture references stale map: {}".format(row["map"]))
                scene_sha256 = hashlib.sha256(scene.read_bytes()).hexdigest()
                if row.get("map_source_sha256") != scene_sha256:
                    raise ValueError(
                        "capture references stale review-scene source: {}".format(
                            row["map"]
                        )
                    )
            if row.get("content_commit") != context.get("content_commit"):
                raise ValueError("capture content commit disagrees with render context")
            actual_sha256 = hashlib.sha256(row["_path"].read_bytes()).hexdigest()
            if row.get("sha256") != actual_sha256:
                raise ValueError("capture digest changed: {}".format(row["_path"]))
            source_fields = (
                "source_kind",
                "source_id",
                "source_semantic_sha256",
            )
            has_source_binding = any(row.get(field) is not None for field in source_fields)
            state_id = row.get("active_state_id")
            if state_id is not None and state_id not in toggle_states:
                raise ValueError("capture references stale toggle state: {}".format(state_id))
            if state_id is not None and mode != "smooth":
                raise ValueError("active-state capture must use smooth lighting")
            if state_id is not None and not isinstance(row.get("runtime_command"), str):
                raise ValueError("active-state capture needs its exact runtime command")
            control_id = row.get("review_control_id")
            if control_id is not None:
                if not isinstance(control_id, str) or len(control_id.strip()) < 6:
                    raise ValueError("capture has an invalid review control id")
                if state_id is None and not has_source_binding:
                    if mode != "smooth":
                        raise ValueError("source control must use smooth lighting")
                    if control_id in controls:
                        raise ValueError("duplicate review control: {}".format(control_id))
                    controls[control_id] = row
            if has_source_binding:
                if mode != "smooth":
                    raise ValueError("source-bound capture must use smooth lighting")
                source_key = (row.get("source_kind"), row.get("source_id"))
                source = source_rows.get(source_key)
                if source is None:
                    raise ValueError(
                        "capture references stale light source: {}:{}".format(*source_key)
                    )
                if row.get("source_semantic_sha256") != source["semantic_sha256"]:
                    raise ValueError(
                        "capture references stale light-source semantics: {}:{}".format(
                            *source_key
                        )
                    )
                command = row.get("runtime_command")
                if not isinstance(command, str) or len(command.strip()) < 12:
                    raise ValueError(
                        "source-bound capture needs its exact runtime command"
                    )
                bound_sources.add(source_key)
            width, height = validate_png(row["_path"])
            if (width, height) != (1024, 768):
                raise ValueError(
                    "{} capture must be a 1024x768 Classic screenshot: {}".format(
                        mode, row["_path"]
                    )
                )
    for source_kind, source_id in sorted(set(source_rows) - bound_sources):
        raise ValueError(
            "{} {} needs a smooth runtime capture".format(source_kind, source_id)
        )
    active_digests = {}
    pool_rows = [
        row
        for rows in modes.values()
        for row in rows
        if row.get("source_kind") is not None or row.get("active_state_id") is not None
    ]
    for row in pool_rows:
        control = controls.get(row.get("review_control_id"))
        if (
            control is None
            or control["map"] != row["map"]
            or control["x"] != row["x"]
            or control["y"] != row["y"]
            or control.get("capture_surface") != row.get("capture_surface")
        ):
            raise ValueError("source capture needs a matching review control")
        if row.get("active_state_id") is not None:
            state = toggle_states[row["active_state_id"]]
            render_semantics = audit._toggle_render_semantics(state)
            previous_state, previous_semantics = active_digests.setdefault(
                row["sha256"], (row["active_state_id"], render_semantics)
            )
            if previous_semantics != render_semantics:
                raise ValueError("renderer-distinct active states reuse one capture")
        width, height, active_pixels = read_png(row["_path"])
        control_width, control_height, control_pixels = read_png(control["_path"])
        if (width, height) != (control_width, control_height):
            raise ValueError("source capture and control dimensions differ")
        if row.get("active_state_id") is not None:
            rendered_source = toggle_states[row["active_state_id"]]
            rendered_extent = audit._rendered_art_extent(rendered_source)
        else:
            rendered_source = source_rows[
                (row["source_kind"], row["source_id"])
            ]
            rendered_extent = audit._source_rendered_art_extent(
                report, row["source_kind"], rendered_source
            )
        if not audit._has_visible_light_pool(
            active_pixels,
            control_pixels,
            width,
            height,
            rendered_extent,
        ):
            raise ValueError("source capture lacks a visible light pool")
    if args.dry_run:
        return {
            "captures": {mode: len(rows) for mode, rows in modes.items()},
            "sheets": sheet_count,
            "output": str(args.output),
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".{}-build-".format(args.output.name), dir=args.output.parent
    ) as transaction_name:
        transaction = Path(transaction_name)
        candidate = transaction / "candidate"
        candidate.mkdir()
        sheets = {}
        views = []
        jobs = []
        for mode, rows in modes.items():
            for offset in range(0, len(rows), SHEET_CAPACITY):
                number = offset // SHEET_CAPACITY + 1
                identifier = f"{mode}-{number:03d}"
                for tile, row in enumerate(
                    rows[offset:offset + SHEET_CAPACITY]
                ):
                    optional = {}
                    if row.get("active_state_id") is not None:
                        optional["active_state_id"] = row["active_state_id"]
                    if row.get("review_control_id") is not None:
                        optional["review_control_id"] = row["review_control_id"]
                    if row.get("source_kind") is not None:
                        optional.update({
                            "source_kind": row["source_kind"],
                            "source_id": row["source_id"],
                            "source_semantic_sha256": row[
                                "source_semantic_sha256"
                            ],
                        })
                    if row.get("capture_surface") is not None:
                        optional["capture_surface"] = row["capture_surface"]
                    if optional:
                        optional["runtime_command"] = row["runtime_command"]
                    map_binding = (
                        {"map_semantic_sha256": map_rows[row["map"]]["semantic_sha256"]}
                        if row["map"] in map_rows
                        else {"map_source_sha256": row["map_source_sha256"]}
                    )
                    views.append({
                        "id": f"{mode}-{offset + tile + 1:04d}",
                        "map": row["map"],
                        **map_binding,
                        "x": row["x"],
                        "y": row["y"],
                        "sheet": identifier,
                        "tile": tile,
                        "mode": mode,
                        "capture_sha256": row["sha256"],
                        "content_commit": row["content_commit"],
                        **optional,
                    })
                artifact_name = f"{identifier}.png"
                jobs.append((str(candidate / artifact_name), [
                    str(row["_path"])
                    for row in rows[offset:offset + SHEET_CAPACITY]
                ]))
                final_artifact = (args.output / artifact_name).resolve()
                sheets[identifier] = {
                    "artifact": final_artifact.relative_to(
                        audit.ROOT.resolve()
                    ).as_posix(),
                    "sha256": None,
                    "columns": COLUMNS,
                    "rows": ROWS,
                    "pixel_width": COLUMNS * TILE_WIDTH,
                    "pixel_height": ROWS * TILE_HEIGHT,
                    "mode": mode,
                }
        workers = min(len(jobs), 4, os.cpu_count() or 1)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            rendered = dict(executor.map(_render_sheet, jobs))
        for identifier, entry in sheets.items():
            candidate_artifact = candidate / Path(entry["artifact"]).name
            entry["sha256"] = rendered[str(candidate_artifact)]
        control_views = {
            view["review_control_id"]: view["id"]
            for view in views
            if view.get("review_control_id") is not None
            and view.get("active_state_id") is None
            and view.get("source_kind") is None
        }
        for view in views:
            if (
                view.get("active_state_id") is not None
                or view.get("source_kind") is not None
            ):
                control_id = view.get("review_control_id")
                if control_id not in control_views:
                    raise ValueError(
                        "source capture needs a matching review control"
                    )
                view["control_view"] = control_views[control_id]
        if audit._runtime_content_sha256() != runtime_digest:
            raise ValueError("runtime content changed while evidence was built")
        context["inventory_sha256"] = audit._inventory_semantic_sha256(report)
        context["runtime_content_sha256"] = runtime_digest
        active_states = {
            row["id"]: {
                "semantic_sha256": row["semantic_sha256"],
                "views": [
                    view["id"]
                    for view in views
                    if view.get("active_state_id") == row["id"]
                ],
                "rationale": row["rationale"],
            }
            for row in report["toggle_states"]
        }
        source_states = {
            "{}:{}".format(source_kind, row["id"]): {
                "source_kind": source_kind,
                "source_id": row["id"],
                "semantic_sha256": row["semantic_sha256"],
                "views": [
                    view["id"]
                    for view in views
                    if view.get("source_kind") == source_kind
                    and view.get("source_id") == row["id"]
                ],
            }
            for source_kind, section in (
                ("archetype", "archetypes"),
                ("artifact", "artifacts"),
            )
            for row in report[section]
        }
        manifest = {
            "schema_version": 2,
            "render_context": context,
            "sheets": sheets,
            "views": views,
            "representative_checks": json.loads(args.representatives.read_text()),
            "active_states": active_states,
            "source_states": source_states,
        }
        (candidate / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n"
        )
        previous = transaction / "previous"
        if args.output.exists():
            args.output.rename(previous)
        try:
            candidate.rename(args.output)
        except BaseException:
            if previous.exists():
                previous.rename(args.output)
            raise
    return {"captures": {mode: len(rows) for mode, rows in modes.items()}, "sheets": sheet_count}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan", help="print the deterministic capture plan")
    plan_parser.add_argument("--inventory", type=Path, required=True)
    source_parser = subparsers.add_parser(
        "plan-sources", help="print the deterministic source-lab capture plan"
    )
    source_parser.add_argument("--inventory", type=Path, required=True)
    source_parser.add_argument("--map", required=True)
    source_parser.add_argument("--x", type=int, required=True)
    source_parser.add_argument("--y", type=int, required=True)
    build_parser = subparsers.add_parser("build", help="build sheets and their bound manifest")
    build_parser.add_argument("--inventory", type=Path, required=True)
    build_parser.add_argument("--smooth-manifest", type=Path, required=True)
    build_parser.add_argument("--discrete-manifest", type=Path, required=True)
    build_parser.add_argument("--context", type=Path, required=True)
    build_parser.add_argument("--representatives", type=Path, required=True)
    build_parser.add_argument("--output", type=Path, required=True)
    build_parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.command == "plan":
        report = json.loads(args.inventory.read_text())
        print(json.dumps(capture_plan(report), indent=2))
    elif args.command == "plan-sources":
        report = json.loads(args.inventory.read_text())
        scene = audit.ROOT / args.map
        if not scene.is_file():
            parser.error("--map must name an existing map in this checkout")
        print(json.dumps(source_capture_plan(
            report,
            args.map,
            hashlib.sha256(scene.read_bytes()).hexdigest(),
            args.x,
            args.y,
        ), indent=2))
    else:
        print(json.dumps(build_evidence(args), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
