"""部门规章下的同名规章：找出来（`laws report duplicates`），合并（`laws merge-duplicates`）。

联合发布的规章在国家规章库里每个部门各列一次，下载后可能散在几个部门目录里，
日期也可能一个取公布日、一个取施行日。按名称分组，正文几乎相同、令号不冲突、
且较新的一份头部没写之后有修正修订的，是「疑似同一版本」。

合并时：
1. 同一版本只留一份：有头部信息、正文更全的优先；文件名用头部里最后一次修正修订的日期，
   没有就用公布、发布的日期。
2. 同一部规章的各个版本放进同一个目录：牵头部门（发布那一行排第一的部门）的目录，
   找不到就用这一组里文件最多的目录。
"""
import difflib
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from lawref.dates import DATE, iso_of
from lawref.document import INFO_END, header_lines, split_filename
from lawref.paths import MAIN_DB, ROOT
from lawref.text import strip_prc

RULES = ROOT / "部门规章"
# 正文相似度超过这个值算同一版本
SAME_VERSION = 0.95


def version_date(path: Path) -> str:
    """文件名里的日期。只处理带日期的文件。"""
    return split_filename(path.name)[1]


def dated_rules() -> dict[str, list[Path]]:
    """部门规章下文件名带日期的规章，按名称分组，组内按路径排序。"""
    groups: dict[str, list[Path]] = defaultdict(list)
    for f in sorted(RULES.rglob("*.md")):
        name, date = split_filename(f.name)
        if date:
            groups[name].append(f)
    return groups


def body(path: Path) -> str:
    """正文去掉空白和 #，用来比较；没有 INFO END 时为空。"""
    text = path.read_text(encoding="utf-8").partition(INFO_END)[2]
    return re.sub(r"[\s#]", "", text)


def header(path: Path) -> list[str]:
    return header_lines(path.read_text(encoding="utf-8"))


def revisions(path: Path) -> list[str]:
    """头部里修正、修订、修改的日期。"""
    return [iso_of(m) for line in header(path) if (m := DATE.match(line)) and re.search("修正|修订|修改", line)]


# 「令第15号」「令14」「第126号令」「令2020年第6号」
_ORDER_NO = re.compile(r"令(?:\d{4}年)?第?(\d+)号?|第(\d+)号令")


def order_numbers(path: Path) -> set:
    return {m.group(1) or m.group(2) for line in header(path) for m in _ORDER_NO.finditer(line)}


def same_version(a: Path, b: Path, bodies: dict[Path, str]) -> bool:
    """b 的日期不早于 a。

    b 的头部写明在 a 之后修正过，或者两份的令号不同（废止后重新制定），就是不同版本，正文再像也不算。
    """
    date_a = version_date(a)
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


def score(path: Path):
    return (bool(header(path)), len(body(path)))


def effective_version(path: Path) -> str:
    """最后一次修正修订的日期，没有就用公布、发布的日期，都没有用文件名里的日期。"""
    if revs := revisions(path):
        return max(revs)
    for line in header(path):
        m = DATE.match(line)
        if m and _ISSUE.search(line) and "施行" not in line:
            return iso_of(m)
    return version_date(path)


def lead_department(paths: list[Path]) -> str | None:
    """发布那一行排第一的部门，换成目录名。"""
    folders = {p.name for p in RULES.iterdir() if p.is_dir()}
    for path in paths:
        for line in header(path):
            m = DATE.match(line)
            if not m or not _ISSUE.search(line):
                continue
            rest = re.sub(r"^[，,\s]*(中华人民共和国)?", "", line[m.end():])
            # 机构名可能用「、」「 」分隔，也可能直接接「令」
            first = re.split(r"[、，,\s]|令|第\d|\d{4}年", rest)[0]
            first = strip_prc(first)
            name = DEPARTMENT_ALIASES.get(first, first)
            if name in folders:
                return name
    return None


def clusters(files: list[Path]) -> list[list[Path]]:
    """同一版本的文件归成一组（files 已按日期排好）。"""
    bodies: dict[Path, str] = {f: body(f) for f in files}
    parent = {f: f for f in files}

    def find(f):
        while parent[f] != f:
            f = parent[f]
        return f

    for i, a in enumerate(files):
        for b in files[i + 1:]:
            if same_version(a, b, bodies):
                parent[find(b)] = find(a)
    groups: dict[Path, list[Path]] = {}
    for f in files:
        groups.setdefault(find(f), []).append(f)
    return list(groups.values())


