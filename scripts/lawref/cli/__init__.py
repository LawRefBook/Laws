"""`laws` 命令：抓取、整理、检查、入库、发布法规数据。在仓库任意位置运行 `laws --help`。"""
import sys

import click

from lawref.cli import fetch
from lawref.cli.db import db
from lawref.cli.lint import lint
from lawref.cli.organize import organize
from lawref.cli.release import release
from lawref.cli.report import merge_duplicates, report, snapshot


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def cli():
    pass


@cli.command()
def shell():
    """交互菜单，方向键选择，不用记命令（`make` 默认运行它）。"""
    from lawref.shell import main as shell_main

    if code := shell_main():
        sys.exit(code)


for command in (*fetch.COMMANDS, organize, lint, db, report, merge_duplicates, release, snapshot):
    cli.add_command(command)


def main():
    cli(prog_name="laws")
