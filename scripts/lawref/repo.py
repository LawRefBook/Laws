"""仓库里有哪些法规文件。所有遍历法规文件的地方都用这里，跳过规则只有一份。

本体和每个 DLC（DLC/<名称>/）各是一个数据包。数据包根目录下的 .lawignore 列出不属于它的路径：
以 ^ 开头的是正则，匹配路径里的任意一段；其余是顶层目录名。本体的 .lawignore 排除了 scripts 和 DLC。
"""
import re
from pathlib import Path

from lawref.paths import DLC_DIR, ROOT
from lawref.text import short_title

# 不是法规的 markdown；另外以 _ 开头的（网站用的 _index.md）也跳过
NOT_LAW_FILES = {"README.md", "法律法规模版.md"}

# 刑法、民法典在仓库里按修正案、分编拆开手动维护，不自动下载
MANUAL_LAWS = re.compile(r"^(刑法|民法典)")


def is_manual_law(title: str) -> bool:
    return bool(MANUAL_LAWS.match(short_title(title)))


def _ignore_rules(pack: Path) -> tuple[set, list[re.Pattern]]:
    names, patterns = set(), []
    ignore_file = pack / ".lawignore"
    if ignore_file.exists():
        for line in ignore_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("^"):
                patterns.append(re.compile(line))
            elif line:
                names.add(line)
    return names, patterns


def _hidden(name: str, patterns: list[re.Pattern]) -> bool:
    return name.startswith(".") or any(p.match(name) for p in patterns)


def pack_files(pack: Path) -> list[Path]:
    """一个数据包里的法规文件，按路径排序。"""
    names, patterns = _ignore_rules(pack)
    files = []
    for folder, dirnames, filenames in pack.walk():
        dirnames[:] = [d for d in dirnames
                       if not _hidden(d, patterns) and not (folder == pack and d in names)]
        files += [folder / f for f in filenames
                  if f.endswith(".md") and f not in NOT_LAW_FILES and not f.startswith("_")
                  and not _hidden(f, patterns)]
    return sorted(files)


def dlc_packs() -> list[Path]:
    return sorted(d for d in DLC_DIR.iterdir() if d.is_dir())


def law_files(root: Path = ROOT, include_dlc: bool = False) -> list[Path]:
    """本体（root 下）的法规文件，include_dlc 时加上 root/DLC 下全部 DLC 的，按路径排序。"""
    files = pack_files(root)
    if include_dlc and (root / "DLC").is_dir():
        for pack in sorted(d for d in (root / "DLC").iterdir() if d.is_dir()):
            files += pack_files(pack)
    return sorted(files)
