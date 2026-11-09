import click

from lawref import release as releaser


@click.command()
@click.option("--main", "only", flag_value="main", help="只发布本体，DLC 保持线上版本不动")
@click.option("--dlc", "only", flag_value="dlc", help="只发布 DLC，本体保持线上版本不动")
@click.option("--channel", type=click.Choice(list(releaser.CHANNELS)), default="alpha", show_default=True,
              help="alpha 在 release 分支的 alpha/ 下，prod 在根目录")
@click.option("-f", "--force", is_flag=True, help="不比较线上的 hash，全部重新打包")
@click.option("--pack-only", is_flag=True,
              help="只打包到 .release，不比较线上版本、不提交、不 push。打包的是工作区文件，"
                   "有未提交的改动时 meta 的 update 取当前时间，App 才会重新解压")
@click.option("--dry-run", is_flag=True, help="打包并列出 release 分支上会有的改动，不提交、不 push")
def release(only, channel: str, force: bool, pack_only: bool, dry_run: bool):
    """打包数据，提交到 release 分支的 channel 目录并 push，该 channel 的用户就会收到。

    和线上 hash 相同的数据包会跳过。打包前校验 DLC 数据库，有问题时整个发布中止。
    """
    try:
        releaser.release(main=only != "dlc", dlc=only != "main", channel=channel, force=force,
                         pack_only=pack_only, dry_run=dry_run)
    except releaser.ReleaseError as e:
        raise click.ClickException(str(e)) from e
