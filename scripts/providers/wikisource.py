"""维基文库：https://zh.wikisource.org

页面信息走 MediaWiki API，正文用维基文库的导出服务 ws-export 导出 epub，交给 EpubParser。
"""
import asyncio
import re
import urllib.parse
from typing import Dict, List, Optional

from model.law import FetchedDocumentResponse, FetchedLawResponse, LawListItem

from .base import Provider
from .cache_provider import CacheType
from .gov_regulation_database import DEPARTMENT_FOLDERS
from . import net

_DATE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")


def _iso(y, m, d) -> str:
    return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"


def header_fields(wikitext: str) -> Dict[str, str]:
    """页首 {{Header|...}} 模板的参数。参数值里可能有 [[链接]] 和换行，按「|名称 =」切分。"""
    m = re.search(r"\{\{\s*[Hh]eader\s*(.*?)\n\}\}", wikitext, re.S)
    if not m:
        return {}
    fields = {}
    for part in re.split(r"\n?\s*\|\s*(?=[^|=\[\]{}\n]+?\s*=)", m.group(1)):
        if "=" in part:
            key, value = part.split("=", 1)
            fields[key.strip()] = value.strip()
    return fields


# 同名法规的不同版本：「中华人民共和国增值税暂行条例实施细则 (2008年)」
_VERSION_SUFFIX = re.compile(r"\s*[（(]\d{4}年(?:\d{1,2}月)?[）)]$")


def base_title(page: str) -> str:
    return _VERSION_SUFFIX.sub("", page).strip()


def folder_for_lawmaker(lawmaker: str) -> Optional[str]:
    """按制定机关决定写到 out/ 下哪个目录，organize 按它判断层级。联合发布的按第一个机关。"""
    first = re.split(r"[、，,\s]+", re.sub(r"\[\[|\]\]", "", lawmaker).strip())[0]
    name = re.sub(r"^中华人民共和国", "", first)
    if not name:
        return None
    if "全国人民代表大会" in name:
        return "法律"
    if name == "国务院":
        return "行政法规"
    if name in ("最高人民法院", "最高人民检察院"):
        return "司法解释"
    return f"部门规章/{DEPARTMENT_FOLDERS.get(name, name)}"


def _title_key(title: str) -> str:
    """比较标题用：去掉空白和开头的「中华人民共和国」，〈〉当作《》。"""
    title = re.sub(r"\s", "", title).replace("〈", "《").replace("〉", "》")
    return re.sub(r"^中华人民共和国", "", title)


def lawmaker_from_notes(notes: str) -> str:
    """页首没有 lawmaker 时，从注释「（2007年3月16日第十届全国人民代表大会第五次会议通过…）」里认出制定机关。"""
    for court in ("最高人民法院", "最高人民检察院"):
        if court in notes:
            return court
    if "人民代表大会" in notes:
        return "全国人民代表大会"
    if "国务院" in notes:
        return "国务院"
    return ""


