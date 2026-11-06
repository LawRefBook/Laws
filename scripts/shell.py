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

from common import REGION_CODE_MAP, parse_regions

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
    for i, region in enumerate(REGION_CODE_MAP, 1):
        print(f"  {i:>2}. {region}")
    while True:
        spec = input("选择地区（编号，可写范围如 7-31 或 3,5,8-10；回车取消）：").strip()
        if not spec:
            return
        try:
            regions = parse_regions(spec)
            break
        except ValueError as e:
            print(e)
    print(f"共 {len(regions)} 个地区：{'、'.join(regions)}")
    limit = ask("每个地区最多下载几部，0 为不限", "0")
    run([PYTHON, "scrape.py", "download-dlc", *regions, "--limit", limit], SCRIPTS)


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


def download_wikisource_versions():
    name = ask("法规名称，与维基文库页面标题一致，如 中华人民共和国律师法")
    if name:
        run([PYTHON, "scrape.py", "download-versions", name], SCRIPTS)


def download_url():
    url = ask("页面链接，目前支持维基文库")
    if url:
        run([PYTHON, "scrape.py", "download-url", url], SCRIPTS)


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
    if run(args, ROOT) == 0:
        return
    # 有 error：先列出能自动修复的改动，确认后再写文件
    if not confirm("查看能自动修复的改动？"):
        return
    preview = [a for a in args if a != "--warnings"]
    run([*preview, "--diff"], ROOT)
    if confirm("按上面的改动修复？"):
        run([*args, "--fix"], ROOT)


def update_db():
    run(["bash", "update_all_db.sh"], SCRIPTS)


# download-list 的数据源
PROVIDERS = {"国家法律法规数据库": "flk", "维基文库（各个版本都下载）": "wikisource"}


def find_missing():
    print(f"\n$ {PYTHON} scripts/find_missing_laws.py .\n")
    out = subprocess.run([PYTHON, "scripts/find_missing_laws.py", "."], cwd=ROOT, env=ENV, capture_output=True, text=True)
    names = sorted(line.strip() for line in out.stdout.splitlines() if line.strip())
    print("\n".join(names))
    print(f"\n共 {len(names)} 个")
    if not names:
        return
    print("从哪里下载？只下载标题完全一致、尚未收录的")
    provider = choose("来源", list(PROVIDERS))
    if not provider:
        print("已取消")
        return
    names_file = SCRIPTS / "__cache__" / "missing_laws.txt"
    names_file.parent.mkdir(parents=True, exist_ok=True)
    names_file.write_text("\n".join(names) + "\n", encoding="utf-8")
    run([PYTHON, "scrape.py", "download-list", str(names_file), "--provider", PROVIDERS[provider]], SCRIPTS)


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


# channel 在 release 分支上的目录，prod 是根目录
CHANNEL_DIRS = {"alpha": "alpha/", "prod": ""}


def published_hash(name: str, channel: str = "alpha") -> str:
    try:
        return json.loads(git("show", f"release:{CHANNEL_DIRS[channel]}metadata/{name}.meta"))["hash"]
    except (json.JSONDecodeError, KeyError):
        return ""


def confirm_release(flag: str, channel: str = "alpha"):
    dirty = git("status", "--porcelain")
    if dirty:
        print(f"\n注意：工作区有 {len(dirty.splitlines())} 处未提交的改动。release.sh 按最后一次提交判断是否有变化，"
              "但打包的是工作区文件：要打包时，这些未提交的改动也会进入数据包。建议先提交。")
    print(f"\nrelease.sh 会提交到 release 分支的 {channel} channel 并 push，发布后该 channel 的用户就会收到。")
    if input(f"确认发布到 {channel} 请输入 release：").strip() == "release":
        run(["bash", "release.sh", flag, "--channel", channel], SCRIPTS)
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
    print("发布到哪个 channel？")
    channel = choose("channel", list(CHANNEL_DIRS))
    if not channel:
        print("已取消")
        return
    changed = []
    for folder in sorted(p for p in (ROOT / "DLC").iterdir() if p.is_dir()):
        head = git("log", "-n", "1", "--format=%H", "--", str(folder.relative_to(ROOT)), *RELEASE_PATHSPEC[:-2])
        if head != published_hash(folder.name, channel):
            changed.append(folder.name)
    local = {p.name for p in (ROOT / "DLC").iterdir() if p.is_dir()}
    listed = git("ls-tree", "--name-only", f"release:{CHANNEL_DIRS[channel]}metadata/").splitlines()
    removed = sorted({Path(n).stem for n in listed} - local - {"laws"})
    print(f"\n{channel} 上有变化的 DLC：{'、'.join(changed) if changed else '没有'}")
    if removed:
        print(f"仓库里已删除、发布时会从 dlc.json 移除的 DLC（zip 保留）：{'、'.join(removed)}")
    elif not changed:
        print("发布会全部跳过。")
    print("本体保持线上版本不动。")
    confirm_release("--dlc", channel)


MENU: List[Tuple[str, List[Tuple[str, Callable[[], None]]]]] = [
    ("抓取", [
        ("下载尚未收录的法律、行政法规和司法解释", download_all),
        ("按名称下载", download_one),
        ("下载地方性法规", download_dlc),
        ("从国家规章库下载部门规章", download_gz),
        ("从维基文库下载国务院修改和废止行政法规的决定", download_state_council_decisions),
        ("从维基文库下载一部法规的全部版本", download_wikisource_versions),
        ("按链接下载", download_url),
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
