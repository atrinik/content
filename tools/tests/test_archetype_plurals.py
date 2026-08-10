"""Tests for the reviewed canonical-archetype plural migration."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from tools.archetype_plurals import (
    COMPARISON_PATH,
    LINES,
    MANIFEST_PATH,
    PluralMigrationError,
    audit,
    inventory,
    load_manifest,
    migrate,
    propose_plural,
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

        applied = migrate(self.root, self.manifest, apply=True, check_git=False)
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


if __name__ == "__main__":
    unittest.main()
