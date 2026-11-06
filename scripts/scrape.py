#!/usr/bin/env python3
"""抓取法规并整理进仓库。用仓库的虚拟环境运行：

    .venv/bin/python scripts/scrape.py download <名称>
    .venv/bin/python scripts/scrape.py download-all [--limit N]
    .venv/bin/python scripts/scrape.py download-dlc <地区> [--limit N]
    .venv/bin/python scripts/scrape.py download-list <名单> [--provider flk|wikisource]
    .venv/bin/python scripts/scrape.py organize [--apply] [--force]

下载结果写到 __cache__/out/，organize 再把它们移进仓库。默认同时下载 4 部，
用 `scrape.py --jobs N <命令>` 调整，被限流时调小。
"""
import asyncio
import difflib
import functools
import itertools
import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import AsyncIterable, Callable, Dict, Iterable, List, Optional, Set, Tuple, Union

import click
import tqdm
import lint
from common import CACHE_DIR, REGION_CODE_MAP, ROOT, is_manual_law, parse_regions, short_title
from docx import Document
from model.law import LawListItem
from parsers.content import ContentParser
from parsers.epub import EpubParser
from parsers.html import HtmlParser
from parsers.word import WordParser
from providers import net
from providers import (GovRegulationDatabaseProvider, NationalLawDatabaseProvider, Provider,
                       WikisourceProvider)
from providers.cache_provider import CacheManager


LAW_FILE = re.compile(r"^(.+?)(?:\((\d{4}-\d{2}-\d{2})\))?\.md$")
REPO_SKIP = {"scripts", ".venv", ".release", ".git", ".github"}

PathModifier = Callable[[Path], Path]

# 同时下载几部，也是同时打开的连接数上限。时间几乎都花在等网络上，解析一部只要几十毫秒
JOBS = 4
# 解析在线程里跑，LibreOffice 同一时间只能跑一个转换
_SOFFICE = threading.Lock()


class ProcessError(Exception):
    pass


def should_ignore(name) -> bool:
    return is_manual_law(name) or bool(re.search(r"的(决定|复函|批复|答复)$", short_title(name)))


def canonical_filename(filename: str) -> str:
    """按仓库的命名规则规范文件名，日期保持不变。"""
    m = LAW_FILE.match(filename)
    if not m:
        return filename
    name = short_title(m.group(1))
    return f"{name}({m.group(2)}).md" if m.group(2) else f"{name}.md"


def law_filename(item: LawListItem) -> str:
    # 「核苷酸和/或氨基酸…」里的斜杠会被当成目录
    name = short_title(item.title).replace("/", "／")
    if item.publication_date:
        name += f"({item.publication_date})"
    return f"{name}.md"


def with_effective_date(lines: List[str], in_effect: Optional[str], published: Optional[str]) -> List[str]:
    """法规库给出的施行日期晚于发布日期、头部又没写时，补一行「X年X月X日 施行」。

    修正版的施行日期往往不在正文里，database.py 从这一行读取生效日期。
    """
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", in_effect or "")
    if not m or not published or in_effect <= published or "<!-- INFO END -->" not in lines:
        return lines
    end = lines.index("<!-- INFO END -->")
    if any(re.match(r"^\d{4}年\d{1,2}月\d{1,2}日\s*施行$", line) for line in lines[1:end]):
        return lines
    line = f"{int(m.group(1))}年{int(m.group(2))}月{int(m.group(3))}日 施行"
    return lines[:end] + [line] + lines[end:]


def repo_files(include_dlc: bool) -> Iterable[Path]:
    skip = REPO_SKIP | (set() if include_dlc else {"DLC"})
    for f in ROOT.rglob("*.md"):
        if not any(p in skip for p in f.relative_to(ROOT).parts[:-1]):
            yield f


HEADER_DATE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")