# ---------- 找出来 ----------

@dataclass
class DuplicateGroup:
    name: str
    # 按日期排序
    files: list[Path]
    folders: set[Path]
    # 疑似同一版本的 (较早的, 较晚的)
    same: list[tuple[Path, Path]]


def find_duplicates(show_all: bool = False) -> list[DuplicateGroup]:
    """分在不同目录、或者有疑似同一版本的同名规章，按名称排序。show_all 时同一目录下正常的多个版本也列出。"""
    ret = []
    for name, files in sorted(dated_rules().items()):
        if len(files) < 2:
            continue
        files.sort(key=version_date)
        folders = {f.parent for f in files}
        bodies = {f: body(f) for f in files}
        same = [(a, b) for i, a in enumerate(files) for b in files[i + 1:] if same_version(a, b, bodies)]
        if show_all or len(folders) > 1 or same:
            ret.append(DuplicateGroup(name, files, folders, same))
    return ret


# ---------- 合并 ----------

@dataclass
class MergeStep:
    """一个版本：留下 keep，移到 dest，删掉 drop。"""
    keep: Path
    dest: Path
    drop: list[Path]

    @property
    def changed(self) -> bool:
        return self.keep != self.dest or bool(self.drop)


@dataclass
class MergePlan:
    name: str
    target_dir: Path
    steps: list[MergeStep]


def merge_plans() -> list[MergePlan]:
    """需要合并的同名规章，按名称排序。"""
    plans = []
    for name, files in sorted(dated_rules().items()):
        if len(files) < 2:
            continue
        files.sort(key=version_date)
        versions = clusters(files)
        if len({f.parent for f in files}) < 2 and all(len(c) == 1 for c in versions):
            continue

        # 算出的版本日期相同的，正文排版差得多也是同一版本（一份用公布日、一份用施行日）
        by_date: dict[str, list[Path]] = {}
        for cluster in versions:
            by_date.setdefault(effective_version(max(cluster, key=score)), []).extend(cluster)
        keepers = {date: max(cluster, key=score) for date, cluster in by_date.items()}
        # 目录看最新版本的牵头部门
        lead = lead_department([keepers[d] for d in sorted(keepers, reverse=True)])
        target_dir = RULES / lead if lead else Counter(f.parent for f in files).most_common(1)[0][0]
        steps = [MergeStep(keepers[date], target_dir / f"{name}({date}).md", [f for f in cluster if f != keepers[date]])
                 for date, cluster in sorted(by_date.items())]
        if any(step.changed for step in steps):
            plans.append(MergePlan(name, target_dir, steps))
    return plans


def _record_ids(db: sqlite3.Connection, path: Path) -> list[str]:
    name, date = split_filename(path.name)
    return [row[0] for row in db.execute(
        "SELECT id FROM law WHERE name = ? AND publish = ? AND category_id IN (SELECT id FROM category WHERE folder = ?)",
        (name, date, str(path.parent.relative_to(ROOT))))]


def apply_merge(plans: list[MergePlan], db_path: Path = MAIN_DB) -> int:
    """移动、删除文件，返回删掉的数据库记录数，之后运行 `laws db update` 重新入库。

    合并后的每个文件留一条记录：文件名不变时，update 按名称和日期认出移动，ID 不变（留下的那份没有记录时，
    用同名同日期被删掉的那份的记录）。其余的记录删掉，它们的文件没有了。没有变化的版本不动。
    """
    removed = 0
    db = sqlite3.connect(db_path)
    try:
        for plan in plans:
            for step in plan.steps:
                if not step.changed:
                    continue
                same_name = [f for f in (step.keep, *step.drop) if f.name == step.dest.name]
                kept = next((ids[:1] for f in same_name if (ids := _record_ids(db, f))), [])
                for f in (step.keep, *step.drop):
                    for id in _record_ids(db, f):
                        if id not in kept:
                            removed += db.execute("DELETE FROM law WHERE id = ?", (id,)).rowcount
                text = step.keep.read_text(encoding="utf-8")
                for f in step.drop:
                    f.unlink()
                step.keep.unlink()
                step.dest.parent.mkdir(parents=True, exist_ok=True)
                step.dest.write_text(text, encoding="utf-8")
        db.commit()
    finally:
        db.close()
    return removed
