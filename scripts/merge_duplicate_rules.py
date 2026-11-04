#!/usr/bin/env python3
"""合并部门规章下的同名规章。在仓库根目录运行：

    .venv/bin/python scripts/merge_duplicate_rules.py [--apply]

按 find_duplicate_rules.py 的分组：
1. 同一版本只留一份：有头部信息、正文更全的优先；文件名用头部里最后一次修正修订的日期，
   没有就用公布、发布的日期。
2. 同一部规章的各个版本放进同一个目录：牵头部门（发布那一行排第一的部门）的目录，
   找不到就用这一组里文件最多的目录。

不加 --apply 只列出计划。执行后数据库里对应的记录会删掉，运行 update 重新入库。
"""
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

from find_duplicate_rules import DATED, ROOT, RULES, body, header, revisions, same_version

# 发布行里的机构名（含旧机构、简称）→ 部门规章下的目录名
DEPARTMENT_ALIASES = {
    "国家发展改革委": "国家发展和改革委员会", "国家发展计划委员会": "国家发展和改革委员会", "国家计委": "国家发展和改革委员会",
    "国家经济贸易委员会": "国家发展和改革委员会", "国家经贸委": "国家发展和改革委员会",
    "信息产业部": "工业和信息化部", "工信部": "工业和信息化部",
    "国防科学技术工业委员会": "国家国防科技工业局", "国防科工委": "国家国防科技工业局",
    "人事部": "人力资源社会保障部", "人力资源和社会保障部": "人力资源社会保障部", "劳动和社会保障部": "人力资源社会保障部",
    "国家工商行政管理总局": "市场监督管理总局", "国家工商行政管理局": "市场监督管理总局", "工商总局": "市场监督管理总局",
    "国家质量监督检验检疫总局": "市场监督管理总局", "质检总局": "市场监督管理总局", "国家市场监督管理总局": "市场监督管理总局",
    "市场监管总局": "市场监督管理总局",
    "国家广播电影电视总局": "国家广播电视总局", "国家新闻出版广电总局": "国家新闻出版署",
    "对外贸易经济合作部": "商务部", "外经贸部": "商务部",
    "国土资源部": "自然资源部", "环境保护部": "生态环境部", "国家环境保护总局": "生态环境部",
    "农业部": "农业农村部", "建设部": "住房和城乡建设部", "住房城乡建设部": "住房和城乡建设部",
    "卫生部": "国家卫生健康委员会", "卫生计生委": "国家卫生健康委员会", "国家卫生和计划生育委员会": "国家卫生健康委员会",
    "国家网信办": "国家互联网信息办公室", "国家宗教局": "国家宗教事务局", "国家林业局": "国家林业和草原局",
    "国家安全监管总局": "应急管理部", "国家安全生产监督管理总局": "应急管理部",
    "中国证监会": "中国证券监督管理委员会", "证监会": "中国证券监督管理委员会",
    "人民银行": "中国人民银行", "国务院国资委": "国务院国有资产监督管理委员会", "国资委": "国务院国有资产监督管理委员会",
}
_ISSUE = re.compile(r"公布|发布|令")
_DATE = re.compile(r"^(\d{4})年(\d{1,2})月(\d{1,2})日\s*")


def score(path: Path):
    return (bool(header(path)), len(body(path)))


def version_date(path: Path) -> str:
    """最后一次修正修订的日期，没有就用公布、发布的日期，都没有用文件名里的日期。"""
    if revs := revisions(path):
        return max(revs)
    for line in header(path):
        m = _DATE.match(line)
        if m and _ISSUE.search(line) and "施行" not in line:
            return "-".join(f"{int(x):02d}" for x in m.groups())
    return DATED.match(path.name).group(2)


