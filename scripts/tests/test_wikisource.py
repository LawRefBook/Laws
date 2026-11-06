"""在仓库根目录运行：.venv/bin/python -m unittest discover scripts/tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from providers.wikisource import WikisourceProvider, base_title, folder_for_lawmaker, lawmaker_from_notes  # noqa: E402


class WikisourceTest(unittest.TestCase):

    def test_base_title(self):
        self.assertEqual(base_title("中华人民共和国增值税暂行条例实施细则 (2008年)"), "中华人民共和国增值税暂行条例实施细则")
        self.assertEqual(base_title("中华人民共和国增值税暂行条例实施细则（2011年）"), "中华人民共和国增值税暂行条例实施细则")
        self.assertEqual(base_title("中华人民共和国增值税暂行条例实施细则"), "中华人民共和国增值税暂行条例实施细则")

    def test_folder_for_lawmaker(self):
        self.assertEqual(folder_for_lawmaker("中华人民共和国财政部"), "部门规章/财政部")
        self.assertEqual(folder_for_lawmaker("[[中华人民共和国国务院]]"), "行政法规")
        self.assertEqual(folder_for_lawmaker("全国人民代表大会常务委员会"), "法律")
        self.assertEqual(folder_for_lawmaker("最高人民法院、最高人民检察院"), "司法解释")
        self.assertEqual(folder_for_lawmaker("人力资源和社会保障部"), "部门规章/人力资源社会保障部")
        self.assertIsNone(folder_for_lawmaker(""))

    def test_lawmaker_from_notes(self):
        self.assertEqual(lawmaker_from_notes("（2007年3月16日第十届人民代表大会第五次会议通过　根据…修正）"), "全国人民代表大会")
        self.assertEqual(lawmaker_from_notes("（2001年…国务院令第321号公布）"), "国务院")
        self.assertEqual(lawmaker_from_notes("（最高人民法院审判委员会第1次会议通过）"), "最高人民法院")
        self.assertEqual(lawmaker_from_notes(""), "")

    def test_page_from_url(self):
        page = WikisourceProvider.page_from_url
        self.assertEqual(page("https://zh.wikisource.org/wiki/%E4%B8%AD%E5%8D%8E%E4%BA%BA%E6%B0%91%E5%85%B1%E5%92%8C%E5%9B%BD"
                              "%E4%BC%81%E4%B8%9A%E6%89%80%E5%BE%97%E7%A8%8E%E6%B3%95_(2017%E5%B9%B4)"), "中华人民共和国企业所得税法 (2017年)")
        self.assertEqual(page("https://zh.wikisource.org/zh-hant/某法_(2009年)"), "某法 (2009年)")
        self.assertEqual(page("https://zh.wikisource.org/w/index.php?title=某法_(1996年)&action=edit"), "某法 (1996年)")
        self.assertIsNone(page("https://flk.npc.gov.cn/detail"))


if __name__ == "__main__":
    unittest.main()
