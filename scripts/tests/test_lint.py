"""在仓库根目录运行：.venv/bin/python -m unittest discover scripts/tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lint import fix_text, lint_text  # noqa: E402


def doc(*header, body="第一条 内容"):
    return "\n\n".join(["# 某条例", *header, "<!-- INFO END -->", body]) + "\n"


class FixTextTest(unittest.TestCase):

    def assertFixed(self, before, after):
        fixed = fix_text(before)
        self.assertEqual(fixed, after)
        self.assertEqual([p for p in lint_text(Path("某条例.md"), fixed) if p.error], [])
        self.assertEqual(fix_text(fixed), fixed)  # 再修一次不变

    def test_dangling_and_trailing_paren(self):
        self.assertFixed(
            doc("2000年1月1日 某会议通过　", "2010年1月1日 某会议第一次修正  根据", "2020年1月1日 某会议第二次修正）"),
            doc("2000年1月1日 某会议通过", "2010年1月1日 某会议第一次修正", "2020年1月1日 某会议第二次修正"))

    def test_leading_paren(self):
        self.assertFixed(doc("（2000年1月1日 某会议通过", "2010年1月1日 某会议修正）"),
                         doc("2000年1月1日 某会议通过", "2010年1月1日 某会议修正"))

    def test_balanced_paren_kept(self):
        line = "1994年5月12日 某会议《关于修改（某条例）的决定》修正"
        self.assertEqual(fix_text(doc(line)), doc(line))

    def test_merged_header_split(self):
        self.assertFixed(
            doc("2012年7月27日 某会议《某决定》第四次修正  2022年12月2日某会议修订）"),
            doc("2012年7月27日 某会议《某决定》第四次修正", "2022年12月2日 某会议修订"))
        self.assertFixed(doc("1988年7月1日 某会议通过根据1994年5月12日某会议修正"),
                         doc("1988年7月1日 某会议通过", "1994年5月12日 某会议修正"))

    def test_date_inside_text_not_split(self):
        line = "2000年1月1日 某会议通过 自2000年3月1日起施行"
        self.assertEqual(fix_text(doc(line)), doc(line))

    def test_space_after_date(self):
        self.assertFixed(doc("2010年12月23日北京市某会议修正"), doc("2010年12月23日 北京市某会议修正"))

    def test_invisible_chars_removed_but_not_replacement_char(self):
        self.assertEqual(fix_text(doc("2000年1月1日 通过", body="第一条​ 内容﻿")),
                         doc("2000年1月1日 通过", body="第一条 内容"))
        text = doc("2000年1月1日 通过", body="第一条 内容�")
        self.assertEqual(fix_text(text), text)

    def test_private_use_chars(self):
        self.assertEqual(fix_text(doc("2000年1月1日 通过", body="（GB9959\ue0102-2001）不低于1\ue0104米。\ue004\n\n第二条 \ue5f9内容\n\n\uf0b7保障")),
                         doc("2000年1月1日 通过", body="（GB9959.2-2001）不低于1.4米。\n\n第二条 内容\n\n保障"))
        # 夹在两个字中间的可能是生僻字，不动
        text = doc("2000年1月1日 通过", body="第一条 张\ue123三")
        self.assertEqual(fix_text(text), text)

    def test_body_untouched(self):
        text = doc("2000年1月1日 通过", body="第一条 依照本条例，根据")
        self.assertEqual(fix_text(text), text)


if __name__ == "__main__":
    unittest.main()
