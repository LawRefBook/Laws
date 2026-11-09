"""检查法规 markdown 的格式，见 `laws lint --help`。

error 是会在 App 里直接显示出来的格式问题；warning 可能是原文本身如此，只报告。
"""
import difflib
import itertools
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from lawref.dates import to_cn
from lawref.document import INFO_END, split_stem
from lawref.numerals import cn_to_int
from lawref.paths import ROOT
from lawref.repo import law_files, pack_files
from lawref.text import fix_private_use, norm

CN = "零〇一二三四五六七八九十百千"
ARTICLE = re.compile(rf"^第([{CN}]+)条(?:之[{CN}]+)?(?:\s|$)")
STRUCTURE = re.compile(rf"^第[{CN}0-9]+(?:编|分编|章|节)")
DATE = re.compile(r"^\d{4}年\d{1,2}月\d{1,2}日 \S")
BAD_CHAR = re.compile("[\ufffd\ufeff\u200b\u200c\u200d\u2060\xad\x00-\x08\x0b\x0c\x0e-\x1f]")
PUA = re.compile("[\ue000-\uf8ff]")
HTML = re.compile(r"<(?!!--)/?[a-zA-Z][^>]*>|&(nbsp|amp|lt|gt|quot|#\d+);")


@dataclass
class Problem:
    file: Path
    line: int
    rule: str
    text: str
    error: bool

    def __str__(self) -> str:
        level = "error" if self.error else "warning"
        try:
            name = self.file.relative_to(ROOT)
        except ValueError:
            name = self.file
        return f"{name}:{self.line}: {level} {self.rule}: {self.text[:80]}"


def lint_text(path: Path, text: str) -> list[Problem]:
    problems: list[Problem] = []

    def add(line: int, rule: str, content: str = "", error: bool = True):
        problems.append(Problem(path, line, rule, content, error))

    lines = text.split("\n")
    first = next((i for i, line in enumerate(lines) if line.strip()), None)
    if first is None:
        add(1, "empty-file")
        return problems
    if not lines[first].startswith("# "):
        add(first + 1, "no-title", lines[first])
    info = next((i for i, line in enumerate(lines) if line.strip().startswith(INFO_END)), None)
    if info is None:
        add(1, "no-info-end")
        return problems

    # 头部：每行「日期 事件」
    header = [(i, line.strip()) for i, line in enumerate(lines[first + 1:info], first + 2) if line.strip()]
    if not header:
        add(first + 1, "header-empty", error=False)
    for n, line in header:
        if line.startswith("#"):
            continue
        if line.count("）") + line.count(")") > line.count("（") + line.count("("):
            add(n, "header-unbalanced-paren", line)
        elif line.startswith(("（", "(")):
            add(n, "header-leading-paren", line)
        elif not DATE.match(line):
            # 司法解释的文号、案例的来源等也写在头部，只提示
            add(n, "header-not-date", line, error=False)
        if re.search(r"(根据|并经|[，,；;、])$", line):
            add(n, "header-dangling", line)

    date = split_stem(path.stem)[1]
    if date and header and not any(to_cn(date) in norm(line) for _, line in header):
        add(1, "filename-date-not-in-header", f"({date})", error=False)

    # 正文
    body = [(i, line) for i, line in enumerate(lines[info + 1:], info + 2) if line.strip()]
    if not body:
        add(info + 1, "empty-body")
    headings = []
    articles = []
    for n, raw in body:
        line = raw.strip()
        if BAD_CHAR.search(raw):
            add(n, "bad-char", repr(BAD_CHAR.search(raw).group(0)) + " " + line)
        if HTML.search(line):
            add(n, "html", line)
        if PUA.search(line):
            # 私用区字符可能是生僻字，也可能是乱码，只提示
            add(n, "private-use-char", repr(PUA.search(line).group(0)) + " " + line, error=False)
        if line.startswith("#"):
            title = line.lstrip("#").strip()
            if not re.match(r"^#+ ", line):
                add(n, "heading-no-space", line)
            if not title:
                add(n, "heading-empty", line)
            if re.fullmatch("目录", norm(title)):
                add(n, "toc", line)
            if line.startswith("# "):
                add(n, "title-in-body", line)
            headings.append((n, norm(title)))
            continue
        if re.fullmatch("目录[：:]?", norm(line)):
            add(n, "toc", line)
        if re.fullmatch("序言", norm(line)):
            add(n, "preface-not-heading", line)
        if STRUCTURE.match(norm(line)) and len(norm(line)) <= 30 and not re.search("[，。；：]", line):
            # 修正案引述的「第七节 监察委员会」这类是正文，只提示
            add(n, "structure-not-heading", line, error=False)
        a = ARTICLE.match(line)
        if a and "之" not in line.split()[0]:
            articles.append((n, cn_to_int(a.group(1)), line))

    # 目录漏进正文：同一个标题出现两次，第一次后面紧跟的还是标题
    seen = {}
    for n, title in headings:
        if title in seen:
            add(n, "duplicate-heading", title, error=False)
        seen.setdefault(title, n)

    if len(articles) >= 3:
        if articles[0][1] != 1:
            add(articles[0][0], "article-not-from-1", articles[0][2], error=False)
        for (_, a, _), (n, b, line) in itertools.pairwise(articles):
            if b == a:
                add(n, "article-duplicate", line, error=False)
            elif b != a + 1:
                add(n, "article-gap", f"{a} -> {b}: {line}", error=False)
    return problems


