"""Start the first Incuna objective after the Deserted Island voyage."""

from Atrinik import *
from InterfaceQuests import escaping_deserted_island, lost_memories
from QuestManager import QuestManager


def main():
    escaping = QuestManager(activator, escaping_deserted_island)
    memories = QuestManager(activator, lost_memories)

    if escaping.completed() and not memories.started():
        memories.start("speak_sam")


if activator.type == Type.PLAYER:
    main()
