from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.scripted_gameplay_audit import (
    MANIFEST_PATH,
    ScriptedGameplayAuditError,
    discover_metric_sites,
    load_and_validate,
)


ROOT = Path(__file__).resolve().parents[2]


class ScriptedGameplayAuditTests(unittest.TestCase):
    def test_repository_inventory_is_exact_and_reviewed(self):
        report = load_and_validate(ROOT)
        self.assertEqual(26, report["metric_sites"])
        self.assertEqual(24, report["metric_identities"])
        self.assertEqual(1, report["audit_like_sites"])

    def test_unreviewed_metric_site_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "maps" / "python" / "feature.py"
            source.parent.mkdir(parents=True)
            source.write_text('player.MetricAdd("economy.new_action")\n', encoding="utf-8")
            manifest = {
                "schema_version": 1,
                "metric_sites": [{
                    "path": "maps/python/feature.py",
                    "method": "MetricAdd",
                    "metric": "economy.other_action",
                    "count": 1,
                    "classification": "aggregate-only",
                    "journal_reason": None,
                    "event_rate": "bounded",
                    "rationale": "fixture",
                }],
                "audit_like_sites": [],
            }
            target = root / MANIFEST_PATH
            target.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ScriptedGameplayAuditError, "unreviewed"):
                load_and_validate(root)

    def test_dynamic_metric_identity_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "maps" / "python" / "feature.py"
            source.parent.mkdir(parents=True)
            source.write_text("player.MetricAdd(metric_name)\n", encoding="utf-8")
            with self.assertRaisesRegex(ScriptedGameplayAuditError, "dynamic metric identity"):
                discover_metric_sites(root)

    def test_journal_classification_requires_bounded_reason(self):
        document = json.loads((ROOT / MANIFEST_PATH).read_text(encoding="utf-8"))
        document["metric_sites"][0]["journal_reason"] = "player supplied text"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "maps" / "python").mkdir(parents=True)
            for source in (ROOT / "maps" / "python").rglob("*.py"):
                relative = source.relative_to(ROOT)
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())
            target = root / MANIFEST_PATH
            target.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ScriptedGameplayAuditError, "bounded journal reason"):
                load_and_validate(root)


if __name__ == "__main__":
    unittest.main()
