"""在仓库根目录运行：.venv/bin/python -m unittest discover scripts/tests"""
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

from docx import Document  # noqa: E402

from scrape import (canonical_filename, law_filename, lint, organize_target,  # noqa: E402
                    should_ignore, with_effective_date)
from model.law import LawListItem  # noqa: E402
from parsers.content import (ContentParser, drop_announcement, drop_toc,  # noqa: E402
                             normalize_heading, parse_desc)
from common import is_traditional  # noqa: E402
from parsers.epub import EpubParser  # noqa: E402
from parsers.html import HtmlParser  # noqa: E402
from providers.gov_regulation_database import dated_note, dates_from_note  # noqa: E402
from parsers.word import WordParser  # noqa: E402
from providers.cache_provider import CacheManager  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def parse(title, desc, content):
    return ContentParser().parse(title, desc, content)


class DescTest(unittest.TestCase):

    def test_trailing_paren(self):
        self.assertEqual(
            parse_desc("（2026年5月15日中华人民共和国国务院令第838号第二次修订）"),
            ["2026年5月15日 中华人民共和国国务院令第838号第二次修订"])

    def test_split_by_date(self):
        self.assertEqual(
            parse_desc("（2017年10月27日秦皇岛市第十四届人民代表大会常务委员会第五次会议通过并经"
                       "2018年3月29日河北省第十三届人民代表大会常务委员会第二次会议批准　根据"
                       "2024年7月25日《决定》修正。）"),
            ["2017年10月27日 秦皇岛市第十四届人民代表大会常务委员会第五次会议通过",
             "2018年3月29日 河北省第十三届人民代表大会常务委员会第二次会议批准",
             "2024年7月25日 《决定》修正"])

    def test_keep_paired_paren(self):
        self.assertEqual(parse_desc("（2020年1月1日公布《办法（试行）》）"), ["2020年1月1日 公布《办法（试行）》"])

    def test_spaced_date(self):
        self.assertEqual(parse_desc("（2014 年 5 月 29 日四川省人大常委会通过）"), ["2014年5月29日 四川省人大常委会通过"])

    def test_effective_date(self):
        self.assertEqual(parse_desc("（2020年1月1日公布 自2020年3月1日起施行）"),
                         ["2020年1月1日 公布", "2020年3月1日 施行"])


class TocTest(unittest.TestCase):

    def test_marked_toc(self):
        lines = ["目　录", "序言", "第一章 总则", "第二章 附则", "序言", "正文", "第一章 总则", "第一条 内容"]
        self.assertEqual(drop_toc(lines), ["序言", "正文", "第一章 总则", "第一条 内容"])

    def test_toc_without_chapter_numbers(self):
        lines = ["目 录", "总则", "协商代表", "第一章 总则", "第一条 内容"]
        self.assertEqual(drop_toc(lines), ["第一章 总则", "第一条 内容"])

    def test_broken_toc_keeps_articles(self):
        # 原文目录从第二章开始，不能把第一章和条文一起删掉
        lines = ["目 录", "第二章 规划", "第一节 森林", "第一章 总 则", "第一条 内容", "第二条 内容", "第二章 规划", "第三条 内容"]
        self.assertEqual(drop_toc(lines), ["第一章 总 则", "第一条 内容", "第二条 内容", "第二章 规划", "第三条 内容"])

    def test_body_starting_with_mulu(self):
        lines = ["第一章 总则", "第一条 内容", "目录管理的范围包括下列事项", "第二条 内容"]
        self.assertEqual(drop_toc(lines), lines)

    def test_unmarked_toc(self):
        lines = ["第一章 总则", "第二章 附则", "第一章 总 则", "第一条 内容", "第二章 附 则", "第二条 内容"]
        self.assertEqual(drop_toc(lines), lines[2:])

    def test_toc_in_parse(self):
        out = parse("某条例", "", ["目录", "第一章　总　　则", "第二章　附则", "第一章　总　　则", "第一条　内容", "第二章　附则", "第二条　内容"])
        self.assertEqual(out, ["# 某条例", "<!-- INFO END -->", "## 第一章 总则", "第一条 内容", "## 第二章 附则", "第二条 内容"])


