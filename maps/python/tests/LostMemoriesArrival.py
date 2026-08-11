import os
import runpy
import unittest

import Atrinik
from Interface import InterfaceBuilder
from InterfaceQuests import escaping_deserted_island, lost_memories
from LostMemoriesApartment import (
    APARTMENT_TAG,
    complete_apartment_tutorial,
    ensure_strakewood_apartment,
    notify_apartment_entry,
)
from QuestManager import QuestManager
from tests import TestSuite, ib_wrapper


ARRIVAL_MAPS = (
    "/shattered_islands/incuna/ship_lower_deck",
    "/shattered_islands/incuna/ship_lower_deck_to_incuna",
)
MAPS_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
SAM_INTERFACE = os.path.join(
    MAPS_ROOT,
    "interfaces/quests/lost_memories/sam_goodberry.py",
)


class LostMemoriesArrivalSuite(TestSuite):
    def setUp(self):
        super().setUp()
        self.quest_items = []
        self.npc = activator.map.CreateObject(
            "ranger", activator.x, activator.y
        )

    def tearDown(self):
        apartment = activator.FindObject(
            archname="player_info", name=APARTMENT_TAG
        )
        if apartment:
            apartment.Destroy()
        for obj in self.quest_items:
            if obj:
                obj.Destroy()
        self.npc.Destroy()
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

    def find_incuna_sam(self):
        activator.TeleportTo("/shattered_islands/world_4_85", 4, 12)

        for x in range(activator.map.width):
            for y in range(activator.map.height):
                for obj in activator.map.Objects(x, y):
                    if obj.name == "Sam Goodberry":
                        return obj
                    sam = obj.FindObject(name="Sam Goodberry")
                    if sam:
                        return sam

        self.fail("Could not find Incuna's Sam Goodberry")

    def run_sam_interface(self, sam, msg):
        runpy.run_path(SAM_INTERFACE, init_globals={
            "activator": activator,
            "me": sam,
            "msg": msg,
        })

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

    def test_actual_incuna_sam_advances_to_apartment_once(self):
        memories = QuestManager(activator, lost_memories)
        memories.start("speak_sam")
        sam = self.find_incuna_sam()
        event = sam.FindObject(archname="event_obj")
        self.assertIsNotNone(event)
        self.assertEqual(
            "/interfaces/quests/lost_memories/quest.xml",
            event.race,
        )

        packets = activator.Controller().s_packets
        packets.clear()
        self.run_sam_interface(sam, "hello")
        self.assertTrue(any(
            b"There you are!" in packet
            for packet in packets
        ))

        sacks_before = activator.FindObjects(archname="sack")
        try:
            self.run_sam_interface(sam, "remember")
            sacks_after = activator.FindObjects(archname="sack")
            rewards = [obj for obj in sacks_after if obj not in sacks_before]
            self.assertEqual(1, len(rewards))
            mushrooms = rewards[0].FindObject(archname="mushroom1")
            self.assertIsNotNone(mushrooms)
            self.assertEqual(14, mushrooms.nrof)
            self.assertEqual(
                Atrinik.QUEST_STATUS_STARTED,
                memories.get_quest_status(),
            )
            self.assertEqual(
                [
                    ("apartment_tutorial", Atrinik.QUEST_STATUS_STARTED),
                    ("speak_sam", Atrinik.QUEST_STATUS_COMPLETED),
                ],
                self.quest_parts(memories),
            )

            state_after = (
                memories.get_quest_status(),
                self.quest_parts(memories),
            )
            self.run_sam_interface(sam, "remember")
            self.assertEqual(
                state_after,
                (memories.get_quest_status(), self.quest_parts(memories)),
            )
            self.assertEqual(
                len(sacks_after),
                len(activator.FindObjects(archname="sack")),
            )
        finally:
            for obj in activator.FindObjects(archname="sack"):
                if obj not in sacks_before:
                    obj.Destroy()

    def test_apartment_grant_is_free_once_and_preserves_existing_tier(self):
        self.assertFalse(notify_apartment_entry(activator))
        apartment, created = ensure_strakewood_apartment(activator)
        self.assertTrue(created)
        self.assertEqual(APARTMENT_TAG, apartment.name)
        self.assertEqual("cheap", apartment.slaying)

        repeated, created = ensure_strakewood_apartment(activator)
        self.assertFalse(created)
        self.assertEqual(apartment, repeated)
        self.assertEqual(1, len(activator.FindObjects(
            archname="player_info", name=APARTMENT_TAG
        )))

        for tier in ("normal", "expensive", "luxurious"):
            apartment.slaying = tier
            existing, created = ensure_strakewood_apartment(activator)
            self.assertFalse(created)
            self.assertEqual(apartment, existing)
            self.assertEqual(tier, existing.slaying)

    def test_failed_apartment_grant_does_not_advance_and_can_retry(self):
        memories = QuestManager(activator, lost_memories)
        memories.start("apartment_tutorial")

        apartment, created = ensure_strakewood_apartment(
            activator, creator=lambda archname: None
        )
        self.assertIsNone(apartment)
        self.assertFalse(created)
        self.assertEqual(
            Atrinik.QUEST_STATUS_STARTED,
            memories.get_quest_status("apartment_tutorial"),
        )
        self.assertFalse(memories.started("speak_priest"))

        apartment, created = ensure_strakewood_apartment(activator)
        self.assertTrue(created)
        self.assertIsNotNone(apartment)

        packets = activator.Controller().s_packets
        packets.clear()
        self.assertTrue(notify_apartment_entry(activator))
        self.assertTrue(any(
            b"Tutorial Available: Apartments" in packet
            for packet in packets
        ))

    def test_bed_use_requires_ownership_and_advances_in_order_once(self):
        memories = QuestManager(activator, lost_memories)
        memories.start("apartment_tutorial")
        self.assertFalse(complete_apartment_tutorial(activator))
        self.assertFalse(memories.started("speak_priest"))

        apartment, created = ensure_strakewood_apartment(activator)
        self.assertTrue(created)
        self.assertTrue(complete_apartment_tutorial(activator))
        self.assertTrue(memories.completed("apartment_tutorial"))
        self.assertEqual(
            Atrinik.QUEST_STATUS_STARTED,
            memories.get_quest_status("speak_priest"),
        )

        state = self.quest_parts(memories)
        self.assertFalse(complete_apartment_tutorial(activator))
        self.assertEqual(state, self.quest_parts(memories))

    def test_incuna_steward_and_owner_gated_portal_are_signposted(self):
        activator.TeleportTo("/shattered_islands/world_4_85", 7, 4)
        steward = None
        portal = None
        for obj in activator.map.Objects(6, 3):
            if obj.name == "Elara Harth":
                steward = obj
        for obj in activator.map.Objects(7, 3):
            if obj.name == "Incuna Strakewood apartment portal":
                portal = obj

        self.assertIsNotNone(steward)
        self.assertIsNotNone(portal)
        steward_event = steward.FindObject(archname="event_obj")
        portal_event = portal.FindObject(archname="event_obj")
        self.assertEqual(
            "/interfaces/quests/lost_memories/quest.xml",
            steward_event.race,
        )
        self.assertEqual(
            "/python/generic/apartment_teleport.py", portal_event.race
        )
        self.assertEqual("strakewood_island", portal_event.slaying)

    def test_arrival_preserves_legacy_lost_memories_states(self):
        states = (
            ("active", Atrinik.QUEST_STATUS_STARTED, None),
            ("completed", Atrinik.QUEST_STATUS_COMPLETED, "complete"),
            ("failed", Atrinik.QUEST_STATUS_FAILED, "fail"),
        )

        for label, status, transition in states:
            for path in ARRIVAL_MAPS:
                with self.subTest(state=label, path=path):
                    self.clear_quests()
                    self.complete_escape()
                    memories = QuestManager(activator, lost_memories)
                    memories.start("broken_spirit")
                    if transition:
                        self.assertTrue(
                            getattr(memories, transition)("broken_spirit")
                        )
                    quest_object = memories.quest_object
                    parts = self.quest_parts(memories)
                    self.assertEqual(status, memories.get_quest_status())
                    self.assertFalse(memories.started("speak_sam"))

                    activator.TeleportTo(path, 2, 2)

                    current = QuestManager(activator, lost_memories)
                    self.assertEqual(quest_object, current.quest_object)
                    self.assertEqual(status, current.get_quest_status())
                    self.assertEqual(parts, self.quest_parts(current))
                    self.assertFalse(current.started("speak_sam"))

    def test_legacy_sam_state_precedes_arrival_fallback(self):
        memories = QuestManager(activator, lost_memories)
        memories.start("broken_spirit")

        # noinspection PyPep8Naming
        class InterfaceDialog_need_complete_broken_spirit(InterfaceBuilder):
            @ib_wrapper
            def dialog_hello(self):
                pass

        # noinspection PyPep8Naming
        class InterfaceDialog_need_start_speak_sam(InterfaceBuilder):
            @ib_wrapper
            def dialog_hello(self):
                pass

        ib = InterfaceBuilder(activator, self.npc)
        ib.set_quest(memories)
        ib.finish(locals(), "hello")

        self.IB_test(
            "InterfaceDialog_need_complete_broken_spirit.dialog_hello"
        )
        self.assertFalse(memories.started("speak_sam"))


activator = Atrinik.WhoIsActivator()
suites = [
    unittest.TestLoader().loadTestsFromTestCase(LostMemoriesArrivalSuite),
]
