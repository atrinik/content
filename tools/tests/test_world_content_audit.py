"""Tests for the read-only world content audit."""

import hashlib
import json
import struct
import subprocess
import tempfile
import unittest
import zlib
from pathlib import Path

from tools import light_review_evidence as evidence_tools
from tools import world_content_audit as audit


class WorldContentAuditTest(unittest.TestCase):
    def test_active_light_evidence_requires_a_material_pool(self):
        control = bytes(1200)
        sprite_only = bytearray(control)
        sprite_only[:24] = bytes([255] * 24)
        light_pool = bytearray(control)
        light_pool[:600] = bytes([12] * 600)

        self.assertFalse(audit._has_visible_light_pool(control, control))
        self.assertFalse(audit._has_visible_light_pool(bytes(sprite_only), control))
        self.assertTrue(audit._has_visible_light_pool(bytes(light_pool), control))

        width, height = 1024, 768
        full_control = bytes(width * height * 3)
        ui_only = bytearray(full_control)
        ui_only[:6000] = bytes([12] * 6000)
        compact_sprite = bytearray(full_control)
        central_pool = bytearray(full_control)
        for y in range(height // 3, height // 3 + 32):
            start = (y * width + width // 2) * 3
            compact_sprite[start:start + 32 * 3] = bytes([255] * 32 * 3)
        for y in range(height // 3, height // 3 + 40):
            start = (y * width + width // 2) * 3
            central_pool[start:start + 40 * 3] = bytes([12] * 40 * 3)
        self.assertFalse(
            audit._has_visible_light_pool(
                bytes(ui_only), full_control, width, height
            )
        )
        self.assertFalse(
            audit._has_visible_light_pool(
                bytes(compact_sprite), full_control, width, height, (32, 32)
            )
        )
        self.assertTrue(
            audit._has_visible_light_pool(
                bytes(central_pool), full_control, width, height
            )
        )

        tile_width = audit.LIGHT_EVIDENCE_TILE_WIDTH - 1
        tile_height = audit.LIGHT_EVIDENCE_TILE_HEIGHT - 1
        tile_control = bytes(tile_width * tile_height * 3)
        tile_sprite = bytearray(tile_control)
        tile_sprite[:24] = bytes([255] * 24)
        tile_compact_sprite = bytearray(tile_control)
        tile_pool = bytearray(tile_control)
        for y in range(tile_height // 3, tile_height // 3 + 8):
            start = (y * tile_width + tile_width // 2) * 3
            tile_compact_sprite[start:start + 8 * 3] = bytes([255] * 8 * 3)
        for y in range(tile_height // 3, tile_height // 3 + 12):
            start = (y * tile_width + tile_width // 2) * 3
            tile_pool[start:start + 12 * 3] = bytes([18] * 12 * 3)
        self.assertFalse(
            audit._has_visible_light_pool(
                bytes(tile_sprite), tile_control, tile_width, tile_height
            )
        )
        self.assertFalse(
            audit._has_visible_light_pool(
                bytes(tile_compact_sprite),
                tile_control,
                tile_width,
                tile_height,
                (40, 40),
            )
        )
        self.assertTrue(
            audit._has_visible_light_pool(
                bytes(tile_pool), tile_control, tile_width, tile_height
            )
        )

        # A real oversized Classic face must not count as emitted light merely
        # because its changed pixels span more than one 32-pixel map cell.
        forcefield_path = (
            self.original_roots[0]
            / "arch/magic/forcefield/forcefield_blue/forcefield_blue.101.png"
        )
        palette = transparency = b""
        compressed = bytearray()
        for name, payload in evidence_tools._png_chunks(forcefield_path.read_bytes()):
            if name == b"IHDR":
                face_width, face_height = struct.unpack(">II", payload[:8])
            elif name == b"PLTE":
                palette = payload
            elif name == b"tRNS":
                transparency = payload
            elif name == b"IDAT":
                compressed.extend(payload)
        raw = zlib.decompress(bytes(compressed))
        previous = bytearray(face_width)
        face_pixels = bytearray(face_width * face_height * 3)
        for y in range(face_height):
            start = y * (face_width + 1)
            filter_type = raw[start]
            scanline = bytearray(raw[start + 1:start + face_width + 1])
            for x in range(face_width):
                left = scanline[x - 1] if x else 0
                above = previous[x]
                upper_left = previous[x - 1] if x else 0
                if filter_type == 1:
                    scanline[x] = (scanline[x] + left) & 0xff
                elif filter_type == 2:
                    scanline[x] = (scanline[x] + above) & 0xff
                elif filter_type == 3:
                    scanline[x] = (scanline[x] + (left + above) // 2) & 0xff
                elif filter_type == 4:
                    estimate = left + above - upper_left
                    candidates = (left, above, upper_left)
                    scanline[x] = (
                        scanline[x]
                        + min(candidates, key=lambda value: abs(estimate - value))
                    ) & 0xff
                elif filter_type != 0:
                    self.fail("unsupported indexed PNG filter")
            for x, palette_index in enumerate(scanline):
                alpha = (
                    transparency[palette_index]
                    if palette_index < len(transparency)
                    else 255
                )
                source = palette_index * 3
                target = (y * face_width + x) * 3
                face_pixels[target:target + 3] = bytes(
                    (palette[source + component] * alpha + 127) // 255
                    for component in range(3)
                )
            previous = scanline
        face_only = bytearray(full_control)
        face_left = width // 2
        face_top = height // 3
        for y in range(face_height):
            source = y * face_width * 3
            target = ((face_top + y) * width + face_left) * 3
            face_only[target:target + face_width * 3] = face_pixels[
                source:source + face_width * 3
            ]
        self.assertFalse(
            audit._has_visible_light_pool(
                bytes(face_only),
                full_control,
                width,
                height,
                (face_width, face_height),
            )
        )

        sampled_width = (face_width * audit.LIGHT_EVIDENCE_TILE_WIDTH + 1023) // 1024
        sampled_height = (face_height * audit.LIGHT_EVIDENCE_TILE_HEIGHT + 767) // 768
        sampled_face_only = bytearray(tile_control)
        sampled_left = tile_width // 2
        sampled_top = tile_height // 3
        for y in range(sampled_height):
            source_y = y * face_height // sampled_height
            for x in range(sampled_width):
                source_x = x * face_width // sampled_width
                source = (source_y * face_width + source_x) * 3
                target = (
                    (sampled_top + y) * tile_width + sampled_left + x
                ) * 3
                sampled_face_only[target:target + 3] = face_pixels[source:source + 3]
        self.assertFalse(
            audit._has_visible_light_pool(
                bytes(sampled_face_only),
                tile_control,
                tile_width,
                tile_height,
                (face_width, face_height),
            )
        )

    def test_rendered_art_extent_fails_closed_on_missing_or_invalid_art(self):
        audit._ART_INDEX_CACHE.clear()
        with self.assertRaisesRegex(ValueError, "rendered face is unresolved"):
            audit._rendered_art_extent({"face": "missing.101", "visible": True})

        evidence_tools.write_png(
            audit.ARCH_ROOT / "valid.101.png", 32, 32, bytes(32 * 32 * 3)
        )
        audit._ART_INDEX_CACHE.clear()
        with self.assertRaisesRegex(ValueError, "rendered animation is unresolved"):
            audit._rendered_art_extent({
                "face": "valid.101",
                "animation": "missing_animation",
                "visible": True,
            })

        (audit.ARCH_ROOT / "invalid.101.png").write_bytes(b"not a PNG")
        audit._ART_INDEX_CACHE.clear()
        audit._ART_DIMENSION_CACHE.clear()
        with self.assertRaisesRegex(ValueError, "invalid PNG"):
            audit._rendered_art_extent({"face": "invalid.101", "visible": True})

        truncated = audit.ARCH_ROOT / "truncated.101.png"
        truncated.write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
            + struct.pack(">II", 48, 69)
        )
        audit._ART_INDEX_CACHE.clear()
        audit._ART_DIMENSION_CACHE.clear()
        with self.assertRaisesRegex(ValueError, "invalid PNG"):
            audit._rendered_art_extent({
                "face": "truncated.101", "visible": True
            })

        zero = audit.ARCH_ROOT / "zero.101.png"
        evidence_tools.write_png(zero, 0, 0, b"")
        audit._ART_INDEX_CACHE.clear()
        audit._ART_DIMENSION_CACHE.clear()
        with self.assertRaisesRegex(ValueError, "invalid PNG"):
            audit._rendered_art_extent({"face": "zero.101", "visible": True})

        for name, depth, color_type, stride, extra_chunks in (
            ("rgba1.101", 1, 6, 4, b""),
            (
                "indexed16.101",
                16,
                3,
                16,
                evidence_tools._chunk(b"PLTE", b"\x00\x00\x00"),
            ),
        ):
            invalid_encoding = audit.ARCH_ROOT / (name + ".png")
            ihdr = struct.pack(">IIBBBBB", 8, 8, depth, color_type, 0, 0, 0)
            scanlines = bytes([0] + [0] * stride) * 8
            invalid_encoding.write_bytes(
                b"\x89PNG\r\n\x1a\n"
                + evidence_tools._chunk(b"IHDR", ihdr)
                + extra_chunks
                + evidence_tools._chunk(b"IDAT", zlib.compress(scanlines))
                + evidence_tools._chunk(b"IEND", b"")
            )
            audit._ART_INDEX_CACHE.clear()
            audit._ART_DIMENSION_CACHE.clear()
            with self.assertRaisesRegex(ValueError, "invalid PNG"):
                audit._rendered_art_extent({"face": name, "visible": True})

        signature = b"\x89PNG\r\n\x1a\n"
        indexed_ihdr = evidence_tools._chunk(
            b"IHDR", struct.pack(">IIBBBBB", 8, 8, 1, 3, 0, 0, 0)
        )
        indexed_idat = evidence_tools._chunk(
            b"IDAT", zlib.compress(bytes([0, 0]) * 8)
        )
        rgb_ihdr = evidence_tools._chunk(
            b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
        )
        rgb_compressed = zlib.compress(b"\x00\x00\x00\x00")
        rgba_ihdr = evidence_tools._chunk(
            b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
        )
        ordering_cases = {
            "late_ihdr.101": (
                evidence_tools._chunk(b"tEXt", b"note\x00value")
                + rgb_ihdr
                + evidence_tools._chunk(b"IDAT", rgb_compressed)
                + evidence_tools._chunk(b"IEND", b"")
            ),
            "late_palette.101": (
                indexed_ihdr
                + indexed_idat
                + evidence_tools._chunk(b"PLTE", b"\x00\x00\x00\xff\xff\xff")
                + evidence_tools._chunk(b"IEND", b"")
            ),
            "split_idat.101": (
                rgb_ihdr
                + evidence_tools._chunk(b"IDAT", rgb_compressed[:3])
                + evidence_tools._chunk(b"tEXt", b"note\x00value")
                + evidence_tools._chunk(b"IDAT", rgb_compressed[3:])
                + evidence_tools._chunk(b"IEND", b"")
            ),
            "oversized_palette.101": (
                indexed_ihdr
                + evidence_tools._chunk(b"PLTE", b"\x00\x00\x00" * 3)
                + indexed_idat
                + evidence_tools._chunk(b"IEND", b"")
            ),
            "rgba_transparency.101": (
                rgba_ihdr
                + evidence_tools._chunk(b"tRNS", b"\x00")
                + evidence_tools._chunk(
                    b"IDAT", zlib.compress(b"\x00\x00\x00\x00\x00")
                )
                + evidence_tools._chunk(b"IEND", b"")
            ),
            "early_indexed_transparency.101": (
                indexed_ihdr
                + evidence_tools._chunk(b"tRNS", b"\x00")
                + evidence_tools._chunk(b"PLTE", b"\x00\x00\x00\xff\xff\xff")
                + indexed_idat
                + evidence_tools._chunk(b"IEND", b"")
            ),
            "oversized_indexed_transparency.101": (
                indexed_ihdr
                + evidence_tools._chunk(b"PLTE", b"\x00\x00\x00\xff\xff\xff")
                + evidence_tools._chunk(b"tRNS", b"\x00\x80\xff")
                + indexed_idat
                + evidence_tools._chunk(b"IEND", b"")
            ),
            "late_indexed_transparency.101": (
                indexed_ihdr
                + evidence_tools._chunk(b"PLTE", b"\x00\x00\x00\xff\xff\xff")
                + indexed_idat
                + evidence_tools._chunk(b"tRNS", b"\x00\x80")
                + evidence_tools._chunk(b"IEND", b"")
            ),
            "short_rgb_transparency.101": (
                rgb_ihdr
                + evidence_tools._chunk(b"tRNS", b"\x00\x00")
                + evidence_tools._chunk(b"IDAT", rgb_compressed)
                + evidence_tools._chunk(b"IEND", b"")
            ),
            "wide_rgb_transparency.101": (
                rgb_ihdr
                + evidence_tools._chunk(
                    b"tRNS", struct.pack(">HHH", 0x0100, 0, 0)
                )
                + evidence_tools._chunk(b"IDAT", rgb_compressed)
                + evidence_tools._chunk(b"IEND", b"")
            ),
            "empty_indexed_transparency.101": (
                indexed_ihdr
                + evidence_tools._chunk(b"PLTE", b"\x00\x00\x00")
                + evidence_tools._chunk(b"tRNS", b"")
                + indexed_idat
                + evidence_tools._chunk(b"IEND", b"")
            ),
            "missing_palette_index.101": (
                indexed_ihdr
                + evidence_tools._chunk(b"PLTE", b"\x00\x00\x00")
                + evidence_tools._chunk(
                    b"IDAT", zlib.compress(bytes([0, 0x80]) * 8)
                )
                + evidence_tools._chunk(b"IEND", b"")
            ),
            "nonempty_iend.101": (
                rgb_ihdr
                + evidence_tools._chunk(b"IDAT", rgb_compressed)
                + evidence_tools._chunk(b"IEND", b"invalid")
            ),
        }
        for name, chunks in ordering_cases.items():
            (audit.ARCH_ROOT / (name + ".png")).write_bytes(signature + chunks)
            audit._ART_INDEX_CACHE.clear()
            audit._ART_DIMENSION_CACHE.clear()
            with self.assertRaisesRegex(ValueError, "invalid PNG"):
                audit._rendered_art_extent({"face": name, "visible": True})

        rgba_palette = audit.ARCH_ROOT / "rgba_palette.101.png"
        rgba_palette.write_bytes(
            signature
            + rgba_ihdr
            + evidence_tools._chunk(b"PLTE", b"\x00\x00\x00")
            + evidence_tools._chunk(
                b"IDAT", zlib.compress(b"\x00\x00\x00\x00\x00")
            )
            + evidence_tools._chunk(b"IEND", b"")
        )
        audit._ART_DIMENSION_CACHE.clear()
        self.assertEqual(
            (1, 1), audit._validated_art_png_dimensions(rgba_palette)
        )

    def test_toggle_render_semantics_ignore_identity_but_track_pixels(self):
        first = {
            "activation_archetype": "lamp",
            "radius": 5,
            "color": "ffd080",
            "face": "lamp.101",
            "animation": "lamp",
            "visible": True,
        }
        alias = {**first, "activation_archetype": "quest_lamp"}
        larger = {**first, "radius": 9}

        self.assertEqual(
            audit._toggle_render_semantics(first),
            audit._toggle_render_semantics(alias),
        )
        self.assertNotEqual(
            audit._toggle_render_semantics(first),
            audit._toggle_render_semantics(larger),
        )

    def test_runtime_digest_excludes_review_and_python_cache_paths(self):
        for relative in (
            "maps/light-source-review.json",
            "maps/light-source-review/dark-lab",
            "maps/light-source-evidence/smooth-001.png",
            "maps/python/__pycache__/Common.cpython-314.pyc",
            "maps/python/stale.pyc",
        ):
            self.assertTrue(audit._is_review_only_runtime_path(relative), relative)
        self.assertFalse(audit._is_review_only_runtime_path("maps/python/Common.py"))
        self.assertTrue(
            audit._is_light_review_scene(
                self.root / "tools/light-source-review/dark-lab"
            )
        )
        self.assertFalse(
            audit._is_light_review_scene(self.root / "tools/other-map")
        )

        self.write("arch/construction.arc", "Object construction\nend\n")
        self.write("arch/construction/LICENSE", "fixture license\n")
        self.write("maps/python/Common.py", "VALUE = 1\n")
        self.git("init", "-q")
        self.git("add", "arch", "maps/python/Common.py")
        self.git("commit", "-qm", "fixture runtime tree")
        commit = self.git("rev-parse", "HEAD")
        self.write("maps/python/__pycache__/Common.cpython-314.pyc", "cache")
        self.write("maps/light-source-review/dark-lab", "review only\n")

        self.assertEqual(
            audit._git_runtime_content_sha256(commit),
            audit._runtime_content_sha256(),
        )

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.original_roots = (audit.ROOT, audit.MAP_ROOT, audit.ARCH_ROOT)
        audit.ROOT = self.root
        audit.MAP_ROOT = self.root / "maps"
        audit.ARCH_ROOT = self.root / "arch"
        audit.MAP_ROOT.mkdir()
        audit.ARCH_ROOT.mkdir()

    def tearDown(self):
        audit.ROOT, audit.MAP_ROOT, audit.ARCH_ROOT = self.original_roots
        self.temporary_directory.cleanup()

    def write(self, relative_path, contents):
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
        return path

    def git(self, *args):
        result = subprocess.run(
            [
                "git",
                "-c",
                "user.name=World Audit Test",
                "-c",
                "user.email=world-audit-test@example.invalid",
                *args,
            ],
            cwd=self.root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return result.stdout.strip()

    def test_inventories_are_structured_and_json_serializable(self):
        self.write(
            "arch/monsters.arc",
            """Object sample_monster
name sample monster
type 80
level 3
end
""",
        )
        self.write(
            "arch/items.art",
            """artifact sample_artifact
def_arch sample_monster
chance 10
Object
name sample reward
end
""",
        )
        self.write(
            "maps/regions.reg",
            """region sample
name Sample Region
msg
Sample description.
endmsg
end
""",
        )
        self.write(
            "maps/world_2_1",
            """arch map
name Sample Map
region sample
width 24
height 24
outdoor 1
end
arch sample_monster
name named sample
x 4
y 5
end
""",
        )
        self.write(
            "maps/interfaces/quests/sample/quest.xml",
            """<dialog><quest name="sample"><part name="first" uid="1">
<info>Find the sample.</info><kill arch="sample_monster" />
</part></quest></dialog>
""",
        )

        report = {
            "quests": audit.quest_inventory(),
            "regions": audit.region_registry(),
            "artifacts": audit.artifact_inventory(),
            "world": audit.world_inventory(),
        }

        self.assertEqual("sample", report["quests"][0]["name"])
        self.assertEqual("Sample description.", report["regions"][0]["msg"])
        self.assertEqual("sample_artifact", report["artifacts"][0]["id"])
        self.assertEqual([2, 1, 0], report["world"]["maps"][0]["world_coord"])
        self.assertEqual("named sample", report["world"]["named_monsters"][0]["name"])
        json.dumps(report)

    def test_map_discovery_is_deterministic_and_ignores_non_maps(self):
        later = self.write("maps/z_map", "arch map\nend\n")
        earlier = self.write("maps/a_map", "arch map\nend\n")
        self.write("maps/readme.txt", "not a map\n")

        self.assertEqual([earlier, later], audit.map_files())

    def test_light_inventory_resolves_inheritance_overrides_and_reviews(self):
        self.write(
            "arch/lights.arc",
            """Object colored_lamp
name colored lamp
face lamp.101
animation lamp
glow_radius 4
light_color ff8040
end
Object light2
name light
face light_bulb_2.111
glow_radius 2
no_pick 1
sys_object 1
type 78
end
Object inert
name inert
animation inert
light_color 4060ff
end
""",
        )
        self.write(
            "arch/lights.art",
            """artifact glowing_reward
def_arch inert
Object
glow_radius 1
face reward.101
end
            """,
        )
        evidence_tools.write_png(
            audit.ARCH_ROOT / "lamp.101.png", 32, 40, bytes(32 * 40 * 3)
        )
        evidence_tools.write_png(
            audit.ARCH_ROOT / "reward.101.png", 32, 32, bytes(32 * 32 * 3)
        )
        self.write("arch/lamp.anim", "anim lamp\nlamp.101\nmina\n")
        audit._ART_INDEX_CACHE.clear()
        self.write(
            "maps/scene",
            """arch map
name Reviewed Scene
region sample
darkness 3
end
arch colored_lamp
x 2
y 3
end
arch light2
x 4
y 5
end
arch inert
x 6
y 7
face orb.101
animation orb
glow_radius 3
light_color 4060ff
end
""",
        )
        review_path = self.write(
            "maps/light-source-review.json",
            json.dumps(
                {
                    "schema_version": 5,
                    "review_method": "test semantic and rendered inspection",
                    "palette": {
                        "4060ff": {"rationale": "focused blue magic"},
                        "ff8040": {"rationale": "warm lamp flame"},
                    },
                    "archetypes": {
                        "colored_lamp": {
                            "uncolored_disposition": "neutral",
                            "rationale": "Warm visible lamp flame.",
                        },
                        "light2": {
                            "uncolored_disposition": "neutral",
                            "rationale": "Neutral invisible composition light.",
                        },
                    },
                    "artifacts": {
                        "glowing_reward": {
                            "uncolored_disposition": "neutral",
                            "rationale": "Neutral reward glow preserves its art.",
                        },
                    },
                    "color_sources": {
                        "colored_lamp": {
                            "rationale": "Warm orange follows this lamp's flame art."
                        },
                        "inert": {
                            "rationale": "Blue follows the inherited inert crystal art."
                        }
                    },
                    "toggle_states": {},
                    "fixture_groups": {
                        "warm-fixtures": {
                            "archetypes": ["colored_lamp"],
                            "default_radii": {"colored_lamp": 4},
                            "expected_color": "ff8040",
                            "expected_maps": 1,
                            "expected_placements": {"colored_lamp": 1},
                            "intentional_non_emitters": {},
                            "checks": ["overlap"],
                            "rationale": "Tracks every warm fixture placement.",
                        }
                    },
                    "context_checks": {
                        check: {
                            "status": "pass",
                            "views": ["smooth-scene", "discrete-scene"],
                            "rationale": "Compared the scene in both lighting modes.",
                        }
                        for check in (
                            "overlap",
                            "linked-depth",
                            "horizontal-boundary",
                            "dark-interior",
                            "outdoor-transition",
                            "fog-roof",
                            "navigation",
                        )
                    },
                    "maps": {
                        "maps/scene": {
                            "uncolored_disposition": "neutral",
                            "rationale": "Rendered room keeps neutral fill around colored accents.",
                            "visible_neutral": {},
                            "art_overrides": {
                                "14": "Blue orb art intentionally overrides the inert base."
                            },
                        }
                    },
                }
            ),
        )

        report = audit.light_inventory()
        review = json.loads(review_path.read_text())
        for section, identity in (
            ("archetypes", "id"),
            ("artifacts", "id"),
            ("color_sources", "id"),
            ("toggle_states", "id"),
            ("maps", "path"),
        ):
            for row in report[section]:
                review[section][row[identity]]["semantic_sha256"] = row[
                    "semantic_sha256"
                ]
        review["fixture_groups"]["warm-fixtures"]["semantic_sha256"] = report[
            "fixture_groups"
        ][0]["semantic_sha256"]
        review_path.write_text(json.dumps(review))
        report = audit.light_inventory()
        review_scene = self.write(
            evidence_tools.SOURCE_REVIEW_MAP, "arch map\nend\n"
        )
        source_plan = evidence_tools.source_capture_plan(
            report,
            evidence_tools.SOURCE_REVIEW_MAP,
            hashlib.sha256(review_scene.read_bytes()).hexdigest(),
            evidence_tools.SOURCE_REVIEW_X,
            evidence_tools.SOURCE_REVIEW_Y,
        )
        planned_control = source_plan[0]
        planned_sources = {
            (row.get("source_kind"), row.get("source_id")): row
            for row in source_plan
            if row.get("source_kind") is not None
        }
        planned_map_control = source_plan[-1]
        self.git("init", "-q")
        self.git("add", "arch", "maps")
        self.git("commit", "-qm", "fixture runtime tree")
        content_commit = self.git("rev-parse", "HEAD")
        evidence_dir = self.root / "maps/light-source-evidence"
        evidence_dir.mkdir()
        smooth = evidence_dir / "smooth.png"
        discrete = evidence_dir / "discrete.png"
        sheet_pixels = bytearray(
            audit.LIGHT_EVIDENCE_WIDTH * audit.LIGHT_EVIDENCE_HEIGHT * 3
        )
        for tile, value in ((2, 12), (3, 18), (4, 24)):
            tile_x = (tile % audit.LIGHT_EVIDENCE_COLUMNS) * audit.LIGHT_EVIDENCE_TILE_WIDTH
            tile_y = (tile // audit.LIGHT_EVIDENCE_COLUMNS) * audit.LIGHT_EVIDENCE_TILE_HEIGHT
            for y in range(tile_y + 65, tile_y + 85):
                for x in range(tile_x + 90, tile_x + 110):
                    offset = (y * audit.LIGHT_EVIDENCE_WIDTH + x) * 3
                    sheet_pixels[offset:offset + 3] = bytes([value] * 3)
        evidence_tools.write_png(
            smooth,
            audit.LIGHT_EVIDENCE_WIDTH,
            audit.LIGHT_EVIDENCE_HEIGHT,
            bytes(sheet_pixels),
        )
        evidence_tools.write_png(
            discrete,
            audit.LIGHT_EVIDENCE_WIDTH,
            audit.LIGHT_EVIDENCE_HEIGHT,
            bytes(audit.LIGHT_EVIDENCE_WIDTH * audit.LIGHT_EVIDENCE_HEIGHT * 3),
        )
        image = smooth.read_bytes()
        evidence = {
            "schema_version": 2,
            "render_context": {
                "content_commit": content_commit,
                "classic_client_commit": "2" * 40,
                "classic_server_commit": "4" * 40,
                "resources_commit": "3" * 40,
                "content_source": (
                    "https://github.com/atrinik/content/tree/" + content_commit
                ),
                "classic_client_source": (
                    "https://github.com/atrinik/classic/tree/" + "2" * 40
                ),
                "classic_server_source": (
                    "https://github.com/atrinik/classic/tree/" + "4" * 40
                ),
                "resources_source": "https://github.com/atrinik/resources/tree/" + "3" * 40,
                "inventory_sha256": audit._inventory_semantic_sha256(report),
                "runtime_content_sha256": audit._runtime_content_sha256(),
                "profile": "test-light-review",
                "command": "test Classic client screenshot command",
                "settings": "seventeen by seventeen viewport with frozen lighting modes",
                "ordinary_state": "all carried toggle lights are inactive",
            },
            "sheets": {
                "smooth": {
                    "artifact": "maps/light-source-evidence/smooth.png",
                    "sha256": audit.hashlib.sha256(smooth.read_bytes()).hexdigest(),
                    "columns": audit.LIGHT_EVIDENCE_COLUMNS,
                    "rows": audit.LIGHT_EVIDENCE_ROWS,
                    "pixel_width": audit.LIGHT_EVIDENCE_WIDTH,
                    "pixel_height": audit.LIGHT_EVIDENCE_HEIGHT,
                    "mode": "smooth",
                },
                "discrete": {
                    "artifact": "maps/light-source-evidence/discrete.png",
                    "sha256": audit.hashlib.sha256(discrete.read_bytes()).hexdigest(),
                    "columns": audit.LIGHT_EVIDENCE_COLUMNS,
                    "rows": audit.LIGHT_EVIDENCE_ROWS,
                    "pixel_width": audit.LIGHT_EVIDENCE_WIDTH,
                    "pixel_height": audit.LIGHT_EVIDENCE_HEIGHT,
                    "mode": "discrete",
                },
            },
            "views": [
                {
                    "id": "smooth-scene",
                    "map": "maps/scene",
                    "map_semantic_sha256": report["maps"][0]["semantic_sha256"],
                    "x": 4,
                    "y": 5,
                    "sheet": "smooth",
                    "tile": 0,
                    "mode": "smooth",
                    "capture_sha256": "5" * 64,
                    "content_commit": content_commit,
                },
                {
                    **{
                        key: value
                        for key, value in planned_control.items()
                        if key != "number"
                    },
                    "id": "toggle-control",
                    "sheet": "smooth",
                    "tile": 1,
                    "mode": "smooth",
                    "capture_sha256": "a" * 64,
                    "content_commit": content_commit,
                },
                {
                    **{
                        key: value
                        for key, value in planned_sources[
                            ("archetype", "colored_lamp")
                        ].items()
                        if key != "number"
                    },
                    "id": "smooth-colored-lamp",
                    "sheet": "smooth",
                    "tile": 2,
                    "mode": "smooth",
                    "capture_sha256": "7" * 64,
                    "content_commit": content_commit,
                    "control_view": "map-control",
                },
                {
                    **{
                        key: value
                        for key, value in planned_sources[
                            ("archetype", "light2")
                        ].items()
                        if key != "number"
                    },
                    "id": "smooth-light2",
                    "sheet": "smooth",
                    "tile": 3,
                    "mode": "smooth",
                    "capture_sha256": "8" * 64,
                    "content_commit": content_commit,
                    "control_view": "map-control",
                },
                {
                    **{
                        key: value
                        for key, value in planned_sources[
                            ("artifact", "glowing_reward")
                        ].items()
                        if key != "number"
                    },
                    "id": "smooth-glowing-reward",
                    "sheet": "smooth",
                    "tile": 4,
                    "mode": "smooth",
                    "capture_sha256": "9" * 64,
                    "content_commit": content_commit,
                    "control_view": "map-control",
                },
                {
                    **{
                        key: value
                        for key, value in planned_map_control.items()
                        if key != "number"
                    },
                    "id": "map-control",
                    "sheet": "smooth",
                    "tile": 5,
                    "mode": "smooth",
                    "capture_sha256": "b" * 64,
                    "content_commit": content_commit,
                },
                {
                    "id": "discrete-scene",
                    "map": "maps/scene",
                    "map_semantic_sha256": report["maps"][0]["semantic_sha256"],
                    "x": 4,
                    "y": 5,
                    "sheet": "discrete",
                    "tile": 0,
                    "mode": "discrete",
                    "capture_sha256": "6" * 64,
                    "content_commit": content_commit,
                },
            ],
            "representative_checks": {
                check: {
                    "views": ["smooth-scene", "discrete-scene"],
                    "rationale": "Compared the scene in both lighting modes.",
                }
                for check in (
                    "overlap",
                    "linked-depth",
                    "horizontal-boundary",
                    "dark-interior",
                    "outdoor-transition",
                    "fog-roof",
                    "navigation",
                )
            },
            "active_states": {},
            "source_states": {
                "archetype:colored_lamp": {
                    "source_kind": "archetype",
                    "source_id": "colored_lamp",
                    "semantic_sha256": report["archetypes"][0]["semantic_sha256"],
                    "views": ["smooth-colored-lamp"],
                },
                "archetype:light2": {
                    "source_kind": "archetype",
                    "source_id": "light2",
                    "semantic_sha256": report["archetypes"][1]["semantic_sha256"],
                    "views": ["smooth-light2"],
                },
                "artifact:glowing_reward": {
                    "source_kind": "artifact",
                    "source_id": "glowing_reward",
                    "semantic_sha256": report["artifacts"][0]["semantic_sha256"],
                    "views": ["smooth-glowing-reward"],
                },
            },
        }
        evidence_path = self.write(
            "maps/light-source-evidence/manifest.json", json.dumps(evidence)
        )

        self.assertEqual(
            {
                "archetypes": 2,
                "artifacts": 1,
                "color_sources": 2,
                "toggle_states": 0,
                "fixture_groups": 1,
                "fixture_placements": 1,
                "maps": 1,
                "map_instances": 3,
                "visible_map_instances": 2,
                "invisible_map_instances": 1,
                "explicit_color": 4,
                "intentional_neutral": 2,
                "unreviewed": 0,
                "colors": ["4060ff", "ff8040"],
            },
            report["summary"],
        )
        self.assertEqual([], audit.validate_light_inventory(report))

        stale_surface = json.loads(json.dumps(evidence))
        next(
            view
            for view in stale_surface["views"]
            if view["id"] == "smooth-colored-lamp"
        )["capture_surface"] = "window"
        evidence_path.write_text(json.dumps(stale_surface))
        self.assertIn(
            "source-plan row ('source', 'archetype', 'colored_lamp') has stale capture_surface",
            audit.validate_light_inventory(report),
        )
        evidence_path.write_text(json.dumps(evidence))

        evidence_tools.write_png(
            smooth,
            audit.LIGHT_EVIDENCE_WIDTH,
            audit.LIGHT_EVIDENCE_HEIGHT,
            bytes(audit.LIGHT_EVIDENCE_WIDTH * audit.LIGHT_EVIDENCE_HEIGHT * 3),
        )
        blank_sources = json.loads(json.dumps(evidence))
        blank_sources["sheets"]["smooth"]["sha256"] = hashlib.sha256(
            smooth.read_bytes()
        ).hexdigest()
        evidence_path.write_text(json.dumps(blank_sources))
        self.assertIn(
            "light source archetype:colored_lamp view smooth-colored-lamp lacks a visible light pool",
            audit.validate_light_inventory(report),
        )
        smooth.write_bytes(image)
        evidence_path.write_text(json.dumps(evidence))

        tiny_evidence = json.loads(json.dumps(evidence))
        evidence_tools.write_png(smooth, 1, 1, b"\x00\x00\x00")
        tiny_evidence["sheets"]["smooth"].update({
            "sha256": audit.hashlib.sha256(smooth.read_bytes()).hexdigest(),
            "columns": 1,
            "rows": 1,
            "pixel_width": 1,
            "pixel_height": 1,
        })
        evidence_path.write_text(json.dumps(tiny_evidence))
        geometry_errors = audit.validate_light_inventory(report)
        self.assertIn(
            "light-source evidence sheet smooth must use 5 by 5 tiles",
            geometry_errors,
        )
        self.assertIn(
            "light-source evidence sheet smooth must declare 1020 by 765 pixels",
            geometry_errors,
        )
        smooth.write_bytes(image)
        evidence_path.write_text(json.dumps(evidence))

        smooth.write_bytes(
            b"\x89PNG\r\n\x1a\n"
            + evidence_tools._chunk(
                b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
            )
            + evidence_tools._chunk(b"IEND", b"")
        )
        errors = audit.validate_light_inventory(report)
        self.assertTrue(
            any("smooth is not a valid image" in error for error in errors), errors
        )
        scene = report["maps"][0]
        self.assertEqual("3", scene["darkness"])
        self.assertEqual("intentional-neutral", scene["emitters"][1]["disposition"])
        self.assertFalse(scene["emitters"][1]["visible"])
        artifact = report["artifacts"][0]
        self.assertTrue(artifact["visible"])
        self.assertEqual("reward.101", artifact["face"])
        self.assertEqual("4060ff", artifact["color"])
        self.assertEqual("inert", artifact["color_source"]["object"])
        self.assertEqual("artifact", artifact["radius_source"]["kind"])
        self.assertEqual("glow_radius", artifact["radius_source"]["field"])
        lamp = report["archetypes"][0]
        self.assertEqual("glow_radius", lamp["radius_source"]["field"])
        self.assertEqual(5, lamp["radius_source"]["field_line"])
        self.assertEqual("archetype", scene["emitters"][0]["color_source"]["kind"])
        override = scene["emitters"][2]
        self.assertEqual("map", override["radius_source"]["kind"])
        self.assertEqual("maps/scene", override["radius_source"]["path"])
        self.assertEqual("light_color", override["color_source"]["field"])
        self.assertEqual("orb", override["animation"])
        self.assertEqual("map", override["animation_source"]["kind"])
        self.assertEqual(["face", "animation"], override["art_override_fields"])

        broken_report = audit.light_inventory()
        broken_report["maps"][0]["emitters"][0]["radius_source"] = None
        self.assertIn(
            "map emitter maps/scene:6 has invalid radius provenance",
            audit.validate_light_inventory(broken_report),
        )

        review = json.loads(review_path.read_text())
        review["context_checks"]["overlap"]["status"] = "not-applicable"
        review_path.write_text(json.dumps(review))
        self.assertIn(
            "contextual lighting check overlap must record pass",
            audit.validate_light_inventory(audit.light_inventory()),
        )

        review["context_checks"]["overlap"]["status"] = "pass"
        review_path.write_text(json.dumps(review))
        smooth.write_bytes(b"changed evidence")
        self.assertIn(
            "light-source evidence sheet smooth artifact hash changed",
            audit.validate_light_inventory(audit.light_inventory()),
        )

        smooth.write_bytes(image)
        smooth.unlink()
        self.assertIn(
            "light-source evidence sheet smooth artifact is missing",
            audit.validate_light_inventory(audit.light_inventory()),
        )
        smooth.write_bytes(image)

        missing_source_evidence = json.loads(evidence_path.read_text())
        missing_source_evidence["source_states"].pop("artifact:glowing_reward")
        evidence_path.write_text(json.dumps(missing_source_evidence))
        self.assertIn(
            "light source artifact:glowing_reward lacks runtime evidence",
            audit.validate_light_inventory(audit.light_inventory()),
        )
        evidence_path.write_text(json.dumps(evidence))

        unresolved_evidence = json.loads(json.dumps(evidence))
        unresolved_commit = "0" * 40
        unresolved_evidence["render_context"]["content_commit"] = unresolved_commit
        unresolved_evidence["render_context"]["content_source"] = (
            "https://github.com/atrinik/content/tree/" + unresolved_commit
        )
        for view in unresolved_evidence["views"]:
            view["content_commit"] = unresolved_commit
        evidence_path.write_text(json.dumps(unresolved_evidence))
        self.assertIn(
            "light-source evidence content commit does not resolve",
            audit.validate_light_inventory(audit.light_inventory()),
        )
        evidence_path.write_text(json.dumps(evidence))

        uncommitted = self.write(
            "arch/post-render.arc", "# uncommitted runtime tree change\n"
        )
        mismatched_evidence = json.loads(json.dumps(evidence))
        mismatched_evidence["render_context"]["runtime_content_sha256"] = (
            audit._runtime_content_sha256()
        )
        evidence_path.write_text(json.dumps(mismatched_evidence))
        mismatch_errors = audit.validate_light_inventory(audit.light_inventory())
        self.assertNotIn(
            "light-source evidence runtime content changed since rendered review",
            mismatch_errors,
        )
        self.assertIn(
            "light-source evidence content commit runtime tree disagrees with rendered review",
            mismatch_errors,
        )
        uncommitted.unlink()
        evidence_path.write_text(json.dumps(evidence))

        broken_evidence = json.loads(evidence_path.read_text())
        broken_evidence["render_context"]["content_commit"] = "not-a-commit"
        broken_evidence["render_context"]["inventory_sha256"] = "0" * 64
        broken_evidence["render_context"].pop("ordinary_state")
        broken_evidence["sheets"]["smooth"]["pixel_width"] = 2
        broken_evidence["views"][0]["x"] = 100
        evidence_path.write_text(json.dumps(broken_evidence))
        evidence_errors = audit.validate_light_inventory(audit.light_inventory())
        self.assertIn("light-source evidence needs a content_commit SHA", evidence_errors)
        self.assertIn("light-source evidence needs ordinary_state", evidence_errors)
        self.assertIn(
            "light-source evidence inventory changed since rendered review",
            evidence_errors,
        )
        self.assertIn(
            "light-source evidence sheet smooth dimensions changed",
            evidence_errors,
        )
        self.assertIn(
            "map maps/scene emitter light2 at 4,5 lacks smooth runtime evidence",
            evidence_errors,
        )
        evidence_path.write_text(json.dumps(evidence))

        scene_path = self.root / "maps/scene"
        scene_source = scene_path.read_text()
        scene_path.write_text(scene_source + "# runtime tree changed\n")
        self.assertIn(
            "light-source evidence runtime content changed since rendered review",
            audit.validate_light_inventory(audit.light_inventory()),
        )
        scene_path.write_text(scene_source)

        archetype_path = self.root / "arch/lights.arc"
        archetype_source = archetype_path.read_text()
        archetype_path.write_text(archetype_source.replace("glow_radius 4", "glow_radius 5"))
        self.assertIn(
            "archetype colored_lamp changed since its lighting review",
            audit.validate_light_inventory(audit.light_inventory()),
        )
        archetype_path.write_text(archetype_source)

        scene_path = self.root / "maps/scene"
        scene_path.write_text(
            scene_path.read_text()
            .replace("x 6\n", "x 8\n")
            .replace("light_color 4060ff\n", "")
        )
        errors = audit.validate_light_inventory(audit.light_inventory())
        self.assertIn(
            "map maps/scene changed since its lighting review",
            errors,
        )

    def test_light_inventory_preserves_black_and_marks_faceless_emitters_invisible(self):
        self.write(
            "arch/lights.arc",
            """Object black_light
face black_light.101
glow_radius 2
light_color 000000
end
Object faceless_satellite
glow_radius 2
end
""",
        )
        self.write(
            "maps/coordinates",
            """arch map
name Coordinate Defaults
end
arch black_light
end
arch black_light
x 2
end
arch black_light
y 3
end
arch inert
x 7
y 8
arch black_light
end
end
""",
        )

        report = audit.light_inventory()
        rows = {row["id"]: row for row in report["archetypes"]}

        self.assertEqual("000000", rows["black_light"]["color"])
        self.assertEqual("explicit-color", rows["black_light"]["disposition"])
        self.assertFalse(rows["faceless_satellite"]["visible"])
        self.assertEqual(
            [(0, 0), (2, 0), (0, 3), (7, 8)],
            [(row["x"], row["y"]) for row in report["maps"][0]["emitters"]],
        )

    def test_light_inventory_includes_toggle_active_type_74_state(self):
        self.write(
            "arch/toggle.arc",
            """Object toggle_lamp
face lamp_lit.101
animation lamp_lit
type 74
anim_speed 4
last_sp 5
light_color ffc080
end
Object toggle_lamp_unlit
face lamp_unlit.101
animation lamp_unlit
type 74
anim_speed 4
last_sp 5
light_color ffc080
end
""",
        )
        self.write(
            "maps/toggle",
            """arch map
name Toggle Lamp
end
arch toggle_lamp
face lamp_unlit.101
animation lamp_unlit
x 3
y 4
end
""",
        )
        self.write(
            "arch/toggle.art",
            """artifact toggle_prize
def_arch toggle_lamp
Object
face prize_unlit.101
animation prize_unlit
end
""",
        )

        report = audit.light_inventory()

        source = report["archetypes"][0]
        self.assertEqual("toggle-active", source["activation"])
        self.assertEqual(5, source["radius"])
        self.assertEqual("last_sp", source["radius_source"]["field"])
        self.assertEqual("toggle_lamp", source["activation_archetype"])
        self.assertEqual("lamp_lit.101", source["active_face"])
        self.assertEqual("lamp_lit", source["active_animation"])
        self.assertEqual("archetype", source["active_animation_source"]["kind"])
        emitter = report["maps"][0]["emitters"][0]
        self.assertEqual("toggle-active", emitter["activation"])
        self.assertEqual((3, 4), (emitter["x"], emitter["y"]))
        self.assertEqual("archetype", emitter["radius_source"]["kind"])
        self.assertEqual("light_color", emitter["color_source"]["field"])
        self.assertEqual("lamp_unlit.101", emitter["face"])
        self.assertEqual("lamp_unlit", emitter["animation"])
        self.assertEqual("lamp_lit.101", emitter["active_face"])
        self.assertEqual("lamp_lit", emitter["active_animation"])
        self.assertEqual("archetype", emitter["active_animation_source"]["kind"])
        self.assertEqual("map", emitter["activation_archetype_source"]["kind"])
        self.assertEqual("arch", emitter["activation_archetype_source"]["field"])
        artifact = report["artifacts"][0]
        self.assertEqual("prize_unlit.101", artifact["face"])
        self.assertEqual("prize_unlit", artifact["animation"])
        self.assertEqual("lamp_lit.101", artifact["active_face"])
        self.assertEqual("lamp_lit", artifact["active_animation"])
        self.assertEqual(
            "artifact", artifact["activation_archetype_source"]["kind"]
        )
        self.assertEqual(
            "def_arch", artifact["activation_archetype_source"]["field"]
        )
        self.assertEqual(2, len(report["toggle_states"]))
        states = {
            row["activation_archetype"]: row for row in report["toggle_states"]
        }
        active_lamp = states["toggle_lamp"]
        self.assertEqual("lamp_lit.101", active_lamp["face"])
        self.assertEqual("lamp_lit", active_lamp["animation"])
        self.assertEqual("archetype", active_lamp["animation_source"]["kind"])
        self.assertEqual(
            {"archetype", "artifact", "map"},
            {row["kind"] for row in active_lamp["sources"]},
        )
        standalone = states["toggle_lamp_unlit"]
        self.assertEqual("lamp_unlit.101", standalone["face"])
        self.assertEqual("lamp_unlit", standalone["animation"])
        self.assertEqual(
            [{"kind": "archetype", "id": "toggle_lamp_unlit"}],
            standalone["sources"],
        )

        clean_errors = audit.validate_light_inventory(report)
        self.assertFalse(
            [error for error in clean_errors if "provenance" in error],
            clean_errors,
        )
        broken = json.loads(json.dumps(report))
        broken["maps"][0]["emitters"][0]["active_animation_source"] = None
        broken["toggle_states"][0]["activation_archetype"] = None
        errors = audit.validate_light_inventory(broken)
        self.assertIn(
            "map emitter maps/toggle:4 has invalid active_animation provenance",
            errors,
        )
        self.assertTrue(
            any(error.endswith("lacks an activation archetype") for error in errors),
            errors,
        )

    def test_allowed_none_artifact_is_a_registered_runtime_archetype(self):
        self.write(
            "arch/toggle.arc",
            """Object toggle_lamp
face lamp_lit.101
animation lamp_lit
type 74
anim_speed 4
last_sp 5
light_color ffc080
end
""",
        )
        self.write(
            "maps/quest.art",
            """Allowed none
chance 1
artifact quest_lamp
def_arch toggle_lamp
Object
face quest_lamp.101
animation quest_lamp
end
""",
        )
        self.write(
            "maps/quest",
            """arch map
name Quest Lamp
end
arch quest_lamp
x 6
y 7
end
""",
        )

        report = audit.light_inventory()

        artifact = report["artifacts"][0]
        self.assertEqual("quest_lamp", artifact["runtime_archetype"])
        self.assertEqual("artifact", artifact["runtime_archetype_source"]["field"])
        self.assertEqual("quest_lamp", artifact["activation_archetype"])
        self.assertEqual("quest_lamp.101", artifact["active_face"])
        emitter = report["maps"][0]["emitters"][0]
        self.assertEqual("quest_lamp", emitter["archetype"])
        self.assertEqual((6, 7), (emitter["x"], emitter["y"]))
        self.assertEqual("artifact", emitter["face_source"]["kind"])
        self.assertEqual("quest_lamp", emitter["activation_archetype"])
        self.assertEqual("quest_lamp.101", emitter["active_face"])
        state = next(
            row for row in report["toggle_states"]
            if row["activation_archetype"] == "quest_lamp"
        )
        self.assertEqual(
            {("artifact", "quest_lamp"), ("map", "maps/quest:4")},
            {(row["kind"], row["id"]) for row in state["sources"]},
        )

    def test_allowed_artifact_is_also_a_registered_map_archetype(self):
        self.write(
            "arch/toggle.arc",
            """Object toggle_lamp
face lamp_lit.101
animation lamp_lit
type 74
anim_speed 4
last_sp 5
light_color ffc080
end
""",
        )
        self.write(
            "maps/quest.art",
            """Allowed toggle_lamp
chance 1
artifact quest_lamp
def_arch toggle_lamp
Object
face quest_lamp.101
animation quest_lamp
end
""",
        )
        self.write(
            "maps/quest",
            """arch map
name Quest Lamp
end
arch quest_lamp
x 6
y 7
end
""",
        )

        report = audit.light_inventory()

        artifact = report["artifacts"][0]
        self.assertEqual("toggle_lamp", artifact["runtime_archetype"])
        self.assertEqual("def_arch", artifact["runtime_archetype_source"]["field"])
        self.assertEqual("toggle_lamp", artifact["activation_archetype"])
        self.assertEqual("lamp_lit.101", artifact["active_face"])

        emitter = report["maps"][0]["emitters"][0]
        self.assertEqual("quest_lamp", emitter["archetype"])
        self.assertEqual((6, 7), (emitter["x"], emitter["y"]))
        self.assertEqual("artifact", emitter["face_source"]["kind"])
        self.assertEqual("quest_lamp.101", emitter["face"])
        self.assertEqual("quest_lamp", emitter["activation_archetype"])
        self.assertEqual("quest_lamp.101", emitter["active_face"])
        self.assertEqual("artifact", emitter["active_face_source"]["kind"])
        self.assertEqual("map", emitter["activation_archetype_source"]["kind"])

        states = {
            row["activation_archetype"]: row for row in report["toggle_states"]
        }
        self.assertEqual(
            {
                ("archetype", "toggle_lamp"),
                ("artifact", "quest_lamp"),
            },
            {
                (row["kind"], row["id"])
                for row in states["toggle_lamp"]["sources"]
            },
        )
        self.assertEqual("lamp_lit.101", states["toggle_lamp"]["face"])
        self.assertEqual(
            [{"kind": "map", "id": "maps/quest:4"}],
            states["quest_lamp"]["sources"],
        )
        self.assertEqual("quest_lamp.101", states["quest_lamp"]["face"])

    def test_light_review_check_rejects_missing_baseline_rows(self):
        self.write(
            "arch/light.arc",
            """Object light1
glow_radius 1
sys_object 1
type 78
end
""",
        )

        report = audit.light_inventory()
        errors = audit.validate_light_inventory(report)

        self.assertIn("light-source review must use schema_version 5", errors)
        self.assertIn("light-source review needs a concise review_method", errors)
        self.assertIn("light-source review archetypes must be an object", errors)
        self.assertIn("1 effective light sources remain unreviewed", errors)


if __name__ == "__main__":
    unittest.main()