class CleanupTest(unittest.TestCase):

    def test_punctuation(self):
        out = parse("某规定", "", ["第一条 为了保证实施,根据《某法》,制定本办法:", "(一)审理(包括调解)笔录;", "第二条 会议于10:30开始。"])
        self.assertEqual(out[2:], ["第一条 为了保证实施，根据《某法》，制定本办法：", "（一）审理(包括调解)笔录；", "第二条 会议于10:30开始。"])

    def test_distribution_table_dropped(self):
        out = parse("某规则", "", ["第一条 内容", "<!-- TABLE -->", "| 主送：各级人民检察院。 抄送：本院领导同志。  |", "|-----|",
                                 "| 最高人民检察院办公厅 2019年12月30日印发  |", "<!-- TABLE END -->"])
        self.assertEqual(out[2:], ["第一条 内容"])


class AnnouncementTest(unittest.TestCase):

    def test_with_fashi(self):
        lines = ["公告", "《解释》已于2020年通过，现予公布。", "法释〔2020〕1号", "第一条 内容"]
        self.assertEqual(drop_announcement(lines), ["第一条 内容"])

    def test_without_fashi_keeps_content(self):
        lines = ["第八条 内容", "公告河砂可采区时，应当明确可采区的具体地点。", "第九条 内容"]
        self.assertEqual(drop_announcement(lines), lines)


class HeadingTest(unittest.TestCase):

    def test_normalize(self):
        self.assertEqual(normalize_heading("序　言"), "序言")
        self.assertEqual(normalize_heading("第一章　总　　则"), "第一章 总则")
        self.assertEqual(normalize_heading("第一章规定的情形，适用本条例。"), "第一章规定的情形，适用本条例。")

    def test_levels_follow_parents(self):
        out = parse("法典", "", [
            "序言", "正文",
            "第一编 总则", "第一章 基本规定", "第一节 一般规定", "第一条 内容",
            "第二编 分则", "第一分编 通则", "第二章 一般规定", "第二条 内容", "第二分编 其他", "第三章 规定", "第一节 规定", "第三条 内容",
        ])
        headings = [line for line in out if line.startswith("##")]
        self.assertEqual(headings, [
            "## 序言",
            "## 第一编 总则", "### 第一章 基本规定", "#### 第一节 一般规定",
            "## 第二编 分则", "### 第一分编 通则", "#### 第二章 一般规定", "### 第二分编 其他", "#### 第三章 规定", "##### 第一节 规定",
        ])

    def test_title_removed_from_body(self):
        out = parse("巴中市人民代表大会及其常务委员会立法条例", "", ["巴中市人民代表大会及其常务委员会 立法条例", "第一条 内容"])
        self.assertEqual(out[2:], ["第一条 内容"])
        out = parse("大同市人民代表大会常务委员会讨论决定重大事项的规定", "",
                    ["大同市人民代表大会常务委员会", "讨论决定重大事项的规定", "第一条 内容"])
        self.assertEqual(out[2:], ["第一条 内容"])


