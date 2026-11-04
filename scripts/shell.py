#!/usr/bin/env python3
"""数据维护的交互入口，不用记各个脚本的命令。在仓库根目录运行：

    .venv/bin/python scripts/shell.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
MIGRATION = SCRIPTS / "migrations" / "2026-11-law-cleanup"
PYTHON = sys.executable

from common import REGION_CODE_MAP

# update_all_db.sh 里直接调用 python，让它用到同一个虚拟环境
ENV = {**os.environ, "PATH": f"{Path(PYTHON).parent}{os.pathsep}{os.environ.get('PATH', '')}"}


def run(args: List[str], cwd: Path) -> int:
    print(f"\n$ {' '.join(args)}\n")
    try:
        code = subprocess.run(args, cwd=cwd, env=ENV).returncode
    except KeyboardInterrupt:
        print("\n已中断")
        return 130
    print(f"\n{'完成' if code == 0 else f'失败，退出码 {code}'}")
    return code


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def ask(prompt: str, default: str = "") -> str:
    suffix = f"（默认 {default}）" if default else ""
    value = input(f"{prompt}{suffix}：").strip()
    return value or default


def confirm(prompt: str, default: bool = False) -> bool:
    value = input(f"{prompt} [{'Y/n' if default else 'y/N'}]：").strip().lower()
    return default if not value else value in ("y", "yes")


def choose(prompt: str, options: List[str]) -> Optional[str]:
    for i, option in enumerate(options, 1):
        print(f"  {i:>2}. {option}")
    value = input(f"{prompt}（编号，回车取消）：").strip()
    if value.isdigit() and 1 <= int(value) <= len(options):
        return options[int(value) - 1]
    return None


# ---------- 抓取 ----------

def download_all():
    limit = ask("最多下载几部，0 为不限", "0")
    run([PYTHON, "scrape.py", "download-all", "--limit", limit], SCRIPTS)


def download_one():
    name = ask("法规名称")
    if name:
        run([PYTHON, "scrape.py", "download", name], SCRIPTS)


def download_dlc():
    region = choose("选择地区", [*REGION_CODE_MAP, "文化与旅游部"])
    if region:
        limit = ask("最多下载几部，0 为不限", "0")
        run([PYTHON, "scrape.py", "download-dlc", region, "--limit", limit], SCRIPTS)


def download_gz():
    department = ask("部门名称，与国家规章库一致，如 教育部、国家市场监督管理总局；留空下载全部部门")
    limit = ask("最多下载几部，0 为不限", "0")
    run([PYTHON, "scrape.py", "download-gz", *([department] if department else []), "--limit", limit], SCRIPTS)


def download_state_council_decisions():
    index = "国务院关于修改和废止部分行政法规的决定"
    args = [PYTHON, "scrape.py", "download-wikisource", index]
    if confirm("「另见」里的「废止和修改」「修改」「废止」部分行政法规的决定也一起下载？", default=True):
        args.append("--see-also")
    run(args, SCRIPTS)


def organize():
    if run([PYTHON, "scrape.py", "organize"], SCRIPTS) != 0:
        return
    if not confirm("按上面的计划移入仓库？"):
        return
    args = [PYTHON, "scrape.py", "organize", "--apply"]
    if confirm("lint 未通过的也移入？"):
        args.append("--force")
    if run(args, SCRIPTS) == 0 and confirm("接着更新数据库？", default=True):
        update_db()


# ---------- 数据 ----------

def lint():
    args = [PYTHON, "scripts/lint.py"]
    if confirm("包括 DLC？"):
        args.append("--dlc")
    if confirm("列出 warning？"):
        args.append("--warnings")
    run(args, ROOT)


def update_db():
    run(["bash", "update_all_db.sh"], SCRIPTS)


def find_missing():
    print(f"\n$ {PYTHON} scripts/find_missing_laws.py .\n")
    out = subprocess.run([PYTHON, "scripts/find_missing_laws.py", "."], cwd=ROOT, env=ENV, capture_output=True, text=True)
    names = sorted(line.strip() for line in out.stdout.splitlines() if line.strip())
    print("\n".join(names))
    print(f"\n共 {len(names)} 个")
    if not names or not confirm("要尝试从国家法律法规数据库下载这些法律吗？只下载标题完全一致、尚未收录的"):
        return
    names_file = SCRIPTS / "__cache__" / "missing_laws.txt"
    names_file.parent.mkdir(parents=True, exist_ok=True)
    names_file.write_text("\n".join(names) + "\n", encoding="utf-8")
    run([PYTHON, "scrape.py", "download-list", str(names_file)], SCRIPTS)


def list_unexplained_expired():
    run([PYTHON, "scripts/list_unexplained_expired.py"], ROOT)


def test_parsers():
    run([PYTHON, "-m", "unittest", "discover", "tests"], SCRIPTS)


# ---------- 发布 ----------

def generate_migration():
    current = json.loads((MIGRATION / "line_map.json").read_text())["baseline"]
    print("基线是用户设备上的数据包版本。新数据包发布后，这份映射仍以发布前的版本为基线。")
    baseline = ask("基线 commit", current)
    run([PYTHON, "generate.py", baseline], MIGRATION)


# 与 release.sh 保持一致
RELEASE_PATHSPEC = [":!scripts", ":!scrape", ":!.*", ":!DLC", ":!Makefile"]


def published_hash(name: str) -> str:
    try:
        return json.loads(git("show", f"release:alpha/metadata/{name}.meta"))["hash"]
    except (json.JSONDecodeError, KeyError):
        return ""


def confirm_release(flag: str):
    dirty = git("status", "--porcelain")
    if dirty:
        print(f"\n注意：工作区有 {len(dirty.splitlines())} 处未提交的改动。release.sh 按最后一次提交判断是否有变化，"
              "但打包的是工作区文件：要打包时，这些未提交的改动也会进入数据包。建议先提交。")
    print("\nrelease.sh 会切到 release 分支提交并 push，发布后用户就会收到。")
    if input("确认发布请输入 release：").strip() == "release":
        run(["bash", "release.sh", flag], SCRIPTS)
    else:
        print("已取消")


def release_main():
    head = git("log", "-n", "1", "--format=%H", "--", ".", *RELEASE_PATHSPEC)
    published = published_hash("laws")
    print(f"\n线上本体：{published[:7] or '（读取失败）'}\n本地数据：{head[:7]}")
    if head == published:
        print("本体没有新提交，发布会跳过。")
    print("DLC 保持线上版本不动。")
    confirm_release("--main")


def release_dlc():
    changed = []
    for folder in sorted(p for p in (ROOT / "DLC").iterdir() if p.is_dir()):
        head = git("log", "-n", "1", "--format=%H", "--", str(folder.relative_to(ROOT)), *RELEASE_PATHSPEC[:-2])
        if head != published_hash(folder.name):
            changed.append(folder.name)
    print(f"\n有变化的 DLC：{'、'.join(changed) if changed else '没有，发布会全部跳过'}")
    print("本体保持线上版本不动。")
    confirm_release("--dlc")


MENU: List[Tuple[str, List[Tuple[str, Callable[[], None]]]]] = [
    ("抓取", [
        ("下载尚未收录的法律、行政法规和司法解释", download_all),
        ("按名称下载", download_one),
        ("下载地方性法规或文化与旅游部规章", download_dlc),
        ("从国家规章库下载部门规章", download_gz),
        ("从维基文库下载国务院修改和废止行政法规的决定", download_state_council_decisions),
        ("把抓取结果整理进仓库", organize),
    ]),
    ("数据", [
        ("检查格式（lint）", lint),
        ("更新数据库", update_db),
        ("查找正文提到但没有收录的法律", find_missing),
        ("列出已失效但不知道被谁废止的法规", list_unexplained_expired),
        ("运行解析器测试", test_parsers),
    ]),
    ("发布", [
        ("重新生成 App 迁移映射", generate_migration),
        ("发布本体", release_main),
        ("发布 DLC", release_dlc),
    ]),
]


def main():
    # 输出到管道时也按行刷新，保证和子命令的输出顺序一致
    sys.stdout.reconfigure(line_buffering=True)
    actions =[action for _, items in MENU for action in items]
    while True:
        print()
        n = 0
        for group, items in MENU:
            print(group)
            for title, _ in items:
                n += 1
                print(f"  {n:>2}. {title}")
        try:
            value = input("\n选择编号，q 退出：").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if value in ("q", "quit", "exit"):
            return
        if not value.isdigit() or not 1 <= int(value) <= len(actions):
            print("没有这个选项")
            continue
        title, action = actions[int(value) - 1]
        print(f"\n== {title}")
        try:
            action()
        except (EOFError, KeyboardInterrupt):
            print("\n已取消")


if __name__ == "__main__":
    main()
