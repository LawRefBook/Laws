"""抓取命令：下载结果写到 __cache__/out/，`laws organize` 再把它们移进仓库。"""
import asyncio
import functools
import itertools
import sys
from pathlib import Path

import click
import tqdm

from lawref.dates import DATE, iso_of
from lawref.document import INFO_END
from lawref.fetch import net
from lawref.fetch.models import LawItem, Page
from lawref.fetch.pipeline import (
    JOBS,
    Result,
    default_place,
    is_known,
    item_filename,
    known_laws,
    run,
    run_pages,
    should_ignore,
    write_output,
)
from lawref.fetch.sources import (
    FlkQuery,
    GovRegulationDatabaseProvider,
    NationalLawDatabaseProvider,
    WikisourceProvider,
    flk,
)
from lawref.parse import ParseError, parse_file
from lawref.parse.content import build
from lawref.paths import CACHE_DIR, OUT_DIR
from lawref.regions import REGION_CODE_MAP, dlc_name, parse_regions
from lawref.repo import is_manual_law, law_files
from lawref.text import title_key

limit_option = click.option("--limit", type=int, default=0, help="最多下载几部，0 为不限")


def async_command(f):
    """click 命令写成 async 函数，加上 --jobs，在事件循环里运行并打开共用的 HTTP 连接。"""
    @click.option("--jobs", "-j", type=click.IntRange(1, 16), default=JOBS, show_default=True,
                  help="同时下载几部，也是同时打开的连接数上限；被限流时调小")
    @functools.wraps(f)
    def wrapper(*args, jobs: int, **kwargs):
        async def main():
            async with net.client(limit=jobs):
                return await f(*args, jobs=jobs, **kwargs)
        return asyncio.run(main())
    return wrapper


def report(result: Result) -> None:
    click.echo(f"写入 {len(result.written)} 部，失败 {len(result.failures)} 部")
    for title, reason in result.failures:
        click.echo(f"  {title}：{reason}", err=True)
    if result.written:
        click.echo("运行 `laws organize` 查看并移入仓库")


def finish(result: Result) -> None:
    report(result)
    if result.failures:
        sys.exit(1)


@click.command()
@click.argument("law_name")
@async_command
async def download(law_name: str, jobs: int):
    """按名称搜索国家法律法规数据库并下载。"""
    click.echo(f"Searching {law_name}", err=True)
    p = NationalLawDatabaseProvider()
    items = []
    for item in (await p.search_title(law_name)).items:
        if is_manual_law(item.title):
            click.echo(f"跳过 {item.title}：刑法、民法典在仓库里手动维护", err=True)
        else:
            items.append(item)
    finish(await run(p, items, jobs=jobs))


@click.command()
@limit_option
@async_command
async def download_all(limit: int, jobs: int):
    """下载全部尚未收录的法律、行政法规和司法解释。"""
    query = FlkQuery(categories=(*flk.LAWS, *flk.ADMINISTRATIVE_REGULATIONS, *flk.JUDICIAL_INTERPRETATIONS))
    click.echo(f"Downloading {limit if limit > 0 else 'all'}: {query}")
    p = NationalLawDatabaseProvider()
    finish(await run_pages(p, lambda n: p.search(query, n), limit, jobs=jobs))


