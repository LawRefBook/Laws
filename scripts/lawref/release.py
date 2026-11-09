"""打包数据包，发布到 release 分支，见 `laws release --help`。

release 分支上每个 channel 一个目录（alpha 在 alpha/，prod 在根目录），里面是
laws.zip（本体）、DLC/<名称>.<hash>.zip、dlc.json（DLC 列表）和 metadata/<名称>.meta。
meta 的 hash 是最后一次改动这个数据包的 commit，和线上的相同时不重新打包。
"""
import json
import math
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from lawref.db import Database
from lawref.paths import DLC_DIR, RELEASE_DIR, ROOT
from lawref.regions import REGION_CODE_MAP, dlc_name
from lawref.repo import dlc_packs

RELEASE_BRANCH = "release"
# channel → 在 release 分支上的目录
CHANNELS = {"alpha": "alpha", "prod": ""}
# channel 目录里由发布管理的文件；prod 的根目录还有 CNAME、alpha/ 等不能动
CHANNEL_PATHS = ("laws.zip", "DLC", "dlc.json", "metadata")
# 不属于数据包的文件和目录。打包时任意一层同名的都不打进去，算 hash 时排除数据包根目录下的；
# 另外以 . 开头的（.git、.release、.venv、.DS_Store …）都不算。scrape、release 是早年的目录名
EXCLUDED = ("scripts", "scrape", "release", "Makefile", "DLC", "README.md", "requirements.txt")
MAIN = "laws"


class ReleaseError(Exception):
    pass


def pathspec() -> list[str]:
    """git log、git status 里数据包的范围，在数据包根目录下使用。"""
    return [".", ":!.*", *(f":!{name}" for name in EXCLUDED)]


def git(*args: str, cwd: Path = ROOT, check: bool = True) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and result.returncode:
        raise ReleaseError(f"git {' '.join(args)} 失败：{result.stderr.strip()}")
    return result.stdout.strip()


def release_ref() -> str:
    """本地的 release 分支；还没有时用远端的。"""
    if git("rev-parse", "--verify", "--quiet", RELEASE_BRANCH, check=False):
        return RELEASE_BRANCH
    return f"origin/{RELEASE_BRANCH}"


def channel_prefix(channel: str) -> str:
    return f"{CHANNELS[channel]}/" if CHANNELS[channel] else ""


def published_meta(name: str, channel: str) -> dict | None:
    """线上的 meta，读不到时为 None。"""
    text = git("show", f"{release_ref()}:{channel_prefix(channel)}metadata/{name}.meta", check=False)
    try:
        return json.loads(text) if text else None
    except json.JSONDecodeError:
        return None


def published_hash(name: str, channel: str) -> str:
    return (published_meta(name, channel) or {}).get("hash", "")


def published_names(channel: str) -> list[str]:
    """线上有 meta 的数据包。"""
    listed = git("ls-tree", "--name-only", f"{release_ref()}:{channel_prefix(channel)}metadata/", check=False)
    return [Path(n).stem for n in listed.splitlines()]


def local_hash(pack: Path) -> str:
    """最后一次改动数据包的 commit。"""
    return git("log", "-n", "1", "--format=%H", "--", *pathspec(), cwd=pack)


# ---------- 打包 ----------

@dataclass
class Meta:
    name: str
    hash: str
    update: int
    filesize: int  # KB

    def dumps(self) -> str:
        # 格式和原来的 release.sh 一样，release 分支上的 meta 不会因为换了实现而改动
        return (f'{{"name":{json.dumps(self.name, ensure_ascii=False)},"hash":"{self.hash}", '
                f'"update":{self.update}, "filesize":{self.filesize}}}\n')


def _excluded(name: str) -> bool:
    return name.startswith(".") or name in EXCLUDED


def pack_entries(pack: Path) -> Iterable[Path]:
    """数据包里的目录和文件，相对 pack，目录在其内容之前。"""
    for folder, dirnames, filenames in pack.walk():
        dirnames[:] = sorted(d for d in dirnames if not _excluded(d))
        rel = folder.relative_to(pack)
        if rel != Path("."):
            yield rel
        for f in sorted(filenames):
            if not _excluded(f):
                yield rel / f


