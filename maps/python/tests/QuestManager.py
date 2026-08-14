import time
import unittest
from collections import OrderedDict
from unittest import mock

import Atrinik
from tests import TestSuite
from QuestManager import QuestManager


class QuestManagerSuite(TestSuite):
    maxDiff = None

    def test_01(self):
        quest = {
            "parts": OrderedDict((("deliver", {
                "info": "",
                "item": {
                    "arch": "sword",
                    "name": "quest sword",
                },
                "uid": "deliver",
                "name": "Delivery",
            }),)),
            "name": "Test Quest",
            "uid": "test_quest",
        }
        qm = QuestManager(activator, quest)
        self.assertFalse(qm.started("deliver"))
        self.assertFalse(qm.finished("deliver"))
        self.assertFalse(qm.completed("deliver"))
        self.assertFalse(qm.completed())
        self.assertTrue(qm.need_start("deliver"))
        self.assertFalse(qm.need_finish("deliver"))
        self.assertFalse(qm.need_complete("deliver"))
        self.assertFalse(qm.need_complete_before_start("deliver"))
        self.assertRaises(AssertionError, qm.complete, "deliver")
        qm.start("deliver")
        self.assertEqual(
            qm.get_quest_status(), Atrinik.QUEST_STATUS_STARTED
        )
        self.assertTrue(qm.started("deliver"))
        self.assertFalse(qm.finished("deliver"))
        self.assertFalse(qm.completed("deliver"))
        self.assertFalse(qm.completed())
        self.assertFalse(qm.need_start("deliver"))
        self.assertTrue(qm.need_finish("deliver"))
        self.assertFalse(qm.need_complete("deliver"))
        self.assertFalse(qm.need_complete_before_start("deliver"))
        sword = activator.CreateObject("sword")
        self.assertTrue(qm.started("deliver"))
        self.assertFalse(qm.finished("deliver"))
        self.assertFalse(qm.completed("deliver"))
        self.assertFalse(qm.completed())
        self.assertFalse(qm.need_start("deliver"))
        self.assertTrue(qm.need_finish("deliver"))
        self.assertFalse(qm.need_complete("deliver"))
        self.assertFalse(qm.need_complete_before_start("deliver"))
        sword.name = "quest sword"
        self.assertTrue(qm.started("deliver"))
        self.assertTrue(qm.finished("deliver"))
        self.assertFalse(qm.completed("deliver"))
        self.assertFalse(qm.completed())
        self.assertFalse(qm.need_start("deliver"))
        self.assertFalse(qm.need_finish("deliver"))
        self.assertTrue(qm.need_complete("deliver"))
        self.assertFalse(qm.need_complete_before_start("deliver"))
        qm.complete("deliver")
        self.assertFalse(sword)
        self.assertTrue(qm.started("deliver"))
        self.assertFalse(qm.finished("deliver"))
        self.assertTrue(qm.completed("deliver"))
        self.assertTrue(qm.completed())
        self.assertFalse(qm.need_start("deliver"))
        self.assertFalse(qm.need_finish("deliver"))
        self.assertFalse(qm.need_complete("deliver"))
        self.assertFalse(qm.need_complete_before_start("deliver"))

    def test_02(self):
        quest = {
            "parts": OrderedDict((("deliver", {
                "info": "",
                "item": {
                    "arch": "torch",
                    "name": "quest torch",
                    "nrof": 50,
                },
                "uid": "deliver",
                "name": "Delivery",
            }),)),
            "name": "Test Quest",
            "uid": "test_quest",
        }
        qm = QuestManager(activator, quest)
        self.assertFalse(qm.started("deliver"))
        self.assertFalse(qm.finished("deliver"))
        self.assertFalse(qm.completed("deliver"))
        self.assertFalse(qm.completed())
        torch = activator.CreateObject("torch")
        torch.name = "quest torch"
        self.assertFalse(qm.started("deliver"))
        self.assertFalse(qm.finished("deliver"))
        self.assertFalse(qm.completed("deliver"))
        self.assertFalse(qm.completed())
        self.assertTrue(qm.need_start("deliver"))
        self.assertFalse(qm.need_finish("deliver"))
        self.assertFalse(qm.need_complete("deliver"))
        self.assertFalse(qm.need_complete_before_start("deliver"))
        torch.nrof = 50
        self.assertFalse(qm.started("deliver"))
        self.assertTrue(qm.finished("deliver"))
        self.assertFalse(qm.completed("deliver"))
        self.assertFalse(qm.completed())
        self.assertTrue(qm.need_start("deliver"))
        self.assertFalse(qm.need_finish("deliver"))
        self.assertFalse(qm.need_complete("deliver"))
        self.assertTrue(qm.need_complete_before_start("deliver"))
        qm.start("deliver")
        self.assertTrue(qm.started("deliver"))
        self.assertTrue(qm.finished("deliver"))
        self.assertFalse(qm.completed("deliver"))
        self.assertFalse(qm.completed())
        self.assertFalse(qm.need_start("deliver"))
        self.assertFalse(qm.need_finish("deliver"))
        self.assertTrue(qm.need_complete("deliver"))
        self.assertFalse(qm.need_complete_before_start("deliver"))
        qm.complete("deliver")
        self.assertFalse(torch)
        self.assertTrue(qm.started("deliver"))
        self.assertFalse(qm.finished("deliver"))
        self.assertTrue(qm.completed("deliver"))
        self.assertTrue(qm.completed())
        self.assertFalse(qm.need_start("deliver"))
        self.assertFalse(qm.need_finish("deliver"))
        self.assertFalse(qm.need_complete("deliver"))
        self.assertFalse(qm.need_complete_before_start("deliver"))

    def test_03(self):
        quest = {
            "parts": OrderedDict((("kill", {
                "info": "",
                "kill": {"nrof": 2},
                "uid": "kill",
                "name": "Killing",
            }),)),
            "name": "Test Quest",
            "uid": "test_quest",
        }
        qm = QuestManager(activator, quest)
        self.assertFalse(qm.started("kill"))
        self.assertFalse(qm.finished("kill"))
        self.assertFalse(qm.completed("kill"))
        self.assertFalse(qm.completed())
        self.assertTrue(qm.need_start("kill"))
        self.assertFalse(qm.need_finish("kill"))
        self.assertFalse(qm.need_complete("kill"))
        self.assertFalse(qm.need_complete_before_start("kill"))
        self.assertRaises(AssertionError, qm.complete, "kill")
        qm.start("kill")
        self.assertTrue(qm.started("kill"))
        self.assertFalse(qm.finished("kill"))
        self.assertFalse(qm.completed("kill"))
        self.assertFalse(qm.completed())
        self.assertFalse(qm.need_start("kill"))
        self.assertTrue(qm.need_finish("kill"))
        self.assertFalse(qm.need_complete("kill"))
        self.assertFalse(qm.need_complete_before_start("kill"))

        def create_raas():
            obj = activator.map.CreateObject("raas", activator.x, activator.y)
            quest_container = obj.CreateObject("quest_container")
            quest_container.name = "test_quest"
            quest_object = quest_container.CreateObject("quest_container")
            quest_object.name = "kill"
            quest_object.sub_type = Atrinik.QUEST_TYPE_KILL
            obj.Update()
            return obj

        raas = create_raas()
        activator.Hit(raas, -1)
        self.assertTrue(qm.started("kill"))
        self.assertFalse(qm.finished("kill"))
        self.assertFalse(qm.completed("kill"))
        self.assertFalse(qm.completed())
        self.assertFalse(qm.need_start("kill"))
        self.assertTrue(qm.need_finish("kill"))
        self.assertFalse(qm.need_complete("kill"))
        self.assertFalse(qm.need_complete_before_start("kill"))
        raas = create_raas()
        activator.Hit(raas, -1)
        self.assertTrue(qm.started("kill"))
        self.assertTrue(qm.finished("kill"))
        self.assertFalse(qm.completed("kill"))
        self.assertFalse(qm.completed())
        self.assertFalse(qm.need_start("kill"))
        self.assertFalse(qm.need_finish("kill"))
        self.assertTrue(qm.need_complete("kill"))
        self.assertFalse(qm.need_complete_before_start("kill"))
        qm.complete("kill")
        self.assertTrue(qm.started("kill"))
        self.assertTrue(qm.finished("kill"))
        self.assertTrue(qm.completed("kill"))
        self.assertTrue(qm.completed())
        self.assertFalse(qm.need_start("kill"))
        self.assertFalse(qm.need_finish("kill"))
        self.assertFalse(qm.need_complete("kill"))
        self.assertFalse(qm.need_complete_before_start("kill"))

    def test_04(self):
        quest = {
            "parts": OrderedDict((("special", {
                "info": "",
                "uid": "special",
                "name": "Special",
            }),)),
            "name": "Test Quest",
            "uid": "test_quest",
        }
        qm = QuestManager(activator, quest)
        self.assertFalse(qm.started("special"))
        self.assertTrue(qm.finished("special"))
        self.assertFalse(qm.completed("special"))
        self.assertFalse(qm.completed())
        self.assertTrue(qm.need_complete_before_start("special"))
        qm.start("special")
        self.assertTrue(qm.started("special"))
        self.assertTrue(qm.finished("special"))
        self.assertFalse(qm.completed("special"))
        self.assertFalse(qm.completed())
        self.assertFalse(qm.need_start("special"))
        self.assertFalse(qm.need_finish("special"))
        self.assertTrue(qm.need_complete("special"))
        self.assertFalse(qm.need_complete_before_start("special"))
        qm.complete("special")
        self.assertTrue(qm.started("special"))
        self.assertTrue(qm.finished("special"))
        self.assertTrue(qm.completed("special"))
        self.assertTrue(qm.completed())
        self.assertFalse(qm.need_start("special"))
        self.assertFalse(qm.need_finish("special"))
        self.assertFalse(qm.need_complete("special"))
        self.assertFalse(qm.need_complete_before_start("special"))

    def test_05(self):
        quest = {
            "parts": OrderedDict((("special", {
                "info": "",
                "uid": "special",
                "name": "Special",
                "parts": OrderedDict((("get_item", {
                    "info": "",
                    "uid": "get_item",
                    "name": "Get an item",
                    "item": {"arch": "sword", "name": "quest sword"},
                    "parts": OrderedDict((("kill", {
                        "info": "",
                        "uid": "kill",
                        "name": "Killing",
                        "kill": {"nrof": 1},
                    }),)),
                }),)),
            }),)),
            "name": "Test Quest",
            "uid": "test_quest",
        }
        qm = QuestManager(activator, quest)
        self.assertFalse(qm.started("special"))
        self.assertTrue(qm.finished("special"))
        self.assertFalse(qm.completed("special"))
        self.assertFalse(qm.completed())
        self.assertTrue(qm.need_complete_before_start("special"))
        qm.start("special")
        self.assertTrue(qm.started("special"))
        self.assertTrue(qm.finished("special"))
        self.assertFalse(qm.completed("special"))
        self.assertFalse(qm.completed())
        self.assertFalse(qm.need_start("special"))
        self.assertFalse(qm.need_finish("special"))
        self.assertTrue(qm.need_complete("special"))
        self.assertFalse(qm.need_complete_before_start("special"))
        
        self.assertFalse(qm.started(["special", "get_item"]))
        self.assertFalse(qm.finished(["special", "get_item"]))
        self.assertFalse(qm.completed(["special", "get_item"]))
        self.assertFalse(qm.completed())
        self.assertTrue(qm.need_start(["special", "get_item"]))
        self.assertFalse(qm.need_finish(["special", "get_item"]))
        self.assertFalse(qm.need_complete(["special", "get_item"]))
        self.assertFalse(qm.need_complete_before_start(["special", "get_item"]))
        self.assertFalse(qm.complete(["special", "get_item"]))
        qm.start(["special", "get_item"])
        self.assertTrue(qm.started(["special", "get_item"]))
        self.assertFalse(qm.finished(["special", "get_item"]))
        self.assertFalse(qm.completed(["special", "get_item"]))
        self.assertFalse(qm.completed())
        self.assertFalse(qm.need_start(["special", "get_item"]))
        self.assertTrue(qm.need_finish(["special", "get_item"]))
        self.assertFalse(qm.need_complete(["special", "get_item"]))
        self.assertFalse(qm.need_complete_before_start(["special", "get_item"]))

        self.assertFalse(qm.started(["special", "get_item", "kill"]))
        self.assertFalse(qm.finished(["special", "get_item", "kill"]))
        self.assertFalse(qm.completed(["special", "get_item", "kill"]))
        self.assertFalse(qm.completed())
        self.assertTrue(qm.need_start(["special", "get_item", "kill"]))
        self.assertFalse(qm.need_finish(["special", "get_item", "kill"]))
        self.assertFalse(qm.need_complete(["special", "get_item", "kill"]))
        self.assertFalse(qm.need_complete_before_start(["special", "get_item",
                                                        "kill"]))
        self.assertFalse(qm.complete(["special", "get_item", "kill"]))
        qm.start(["special", "get_item", "kill"])
        self.assertTrue(qm.started(["special", "get_item", "kill"]))
        self.assertFalse(qm.finished(["special", "get_item", "kill"]))
        self.assertFalse(qm.completed(["special", "get_item", "kill"]))
        self.assertFalse(qm.completed())
        self.assertFalse(qm.need_start(["special", "get_item", "kill"]))
        self.assertTrue(qm.need_finish(["special", "get_item", "kill"]))
        self.assertFalse(qm.need_complete(["special", "get_item", "kill"]))
        self.assertFalse(qm.need_complete_before_start(["special", "get_item",
                                                        "kill"]))

        raas = activator.map.CreateObject("raas", activator.x, activator.y)
        quest_container = raas.CreateObject("quest_container")
        quest_container.name = "test_quest"
        quest_object = quest_container.CreateObject("quest_container")
        quest_object.name = "kill"
        quest_object.sub_type = Atrinik.QUEST_TYPE_KILL
        raas.Update()
        activator.Hit(raas, -1)
        self.assertTrue(qm.started(["special", "get_item", "kill"]))
        self.assertTrue(qm.finished(["special", "get_item", "kill"]))
        self.assertFalse(qm.completed(["special", "get_item", "kill"]))
        self.assertFalse(qm.completed())
        self.assertFalse(qm.need_start(["special", "get_item", "kill"]))
        self.assertFalse(qm.need_finish(["special", "get_item", "kill"]))
        self.assertTrue(qm.need_complete(["special", "get_item", "kill"]))
        self.assertFalse(qm.need_complete_before_start(["special", "get_item",
                                                        "kill"]))
        qm.complete(["special", "get_item", "kill"])
        self.assertTrue(qm.started(["special", "get_item", "kill"]))
        self.assertTrue(qm.finished(["special", "get_item", "kill"]))
        self.assertTrue(qm.completed(["special", "get_item", "kill"]))
        self.assertFalse(qm.completed())
        self.assertFalse(qm.need_start(["special", "get_item", "kill"]))
        self.assertFalse(qm.need_finish(["special", "get_item", "kill"]))
        self.assertFalse(qm.need_complete(["special", "get_item", "kill"]))
        self.assertFalse(qm.need_complete_before_start(["special", "get_item",
                                                        "kill"]))
        
        sword = activator.CreateObject("sword")
        self.assertTrue(qm.started(["special", "get_item"]))
        self.assertFalse(qm.finished(["special", "get_item"]))
        self.assertFalse(qm.completed(["special", "get_item"]))
        self.assertFalse(qm.completed())
        self.assertFalse(qm.need_start(["special", "get_item"]))
        self.assertTrue(qm.need_finish(["special", "get_item"]))
        self.assertFalse(qm.need_complete(["special", "get_item"]))
        self.assertFalse(qm.need_complete_before_start(["special", "get_item"]))
        sword.name = "quest sword"
        self.assertTrue(qm.started(["special", "get_item"]))
        self.assertTrue(qm.finished(["special", "get_item"]))
        self.assertFalse(qm.completed(["special", "get_item"]))
        self.assertFalse(qm.completed())
        self.assertFalse(qm.need_start(["special", "get_item"]))
        self.assertFalse(qm.need_finish(["special", "get_item"]))
        self.assertTrue(qm.need_complete(["special", "get_item"]))
        self.assertFalse(qm.need_complete_before_start(["special", "get_item"]))
        qm.complete(["special", "get_item"])
        self.assertFalse(sword)
        self.assertTrue(qm.started(["special", "get_item"]))
        self.assertFalse(qm.finished(["special", "get_item"]))
        self.assertTrue(qm.completed(["special", "get_item"]))
        self.assertFalse(qm.completed())
        self.assertFalse(qm.need_start(["special", "get_item"]))
        self.assertFalse(qm.need_finish(["special", "get_item"]))
        self.assertFalse(qm.need_complete(["special", "get_item"]))
        self.assertFalse(qm.need_complete_before_start(["special", "get_item"]))
        
        qm.complete("special")
        self.assertTrue(qm.started("special"))
        self.assertTrue(qm.finished("special"))
        self.assertTrue(qm.completed("special"))
        self.assertTrue(qm.completed())
        self.assertFalse(qm.need_start("special"))
        self.assertFalse(qm.need_finish("special"))
        self.assertFalse(qm.need_complete("special"))
        self.assertFalse(qm.need_complete_before_start("special"))

    def test_06(self):
        quest = {
            "parts": OrderedDict((("special", {
                "info": "",
                "uid": "special",
                "name": "Special",
                "parts": OrderedDict((("special2", {
                    "info": "",
                    "uid": "special2",
                    "name": "Special 2",
                    "parts": OrderedDict((("kill", {
                        "info": "",
                        "uid": "kill",
                        "name": "Killing",
                        "kill": {"nrof": 1},
                    }),)),
                }),)),
            }),)),
            "name": "Test Quest",
            "uid": "test_quest",
        }
        qm = QuestManager(activator, quest)
        qm.start("special")
        self.assertTrue(qm.started("special"))
        self.assertFalse(qm.started(["special", "special2"]))
        qm.start(["special", "special2"])
        self.assertTrue(qm.started(["special", "special2"]))
        self.assertTrue(qm.need_complete("special"))
        qm.start(["special", "special2", "kill"])
        self.assertTrue(qm.started(["special", "special2", "kill"]))
        qm.complete(["special", "special2"])
        self.assertFalse(qm.completed(["special", "special2", "kill"]))

    def test_07(self):
        quest = {
            "name": "Test Quest",
            "uid": "test_quest",
        }
        qm = QuestManager(activator, quest)
        self.assertIsNone(qm.state_get("foo"))
        self.assertEqual(qm.state_get_int("foo"), 0)
        self.assertFalse(qm.state_get_bool("foo"))
        self.assertAlmostEqual(qm.state_get_float("foo"), 0.0)
        qm.state_set("foo", True)
        self.assertEqual(qm.state_get("foo"), "1")
        self.assertEqual(qm.state_get_int("foo"), 1)
        self.assertTrue(qm.state_get_bool("foo"))
        self.assertAlmostEqual(qm.state_get_float("foo"), 1.0)
        qm.state_set("foo", False)
        self.assertEqual(qm.state_get("foo"), "0")
        self.assertEqual(qm.state_get_int("foo"), 0)
        self.assertFalse(qm.state_get_bool("foo"))
        self.assertAlmostEqual(qm.state_get_float("foo"), 0.0)
        qm.state_set("foo", 42)
        self.assertEqual(qm.state_get("foo"), "42")
        self.assertEqual(qm.state_get_int("foo"), 42)
        self.assertTrue(qm.state_get_bool("foo"))
        self.assertAlmostEqual(qm.state_get_float("foo"), 42.0)
        qm.state_set("bar", "hello world")
        self.assertEqual(qm.state_get("bar"), "hello world")
        self.assertEqual(qm.state_get_int("bar"), 0)
        self.assertFalse(qm.state_get_bool("bar"))
        qm.state_set("foo", 42.69)
        self.assertEqual(qm.state_get("foo"), "42.69")
        self.assertEqual(qm.state_get_int("foo"), 0)
        self.assertTrue(qm.state_get_bool("foo"))
        self.assertAlmostEqual(qm.state_get_float("foo"), 42.69)

    def test_08_failed_quest_is_not_completed(self):
        quest = {
            "parts": OrderedDict((("attempt", {
                "info": "",
                "uid": "attempt",
                "name": "Attempt",
            }),)),
            "name": "Failure Test Quest",
            "uid": "failure_test_quest",
        }
        qm = QuestManager(activator, quest)
        qm.start("attempt")
        self.assertTrue(qm.fail("attempt"))
        self.assertTrue(qm.failed())
        self.assertFalse(qm.completed())
        self.assertFalse(qm.fail("attempt"))

    def test_09_failed_repeat_quest_resets(self):
        quest_container = activator.Controller().quest_container
        old_magic = quest_container.magic
        old_exp = quest_container.exp
        self.addCleanup(setattr, quest_container, "magic", old_magic)
        self.addCleanup(setattr, quest_container, "exp", old_exp)
        quest_container.magic = 0
        quest_container.exp = int(time.time())

        quest = {
            "parts": OrderedDict((("attempt", {
                "info": "",
                "uid": "attempt",
                "name": "Attempt",
            }),)),
            "name": "Repeat Failure Test Quest",
            "uid": "repeat_failure_test_quest",
            "repeat": True,
        }
        qm = QuestManager(activator, quest)
        self.assertEqual(qm.get_qp_remaining(), qm.get_qp_max())
        qm.start("attempt")
        self.assertTrue(qm.fail("attempt"))
        self.assertTrue(qm.failed())

        quest_container.exp = int(time.time()) - 60 * 60 * 20
        self.assertEqual(qm.get_qp_restored(), qm.get_qp_max())
        intents = []
        commits = []
        def journal_begin(*args):
            intents.append(args)
            return "repeat-reset"

        with mock.patch.object(
                qm, "journal_begin", side_effect=journal_begin), \
                mock.patch.object(
                    qm, "journal_commit", side_effect=commits.append):
            qm.reset_quest()
        self.assertFalse(qm.started())
        self.assertEqual([
            ("quest.repeat-reset", "quest:repeat_failure_test_quest",
             Atrinik.QUEST_STATUS_FAILED, Atrinik.QUEST_STATUS_INVALID,
             "actor:quest-manager"),
        ], intents)
        self.assertEqual(["repeat-reset"], commits)

    def test_10_missing_repeat_delay_has_no_cooldown(self):
        quest_container = activator.Controller().quest_container
        old_magic = quest_container.magic
        old_exp = quest_container.exp
        self.addCleanup(setattr, quest_container, "magic", old_magic)
        self.addCleanup(setattr, quest_container, "exp", old_exp)

        qm = QuestManager(activator, {
            "name": "Missing Repeat Delay Test Quest",
            "uid": "missing_repeat_delay_test_quest",
            "repeat": True,
        })
        qm.ensure_quest_object()
        quest_container.magic = 0
        quest_container.exp = 0
        qm.quest_object.exp = 0

        with mock.patch("QuestManager.time.time", return_value=1000):
            qm.use_qp()

        self.assertEqual(quest_container.magic, 1)
        self.assertEqual(quest_container.exp, 1000)
        self.assertEqual(qm.quest_object.exp, 0)

    def test_11_integer_repeat_delay_sets_cooldown(self):
        quest_container = activator.Controller().quest_container
        old_magic = quest_container.magic
        old_exp = quest_container.exp
        self.addCleanup(setattr, quest_container, "magic", old_magic)
        self.addCleanup(setattr, quest_container, "exp", old_exp)

        qm = QuestManager(activator, {
            "name": "Integer Repeat Delay Test Quest",
            "uid": "integer_repeat_delay_test_quest",
            "repeat": True,
            "repeat_delay": 300,
        })
        qm.ensure_quest_object()
        quest_container.magic = 0
        quest_container.exp = 0
        qm.quest_object.exp = 0

        with mock.patch("QuestManager.time.time", return_value=1000):
            qm.use_qp()

        self.assertEqual(quest_container.magic, 1)
        self.assertEqual(quest_container.exp, 1000)
        self.assertEqual(qm.quest_object.exp, 1300)

    def test_12_invalid_repeat_delay_preserves_state(self):
        quest_container = activator.Controller().quest_container
        old_magic = quest_container.magic
        old_exp = quest_container.exp
        self.addCleanup(setattr, quest_container, "magic", old_magic)
        self.addCleanup(setattr, quest_container, "exp", old_exp)

        qm = QuestManager(activator, {
            "name": "Invalid Repeat Delay Test Quest",
            "uid": "invalid_repeat_delay_test_quest",
            "repeat": True,
            "repeat_delay": "300",
        })
        qm.ensure_quest_object()
        quest_container.magic = 2
        quest_container.exp = 321
        qm.quest_object.exp = 654

        with mock.patch("QuestManager.time.time") as time_mock:
            with self.assertRaisesRegex(
                    TypeError,
                    "invalid_repeat_delay_test_quest.*repeat_delay must be "
                    "an integer or None, got str"):
                qm.use_qp()

        time_mock.assert_not_called()
        self.assertEqual(quest_container.magic, 2)
        self.assertEqual(quest_container.exp, 321)
        self.assertEqual(qm.quest_object.exp, 654)

    def test_13_journal_hooks_use_stable_paths_exactly_once(self):
        quest = {
            "parts": OrderedDict((("outer", {
                "info": "",
                "uid": "outer",
                "name": "Outer",
                "parts": OrderedDict((("inner", {
                    "info": "",
                    "uid": "inner",
                    "name": "Inner",
                }),)),
            }),)),
            "name": "Journal Hook Quest",
            "uid": "journal_hook_quest",
        }
        qm = QuestManager(activator, quest)
        intents = []
        commits = []

        def journal_begin(reason, subject, before, after, lineage=""):
            transaction = "transaction-{}".format(len(intents))
            intents.append((reason, subject, before, after, lineage))
            return transaction

        with mock.patch.object(qm, "journal_begin", side_effect=journal_begin), \
                mock.patch.object(qm, "journal_commit", side_effect=commits.append):
            qm.start("outer")
            qm.start(["outer", "inner"])
            qm.start(["outer", "inner"])
            self.assertFalse(qm.complete(["outer", "inner"]))
            self.assertFalse(qm.complete(["outer", "inner"]))
            self.assertTrue(qm.complete("outer"))
            self.assertFalse(qm.complete("outer"))

        self.assertEqual([
            ("quest.part-started", "quest-part:journal_hook_quest::outer",
             Atrinik.QUEST_STATUS_INVALID, Atrinik.QUEST_STATUS_STARTED, ""),
            ("quest.started", "quest:journal_hook_quest",
             Atrinik.QUEST_STATUS_INVALID, Atrinik.QUEST_STATUS_STARTED, ""),
            ("quest.part-started",
             "quest-part:journal_hook_quest::outer::inner",
             Atrinik.QUEST_STATUS_INVALID, Atrinik.QUEST_STATUS_STARTED, ""),
            ("quest.part-completed",
             "quest-part:journal_hook_quest::outer::inner",
             Atrinik.QUEST_STATUS_STARTED, Atrinik.QUEST_STATUS_COMPLETED, ""),
            ("quest.part-completed", "quest-part:journal_hook_quest::outer",
             Atrinik.QUEST_STATUS_STARTED, Atrinik.QUEST_STATUS_COMPLETED, ""),
            ("quest.completed", "quest:journal_hook_quest",
             Atrinik.QUEST_STATUS_STARTED, Atrinik.QUEST_STATUS_COMPLETED, ""),
        ], intents)
        self.assertEqual([
            "transaction-0", "transaction-1", "transaction-2",
            "transaction-3", "transaction-4", "transaction-5",
        ], commits)

    def test_14_kept_objective_item_is_retained_without_quest_flags(self):
        quest = {
            "parts": OrderedDict((("deliver", {
                "info": "",
                "item": {
                    "arch": "sword",
                    "name": "kept quest sword",
                    "keep": True,
                },
                "uid": "deliver",
                "name": "Delivery",
            }),)),
            "name": "Kept Objective Quest",
            "uid": "kept_objective_quest",
        }
        qm = QuestManager(activator, quest)
        qm.start("deliver")
        sword = activator.CreateObject("sword")
        sword.name = "kept quest sword"
        sword.f_quest_item = True
        sword.f_startequip = True
        self.assertTrue(qm.complete("deliver"))
        self.assertTrue(sword)
        self.assertFalse(sword.f_quest_item)
        self.assertFalse(sword.f_startequip)
        sword.Destroy("test.quest-objective-cleanup")


activator = Atrinik.WhoIsActivator()
me = Atrinik.WhoAmI()
suites = [
    unittest.TestLoader().loadTestsFromTestCase(QuestManagerSuite),
]
