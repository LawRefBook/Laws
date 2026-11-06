#!/usr/bin/env python3
"""检查法规 markdown 的格式。

    python3 scripts/lint.py                # 本体全部文件
    python3 scripts/lint.py --dlc          # 包括 DLC
    python3 scripts/lint.py a.md 目录/     # 指定文件或目录
    python3 scripts/lint.py --warnings     # 同时列出 warning
    python3 scripts/lint.py --diff         # 列出能自动修复的改动，不写文件
    python3 scripts/lint.py --fix          # 自动修复后再检查，剩下的需要手动处理

有 error 时退出码为 1。error 是会在 App 里直接显示出来的格式问题；warning 可能是原文本身如此，只报告。
"""
import argparse
import difflib
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

from common import fix_private_use

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {"scripts", ".venv", ".release", ".git", ".github", "DLC"}
SKIP_FILES = {"README.md", "法律法规模版.md"}  # 另外跳过网站用的 _index.md

CN = "零〇一二三四五六七八九十百千"
ARTICLE = re.compile(rf"^第([{CN}]+)条(?:之[{CN}]+)?(?:\s|$)")
STRUCTURE = re.compile(rf"^第[{CN}0-9]+(?:编|分编|章|节)")
DATE = re.compile(r"^\d{4}年\d{1,2}月\d{1,2}日 \S")
BAD_CHAR = re.compile("[�﻿​‌‍⁠\xad\x00-\x08\x0b\x0c\x0e-\x1f]")
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


def cn2int(s: str) -> int:
    digits = dict(zip("零〇一二三四五六七八九", [0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9]))
    if not any(c in s for c in "十百千"):
        value = 0
        for c in s:
            value = value * 10 + digits[c]
        return value
    total, cur = 0, 0
    for c in s:
        if c in digits:
            cur = digits[c]
        else:
            total += (cur or 1) * {"十": 10, "百": 100, "千": 1000}[c]
            cur = 0
    return total + cur


def norm(text: str) -> str:
    return re.sub(r"[\s　]+", "", text)


def lint_text(path: Path, text: str) -> List[Problem]:
    problems: List[Problem] = []

    def add(line: int, rule: str, content: str = "", error: bool = True):
        problems.append(Problem(path, line, rule, content, error))

    lines = text.split("\n")
    first = next((i for i, l in enumerate(lines) if l.strip()), None)
    if first is None:
        add(1, "empty-file")
        return problems
    if not lines[first].startswith("# "):
        add(first + 1, "no-title", lines[first])
    info = next((i for i, l in enumerate(lines) if l.strip().startswith("<!-- INFO END -->")), None)
    if info is None:
        add(1, "no-info-end")
        return problems

    # 头部：每行「日期 事件」
    header = [(i, l.strip()) for i, l in enumerate(lines[first + 1:info], first + 2) if l.strip()]
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

    stem = path.stem
    m = re.search(r"\((\d{4})-(\d{2})-(\d{2})\)$", stem)
    if m and header:
        date = f"{int(m.group(1))}年{int(m.group(2))}月{int(m.group(3))}日"
        if not any(date in norm(l) for _, l in header):
            add(1, "filename-date-not-in-header", f"{m.group(0)}", error=False)

    # 正文
    body = [(i, l) for i, l in enumerate(lines[info + 1:], info + 2) if l.strip()]
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
            articles.append((n, cn2int(a.group(1)), line))

    # 目录漏进正文：同一个标题出现两次，第一次后面紧跟的还是标题
    seen = {}
    for idx, (n, title) in enumerate(headings):
        if title in seen:
            add(n, "duplicate-heading", title, error=False)
        seen.setdefault(title, n)

    if len(articles) >= 3:
        if articles[0][1] != 1:
            add(articles[0][0], "article-not-from-1", articles[0][2], error=False)
        for (_, a, _), (n, b, line) in zip(articles, articles[1:]):
            if b == a:
                add(n, "article-duplicate", line, error=False)
            elif b != a + 1:
                add(n, "article-gap", f"{a} -> {b}: {line}", error=False)
    return problems


# ---------- 自动修复 ----------

# 能直接删掉的字符；� 是解码时丢失的原文，删了也找不回来，留给人工处理
REMOVABLE_CHAR = re.compile("[﻿​‌‍⁠\xad\x00-\x08\x0b\x0c\x0e-\x1f]")
DATE_ANYWHERE = r"\d{4}年\d{1,2}月\d{1,2}日"
# 两条头部挤在一行：「…第四次修正  2022年12月2日四川省…」，「根据」原本连着下一条
MERGED_HEADER = re.compile(rf"(?<=通过|修正|修订|批准|公布)[\s　]*(?:根据)?[\s　]*(?={DATE_ANYWHERE})")
DANGLING = re.compile(r"[\s　]*(?:根据|根|并经|[，,；;、])$")
CLOSE, OPEN = "）)", "（("


def _unbalanced(line: str) -> int:
    return sum(line.count(c) for c in CLOSE) - sum(line.count(c) for c in OPEN)


def fix_header_line(line: str) -> List[str]:
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
    first = next((i for i, l in enumerate(lines) if l.strip()), None)
    info = next((i for i, l in enumerate(lines) if l.strip().startswith("<!-- INFO END -->")), None)
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


def lint_file(path: Path) -> List[Problem]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        return [Problem(path, 1, "not-utf8", str(e), True)]
    return lint_text(path, text)


def iter_files(targets: Iterable[Path], dlc: bool) -> Iterable[Path]:
    skip = SKIP_DIRS - ({"DLC"} if dlc else set())
    for target in targets:
        if target.is_file():
            yield target
            continue
        for f in sorted(target.rglob("*.md")):
            rel = f.relative_to(target)
            if f.name in SKIP_FILES or f.name.startswith("_") or any(p in skip or p.startswith(".") for p in rel.parts[:-1]):
                continue
            yield f


def main() -> int:
    parser = argparse.ArgumentParser(description="检查法规 markdown 的格式")
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--dlc", action="store_true", help="包括 DLC")
    parser.add_argument("--warnings", action="store_true", help="同时列出 warning")
    fix = parser.add_mutually_exclusive_group()
    fix.add_argument("--diff", action="store_true", help="列出能自动修复的改动，不写文件")
    fix.add_argument("--fix", action="store_true", help="自动修复后再检查")
    args = parser.parse_args()

    files = list(iter_files(args.paths or [ROOT], args.dlc))
    if args.diff or args.fix:
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
            if args.fix:
                f.write_text(new, encoding="utf-8")
            else:
                try:
                    name = f.relative_to(ROOT)
                except ValueError:
                    name = f
                sys.stdout.writelines(difflib.unified_diff(
                    old.splitlines(True), new.splitlines(True), f"a/{name}", f"b/{name}", n=0))
        print(f"{'已修复' if args.fix else '可以自动修复'} {changed} 个文件", file=sys.stderr)
        if args.diff:
            return 0
        print("修复后重新检查：", file=sys.stderr)

    errors = warnings = 0
    for f in files:
        for p in lint_file(f):
            if p.error:
                errors += 1
            else:
                warnings += 1
            if p.error or args.warnings:
                print(p)
    print(f"{len(files)} 个文件，{errors} 个 error，{warnings} 个 warning", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