# ---------- 自动修复 ----------

# 能直接删掉的字符；� 是解码时丢失的原文，删了也找不回来，留给人工处理
REMOVABLE_CHAR = re.compile("[\ufeff\u200b\u200c\u200d\u2060\xad\x00-\x08\x0b\x0c\x0e-\x1f]")
DATE_ANYWHERE = r"\d{4}年\d{1,2}月\d{1,2}日"
# 两条头部挤在一行：「…第四次修正  2022年12月2日四川省…」，「根据」原本连着下一条
MERGED_HEADER = re.compile(rf"(?<=通过|修正|修订|批准|公布)[\s　]*(?:根据)?[\s　]*(?={DATE_ANYWHERE})")
DANGLING = re.compile(r"[\s　]*(?:根据|根|并经|[，,；;、])$")
CLOSE, OPEN = "）)", "（("


def _unbalanced(line: str) -> int:
    return sum(line.count(c) for c in CLOSE) - sum(line.count(c) for c in OPEN)


def fix_header_line(line: str) -> list[str]:
    """一行头部修成一行或几行。"""
    if line.lstrip().startswith("#"):
        return [line]
    ret = []
    parts = MERGED_HEADER.split(line)
    for part in parts:
        # 「2022年12月2日四川省…」补上日期后面的空格，「…日起施行」不算
        part = re.sub(rf"^([\s　]*{DATE_ANYWHERE})(?=[^\s　起])", r"\1 ", part)
        while True:
            fixed = part.strip(" \t　")
            fixed = DANGLING.sub("", fixed)
            # 原文整段头部包在括号里，按日期拆开后括号落在首行开头和末行结尾
            if _unbalanced(fixed) > 0 and fixed.endswith(tuple(CLOSE)):
                fixed = fixed[:-1]
            if _unbalanced(fixed) < 0 and fixed.startswith(tuple(OPEN)):
                fixed = fixed[1:]
            if fixed == part:
                break
            part = fixed
        if part:
            ret.append(part)
    return ret or [""]


def fix_text(text: str) -> str:
    """能按规则修好的格式问题：不可见字符、私用区字符、头部多出的括号、行尾悬空的「根据」、挤在一行的两条头部。"""
    text = fix_private_use(REMOVABLE_CHAR.sub("", text))
    lines = text.split("\n")
    first = next((i for i, line in enumerate(lines) if line.strip()), None)
    info = next((i for i, line in enumerate(lines) if line.strip().startswith(INFO_END)), None)
    if first is None or info is None or info <= first:
        return text
    header = []
    for line in lines[first + 1:info]:
        if not line.strip():
            header.append(line)
            continue
        fixed = fix_header_line(line)
        # 头部每条之间空一行
        header.append("\n\n".join(fixed))
    return "\n".join(lines[:first + 1] + header + lines[info:])


def lint_file(path: Path) -> list[Problem]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        return [Problem(path, 1, "not-utf8", str(e), True)]
    return lint_text(path, text)


def iter_files(targets: Iterable[Path], dlc: bool) -> Iterable[Path]:
    """要检查的文件：仓库根目录按本体（dlc 时加上 DLC）的法规文件，其他目录取其下全部法规文件。"""
    for target in targets:
        if target.is_file():
            yield target
        elif target.resolve() == ROOT:
            yield from law_files(include_dlc=dlc)
        else:
            yield from pack_files(target)


def run(paths: list[Path], dlc: bool = False, show_warnings: bool = False, diff: bool = False, fix: bool = False) -> int:
    """检查（diff 时只列出能自动修复的改动，fix 时先修复再检查），返回退出码：有 error 时为 1。"""
    files = list(iter_files(paths or [ROOT], dlc))
    if diff or fix:
        changed = 0
        for f in files:
            try:
                old = f.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            new = fix_text(old)
            if new == old:
                continue
            changed += 1
            if fix:
                f.write_text(new, encoding="utf-8")
            else:
                try:
                    name = f.relative_to(ROOT)
                except ValueError:
                    name = f
                sys.stdout.writelines(difflib.unified_diff(
                    old.splitlines(True), new.splitlines(True), f"a/{name}", f"b/{name}", n=0))
        print(f"{'已修复' if fix else '可以自动修复'} {changed} 个文件", file=sys.stderr)
        if diff:
            return 0
        print("修复后重新检查：", file=sys.stderr)

    errors = warnings = 0
    for f in files:
        for p in lint_file(f):
            if p.error:
                errors += 1
            else:
                warnings += 1
            if p.error or show_warnings:
                print(p)
    print(f"{len(files)} 个文件，{errors} 个 error，{warnings} 个 warning", file=sys.stderr)
    return 1 if errors else 0