class WordParserTest(unittest.TestCase):

    def test_hyperlink_text_kept(self):
        from docx.oxml.ns import qn
        from docx.oxml import OxmlElement
        document = Document()
        p = document.add_paragraph("（二）具有")
        link = OxmlElement("w:hyperlink")
        run = OxmlElement("w:r")
        text = OxmlElement("w:t")
        text.text = "刑事诉讼法"
        run.append(text)
        link.append(run)
        p._p.append(link)
        p.add_run("第十六条规定的情形之一的。")
        _, _, content = WordParser().parse_document(document, "某规则")
        self.assertEqual(content, ["（二）具有刑事诉讼法第十六条规定的情形之一的。"])

    def parse_paragraphs(self, title, paragraphs):
        document = Document()
        for text in paragraphs:
            document.add_paragraph(text)
        return WordParser().parse_document(document, title)

    def test_blank_paragraphs_and_invisible_chars(self):
        _, desc, content = self.parse_paragraphs("某条例", ["", "某条例", "​", "（2020年1月1日通过）", "", "第一条　内容"])
        self.assertEqual(desc, "（2020年1月1日通过）")
        self.assertEqual(content, ["某条例", "第一条 内容"])

    def test_desc_without_closing_paren_ends_at_first_article(self):
        _, desc, content = self.parse_paragraphs("大同市规定", [
            "大同市人民代表大会常务委员会\ue003", "规定", "（2000年3月2日通过\u30002004年9月25日批准）\ue003", "\ue004", "第一条 内容"])
        self.assertEqual(desc, "（2000年3月2日通过 2004年9月25日批准）")
        self.assertEqual(content, ["大同市人民代表大会常务委员会", "规定", "第一条 内容"])
        _, desc, content = self.parse_paragraphs("某条例", ["（2000年3月2日通过", "第一条 内容"])
        self.assertEqual((desc, content), ("（2000年3月2日通过", ["第一条 内容"]))

    def test_auto_numbering(self):
        from docx.oxml import parse_xml
        document = Document()
        numbering = document.part.numbering_part.element
        w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
        numbering.append(parse_xml(
            f'<w:abstractNum {w} w:abstractNumId="90"><w:lvl w:ilvl="0"><w:start w:val="1"/>'
            '<w:numFmt w:val="chineseCounting"/><w:lvlText w:val="第%1章"/></w:lvl>'
            '<w:lvl w:ilvl="1"><w:start w:val="1"/><w:numFmt w:val="chineseCounting"/><w:lvlText w:val="（%2）"/></w:lvl></w:abstractNum>'))
        numbering.append(parse_xml(f'<w:num {w} w:numId="90"><w:abstractNumId w:val="90"/></w:num>'))
        numbering.append(parse_xml(f'<w:abstractNum {w} w:abstractNumId="91"><w:lvl w:ilvl="0"><w:start w:val="12"/>'
                                   '<w:numFmt w:val="taiwaneseCountingThousand"/><w:lvlText w:val="第%1条"/></w:lvl></w:abstractNum>'))
        numbering.append(parse_xml(f'<w:num {w} w:numId="91"><w:abstractNumId w:val="91"/></w:num>'))
        for text, num_id, ilvl in (("总则", 90, 0), ("内容", 90, 1), ("内容", 90, 1), ("附则", 90, 0), ("内容", 90, 1),
                                   ("内容", 91, 0), ("没有编号", None, None)):
            p = document.add_paragraph(text)
            if num_id is not None:
                num_pr = p._p.get_or_add_pPr().get_or_add_numPr()
                num_pr.get_or_add_numId().val = num_id
                num_pr.get_or_add_ilvl().val = ilvl
        _, _, content = WordParser().parse_document(document, "某条例")
        self.assertEqual(content, ["第一章 总则", "（一）内容", "（二）内容", "第二章 附则", "（一）内容", "第十二条 内容", "没有编号"])

    def test_title_and_desc_in_one_paragraph(self):
        _, desc, content = self.parse_paragraphs("河北省条例", ["河北省条例 （2017年12月1日河北省人大常委会通过）", "第一条 内容"])
        self.assertEqual(desc, "（2017年12月1日河北省人大常委会通过）")
        self.assertEqual(content, ["河北省条例", "第一条 内容"])


class FixtureTest(unittest.TestCase):
    """真实 Word 原文解析后，应与仓库里清理过的文件一字不差。"""

    def test_fixtures(self):
        docs = sorted(FIXTURES.glob("*.docx"))
        self.assertTrue(docs)
        for doc in docs:
            with self.subTest(doc.stem), tempfile.TemporaryDirectory() as tmp:
                want = doc.with_suffix(".md").read_text(encoding="utf-8")
                title = want.splitlines()[0][2:]
                _, desc, content = WordParser().parse_document(Document(str(doc)), title)
                got = CacheManager(Path(tmp)).write_law(Path("out.md"), parse(title, desc, content))
                self.assertEqual(got.read_text(encoding="utf-8").strip(), want.strip())
                self.assertEqual([p for p in lint.lint_file(got) if p.error], [])


