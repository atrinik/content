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


COLUMNS = 5
ROWS = 5
TILE_WIDTH = 204
TILE_HEIGHT = 153


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
    context = json.loads(args.context.read_text())
    modes = {
        "smooth": _load_captures(args.smooth_manifest, "smooth"),
        "discrete": _load_captures(args.discrete_manifest, "discrete"),
    }
    sheet_count = sum((len(rows) + 24) // 25 for rows in modes.values())
    for mode, rows in modes.items():
        for row in rows:
            if row["map"] not in map_rows:
                raise ValueError("capture references stale map: {}".format(row["map"]))
            if row.get("map_semantic_sha256") != map_rows[row["map"]]["semantic_sha256"]:
                raise ValueError("capture references stale map semantics: {}".format(row["map"]))
            if row.get("content_commit") != context.get("content_commit"):
                raise ValueError("capture content commit disagrees with render context")
            actual_sha256 = hashlib.sha256(row["_path"].read_bytes()).hexdigest()
            if row.get("sha256") != actual_sha256:
                raise ValueError("capture digest changed: {}".format(row["_path"]))
            state_id = row.get("active_state_id")
            if state_id is not None and state_id not in toggle_states:
                raise ValueError("capture references stale toggle state: {}".format(state_id))
            if state_id is not None and not isinstance(row.get("runtime_command"), str):
                raise ValueError("active-state capture needs its exact runtime command")
            width, height = validate_png(row["_path"])
            if (width, height) != (1024, 768):
                raise ValueError(
                    "{} capture must be a 1024x768 Classic screenshot: {}".format(
                        mode, row["_path"]
                    )
                )
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
            for offset in range(0, len(rows), 25):
                number = offset // 25 + 1
                identifier = f"{mode}-{number:03d}"
                for tile, row in enumerate(rows[offset:offset + 25]):
                    views.append({
                        "id": f"{mode}-{offset + tile + 1:04d}",
                        "map": row["map"],
                        "map_semantic_sha256": map_rows[row["map"]]["semantic_sha256"],
                        "x": row["x"],
                        "y": row["y"],
                        "sheet": identifier,
                        "tile": tile,
                        "mode": mode,
                        "capture_sha256": row["sha256"],
                        "content_commit": row["content_commit"],
                        **(
                            {
                                "active_state_id": row["active_state_id"],
                                "runtime_command": row["runtime_command"],
                            }
                            if row.get("active_state_id") else {}
                        ),
                    })
                artifact_name = f"{identifier}.png"
                jobs.append((str(candidate / artifact_name), [
                    str(row["_path"])
                    for row in rows[offset:offset + 25]
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
        context["inventory_sha256"] = audit._inventory_semantic_sha256(report)
        context["runtime_content_sha256"] = audit._runtime_content_sha256()
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
        manifest = {
            "schema_version": 2,
            "render_context": context,
            "sheets": sheets,
            "views": views,
            "representative_checks": json.loads(args.representatives.read_text()),
            "active_states": active_states,
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
    else:
        print(json.dumps(build_evidence(args), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
