from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).parents[2].resolve()
sys.path.insert(0, str(ROOT / "maps" / "python"))

import TempleServices


class TempleServicesTest(unittest.TestCase):
    def snapshot(self, count=1, difficulty=1, severity=0, evidence=("x",)):
        return TempleServices.condition(count, difficulty, severity, evidence)

    def test_provider_inventory_is_explicit_and_not_combat_level(self):
        self.assertEqual(len(TempleServices.PROVIDERS), 27)
        self.assertEqual(
            {provider.service_rank for provider in TempleServices.PROVIDERS.values()},
            {20, 40, 60, 100},
        )
        self.assertEqual(TempleServices.PROVIDERS["manzom"].combat_level, 1)
        self.assertEqual(TempleServices.PROVIDERS["manzom"].service_rank, 20)
        self.assertEqual(TempleServices.PROVIDERS["talrain"].combat_level, 115)
        self.assertEqual(TempleServices.PROVIDERS["talrain"].service_rank, 60)
        self.assertEqual(
            TempleServices.provider_for(
                "Talrain", "/shattered_islands/world_9_69"
            ),
            TempleServices.PROVIDERS["talrain"],
        )
        self.assertIsNone(
            TempleServices.provider_for(
                "Talrain", "/shattered_islands/world_0_41"
            )
        )

    def test_newcomer_boundary_and_difficulty_guard(self):
        easy = self.snapshot(difficulty=5)
        self.assertEqual(TempleServices.quote("cure disease", 2, 20, easy).cost, 0)
        self.assertEqual(TempleServices.quote("cure disease", 3, 20, easy).cost, 0)
        self.assertGreater(TempleServices.quote("cure disease", 4, 20, easy).cost, 0)
        hard = self.snapshot(difficulty=6)
        self.assertGreater(TempleServices.quote("cure disease", 3, 20, hard).cost, 0)
        self.assertGreater(TempleServices.quote("remove curse", 1, 20, easy).cost, 0)

    def test_weak_equal_and_strong_provider_quotes(self):
        snapshot = self.snapshot(difficulty=20)
        with self.assertRaisesRegex(ValueError, "incapable"):
            TempleServices.quote("cure disease", 20, 19, snapshot)
        equal = TempleServices.quote("cure disease", 20, 20, snapshot)
        strong = TempleServices.quote("cure disease", 20, 100, snapshot)
        self.assertEqual(equal.cost, 1800)
        self.assertEqual(strong.cost, 1260)
        self.assertLess(strong.cost, equal.cost)

    def test_need_is_monotonic(self):
        lower_patient = TempleServices.quote(
            "cure poison", 4, 40, self.snapshot(difficulty=4)
        )
        higher_patient = TempleServices.quote(
            "cure poison", 10, 40, self.snapshot(difficulty=4)
        )
        harder_condition = TempleServices.quote(
            "cure poison", 10, 40, self.snapshot(difficulty=20)
        )
        self.assertLess(lower_patient.cost, higher_patient.cost)
        self.assertLess(higher_patient.cost, harder_condition.cost)

    def test_rounding_minimum_and_cap(self):
        self.assertEqual(
            TempleServices.bounded_cost(1, 0, 100, 8000), 100
        )
        rounded = TempleServices.quote(
            "cure poison", 4, 20, self.snapshot(difficulty=4)
        )
        self.assertEqual(rounded.cost, 390)
        self.assertEqual(rounded.cost % TempleServices.ROUNDING_UNIT, 0)
        capped = TempleServices.quote(
            "cure poison", 999, 1000, self.snapshot(100, 100)
        )
        self.assertEqual(capped.cost, TempleServices.SERVICES["cure poison"].maximum)

    def test_preview_token_captures_all_quote_inputs(self):
        first = TempleServices.quote(
            "remove depletion", 4, 20,
            self.snapshot(difficulty=5, severity=1, evidence=("str:-1",)),
        )
        same = TempleServices.quote(
            "remove depletion", 4, 20,
            self.snapshot(difficulty=5, severity=1, evidence=("str:-1",)),
        )
        changed = TempleServices.quote(
            "remove depletion", 4, 20,
            self.snapshot(difficulty=10, severity=2, evidence=("str:-2",)),
        )
        self.assertEqual(first.token, same.token)
        self.assertNotEqual(first.token, changed.token)

    def test_no_condition_is_refused(self):
        with self.assertRaisesRegex(ValueError, "no applicable"):
            TempleServices.quote("cure poison", 4, 20, self.snapshot(0, 0))

    def test_treatment_progress(self):
        before = self.snapshot(count=2, difficulty=10, evidence=("a", "b"))
        self.assertEqual(TempleServices.treatment_progress(before, before), "failure")
        self.assertEqual(
            TempleServices.treatment_progress(
                before, self.snapshot(count=1, difficulty=5, evidence=("b",))
            ),
            "partial",
        )
        self.assertEqual(
            TempleServices.treatment_progress(before, self.snapshot(0, 0)),
            "full",
        )

    def test_condition_snapshots_match_spell_boundaries(self):
        class Arch:
            def __init__(self, name):
                self.name = name

        class Obj:
            def __init__(self, arch, obj_type=0, level=1, cursed=False,
                         damned=False, stats=(0, 0, 0, 0, 0)):
                self.arch = Arch(arch)
                self.name = arch
                self.type = obj_type
                self.level = level
                self.f_cursed = cursed
                self.f_damned = damned
                for name, value in zip(
                    ("Str", "Dex", "Con", "Int", "Pow"), stats
                ):
                    setattr(self, name, value)

        objects = [
            Obj("depletion", stats=(-1, 0, -2, 0, 0)),
            Obj("plague", obj_type=99, level=30),
            Obj("poisoning", level=8),
            Obj("ring", level=12, cursed=True),
            Obj("sword", level=18, cursed=True, damned=True),
        ]
        depletion = TempleServices.snapshot("remove depletion", objects, 99)
        self.assertEqual(
            (depletion.count, depletion.severity, depletion.difficulty),
            (1, 3, 15),
        )
        self.assertEqual(TempleServices.snapshot("cure disease", objects, 99).difficulty, 30)
        self.assertEqual(TempleServices.snapshot("cure poison", objects, 99).difficulty, 8)
        self.assertEqual(TempleServices.snapshot("remove curse", objects, 99).difficulty, 18)
        self.assertEqual(TempleServices.snapshot("remove damnation", objects, 99).difficulty, 18)

    def test_execute_treatment_covers_drift_money_and_settlement(self):
        before = self.snapshot(count=2, difficulty=10, evidence=("a", "b"))
        preview = TempleServices.quote("cure disease", 20, 20, before)
        drifted = TempleServices.quote(
            "cure disease", 20, 20,
            self.snapshot(count=2, difficulty=11, evidence=("a", "changed")),
        )
        events = []
        result = TempleServices.execute_treatment(
            preview, drifted, 10000, before,
            lambda: events.append("cast"), lambda: before,
            lambda amount: events.append(("pay", amount)),
        )
        self.assertEqual(result.outcome, "drift")
        self.assertEqual(events, [])

        result = TempleServices.execute_treatment(
            preview, preview, preview.cost - 1, before,
            lambda: events.append("cast"), lambda: before, lambda amount: True,
        )
        self.assertEqual(result.outcome, "insufficient-funds")
        self.assertEqual(events, [])

        result = TempleServices.execute_treatment(
            preview, preview, preview.cost, before,
            lambda: events.append("cast"), lambda: before,
            lambda amount: events.append(("pay", amount)),
        )
        self.assertEqual(result.outcome, "failure")
        self.assertEqual(result.charged, 0)
        self.assertEqual(events, ["cast"])

        after = self.snapshot(count=1, difficulty=5, evidence=("b",))
        result = TempleServices.execute_treatment(
            preview, preview, preview.cost, before,
            lambda: events.append("cast"), lambda: after,
            lambda amount: events.append(("pay", amount)) or True,
        )
        self.assertEqual(result.outcome, "partial")
        self.assertEqual(result.charged, preview.cost)
        self.assertEqual(events[-2:], ["cast", ("pay", preview.cost)])

        result = TempleServices.execute_treatment(
            preview, preview, preview.cost, before,
            lambda: None, lambda: self.snapshot(0, 0), lambda amount: True,
        )
        self.assertEqual(result.outcome, "full")
        self.assertEqual(result.charged, preview.cost)


if __name__ == "__main__":
    unittest.main()
