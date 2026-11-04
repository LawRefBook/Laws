from model.law import FetchedLawResponse, FetchedDocumentResponse, LawListItem
from .cache_provider import CacheManager


class Provider:
    def __init__(self) -> None:
        self.cache_manager = CacheManager()

    def fetch(self, page_num=1, page_size=20, **kwargs) -> FetchedLawResponse:
        raise NotImplementedError("Subclasses must implement this method")

    def fetch_document(self, law: LawListItem) -> FetchedDocumentResponse:
        raise NotImplementedError("Subclasses must implement this method")

    def note(self, law: LawListItem) -> str:
        """原文里没有题注时，由数据源给出的头部信息，格式同「（2020年…公布　自…起施行）」。"""
        return ""

    def heading(self, law: LawListItem) -> str:
        """文件里的 # 标题。"""
        return law.title