def link_titles(text: str) -> List[str]:
    """「*[[页面]]」「#[[页面|显示文字]]」里的页面名。"""
    return [m.group(1).strip() for m in re.finditer(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]", text)]


class WikisourceProvider(Provider):
    API = "https://zh.wikisource.org/w/api.php"
    EXPORT = "https://ws-export.wmcloud.org/"
    # 高级搜索默认勾选的名字空间：主名字空间、106、114
    SEARCH_NAMESPACES = "0|106|114"
    HEADERS = {"User-Agent": "LawsBot/1.0 (https://github.com/RanKKI/Laws)"}

    async def wikitext(self, title: str) -> str:
        data = await net.get_json("GET", self.API, headers=self.HEADERS, params={
            "action": "parse", "page": title, "prop": "wikitext", "format": "json", "formatversion": 2, "redirects": 1})
        if "error" in data:
            raise ValueError(f"{title}：{data['error'].get('info')}")
        return data["parse"]["wikitext"]

    async def index(self, title: str, see_also: bool = False) -> List[str]:
        """消歧义页、索引页列出的页面。see_also 时「另见」里的索引页也展开一层。"""
        main, _, also = (await self.wikitext(title)).partition("另见")
        pages = [t for line in main.splitlines() if line.lstrip().startswith(("*", "#")) for t in link_titles(line)]
        if see_also:
            for other in link_titles(also):
                if other != title and not other.startswith("Wikisource:"):
                    pages += [p for p in await self.index(other) if p not in pages]
        return list(dict.fromkeys(p for p in pages if not p.startswith(("Wikisource:", "Category:", "Portal:"))))

    async def item(self, page: str, type_: str) -> LawListItem:
        """页面 → 法规条目。名称保留维基文库的区分后缀，如「（2017年）」，同名的不同决定不会被当成一部法规的多个版本。"""
        fields = header_fields(await self.wikitext(page))
        y, m, d = (fields.get(k) or fields.get(k[0]) for k in ("year", "month", "day"))
        publish = _iso(y, m, d) if y and m and d and all(x.isdigit() for x in (y, m, d)) else None
        effective = _DATE.search(fields.get("生效日期", ""))
        notes = fields.get("notes", "")
        # 注释里不是施行的日期
        dates = [_iso(*m.groups()) for m in _DATE.finditer(notes)
                 if not notes[max(0, m.start() - 1):m.start()] == "自" and not notes[m.end():].startswith("起施行")]
        suffix = re.search(r"[（(](\d{4})年[）)]$", page)
        if publish and suffix and publish[:4] != suffix.group(1):
            # 页面「(2021年)」的日期字段抄成了上一版的 2018 年，按标题的年份从注释里找
            publish = max((d for d in dates if d[:4] == suffix.group(1)), default=publish)
        if not publish:
            # 没有日期字段的（「沿革和最新版」页、早年的版本），取注释里最后一个日期
            publish = max(dates) if dates else None
        if not effective and (m := re.search(r"自(\d{4})年(\d{1,2})月(\d{1,2})日起施行", notes)):
            effective = m
        title = re.sub(r"\s*\((.+?)\)$", r"（\1）", page)
        return LawListItem(
            id=page,
            title=title,
            released_by=re.sub(r"\[\[|\]\]", "", fields.get("lawmaker", "")) or lawmaker_from_notes(notes),
            publication_date=publish,
            in_effect_date=_iso(*effective.groups()) if effective else None,
            type=type_,
            file_link=page,
        )

    async def note(self, item: LawListItem) -> str:
        """头部信息：「（2017年3月1日中华人民共和国国务院令第676号公布　自2017年3月21日起施行）」。"""
        fields = header_fields(await self.wikitext(item.id))
        order = "".join(link_titles(fields.get("发布于", ""))) or re.sub(r"\[\[|\]\]", "", fields.get("发布于", ""))
        parts = []
        if item.publication_date:
            y, m, d = item.publication_date.split("-")
            parts.append(f"{int(y)}年{int(m)}月{int(d)}日{order}公布")
        if item.in_effect_date:
            y, m, d = item.in_effect_date.split("-")
            parts.append(f"自{int(y)}年{int(m)}月{int(d)}日起施行")
        return f"（{'　'.join(parts)}）" if parts else ""

    def heading(self, item: LawListItem) -> str:
        """去掉区分同名页面的「（2017年）」，只留在文件名里。"""
        return re.sub(r"（\d{4}年(?:\d{1,2}月)?）$", "", item.title)

    async def fetch(self, page_num=1, page_size=20, index: str = "", see_also: bool = False, type_: str = "行政法规",
              **kwargs) -> FetchedLawResponse:
        """索引页一次列完，只有第一页。"""
        if page_num > 1:
            return FetchedLawResponse(total=0, items=[])
        items = await asyncio.gather(*(self.item(page, type_) for page in await self.index(index, see_also)))
        return FetchedLawResponse(total=len(items), items=list(items))

    async def search(self, name: str) -> List[str]:
        """标题是 name 或「name (2008年)」的页面，开头的「中华人民共和国」可有可无，消歧义页除外。

        和维基文库高级搜索的「精确短语」一样搜正文和标题，范围是主名字空间和 106、114，再加上按标题搜。
        搜到的公报、判决书等只是提到了 name，按标题筛掉。
        """
        # 常见的名称正文提到的很多，版本页可能排在 100 条以后，再按标题搜一次合起来
        results = await asyncio.gather(*(net.get_json("GET", self.API, headers=self.HEADERS, params={
            "action": "query", "list": "search", "srsearch": query, "srnamespace": self.SEARCH_NAMESPACES,
            "srlimit": 100, "format": "json", "formatversion": 2}) for query in (f'"{name}"', f'intitle:"{name}"')))
        key = _title_key(name)
        pages = list(dict.fromkeys(r["title"] for data in results for r in data["query"]["search"]
                                   if _title_key(base_title(r["title"])) == key))
        if not pages:
            return []
        props = await net.get_json("GET", self.API, headers=self.HEADERS, params={
            "action": "query", "prop": "pageprops", "ppprop": "disambiguation", "titles": "|".join(pages),
            "format": "json", "formatversion": 2})
        disambiguation = {p["title"] for p in props["query"]["pages"] if "disambiguation" in p.get("pageprops", {})}
        return [p for p in pages if p not in disambiguation]

    @staticmethod
    def page_from_url(url: str) -> Optional[str]:
        """「https://zh.wikisource.org/wiki/页面」「/zh-hant/页面」「/w/index.php?title=页面」→ 页面名；不是维基文库的返回 None。"""
        parsed = urllib.parse.urlparse(url.strip())
        if not parsed.netloc.endswith("wikisource.org"):
            return None
        title = urllib.parse.parse_qs(parsed.query).get("title", [None])[0]
        if not title:
            m = re.match(r"^/(?:wiki|zh(?:-[a-z]+)?)/(.+)$", parsed.path)
            title = urllib.parse.unquote(m.group(1)) if m else None
        return title.replace("_", " ") if title else None

    async def version(self, page: str) -> Optional[LawListItem]:
        """一个页面作为一部法规的一个版本，和 versions 一样去掉年份后缀、按制定机关定目录。
        没有日期或定不了目录时返回 None。"""
        item = await self.item(page, "")
        folder = folder_for_lawmaker(item.released_by)
        if not item.publication_date or not folder:
            return None
        item.title = base_title(item.title)
        item.type = folder
        return item

    async def versions(self, name: str) -> List[LawListItem]:
        """搜索 name 的各个版本，按制定机关定目录。同一天的只留一个，优先带年份的页面，
        「沿革和最新版」页的内容和最新版相同。没有日期、也定不了目录的不要。"""
        items = await asyncio.gather(*(self.item(page, "") for page in await self.search(name)))
        by_date: Dict[str, LawListItem] = {}
        for item in sorted(items, key=lambda i: base_title(i.id) == i.id):
            folder = folder_for_lawmaker(item.released_by)
            if not item.publication_date or not folder or item.publication_date in by_date:
                continue
            item.title = base_title(item.title)
            item.type = folder
            by_date[item.publication_date] = item
        return sorted(by_date.values(), key=lambda i: i.publication_date)

    async def fetch_document(self, law: LawListItem) -> FetchedDocumentResponse:
        url = f"{self.EXPORT}?format=epub&lang=zh&page={law.file_link.replace(' ', '_')}"
        filename = re.sub(r"[\\/:*?\"<>|\s]+", "_", law.file_link) + ".epub"
        path = await self.cache_manager.download_binary(url, CacheType.Epub, headers=self.HEADERS, filename=filename)
        return FetchedDocumentResponse(law=law, path_to_file=path)
