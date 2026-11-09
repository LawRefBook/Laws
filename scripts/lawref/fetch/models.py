from dataclasses import dataclass

from lawref.text import short_title


@dataclass
class LawItem:
    """数据源列出的一部法规。"""
    # 数据源里的标识，下载原文时用
    id: str
    title: str
    released_by: str
    # 写到 out/ 下哪个目录，organize 按它判断层级：「法律」「行政法规」「部门规章/教育部」……
    folder: str
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
class Page:
    """列表的一页。"""
    total: int
    items: list[LawItem]
