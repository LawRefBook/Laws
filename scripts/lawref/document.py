"""仓库里一份法规文件的约定：文件名和 markdown 的结构。

文件名是「名称(YYYY-MM-DD).md」，日期是发布日期；手工维护的（刑法、民法典、案例等）没有日期。
markdown 依次是「# 标题」、头部信息（每行「X年X月X日 事件」）、`<!-- INFO END -->`、正文。
"""
import re

from lawref.text import short_title

INFO_END = "<!-- INFO END -->"

LAW_FILE = re.compile(r"^(.+?)(?:\((\d{4}-\d{2}-\d{2})\))?\.md$")
_DATED_STEM = re.compile(r"^(.+?)\((\d{4}-\d{2}-\d{2})\)$")


def split_stem(stem: str) -> tuple[str, str | None]:
    """「名称(2020-01-01)」→ ("名称", "2020-01-01")；没有日期时为 (stem, None)。"""
    m = _DATED_STEM.match(stem)
    return (m.group(1), m.group(2)) if m else (stem, None)


def split_filename(filename: str) -> tuple[str, str | None]:
    """「名称(2020-01-01).md」→ ("名称", "2020-01-01")。"""
    return split_stem(filename.removesuffix(".md"))


def law_filename(title: str, date: str | None = None) -> str:
    """按仓库的命名规则拼文件名：名称按 short_title 去掉「中华人民共和国」。"""
    # 「核苷酸和/或氨基酸…」里的斜杠会被当成目录
    name = short_title(title).replace("/", "／")
    return f"{name}({date}).md" if date else f"{name}.md"


def canonical_filename(filename: str) -> str:
    """按仓库的命名规则规范已有的文件名，日期保持不变。不是 .md 的原样返回。"""
    if not LAW_FILE.match(filename):
        return filename
    return law_filename(*split_filename(filename))


def head_of(text: str) -> str:
    """标题和头部信息；没有 INFO END 时是全文。"""
    return text.partition(INFO_END)[0]


def body_of(text: str) -> str:
    """INFO END 之后的正文；没有 INFO END、或者其后为空时是全文。"""
    return text.partition(INFO_END)[2] or text


def header_lines(text: str) -> list[str]:
    """头部信息的各行，不含标题和空行。"""
    return [line for line in head_of(text).splitlines()[1:] if line.strip()]
