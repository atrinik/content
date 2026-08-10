import unittest

import Atrinik
from InterfaceQuests import escaping_deserted_island, lost_memories
from QuestManager import QuestManager
from tests import TestSuite


ARRIVAL_MAPS = (
    "/shattered_islands/incuna/ship_lower_deck",
    "/shattered_islands/incuna/ship_lower_deck_to_incuna",
)


class LostMemoriesArrivalSuite(TestSuite):
    def setUp(self):
        super().setUp()
        self.quest_items = []

    def tearDown(self):
        for obj in self.quest_items:
            if obj:
                obj.Destroy()
        activator.TeleportTo("/emergency")
        super().tearDown()

    def clear_quests(self):
        container = activator.Controller().quest_container
        while container.inv:
            container.inv[0].Destroy()

    def complete_escape(self):
        escaping = QuestManager(activator, escaping_deserted_island)
        escaping.start("get_branches")
        branches = Atrinik.CreateObject("deserted_island_branch")
        branches.nrof = 10
        branches.InsertInto(activator)
        self.quest_items.append(branches)
        self.assertTrue(escaping.finished("get_branches"))
        self.assertTrue(escaping.complete("get_branches"))
        self.assertTrue(escaping.completed())

    def quest_parts(self, qm):
        return sorted((obj.name, obj.magic) for obj in qm.quest_object.inv)

    def test_arrival_starts_speak_sam(self):
        for path in ARRIVAL_MAPS:
            with self.subTest(path=path):
                self.clear_quests()
                self.complete_escape()
                self.assertFalse(
                    QuestManager(activator, lost_memories).started()
                )
                packets = activator.Controller().s_packets
                packets.clear()

                activator.TeleportTo(path, 2, 2)

                self.assertTrue(any(
                    "You have reached Incuna.".encode() in packet
                    for packet in packets
                ))
                memories = QuestManager(activator, lost_memories)
                self.assertEqual(
                    Atrinik.QUEST_STATUS_STARTED,
                    memories.get_quest_status(),
                )
                self.assertEqual(
                    Atrinik.QUEST_STATUS_STARTED,
                    memories.get_quest_status("speak_sam"),
                )
                self.assertFalse(memories.started("speak_priest"))
                self.assertEqual(
                    [("speak_sam", Atrinik.QUEST_STATUS_STARTED)],
                    self.quest_parts(memories),
                )

    def test_arrival_preserves_active_lost_memories(self):
        self.complete_escape()
        memories = QuestManager(activator, lost_memories)
        memories.start("speak_sam")
        memories.start("speak_priest")
        self.assertFalse(memories.complete("speak_sam"))
        self.assertTrue(memories.completed("speak_sam"))
        self.assertEqual(
            Atrinik.QUEST_STATUS_STARTED,
            memories.get_quest_status("speak_priest"),
        )
        quest_object = memories.quest_object
        parts = self.quest_parts(memories)

        for path in ARRIVAL_MAPS:
            with self.subTest(path=path):
                activator.TeleportTo(path, 2, 2)
                current = QuestManager(activator, lost_memories)
                self.assertEqual(quest_object, current.quest_object)
                self.assertEqual(parts, self.quest_parts(current))
                self.assertTrue(current.completed("speak_sam"))
                self.assertEqual(
                    Atrinik.QUEST_STATUS_STARTED,
                    current.get_quest_status("speak_priest"),
                )


activator = Atrinik.WhoIsActivator()
suites = [
    unittest.TestLoader().loadTestsFromTestCase(LostMemoriesArrivalSuite),
]
