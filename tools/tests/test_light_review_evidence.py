"""Tests for deterministic Classic client light-review evidence generation."""

import hashlib
import json
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
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
                "semantic_sha256": "2" * 64,
            }],
            "toggle_states": [{
                "id": "3" * 64,
                "sources": [{"kind": "archetype", "id": "torch"}],
            }],
            "maps": [],
        }

        plan = evidence.source_capture_plan(
            report, "maps/dark", "4" * 64, 12, 13
        )

        self.assertEqual("toggle-dark-control", plan[0]["review_control_id"])
        self.assertEqual("/create torch", plan[1]["runtime_command"])
        self.assertEqual("3" * 64, plan[1]["active_state_id"])
        self.assertEqual("archetype", plan[1]["source_kind"])
        self.assertEqual(
            "/create shield_high of holy_shield", plan[2]["runtime_command"]
        )
        self.assertNotIn("active_state_id", plan[2])

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
                    "semantic_sha256": artifact_semantic,
                }],
                "color_sources": [],
                "toggle_states": [],
                "maps": [{
                    "path": "maps/scene",
                    "semantic_sha256": semantic,
                    "emitters": [{"x": 1, "y": 2, "visible": True}],
                }],
            }
            inventory_path = root / "inventory.json"
            inventory_path.write_text(json.dumps(inventory))
            context_path = root / "context.json"
            context_path.write_text(json.dumps({"content_commit": commit}))
            representatives_path = root / "representatives.json"
            representatives_path.write_text("{}")
            ordinary = {
                "artifact": "scene.png",
                "map": "maps/scene",
                "map_semantic_sha256": semantic,
                "content_commit": commit,
                "sha256": digest,
                "x": 1,
                "y": 2,
            }
            rows = [
                ordinary,
                {
                    **ordinary,
                    "source_kind": "archetype",
                    "source_id": "lamp",
                    "source_semantic_sha256": lamp_semantic,
                    "runtime_command": "/spawn lamp; /screenshot map",
                },
                {
                    **ordinary,
                    "source_kind": "artifact",
                    "source_id": "glowing_reward",
                    "source_semantic_sha256": artifact_semantic,
                    "runtime_command": "/spawn artifact glowing_reward; /screenshot map",
                },
            ]
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
                ["smooth-0002"],
                manifest["source_states"]["archetype:lamp"]["views"],
            )
            self.assertEqual(
                ["smooth-0003"],
                manifest["source_states"]["artifact:glowing_reward"]["views"],
            )
            self.assertNotIn("source_kind", manifest["views"][0])
            self.assertEqual(5, manifest["sheets"]["smooth-001"]["columns"])
            self.assertEqual(5, manifest["sheets"]["smooth-001"]["rows"])
            self.assertEqual(1020, manifest["sheets"]["smooth-001"]["pixel_width"])
            self.assertEqual(765, manifest["sheets"]["smooth-001"]["pixel_height"])

            smooth.write_text(json.dumps([ordinary]))
            args.dry_run = True
            evidence.audit.ROOT = root
            evidence.audit.ARCH_ROOT = root / "arch"
            evidence.audit.MAP_ROOT = root / "maps"
            try:
                with self.assertRaisesRegex(
                    ValueError, "archetype lamp needs a smooth runtime capture"
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
