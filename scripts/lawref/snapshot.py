"""把各工具的输出存成一个目录，改代码前后各存一份，`diff -r` 就能看出行为有没有变。

只读：数据库更新在临时目录里的副本上做，不改动仓库。比较的是当前工作区里的数据，
所以前后两次之间不要改法规文件，只改 scripts/。
"""
import contextlib
import io
import shutil
import sqlite3
import tempfile
from pathlib import Path

from click.testing import CliRunner

from lawref import db, lint
from lawref.parse import parse_file
from lawref.parse.content import build, render
from lawref.paths import CACHE_DIR, ROOT


def _not_data(folder: str, names: list[str]) -> set[str]:
    """复制数据时不要的：工具和以 . 开头的目录（.git、.venv …）。.lawignore 这样的文件要留着。"""
    return {n for n in names if n in ("scripts", "__pycache__") or (n.startswith(".") and (Path(folder) / n).is_dir())}


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _captured(fn, *args, **kwargs) -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        result = fn(*args, **kwargs)
    return f"{out.getvalue()}--- result: {result!r}\n"


def snapshot_lint(out: Path) -> None:
    _write(out / "lint.txt", _captured(lint.run, [ROOT], dlc=True, show_warnings=True))


def snapshot_reports(out: Path) -> None:
    from lawref.cli import cli

    runner = CliRunner()
    for name, args in {"missing": ["report", "missing"], "expired": ["report", "expired"],
                       "duplicates": ["report", "duplicates", "--all"], "merge-plan": ["merge-duplicates"]}.items():
        result = runner.invoke(cli, args)
        _write(out / "reports" / f"{name}.txt", f"{result.output}--- exit {result.exit_code}\n")


def _word_title(path: Path) -> str:
    """缓存的 Word 文件名是哈希，取第一段当标题，和下载时数据源给的标题一致。"""
    from docx import Document

    return next((p.text.strip() for p in Document(str(path)).paragraphs if p.text.strip()), path.stem)[:60]


def snapshot_parse(out: Path) -> None:
    """重新解析缓存里的原文。"""
    for path in sorted(CACHE_DIR.glob("*/*")):
        if path.parent.name == "out" or path.suffix not in (".docx", ".htm", ".html", ".shtml", ".epub"):
            continue
        dest = out / "parse" / path.parent.name / f"{path.name}.md"
        try:
            doc = parse_file(path, _word_title(path) if path.suffix == ".docx" else None)
            lines = build(doc.title, doc.note, doc.lines)
            _write(dest, render(lines) if lines else "（没有正文）\n")
        except Exception as e:
            _write(dest, f"{type(e).__name__}: {e}\n")


def _dump(db_file: Path) -> str:
    rows = []
    with contextlib.closing(sqlite3.connect(db_file)) as conn:
        for table in ("category", "law", "relationship"):
            rows.append(f"== {table}")
            rows += sorted(map(repr, conn.execute(f"SELECT * FROM {table}")))
    return "\n".join(rows) + "\n"


def snapshot_db(out: Path) -> None:
    """在数据的副本上运行 `laws db update`（先本体，再全部 DLC），存下输出和三张表。"""
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp) / "data"
        shutil.copytree(ROOT, data, ignore=_not_data)
        targets = [data / "db.sqlite3", *sorted((data / "DLC").glob("*/db.sqlite3"))]
        for db_file in targets:
            name = str(db_file.relative_to(data)).replace("/", "__")

            def run(db_file=db_file):
                with db.Database(db_file) as database:
                    return db.update(database)

            _write(out / "db" / f"{name}.log", _captured(run))
            _write(out / "db" / f"{name}.txt", _dump(db_file))


STEPS = {"lint": snapshot_lint, "reports": snapshot_reports, "parse": snapshot_parse, "db": snapshot_db}


def snapshot(out: Path, steps=tuple(STEPS)) -> None:
    for step in steps:
        print(f"== {step}")
        STEPS[step](out)
