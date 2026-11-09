from typing import NamedTuple


class ParsedDocument(NamedTuple):
    """parser 从原文里取出的内容，再由 content.build 整理成仓库的格式。"""
    title: str
    # 题注：「（2020年…通过　根据2021年…修正）」，原文里没有时为空
    note: str
    # 正文各行，不含空行
    lines: list[str]


class ParseError(Exception):
    """原文无法解析，消息说明原因。"""
