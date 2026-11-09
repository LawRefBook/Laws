import click

from lawref.organize import organize as organize_out


@click.command()
@click.option("--apply", "apply_", is_flag=True, help="实际移动文件；不加只列出计划")
@click.option("--force", is_flag=True, help="疑似已收录、lint 有 error 的也移入")
def organize(apply_: bool, force: bool):
    """把 __cache__/out/ 里的新法规移入仓库，已有的文件不覆盖。"""
    report, moved = organize_out(apply=apply_, force=force)
    for title, items in report.items():
        if items:
            click.echo(f"\n{title}（{len(items)}）")
            for item in items:
                click.echo(f"  {item}")
    if not apply_:
        click.echo("\n以上为计划，加 --apply 执行。有变化的文件不会被覆盖，需要对照 diff 手动处理。")
    elif moved:
        click.echo(f"\n已移入 {moved} 部。接着运行 `laws db update` 更新数据库。")
