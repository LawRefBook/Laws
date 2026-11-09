"""交互菜单，`make` 或 `laws shell` 打开。

↑↓ 选择，回车确认，Esc 返回上一级；提问时按 Esc 或 Ctrl-C 取消这一项。
每一项都对应一条 `laws` 命令，选中时显示在下方，运行时也会打印出来，不用菜单时可以照着运行。
"""
import importlib.util
import json
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import click
import questionary
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings

from lawref import release as releaser
from lawref.dates import parse_iso
from lawref.paths import CACHE_DIR, DLC_DIR, MIGRATIONS_DIR, RELEASE_DIR, ROOT, SCRIPTS_DIR
from lawref.regions import REGION_CODE_MAP, dlc_name
from lawref.reports.missing import find_missing

MIGRATION = MIGRATIONS_DIR / "2026-11-law-cleanup"
# Laws 仓库放在 App 仓库里时（LawRefBook/Laws），App 内置的本体包在上一层
APP_ROOT = ROOT.parent


# ---------- 提问 ----------

class Cancelled(Exception):
    """提问时按了 Esc 或 Ctrl-C。"""


@dataclass
class Option:
    title: str
    value: Any = None
    # 选中时显示在下方
    description: str = ""
    checked: bool = False


_BACK = object()
_ESCAPE = KeyBindings()


@_ESCAPE.add("escape", eager=True)
def _(event):
    event.app.exit(result=_BACK)


SELECT_HINT = "（↑↓ 选择，回车确认，Esc 返回）"
CHECKBOX_HINT = "（↑↓ 移动，空格选中，a 全选，i 反选，回车确认）"


class Prompter:
    """所有提问都经过这里，测试时换成预先写好答案的。app_kwargs 传给 prompt_toolkit，测试时指定输入输出。"""

    def __init__(self, **app_kwargs) -> None:
        self.app_kwargs = app_kwargs

    def _ask(self, question: questionary.Question) -> Any:
        question.application.key_bindings = merge_key_bindings([question.application.key_bindings, _ESCAPE])
        answer = question.ask(kbi_msg="")
        if answer is None or answer is _BACK:
            raise Cancelled
        return answer

    @staticmethod
    def _choices(options: Sequence[Option]) -> list[questionary.Choice]:
        return [questionary.Choice(o.title, value=o.value if o.value is not None else o.title,
                                   description=o.description or None, checked=o.checked) for o in options]

    def select(self, message: str, options: Sequence[Option]) -> Any:
        return self._ask(questionary.select(message, self._choices(options), instruction=SELECT_HINT,
                                            **self.app_kwargs))

    def checkbox(self, message: str, options: Sequence[Option], required: bool = False) -> list:
        validate = (lambda picked: bool(picked) or "至少选一项") if required else (lambda _: True)
        return self._ask(questionary.checkbox(message, self._choices(options), instruction=CHECKBOX_HINT,
                                              validate=validate, **self.app_kwargs))

    def text(self, message: str, default: str = "", validate: Callable[[str], bool | str] = lambda _: True) -> str:
        return self._ask(questionary.text(message, default=default, validate=validate, **self.app_kwargs)).strip()

    def path(self, message: str, validate: Callable[[str], bool | str] = lambda _: True) -> str:
        return self._ask(questionary.path(message, validate=validate, **self.app_kwargs)).strip()

    def confirm(self, message: str, default: bool = False) -> bool:
        return self._ask(questionary.confirm(message, default=default, **self.app_kwargs))


prompt = Prompter()


def _required(value: str) -> bool | str:
    return bool(value.strip()) or "不能为空"


def _count(value: str) -> bool | str:
    return value.strip().isdigit() or "请输入数字，0 为不限"


def _existing_file(value: str) -> bool | str:
    return Path(value.strip()).expanduser().is_file() or "找不到这个文件"


def ask_limit(message: str = "最多下载几部，0 为不限") -> str:
    return prompt.text(message, default="0", validate=_count)


# ---------- 运行命令 ----------

def _finish(code: int) -> int:
    print(f"\n{'完成' if code == 0 else f'失败，退出码 {code}'}")
    return code


def laws(*args: str) -> int:
    """在当前进程里运行 `laws <args>`，返回退出码。"""
    from lawref.cli import cli

    print(f"\n$ laws {shlex.join(args)}\n")
    try:
        result = cli.main(list(args), prog_name="laws", standalone_mode=False)
        code = result if isinstance(result, int) else 0
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    except click.ClickException as e:
        e.show()
        code = e.exit_code
    except (click.Abort, KeyboardInterrupt):
        print("\n已中断")
        return 130
    return _finish(code)


