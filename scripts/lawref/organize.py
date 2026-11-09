"""把抓取到 __cache__/out/ 的法规整理进仓库：定目录、去重、lint，已有的文件不覆盖。"""
import difflib
from pathlib import Path

from lawref import lint
from lawref.document import canonical_filename, split_filename
from lawref.fetch.pipeline import law_dates
from lawref.paths import CACHE_DIR, DIFF_DIR, OUT_DIR, ROOT
from lawref.repo import is_manual_law, law_files
from lawref.text import short_title

# 报告的各部分，按这个顺序列出
SECTIONS = ("新增", "相同", "有变化", "疑似已收录", "lint 未通过", "无法确定目录", "跳过")
Report = dict[str, list[str]]


def suspected_duplicate(f: Path, versions: dict[str, list[Path]]) -> Path | None:
    """同名法规已有文件，而新文件的发布日期或头部最新日期已经出现在其中，多半是同一版本。"""
    name, date = split_filename(canonical_filename(f.name))
    new_dates = law_dates(f)
    keys = {date} if date else set()
    if new_dates:
        keys.add(max(new_dates))
    for existing in versions.get(name, []):
        if keys & law_dates(existing):
            return existing
    return None


def organize_target(rel: Path, folders: dict[str, set[Path]]) -> tuple[Path | None, str]:
    """out/ 里的文件应该放到仓库哪里。返回 (目标路径, 无法确定时的原因)。"""
    top = rel.parts[0]
    name = canonical_filename(rel.name)
    if top.endswith("地方法规"):
        return ROOT / "DLC" / rel.parent / name, ""
    if top == "部门规章":
        return ROOT / rel.parent / name, ""
    candidates = folders.get(split_filename(name)[0], set())
    if len(candidates) == 1:
        return ROOT / next(iter(candidates)) / name, ""
    if len(candidates) > 1:
        return None, "同名法规在多个目录：" + "、".join(sorted(map(str, candidates)))
    if top in ("行政法规", "司法解释"):
        return ROOT / top / name, ""
    return None, "新法规，需要手动选择目录"


def organize(apply: bool = False, force: bool = False) -> tuple[Report, int]:
    """列出 out/ 里每个文件的去向，apply 时移入仓库。返回 (报告, 移入的部数)。

    仓库里已有、内容不同的不覆盖，diff 写到 __cache__/diff/；force 时疑似已收录、lint 有 error 的也移入。
    """
    folders: dict[str, set[Path]] = {}
    for f in law_files():
        folders.setdefault(short_title(split_filename(f.name)[0]), set()).add(f.parent.relative_to(ROOT))
    versions: dict[str, list[Path]] = {}
    for f in law_files(include_dlc=True):
        versions.setdefault(short_title(split_filename(f.name)[0]), []).append(f)

    report: Report = {k: [] for k in SECTIONS}
    moved = 0
    for f in sorted(OUT_DIR.rglob("*.md")):
        rel = f.relative_to(OUT_DIR)
        if is_manual_law(split_filename(rel.name)[0]):
            report["跳过"].append(f"{rel}：刑法、民法典在仓库里手动维护")
            continue
        target, reason = organize_target(rel, folders)
        if target is None:
            report["无法确定目录"].append(f"{rel}：{reason}")
            continue
        shown = target.relative_to(ROOT)

        if target.exists():
            old, new = target.read_text(encoding="utf-8"), f.read_text(encoding="utf-8")
            if old.strip() == new.strip():
                report["相同"].append(str(shown))
                if apply:
                    f.unlink()
                continue
            diff_file = DIFF_DIR / rel.with_suffix(".diff")
            diff_file.parent.mkdir(parents=True, exist_ok=True)
            diff_file.write_text("".join(difflib.unified_diff(
                old.splitlines(True), new.splitlines(True), f"仓库/{shown}", f"抓取/{rel}")), encoding="utf-8")
            report["有变化"].append(f"{shown}（diff：{diff_file.relative_to(CACHE_DIR.parent)}）")
            continue

        if not force and (same := suspected_duplicate(f, versions)):
            report["疑似已收录"].append(f"{rel}：日期与 {same.relative_to(ROOT)} 重合，确认是新版本后加 --force")
            continue

        errors = [p for p in lint.lint_file(f) if p.error]
        if errors and not force:
            report["lint 未通过"].append(f"{rel}：" + "；".join(f"{p.line} 行 {p.rule}" for p in errors[:3]))
            continue
        report["新增"].append(str(shown))
        if apply:
            target.parent.mkdir(parents=True, exist_ok=True)
            f.rename(target)
            moved += 1
    return report, moved
