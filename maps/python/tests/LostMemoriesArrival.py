import os
import runpy
import unittest

import Atrinik
import LostMemoriesApartment
from Interface import InterfaceBuilder
from InterfaceQuests import escaping_deserted_island, lost_memories
from Apartments import apartments_info
from LostMemoriesApartment import (
    APARTMENT_TAG,
    complete_apartment_tutorial,
    ensure_incuna_apartment,
    find_incuna_apartment,
    notify_apartment_entry,
)
from QuestManager import QuestManager
from tests import TestSuite, ib_wrapper, simulate_server


ARRIVAL_MAPS = (
    "/shattered_islands/incuna/ship_lower_deck",
    "/shattered_islands/incuna/ship_lower_deck_to_incuna",
)
MAPS_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
SAM_INTERFACE = os.path.join(
    MAPS_ROOT,
    "interfaces/quests/lost_memories/sam_goodberry.py",
)
STEWARD_INTERFACE = os.path.join(
    MAPS_ROOT,
    "interfaces/quests/lost_memories/incuna_apartment_steward.py",
)
BRELEND_INTERFACE = os.path.join(
    MAPS_ROOT,
    "interfaces/quests/lost_memories/brelend_lee.py",
)


class LostMemoriesArrivalSuite(TestSuite):
    def setUp(self):
        super().setUp()
        self.quest_items = []
        self.npc = activator.map.CreateObject(
            "ranger", activator.x, activator.y
        )

    def tearDown(self):
        for region in ("incuna", "strakewood_island"):
            apartment = activator.FindObject(
                archname="player_info",
                name=apartments_info[region]["tag"],
            )
            if apartment:
                apartment.Destroy()
        for obj in self.quest_items:
            if obj:
                obj.Destroy()
        if self.npc:
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

    def run_steward_interface(self, steward, msg):
        runpy.run_path(STEWARD_INTERFACE, init_globals={
            "activator": activator,
            "me": steward,
            "msg": msg,
        })

    def run_brelend_interface(self, brelend, msg):
        runpy.run_path(BRELEND_INTERFACE, init_globals={
            "activator": activator,
            "me": brelend,
            "msg": msg,
        })

    def find_map_object(self, predicate):
        for x in range(activator.map.width):
            for y in range(activator.map.height):
                for obj in activator.map.Objects(x, y):
                    if predicate(obj):
                        return obj
        return None

    def find_map_objects(self, predicate):
        matches = []
        for x in range(activator.map.width):
            for y in range(activator.map.height):
                matches.extend(
                    obj for obj in activator.map.Objects(x, y)
                    if predicate(obj)
                )
        return matches

    def find_incuna_steward(self):
        """Allow the authored spawn point to generate Elara before inspection."""

        # Spawn points use a fractional negative speed and may begin with a
        # negative speed credit.  Advance far enough for that normal credit
        # cycle to elapse instead of relying on the initial random offset.
        for _ in range(400):
            steward = self.find_map_object(
                lambda obj: obj.name == "Elara Harth"
            )
            if (
                steward is not None
                and steward.FindObject(
                    type=Atrinik.Type.SPAWN_POINT_INFO
                ) is not None
            ):
                return steward
            simulate_server(count=1, wait=False)
        return None

    @staticmethod
    def event_with_race(obj, race):
        event = obj.FindObject(archname="event_obj")
        return event is not None and event.race == race

    @staticmethod
    def walk_into_portal(portal):
        activator.SetPosition(portal.x, portal.y + 1)
        activator.Move(Atrinik.NORTH)

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

    def test_apartment_grant_is_free_once_and_regionally_independent(self):
        self.assertFalse(notify_apartment_entry(activator))
        strakewood = activator.CreateObject("player_info")
        strakewood.name = apartments_info["strakewood_island"]["tag"]
        strakewood.slaying = "luxurious"

        apartment, created = ensure_incuna_apartment(activator)
        self.assertTrue(created)
        self.assertEqual(APARTMENT_TAG, apartment.name)
        self.assertEqual("cheap", apartment.slaying)
        self.assertNotEqual(strakewood.name, apartment.name)
        self.assertEqual("luxurious", strakewood.slaying)

        repeated, created = ensure_incuna_apartment(activator)
        self.assertFalse(created)
        self.assertEqual(apartment, repeated)
        self.assertEqual(1, len(activator.FindObjects(
            archname="player_info", name=APARTMENT_TAG
        )))

    def test_failed_apartment_grant_does_not_advance_and_can_retry(self):
        memories = QuestManager(activator, lost_memories)
        memories.start("apartment_tutorial")

        apartment, created = ensure_incuna_apartment(
            activator, creator=lambda archname: None
        )
        self.assertIsNone(apartment)
        self.assertFalse(created)
        self.assertEqual(
            Atrinik.QUEST_STATUS_STARTED,
            memories.get_quest_status("apartment_tutorial"),
        )
        self.assertFalse(memories.started("speak_priest"))

        apartment, created = ensure_incuna_apartment(
            activator, ready_map=lambda path: None
        )
        self.assertIsNone(apartment)
        self.assertFalse(created)
        self.assertIsNone(find_incuna_apartment(activator))

        apartment, created = ensure_incuna_apartment(activator)
        self.assertTrue(created)
        self.assertIsNotNone(apartment)

        packets = activator.Controller().s_packets
        packets.clear()
        self.assertTrue(notify_apartment_entry(activator))
        self.assertTrue(any(
            b"Tutorial Available: Apartments" in packet
            for packet in packets
        ))

    def test_actual_steward_failure_does_not_advance_and_retry_grants_once(self):
        memories = QuestManager(activator, lost_memories)
        memories.start("apartment_tutorial")
        activator.TeleportTo("/shattered_islands/world_4_84", 16, 18)
        steward = self.find_incuna_steward()
        self.assertIsNotNone(steward)

        original_ensure = LostMemoriesApartment.ensure_incuna_apartment
        try:
            LostMemoriesApartment.ensure_incuna_apartment = (
                lambda player: (None, False)
            )
            self.run_steward_interface(steward, "claim")
        finally:
            LostMemoriesApartment.ensure_incuna_apartment = original_ensure

        self.assertIsNone(activator.FindObject(
            archname="player_info", name=APARTMENT_TAG
        ))
        self.assertFalse(memories.started("speak_priest"))
        self.assertEqual(
            Atrinik.QUEST_STATUS_STARTED,
            memories.get_quest_status("apartment_tutorial"),
        )

        self.run_steward_interface(steward, "claim")
        self.run_steward_interface(steward, "claim")
        self.assertEqual(1, len(activator.FindObjects(
            archname="player_info", name=APARTMENT_TAG
        )))

    def test_bed_use_requires_ownership_and_advances_in_order_once(self):
        memories = QuestManager(activator, lost_memories)
        memories.start("apartment_tutorial")
        self.assertFalse(complete_apartment_tutorial(activator))
        self.assertFalse(memories.started("speak_priest"))

        apartment, created = ensure_incuna_apartment(activator)
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
        activator.TeleportTo("/shattered_islands/world_4_85", 9, 4)
        steward = None
        portal = None
        notice = None
        for obj in activator.map.Objects(9, 4):
            if obj.name == "NEW ARRIVALS":
                notice = obj
        activator.TeleportTo("/shattered_islands/world_4_84", 16, 18)
        steward = self.find_incuna_steward()
        for obj in activator.map.Objects(17, 18):
            if obj.name == "Incuna beach nook portal":
                portal = obj

        self.assertIsNotNone(notice)
        self.assertIsNotNone(steward)
        self.assertIsNotNone(portal)
        self.assertEqual((16, 19), (steward.x, steward.y))
        self.assertIn("Elara Harth", notice.msg)
        self.assertIn("apartment", notice.msg)
        steward_event = steward.FindObject(archname="event_obj")
        portal_event = portal.FindObject(archname="event_obj")
        self.assertEqual(
            "/interfaces/quests/lost_memories/incuna_apartment_steward.py",
            steward_event.race,
        )
        self.assertEqual(
            "/python/generic/apartment_teleport.py", portal_event.race
        )
        self.assertEqual("incuna", portal_event.slaying)
        self.assertIn("dormant", portal.msg)
        self.assertIn("Elara Harth", portal.msg)

        packets = activator.Controller().s_packets
        packets.clear()
        origin_map = activator.map.path
        self.walk_into_portal(portal)
        self.assertEqual(origin_map, activator.map.path)
        self.assertEqual((10, 1), (activator.x, activator.y))
        self.assertTrue(any(
            b"You don't own an apartment here!" in packet
            for packet in packets
        ))

    def test_brelend_redirects_until_apartment_tutorial_is_complete(self):
        memories = QuestManager(activator, lost_memories)
        memories.start("apartment_tutorial")
        activator.TeleportTo("/shattered_islands/world_4_84", 7, 7)
        brelend = self.find_map_object(
            lambda obj: obj.name == "Brelend Lee"
        )
        if brelend is None:
            for obj in activator.map.Objects(7, 7):
                brelend = obj.FindObject(name="Brelend Lee")
                if brelend:
                    break
        self.assertIsNotNone(brelend)

        packets = activator.Controller().s_packets
        packets.clear()
        self.run_brelend_interface(brelend, "hello")
        conversation = b"".join(packets)
        self.assertIn(b"Brelend pauses before beginning the service", conversation)
        self.assertIn(b"Elara Harth", conversation)
        self.assertNotIn(b"I need help recovering my memories", conversation)

    def test_incuna_beach_nook_persists_and_completes_at_hammock(self):
        region = apartments_info["incuna"]
        info = region["apartments"]["cheap"]
        apartment, created = ensure_incuna_apartment(activator)
        self.assertTrue(created)
        expected_path = activator.map.GetPath(
            info["path"], True, activator.name
        )
        self.assertIsNotNone(Atrinik.ReadyMap(expected_path))
        memories = QuestManager(activator, lost_memories)
        memories.start("apartment_tutorial")

        activator.TeleportTo("/shattered_islands/world_4_84", 16, 18)
        portal = self.find_map_object(
            lambda obj: obj.name == "Incuna beach nook portal"
        )
        self.assertIsNotNone(portal)
        self.walk_into_portal(portal)
        self.assertEqual(expected_path, activator.map.path)
        self.assertEqual((11, 10), (activator.x, activator.y))

        sand_tiles = self.find_map_objects(
            lambda obj: obj.arch.name.startswith("floor_ruin")
        )
        grass_tiles = self.find_map_objects(
            lambda obj: obj.arch.name.startswith("grassd_")
        )
        chests = self.find_map_objects(
            lambda obj: obj.arch.name == "chest_sw_1"
        )
        hammocks = self.find_map_objects(
            lambda obj: obj.name == "hammock to reality"
        )
        self.assertEqual(9, len(sand_tiles))
        self.assertEqual(12, len(grass_tiles))
        self.assertEqual(1, len(chests))
        self.assertEqual(2, len(hammocks))
        self.assertEqual(
            {"hammock_a", "hammock_b"},
            {hammock.arch.name for hammock in hammocks},
        )
        self.assertEqual(
            {"hammock_a.101", "hammock_b.101"},
            {hammock.face[0] for hammock in hammocks},
        )
        for hammock in hammocks:
            self.assertTrue(self.event_with_race(
                hammock,
                "/python/items/lost_memories_apartment_bed.py",
            ))

        marker = activator.map.CreateObject(
            "sword", activator.x, activator.y
        )
        marker.title = "issue 105 persistence marker"
        hammock = hammocks[0]
        activator.SetPosition(hammock.x, hammock.y)
        activator.Apply(hammock)
        self.assertTrue(memories.completed("apartment_tutorial"))
        self.assertEqual(
            Atrinik.QUEST_STATUS_STARTED,
            memories.get_quest_status("speak_priest"),
        )
        self.assertEqual(expected_path, activator.Controller().savebed_map)
        self.assertEqual(
            (hammock.x, hammock.y),
            (activator.Controller().bed_x, activator.Controller().bed_y),
        )
        activator.map.Save()
        activator.Controller().Save()
        serialized_apartment = apartment.Save()
        with open(expected_path, "r", encoding="utf-8") as saved:
            self.assertIn("title issue 105 persistence marker", saved.read())

        apartment_exit = self.find_map_object(
            lambda obj: self.event_with_race(
                obj, "/python/generic/apartment_out.py"
            )
        )
        self.assertIsNotNone(apartment_exit)
        # Apartment exits are trigger events; use the same movement path as
        # a player entering the exit instead of bypassing the event with Apply.
        self.walk_into_portal(apartment_exit)
        self.assertEqual("/shattered_islands/world_4_84", activator.map.path)
        self.assertEqual((10, 1), (activator.x, activator.y))

        # Rebuild the apartment entitlement from its saved inventory
        # representation, as player loading does during a relog.
        serialized_fields = serialized_apartment.splitlines()[1:-1]
        reconstructed_apartment = Atrinik.CreateObject("player_info")
        reconstructed_apartment.Load(
            "{}\n".format("\n".join(serialized_fields))
        )
        self.assertIsNotNone(reconstructed_apartment)
        self.assertEqual("cheap", reconstructed_apartment.slaying)
        self.assertEqual(
            "/shattered_islands/world_4_84",
            reconstructed_apartment.race,
        )
        self.assertEqual(
            (10, 1),
            (
                reconstructed_apartment.last_sp,
                reconstructed_apartment.last_grace,
            ),
        )
        reconstructed_apartment.Destroy()

        # Force the vacated private map through the normal server swap path.
        # Re-entry must load the marker from disk, not the resident map object.
        del (
            marker, sand_tiles, grass_tiles, chests, hammocks, hammock,
            apartment_exit,
        )
        apartment_map = Atrinik.ReadyMap(expected_path)
        self.assertIsNotNone(apartment_map)
        apartment_map.timeout = 1
        del apartment_map
        if self.npc:
            self.npc.Destroy()
            self.npc = None
        simulate_server(count=2, wait=False)

        portal = self.find_map_object(
            lambda obj: obj.name == "Incuna beach nook portal"
        )
        self.walk_into_portal(portal)
        self.assertEqual(expected_path, activator.map.path)
        persisted = self.find_map_object(
            lambda obj: obj.title == "issue 105 persistence marker"
        )
        self.assertIsNotNone(persisted)
        persisted.Destroy()

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