def run(args: list[str], cwd: Path) -> int:
    """运行不属于 `laws` 的外部命令（测试、代码风格检查、迁移脚本）。"""
    print(f"\n$ {shlex.join(args)}\n")
    try:
        code = subprocess.run(args, cwd=cwd).returncode
    except KeyboardInterrupt:
        print("\n已中断")
        return 130
    return _finish(code)


# ---------- 抓取 ----------

def download_all():
    laws("download-all", "--limit", ask_limit())


def download_by_name():
    laws("download", prompt.text("法规名称", validate=_required))


# download-list 的数据源
PROVIDERS = [
    Option("国家法律法规数据库", "flk", "只下载标题完全一致、尚未收录的"),
    Option("维基文库", "wikisource", "同名的各个版本都下载"),
]


def download_list():
    names_file = prompt.path("名单文件，每行一个名称", validate=_existing_file)
    provider = prompt.select("从哪里下载", PROVIDERS)
    laws("download-list", str(Path(names_file).expanduser()), "--provider", provider)


def download_missing():
    names = sorted(find_missing(ROOT))
    print("\n".join(names))
    print(f"\n共 {len(names)} 个")
    if not names:
        return
    provider = prompt.select("从哪里下载这些法律", PROVIDERS)
    names_file = CACHE_DIR / "missing_laws.txt"
    names_file.parent.mkdir(parents=True, exist_ok=True)
    names_file.write_text("\n".join(names) + "\n", encoding="utf-8")
    laws("download-list", str(names_file), "--provider", provider)


def download_dlc():
    options = [Option(f"{i:>2}. {region}" + ("（已有 DLC）" if (DLC_DIR / dlc_name(region)).is_dir() else ""), region)
               for i, region in enumerate(REGION_CODE_MAP, 1)]
    regions = prompt.checkbox("选择地区", options, required=True)
    print(f"共 {len(regions)} 个地区：{'、'.join(regions)}")
    laws("download-dlc", *regions, "--limit", ask_limit("每个地区最多下载几部，0 为不限"))


def download_rules():
    department = prompt.text("部门名称，与国家规章库一致，如 教育部、国家市场监督管理总局；留空下载全部部门")
    laws("download-gz", *([department] if department else []), "--limit", ask_limit())


def download_state_council_decisions():
    args = ["download-wikisource", "国务院关于修改和废止部分行政法规的决定"]
    if prompt.confirm("「另见」里的「废止和修改」「修改」「废止」部分行政法规的决定也一起下载？", default=True):
        args.append("--see-also")
    laws(*args)


def download_versions():
    laws("download-versions", prompt.text("法规名称，与维基文库页面标题一致，如 中华人民共和国律师法", validate=_required))


def download_url():
    url = prompt.text("页面链接，目前支持维基文库",
                      validate=lambda v: v.strip().startswith(("http://", "https://")) or "请输入以 http 开头的链接")
    laws("download-url", url)


FOLDERS = [Option(f) for f in ("法律", "行政法规", "司法解释")]


def parse_local_file():
    path = prompt.path("epub、网页或 Word 文件", validate=_existing_file)
    folder = prompt.select("写到 out/ 下哪个目录，organize 按它判断层级", [*FOLDERS, Option("其他（输入）", "")])
    if not folder:
        folder = prompt.text("目录，如 部门规章/教育部", validate=_required)
    args = ["parse-file", str(Path(path).expanduser()), "--type", folder]
    if title := prompt.text("法规名称，留空取文件里的标题"):
        args += ["--title", title]
    if date := prompt.text("发布日期 YYYY-MM-DD，留空取头部信息里的日期",
                           validate=lambda v: not v.strip() or bool(parse_iso(v.strip())) or "格式是 YYYY-MM-DD"):
        args += ["--date", date]
    laws(*args)


def organize():
    if laws("organize") != 0 or not prompt.confirm("按上面的计划移入仓库？"):
        return
    args = ["organize", "--apply"]
    if prompt.confirm("疑似已收录、lint 未通过的也移入？"):
        args.append("--force")
    if laws(*args) == 0 and prompt.confirm("接着更新数据库？", default=True):
        update_db()


# ---------- 数据 ----------