def lead_department(paths: List[Path]) -> Optional[str]:
    """发布那一行排第一的部门，换成目录名。"""
    folders = {p.name for p in RULES.iterdir() if p.is_dir()}
    for path in paths:
        for line in header(path):
            m = _DATE.match(line)
            if not m or not _ISSUE.search(line):
                continue
            rest = re.sub(r"^[，,\s]*(中华人民共和国)?", "", line[m.end():])
            # 机构名可能用「、」「 」分隔，也可能直接接「令」
            first = re.split(r"[、，,\s]|令|第\d|\d{4}年", rest)[0]
            first = re.sub("^中华人民共和国", "", first)
            name = DEPARTMENT_ALIASES.get(first, first)
            if name in folders:
                return name
    return None


def clusters(files: List[Path]) -> List[List[Path]]:
    """同一版本的文件归成一组（files 已按日期排好）。"""
    bodies: Dict[Path, str] = {f: body(f) for f in files}
    parent = {f: f for f in files}

    def find(f):
        while parent[f] != f:
            f = parent[f]
        return f

    for i, a in enumerate(files):
        for b in files[i + 1:]:
            if same_version(a, b, bodies):
                parent[find(b)] = find(a)
    groups: Dict[Path, List[Path]] = {}
    for f in files:
        groups.setdefault(find(f), []).append(f)
    return list(groups.values())


def main(apply: bool) -> int:
    groups: Dict[str, List[Path]] = {}
    for f in RULES.rglob("*.md"):
        if m := DATED.match(f.name):
            groups.setdefault(m.group(1), []).append(f)

    db = sqlite3.connect(ROOT / "db.sqlite3")
    removed_records = 0
    for name, files in sorted(groups.items()):
        if len(files) < 2:
            continue
        files.sort(key=lambda f: DATED.match(f.name).group(2))
        versions = clusters(files)
        folders = {f.parent for f in files}
        if len(folders) < 2 and all(len(c) == 1 for c in versions):
            continue

        # 算出的版本日期相同的，正文排版差得多也是同一版本（一份用公布日、一份用施行日）
        by_date: Dict[str, List[Path]] = {}
        for cluster in versions:
            by_date.setdefault(version_date(max(cluster, key=score)), []).extend(cluster)
        keepers = {date: max(cluster, key=score) for date, cluster in by_date.items()}
        # 目录看最新版本的牵头部门
        lead = lead_department([keepers[d] for d in sorted(keepers, reverse=True)])
        target_dir = RULES / lead if lead else Counter(f.parent for f in files).most_common(1)[0][0]
        plan = []
        for date, cluster in sorted(by_date.items()):
            keeper = keepers[date]
            plan.append((keeper, target_dir / f"{name}({date}).md", [f for f in cluster if f != keeper]))

        changes = [(k, d, drop) for k, d, drop in plan if k != d or drop]
        if not changes:
            continue
        print(f"\n{name} → {target_dir.name}/")
        for keeper, dest, drop in plan:
            rel = lambda p: str(p.relative_to(RULES))
            print(f"  保留 {rel(keeper)}" + (f" → {rel(dest)}" if keeper != dest else ""))
            for f in drop:
                print(f"  删除 {rel(f)}")
        if not apply:
            continue
        for keeper, dest, drop in plan:
            for f in [keeper, *drop]:
                m = DATED.match(f.name)
                folder = str(f.parent.relative_to(ROOT))
                removed_records += db.execute(
                    "delete from law where name = ? and publish = ? and category_id in (select id from category where folder = ?)",
                    (m.group(1), m.group(2), folder)).rowcount
            text = keeper.read_text(encoding="utf-8")
            for f in drop:
                f.unlink()
            keeper.unlink()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(text, encoding="utf-8")
    if apply:
        db.commit()
        print(f"\n删除了 {removed_records} 条数据库记录，运行 `cd scripts && ./update_all_db.sh` 重新入库")
    else:
        print("\n以上为计划，加 --apply 执行")
    return 0


if __name__ == "__main__":
    sys.exit(main("--apply" in sys.argv[1:]))
