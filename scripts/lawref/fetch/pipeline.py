"""下载、解析一批法规，写到 __cache__/out/。同时下载几部，一部失败不影响其余的。"""
import asyncio
import itertools
import re
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

import tqdm

from lawref.dates import iso_dates, parse_iso, to_cn
from lawref.document import INFO_END, head_of, law_filename, split_filename
from lawref.fetch import net
from lawref.fetch.models import LawItem, Page
from lawref.fetch.sources import Provider
from lawref.parse import ParseError, parse_file
from lawref.parse.content import build, render
from lawref.paths import OUT_DIR
from lawref.repo import is_manual_law, law_files
from lawref.text import short_title

# 同时下载几部，也是同时打开的连接数上限。时间几乎都花在等网络上，解析一部只要几十毫秒
JOBS = 4

# 一部法规写到 out/ 下的哪个位置
Place = Callable[[LawItem], Path]
Items = Iterable[LawItem] | AsyncIterable[LawItem]


class ProcessError(Exception):
    """一部法规下载或解析失败，消息说明原因。"""


@dataclass
class Result:
    written: list[Path] = field(default_factory=list)
    # (法规名称或列表页, 原因)
    failures: list[tuple[str, str]] = field(default_factory=list)


def item_filename(item: LawItem) -> str:
    return law_filename(item.title, item.publication_date)


def default_place(item: LawItem) -> Path:
    return Path(item.folder) / item_filename(item)


def should_ignore(name: str) -> bool:
    """不下载的：手动维护的刑法、民法典，以及决定、复函、批复、答复。"""
    return is_manual_law(name) or bool(re.search(r"的(决定|复函|批复|答复)$", short_title(name)))


def with_effective_date(lines: list[str], in_effect: str | None, published: str | None) -> list[str]:
    """法规库给出的施行日期晚于发布日期、头部又没写时，补一行「X年X月X日 施行」。

    修正版的施行日期往往不在正文里，`laws db update` 从这一行读取生效日期。
    """
    if not parse_iso(in_effect) or not published or in_effect <= published or INFO_END not in lines:
        return lines
    end = lines.index(INFO_END)
    if any(re.match(r"^\d{4}年\d{1,2}月\d{1,2}日\s*施行$", line) for line in lines[1:end]):
        return lines
    return [*lines[:end], f"{to_cn(in_effect)} 施行", *lines[end:]]


def write_output(rel: Path, lines: list[str]) -> Path:
    path = OUT_DIR / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(lines), encoding="utf-8")
    return path


# ---------- 已经收录的 ----------

def law_dates(path: Path) -> set[str]:
    """文件名里的日期和头部信息里出现的日期（通过、公布、施行等），格式 YYYY-MM-DD。

    同一部法规，仓库文件名有时用通过日，法规库给的是公布日，只比文件名会重复收录。
    """
    dates = set(iso_dates(head_of(path.read_text(encoding="utf-8"))))
    if date := split_filename(path.name)[1]:
        dates.add(date)
    return dates


def known_laws() -> dict[str, set[str]]:
    """仓库（含 DLC）和 out/ 里已有的法规：{名称: {文件名和头部信息里的日期，没有日期为空串}}。"""
    known: dict[str, set[str]] = {}
    for f in itertools.chain(law_files(include_dlc=True), OUT_DIR.rglob("*.md")):
        name, date = split_filename(f.name)
        dates = known.setdefault(short_title(name), set())
        dates.add(date or "")
        dates |= law_dates(f)
    return known


def is_known(item: LawItem, known: dict[str, set[str]]) -> bool:
    dates = known.get(short_title(item.title), set())
    if not item.publication_date:
        return "" in dates
    return item.publication_date in dates or (item.in_effect_date or "") in dates


# ---------- 下载 ----------

async def process_item(provider: Provider, item: LawItem, place: Place = default_place) -> Path:
    """下载并解析一部法规，写到 out/。失败时抛 ProcessError。"""
    try:
        path = await provider.fetch_document(item)
    except Exception as e:
        # 超时之类的异常 str() 是空的
        raise ProcessError(f"下载失败：{str(e) or repr(e)}") from e
    title = provider.heading(item)
    # 解析 Word 和转换 .doc 会占住事件循环，放到线程里
    try:
        doc = await asyncio.to_thread(parse_file, path, title)
    except ParseError as e:
        raise ProcessError(str(e)) from e
    lines = build(doc.title, await provider.header_note(item, doc.note), doc.lines)
    if not lines:
        raise ProcessError(f"没有解析出正文：{path.name}")
    lines = with_effective_date(lines, item.in_effect_date, item.publication_date)
    return write_output(place(item), lines)


async def _aiter(items: Items) -> AsyncIterator[LawItem]:
    if hasattr(items, "__aiter__"):
        async for item in items:
            yield item
    else:
        for item in items:
            yield item


async def run(provider: Provider, items: Items, place: Place = default_place, jobs: int = JOBS,
              total: int | None = None, result: Result | None = None) -> Result:
    """下载 items，同时最多 jobs 部。items 可以边翻页边产出，有空位时再取下一部。"""
    result = result or Result()
    bar = tqdm.tqdm(total=total, unit="laws")
    slots = asyncio.Semaphore(jobs)

    async def one(item: LawItem):
        try:
            result.written.append(await process_item(provider, item, place))
        except ProcessError as e:
            result.failures.append((item.title, str(e)))
        except Exception as e:
            # 一部出错不影响其余的，记下来最后一起列出
            result.failures.append((item.title, f"{type(e).__name__}：{e}"))
        finally:
            slots.release()
            bar.set_description(f"Processing: {item.short_title[:20]}")
            bar.update()

    async with asyncio.TaskGroup() as group:
        async for item in _aiter(items):
            await slots.acquire()
            group.create_task(one(item))
    bar.close()
    return result


async def run_pages(provider: Provider, pages: Callable[[int], Awaitable[Page]], limit: int = 0,
                    place: Place = default_place, jobs: int = JOBS) -> Result:
    """从第 1 页起逐页列出，下载尚未收录的，最多 limit 部（0 为不限）。列表页出错时停在那一页。"""
    known = known_laws()
    result = Result()

    async def pending() -> AsyncIterator[LawItem]:
        count = 0
        for page_num in itertools.count(1):
            try:
                page = await pages(page_num)
            except net.HTTPError as e:
                if e.status != 404:
                    result.failures.append((f"列表第 {page_num} 页", str(e)))
                return
            except net.NetworkError as e:
                result.failures.append((f"列表第 {page_num} 页", str(e) or repr(e)))
                return
            if not page.items:
                return
            for item in page.items:
                if should_ignore(item.title) or is_known(item, known):
                    continue
                yield item
                count += 1
                if count == limit:
                    return

    return await run(provider, pending(), place, jobs, total=limit if limit > 0 else None, result=result)
