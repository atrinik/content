"""Regression tests for stable interface compiler identities."""

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


if __name__ == "__main__":
    unittest.main()
