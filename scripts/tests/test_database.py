"""在仓库根目录运行：.venv/bin/python -m unittest discover scripts/tests"""
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import (Category, Database, Law, LawFlag, Relationship, content_flags, effective_date,  # noqa: E402
                      decision_listed_date, extract_abolished_law_names, extract_decision_abolished_names, extract_decision_amended_names,
                      extract_valid_from)  # noqa: E402


def law_text(title, body, header=("2020年1月1日 通过",)):
    return "\n\n".join([f"# {title}", *header, "<!-- INFO END -->", *body]) + "\n"


class EffectiveDateTest(unittest.TestCase):

    def test_header_line_wins(self):
        text = law_text("某规定", ["第一条 内容", "第二条 本规定自2019年1月1日起施行。"], ("2022年1月1日 施行",))
        self.assertEqual(extract_valid_from(text, "2021-12-20"), "2022-01-01")

    def test_subject_clause_not_narration(self):
        # 条文里叙述别的法规「自公布之日起施行」不算
        text = law_text("某条例", [
            "第三十四条 行政法规应当自公布之日起30日后施行；特殊情况可以自公布之日起施行。",
            "第三十五条 本条例自2026年7月1日起施行。",
        ])
        self.assertEqual(extract_valid_from(text, "2026-05-15"), "2026-07-01")

    def test_promulgation_note_after_clause(self):
        text = law_text("某解释", ["第十九条 本解释自2019年5月1日起施行。", "本解释公布施行后，以前发布的司法解释与本解释不一致的，不再适用。"])
        self.assertEqual(extract_valid_from(text, "2019-04-24"), "2019-05-01")

    def test_transitional_dates_ignored(self):
        text = law_text("某规定", ["第九条 本规定自1995年5月1日起施行。", "有困难的单位，最迟应当自1997年5月1日起施行。"])
        self.assertEqual(extract_valid_from(text, "1995-03-25"), "1995-05-01")

    def test_revision_keeps_original_date(self):
        text = law_text("某法", ["第六十三条 本法自1994年1月1日起施行。"])
        self.assertEqual(effective_date(text, "2013-10-25"), "2013-10-25")


class DecisionAbolishTest(unittest.TestCase):

    def names(self, *body):
        return extract_decision_abolished_names(law_text("国务院关于修改和废止部分行政法规的决定", body))

    def test_attachment_list_skips_amendments(self):
        self.assertEqual(self.names(
            "一、对36部行政法规的部分条款予以修改。（附件1）", "二、对2部行政法规予以废止。（附件2）",
            "附件1：国务院决定修改的行政法规", "一、删去《城市绿化条例》第十一条第三款。",
            "附件2：国务院决定废止的行政法规",
            "一、城乡集市贸易管理办法（1983年2月5日国务院发布）",
            "二、国家体育锻炼标准施行办法（试行）（1989年12月9日国务院批准）",
        ), ["城乡集市贸易管理办法", "国家体育锻炼标准施行办法（试行）"])

    def test_untitled_attachment_from_summary(self):
        # 「附件1」下面直接是名单，靠总述「予以废止。（附件1）」判断
        self.assertEqual(self.names(
            "一、对2部行政法规予以废止。（附件1）", "二、对8部行政法规的部分条款予以修改。（附件2）",
            "附件1", "一、《中华人民共和国甲规定》（1987年12月30日国务院批准）",
            "二、《〈甲规定〉的补充规定》（1997年9月29日国务院批准）",
            "附件2", "一、将《乙条例》第五条修改为：“内容”",
        ), ["甲规定", "《甲规定》的补充规定"])

    def test_intro_heading_and_inline(self):
        self.assertEqual(self.names("根据关于修改人口与计划生育法的决定，国务院决定废止以下行政法规：",
                                    "一、甲条例（2001年6月13日国务院令第309号公布）"), ["甲条例"])
        self.assertEqual(self.names("## 二、废止5件行政法规", "（一）《乙条例》（1951年4月24日发布）。"), ["乙条例"])
        self.assertEqual(self.names("一、修改《丙条例》。", "二、废止《丁办法》（1994年12月20日国务院公布）。"), ["丁办法"])

    def test_amended_names(self):
        body = ("一、对3部行政法规的部分条款予以修改。（附件1）", "二、对1部行政法规予以废止。（附件2）",
                "附件1：国务院决定修改的行政法规", "一、删去《中华人民共和国甲条例》第十一条第三款。",
                "第二十二条改为第二十一条，修改为：“内容”", "二、将《乙条例》第五条修改为：“依照《丙法》处理。”",
                "3. 删去《丁办法》第三条。",
                "附件2：国务院决定废止的行政法规", "一、《戊条例》（1983年2月5日国务院发布）")
        text = law_text("国务院关于修改和废止部分行政法规的决定", body)
        self.assertEqual(extract_decision_amended_names(text), ["甲条例", "乙条例", "丁办法"])
        self.assertEqual(extract_decision_abolished_names(text), ["戊条例"])

    def test_table(self):
        self.assertEqual(self.names(
            "附件1 国务院决定废止的行政法规目录（49件）", "<!-- TABLE -->",
            "| 序号  |法规名称  |公布机关及日期  |", "|-----|-----|-----|", "| 1  |铁路留用土地办法  |1950年6月24日政务院公布  |",
            "<!-- TABLE END -->"), ["铁路留用土地办法"])


