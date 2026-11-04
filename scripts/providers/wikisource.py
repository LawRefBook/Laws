"""维基文库：https://zh.wikisource.org

页面信息走 MediaWiki API，正文用维基文库的导出服务 ws-export 导出 epub，交给 EpubParser。
"""
import re
from typing import Dict, List, Optional, Tuple

from model.law import FetchedDocumentResponse, FetchedLawResponse, LawListItem

from .base import Provider
from .cache_provider import CacheType
from .net import session

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


def link_titles(text: str) -> List[str]:
    """「*[[页面]]」「#[[页面|显示文字]]」里的页面名。"""
    return [m.group(1).strip() for m in re.finditer(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]", text)]


class WikisourceProvider(Provider):
    API = "https://zh.wikisource.org/w/api.php"
    EXPORT = "https://ws-export.wmcloud.org/"
    HEADERS = {"User-Agent": "LawsBot/1.0 (https://github.com/RanKKI/Laws)"}

    def wikitext(self, title: str) -> str:
        response = session.get(self.API, headers=self.HEADERS, params={
            "action": "parse", "page": title, "prop": "wikitext", "format": "json", "formatversion": 2, "redirects": 1})
        response.raise_for_status()
        data = response.json()
        if "error" in data:
            raise ValueError(f"{title}：{data['error'].get('info')}")
        return data["parse"]["wikitext"]

    def index(self, title: str, see_also: bool = False) -> List[str]:
        """消歧义页、索引页列出的页面。see_also 时「另见」里的索引页也展开一层。"""
        main, _, also = self.wikitext(title).partition("另见")
        pages = [t for line in main.splitlines() if line.lstrip().startswith(("*", "#")) for t in link_titles(line)]
        if see_also:
            for other in link_titles(also):
                if other != title and not other.startswith("Wikisource:"):
                    pages += [p for p in self.index(other) if p not in pages]
        return list(dict.fromkeys(p for p in pages if not p.startswith(("Wikisource:", "Category:", "Portal:"))))

    def item(self, page: str, type_: str) -> LawListItem:
        """页面 → 法规条目。名称保留维基文库的区分后缀，如「（2017年）」，同名的不同决定不会被当成一部法规的多个版本。"""
        fields = header_fields(self.wikitext(page))
        y, m, d = (fields.get(k) or fields.get(k[0]) for k in ("year", "month", "day"))
        publish = _iso(y, m, d) if y and m and d and all(x.isdigit() for x in (y, m, d)) else None
        effective = _DATE.search(fields.get("生效日期", ""))
        title = re.sub(r"\s*\((.+?)\)$", r"（\1）", page)
        return LawListItem(
            id=page,
            title=title,
            released_by=re.sub(r"\[\[|\]\]", "", fields.get("lawmaker", "")),
            publication_date=publish,
            in_effect_date=_iso(*effective.groups()) if effective else None,
            type=type_,
            file_link=page,
        )

    def note(self, item: LawListItem) -> str:
        """头部信息：「（2017年3月1日中华人民共和国国务院令第676号公布　自2017年3月21日起施行）」。"""
        fields = header_fields(self.wikitext(item.id))
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

    def fetch(self, page_num=1, page_size=20, index: str = "", see_also: bool = False, type_: str = "行政法规",
              **kwargs) -> FetchedLawResponse:
        """索引页一次列完，只有第一页。"""
        if page_num > 1:
            return FetchedLawResponse(total=0, items=[])
        items = [self.item(page, type_) for page in self.index(index, see_also)]
        return FetchedLawResponse(total=len(items), items=items)

    def fetch_document(self, law: LawListItem) -> FetchedDocumentResponse:
        url = f"{self.EXPORT}?format=epub&lang=zh&page={law.file_link.replace(' ', '_')}"
        filename = re.sub(r"[\\/:*?\"<>|\s]+", "_", law.file_link) + ".epub"
        path = self.cache_manager.download_binary(url, CacheType.Epub, headers=self.HEADERS, filename=filename)
        return FetchedDocumentResponse(law=law, path_to_file=path)
