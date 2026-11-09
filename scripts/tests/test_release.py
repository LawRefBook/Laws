import io
import json
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from lawref import release


class ReleaseTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_meta_format(self):
        # 和原来 release.sh 用 printf 拼出来的一样
        meta = release.Meta(name="北京地方法规", hash="abc-dirty", update=1700000000, filesize=1520)
        self.assertEqual(meta.dumps(), '{"name":"北京地方法规","hash":"abc-dirty", "update":1700000000, "filesize":1520}\n')
        self.assertEqual(json.loads(meta.dumps())["name"], "北京地方法规")

    def test_pathspec(self):
        spec = release.pathspec()
        self.assertEqual(spec[:2], [".", ":!.*"])
        for name in ("scripts", "DLC", "Makefile", "README.md", "requirements.txt"):
            self.assertIn(f":!{name}", spec)

    def test_pack_entries(self):
        for rel in ("db.sqlite3", "宪法/宪法.md", "宪法/_index.md", ".lawignore", ".git/HEAD", "README.md",
                    "scripts/lawref/x.py", "DLC/北京地方法规/db.sqlite3", "Makefile", "法律/.DS_Store", "法律/README.md"):
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x", encoding="utf-8")
        entries = [p.as_posix() for p in release.pack_entries(self.root)]
        self.assertEqual(entries, ["db.sqlite3", "宪法", "宪法/_index.md", "宪法/宪法.md", "法律"])
        with tempfile.TemporaryDirectory() as out:
            dest = Path(out) / "out.zip"
            release.write_zip(self.root, dest)
            with zipfile.ZipFile(dest) as zf:
                names = zf.namelist()
        self.assertEqual(names, ["db.sqlite3", "宪法/", "宪法/_index.md", "宪法/宪法.md", "法律/"])

    def test_dlc_list(self):
        release_dir, dlc_dir = self.root / ".release", self.root / "DLC"
        for name in ("上海地方法规", "北京地方法规", "已删除地方法规"):
            (release_dir / "DLC").mkdir(parents=True, exist_ok=True)
            (release_dir / "DLC" / f"{name}.abc.zip").write_bytes(b"")
            (release_dir / "metadata").mkdir(exist_ok=True)
            (release_dir / "metadata" / f"{name}.meta").write_text(
                release.Meta(name=name, hash="abc", update=1, filesize=2).dumps(), encoding="utf-8")
        for name in ("上海地方法规", "北京地方法规"):
            (dlc_dir / name).mkdir(parents=True)
        with mock.patch.object(release, "RELEASE_DIR", release_dir), mock.patch.object(release, "DLC_DIR", dlc_dir), \
                redirect_stderr(io.StringIO()) as err:
            release.write_dlc_list()
        listed = json.loads((release_dir / "dlc.json").read_text(encoding="utf-8"))
        # 按地区编号排序：北京在上海前面；仓库里已经删掉的不列出
        self.assertEqual([m["name"] for m in listed], ["北京地方法规", "上海地方法规"])
        self.assertIn("Delisting 已删除地方法规", err.getvalue())
        self.assertTrue((release_dir / "dlc.json").read_text(encoding="utf-8").startswith('[\n  {\n    "name": "北京地方法规",'))