def write_zip(pack: Path, dest: Path) -> None:
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in pack_entries(pack):
            zf.write(pack / rel, rel.as_posix())


def check_database(pack: Path) -> None:
    db_file = pack / "db.sqlite3"
    print(f"Checking {db_file.relative_to(ROOT)}")
    if not db_file.is_file():
        raise ReleaseError(f"找不到数据库 {db_file}，发布中止")
    with Database(db_file, readonly=True) as db:
        problems = db.check()
    for problem in problems:
        print(f"❌ {problem}")
    if problems:
        raise ReleaseError(f"{pack.relative_to(ROOT)} 的数据库校验失败，发布中止")


def pack(pack_dir: Path, *, channel: str, force: bool, pack_only: bool) -> Meta | None:
    """把一个数据包打成 zip、写好 meta，放进 .release。和线上的 hash 相同且没有 force 时跳过，返回 None。"""
    is_main = pack_dir == ROOT
    name = MAIN if is_main else pack_dir.name
    shown = "本体" if is_main else str(pack_dir.relative_to(ROOT))
    commit = local_hash(pack_dir)
    if not force and commit and commit == published_hash(name, channel):
        print(f"No changes detected {shown}, skipping...")
        return None
    if not is_main:
        # 打包前校验 DLC 数据库，失败时整个发布中止，不会提交和 push
        check_database(pack_dir)

    out_dir = RELEASE_DIR if is_main else RELEASE_DIR / "DLC"
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.rglob(f"{name}*"):
        if old.is_file():
            old.unlink()
    dest = out_dir / (f"{MAIN}.zip" if is_main else f"{name}.{commit}.zip")
    print(f"Packaging {shown} to {dest.relative_to(ROOT)}")
    write_zip(pack_dir, dest)

    updated = int(git("log", "-n", "1", "--format=%at", "--", *pathspec(), cwd=pack_dir) or 0)
    if pack_only and git("status", "--porcelain", "--", *pathspec(), cwd=pack_dir):
        # 包里有未提交的改动：hash 标出来，update 取当前时间，否则 App 以为没有变化，不会重新解压
        print("工作区有未提交的改动，已一起打包")
        commit, updated = f"{commit}-dirty", int(time.time())
    meta = Meta(name=name, hash=commit, update=updated, filesize=math.ceil(dest.stat().st_size / 1024))
    meta_file = RELEASE_DIR / "metadata" / f"{name}.meta"
    meta_file.parent.mkdir(parents=True, exist_ok=True)
    meta_file.write_text(meta.dumps(), encoding="utf-8")
    return meta


def _dlc_order(name: str):
    regions = [dlc_name(r) for r in REGION_CODE_MAP]
    return (regions.index(name) if name in regions else len(regions), name)