class DecisionListedDateTest(unittest.TestCase):

    def test_list_item_takes_latest_revision(self):
        text = law_text("国务院关于修改和废止部分行政法规的决定", [
            "## 附件2 国务院决定废止的行政法规",
            "三、危险化学品安全管理条例（2002年1月26日中华人民共和国国务院令第344号公布 根据2011年3月2日"
            "中华人民共和国国务院令第591号第一次修订 根据2013年12月7日《国务院关于修改部分行政法规的决定》第二次修订）"])
        self.assertEqual(decision_listed_date(text, "危险化学品安全管理条例"), "2013-12-07")

    def test_table_ignores_reason_column(self):
        text = law_text("国务院关于废止2000年底以前发布的部分行政法规的决定", [
            "| 序号 | 行政法规名称 | 发布日期 | 失效年份 | 废止理由 |", "|-----|-----|-----|-----|-----|",
            "| 59 | 广播电视设施保护条例 | 1987年4月24日国务院发布 | 2000年（7件） |"
            " 被2000年11月5日中华人民共和国国务院令第295号公布的《广播电视设施保护条例》明令废止。 |"])
        self.assertEqual(decision_listed_date(text, "广播电视设施保护条例"), "1987-04-24")

    def test_each_version_on_its_own_row(self):
        text = law_text("国务院关于废止2000年底以前发布的部分行政法规的决定", [
            "| 序号 | 行政法规名称 | 发布日期 | 失效年份 | 废止理由 |", "|-----|-----|-----|-----|-----|",
            "| 45 | 中华人民共和国发明奖励条例 | 1978年12月28日国务院发布 | 1999年（11件） | 被…明令废止。 |",
            "| 53 | 中华人民共和国发明奖励条例 | 1993年6月28日国务院第二次修订发布 | 1999年（11件） | 被…明令废止。 |"])
        self.assertEqual(decision_listed_date(text, "发明奖励条例"), "1993-06-28")

    def test_not_listed(self):
        self.assertIsNone(decision_listed_date(law_text("某决定", ["一、某条例"]), "其他条例"))