def law_dates(path: Path) -> Set[str]:
    """文件名里的日期和头部信息里出现的日期（通过、公布、施行等），格式 YYYY-MM-DD。

    同一部法规，仓库文件名有时用通过日，法规库给的是公布日，只比文件名会重复收录。
    """
    dates = set()
    if (m := LAW_FILE.match(path.name)) and m.group(2):
        dates.add(m.group(2))
    head = path.read_text(encoding="utf-8").partition("<!-- INFO END -->")[0]
    for d in HEADER_DATE.finditer(head):
        dates.add(f"{int(d.group(1)):04d}-{int(d.group(2)):02d}-{int(d.group(3)):02d}")
    return dates


def known_laws(out_path: Path) -> Dict[str, Set[str]]:
    """仓库（含 DLC）和 out/ 里已有的法规：{名称: {文件名和头部信息里的日期，没有日期为空串}}。"""
    known: Dict[str, Set[str]] = {}
    for f in itertools.chain(repo_files(include_dlc=True), out_path.rglob("*.md")):
        if m := LAW_FILE.match(f.name):
            dates = known.setdefault(short_title(m.group(1)), set())
            dates.add(m.group(2) or "")
            dates |= law_dates(f)
    return known


def is_known(item: LawListItem, known: Dict[str, Set[str]]) -> bool:
    dates = known.get(short_title(item.title), set())
    if not item.publication_date:
        return "" in dates
    return item.publication_date in dates or (item.in_effect_date or "") in dates


def convert_to_docx(p: Path) -> Path:
    docx = p.with_suffix(".docx")
    if docx.exists():
        return docx
    try:
        with _SOFFICE:
            subprocess.run(
                ["soffice", "--headless", "--convert-to", "docx", "--outdir", str(p.parent), str(p)],
                check=True, capture_output=True,
            )
    except (OSError, subprocess.CalledProcessError) as e:
        raise ProcessError(f"无法把 .doc 转成 .docx：{e}") from e
    if not docx.exists():
        raise ProcessError(f"无法把 .doc 转成 .docx：{p}")
    return docx


def parse_file_content(path: Path, title: Optional[str]) -> Tuple[str, str, List[str]]:
    """按文件类型选 parser，返回 (title, desc, content)。"""
    if path.suffix == ".epub":
        return EpubParser().parse_document(path, title)
    if path.suffix in (".htm", ".html", ".shtml"):
        return HtmlParser().parse_document(path, title)
    if path.suffix == ".doc":
        path = convert_to_docx(path)
    try:
        document = Document(str(path))
    except Exception as e:
        raise ProcessError(f"无法解析 Word 文件 {path.name}：{e}") from e
    title = title or path.stem
    _, desc, content = WordParser().parse_document(document, title)
    return title, desc, content


async def process_item(provider: Provider, item: LawListItem, path_modifier: PathModifier) -> Path:
    """下载并解析一部法规，写到 out/。失败时抛 ProcessError。"""
    try:
        path = (await provider.fetch_document(item)).path_to_file
    except Exception as e:
        # 超时之类的异常 str() 是空的
        raise ProcessError(f"下载失败：{str(e) or repr(e)}") from e
    title = provider.heading(item)
    # 解析 Word 和转换 .doc 会占住事件循环，放到线程里
    _, desc, content = await asyncio.to_thread(parse_file_content, path, title)
    filedata = ContentParser().parse(title, await provider.header_note(item, desc), content)
    if not filedata:
        raise ProcessError(f"没有解析出正文：{path.name}")
    filedata = with_effective_date(filedata, item.in_effect_date, item.publication_date)
    return provider.cache_manager.write_law(path_modifier(Path(item.type) / law_filename(item)), filedata)


Items = Union[Iterable[LawListItem], AsyncIterable[LawListItem]]


async def aiter_items(items: Items):
    if hasattr(items, "__aiter__"):
        async for item in items:
            yield item
    else:
        for item in items:
            yield item


