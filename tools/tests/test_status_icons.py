import unittest
from pathlib import Path

from tools.validate_status_icons import validate


class StatusIconValidationTest(unittest.TestCase):
    def test_library_and_fixed_status_mapping(self):
        result = validate(Path(__file__).resolve().parents[2])
        self.assertEqual(result, {"canonical": 496, "statuses": 23})


if __name__ == "__main__":
    unittest.main()
