"""仓库里的固定位置，全部由这里给出。

按源码所在位置推算，所以要用可编辑方式安装（`make setup` 即 `pip install -e scripts`）。
"""
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = PACKAGE_DIR.parent
ROOT = SCRIPTS_DIR.parent

MAIN_DB = ROOT / "db.sqlite3"
DLC_DIR = ROOT / "DLC"
RELEASE_DIR = ROOT / ".release"

CACHE_DIR = SCRIPTS_DIR / "__cache__"
# 抓取结果，organize 再把它们移进仓库
OUT_DIR = CACHE_DIR / "out"
# organize 发现仓库里已有、内容不同的文件时，diff 写在这里
DIFF_DIR = CACHE_DIR / "diff"
MIGRATIONS_DIR = SCRIPTS_DIR / "migrations"