class MainTest(unittest.TestCase):

    def test_should_ignore(self):
        self.assertTrue(should_ignore("国务院关于修改部分行政法规的决定"))
        # 刑法、民法典在仓库里手动维护
        self.assertTrue(should_ignore("中华人民共和国民法典"))
        self.assertTrue(should_ignore("中华人民共和国刑法修正案（十二）"))
        self.assertFalse(should_ignore("最高人民法院关于适用《中华人民共和国民法典》继承编的解释（一）"))
        self.assertFalse(should_ignore("全国人民代表大会常务委员会关于《中华人民共和国刑法》第三十条的解释"))

    def test_canonical_filename(self):
        self.assertEqual(canonical_filename("最高人民法院关于适用《中华人民共和国民事诉讼法》的解释(2022-04-01).md"),
                         "最高人民法院关于适用《民事诉讼法》的解释(2022-04-01).md")
        self.assertEqual(canonical_filename("最高人民法院印发《关于执行〈中华人民共和国国家赔偿法〉几个问题的解释》的通知(1996-05-06).md"),
                         "最高人民法院印发《关于执行〈国家赔偿法〉几个问题的解释》的通知(1996-05-06).md")
        self.assertEqual(canonical_filename("国际邮轮在中华人民共和国港口靠港补给的规定(2024-04-22).md"),
                         "国际邮轮在中华人民共和国港口靠港补给的规定(2024-04-22).md")

    def test_known_by_header_dates(self):
        from scrape import is_known
        known = {"人民检察院刑事诉讼规则": {"2019-12-02", "2019-12-30"}}
        item = LawListItem(id="", title="人民检察院刑事诉讼规则", released_by="", type="", publication_date="2019-12-30", in_effect_date="2019-12-30")
        self.assertTrue(is_known(item, known))
        item.publication_date = item.in_effect_date = "2026-01-01"
        self.assertFalse(is_known(item, known))

    def test_suspected_duplicate(self):
        from scrape import suspected_duplicate
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            old = tmp / "长城保护条例(2006-10-01).md"
            old.write_text("# 长城保护条例\n\n2006年10月11日 公布\n\n2006年12月1日 施行\n\n<!-- INFO END -->\n")
            same = tmp / "out" / "长城保护条例(2006-10-11).md"
            same.parent.mkdir()
            same.write_text(old.read_text())
            revised = tmp / "out" / "长城保护条例(2026-01-30).md"
            revised.write_text("# 长城保护条例\n\n2006年10月11日 公布\n\n2026年1月30日 修订\n\n<!-- INFO END -->\n")
            versions = {"长城保护条例": [old]}
            self.assertEqual(suspected_duplicate(same, versions), old)
            self.assertIsNone(suspected_duplicate(revised, versions))

    def test_with_effective_date(self):
        lines = ["# 某法", "2013年10月25日 修正", "<!-- INFO END -->", "第一条 内容"]
        self.assertEqual(with_effective_date(lines, "2014-03-15", "2013-10-25"),
                         ["# 某法", "2013年10月25日 修正", "2014年3月15日 施行", "<!-- INFO END -->", "第一条 内容"])
        self.assertEqual(with_effective_date(lines, "2013-10-25", "2013-10-25"), lines)
        with_line = lines[:2] + ["2014年3月15日 施行"] + lines[2:]
        self.assertEqual(with_effective_date(with_line, "2014-03-15", "2013-10-25"), with_line)

    def test_document_number_in_header(self):
        out = parse("某解释", "（2020年12月25日最高人民法院审判委员会第1825次会议通过）", ["法释〔2020〕23号", "第一条 内容"])
        self.assertEqual(out, ["# 某解释", "2020年12月25日 最高人民法院审判委员会第1825次会议通过", "法释〔2020〕23号",
                               "<!-- INFO END -->", "第一条 内容"])

    def test_law_filename(self):
        item = LawListItem(id="", title="中华人民共和国外国人在中华人民共和国收养子女登记办法 ", released_by="", type="", publication_date="1999-05-25")
        self.assertEqual(law_filename(item), "外国人在中华人民共和国收养子女登记办法(1999-05-25).md")

    def test_organize_target(self):
        folders = {"监狱法": {Path("行政法")}, "某法": {Path("经济法"), Path("社会法")}}
        root = SCRIPTS.parent
        self.assertEqual(organize_target(Path("法律/监狱法(2026-04-30).md"), folders)[0], root / "行政法/监狱法(2026-04-30).md")
        self.assertEqual(organize_target(Path("行政法规/新条例(2026-01-01).md"), folders)[0], root / "行政法规/新条例(2026-01-01).md")
        self.assertEqual(organize_target(Path("北京地方法规/地方性法规/北京/某条例(2026-01-01).md"), folders)[0],
                         root / "DLC/北京地方法规/地方性法规/北京/某条例(2026-01-01).md")
        self.assertEqual(organize_target(Path("司法解释/关于适用《中华人民共和国监狱法》的解释(2026-01-01).md"), folders)[0],
                         root / "司法解释/关于适用《监狱法》的解释(2026-01-01).md")
        self.assertIsNone(organize_target(Path("法律/新法(2026-01-01).md"), folders)[0])
        self.assertIsNone(organize_target(Path("法律/某法(2026-01-01).md"), folders)[0])


