import sys
from pathlib import Path

import click

from lawref.db import Database, Relationship
from lawref.db import update as update_database
from lawref.paths import MAIN_DB, ROOT
from lawref.repo import dlc_packs


def all_databases() -> list[Path]:
    """本体在前：DLC 的实施关系指向本体数据库里的法规 ID。DLC 目录里还没有数据库的会新建。"""
    return [MAIN_DB, *(pack / "db.sqlite3" for pack in dlc_packs())]


def _shown(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


@click.group()
def db():
    """让 db.sqlite3 与仓库里的法规文件保持一致。"""


@db.command()
@click.argument("databases", nargs=-1, type=click.Path(dir_okay=False, path_type=Path))
def update(databases):
    """入库、同步目录、计算生效和失效日期、重建法规之间的关系。

    不传路径时先更新本体，再更新全部 DLC。每个数据库在一个事务里完成，中途出错不会留下改了一半的数据。
    """
    targets = list(databases) or all_databases()
    for path in targets:
        if len(targets) > 1:
            click.echo(f"\n=== {_shown(path)}")
        with Database(path) as database:
            count = update_database(database)
        click.echo(f"Total: {count['laws']}")
        click.echo(f"Created: {count['created']}")
        click.echo(f"Moved: {count['moved']}")
        click.echo(f"Level updated: {count['updated']}")
        click.echo(f"Versions/dates updated: {count['versions']}")
        click.echo(f"Invalidated: {count['invalidated']}")
        click.echo(f"Expiry restored: {count['restored']}")
        click.echo(f"Flags updated: {count['flags']}")
        click.echo("Relationships: " + ", ".join(f"{type} {count[type]}" for type in Relationship.TYPES))
        click.echo(f"Missing file: {count['missing']}")
        click.echo(f"File not indexed: {count['unindexed']}")


@db.command()
@click.argument("database", type=click.Path(path_type=Path))
def check(database: Path):
    """发布前校验，有问题时退出码为 1。只读打开，不改动数据库文件。"""
    if not database.is_file():
        click.echo(f"找不到数据库 {database}")
        sys.exit(1)
    with Database(database, readonly=True) as store:
        problems = store.check()
    for problem in problems:
        click.echo(f"❌ {problem}")
    if problems:
        sys.exit(1)


@db.command()
@click.argument("database", type=click.Path(dir_okay=False, path_type=Path))
def drop(database: Path):
    """清空重建。会重新生成全部 ID，App 里用户的收藏、搜索记录都会失效。"""
    click.echo("清空后所有法规会重新生成 ID，App 里用户的收藏、搜索记录都会失效。")
    for _ in range(3):
        if not click.confirm("确定清空数据库？"):
            click.echo("已取消")
            return
    with Database(database) as store:
        store.reset()
