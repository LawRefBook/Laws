#!/usr/bin/env python3
"""检查部门规章下的同名规章。在仓库根目录运行：

    .venv/bin/python scripts/find_duplicate_rules.py [--all]

联合发布的规章在国家规章库里每个部门各列一次，下载后可能散在几个部门目录里，
日期也可能一个取公布日、一个取施行日。按名称分组，列出每一份的目录、日期和头部，
正文几乎相同、令号不冲突、且较新的一份头部没写之后有修正修订的，标为「疑似同一版本」。

默认只列出分在不同目录、或有疑似同一版本的组；--all 连同一目录下的正常多版本也列出。
"""
import difflib
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parent.parent
RULES = ROOT / "部门规章"
DATED = re.compile(r"^(.+)\((\d{4}-\d{2}-\d{2})\)\.md$")
# 正文相似度超过这个值算同一版本
SAME_VERSION = 0.95


def body(path: Path) -> str:
    text = path.read_text(encoding="utf-8").partition("<!-- INFO END -->")[2]
    return re.sub(r"[\s#]", "", text)


def header(path: Path) -> List[str]:
    head = path.read_text(encoding="utf-8").partition("<!-- INFO END -->")[0]
    return [line for line in head.splitlines()[1:] if line.strip()]


_HEADER_DATE = re.compile(r"^(\d{4})年(\d{1,2})月(\d{1,2})日")


def revisions(path: Path) -> List[str]:
    """头部里修正、修订、修改的日期。"""
    ret = []
    for line in header(path):
        m = _HEADER_DATE.match(line)
        if m and re.search("修正|修订|修改", line):
            ret.append("-".join(f"{int(x):02d}" for x in m.groups()))
    return ret


# 「令第15号」「令14」「第126号令」「令2020年第6号」
_ORDER_NO = re.compile(r"令(?:\d{4}年)?第?(\d+)号?|第(\d+)号令")


def order_numbers(path: Path) -> set:
    return {m.group(1) or m.group(2) for line in header(path) for m in _ORDER_NO.finditer(line)}


def same_version(a: Path, b: Path, bodies: Dict[Path, str]) -> bool:
    """b 的日期不早于 a。

    b 的头部写明在 a 之后修正过，或者两份的令号不同（废止后重新制定），就是不同版本，正文再像也不算。
    """
    date_a = DATED.match(a.name).group(2)
    if any(d > date_a for d in revisions(b)):
        return False
    orders_a, orders_b = order_numbers(a), order_numbers(b)
    if orders_a and orders_b and not orders_a & orders_b:
        return False
    return similar(bodies[a], bodies[b]) >= SAME_VERSION


def similar(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    m = difflib.SequenceMatcher(None, a, b, autojunk=False)
    # 先用上限快速排除，长文本时省很多时间
    if m.real_quick_ratio() < SAME_VERSION or m.quick_ratio() < SAME_VERSION:
        return 0.0
    return m.ratio()


def main(show_all: bool) -> int:
    groups: Dict[str, List[Path]] = defaultdict(list)
    for f in RULES.rglob("*.md"):
        if m := DATED.match(f.name):
            groups[m.group(1)].append(f)

    reported = 0
    for name, files in sorted(groups.items()):
        if len(files) < 2:
            continue
        files.sort(key=lambda f: DATED.match(f.name).group(2))
        folders = {f.parent for f in files}
        bodies = {f: body(f) for f in files}
        same = [(a, b) for i, a in enumerate(files) for b in files[i + 1:] if same_version(a, b, bodies)]
        if not show_all and len(folders) < 2 and not same:
            continue

        reported += 1
        print(f"\n{name}（{len(files)} 份，{len(folders)} 个目录）")
        for f in files:
            date = DATED.match(f.name).group(2)
            print(f"  {date}  {f.parent.name:<14}  {' / '.join(header(f)) or '（没有头部信息）'}")
        for a, b in same:
            print(f"  ⚠️ 疑似同一版本：{a.parent.name}/{DATED.match(a.name).group(2)} ≈ {b.parent.name}/{DATED.match(b.name).group(2)}")

    print(f"\n共 {reported} 组")
    return 0


if __name__ == "__main__":
    sys.exit(main("--all" in sys.argv[1:]))