class LintTest(unittest.TestCase):

    def test_detects_known_defects(self):
        text = "\n\n".join([
            "# 某条例", "2020年1月1日 国务院令第1号第二次修订）", "2021年1月1日 通过 根据", "<!-- INFO END -->",
            "目 录", "序言", "第一章 总则", "第一条​ 内容",
        ])
        rules = {p.rule for p in lint.lint_text(Path("某条例(2020-01-01).md"), text) if p.error}
        self.assertEqual(rules, {"header-unbalanced-paren", "header-dangling", "toc", "preface-not-heading", "bad-char"})


def write_epub(path: Path, body: str, title: str = "某法 (1998年)"):
    """维基文库导出格式的最小 epub：封面、正文、说明页。"""
    import zipfile
    page = '<html xmlns="http://www.w3.org/1999/xhtml"><body>{}</body></html>'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", '<container><rootfiles><rootfile full-path="OPS/content.opf"/></rootfiles></container>')
        z.writestr("OPS/content.opf", f"""<package xmlns="http://www.idpf.org/2007/opf"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
            <dc:title>{title}</dc:title></metadata><manifest>
            <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
            <item id="title" href="title.xhtml" media-type="application/xhtml+xml"/>
            <item id="c0" href="c0.xhtml" media-type="application/xhtml+xml"/>
            <item id="about" href="about.xhtml" media-type="application/xhtml+xml"/></manifest>
            <spine><itemref idref="title"/><itemref idref="c0"/><itemref idref="about"/></spine></package>""")
        z.writestr("OPS/nav.xhtml", page.format("<p>第一条 目录</p>"))
        z.writestr("OPS/title.xhtml", page.format(f"<p>{title}</p><p>以2026年11月4日从维基文库导出</p>"))
        z.writestr("OPS/c0.xhtml", page.format(body))
        z.writestr("OPS/about.xhtml", page.format("<p>We distribute our books for free.</p>"))


