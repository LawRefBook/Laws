"""「2020年1月1日」和「2020-01-01」之间的转换。

仓库里的头部写「2020年1月1日」，文件名、数据库写「2020-01-01」。
"""
import re

# 嵌进别的正则里用，不带分组。原文里有「2014 年 5 月 29 日」这样带空格的写法
DATE_RE = r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日"
# 分组依次是年、月、日
SPACED_DATE_RE = r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"
DATE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")
ISO_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def iso(year, month, day) -> str:
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def iso_of(m: re.Match) -> str:
    """年、月、日在第 1、2、3 组的匹配 → 「2020-01-01」。"""
    return iso(m.group(1), m.group(2), m.group(3))


def iso_dates(text: str) -> list[str]:
    """text 里依次出现的「X年X月X日」。"""
    return [iso_of(m) for m in DATE.finditer(text)]


def to_cn(date: str) -> str:
    """「2020-01-01」→「2020年1月1日」。"""
    year, month, day = date.split("-")
    return f"{int(year)}年{int(month)}月{int(day)}日"


def parse_iso(text: str | None) -> re.Match | None:
    """完整的「YYYY-MM-DD」，不是时返回 None。"""
    return ISO_DATE.fullmatch(text or "")
