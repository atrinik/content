"""Tests for deterministic Classic client light-review evidence generation."""

import hashlib
import json
import struct
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
import zlib
from pathlib import Path

from tools import light_review_evidence as evidence


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        [
            "git",
            "-c",
            "user.name=Evidence Test",
            "-c",
            "user.email=evidence-test@example.invalid",
            *args,
        ],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout.strip()


class LightReviewEvidenceTest(unittest.TestCase):
    def test_read_png_composites_classic_rgba_darkness_against_black(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rgba.png"
            raw = b"\x00" + bytes((255, 0, 0, 0, 100, 50, 20, 128))
            data = b"\x89PNG\r\n\x1a\n"
            data += evidence._chunk(
                b"IHDR", struct.pack(">IIBBBBB", 2, 1, 8, 6, 0, 0, 0)
            )
            data += evidence._chunk(b"IDAT", zlib.compress(raw, 9))
            data += evidence._chunk(b"IEND", b"")
            path.write_bytes(data)

            self.assertEqual(
                (2, 1, bytes((0, 0, 0, 50, 25, 10))),
                evidence.read_png(path),
            )

    def test_capture_plan_covers_invisible_emitters_and_representative_maps(self):
        report = {
            "maps": [
                {
                    "path": "maps/invisible",
                    "semantic_sha256": "1" * 64,
                    "emitters": [
                        {"x": 0, "y": 0, "visible": False},
                        {"x": 8, "y": 8, "visible": False},
                        {"x": 20, "y": 20, "visible": False},
                    ],
                },
                {
                    "path": "maps/visible",
                    "semantic_sha256": "2" * 64,
                    "emitters": [{"x": 4, "y": 5, "visible": True}],
                },
            ]
        }

        plan = evidence.capture_plan(report)

        self.assertEqual(
            [
                ("maps/invisible", 0, 0),
                ("maps/invisible", 20, 20),
                ("maps/visible", 4, 5),
            ],
            [(row["map"], row["x"], row["y"]) for row in plan],
        )

    def test_source_capture_plan_binds_definitions_and_toggle_state(self):
        report = {
            "archetypes": [{"id": "torch", "semantic_sha256": "1" * 64}],
            "artifacts": [{
                "id": "holy_shield",
                "archetype": "shield_high",
                "runtime_archetype": "shield_high",
                "semantic_sha256": "2" * 64,
            }, {
                "id": "quest_shield",
                "archetype": "shield_high",
                "runtime_archetype": "quest_shield",
                "semantic_sha256": "4" * 64,
            }],
            "toggle_states": [{
                "id": "3" * 64,
                "sources": [{"kind": "archetype", "id": "torch"}],
            }],
            "maps": [],
        }

        plan = evidence.source_capture_plan(
            report,
            evidence.SOURCE_REVIEW_MAP,
            "4" * 64,
            evidence.SOURCE_REVIEW_X,
            evidence.SOURCE_REVIEW_Y,
        )

        self.assertEqual("toggle-full-control", plan[0]["review_control_id"])
        self.assertEqual("window", plan[0]["capture_surface"])
        self.assertEqual(
            "/tpto /light-source-review/dark-lab 9 9; "
            "verify no carried emitted light; capture full window",
            plan[0]["runtime_command"],
        )
        self.assertEqual(
            "/create torch name issue65_capture; "
            "/console \"noinf::obj=activator.FindObject(name='issue65_capture'); "
            "activator.Apply(obj)",
            plan[1]["runtime_command"],
        )
        self.assertEqual("3" * 64, plan[1]["active_state_id"])
        self.assertEqual("toggle-full-control", plan[1]["review_control_id"])
        self.assertEqual("window", plan[1]["capture_surface"])
        self.assertEqual("archetype", plan[1]["source_kind"])
        self.assertEqual(
            "/console \"noinf::obj=activator.map.CreateObject('shield_high',"
            "activator.x+1,activator.y); obj.Remove(); "
            "obj.Artificate('holy_shield'); obj.speed=0; "
            "obj=activator.map.Insert(obj,activator.x+1,activator.y); "
            "obj.Update()",
            plan[2]["runtime_command"],
        )
        self.assertNotIn("active_state_id", plan[2])
        self.assertEqual("source-map-control", plan[2]["review_control_id"])
        self.assertEqual("map", plan[2]["capture_surface"])
        self.assertEqual(
            "/console \"noinf::obj=activator.map.CreateObject('quest_shield',"
            "activator.x+1,activator.y); obj.speed=0; obj.Update()",
            plan[3]["runtime_command"],
        )
        self.assertEqual("source-map-control", plan[-1]["review_control_id"])
        self.assertEqual("map", plan[-1]["capture_surface"])

    def test_source_capture_plan_spawns_multipart_head_for_satellite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "arch" / "multipart.arc"
            path.parent.mkdir()
            path.write_text(
                "Object explosion\nend\nMore\n"
                "Object explosion_a\nglow_radius 3\nend\nMore\n"
                "Object explosion_b\nglow_radius 3\nend\n"
            )
            report = {
                "archetypes": [
                    {
                        "id": "explosion_a",
                        "path": "arch/multipart.arc",
                        "object_line": 4,
                        "semantic_sha256": "1" * 64,
                    },
                    {
                        "id": "explosion_b",
                        "path": "arch/multipart.arc",
                        "object_line": 8,
                        "semantic_sha256": "2" * 64,
                    },
                ],
                "artifacts": [],
                "toggle_states": [],
                "maps": [],
            }
            original_root = evidence.audit.ROOT
            evidence.audit.ROOT = root
            try:
                plan = evidence.source_capture_plan(
                    report,
                    evidence.SOURCE_REVIEW_MAP,
                    "3" * 64,
                    evidence.SOURCE_REVIEW_X,
                    evidence.SOURCE_REVIEW_Y,
                )
            finally:
                evidence.audit.ROOT = original_root

        expected = (
            "/console \"noinf::obj=activator.map.CreateObject('explosion',"
            "activator.x+1,activator.y); obj.speed=0; obj.Update()"
        )
        self.assertEqual(expected, plan[1]["runtime_command"])
        self.assertEqual(expected, plan[2]["runtime_command"])

    def test_source_plan_rejects_stale_commands_and_coordinates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scene = root / evidence.SOURCE_REVIEW_MAP
            scene.parent.mkdir(parents=True)
            scene.write_text("arch map\nend\n")
            report = {
                "archetypes": [{"id": "lamp", "semantic_sha256": "1" * 64}],
                "artifacts": [],
                "toggle_states": [],
                "maps": [],
            }
            original_root = evidence.audit.ROOT
            evidence.audit.ROOT = root
            try:
                plan = evidence.source_capture_plan(
                    report,
                    evidence.SOURCE_REVIEW_MAP,
                    hashlib.sha256(scene.read_bytes()).hexdigest(),
                    evidence.SOURCE_REVIEW_X,
                    evidence.SOURCE_REVIEW_Y,
                )
                self.assertEqual([], evidence.source_plan_errors(report, plan))
                stale = json.loads(json.dumps(plan))
                stale[1]["runtime_command"] = "/create lamp"
                self.assertIn(
                    "source-plan row ('source', 'archetype', 'lamp') has stale runtime_command",
                    evidence.source_plan_errors(report, stale),
                )
                stale = json.loads(json.dumps(plan))
                stale[1]["x"] = 8
                self.assertIn(
                    "source-plan row ('source', 'archetype', 'lamp') has stale x",
                    evidence.source_plan_errors(report, stale),
                )
                stale = json.loads(json.dumps(plan))
                stale[1]["capture_surface"] = "window"
                self.assertIn(
                    "source-plan row ('source', 'archetype', 'lamp') has stale capture_surface",
                    evidence.source_plan_errors(report, stale),
                )
            finally:
                evidence.audit.ROOT = original_root

    def test_png_round_trip_is_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.png"
            second = Path(directory) / "second.png"
            pixels = bytes((255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 255))

            evidence.write_png(first, 2, 2, pixels)
            evidence.write_png(second, 2, 2, pixels)

            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual((2, 2, pixels), evidence.read_png(first))

    def test_build_validates_captures_and_replaces_stale_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "maps" / "light-source-evidence"
            output.mkdir(parents=True)
            (output / "stale.png").write_bytes(b"stale")
            captures = root / "captures"
            captures.mkdir()
            screenshot = captures / "scene.png"
            evidence.write_png(screenshot, 1024, 768, bytes(1024 * 768 * 3))
            digest = hashlib.sha256(screenshot.read_bytes()).hexdigest()
            light_pixels = bytearray(1024 * 768 * 3)
            for y in range(768 // 3, 768 // 3 + 40):
                start = (y * 1024 + 1024 // 2) * 3
                light_pixels[start:start + 40 * 3] = bytes([12] * 40 * 3)
            lamp_capture = captures / "lamp.png"
            artifact_capture = captures / "artifact.png"
            evidence.write_png(lamp_capture, 1024, 768, bytes(light_pixels))
            for y in range(768 // 3, 768 // 3 + 40):
                start = (y * 1024 + 1024 // 2) * 3
                light_pixels[start:start + 40 * 3] = bytes([18] * 40 * 3)
            evidence.write_png(artifact_capture, 1024, 768, bytes(light_pixels))
            window_control = captures / "window-control.png"
            window_pixels = bytearray(1024 * 768 * 3)
            window_pixels[:3] = b"\x01\x01\x01"
            evidence.write_png(window_control, 1024, 768, bytes(window_pixels))
            semantic = "a" * 64
            lamp_semantic = "c" * 64
            artifact_semantic = "d" * 64
            arch = root / "arch"
            arch.mkdir()
            (arch / "runtime.arc").write_text("Object runtime\nend\n")
            (root / "maps" / "scene").write_text("arch map\nend\n")
            _git(root, "init", "-q")
            _git(root, "add", "arch", "maps/scene")
            _git(root, "commit", "-qm", "fixture runtime tree")
            commit = _git(root, "rev-parse", "HEAD")
            inventory = {
                "archetypes": [{"id": "lamp", "semantic_sha256": lamp_semantic}],
                "artifacts": [{
                    "id": "glowing_reward",
                    "archetype": "shield",
                    "runtime_archetype": "shield",
                    "semantic_sha256": artifact_semantic,
                }],
                "color_sources": [],
                "toggle_states": [],
                "maps": [{
                    "path": "maps/scene",
                    "semantic_sha256": semantic,
                    "emitters": [{
                        "id": "maps/scene:2",
                        "x": 1,
                        "y": 2,
                        "visible": True,
                    }],
                }],
            }
            inventory_path = root / "inventory.json"
            inventory_path.write_text(json.dumps(inventory))
            context_path = root / "context.json"
            context_path.write_text(json.dumps({"content_commit": commit}))
            representatives_path = root / "representatives.json"
            representatives_path.write_text("{}")
            review_scene = root / evidence.SOURCE_REVIEW_MAP
            review_scene.parent.mkdir(parents=True)
            review_scene.write_text("arch map\nend\n")
            ordinary = {
                "artifact": "scene.png",
                "map": "maps/scene",
                "map_semantic_sha256": semantic,
                "content_commit": commit,
                "sha256": digest,
                "x": 1,
                "y": 2,
            }
            source_plan = evidence.source_capture_plan(
                inventory,
                evidence.SOURCE_REVIEW_MAP,
                hashlib.sha256(review_scene.read_bytes()).hexdigest(),
                evidence.SOURCE_REVIEW_X,
                evidence.SOURCE_REVIEW_Y,
            )
            source_artifacts = (
                "window-control.png",
                "lamp.png",
                "artifact.png",
                "scene.png",
            )
            source_rows = []
            for planned, artifact_name in zip(source_plan, source_artifacts):
                artifact_path = captures / artifact_name
                source_rows.append({
                    **{key: value for key, value in planned.items() if key != "number"},
                    "artifact": artifact_name,
                    "content_commit": commit,
                    "sha256": hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
                })
            rows = [ordinary, *source_rows]
            smooth = captures / "smooth.json"
            discrete = captures / "discrete.json"
            smooth.write_text(json.dumps(rows))
            discrete.write_text(json.dumps([ordinary]))
            args = SimpleNamespace(
                inventory=inventory_path,
                smooth_manifest=smooth,
                discrete_manifest=discrete,
                context=context_path,
                representatives=representatives_path,
                output=output,
                dry_run=False,
            )
            original_roots = (
                evidence.audit.ROOT,
                evidence.audit.ARCH_ROOT,
                evidence.audit.MAP_ROOT,
            )
            evidence.audit.ROOT = root
            evidence.audit.ARCH_ROOT = root / "arch"
            evidence.audit.MAP_ROOT = root / "maps"
            try:
                result = evidence.build_evidence(args)
                runtime_digest = evidence.audit._runtime_content_sha256()
            finally:
                (
                    evidence.audit.ROOT,
                    evidence.audit.ARCH_ROOT,
                    evidence.audit.MAP_ROOT,
                ) = original_roots

            self.assertEqual(2, result["sheets"])
            self.assertFalse((output / "stale.png").exists())
            self.assertTrue((output / "smooth-001.png").is_file())
            self.assertEqual(
                (1020, 765), evidence.validate_png(output / "smooth-001.png")
            )
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(2, manifest["schema_version"])
            self.assertEqual(
                runtime_digest, manifest["render_context"]["runtime_content_sha256"]
            )
            self.assertEqual(
                ["smooth-0003"],
                manifest["source_states"]["archetype:lamp"]["views"],
            )
            self.assertEqual(
                ["smooth-0004"],
                manifest["source_states"]["artifact:glowing_reward"]["views"],
            )
            self.assertNotIn("source_kind", manifest["views"][0])
            self.assertEqual(5, manifest["sheets"]["smooth-001"]["columns"])
            self.assertEqual(5, manifest["sheets"]["smooth-001"]["rows"])
            self.assertEqual(1020, manifest["sheets"]["smooth-001"]["pixel_width"])
            self.assertEqual(765, manifest["sheets"]["smooth-001"]["pixel_height"])

            original_lamp = lamp_capture.read_bytes()
            lamp_capture.write_bytes(screenshot.read_bytes())
            source_rows[1]["sha256"] = hashlib.sha256(
                lamp_capture.read_bytes()
            ).hexdigest()
            smooth.write_text(json.dumps(rows))
            args.dry_run = True
            evidence.audit.ROOT = root
            evidence.audit.ARCH_ROOT = root / "arch"
            evidence.audit.MAP_ROOT = root / "maps"
            try:
                with self.assertRaisesRegex(
                    ValueError, "source capture lacks a visible light pool"
                ):
                    evidence.build_evidence(args)
            finally:
                (
                    evidence.audit.ROOT,
                    evidence.audit.ARCH_ROOT,
                    evidence.audit.MAP_ROOT,
                ) = original_roots
            lamp_capture.write_bytes(original_lamp)
            source_rows[1]["sha256"] = hashlib.sha256(
                lamp_capture.read_bytes()
            ).hexdigest()
            smooth.write_text(json.dumps(rows))

            smooth.write_text(json.dumps([ordinary]))
            evidence.audit.ROOT = root
            evidence.audit.ARCH_ROOT = root / "arch"
            evidence.audit.MAP_ROOT = root / "maps"
            try:
                with self.assertRaisesRegex(
                    ValueError, "missing source-plan row"
                ):
                    evidence.build_evidence(args)
            finally:
                (
                    evidence.audit.ROOT,
                    evidence.audit.ARCH_ROOT,
                    evidence.audit.MAP_ROOT,
                ) = original_roots

            smooth.write_text(json.dumps(rows))
            context_path.write_text(json.dumps({"content_commit": "0" * 40}))
            evidence.audit.ROOT = root
            evidence.audit.ARCH_ROOT = root / "arch"
            evidence.audit.MAP_ROOT = root / "maps"
            try:
                with self.assertRaisesRegex(
                    ValueError, "render-context content commit does not resolve"
                ):
                    evidence.build_evidence(args)
            finally:
                (
                    evidence.audit.ROOT,
                    evidence.audit.ARCH_ROOT,
                    evidence.audit.MAP_ROOT,
                ) = original_roots

            context_path.write_text(json.dumps({"content_commit": commit}))
            uncommitted = arch / "post-render.arc"
            uncommitted.write_text("Object post_render\nend\n")
            evidence.audit.ROOT = root
            evidence.audit.ARCH_ROOT = root / "arch"
            evidence.audit.MAP_ROOT = root / "maps"
            try:
                with self.assertRaisesRegex(
                    ValueError,
                    "render-context content_commit runtime tree disagrees with captures",
                ):
                    evidence.build_evidence(args)
            finally:
                (
                    evidence.audit.ROOT,
                    evidence.audit.ARCH_ROOT,
                    evidence.audit.MAP_ROOT,
                ) = original_roots
                uncommitted.unlink()

            rows[0]["sha256"] = "0" * 64
            smooth.write_text(json.dumps(rows))
            evidence.audit.ROOT = root
            evidence.audit.ARCH_ROOT = root / "arch"
            evidence.audit.MAP_ROOT = root / "maps"
            try:
                with self.assertRaisesRegex(ValueError, "capture digest changed"):
                    evidence.build_evidence(args)
            finally:
                (
                    evidence.audit.ROOT,
                    evidence.audit.ARCH_ROOT,
                    evidence.audit.MAP_ROOT,
                ) = original_roots


if __name__ == "__main__":
    unittest.main()