async def run(provider: Provider, items: Items, path_modifier: PathModifier,
              failures: List[Tuple[str, str]], total: Optional[int] = None, exit_on_failure: bool = True) -> int:
    """返回写入了几部。exit_on_failure 时有失败就以退出码 1 结束；连续下载多批时传 False，最后再判断。"""
    written = []
    bar = tqdm.tqdm(total=total, unit="laws")
    slots = asyncio.Semaphore(JOBS)

    async def one(item: LawListItem):
        try:
            written.append(await process_item(provider, item, path_modifier))
        except ProcessError as e:
            failures.append((item.title, str(e)))
        except Exception as e:
            # 一部出错不影响其余的，记下来最后一起列出
            failures.append((item.title, f"{type(e).__name__}：{e}"))
        finally:
            slots.release()
            bar.set_description(f"Processing: {item.short_title[:20]}")
            bar.update()

    # items 可能是边翻页边产出的，等有空位再取下一部，不必等所有列表页取完才开始下载
    async with asyncio.TaskGroup() as group:
        async for item in aiter_items(items):
            await slots.acquire()
            group.create_task(one(item))
    bar.close()

    click.echo(f"写入 {len(written)} 部，失败 {len(failures)} 部")
    for title, reason in failures:
        click.echo(f"  {title}：{reason}", err=True)
    if written:
        click.echo("运行 `scrape.py organize` 查看并移入仓库")
    if failures and exit_on_failure:
        sys.exit(1)
    return len(written)


@click.group()
@click.option("--jobs", "-j", type=click.IntRange(1, 16), default=JOBS, show_default=True,
              help="同时下载几部；被限流时调小")
def cli(jobs: int):
    global JOBS
    JOBS = jobs


def async_command(f):
    """click 命令写成 async 函数，在事件循环里运行，并打开共用的 HTTP 连接。"""
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        async def main():
            async with net.client(limit=JOBS):
                return await f(*args, **kwargs)
        return asyncio.run(main())
    return wrapper


@cli.command()
@click.argument("law_name")
@async_command
async def download(law_name):
    """按名称搜索并下载。"""
    click.echo(f"Searching {law_name}", err=True)
    p = NationalLawDatabaseProvider()
    ret = await p.fetch(use_high_search=True, dataList=[("title", law_name)])
    items = []
    for item in ret.items:
        if is_manual_law(item.title):
            click.echo(f"跳过 {item.title}：刑法、民法典在仓库里手动维护", err=True)
        else:
            items.append(item)
    await run(p, items, lambda x: x, failures=[])


