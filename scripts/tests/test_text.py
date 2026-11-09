import unittest

from lawref.dates import DATE, iso_dates, iso_of, parse_iso, to_cn
from lawref.document import body_of, canonical_filename, head_of, header_lines, law_filename, split_filename, split_stem
from lawref.numerals import cn_to_int, int_to_cn
from lawref.text import short_title, strip_prc, title_key


class TextTest(unittest.TestCase):

    def test_short_title(self):
        self.assertEqual(short_title("中华人民共和国民法典"), "民法典")
        self.assertEqual(short_title("关于适用《中华人民共和国民事诉讼法》的解释"), "关于适用《民事诉讼法》的解释")
        self.assertEqual(short_title("外国人在中华人民共和国收养子女登记办法"), "外国人在中华人民共和国收养子女登记办法")

    def test_title_key(self):
        self.assertEqual(title_key("最高人民法院关于适用〈中华人民共和国婚姻法〉若干问题的解释（三）"),
                         title_key("最高人民法院关于适用《婚姻法》若干问题的解释（三）"))
        self.assertEqual(title_key("中华人民共和国 律师法"), "律师法")

    def test_strip_prc(self):
        self.assertEqual(strip_prc("中华人民共和国国务院"), "国务院")
        self.assertEqual(strip_prc("在中华人民共和国境内"), "在中华人民共和国境内")


class DatesTest(unittest.TestCase):

    def test_conversions(self):
        self.assertEqual(iso_of(DATE.search("于2020年1月2日通过")), "2020-01-02")
        self.assertEqual(to_cn("2020-01-02"), "2020年1月2日")
        self.assertEqual(iso_dates("2001年10月27日修正 2020年1月1日施行"), ["2001-10-27", "2020-01-01"])

    def test_parse_iso(self):
        self.assertIsNotNone(parse_iso("2020-01-02"))
        for text in (None, "", "2020-1-2", "2020-01-02 00:00:00"):
            self.assertIsNone(parse_iso(text), text)


class NumeralsTest(unittest.TestCase):

    def test_round_trip(self):
        for n in (1, 9, 10, 11, 20, 21, 99, 100, 101, 105, 110, 999, 1000, 1001, 1010, 1234):
            self.assertEqual(cn_to_int(int_to_cn(n)), n, n)

    def test_examples(self):
        self.assertEqual(int_to_cn(105), "一百零五")
        self.assertEqual(int_to_cn(10), "十")
        self.assertEqual(cn_to_int("二〇二〇"), 2020)
        self.assertEqual(cn_to_int("十二"), 12)


class DocumentTest(unittest.TestCase):

    def test_split_filename(self):
        self.assertEqual(split_filename("监狱法(2012-10-26).md"), ("监狱法", "2012-10-26"))
        self.assertEqual(split_filename("刑法修正案（十）.md"), ("刑法修正案（十）", None))
        self.assertEqual(split_stem("某法(2000-01-01)(2010-01-01)"), ("某法(2000-01-01)", "2010-01-01"))

    def test_law_filename(self):
        self.assertEqual(law_filename("中华人民共和国监狱法", "2012-10-26"), "监狱法(2012-10-26).md")
        self.assertEqual(law_filename("核苷酸和/或氨基酸序列表"), "核苷酸和／或氨基酸序列表.md")
        self.assertEqual(canonical_filename("中华人民共和国监狱法(2012-10-26).md"), "监狱法(2012-10-26).md")
        self.assertEqual(canonical_filename("监狱法.txt"), "监狱法.txt")

    def test_sections(self):
        text = "# 某法\n\n2020年1月1日 通过\n\n<!-- INFO END -->\n\n第一条 内容\n"
        self.assertEqual(head_of(text), "# 某法\n\n2020年1月1日 通过\n\n")
        self.assertEqual(body_of(text), "\n\n第一条 内容\n")
        self.assertEqual(header_lines(text), ["2020年1月1日 通过"])
        # 没有 INFO END：头部和正文都是全文
        self.assertEqual(head_of("# 某法\n内容"), "# 某法\n内容")
        self.assertEqual(body_of("# 某法\n内容"), "# 某法\n内容")