class EpubTest(unittest.TestCase):

    def test_wikisource(self):
        body = """
            <table><tr><td>← 某法 (1997年)</td><td>某法</td><td>某法 (1999年) →</td></tr></table>
            <table><tr><td>（1979年7月1日第五届全国人民代表大会第二次会议通过　1997年3月14日修订）
                <ul><li class="noprint">姊妹计划: 数据项</li></ul></td></tr></table>
            <h2>第一编　总则</h2><h3>第一章　任务</h3>
            <p>第一条 为了惩罚犯罪，制定本法。<sup>[1]</sup></p><p>第二条 内容。</p>
            <p>本作品是由全国人民代表大会制定的基本法律。</p>
            <table class="navbox-inner"><tr><td><p>第三条 导航框里的不算</p></td></tr></table>"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "某法.epub"
            write_epub(path, body)
            title, desc, content = EpubParser().parse_document(path)
        self.assertEqual(title, "某法")
        self.assertEqual(parse(title, desc, content), [
            "# 某法",
            "1979年7月1日 第五届全国人民代表大会第二次会议通过",
            "1997年3月14日 修订",
            "<!-- INFO END -->",
            "## 第一编 总则",
            "### 第一章 任务",
            "第一条 为了惩罚犯罪，制定本法。",
            "第二条 内容。",
        ])

    def test_traditional_converted(self):
        body = """
            <table><tr><td>（一九五四年九月二十日第一屆全國人民代表大會第一次會議通過）</td></tr></table>
            <h2>第一章\u3000總綱</h2>
            <p>第一條 中華人民共和國是工人階級領導的、以工農聯盟為基礎的人民民主國家。</p>
            <p>第二條 中華人民共和國的一切權力屬於人民。</p>"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "憲法.epub"
            write_epub(path, body, title="中華人民共和國憲法 (1954年)")
            title, desc, content = EpubParser().parse_document(path)
        self.assertEqual(title, "中华人民共和国宪法")
        self.assertEqual(content, ["第一章 总纲", "第一条 中华人民共和国是工人阶级领导的、以工农联盟为基础的人民民主国家。",
                                   "第二条 中华人民共和国的一切权力属于人民。"])

    def test_simplified_untouched(self):
        # 简体文本不转换，「著作权」「乾」这类字保持原样
        self.assertFalse(is_traditional("第一条 为了保护文学、艺术和科学作品作者的著作权，以及与著作权有关的权益，乾坤，征收，制定本法。"))
        self.assertTrue(is_traditional("第一條 中華人民共和國是工人階級領導的、以工農聯盟為基礎的人民民主國家。"))


class AmendmentTest(unittest.TestCase):

    def test_amendment_lines_not_articles(self):
        from parsers.content import normalize_article
        self.assertEqual(normalize_article("第二十二条改为第二十一条，修改为：“内容”"), "第二十二条改为第二十一条，修改为：“内容”")
        self.assertEqual(normalize_article("第六十二条第一项修改为：“内容”"), "第六十二条第一项修改为：“内容”")
        self.assertEqual(normalize_article("第六十九条中的“甲”修改为“乙”。"), "第六十九条中的“甲”修改为“乙”。")
        self.assertEqual(normalize_article("第一条为了规范，制定本办法。"), "第一条 为了规范，制定本办法。")
        self.assertEqual(normalize_article("第一条　内容"), "第一条 内容")