@cli.command()
@click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--type", "type_", default="法律", show_default=True, help="写到 out/ 下哪个目录，organize 按它判断层级")
@click.option("--title", help="法规名称，不传时取文件里的标题")
@click.option("--date", "publish", help="发布日期 YYYY-MM-DD，不传时取头部信息里最后一个不是施行的日期")
def parse_file(path: Path, type_: str, title: Optional[str], publish: Optional[str]):
    """解析本地的 epub、网页或 Word 文件，写到 out/。"""
    try:
        title, desc, content = parse_file_content(path, title)
    except ProcessError as e:
        raise click.ClickException(str(e)) from e
    filedata = ContentParser().parse(title, desc, content)
    if not filedata:
        raise click.ClickException(f"没有解析出正文：{path.name}")
    if not publish:
        header = filedata[1:filedata.index("<!-- INFO END -->")]
        # 「1980年1月1日 施行」不是发布日期
        dates = [m.groups() for line in header
                 if (m := re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", line)) and not line.endswith("施行")]
        publish = "-".join(f"{int(x):02d}" for x in dates[-1]) if dates else None
    item = LawListItem(id="", title=title, released_by="", type=type_, publication_date=publish)
    out = CacheManager().write_law(Path(type_) / law_filename(item), filedata)
    click.echo(f"写入 {out.relative_to(CACHE_DIR.parent)}")
    click.echo("运行 `scrape.py organize` 查看并移入仓库；刑法、民法典需要手动移入")


def _title_key(title: str) -> str:
    """比较标题用：去掉空白，〈〉换成《》，再去掉「中华人民共和国」。"""
    title = re.sub(r"\s", "", title).replace("〈", "《").replace("〉", "》")
    return short_title(title)


@cli.command()
@click.argument("names_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--provider", type=click.Choice(["flk", "wikisource"]), default="flk", show_default=True,
              help="flk：国家法律法规数据库；wikisource：维基文库，同名的各个版本都下载")
@click.option("--delay", type=float, default=1.0, show_default=True, help="每次搜索之间等几秒，避免被限流")
@async_command
async def download_list(names_file: Path, provider: str, delay: float):
    """按名单逐个搜索下载，每行一个名称。只下载标题完全一致、尚未收录的。"""
    names = [line.strip() for line in names_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    p = NationalLawDatabaseProvider() if provider == "flk" else WikisourceProvider()
    known = known_laws(p.cache_manager.out_path)
    items: List[LawListItem] = []
    not_found: List[str] = []
    for name in tqdm.tqdm(names, unit="名称", desc="搜索"):
        try:
            matched = await (_search_flk(p, name, delay) if provider == "flk" else p.versions(name))
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
        await run(p, items, lambda x: x, failures=[])


async def _search_flk(p: NationalLawDatabaseProvider, name: str, delay: float) -> List[LawListItem]:
    ret = await p.fetch(use_high_search=True, dataList=[("title", name)])
    matched = [i for i in ret.items if _title_key(i.title) == _title_key(name)]
    if not matched:
        # 高级搜索只有现行有效的，已废止、已修改的用标题检索再找一次
        await asyncio.sleep(delay)
        ret = await p.fetch(searchContent=name, searchType=1, sxx=p.ALL_VALIDITY, flfgCodeId=[], page_size=50)
        matched = [i for i in ret.items if _title_key(i.title) == _title_key(name)]
    return matched


@cli.command()
@click.argument("name")
@async_command
async def download_versions(name: str):
    """从维基文库下载一部法规的全部版本，如「中华人民共和国律师法」。

    只跳过同名同日期的文件已经存在的版本。download-all 那样按头部日期去重会把历史版本当成已收录：
    2017 年版的头部写着 2001、2007、2012 年的修正，但那几个版本并不在仓库里。
    """
    w = WikisourceProvider()
    existing = {f.name for f in itertools.chain(repo_files(include_dlc=True), w.cache_manager.out_path.rglob("*.md"))}
    items = await w.versions(name)
    for item in items:
        click.echo(f"  {item.id}：{item.publication_date} → {item.type}"
                   + ("（已有）" if law_filename(item) in existing else ""))
    items = [i for i in items if law_filename(i) not in existing]
    if not items:
        click.echo("没有要下载的版本")
        return
    await run(w, items, lambda x: x, failures=[])


@cli.command()
@click.argument("url")
@async_command
async def download_url(url: str):
    """下载一个页面，目前支持维基文库，如
    https://zh.wikisource.org/wiki/中华人民共和国企业所得税法_(2017年)。按制定机关决定写到 out/ 下哪个目录。"""
    w = WikisourceProvider()
    page = w.page_from_url(url)
    if not page:
        raise click.BadParameter("目前只支持维基文库的页面链接", param_hint="url")
    item = await w.version(page)
    if not item:
        raise click.ClickException(f"{page}：页面里没有日期或制定机关，无法确定文件名和目录")
    click.echo(f"  {page}：{item.publication_date} → {item.type}")
    await run(w, [item], lambda x: x, failures=[])


async def _download_all(p: Provider, limit: int, path_modifier: PathModifier = lambda x: x,
                        exit_on_failure: bool = True, **kwargs) -> Tuple[int, int]:
    """返回 (写入, 失败) 部数。"""
    click.echo(f"Downloading {limit if limit > 0 else 'all'} with params: {kwargs}")
    known = known_laws(p.cache_manager.out_path)
    failures: List[Tuple[str, str]] = []

    async def pending():
        count = 0
        for page in itertools.count(1):
            try:
                ret = await p.fetch(page_num=page, **kwargs)
            except net.HTTPError as e:
                if e.status != 404:
                    failures.append((f"列表第 {page} 页", str(e)))
                return
            except net.NetworkError as e:
                failures.append((f"列表第 {page} 页", str(e) or repr(e)))
                return
            if not ret.items:
                return
            for item in ret.items:
                if should_ignore(item.title):
                    continue
                if is_known(item, known):
                    continue
                yield item
                count += 1
                if count == limit:
                    return

    written = await run(p, pending(), path_modifier, failures, total=limit if limit > 0 else None,
                        exit_on_failure=exit_on_failure)
    return written, len(failures)


limit_option = click.option("--limit", type=int, default=0, help="最多下载几部，0 为不限")


@cli.command()
@limit_option
@async_command
async def download_all(limit: int):
    """下载全部尚未收录的法律、行政法规和司法解释。"""
    kwargs = {
        "flfgCodeId": [
            101, 102, 110, 120, 130, 140, 150, 155, 160, 170, 180, 190, 195, 200,  # 法律
            210,  # 行政法规
            311, 320, 330, 340, 350  # 司法解释
        ],
        "orderByParam": {"order": "gbrq", "sort": "DESC"},
    }
    await _download_all(NationalLawDatabaseProvider(), limit, **kwargs)


@cli.command()
@click.argument("regions", nargs=-1, required=True)
@limit_option
@async_command
async def download_dlc(regions: Tuple[str, ...], limit: int):
    """下载地方性法规。地区可以写名称、编号或编号范围，如「北京」「7-31」「3,5,8-10」，
    编号从 1（北京）到 31（新疆）。多个地区逐个下载，--limit 是每个地区的上限。"""
    try:
        names = parse_regions(" ".join(regions))
    except ValueError as e:
        raise click.BadParameter(str(e), param_hint="regions") from e
    summary = []
    for i, region in enumerate(names, 1):
        if len(names) > 1:
            click.echo(f"\n== [{i}/{len(names)}] {region}")
        summary.append((region, *await _download_all(
            NationalLawDatabaseProvider(), limit,
            path_modifier=lambda path, region=region: Path(f"{region}地方法规") / "地方性法规" / region / path.name,
            exit_on_failure=False,
            flfgCodeId=[230],  # 地方性法规
            zdjgCodeId=[REGION_CODE_MAP[region]],
        )))
    if len(names) > 1:
        click.echo("\n汇总：" + "，".join(f"{r} 写入 {w}" + (f" 失败 {f}" if f else "") for r, w, f in summary))
    if any(f for _, _, f in summary):
        sys.exit(1)


@cli.command()
@click.argument("index")
@click.option("--see-also", is_flag=True, help="「另见」里的索引页也展开一层")
@click.option("--type", "type_", default="行政法规", show_default=True, help="写到 out/ 下哪个目录")
@limit_option
@async_command
async def download_wikisource(index: str, see_also: bool, type_: str, limit: int):
    """下载维基文库索引页（消歧义页）列出的页面，如「国务院关于修改和废止部分行政法规的决定」。"""
    await _download_all(WikisourceProvider(), limit, index=index, see_also=see_also, type_=type_)


@cli.command()
@click.argument("department", required=False, default="")
@limit_option
@async_command
async def download_gz(department: str, limit: int):
    """从国家规章库下载部门规章，如「教育部」；不传部门时下载全部部门。"""
    await _download_all(GovRegulationDatabaseProvider(), limit, department=department or None)


def suspected_duplicate(f: Path, versions: Dict[str, List[Path]]) -> Optional[Path]:
    """同名法规已有文件，而新文件的发布日期或头部最新日期已经出现在其中，多半是同一版本。"""
    m = LAW_FILE.match(canonical_filename(f.name))
    if not m:
        return None
    new_dates = law_dates(f)
    keys = {m.group(2)} if m.group(2) else set()
    if new_dates:
        keys.add(max(new_dates))
    for existing in versions.get(m.group(1), []):
        if keys & law_dates(existing):
            return existing
    return None


def organize_target(rel: Path, folders: Dict[str, Set[Path]]) -> Tuple[Optional[Path], str]:
    """out/ 里的文件应该放到仓库哪里。返回 (目标路径, 无法确定时的原因)。"""
    top = rel.parts[0]
    name = canonical_filename(rel.name)
    if top.endswith("地方法规"):
        return ROOT / "DLC" / rel.parent / name, ""
    if top == "部门规章":
        return ROOT / rel.parent / name, ""
    m = LAW_FILE.match(name)
    candidates = folders.get(m.group(1) if m else rel.stem, set())
    if len(candidates) == 1:
        return ROOT / next(iter(candidates)) / name, ""
    if len(candidates) > 1:
        return None, "同名法规在多个目录：" + "、".join(sorted(map(str, candidates)))
    if top in ("行政法规", "司法解释"):
        return ROOT / top / name, ""
    return None, "新法规，需要手动选择目录"


@cli.command()
@click.option("--apply", "apply_", is_flag=True, help="实际移动文件；不加只列出计划")
@click.option("--force", is_flag=True, help="lint 有 error 也移入")
def organize(apply_: bool, force: bool):
    """把 __cache__/out/ 里的新法规移入仓库，已有的文件不覆盖。"""
    out = CACHE_DIR / "out"
    diff_dir = CACHE_DIR / "diff"
    folders: Dict[str, Set[Path]] = {}
    for f in repo_files(include_dlc=False):
        if m := LAW_FILE.match(f.name):
            folders.setdefault(short_title(m.group(1)), set()).add(f.parent.relative_to(ROOT))
    versions: Dict[str, List[Path]] = {}
    for f in repo_files(include_dlc=True):
        if m := LAW_FILE.match(f.name):
            versions.setdefault(short_title(m.group(1)), []).append(f)

    report: Dict[str, List[str]] = {k: [] for k in ("新增", "相同", "有变化", "疑似已收录", "lint 未通过", "无法确定目录", "跳过")}
    moved = 0
    for f in sorted(out.rglob("*.md")):
        rel = f.relative_to(out)
        if is_manual_law(LAW_FILE.match(rel.name).group(1) if LAW_FILE.match(rel.name) else rel.stem):
            report["跳过"].append(f"{rel}：刑法、民法典在仓库里手动维护")
            continue
        target, reason = organize_target(rel, folders)
        if target is None:
            report["无法确定目录"].append(f"{rel}：{reason}")
            continue
        shown = target.relative_to(ROOT)

        if target.exists():
            old, new = target.read_text(encoding="utf-8"), f.read_text(encoding="utf-8")
            if old.strip() == new.strip():
                report["相同"].append(str(shown))
                if apply_:
                    f.unlink()
                continue
            diff_file = diff_dir / rel.with_suffix(".diff")
            diff_file.parent.mkdir(parents=True, exist_ok=True)
            diff_file.write_text("".join(difflib.unified_diff(
                old.splitlines(True), new.splitlines(True), f"仓库/{shown}", f"抓取/{rel}")), encoding="utf-8")
            report["有变化"].append(f"{shown}（diff：{diff_file.relative_to(CACHE_DIR.parent)}）")
            continue

        if not force and (same := suspected_duplicate(f, versions)):
            report["疑似已收录"].append(f"{rel}：日期与 {same.relative_to(ROOT)} 重合，确认是新版本后加 --force")
            continue

        errors = [p for p in lint.lint_file(f) if p.error]
        if errors and not force:
            report["lint 未通过"].append(f"{rel}：" + "；".join(f"{p.line} 行 {p.rule}" for p in errors[:3]))
            continue
        report["新增"].append(str(shown))
        if apply_:
            target.parent.mkdir(parents=True, exist_ok=True)
            f.rename(target)
            moved += 1

    for title, items in report.items():
        if items:
            click.echo(f"\n{title}（{len(items)}）")
            for item in items:
                click.echo(f"  {item}")
    if not apply_:
        click.echo("\n以上为计划，加 --apply 执行。有变化的文件不会被覆盖，需要对照 diff 手动处理。")
    elif moved:
        click.echo(f"\n已移入 {moved} 部。接着运行 `cd scripts && ./update_all_db.sh` 更新数据库。")


if __name__ == "__main__":
    cli()
