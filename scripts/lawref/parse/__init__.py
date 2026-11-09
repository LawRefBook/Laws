"""把下载的原文（Word、网页、epub）解析成仓库的 markdown。

各格式的 parser 返回 ParsedDocument（标题、题注、正文各行），content.build 整理成仓库的格式，
content.render 拼成文件内容。
"""
import subprocess
import threading
from pathlib import Path

from docx import Document

from lawref.parse.base import ParsedDocument, ParseError
from lawref.parse.epub import parse_epub
from lawref.parse.html import parse_html
from lawref.parse.word import parse_word

__all__ = ["ParseError", "ParsedDocument", "parse_epub", "parse_file", "parse_html", "parse_word"]

HTML_SUFFIXES = (".htm", ".html", ".shtml")

# 下载时在多个线程里解析，LibreOffice 同一时间只能跑一个转换
_SOFFICE = threading.Lock()


def convert_to_docx(path: Path) -> Path:
    """用 LibreOffice 把 .doc 转成同目录下的 .docx，已经转过的直接用。"""
    docx = path.with_suffix(".docx")
    if docx.exists():
        return docx
    try:
        with _SOFFICE:
            subprocess.run(
                ["soffice", "--headless", "--convert-to", "docx", "--outdir", str(path.parent), str(path)],
                check=True, capture_output=True,
            )
    except (OSError, subprocess.CalledProcessError) as e:
        raise ParseError(f"无法把 .doc 转成 .docx：{e}") from e
    if not docx.exists():
        raise ParseError(f"无法把 .doc 转成 .docx：{path}")
    return docx


def parse_file(path: Path, title: str | None = None) -> ParsedDocument:
    """按扩展名选 parser。title 不传时 epub、网页取文件里的标题，Word 取文件名。"""
    if path.suffix == ".epub":
        return parse_epub(path, title)
    if path.suffix in HTML_SUFFIXES:
        return parse_html(path, title)
    if path.suffix == ".doc":
        path = convert_to_docx(path)
    try:
        document = Document(str(path))
    except Exception as e:
        raise ParseError(f"无法解析 Word 文件 {path.name}：{e}") from e
    return parse_word(document, title or path.stem)