class GovRegulationTest(unittest.TestCase):

    def test_dates_from_note(self):
        self.assertEqual(dates_from_note("（2023年8月23日中华人民共和国教育部令第53号公布\u3000自2023年10月15日起施行）"),
                         ("2023-08-23", "2023-10-15"))
        # 修正过的取最后一次修正的日期
        self.assertEqual(dates_from_note("(2012年12月19日公安部令第125号发布 根据2014年6月29日公安部令第132号第一次修正 "
                                         "根据2020年8月6日公安部令第160号第三次修正)"), ("2020-08-06", None))
        self.assertEqual(dates_from_note("（2026年10月24日生态环境部令第40号公布，自公布之日起施行）"), ("2026-10-24", "2026-10-24"))
        self.assertEqual(dates_from_note(None), (None, None))

    def test_html_page(self):
        html = """<html><head><meta name="ArticleTitle" content="某办法"></head><body><div id="UCAP-CONTENT">
            <p style="text-align: center">某办法</p>
            <p style="text-align: center">（2023年8月23日教育部令第53号公布\u3000自2023年10月15日起施行）</p>
            <p> </p><p style="text-align: center">第一章\u3000总\u3000\u3000则</p>
            <p>第一条为了规范，制定本办法。</p><p>第二条\u3000本办法自2023年10月15日起施行。</p>
            </div><div class="footer"><p>版权所有</p></div></body></html>"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "content_1.htm"
            path.write_text(html, encoding="utf-8")
            title, desc, content = HtmlParser().parse_document(path)
        self.assertEqual(title, "某办法")
        self.assertEqual(parse(title, desc, content), [
            "# 某办法",
            "2023年8月23日 教育部令第53号公布",
            "2023年10月15日 施行",
            "<!-- INFO END -->",
            "## 第一章 总则",
            "第一条 为了规范，制定本办法。",
            "第二条 本办法自2023年10月15日起施行。",
        ])

    def test_dated_note(self):
        cases = [
            # 开头没有日期，补上发布日期
            ("（国家旅游局令第22号公布 自2005年7月3日起施行）", "2005-09-26",
             ["2005年9月26日 国家旅游局令第22号公布", "2005年7月3日 施行"]),
            # 还有修订日期时不补，发布日期多半是修订那次的
            ("(某委员会令2007年第3号公布，根据2008年12月17日某会议修订)", "2008-12-17", ["2008年12月17日 某会议修订"]),
            # 只有施行日期
            ("（自2025年7月1日起施行）", "2025-03-10", ["2025年7月1日 施行"]),
            ("(本规定自2008年2月14日起施行)", "2008-01-14", ["2008年2月14日 施行"]),
            # 日期在末尾
            ("（国家林业局令第2号 1999年4月22日）", "1999-04-22", ["1999年4月22日 国家林业局令第2号"]),
            # ISO 日期、「实施」
            ("（2016-02-16财政部令第80号公布 2016-05-01实施）", "2016-02-16", ["2016年2月16日 财政部令第80号公布", "2016年5月1日 施行"]),
            ("（1997年11月21日银发〔1997〕485号文印发 自1997年11月21日起实施）", None, ["1997年11月21日 银发〔1997〕485号文印发", "1997年11月21日 施行"]),
        ]
        for note, publish, want in cases:
            with self.subTest(note):
                self.assertEqual(parse_desc(dated_note(note, publish)), want)
        self.assertEqual(dated_note(None, "2020-01-01"), "")

    def html(self, body):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "content_1.htm"
            path.write_text(f'<html><body><div id="UCAP-CONTENT">{body}</div></body></html>', encoding="utf-8")
            return HtmlParser().parse_document(path, "某办法")

    def test_html_undated_note_and_title_in_one_paragraph(self):
        _, desc, content = self.html("<p>某办法</p><p>( 国家旅游局令第22号公布 自2005年7月3日起施行)</p><p>第一条 内容</p>")
        self.assertEqual((desc, content), ("( 国家旅游局令第22号公布 自2005年7月3日起施行)", ["第一条 内容"]))
        _, desc, content = self.html("<p>某办法 （1997年11月21日银发〔1997〕485号文印发 自1997年11月21日起实施）</p><p>第一条 内容</p>")
        self.assertEqual(desc, "（1997年11月21日银发〔1997〕485号文印发 自1997年11月21日起实施）")
        self.assertEqual(content, ["第一条 内容"])
        # 正文里的括号段落不算题注
        _, desc, content = self.html("<p>某办法</p><p>第一条 内容</p><p>（本条自公布之日起施行）</p>")
        self.assertEqual((desc, content), ("", ["第一条 内容", "（本条自公布之日起施行）"]))

    def test_html_nested_paragraphs(self):
        _, _, content = self.html("<p><p>第一条 甲</p><p>第二条 乙</p></p>".replace("<p><p>", "<p><span>x</span><p>"))
        self.assertEqual(content, ["第一条 甲", "第二条 乙"])


if __name__ == "__main__":
    unittest.main()
