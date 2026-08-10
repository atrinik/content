"""Tests for the reviewed canonical-archetype plural migration."""

from __future__ import annotations

import copy
from contextlib import redirect_stderr
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from tools.content_core import ContentCoreError
from tools.archetype_plurals import (
    COMPARISON_PATH,
    LINES,
    MANIFEST_PATH,
    RECOVERY_JOURNAL_PATH,
    REVIEWED_MANIFEST_SHA256,
    PluralMigrationError,
    _assert_comparison_lines,
    _operation_lock,
    audit,
    inventory,
    load_manifest,
    main as plurals_main,
    migrate,
    propose_plural,
    recover,
)


ROOT = Path(__file__).parents[2].resolve()


class ArchetypePluralTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        for directory in ("arch", "maps", "tools"):
            (self.root / directory).mkdir(parents=True)
            (self.root / directory / "COPYING").write_text(
                "fixture license\n", encoding="utf-8"
            )
        shutil.copytree(
            ROOT / "schemas" / "authored-content-v1",
            self.root / "schemas" / "authored-content-v1",
        )
        (self.root / "arch" / "objects.arc").write_text(
            "Object torch\n"
            "name torch\n"
            "type 78\n"
            "end\n"
            "More\n"
            "Object torch_part\n"
            "name continuation\n"
            "type 78\n"
            "end\n"
            "Object fallback\n"
            "type 79\n"
            "end\n",
            encoding="utf-8",
        )
        self.manifest = {
            "schema_version": 1,
            "kind": "archetype-plural-manifest",
            "issue": "atrinik/content#62",
            "lines": LINES,
            "rows": [
                {
                    "archetype_id": "fallback",
                    "singular": "fallback",
                    "object_type": "79",
                    "name_pl": "fallbacks",
                    "classification": "review:object-id-fallback",
                },
                {
                    "archetype_id": "torch",
                    "singular": "torch",
                    "object_type": "78",
                    "name_pl": "torches",
                    "classification": "review:required-issue-vocabulary",
                },
            ],
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_inventory_selects_canonical_definitions_only(self) -> None:
        report = inventory(self.root)

        self.assertEqual(2, report["archetypes"])
        self.assertEqual(1, report["explicit_singulars"])
        self.assertEqual(1, report["object_id_fallbacks"])
        self.assertEqual(1, report["multipart_continuations"])
        self.assertEqual(0, report["with_name_pl"])
        self.assertNotIn("torch_part", {row["archetype_id"] for row in report["rows"]})

    def test_migration_is_dry_run_first_bounded_and_idempotent(self) -> None:
        before = (self.root / "arch" / "objects.arc").read_bytes()
        prepared = migrate(self.root, self.manifest, check_git=False)
        self.assertEqual("prepared", prepared["status"])
        self.assertEqual(2, prepared["operations"])
        self.assertEqual(before, (self.root / "arch" / "objects.arc").read_bytes())

        with mock.patch(
            "tools.archetype_plurals._sync_directory", wraps=lambda path: None
        ) as sync_directory:
            applied = migrate(
                self.root, self.manifest, apply=True, check_git=False
            )
        self.assertIn(
            mock.call((self.root / "arch").resolve()),
            sync_directory.call_args_list,
        )
        self.assertEqual("applied", applied["status"])
        source = (self.root / "arch" / "objects.arc").read_text(encoding="utf-8")
        self.assertIn("name_pl torches\nend\nMore\n", source)
        self.assertIn("name_pl fallbacks\nend\n", source)
        self.assertNotIn("name continuation\nname_pl", source)
        self.assertEqual(2, audit(self.root, self.manifest)["canonical_name_pl"])

        satisfied = migrate(
            self.root, self.manifest, apply=True, check_git=False
        )
        self.assertEqual("already-satisfied", satisfied["status"])
        self.assertFalse(satisfied["applied"])

    def test_partial_divergent_and_catalog_drift_fail_closed(self) -> None:
        path = self.root / "arch" / "objects.arc"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "name torch\n", "name torch\nname_pl torches\n"
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(PluralMigrationError, "partial plural migration"):
            migrate(self.root, self.manifest, check_git=False)

        path.write_text(
            path.read_text(encoding="utf-8").replace("torches", "wrong"),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(PluralMigrationError, "divergent existing"):
            migrate(self.root, self.manifest, check_git=False)

        drifted = copy.deepcopy(self.manifest)
        drifted["rows"][0]["singular"] = "not fallback"
        path.write_text(
            path.read_text(encoding="utf-8").replace("name_pl wrong\n", ""),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(PluralMigrationError, "singular/type drift"):
            migrate(self.root, drifted, check_git=False)

    def test_explicit_recovery_removes_only_reviewed_partial_additions(self) -> None:
        path = self.root / "arch" / "objects.arc"
        original = path.read_bytes()
        artifact_token = "a" * 32
        preserved_artifact = self.root / "arch" / ".preserved-content-stage-a.tmp"
        owned_artifact = (
            self.root
            / "arch"
            / ".owned-content-backup-{}-b.tmp".format(artifact_token)
        )
        preserved_artifact.write_bytes(b"pre-existing")
        owned_artifact.write_bytes(b"interrupted migration")
        journal = self.root / RECOVERY_JOURNAL_PATH
        journal.parent.mkdir(parents=True)
        journal.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "archetype-plural-recovery-journal",
                    "manifest_sha256": REVIEWED_MANIFEST_SHA256,
                    "artifact_token": artifact_token,
                    "preexisting_artifacts": [
                        preserved_artifact.relative_to(self.root).as_posix()
                    ],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "name torch\n", "name torch\nname_pl torches\n"
            ),
            encoding="utf-8",
        )

        prepared = recover(self.root, self.manifest, check_git=False)
        self.assertEqual("prepared", prepared["status"])
        self.assertEqual(1, prepared["archetypes"])
        self.assertNotEqual(original, path.read_bytes())
        self.assertTrue(preserved_artifact.exists())
        self.assertTrue(owned_artifact.exists())
        self.assertTrue(journal.exists())
        concurrent_artifact = (
            self.root / "arch" / ".foreign-content-stage-concurrent.tmp"
        )
        concurrent_artifact.write_bytes(b"foreign transaction")
        recovered = recover(
            self.root, self.manifest, apply=True, check_git=False
        )
        self.assertEqual("recovered", recovered["status"])
        self.assertEqual(original, path.read_bytes())
        self.assertTrue(preserved_artifact.exists())
        self.assertTrue(concurrent_artifact.exists())
        self.assertFalse(owned_artifact.exists())
        self.assertFalse(journal.exists())
        repeated = recover(
            self.root, self.manifest, apply=True, check_git=False
        )
        self.assertEqual("already-recovered", repeated["status"])
        self.assertFalse(repeated["applied"])
        self.assertEqual(
            "prepared", migrate(self.root, self.manifest, check_git=False)["status"]
        )

    def test_publish_failure_after_first_batch_rolls_back_every_file(self) -> None:
        (self.root / "arch" / "objects.arc").unlink()
        rows = []
        for index in range(65):
            archetype_id = "object_{:02d}".format(index)
            (self.root / "arch" / "{}.arc".format(archetype_id)).write_text(
                "Object {}\nname object {}\ntype 79\nend\n".format(
                    archetype_id, index
                ),
                encoding="utf-8",
            )
            rows.append(
                {
                    "archetype_id": archetype_id,
                    "singular": "object {}".format(index),
                    "object_type": "79",
                    "name_pl": "objects {}".format(index),
                    "classification": "review:test",
                }
            )
        manifest = {**self.manifest, "rows": rows}

        with self.assertRaisesRegex(ContentCoreError, "rolled back"):
            migrate(
                self.root,
                manifest,
                apply=True,
                check_git=False,
                publish_failure_after=64,
            )
        self.assertTrue(
            all(
                b"name_pl " not in path.read_bytes()
                for path in (self.root / "arch").glob("*.arc")
            )
        )
        incomplete = ContentCoreError(
            "incomplete rollback", code="transaction-rollback-failed"
        )
        with mock.patch(
            "tools.archetype_plurals.publish_transaction",
            side_effect=incomplete,
        ):
            with self.assertRaisesRegex(ContentCoreError, "incomplete rollback"):
                migrate(self.root, manifest, apply=True, check_git=False)
        self.assertTrue((self.root / RECOVERY_JOURNAL_PATH).exists())

    def test_unapplied_migration_rejects_archetype_source_baseline_drift(self) -> None:
        subprocess.run(
            ["git", "init", "-b", "review-plurals"], cwd=self.root, check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "fixture@example.invalid"],
            cwd=self.root, check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Fixture"], cwd=self.root, check=True,
        )
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        subprocess.run(
            ["git", "commit", "-m", "fixture baseline"], cwd=self.root,
            check=True, capture_output=True,
        )
        baseline = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.root, check=True,
            capture_output=True, text=True,
        ).stdout.strip()
        path = self.root / "arch" / "objects.arc"
        path.write_text(
            path.read_text(encoding="utf-8").replace("type 78\n", "type 78\nweight 1\n"),
            encoding="utf-8",
        )
        coordinates = {
            "fixture": {
                "baseline_sha": baseline,
                "delivery_branch": "review-plurals",
            }
        }
        with mock.patch.dict(LINES, coordinates, clear=True), mock.patch(
            "tools.archetype_plurals.load_manifest", return_value=self.manifest
        ):
            with self.assertRaisesRegex(
                PluralMigrationError, "sources differ from the exact reviewed baseline"
            ):
                migrate(self.root, self.manifest)

    def test_proposals_cover_required_compounds_irregulars_and_labels(self) -> None:
        self.assertEqual(("torches", "review:required-issue-vocabulary"), propose_plural("torch", "78", True))
        self.assertEqual(("burnt out torches", "review:required-issue-vocabulary"), propose_plural("burnt out torch", "78", True))
        self.assertEqual(("bottles of wine", "rule:regular-s"), propose_plural("bottle of wine", "54", True))
        self.assertEqual(("old women", "review:irregular"), propose_plural("old woman", "80", True))
        self.assertEqual(("word of recall", "review:spell-or-skill-label"), propose_plural("word of recall", "29", True))

    def test_committed_review_and_cross_line_proof_are_complete(self) -> None:
        path = ROOT / MANIFEST_PATH
        manifest = load_manifest(path)
        self.assertEqual(
            "6c4eede454e239911049bb87c9ce5f96aeb328d0d11b6d7d9468ffb8c9569660",
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        self.assertEqual(3559, len(manifest["rows"]))
        self.assertEqual(
            53,
            sum(
                row["classification"].startswith("review:object-id-fallback")
                for row in manifest["rows"]
            ),
        )
        required = {
            row["archetype_id"]: row["name_pl"]
            for row in manifest["rows"]
            if row["archetype_id"] in {"torch", "torch_burnt"}
        }
        self.assertEqual(
            {"torch": "torches", "torch_burnt": "burnt out torches"}, required
        )

        comparison = json.loads((ROOT / COMPARISON_PATH).read_text(encoding="utf-8"))
        self.assertEqual(3559, comparison["shared_archetypes"])
        self.assertEqual([], comparison["left_only"])
        self.assertEqual([], comparison["right_only"])
        self.assertEqual([], comparison["differences"])

    def test_manifest_digest_and_comparison_coordinates_fail_closed(self) -> None:
        with _operation_lock(self.root):
            with self.assertRaisesRegex(PluralMigrationError, "another plural"):
                migrate(self.root, self.manifest, check_git=False)

        dry_run_output = self.root / "dry-run.json"
        with redirect_stderr(io.StringIO()):
            self.assertEqual(
                1,
                plurals_main(
                    [
                        "migrate",
                        "--root",
                        str(self.root),
                        "--output",
                        str(dry_run_output),
                    ]
                ),
            )
        self.assertFalse(dry_run_output.exists())

        drifted = self.root / "tools" / "drifted-manifest.json"
        drifted.write_text(
            (ROOT / MANIFEST_PATH).read_text(encoding="utf-8").replace(
                '"name_pl": "torches"', '"name_pl": "wrong"', 1
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(PluralMigrationError, "reviewed digest"):
            load_manifest(drifted)
        alternate = copy.deepcopy(load_manifest(ROOT / MANIFEST_PATH))
        alternate["rows"][0]["name_pl"] = "unreviewed"
        with self.assertRaisesRegex(PluralMigrationError, "repository-owned"):
            migrate(ROOT, alternate)

        for lines in (("main", "main"), ("1.x", "main"), ("1.x", "1.x")):
            with self.assertRaisesRegex(
                PluralMigrationError, "requires main as --root and 1.x"
            ):
                _assert_comparison_lines(*lines)


if __name__ == "__main__":
    unittest.main()
