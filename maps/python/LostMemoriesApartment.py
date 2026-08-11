"""State transitions for the Lost Memories apartment tutorial."""

import Atrinik

from Apartments import apartments_info
from InterfaceQuests import lost_memories
from Notification import Notification
from QuestManager import QuestManager


APARTMENT_REGION = "strakewood_island"
APARTMENT_TIER = "cheap"
APARTMENT_TAG = apartments_info[APARTMENT_REGION]["tag"]
TUTORIAL_PART = "apartment_tutorial"
NEXT_PART = "speak_priest"


def find_strakewood_apartment(player):
    """Return the player's existing Strakewood apartment entitlement."""

    return player.FindObject(archname="player_info", name=APARTMENT_TAG)


def ensure_strakewood_apartment(player, creator=None):
    """Create the free cheap entitlement once, preserving any existing tier."""

    apartment = find_strakewood_apartment(player)
    if apartment:
        return apartment, False

    creator = creator or player.CreateObject
    apartment = None
    try:
        apartment = creator("player_info")
        if not apartment:
            return None, False
        apartment.name = APARTMENT_TAG
        apartment.slaying = APARTMENT_TIER
    except Exception:
        if apartment:
            apartment.Destroy()
        return None, False

    verified = find_strakewood_apartment(player)
    if verified != apartment or verified.slaying != APARTMENT_TIER:
        apartment.Destroy()
        return None, False

    return apartment, True


def notify_apartment_entry(player):
    """Show the apartment lesson after a tutorial owner enters their map."""

    manager = QuestManager(player, lost_memories)
    if (not manager.started() or
            manager.get_quest_status(TUTORIAL_PART) !=
            Atrinik.QUEST_STATUS_STARTED):
        return False
    if not find_strakewood_apartment(player):
        return False

    Notification(
        player.Controller(),
        "Tutorial Available: Apartments",
        "/help basics_apartments",
        "?HELP",
        90000,
    )
    return True


def complete_apartment_tutorial(player):
    """Advance to the priest only after an entitled owner uses the bed."""

    manager = QuestManager(player, lost_memories)
    if (not manager.started() or
            manager.get_quest_status(TUTORIAL_PART) !=
            Atrinik.QUEST_STATUS_STARTED):
        return False
    if not find_strakewood_apartment(player):
        return False

    if not manager.started(NEXT_PART):
        manager.start(NEXT_PART)
    if (manager.get_quest_status(NEXT_PART) !=
            Atrinik.QUEST_STATUS_STARTED):
        return False

    manager.complete(TUTORIAL_PART)
    return manager.completed(TUTORIAL_PART)
