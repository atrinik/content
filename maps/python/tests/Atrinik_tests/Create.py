import unittest

import Atrinik
from tests import TestSuite, create_test_map


class CreateCommandSuite(TestSuite):
    def setUp(self):
        super().setUp()
        self.map = create_test_map(24, 24, self.id())
        self.pl = activator.Controller()
        self.map.Insert(activator, 0, 0)
        self.added_permissions = []
        for permission in ("create", "[OP]"):
            if permission not in self.pl.cmd_permissions:
                self.pl.cmd_permissions.append(permission)
                self.added_permissions.append(permission)

    def tearDown(self):
        for obj in list(self.map.Objects(0, 0)):
            if obj != activator and obj.arch.name == "raas":
                obj.Destroy()

        for permission in self.added_permissions:
            self.pl.cmd_permissions.remove(permission)
        super().tearDown()

    def test_monster_randomitems(self):
        self.pl.s_packets.clear()
        self.pl.ExecuteCommand("/create raas randomitems random_coin")

        monsters = [obj for obj in self.map.Objects(0, 0)
                    if obj != activator and obj.arch.name == "raas"]
        self.assertEqual(len(monsters), 1)
        self.assertTrue(monsters[0].inv)
        self.assertTrue(any(item.type == Atrinik.Type.MONEY
                            for item in monsters[0].inv))

        packet = b"".join(self.pl.s_packets)
        self.assertNotIn(b"Traceback", packet)
        self.assertNotIn(b"CreateTreasure cannot generate persistent", packet)


activator = Atrinik.WhoIsActivator()
me = Atrinik.WhoAmI()
suites = [
    unittest.TestLoader().loadTestsFromTestCase(CreateCommandSuite),
]
