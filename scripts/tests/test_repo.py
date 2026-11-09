import tempfile
import unittest
from pathlib import Path

from lawref.repo import is_manual_law, law_files, pack_files


class RepoTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for rel in ("宪法/宪法.md", "行政法规/某条例(2020-01-01).md", "行政法规/_index.md", "README.md",
                    "法律法规模版.md", "scripts/tests/fixtures/x.md", ".venv/lib/a.md", "旧/.hidden/b.md",
                    "DLC/北京地方法规/地方性法规/北京/某条例(2021-01-01).md", "DLC/北京地方法规/地方性法规/北京/_index.md",
                    "草稿/c.md", "正文/草稿/d.md"):
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# x\n", encoding="utf-8")
        (self.root / ".lawignore").write_text("^\\..*\nscripts\nDLC\n草稿\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def rel(self, files):
        return [str(f.relative_to(self.root)) for f in files]

    def test_main_pack(self):
        # .lawignore 里的目录名只排除顶层的「草稿」，正则排除任意一段以 . 开头的
        self.assertEqual(self.rel(pack_files(self.root)),
                         ["宪法/宪法.md", "正文/草稿/d.md", "行政法规/某条例(2020-01-01).md"])

    def test_with_dlc(self):
        self.assertEqual(self.rel(law_files(self.root, include_dlc=True)),
                         ["DLC/北京地方法规/地方性法规/北京/某条例(2021-01-01).md",
                          "宪法/宪法.md", "正文/草稿/d.md", "行政法规/某条例(2020-01-01).md"])

    def test_dlc_pack(self):
        pack = self.root / "DLC/北京地方法规"
        self.assertEqual([str(f.relative_to(pack)) for f in pack_files(pack)], ["地方性法规/北京/某条例(2021-01-01).md"])

    def test_manual_law(self):
        self.assertTrue(is_manual_law("中华人民共和国刑法修正案（十二）"))
        self.assertTrue(is_manual_law("民法典 总则编"))
        self.assertFalse(is_manual_law("监狱法"))
