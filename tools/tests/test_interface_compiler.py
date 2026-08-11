"""Regression tests for stable interface compiler identities."""

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path


TOOLS_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(TOOLS_ROOT))

from compilers.interface_compiler import InterfaceCompiler  # noqa: E402


class InterfaceCompilerTest(unittest.TestCase):
    def test_distinct_stable_npc_ids_produce_distinct_handlers(self):
        with tempfile.TemporaryDirectory() as temporary:
            maps = Path(temporary) / "maps"
            interfaces = maps / "interfaces"
            interfaces.mkdir(parents=True)
            (maps / "python").mkdir()
            (interfaces / "stable.xml").write_text(
                "<interfaces>"
                '<interface npc_id="foo-bar"/>'
                '<interface npc_id="foo.bar"/>'
                '<interface npc_id="foobar"/>'
                "</interfaces>",
                encoding="utf-8",
            )

            InterfaceCompiler({"maps": str(maps)}).compile()

            self.assertTrue((interfaces / "foo-bar.py").is_file())
            self.assertTrue((interfaces / "foo.bar.py").is_file())
            self.assertTrue((interfaces / "foobar.py").is_file())

    def test_windows_device_ids_never_become_handler_filenames(self):
        for npc_id in ("con", "aux.config", "com1", "lpt9.handler"):
            with self.subTest(npc_id=npc_id), tempfile.TemporaryDirectory() as temporary:
                maps = Path(temporary) / "maps"
                interfaces = maps / "interfaces"
                interfaces.mkdir(parents=True)
                (maps / "python").mkdir()
                (interfaces / "stable.xml").write_text(
                    '<interfaces><interface npc_id="{}"/></interfaces>'.format(npc_id),
                    encoding="utf-8",
                )

                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    InterfaceCompiler({"maps": str(maps)}).compile()

                self.assertEqual([], list(interfaces.glob("*.py")))
                self.assertIn("not a portable stable identifier", output.getvalue())


if __name__ == "__main__":
    unittest.main()
