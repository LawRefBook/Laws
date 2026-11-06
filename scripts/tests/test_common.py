"""在仓库根目录运行：.venv/bin/python -m unittest discover scripts/tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import REGION_CODE_MAP, parse_regions  # noqa: E402


class ParseRegionsTest(unittest.TestCase):

    def test_range(self):
        regions = parse_regions("7-31")
        self.assertEqual(regions, list(REGION_CODE_MAP)[6:])
        self.assertEqual((regions[0], regions[-1], len(regions)), ("吉林", "新疆", 25))
        self.assertEqual(parse_regions("7 - 9"), ["吉林", "黑龙江", "上海"])

    def test_mixed_and_dedup(self):
        self.assertEqual(parse_regions("北京 3，5-6、5 北京"), ["北京", "河北", "内蒙古", "辽宁"])
        self.assertEqual(parse_regions("31"), ["新疆"])

    def test_invalid(self):
        for spec in ("0", "32", "9-7", "1-40", "火星", "", " , "):
            with self.assertRaises(ValueError, msg=spec):
                parse_regions(spec)


if __name__ == "__main__":
    unittest.main()
