from model.law import FetchedLawResponse, FetchedDocumentResponse, LawListItem
from .cache_provider import CacheManager


class Provider:
    def __init__(self) -> None:
        self.cache_manager = CacheManager()

    async def fetch(self, page_num=1, page_size=20, **kwargs) -> FetchedLawResponse:
        raise NotImplementedError("Subclasses must implement this method")

    async def fetch_document(self, law: LawListItem) -> FetchedDocumentResponse:
        raise NotImplementedError("Subclasses must implement this method")

    async def note(self, law: LawListItem) -> str:
        """原文里没有题注时，由数据源给出的头部信息，格式同「（2020年…公布　自…起施行）」。"""
        return ""

    async def header_note(self, law: LawListItem, desc: str) -> str:
        """写进头部的信息：原文里解析出来的优先，没有时用数据源给的。"""
        return desc or await self.note(law)

    def heading(self, law: LawListItem) -> str:
        """文件里的 # 标题。"""
        return law.title