def lint():
    args = ["lint", *prompt.checkbox("检查范围", [Option("包括 DLC", "--dlc"), Option("列出 warning", "--warnings")])]
    if laws(*args) == 0:
        return
    # 有 error：先列出能自动修复的改动，确认后再写文件
    if not prompt.confirm("查看能自动修复的改动？"):
        return
    laws(*[a for a in args if a != "--warnings"], "--diff")
    if prompt.confirm("按上面的改动修复？"):
        laws(*args, "--fix")


def update_db():
    laws("db", "update")


def report_missing():
    laws("report", "missing")


def report_expired():
    laws("report", "expired")


def report_duplicates():
    show_all = prompt.confirm("同一目录下正常的多个版本也列出？")
    laws("report", "duplicates", *(["--all"] if show_all else []))


def merge_duplicates():
    if laws("merge-duplicates") != 0 or not prompt.confirm("按上面的计划合并？"):
        return
    if laws("merge-duplicates", "--apply") == 0 and prompt.confirm("接着更新数据库？", default=True):
        update_db()


# ---------- 发布 ----------

CHANNELS = [Option("alpha", "alpha", "release 分支的 alpha/，测试用户"), Option("prod", "prod", "release 分支根目录，全部用户")]


def confirm_release(args: list[str], channel: str = "alpha"):
    dirty = releaser.dirty_files()
    if dirty:
        print(f"\n注意：数据包里有 {len(dirty)} 处未提交的改动。发布按最后一次提交判断是否有变化，"
              "但打包的是工作区文件：要打包时，这些未提交的改动也会进入数据包。建议先提交。")
    print(f"\n会提交到 release 分支的 {channel} channel 并 push，发布后该 channel 的用户就会收到。")
    if prompt.text(f"确认发布到 {channel} 请输入 release") == "release":
        laws("release", *args, "--channel", channel)
    else:
        print("已取消")


def release_main():
    head = releaser.local_hash(ROOT)
    published = releaser.published_hash(releaser.MAIN, "alpha")
    print(f"\n线上本体：{published[:7] or '（读取失败）'}\n本地数据：{head[:7]}")
    if head == published:
        print("本体没有新提交，发布会跳过。")
    print("DLC 保持线上版本不动。")
    confirm_release(["--main"])


def release_dlc():
    channel = prompt.select("发布到哪个 channel", CHANNELS)
    changed, removed = releaser.dlc_changes(channel), releaser.delisted(channel)
    print(f"\n{channel} 上有变化的 DLC：{'、'.join(changed) if changed else '没有'}")
    if removed:
        print(f"仓库里已删除、发布时会从 dlc.json 移除的 DLC（zip 保留）：{'、'.join(removed)}")
    elif not changed:
        print("发布会全部跳过。")
    print("本体保持线上版本不动。")
    confirm_release(["--dlc"], channel)


def pack_main():
    """只打包本体到 .release，不发布。可以再复制到 App 仓库，替换 App 内置的本体包。"""
    if laws("release", "--main", "--pack-only") != 0:
        return
    zip_file, meta_file = RELEASE_DIR / "laws.zip", RELEASE_DIR / "metadata" / "laws.meta"
    meta = json.loads(meta_file.read_text())
    print(f"\n{zip_file}（{meta['filesize'] / 1024:.1f} MB）\n{meta_file}：hash {meta['hash'][:7]}"
          f"{'-dirty' if meta['hash'].endswith('-dirty') else ''}")
    app_zip, app_meta = APP_ROOT / "laws.zip", APP_ROOT / "laws.meta"
    if app_zip.exists() and prompt.confirm(f"复制到 App 仓库，替换 {app_zip} 和 {app_meta}？"):
        shutil.copyfile(zip_file, app_zip)
        shutil.copyfile(meta_file, app_meta)
        print("已复制。重新编译运行 App 后会解压新的本体包")


def generate_migration():
    current = json.loads((MIGRATION / "line_map.json").read_text())["baseline"]
    print("基线是用户设备上的数据包版本。新数据包发布后，这份映射仍以发布前的版本为基线。")
    run([sys.executable, "generate.py", prompt.text("基线 commit", default=current, validate=_required)], MIGRATION)


# ---------- 开发 ----------

def run_tests():
    runner = ["pytest"] if importlib.util.find_spec("pytest") else ["unittest", "discover"]
    run([sys.executable, "-m", *runner, "tests"], SCRIPTS_DIR)


def check_code():
    if not importlib.util.find_spec("ruff"):
        print("没有安装 ruff，先运行 make setup")
        return
    run([sys.executable, "-m", "ruff", "check", "."], SCRIPTS_DIR)


