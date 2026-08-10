from __future__ import annotations

import importlib.util
from pathlib import Path
import runpy
import sys
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
COMMON_PATH = ROOT / "maps" / "python" / "Common.py"
COMMANDS_PATH = ROOT / "maps" / "python" / "commands"


def load_common():
    spec = importlib.util.spec_from_file_location("content_test_common", COMMON_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeObject:
    def __init__(self):
        self.count = 1
        self.ratio = 0.0
        self.label = ""
        self.f_enabled = False
        self.light_color = 0xffffff
        self.loaded = []
        self.destroyed = False
        self.type = 0
        self.f_monster = False
        self.randomitems = None
        self.optional = "present"
        self.inserted = False

    def Load(self, value):
        self.loaded.append(value)

    def Destroy(self):
        self.destroyed = True

    def InsertInto(self, container):
        self.inserted = True


class DrawInfoRecorder:
    def __init__(self):
        self.messages = []

    def DrawInfo(self, message, color):
        self.messages.append((message, color))


class PythonCommandTests(unittest.TestCase):
    def setUp(self):
        self.common = load_common()

    def test_light_color_accepts_lower_and_uppercase_rgb(self):
        obj = FakeObject()

        self.common.obj_assign_attribs(obj, "light_color ff0000")
        self.assertEqual(0xff0000, obj.light_color)

        self.common.obj_assign_attribs(obj, "light_color 00FF7f")
        self.assertEqual(0x00ff7f, obj.light_color)

        self.common.obj_assign_attribs(obj, "light_color\tabcdef")
        self.assertEqual(0xabcdef, obj.light_color)

    def test_light_color_rejects_malformed_input_before_assignment(self):
        for value in ("#ff0000", "ff000", "ff00000", "gg0000"):
            with self.subTest(value=value):
                obj = FakeObject()
                with self.assertRaisesRegex(ValueError, "six hexadecimal digits"):
                    self.common.obj_assign_attribs(
                        obj, "count 2 light_color {}".format(value)
                    )
                self.assertEqual(1, obj.count)
                self.assertEqual(0xffffff, obj.light_color)

        for attribs in ('count 2 light_color', 'count 2 light_color ""'):
            with self.subTest(attribs=attribs):
                obj = FakeObject()
                with self.assertRaisesRegex(ValueError, "six hexadecimal digits"):
                    self.common.obj_assign_attribs(obj, attribs)
                self.assertEqual(1, obj.count)
                self.assertEqual(0xffffff, obj.light_color)

        for attribs in (
            "count 2 light_color  gg0000",
            "count 2 light_color\tgg0000",
            'count 2 light_color "ff0000"junk',
            'count 2 "junk" light_color',
            'count 2 label "junk light_color ff0000',
            'count 2 label junk" light_color ff0000',
            'count 2 label "junk"light_color ff0000',
        ):
            with self.subTest(attribs=attribs):
                obj = FakeObject()
                with self.assertRaisesRegex(ValueError, "six hexadecimal digits"):
                    self.common.obj_assign_attribs(obj, attribs)
                self.assertEqual(1, obj.count)
                self.assertEqual(0xffffff, obj.light_color)

    def test_unrelated_attribute_coercion_is_unchanged(self):
        obj = FakeObject()

        self.common.obj_assign_attribs(
            obj,
            'count 12 ratio 1.5 label "quoted value" enabled 0 '
            'optional None custom fallback',
        )

        self.assertEqual(12, obj.count)
        self.assertEqual(1.5, obj.ratio)
        self.assertEqual("quoted value", obj.label)
        self.assertFalse(obj.f_enabled)
        self.assertIsNone(obj.optional)
        self.assertEqual(["custom fallback"], obj.loaded)

        self.common.obj_assign_attribs(
            obj, 'label "quoted light_color value" custom light_color'
        )
        self.assertEqual("quoted light_color value", obj.label)
        self.assertEqual(["custom fallback", "custom light_color"], obj.loaded)

    def command_module(self, message, obj):
        recorder = DrawInfoRecorder()
        atrinik = types.ModuleType("Atrinik")
        atrinik.AtrinikError = type("AtrinikError", (Exception,), {})
        atrinik.COLOR_RED = 1
        atrinik.Type = types.SimpleNamespace(PLAYER=1, MONSTER=2)
        atrinik.WhatIsMessage = lambda: message
        atrinik.CreateObject = lambda archname: obj
        atrinik.FindPlayer = lambda name: None
        atrinik.pl = recorder
        atrinik.activator = obj
        obj.map = types.SimpleNamespace(Insert=lambda *args: None)
        obj.x = 0
        obj.y = 0

        return atrinik, recorder

    def test_create_destroys_object_after_malformed_color(self):
        for message in (
            "torch count 2 light_color  gg0000",
            'torch count 2 light_color "ff0000"junk',
            'torch count 2 "junk" light_color',
            'torch count 2 label "junk light_color ff0000',
            'torch count 2 label junk" light_color ff0000',
            'torch count 2 label "junk"light_color ff0000',
        ):
            with self.subTest(message=message):
                obj = FakeObject()
                atrinik, recorder = self.command_module(message, obj)

                with mock.patch.dict(
                    sys.modules, {"Atrinik": atrinik, "Common": self.common}
                ):
                    runpy.run_path(
                        str(COMMANDS_PATH / "create.py"), run_name="create_test"
                    )

                self.assertTrue(obj.destroyed)
                self.assertFalse(obj.inserted)
                self.assertEqual(1, obj.count)
                self.assertEqual(
                    [
                        (
                            "light_color must be exactly six hexadecimal digits "
                            "(RRGGBB).",
                            1,
                        )
                    ],
                    recorder.messages,
                )

    def test_create_assigns_hexadecimal_color(self):
        obj = FakeObject()
        atrinik, recorder = self.command_module("torch light_color ff0000", obj)

        with mock.patch.dict(
            sys.modules, {"Atrinik": atrinik, "Common": self.common}
        ):
            runpy.run_path(str(COMMANDS_PATH / "create.py"), run_name="create_test")

        self.assertEqual(0xff0000, obj.light_color)
        self.assertTrue(obj.inserted)
        self.assertEqual([], recorder.messages)

    def test_create_preserves_light_color_in_unrelated_values(self):
        obj = FakeObject()
        atrinik, recorder = self.command_module(
            'torch label "quoted light_color value" custom light_color', obj
        )

        with mock.patch.dict(
            sys.modules, {"Atrinik": atrinik, "Common": self.common}
        ):
            runpy.run_path(str(COMMANDS_PATH / "create.py"), run_name="create_test")

        self.assertEqual("quoted light_color value", obj.label)
        self.assertEqual(["custom light_color"], obj.loaded)
        self.assertTrue(obj.inserted)
        self.assertEqual([], recorder.messages)

    def test_patch_reports_malformed_color_without_mutation(self):
        for message in (
            "me count 2 light_color  gg0000",
            'me count 2 light_color "ff0000"junk',
            'me count 2 "junk" light_color',
            'me count 2 label "junk light_color ff0000',
            'me count 2 label junk" light_color ff0000',
            'me count 2 label "junk"light_color ff0000',
        ):
            with self.subTest(message=message):
                obj = FakeObject()
                atrinik, recorder = self.command_module(message, obj)

                with mock.patch.dict(
                    sys.modules, {"Atrinik": atrinik, "Common": self.common}
                ):
                    runpy.run_path(
                        str(COMMANDS_PATH / "patch.py"), run_name="patch_test"
                    )

                self.assertEqual(0xffffff, obj.light_color)
                self.assertEqual(1, obj.count)
                self.assertEqual(
                    [
                        (
                            "light_color must be exactly six hexadecimal digits "
                            "(RRGGBB).",
                            1,
                        )
                    ],
                    recorder.messages,
                )

    def test_patch_assigns_hexadecimal_color(self):
        obj = FakeObject()
        atrinik, recorder = self.command_module("me light_color 00FF7f", obj)

        with mock.patch.dict(
            sys.modules, {"Atrinik": atrinik, "Common": self.common}
        ):
            runpy.run_path(str(COMMANDS_PATH / "patch.py"), run_name="patch_test")

        self.assertEqual(0x00ff7f, obj.light_color)
        self.assertEqual([], recorder.messages)

    def test_patch_preserves_light_color_in_unrelated_values(self):
        obj = FakeObject()
        atrinik, recorder = self.command_module(
            'me label "quoted light_color value" custom light_color', obj
        )

        with mock.patch.dict(
            sys.modules, {"Atrinik": atrinik, "Common": self.common}
        ):
            runpy.run_path(str(COMMANDS_PATH / "patch.py"), run_name="patch_test")

        self.assertEqual("quoted light_color value", obj.label)
        self.assertEqual(["custom light_color"], obj.loaded)
        self.assertEqual([], recorder.messages)


if __name__ == "__main__":
    unittest.main()