@click.command()
@click.argument("regions", nargs=-1, required=True)
@limit_option
@async_command
async def download_dlc(regions: tuple[str, ...], limit: int, jobs: int):
    """下载地方性法规。地区可以写名称、编号或编号范围，如「北京」「7-31」「3,5,8-10」，
    编号从 1（北京）到 31（新疆）。多个地区逐个下载，--limit 是每个地区的上限。"""
    try:
        names = parse_regions(" ".join(regions))
    except ValueError as e:
        raise click.BadParameter(str(e), param_hint="regions") from e
    p = NationalLawDatabaseProvider()
    summary = []
    for i, region in enumerate(names, 1):
        if len(names) > 1:
            click.echo(f"\n== [{i}/{len(names)}] {region}")
        query = FlkQuery(categories=flk.LOCAL_REGULATIONS, lawmakers=(REGION_CODE_MAP[region],))
        click.echo(f"Downloading {limit if limit > 0 else 'all'}: {query}")
        result = await run_pages(
            p, lambda n, query=query: p.search(query, n), limit, jobs=jobs,
            place=lambda item, region=region: Path(dlc_name(region)) / "地方性法规" / region / item_filename(item))
        report(result)
        summary.append((region, len(result.written), len(result.failures)))
    if len(names) > 1:
        click.echo("\n汇总：" + "，".join(f"{r} 写入 {w}" + (f" 失败 {f}" if f else "") for r, w, f in summary))
    if any(f for _, _, f in summary):
        sys.exit(1)


@click.command()
@click.argument("department", required=False, default="")
@limit_option
@async_command
async def download_gz(department: str, limit: int, jobs: int):
    """从国家规章库下载部门规章，如「教育部」；不传部门时下载全部部门。"""
    click.echo(f"Downloading {limit if limit > 0 else 'all'}: {department or '全部部门'}")
    p = GovRegulationDatabaseProvider()
    finish(await run_pages(p, lambda n: p.search(n, department=department or None), limit, jobs=jobs))


@click.command()
@click.argument("names_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--provider", type=click.Choice(["flk", "wikisource"]), default="flk", show_default=True,
              help="flk：国家法律法规数据库；wikisource：维基文库，同名的各个版本都下载")
