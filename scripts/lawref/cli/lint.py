import sys
from pathlib import Path

import click

from lawref import lint as linter


@click.command()
@click.argument("paths", nargs=-1, type=click.Path(exists=True, path_type=Path))
@click.option("--dlc", is_flag=True, help="包括 DLC")
@click.option("--warnings", "show_warnings", is_flag=True, help="同时列出 warning")
@click.option("--diff", is_flag=True, help="列出能自动修复的改动，不写文件")
@click.option("--fix", is_flag=True, help="自动修复后再检查，剩下的需要手动处理")
def lint(paths, dlc: bool, show_warnings: bool, diff: bool, fix: bool):
    """检查法规 markdown 的格式，有 error 时退出码为 1。不传路径时检查本体全部文件。

    error 是会在 App 里直接显示出来的格式问题；warning 可能是原文本身如此，只报告。
    """
    if diff and fix:
        raise click.UsageError("--diff 和 --fix 不能同时使用")
    if code := linter.run(list(paths), dlc=dlc, show_warnings=show_warnings, diff=diff, fix=fix):
        sys.exit(code)
