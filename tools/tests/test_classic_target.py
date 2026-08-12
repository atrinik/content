"""Tests for the explicit Classic runtime target published from main."""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.build_runtime import (
    CLASSIC_TARGET,
    create_manifest,
    load_target_contract,
    validate_classic_source_coordinate,
)


ROOT = Path(__file__).parents[2]


class ClassicTargetTest(unittest.TestCase):
    def test_contract_identifies_main_without_claiming_replacement_readiness(self):
        contract = load_target_contract(ROOT, CLASSIC_TARGET)

        self.assertEqual("atrinik/content", contract["repository"])
        self.assertEqual("main", contract["branch"])
        self.assertEqual("classic-ads-v1", contract["content_format"])
        self.assertFalse(contract["replacement_ready"])
        self.assertFalse(contract["replacement_toolkit_package"])

    def test_schema_two_manifest_binds_target_payload_and_licenses(self):
        contract = load_target_contract(ROOT, CLASSIC_TARGET)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            (output / "maps").mkdir()
            (output / "maps" / "world").write_text("map\n", encoding="utf-8")
            license_path = output / "attribution" / "maps" / "COPYING"
            license_path.parent.mkdir(parents=True)
            license_path.write_text("license\n", encoding="utf-8")

            create_manifest(output, "1" * 40, contract, "2.14.0")
            manifest = json.loads(
                (output / "manifest.json").read_text(encoding="utf-8")
            )

        self.assertEqual(2, manifest["schema_version"])
        self.assertEqual("classic", manifest["target"])
        self.assertEqual(
            {
                "repository": "atrinik/content",
                "branch": "main",
                "commit": "1" * 40,
            },
            manifest["source"],
        )
        self.assertEqual("2.14.0", manifest["release_version"])
        self.assertEqual(
            ["attribution/maps/COPYING"],
            [entry["path"] for entry in manifest["license_files"]],
        )
        self.assertEqual(
            ["attribution/maps/COPYING", "maps/world"],
            [entry["path"] for entry in manifest["files"]],
        )

    def test_coordinate_validation_rejects_mismatch_and_dirty_checkout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(
                ["git", "-C", str(root), "config", "user.name", "Test"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(root), "config", "user.email", "test@example.invalid"],
                check=True,
            )
            source = root / "source"
            source.write_text("clean\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "source"], check=True)
            subprocess.run(
                ["git", "-C", str(root), "commit", "-qm", "test: baseline"],
                check=True,
            )
            commit = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()

            validate_classic_source_coordinate(root, commit)
            with self.assertRaisesRegex(ValueError, "does not match"):
                validate_classic_source_coordinate(root, "0" * 40)

            source.write_text("dirty\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "clean source checkout"):
                validate_classic_source_coordinate(root, commit)


if __name__ == "__main__":
    unittest.main()
