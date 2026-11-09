import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from lawref.db import Category, Database, Law, update
from lawref.reports import duplicates


def rule(title, header, body):
    return f"# {title}\n\n{header}\n\n<!-- INFO END -->\n\n{body}\n"


X_BODY = "\n\n".join(f"第{n}条 甲规定的内容，部门联合发布。" for n in "一二三四五六")
Y_OLD = "\n\n".join(f"第{n}条 乙办法旧版本的内容。" for n in "一二三")
Y_NEW = "\n\n".join(f"第{n}条 乙办法重新制定以后完全不同的条文，第{n}项。" for n in "一二三四五六七八")


class MergeTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.rules = self.root / "部门规章"
        files = {
            # 两个部门各收了一份，同一版本
            "教育部/甲规定(2020-01-01).md": rule("甲规定", "2020年1月1日 教育部 财政部令第1号公布", X_BODY),
            "财政部/甲规定(2020-01-01).md": rule("甲规定", "2020年1月1日 教育部 财政部令第1号公布", X_BODY),
            # 两个版本分在两个目录，新版本由财政部发布
            "教育部/乙办法(2019-01-01).md": rule("乙办法", "2019年1月1日 教育部令第3号公布", Y_OLD),
            "财政部/乙办法(2021-01-01).md": rule("乙办法", "2021年1月1日 财政部令第4号公布", Y_NEW),
        }
        for rel, text in files.items():
            path = self.rules / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        for target, value in (("RULES", self.rules), ("ROOT", self.root)):
            patcher = mock.patch.object(duplicates, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.db_file = self.root / "db.sqlite3"
        self.update()

    def update(self):
        with redirect_stdout(io.StringIO()), Database(self.db_file) as db:
            count = update(db)
            ids = {(law.name, law.publish): law.id for law in Law.select()}
        return count, ids

    def test_find(self):
        groups = {g.name: g for g in duplicates.find_duplicates()}
        self.assertEqual(set(groups), {"甲规定", "乙办法"})
        self.assertEqual(len(groups["甲规定"].same), 1)
        self.assertEqual(groups["乙办法"].same, [])

    def test_plan(self):
        plans = {p.name: p for p in duplicates.merge_plans()}
        self.assertEqual(plans["甲规定"].target_dir, self.rules / "教育部")
        self.assertEqual([(s.dest.relative_to(self.rules), len(s.drop)) for s in plans["甲规定"].steps],
                         [(Path("教育部/甲规定(2020-01-01).md"), 1)])
        self.assertEqual(plans["乙办法"].target_dir, self.rules / "财政部")
        self.assertEqual([(s.keep.relative_to(self.rules), s.dest.relative_to(self.rules), s.changed)
                          for s in plans["乙办法"].steps],
                         [(Path("教育部/乙办法(2019-01-01).md"), Path("财政部/乙办法(2019-01-01).md"), True),
                          (Path("财政部/乙办法(2021-01-01).md"), Path("财政部/乙办法(2021-01-01).md"), False)])

    def test_apply_keeps_ids(self):
        _, before = self.update()
        # 同名同日期的两份甲规定只有一份入了库
        self.assertEqual(len(before), 3)
        removed = duplicates.apply_merge(duplicates.merge_plans(), self.db_file)
        self.assertEqual(removed, 0)
        self.assertEqual(sorted(str(p.relative_to(self.rules)) for p in self.rules.rglob("*.md")),
                         ["教育部/甲规定(2020-01-01).md", "财政部/乙办法(2019-01-01).md", "财政部/乙办法(2021-01-01).md"])
        count, after = self.update()
        # 乙办法 2019 年版只换了目录，update 认出移动；所有 ID 都不变
        self.assertEqual((count["created"], count["moved"], count["missing"]), (0, 1, 0))
        self.assertEqual(after, before)

    def test_apply_drops_record_of_removed_copy(self):
        # 两份都入了库（比如之前分别下载、分别入库）：删掉的那份的记录也删掉，否则会一直找不到文件
        with Database(self.db_file):
            category = Category.get_or_create_category(Path("部门规章/财政部"))
            Law.create(name="甲规定", publish="2020-01-01", level="部门规章", category_id=category.id)
        removed = duplicates.apply_merge(duplicates.merge_plans(), self.db_file)
        self.assertEqual(removed, 1)
        count, after = self.update()
        self.assertEqual((count["created"], count["missing"]), (0, 0))
        self.assertEqual(len(after), 3)
