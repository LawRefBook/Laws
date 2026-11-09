from pathlib import Path

import click

from lawref.paths import MAIN_DB, ROOT
from lawref.reports import duplicates, expired
from lawref.reports import missing as finder


@click.group()
def report():
    """列出数据里需要人工处理的问题，只读。"""


@report.command()
def missing():
    """正文以「中华人民共和国」引用、但仓库里没有收录的法律。"""
    for name in finder.find_missing(ROOT):
        click.echo(name)


@report.command("expired")
@click.argument("database", required=False, default=MAIN_DB, type=click.Path(exists=True, dir_okay=False, path_type=Path))
def expired_command(database: Path):
    """已失效、但不知道被谁废止的法规。"""
    expired.run(database)


@report.command("duplicates")
@click.option("--all", "show_all", is_flag=True, help="连同一目录下正常的多个版本也列出")
def duplicates_command(show_all: bool):
    """部门规章下的同名规章：分在不同目录、或者疑似同一版本的。"""
    groups = duplicates.find_duplicates(show_all)
    for group in groups:
        click.echo(f"\n{group.name}（{len(group.files)} 份，{len(group.folders)} 个目录）")
        for f in group.files:
            header = " / ".join(duplicates.header(f)) or "（没有头部信息）"
            click.echo(f"  {duplicates.version_date(f)}  {f.parent.name:<14}  {header}")
        for a, b in group.same:
            click.echo(f"  ⚠️ 疑似同一版本：{a.parent.name}/{duplicates.version_date(a)} ≈ "
                       f"{b.parent.name}/{duplicates.version_date(b)}")
    click.echo(f"\n共 {len(groups)} 组")


@click.command("merge-duplicates")
@click.option("--apply", "apply_", is_flag=True, help="实际合并；不加只列出计划")
def merge_duplicates(apply_: bool):
    """合并部门规章下的同名规章：同一版本只留一份，各个版本放进牵头部门的目录。

    删掉的文件、改了文件名的文件，数据库里的记录会删掉；之后运行 `laws db update` 重新入库。
    """
    plans = duplicates.merge_plans()

    def rel(path: Path) -> str:
        return str(path.relative_to(duplicates.RULES))

    for plan in plans:
        click.echo(f"\n{plan.name} → {plan.target_dir.name}/")
        for step in plan.steps:
            click.echo(f"  保留 {rel(step.keep)}" + (f" → {rel(step.dest)}" if step.keep != step.dest else ""))
            for f in step.drop:
                click.echo(f"  删除 {rel(f)}")
    if apply_:
        removed = duplicates.apply_merge(plans)
        click.echo(f"\n删除了 {removed} 条数据库记录，运行 `laws db update` 重新入库")
    else:
        click.echo("\n以上为计划，加 --apply 执行")


@click.command()
@click.argument("out", type=click.Path(file_okay=False, path_type=Path))
@click.option("--only", type=click.Choice(["lint", "reports", "parse", "db"]), multiple=True,
              help="只存这几项，可以写多次；不传时全部")
def snapshot(out: Path, only):
    """把 lint、各报告、重新解析缓存原文、数据库更新的结果存到 OUT，用来比较改代码前后的行为。

    改代码前后各运行一次，再 `diff -r` 两个目录。只读，数据库更新在临时副本上做。
    """
    from lawref.snapshot import STEPS
    from lawref.snapshot import snapshot as take

    if out.exists() and any(out.iterdir()):
        raise click.UsageError(f"{out} 不是空目录")
    take(out, only or tuple(STEPS))