@click.option("--delay", type=float, default=1.0, show_default=True, help="每次搜索之间等几秒，避免被限流")
@async_command
async def download_list(names_file: Path, provider: str, delay: float, jobs: int):
    """按名单逐个搜索下载，每行一个名称。只下载标题完全一致、尚未收录的。"""
    names = [line.strip() for line in names_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    if provider == "flk":
        p = NationalLawDatabaseProvider()
        search = functools.partial(_search_flk, p, delay=delay)
    else:
        p = WikisourceProvider()
        search = p.versions
    known = known_laws()
    items: list[LawItem] = []
    not_found: list[str] = []
    for name in tqdm.tqdm(names, unit="名称", desc="搜索"):
        try:
            matched = await search(name)
        except (*net.NetworkError, ValueError, KeyError) as e:
            not_found.append(f"{name}（搜索失败：{e}）")
            continue
        finally:
            await asyncio.sleep(delay)
        if not matched:
            not_found.append(name)
        items += [i for i in matched if not should_ignore(i.title) and not is_known(i, known)]
    # 同一部法规的多个版本都下载；不同名称可能搜到同一条
    items = list({i.id: i for i in items}.values())
    click.echo(f"\n{len(names)} 个名称，找到 {len(items)} 部待下载，{len(not_found)} 个没有找到同名的")
    if not_found:
        click.echo("没有找到：" + "、".join(not_found[:30]) + (" ……" if len(not_found) > 30 else ""))
    if items:
        finish(await run(p, items, jobs=jobs))


async def _search_flk(p: NationalLawDatabaseProvider, name: str, delay: float) -> list[LawItem]:
    matched = [i for i in (await p.search_title(name)).items if title_key(i.title) == title_key(name)]
    if not matched:
        # 高级检索只有现行有效的，已废止、已修改的用标题检索再找一次
        await asyncio.sleep(delay)
        query = FlkQuery(categories=(), validity=flk.ALL_VALIDITY, keyword=name, search_type=flk.TITLE_SEARCH)
        matched = [i for i in (await p.search(query, page_size=50)).items if title_key(i.title) == title_key(name)]
    return matched


@click.command()
@click.argument("name")
@async_command
async def download_versions(name: str, jobs: int):
    """从维基文库下载一部法规的全部版本，如「中华人民共和国律师法」。

    只跳过同名同日期的文件已经存在的版本。download-all 那样按头部日期去重会把历史版本当成已收录：
    2017 年版的头部写着 2001、2007、2012 年的修正，但那几个版本并不在仓库里。
    """
    w = WikisourceProvider()
    existing = {f.name for f in itertools.chain(law_files(include_dlc=True), OUT_DIR.rglob("*.md"))}
    items = await w.versions(name)
    for item in items:
        click.echo(f"  {item.id}：{item.publication_date} → {item.folder}"
                   + ("（已有）" if item_filename(item) in existing else ""))
    items = [i for i in items if item_filename(i) not in existing]
    if not items:
        click.echo("没有要下载的版本")
        return
    finish(await run(w, items, jobs=jobs))


@click.command()
@click.argument("url")
@async_command
async def download_url(url: str, jobs: int):
    """下载一个页面，目前支持维基文库，如
    https://zh.wikisource.org/wiki/中华人民共和国企业所得税法_(2017年)。按制定机关决定写到 out/ 下哪个目录。"""
    w = WikisourceProvider()
    page = w.page_from_url(url)
    if not page:
        raise click.BadParameter("目前只支持维基文库的页面链接", param_hint="url")
    item = await w.version(page)
    if not item:
        raise click.ClickException(f"{page}：页面里没有日期或制定机关，无法确定文件名和目录")
    click.echo(f"  {page}：{item.publication_date} → {item.folder}")
    finish(await run(w, [item], jobs=jobs))


@click.command()
@click.argument("index")
@click.option("--see-also", is_flag=True, help="「另见」里的索引页也展开一层")
@click.option("--type", "folder", default="行政法规", show_default=True, help="写到 out/ 下哪个目录")
@limit_option
@async_command
async def download_wikisource(index: str, see_also: bool, folder: str, limit: int, jobs: int):
    """下载维基文库索引页（消歧义页）列出的页面，如「国务院关于修改和废止部分行政法规的决定」。"""
    click.echo(f"Downloading {limit if limit > 0 else 'all'}: {index}")
    w = WikisourceProvider()

    async def pages(page_num: int) -> Page:
        # 索引页一次列完，只有第一页
        if page_num > 1:
            return Page(total=0, items=[])
        items = await w.index_items(index, see_also, folder)
        return Page(total=len(items), items=items)

    finish(await run_pages(w, pages, limit, jobs=jobs))


@click.command("parse-file")
@click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--type", "folder", default="法律", show_default=True, help="写到 out/ 下哪个目录，organize 按它判断层级")
@click.option("--title", help="法规名称，不传时取文件里的标题")
@click.option("--date", "publish", help="发布日期 YYYY-MM-DD，不传时取头部信息里最后一个不是施行的日期")
def parse_file_command(path: Path, folder: str, title: str | None, publish: str | None):
    """解析本地的 epub、网页或 Word 文件，写到 out/。"""
    try:
        doc = parse_file(path, title)
    except ParseError as e:
        raise click.ClickException(str(e)) from e
    lines = build(doc.title, doc.note, doc.lines)
    if not lines:
        raise click.ClickException(f"没有解析出正文：{path.name}")
    if not publish:
        header = lines[1:lines.index(INFO_END)]
        # 「1980年1月1日 施行」不是发布日期
        dates = [iso_of(m) for line in header if (m := DATE.match(line)) and not line.endswith("施行")]
        publish = dates[-1] if dates else None
    item = LawItem(id="", title=doc.title, released_by="", folder=folder, publication_date=publish)
    out = write_output(default_place(item), lines)
    click.echo(f"写入 {out.relative_to(CACHE_DIR.parent)}")
    click.echo("运行 `laws organize` 查看并移入仓库；刑法、民法典需要手动移入")


COMMANDS = [download, download_all, download_dlc, download_gz, download_list, download_versions, download_url,
            download_wikisource, parse_file_command]
