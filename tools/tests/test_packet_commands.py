from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
PACKET_PATH = ROOT / "maps" / "python" / "Packet.py"
NOTIFICATION_COMMAND = 26026
MAPSTATS_COMMAND = 12012


def load_packet():
    atrinik = types.ModuleType("Atrinik")
    atrinik.CLIENT_CMD_NOTIFICATION = NOTIFICATION_COMMAND
    atrinik.CLIENT_CMD_MAPSTATS = MAPSTATS_COMMAND
    spec = importlib.util.spec_from_file_location("content_test_packet", PACKET_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {"Atrinik": atrinik}):
        spec.loader.exec_module(module)
    return module


class RecordingPlayer:
    def __init__(self):
        self.packets = []

    def SendPacket(self, command, fmt, *data):
        self.packets.append((command, fmt, data))


class PacketCommandTests(unittest.TestCase):
    def setUp(self):
        self.packet = load_packet()
        self.player = RecordingPlayer()

    def test_notification_uses_exported_command_and_preserves_optional_fields(self):
        cases = (
            (
                {},
                (NOTIFICATION_COMMAND, "Bs", (0, "Message")),
            ),
            (
                {"action": "apply"},
                (NOTIFICATION_COMMAND, "BsBs", (0, "Message", 1, "apply")),
            ),
            (
                {"shortcut": "?HELP", "delay": 4000},
                (NOTIFICATION_COMMAND, "BsBi", (0, "Message", 3, 4000)),
            ),
            (
                {"action": "apply", "shortcut": "?HELP", "delay": 120000},
                (
                    NOTIFICATION_COMMAND,
                    "BsBsBsBi",
                    (0, "Message", 1, "apply", 2, "?HELP", 3, 120000),
                ),
            ),
        )

        for kwargs, expected in cases:
            with self.subTest(kwargs=kwargs):
                self.player.packets.clear()
                self.packet.Notification(self.player, "Message", **kwargs)
                self.assertEqual([expected], self.player.packets)

    def test_map_stats_uses_exported_command_and_preserves_field_order(self):
        cases = (
            ({}, (MAPSTATS_COMMAND, "", ())),
            (
                {"name": "The Lake", "music": "lake.ogg", "weather": "rain"},
                (
                    MAPSTATS_COMMAND,
                    "BsBsBs",
                    (1, "The Lake", 2, "lake.ogg", 3, "rain"),
                ),
            ),
            (
                {"music": "lake.ogg"},
                (MAPSTATS_COMMAND, "Bs", (2, "lake.ogg")),
            ),
        )

        for kwargs, expected in cases:
            with self.subTest(kwargs=kwargs):
                self.player.packets.clear()
                self.packet.MapStats(self.player, **kwargs)
                self.assertEqual([expected], self.player.packets)


if __name__ == "__main__":
    unittest.main()