class AbolishClauseTest(unittest.TestCase):

    def names(self, *body, header=("2020年1月1日 通过",)):
        return extract_abolished_law_names(law_text("某法", body, header))

    def test_names_separated_by_dates(self):
        self.assertEqual(self.names(
            "第六十条 本法自2008年1月1日起施行。1991年4月9日第七届全国人民代表大会第四次会议通过的"
            "《中华人民共和国外商投资企业和外国企业所得税法》和1993年12月13日国务院发布的"
            "《中华人民共和国企业所得税暂行条例》同时废止。"),
            ["企业所得税暂行条例", "外商投资企业和外国企业所得税法"])

    def test_listed_without_title_marks(self):
        self.assertEqual(self.names(
            "附件一", "全国人民代表大会常务委员会制定的下列条例、补充规定和决定，已纳入本法或者已不适用，自本法施行之日起，予以废止：",
            "1. 中华人民共和国惩治军人违反职责罪暂行条例", "2. 关于惩治走私罪的补充规定", "附件二",
            "3. 不在名单里"), ["惩治军人违反职责罪暂行条例", "关于惩治走私罪的补充规定"])

    def test_repeal_of_provisions_within_a_law_ignored(self):
        self.assertEqual(self.names(
            "第十九条 本规定自1988年9月1日起施行。1953年1月2日政务院修正发布的《中华人民共和国劳动保险条例》"
            "中有关女工人、女职员生育待遇的规定和1955年4月26日《国务院关于女工作人员生产假期的通知》同时废止。"),
            ["国务院关于女工作人员生产假期的通知"])

    def test_partial_repeal_and_header_ignored(self):
        self.assertEqual(self.names(
            "第五条 《最高人民法院关于审理劳动争议案件适用法律问题的解释（一）》（法释〔2020〕26号）第三十二条第一款同时废止。",
            header=("2008年1月1日 《中华人民共和国外商投资企业和外国企业所得税法》废止",)), [])

class ContentFlagsTest(unittest.TestCase):

    def test_toc_and_info(self):
        text = law_text("某法", ["## 第一章 总则", "第一条 内容", "### 第一节 一般规定", "第二条 内容"])
        self.assertEqual(content_flags(text), (True, True))

    def test_without_toc(self):
        self.assertEqual(content_flags(law_text("某规定", ["第一条 内容"])), (False, True))

    def test_without_info(self):
        # 信息部分只有标题，或者只有标记
        self.assertEqual(content_flags(law_text("某规定", ["## 第一章", "第一条 内容"], header=())), (True, False))
        self.assertEqual(content_flags(law_text("某规定", ["第一条 内容"], header=("<!-- FORCE BREAK -->",))), (False, False))

    def test_without_info_end_everything_is_info(self):
        self.assertEqual(content_flags("# 某规定\n\n## 第一章\n\n第一条 内容\n"), (False, True))

    def test_heading_in_info_is_info(self):
        self.assertEqual(content_flags(law_text("某规定", ["第一条 内容"], header=("## 说明",))), (False, True))


class UpdateTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def update(self):
        with redirect_stdout(io.StringIO()) as out:
            count = Database(self.root / "db.sqlite3").update_database()
        return count, out.getvalue()

    def law(self, name, publish=None):
        q = Law.select().where(Law.name == name)
        if publish:
            q = q.where(Law.publish == publish)
        return q.get()

    def test_single_version_gets_valid_from(self):
        self.write("行政法规/某条例(2026-10-17).md", law_text("某条例", ["第三十四条 本条例自2026年12月1日起施行。"]))
        count, _ = self.update()
        self.assertEqual(count["created"], 1)
        self.assertEqual(self.law("某条例").valid_from, "2026-12-01")

    def test_versions_chain_including_judicial_interpretations(self):
        for folder, name in (("行政法规", "甲条例"), ("司法解释", "某规定（三）")):
            self.write(f"{folder}/{name}(2011-01-27).md", law_text(name, ["第一条 本规定自2011年2月16日起施行。"]))
            self.write(f"{folder}/{name}(2014-02-20).md", law_text(name, ["第一条 内容"]))
        self.update()
        for name in ("甲条例", "某规定（三）"):
            old, new = self.law(name, "2011-01-27"), self.law(name, "2014-02-20")
            self.assertEqual((old.valid_from, old.valid_to), ("2011-02-16", "2014-02-20"))
            self.assertEqual((new.valid_from, new.valid_to), ("2014-02-20", "2099-12-31"))
            self.assertEqual(new.ver, 2)

    def test_abolish_from_undated_file_but_not_from_case(self):
        self.write("法律/婚姻法(2001-04-28).md", law_text("婚姻法", ["第一条 内容"]))
        self.write("法律/合同法(1999-03-15).md", law_text("合同法", ["第一条 内容"]))
        self.write("案例/某案.md", law_text("某案", ["《合同法》废止后，法院适用民法典。"]))
        self.update()
        # 民法典按编拆分、文件名没有日期，靠 filename 入库
        civil = Category.get_or_create_category(Path("民法典"))
        Law.create(name="民法典 附则", filename="附则", publish="2020-05-28", level="法律", category_id=civil.id)
        self.write("民法典/附则.md", law_text("民法典 附则", ["第一千二百六十条 本法自2021年1月1日起施行。《中华人民共和国婚姻法》同时废止。"]))
        case = Category.get_or_create_category(Path("案例"))
        Law.create(name="某案", level="案例", category_id=case.id)
        count, _ = self.update()
        self.assertEqual(count["invalidated"], 1)
        self.assertEqual(self.law("婚姻法").valid_to, "2021-01-01")
        self.assertEqual(self.law("合同法").valid_to, "2099-12-31")

    def relations(self, type):
        names = {law.id: (law.name, law.publish) for law in Law.select()}
        return {(names[r.source_id], names[r.target_id], r.date)
                for r in Relationship.select().where(Relationship.type == type)}

    def test_relationships(self):
        self.write("法律/甲法(2001-01-01).md", law_text("甲法", ["第一条 本法自2001年1月1日起施行。"]))
        self.write("法律/甲法(2010-01-01).md", law_text("甲法", ["第一条 本法自2010年3月1日起施行。"]))
        self.write("法律/乙法(2005-01-01).md", law_text("乙法", ["第一条 本法自2005年1月1日起施行。"]))
        self.write("法律/乙法(2020-01-01).md", law_text("乙法", ["第一条 本法自2020年1月1日起施行。"]))
        self.write("法律/丁法(2025-01-01).md", law_text("丁法", ["第九条 本法自2025年1月1日起施行。《乙法》同时废止。"]))
        self.update()
        self.assertEqual(self.relations(Relationship.SUPERSEDES), {
            (("甲法", "2010-01-01"), ("甲法", "2001-01-01"), "2010-03-01"),
            (("乙法", "2020-01-01"), ("乙法", "2005-01-01"), "2020-01-01"),
        })
        self.assertEqual(self.relations(Relationship.ABOLISHES), {
            (("丁法", "2025-01-01"), ("乙法", "2020-01-01"), "2025-01-01"),
        })
        count, _ = self.update()  # 重新生成，不重复
        self.assertEqual((count["supersedes"], count["abolishes"]), (2, 1))

    def test_implements(self):
        self.write("法律/甲法(2001-01-01).md", law_text("甲法", ["第一条 本法自2001年1月1日起施行。"]))
        self.write("法律/甲法(2020-01-01).md", law_text("甲法", ["第一条 本法自2020年1月1日起施行。"]))
        self.write("行政法规/甲法实施条例(2005-01-01).md", law_text("甲法实施条例", ["第一条 内容"]))
        self.write("司法解释/最高人民法院关于适用《中华人民共和国甲法》若干问题的解释(2021-01-01).md",
                   law_text("最高人民法院关于适用《中华人民共和国甲法》若干问题的解释", ["第一条 内容"]))
        self.write("司法解释/最高人民法院关于修改《甲法实施条例》的决定(2021-01-01).md",
                   law_text("最高人民法院关于修改《甲法实施条例》的决定", ["第一条 内容"]))
        self.write("司法解释/最高人民法院关于适用《民法典》物权编的解释（一）(2021-01-01).md",
                   law_text("最高人民法院关于适用《民法典》物权编的解释（一）", ["第一条 内容"]))
        self.write("司法解释/最高人民法院关于适用《民法典》时间效力的若干规定(2020-12-29).md",
                   law_text("最高人民法院关于适用《民法典》时间效力的若干规定", ["第一条 内容"]))
        self.update()
        civil = Category.create(name="民法典", folder="民法典")
        for order, part in enumerate(("总则", "物权编")):
            Law.create(name=f"民法典 {part}", filename=part, level="法律", category_id=civil.id, order=order)
            self.write(f"民法典/{part}.md", law_text(f"民法典 {part}", ["第一条 内容"]))
        self.update()
        self.assertEqual(self.relations(Relationship.IMPLEMENTS), {
            (("甲法实施条例", "2005-01-01"), ("甲法", "2001-01-01"), None),
            (("最高人民法院关于适用《中华人民共和国甲法》若干问题的解释", "2021-01-01"), ("甲法", "2020-01-01"), None),
            (("最高人民法院关于适用《民法典》物权编的解释（一）", "2021-01-01"), ("民法典 物权编", None), None),
            (("最高人民法院关于适用《民法典》时间效力的若干规定", "2020-12-29"), ("民法典 总则", None), None),
        })

    def test_implements_from_basis(self):
        self.write("法律/统计法(2009-06-27).md", law_text("统计法", ["第一条 内容"]))
        self.write("行政法规/统计法实施条例(2017-05-28).md",
                   law_text("统计法实施条例", ["第一条 根据《中华人民共和国统计法》，制定本条例。"]))
        self.write("部门规章/国家民族事务委员会/民族统计工作管理办法(2017-12-20).md", law_text("民族统计工作管理办法", [
            "第一条 为规范民族统计工作，根据《中华人民共和国统计法》及其实施细则和《部门统计调查项目管理暂行办法》，制定本办法。"]))
        self.write("部门规章/国家统计局/部门统计调查项目管理暂行办法(1999-01-01).md",
                   law_text("部门统计调查项目管理暂行办法", ["第一条 内容"]))
        self.write("部门规章/某部/某办法(2020-01-01).md", law_text("某办法", ["第一条 为了规范管理，制定本办法。", "第二条 依照《统计法》处罚。"]))
        self.update()
        self.assertEqual({(s[0], t[0]) for s, t, _ in self.relations(Relationship.IMPLEMENTS)}, {
            ("统计法实施条例", "统计法"),
            ("民族统计工作管理办法", "统计法"),
        })

    def test_dlc_implements_points_to_main_database(self):
        self.write("法律/义务教育法(1986-04-12).md", law_text("义务教育法", ["第一条 内容"]))
        self.write("法律/义务教育法(2018-12-29).md", law_text("义务教育法", ["第一条 内容"]))
        self.write("法律/统计法(2009-06-27).md", law_text("统计法", ["第一条 内容"]))
        self.update()
        main = {(law.name, law.publish): law.id for law in Law.select()}

        dlc = self.root / "DLC" / "北京地方法规"
        self.write(dlc / "地方性法规/北京/北京市实施《中华人民共和国义务教育法》办法(2019-05-01).md",
                   law_text("北京市实施《中华人民共和国义务教育法》办法", ["第一条 内容"]))
        self.write(dlc / "地方性法规/北京/北京市统计条例(2020-01-01).md",
                   law_text("北京市统计条例", ["第一条 根据《中华人民共和国统计法》，结合本市实际，制定本条例。"]))
        with redirect_stdout(io.StringIO()):
            count = Database(dlc / "db.sqlite3").update_database()
        self.assertEqual(count["created"], 2)
        local = {law.id: law.name for law in Law.select()}
        self.assertEqual(
            {(local[r.source_id], r.target_id) for r in Relationship.select().where(Relationship.type == Relationship.IMPLEMENTS)},
            {("北京市实施《中华人民共和国义务教育法》办法", main[("义务教育法", "2018-12-29")]),
             ("北京市统计条例", main[("统计法", "2009-06-27")])})
        # 本体的法规不会写进 DLC 数据库
        self.assertEqual(set(local.values()), {"北京市实施《中华人民共和国义务教育法》办法", "北京市统计条例"})

        # implements 指向本体没问题；abolishes、amends 指向本库以外的法规要报出来
        db = Database(dlc / "db.sqlite3")
        self.assertEqual(db.check(), [])
        source = self.law("北京市统计条例")
        for type in (Relationship.ABOLISHES, Relationship.AMENDS):
            Relationship.create(source_id=source.id, target_id=main[("统计法", "2009-06-27")], type=type)
        problems = db.check()
        self.assertEqual(len(problems), 2)
        self.assertTrue(all("北京市统计条例" in p for p in problems))

    def test_expiry_restored_after_rename(self):
        self.write("行政法规/甲规定(2007-09-19).md", law_text("甲规定", ["第一条 内容"]))
        self.write("行政法规/甲规定(2008-02-14).md", law_text("甲规定", ["第一条 内容"]))
        self.write("行政法规/乙条例(2003-04-07).md", law_text("乙条例", ["第一条 内容"]))
        self.update()
        self.assertEqual(self.law("甲规定", "2007-09-19").valid_to, "2008-02-14")
        Law.update(valid_to="1970-01-01").where(Law.name == "乙条例").execute()  # 手工标记的已失效
        # 2008 年那份其实是另一部规定，改名后两部不再是同名版本
        (self.root / "行政法规/甲规定(2008-02-14).md").rename(self.root / "行政法规/甲规定二(2008-02-14).md")
        Law.delete().where(Law.name == "甲规定", Law.publish == "2008-02-14").execute()
        count, out = self.update()
        self.assertEqual(count["restored"], 1)
        self.assertEqual(self.law("甲规定").valid_to, "2099-12-31")
        self.assertEqual(self.law("乙条例").valid_to, "1970-01-01")

    def test_amends_points_to_version_before(self):
        self.write("行政法规/甲条例(2011-01-08).md", law_text("甲条例", ["第一条 内容"]))
        self.write("行政法规/甲条例(2017-03-01).md", law_text("甲条例", ["第一条 内容"]))
        self.write("行政法规/乙条例(2017-03-01).md", law_text("乙条例", ["第一条 内容"]))
        self.write("行政法规/国务院关于修改部分行政法规的决定（2017年）(2017-03-01).md", law_text(
            "国务院关于修改部分行政法规的决定", ["一、将《甲条例》第五条修改为：“内容”", "二、删去《乙条例》第三条。",
                                    "本决定自2017年3月21日起施行。"]))
        self.update()
        # 甲条例指向修改前的 2011 版；乙条例库里只有修改后的版本，指向它
        self.assertEqual(self.relations(Relationship.AMENDS), {
            (("国务院关于修改部分行政法规的决定（2017年）", "2017-03-01"), ("甲条例", "2011-01-08"), "2017-03-21"),
            (("国务院关于修改部分行政法规的决定（2017年）", "2017-03-01"), ("乙条例", "2017-03-01"), "2017-03-21"),
        })

    def test_existing_valid_from_kept_unless_stale(self):
        self.write("法律/消费者权益保护法(2013-10-25).md", law_text("消费者权益保护法", ["第六十三条 本法自1994年1月1日起施行。"]))
        self.write("行政法规/乙条例(2026-05-15).md", law_text("乙条例", ["第三十五条 本条例自2026年7月1日起施行。"]))
        self.update()
        Law.update(valid_from="2014-03-15").where(Law.name == "消费者权益保护法").execute()  # 来自法规库
        Law.update(valid_from="2026-05-15").where(Law.name == "乙条例").execute()  # 旧逻辑误取发布日期
        self.update()
        self.assertEqual(self.law("消费者权益保护法").valid_from, "2014-03-15")
        self.assertEqual(self.law("乙条例").valid_from, "2026-07-01")

    def test_moved_and_missing_files(self):
        self.write("行政法规/丙条例(2020-01-01).md", law_text("丙条例", ["第一条 内容"]))
        self.write("行政法规/丁条例(2020-01-01).md", law_text("丁条例", ["第一条 内容"]))
        self.update()
        law_id = self.law("丙条例").id
        (self.root / "法律").mkdir()
        (self.root / "行政法规/丙条例(2020-01-01).md").rename(self.root / "法律/丙条例(2020-01-01).md")
        (self.root / "行政法规/丁条例(2020-01-01).md").unlink()
        count, out = self.update()
        moved = self.law("丙条例")
        self.assertEqual((count["moved"], count["created"], count["missing"]), (1, 0, 1))
        self.assertEqual(moved.id, law_id)
        self.assertEqual(Category.get_by_id(moved.category_id).folder, "法律")
        self.assertEqual(moved.level, "法律")
        self.assertIn("找不到文件", out)

    def flags(self, name, publish=None):
        return LawFlag(self.law(name, publish).flags)

    def test_content_flags_written(self):
        self.write("行政法规/甲条例(2020-01-01).md", law_text("甲条例", ["## 第一章 总则", "第一条 内容"]))
        self.write("行政法规/乙条例(2020-01-01).md", law_text("乙条例", ["第一条 内容"], header=()))
        count, _ = self.update()
        self.assertEqual(count["flags"], 1)
        self.assertEqual(self.flags("甲条例"), LawFlag.TOC | LawFlag.INFO)
        self.assertEqual(self.flags("乙条例"), LawFlag(0))
        # 文件改了再更新，跟着变
        self.write("行政法规/乙条例(2020-01-01).md", law_text("乙条例", ["## 第一章", "第一条 内容"]))
        count, _ = self.update()
        self.assertEqual(count["flags"], 1)
        self.assertEqual(self.flags("乙条例"), LawFlag.TOC | LawFlag.INFO)

    def test_history_flag_on_every_version(self):
        self.write("行政法规/甲条例(2011-01-27).md", law_text("甲条例", ["第一条 内容"]))
        self.write("行政法规/甲条例(2014-02-20).md", law_text("甲条例", ["第一条 内容"]))
        self.write("行政法规/乙条例(2011-01-27).md", law_text("乙条例", ["第一条 内容"]))
        self.update()
        self.assertIn(LawFlag.HISTORY, self.flags("甲条例", "2011-01-27"))
        self.assertIn(LawFlag.HISTORY, self.flags("甲条例", "2014-02-20"))
        self.assertNotIn(LawFlag.HISTORY, self.flags("乙条例"))

    def test_old_database_gets_new_columns(self):
        import sqlite3
        db_file = self.root / "db.sqlite3"
        conn = sqlite3.connect(db_file)
        conn.execute("CREATE TABLE law (id TEXT PRIMARY KEY, level TEXT, name TEXT, subtitle TEXT, filename TEXT, "
                     "publish DATE, valid_from DATE, valid_to DATE, \"order\" INTEGER, ver INTEGER, tags TEXT, category_id TEXT)")
        conn.commit()
        conn.close()
        self.write("行政法规/甲条例(2020-01-01).md", law_text("甲条例", ["## 第一章 总则", "第一条 内容"]))
        self.update()
        self.assertIn(LawFlag.TOC, self.flags("甲条例"))

    def test_rollback_on_error(self):
        self.write("行政法规/戊条例(2020-01-01).md", law_text("戊条例", ["第一条 内容"]))
        db = Database(self.root / "db.sqlite3")
        db.update_versions = lambda: 1 / 0
        with redirect_stdout(io.StringIO()), self.assertRaises(ZeroDivisionError):
            db.update_database()
        self.assertEqual(Law.select().count(), 0)


if __name__ == "__main__":
    unittest.main()
