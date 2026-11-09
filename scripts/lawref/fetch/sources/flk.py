"""国家法律法规数据库：https://flk.npc.gov.cn"""
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from lawref.fetch import net
from lawref.fetch.cache import CacheType
from lawref.fetch.models import LawItem, Page

from .base import Provider

# 时效性（sxx）
ABOLISHED = 1      # 已废止
AMENDED = 2        # 已修改
VALID = 3          # 有效
NOT_YET_VALID = 4  # 尚未生效
ALL_VALIDITY = (NOT_YET_VALID, VALID, AMENDED, ABOLISHED)

# 法律性质（flfgCodeId）
LAWS = (101, 102, 110, 120, 130, 140, 150, 155, 160, 170, 180, 190, 195, 200)
ADMINISTRATIVE_REGULATIONS = (210,)
LOCAL_REGULATIONS = (230,)
JUDICIAL_INTERPRETATIONS = (311, 320, 330, 340, 350)
# 检索页面默认勾选的法律性质
DEFAULT_CATEGORIES = (102, 110, 120, 130, 140, 150, 160, 170, 180, 190, 195)

# 检索方式（searchType）：1 只搜标题，2 是检索页面的默认方式
TITLE_SEARCH = 1
DEFAULT_SEARCH = 2


@dataclass(frozen=True)
class FlkQuery:
    """列表检索的条件，对应检索页面上的选项。"""
    categories: Sequence[int] = DEFAULT_CATEGORIES
    # 制定机关（zdjgCodeId），地方性法规按它选地区，见 regions.REGION_CODE_MAP
    lawmakers: Sequence[int] = ()
    validity: Sequence[int] = (NOT_YET_VALID, VALID)
    keyword: str = ""
    search_type: int = DEFAULT_SEARCH


class NationalLawDatabaseProvider(Provider):
    BASE_URL = "https://flk.npc.gov.cn"
    HEADERS: ClassVar[dict[str, str]] = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json;charset=UTF-8",
        "Origin": "https://flk.npc.gov.cn",
        "Referer": "https://flk.npc.gov.cn/search",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
    }

    async def search(self, query: FlkQuery, page_num: int = 1, page_size: int = 20) -> Page:
        """按条件检索，按公布日期从新到旧排列。"""
        payload = {
            "searchRange": 1,
            "sxrq": [],
            "gbrq": [],
            "searchType": query.search_type,
            "sxx": list(query.validity),
            "gbrqYear": [],
            "flfgCodeId": list(query.categories),
            "zdjgCodeId": list(query.lawmakers),
            "searchContent": query.keyword,
            "orderByParam": {"order": "gbrq", "sort": "DESC"},
            "pageNum": page_num,
            "pageSize": page_size,
        }
        return self._page(await net.get_json("POST", f"{self.BASE_URL}/law-search/search/list",
                                             headers=self.HEADERS, json=payload))

    async def search_title(self, title: str, page_num: int = 1, page_size: int = 20) -> Page:
        """高级检索按标题找，只有现行有效的。"""
        payload = {
            "dataList": [{"fieldName": "title", "values": [title], "link": 0, "searchType": 1, "index": 0}],
            "orderByParam": {},
            "pageNum": page_num,
            "pageSize": page_size,
        }
        return self._page(await net.get_json("POST", f"{self.BASE_URL}/law-search/highSearch/highSearch",
                                             headers=self.HEADERS, json=payload))

    @staticmethod
    def _page(response: dict) -> Page:
        items = [LawItem(
            id=row.get("bbbs", ""),
            # 标题里有高亮用的 HTML 标签
            title=re.sub(r"<[^>]*>", "", row.get("title", "")),
            released_by=row.get("zdjgName", ""),
            publication_date=row.get("gbrq", ""),
            in_effect_date=row.get("sxrq", ""),
            folder=row.get("flxz", ""),
            type_code=row.get("flfgCodeId", 0),
        ) for row in response.get("rows", [])]
        return Page(total=response.get("total", 0), items=items)

    async def fetch_document(self, item: LawItem) -> Path:
        response = await net.get_json("GET", f"{self.BASE_URL}/law-search/download/pc?format=docx&bbbs={item.id}",
                                      headers=self.HEADERS)
        download_url = (response.get("data") or {}).get("url", "")
        if not download_url:
            raise ValueError("接口没有返回下载地址")
        return await self.cache.download(download_url, CacheType.WORD)
