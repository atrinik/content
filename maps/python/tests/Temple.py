import unittest

import Atrinik
from Temple import Temple
import TempleServices
from tests import TestSuite


class TempleSuite(TestSuite):
    def setUp(self):
        super().setUp()
        self.npc = activator.map.CreateObject(
            "cleric_white_red", activator.x, activator.y
        )
        self.provider = None
        self.npc.level = 68
        self.created = []

    def tearDown(self):
        for obj in reversed(self.created):
            if obj:
                obj.Destroy()
        if self.npc:
            self.npc.Destroy()
        super().tearDown()

    def create(self, archname):
        obj = activator.CreateObject(archname)
        self.created.append(obj)
        return obj

    def fund(self):
        coin = self.create("goldcoin")
        coin.nrof = 1000
        return coin

    def quote(self, service_name):
        temple = Temple(activator, self.npc)
        if self.provider is not None:
            temple._provider = lambda: self.provider
        else:
            temple._provider = lambda: TempleServices.PROVIDERS[
                "archbishop-theodorus-iii"
            ]
        provider, before, current = temple._current_quote(service_name)
        return temple, provider, before, current

    def test_live_depletion_success_charges_after_effect_and_restores_rank(self):
        depletion = self.create("depletion")
        depletion.Str = -2
        self.fund()
        money = activator.GetMoney()
        temple, provider, before, current = self.quote("remove depletion")

        temple._confirm(
            "remove depletion", current.token, provider, before, current
        )

        self.assertFalse(depletion)
        self.assertEqual(money - activator.GetMoney(), current.cost)
        self.assertEqual(self.npc.level, 68)

        money = activator.GetMoney()
        repeated = Temple(activator, self.npc)
        repeated._provider = lambda: provider
        repeated.dialog("buy remove depletion|" + current.token)
        self.assertEqual(activator.GetMoney(), money)
        self.assertIn("do not have a condition", repeated._msg)

    def test_quote_drift_does_not_cast_or_charge(self):
        depletion = self.create("depletion")
        depletion.Str = -2
        self.fund()
        money = activator.GetMoney()
        temple, provider, before, current = self.quote("remove depletion")
        depletion.Str = -3
        quoted = temple._current_quote("remove depletion")

        temple._confirm(
            "remove depletion", current.token, provider, quoted[1], quoted[2]
        )

        self.assertTrue(depletion)
        self.assertEqual(depletion.Str, -3)
        self.assertEqual(activator.GetMoney(), money)
        self.assertIn("changed before confirmation", temple._msg)

    def test_insufficient_funds_does_not_cast(self):
        depletion = self.create("depletion")
        depletion.Str = -2
        temple, provider, before, current = self.quote("remove depletion")
        self.assertGreater(current.cost, 0)

        temple._confirm(
            "remove depletion", current.token, provider, before, current
        )

        self.assertTrue(depletion)
        self.assertEqual(activator.GetMoney(), 0)
        self.assertIn("not have enough money", temple._msg)

    def test_total_failure_is_free_and_partial_success_uses_exact_quote(self):
        first = self.create("sword")
        first.level = 5
        first.f_cursed = True
        second = self.create("dagger")
        second.level = 10
        second.f_cursed = True
        self.fund()

        temple, provider, before, current = self.quote("remove curse")
        money = activator.GetMoney()
        temple._cast = lambda provider, service_name: None
        temple._confirm("remove curse", current.token, provider, before, current)
        self.assertEqual(activator.GetMoney(), money)
        self.assertTrue(first.f_cursed)
        self.assertTrue(second.f_cursed)
        self.assertIn("no effect", temple._msg)

        temple, provider, before, current = self.quote("remove curse")
        temple._cast = lambda provider, service_name: setattr(
            first, "f_cursed", False
        )
        temple._confirm("remove curse", current.token, provider, before, current)
        self.assertEqual(money - activator.GetMoney(), current.cost)
        self.assertFalse(first.f_cursed)
        self.assertTrue(second.f_cursed)
        self.assertIn("some of the condition remains", temple._msg)

    def test_incapable_provider_refuses_high_level_curse(self):
        self.provider = TempleServices.PROVIDERS["brelend-lee"]
        item = self.create("sword")
        item.level = 21
        item.f_cursed = True
        temple = Temple(activator, self.npc)
        temple._provider = lambda: self.provider

        self.assertIsNone(temple._current_quote("remove curse"))
        self.assertTrue(item.f_cursed)
        self.assertIn("cannot reliably treat", temple._msg)


activator = Atrinik.WhoIsActivator()
suites = [unittest.TestLoader().loadTestsFromTestCase(TempleSuite)]
