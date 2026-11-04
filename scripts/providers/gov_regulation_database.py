"""国家规章库：https://www.gov.cn/zhengce/xxgk/gjgzk/

列表走 sousuoht.www.gov.cn 的检索接口，原文是 gov.cn 上的网页。
规章库里还有地方政府规章，原文在各地政府网站上，这里只取部门规章。
"""
import re
from typing import Optional

from model.law import FetchedDocumentResponse, FetchedLawResponse, LawListItem

from .base import Provider
from .cache_provider import CacheType
from .net import session

# 国家规章库的部门名 → 仓库里已有的目录名
DEPARTMENT_FOLDERS = {
    "国家市场监督管理总局": "市场监督管理总局",
    "人力资源和社会保障部": "人力资源社会保障部",
    "人民银行": "中国人民银行",
}

_DATE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")


def _iso(m: re.Match) -> str:
    return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


def dates_from_note(note: str):
    """题注「（2023年8月23日教育部令第53号公布 自2023年10月15日起施行）」→ (发布日期, 施行日期)。

    修正过的规章取最后一次修正的日期，和国家法律法规数据库的文件名一致。
    """
    note = note or ""
    effective = re.search(r"自(\d{4})年(\d{1,2})月(\d{1,2})日起?施行", note)
    dates = [m for m in _DATE.finditer(note) if not (effective and m.start() == effective.start() + 1)]
    if not dates:
        return None, None
    publish = _iso(dates[-1])
    if effective:
        return publish, _iso(effective)
    if re.search(r"自(?:公布|发布)之日起?施行", note):
        return publish, publish
    return publish, None


class GovRegulationDatabaseProvider(Provider):
    URL = "https://sousuoht.www.gov.cn/athena/forward/BD8730CDDA12515E2D9E1B21AA11C0D6"
    HEADERS = {
        "Accept": "*/*",
        "Content-Type": "application/json;charset=UTF-8",
        "Origin": "https://www.gov.cn",
        "Referer": "https://www.gov.cn/",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36",
        # 页面用固定公钥把固定的 app key 做 RSA 加密，服务器只解密，所以这段密文可以一直用。
        # 失效时在浏览器开发者工具里复制新的。
        "athenaAppKey": "e378ss4Fioi7k6RUxat%2FpYwMOZBnHL76BkfMmP%2FEbzalXTQc1i4crLIxrsMs%2F6JzKcLqyGxWki1mqco1gK%2F7PhIGkYKscCoz8GXXqrznxAIenlg3QHvotnEtzIKBl2DPu%2BkFlmvxPX6iJYnOi3z26v0uol%2FNVtWckaBblXFHqIk%3D",
        "athenaAppName": "%E8%A7%84%E7%AB%A0%E5%BA%93",  # 规章库
    }

    # 检索接口的字段
    TITLE = "f_202321360426"
    NOTE = "f_202344311304"           # 题注：「（…令第X号公布 自…起施行）」
    DEPARTMENT = "f_202328191239"     # 制定部门，按它检索
    DEPARTMENT_NAME = "f_202323394765"
    KIND = "f_202321864401"           # 1 部门规章，3 地方政府规章
    PUBLISHED_AT = "f_202321915922"   # 「2023-08-23 00:00:00」，按它排序
    FULL_TEXT = "f_202321758948"      # 全文，空白已被压成一行，只用来检索
    URL_FIELD = "doc_pub_url"
    DEPARTMENT_RULE = 1

    def fetch(self, page_num=1, page_size=20, department: Optional[str] = None, search_word: str = "",
              **kwargs) -> FetchedLawResponse:
        """department 为空时取全部部门规章。"""
        fields = [
            {"fieldName": self.KIND, "searchWord": str(self.DEPARTMENT_RULE), "searchType": "TERM"},
            {"fieldName": self.FULL_TEXT, "searchWord": search_word, "withHighLight": True},
        ]
        if department:
            fields.insert(0, {"fieldName": self.DEPARTMENT, "searchWord": department, "searchType": "TERM"})
        payload = {
            "code": "18258ab0ac9",
            "searchFields": fields,
            "sorts": [{"sortField": self.PUBLISHED_AT, "sortOrder": "DESC"}],
            "resultFields": [self.TITLE, self.NOTE, self.DEPARTMENT, self.DEPARTMENT_NAME, self.KIND,
                             self.PUBLISHED_AT, self.URL_FIELD],
            "tableName": "t_1860c735d31",
            "trackTotalHits": "true",
            "pageNo": page_num,
            "pageSize": str(page_size),
            "granularity": "ALL",
        }
        response = session.post(self.URL, headers=self.HEADERS, json=payload)
        response.raise_for_status()
        data = response.json()["result"]["data"]

        items = []
        for row in data.get("list", []):
            url = row.get(self.URL_FIELD) or ""
            if row.get(self.KIND) != self.DEPARTMENT_RULE or "www.gov.cn" not in url:
                continue
            publish, effective = dates_from_note(row.get(self.NOTE))
            department_name = department or self.first_department(row)
            items.append(LawListItem(
                id=url,
                title=re.sub(r"<[^>]*>", "", row.get(self.TITLE) or ""),
                released_by=department_name,
                publication_date=publish or (row.get(self.PUBLISHED_AT) or "")[:10] or None,
                in_effect_date=effective,
                # 写到 out/部门规章/<部门>/
                type=f"部门规章/{DEPARTMENT_FOLDERS.get(department_name, department_name)}",
                file_link=url,
            ))
        return FetchedLawResponse(total=data["pager"]["total"], items=items)

    def first_department(self, row: dict) -> str:
        """制定部门。字段有时是列表、有时是字符串，联合发布的放在第一个部门的目录下。"""
        for field in (self.DEPARTMENT, self.DEPARTMENT_NAME):
            value = row.get(field)
            if isinstance(value, list):
                value = next((v for v in value if v), None)
            if value:
                return re.split(r"[、，,\s]+", value.strip())[0]
        return "其他"

    def fetch_document(self, law: LawListItem) -> FetchedDocumentResponse:
        path = self.cache_manager.download_binary(
            law.file_link, CacheType.HtmlPage, headers={"User-Agent": self.HEADERS["User-Agent"]})
        return FetchedDocumentResponse(law=law, path_to_file=path)