def write_dlc_list() -> None:
    """.release/DLC 里的 zip 列成 dlc.json，按地区编号排序。

    仓库里已经删掉的 DLC 不再列出，zip 和 meta 留在 release 分支上，已经下载的用户不受影响。
    """
    names = {Path(Path(z.name).stem).stem for z in (RELEASE_DIR / "DLC").glob("*.zip")}
    metas = []
    for name in sorted(names, key=_dlc_order):
        if not (DLC_DIR / name).is_dir():
            print(f"Delisting {name}: no longer in the repository", file=sys.stderr)
            continue
        metas.append(json.loads((RELEASE_DIR / "metadata" / f"{name}.meta").read_text(encoding="utf-8")))
    (RELEASE_DIR / "dlc.json").write_text(json.dumps(metas, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def pack_all(*, main: bool, dlc: bool, channel: str, force: bool, pack_only: bool) -> None:
    if main:
        pack(ROOT, channel=channel, force=force, pack_only=pack_only)
    if dlc:
        for pack_dir in dlc_packs():
            pack(pack_dir, channel=channel, force=force, pack_only=pack_only)


# ---------- 发布 ----------

def fetch_published(channel: str) -> None:
    """把 release 分支上该 channel 的现有内容取到 .release，作为打包的基础。"""
    ref, prefix = release_ref(), channel_prefix(channel)
    existing = [p for p in CHANNEL_PATHS
                if subprocess.run(["git", "cat-file", "-e", f"{ref}:{prefix}{p}"], cwd=ROOT,
                                  capture_output=True).returncode == 0]
    if not existing:
        return
    archive = subprocess.run(["git", "archive", f"{ref}:{CHANNELS[channel]}", "--", *existing],
                             cwd=ROOT, capture_output=True, check=True).stdout
    with tempfile.TemporaryFile() as f:
        f.write(archive)
        f.seek(0)
        with tarfile.open(fileobj=f) as tar:
            tar.extractall(RELEASE_DIR, filter="data")


def commit_release(channel: str, dry_run: bool) -> None:
    """在临时 worktree 里提交到 release 分支并 push，不切换当前分支，也不碰工作区里未跟踪的文件。"""
    print(f"Finalizing release ({channel})...")
    worktree = Path(tempfile.mkdtemp())
    if dry_run:
        git("worktree", "add", "-q", "--detach", str(worktree), release_ref())
    else:
        git("worktree", "add", "-q", str(worktree), RELEASE_BRANCH)
    try:
        target = worktree / CHANNELS[channel]
        target.mkdir(parents=True, exist_ok=True)
        paths = []
        for p in CHANNEL_PATHS:
            shutil.rmtree(target / p, ignore_errors=True)
            (target / p).unlink(missing_ok=True)
            paths.append(f"{channel_prefix(channel)}{p}")
        shutil.copytree(RELEASE_DIR, target, dirs_exist_ok=True)
        git("add", "-A", "--", *paths, cwd=worktree)
        if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=worktree).returncode == 0:
            print(f"Nothing changed in {channel}, nothing to release.")
            return
        if dry_run:
            print(git("diff", "--cached", "--stat", cwd=worktree))
            print("dry run：以上改动不会提交，也不会 push")
            return
        git("commit", "-q", "-m", f"release({channel}): {time.strftime('%Y-%m-%d %H:%M:%S')}", cwd=worktree)
        if subprocess.run(["git", "push"], cwd=worktree).returncode:
            raise ReleaseError(f"Push failed. The commit stays on the local {RELEASE_BRANCH} branch; push it manually.")
    finally:
        git("worktree", "remove", "--force", str(worktree))
    print("Release finalized.")


def release(*, main: bool = True, dlc: bool = True, channel: str = "alpha", force: bool = False,
            pack_only: bool = False, dry_run: bool = False) -> None:
    """pack_only 时只打包到 .release（打包的是工作区文件），不比较线上版本、不提交、不 push。"""
    if channel not in CHANNELS:
        raise ReleaseError(f"不支持的 channel：{channel}")
    shutil.rmtree(RELEASE_DIR, ignore_errors=True)
    RELEASE_DIR.mkdir(parents=True)
    if pack_only:
        pack_all(main=main, dlc=dlc, channel=channel, force=True, pack_only=True)
        print(f"已打包到 {RELEASE_DIR}，没有发布")
        return
    print(f"Channel: {channel}")
    fetch_published(channel)
    pack_all(main=main, dlc=dlc, channel=channel, force=force, pack_only=False)
    # 只发布本体时 DLC 不动，沿用线上的 dlc.json
    if dlc:
        write_dlc_list()
    commit_release(channel, dry_run)


def dirty_files() -> list[str]:
    """数据包范围内未提交的改动。"""
    return git("status", "--porcelain", "--", *pathspec()).splitlines()


def dlc_changes(channel: str) -> list[str]:
    """和线上相比有新提交的 DLC。"""
    return [pack.name for pack in dlc_packs() if local_hash(pack) != published_hash(pack.name, channel)]


def delisted(channel: str) -> list[str]:
    """线上还有、仓库里已经删掉的 DLC。"""
    local = {pack.name for pack in dlc_packs()}
    return sorted(set(published_names(channel)) - local - {MAIN})

