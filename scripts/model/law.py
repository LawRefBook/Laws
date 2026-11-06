from dataclasses import dataclass
from typing import List
from pathlib import Path

from common import short_title


@dataclass
class LawListItem:
    id: str
    title: str
    released_by: str
    type: str
    publication_date: str | None = None
    in_effect_date: str | None = None
    type_code: int | None = None
    file_link: str | None = None
    # 数据源给的题注「（…公布 自…起施行）」，原文里没有时写进头部
    note: str | None = None

    @property
    def short_title(self) -> str:
        return short_title(self.title)


@dataclass
class FetchedLawResponse:
    total: int
    items: List[LawListItem]


@dataclass
class FetchedDocumentResponse:
    law: LawListItem
    path_to_file: Path | None