def take_snapshot():
    out = prompt.path("存到哪个目录（要是空目录或者不存在）", validate=_required)
    laws("snapshot", str(Path(out).expanduser()))


# ---------- 菜单 ----------

@dataclass
class Action:
    title: str
    run: Callable[[], object]
    # 对应的命令，选中时显示在下方
    command: str = ""


@dataclass
class Menu:
    title: str
    items: list["Action | Menu"] = field(default_factory=list)
    description: str = ""


MENU = Menu("LawRefBook 数据工具", [
    Menu("抓取", description="下载到 __cache__/out/，再整理进仓库", items=[
        Menu("法律、行政法规、司法解释", description="国家法律法规数据库 flk.npc.gov.cn", items=[
            Action("下载尚未收录的", download_all, "laws download-all --limit N"),
            Action("按名称下载", download_by_name, "laws download <名称>"),
            Action("按名单下载", download_list, "laws download-list <名单文件> --provider flk|wikisource"),
            Action("下载正文提到但没有收录的", download_missing, "laws report missing，再 laws download-list"),
        ]),
        Menu("地方性法规", description="国家法律法规数据库，按地区写进 DLC", items=[
            Action("按地区下载", download_dlc, "laws download-dlc <地区…> --limit N"),
        ]),
        Menu("部门规章", description="国家规章库 www.gov.cn", items=[
            Action("按部门下载", download_rules, "laws download-gz [部门] --limit N"),
        ]),
        Menu("维基文库", description="zh.wikisource.org，历史版本、国务院的决定", items=[
            Action("国务院修改和废止行政法规的决定", download_state_council_decisions,
                   "laws download-wikisource 国务院关于修改和废止部分行政法规的决定 [--see-also]"),
            Action("一部法规的全部版本", download_versions, "laws download-versions <名称>"),
            Action("按链接下载", download_url, "laws download-url <链接>"),
        ]),
        Action("解析本地文件", parse_local_file, "laws parse-file <文件> --type <目录>"),
        Action("把抓取结果整理进仓库", organize, "laws organize [--apply] [--force]"),
    ]),
    Menu("数据", description="检查格式、更新数据库、需要人工处理的问题", items=[
        Action("检查格式（lint）", lint, "laws lint [--dlc] [--warnings] [--diff|--fix]"),
        Action("更新数据库", update_db, "laws db update"),
        Menu("报告", description="只读", items=[
            Action("正文提到但没有收录的法律", report_missing, "laws report missing"),
            Action("已失效但不知道被谁废止的法规", report_expired, "laws report expired"),
            Action("部门规章下的同名规章", report_duplicates, "laws report duplicates [--all]"),
        ]),
        Action("合并部门规章下的同名规章", merge_duplicates, "laws merge-duplicates [--apply]"),
    ]),
    Menu("发布", description="打包数据包，发布到 release 分支", items=[
        Action("打包本体（不发布）", pack_main, "laws release --main --pack-only"),
        Action("发布本体", release_main, "laws release --main --channel alpha"),
        Action("发布 DLC", release_dlc, "laws release --dlc --channel alpha|prod"),
        Action("重新生成 App 迁移映射", generate_migration, "python scripts/migrations/2026-11-law-cleanup/generate.py"),
    ]),
    Menu("开发", description="改了 scripts/ 之后", items=[
        Action("运行测试", run_tests, "make test"),
        Action("代码风格检查", check_code, "make check"),
        Action("存一份行为快照", take_snapshot, "laws snapshot <目录>"),
    ]),
])


def run_action(action: Action) -> None:
    print(f"\n== {action.title}")
    try:
        action.run()
    except Cancelled:
        print("已取消")


def browse(menu: Menu, trail: tuple[str, ...] = ()) -> None:
    """显示菜单，直到按 Esc 或选「返回」。运行完一项后回到同一个菜单。"""
    top = not trail
    trail = (*trail, menu.title)
    back = Option("退出" if top else "← 返回", _BACK)
    while True:
        options = [Option(f"{item.title} ›" if isinstance(item, Menu) else item.title, item,
                          item.description if isinstance(item, Menu) else item.command) for item in menu.items]
        try:
            item = prompt.select(" › ".join(trail), [*options, back])
        except Cancelled:
            return
        if item is _BACK:
            return
        if isinstance(item, Menu):
            browse(item, trail)
        else:
            run_action(item)
            print()


def main() -> int:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("菜单要在终端里运行。不用菜单时直接运行 `laws <命令>`，`laws --help` 列出全部命令。", file=sys.stderr)
        return 1
    browse(MENU)
    return 0
