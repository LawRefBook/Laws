"""文本清理、法规名称归一化、繁简转换。都是纯函数。"""
import re

NUMBER_RE = "[一二三四五六七八九十零百千万1234567890]"

# 标题层级按首次出现的顺序决定，序言固定为二级标题
PREFACE_RE = "^序言$"
INDENT_RE = [
    f"^第{NUMBER_RE}+编",
    f"^第{NUMBER_RE}+分编",
    # 民航规章的章是「A章 总则」「B章 飞行」
    f"^(?:第{NUMBER_RE}+|[A-Z]{{1,2}})章",
    f"^第{NUMBER_RE}+节",
    "^([一二三四五六七八九十零百千万]+、.{1,15})[^。；：]$",
]

LINE_RE = [PREFACE_RE, *INDENT_RE, f"^第{NUMBER_RE}+条"]

_INVISIBLE = re.compile("[​‌‍⁠﻿\xad]")
_SPACE = re.compile(r"[\s　\xa0]+")

_PUA = "-"
# 私用区字符：数字之间的  是小数点（「GB99592-2001」「14米」）；
# 在段首段尾、空白或标点旁边的是排版残留；夹在两个字中间的可能是生僻字，保留
_PUA_DOT = re.compile(r"(?<=\d)(?=\d)")
_PUA_STRAY = re.compile(rf"(?:^|(?<=[\s　，。；：、！？）)》”]))[{_PUA}]+|[{_PUA}]+(?=$|[\s　，。；：、！？（(《“])", re.M)


def fix_private_use(text: str) -> str:
    return _PUA_STRAY.sub("", _PUA_DOT.sub(".", text))


def clean(text: str) -> str:
    """去掉不可见字符和排版残留的私用区字符，连续空白合并为一个半角空格。"""
    return _SPACE.sub(" ", _INVISIBLE.sub("", fix_private_use(text))).strip()


def norm(text: str) -> str:
    """去掉全部空白和不可见字符，用于比较。"""
    return _SPACE.sub("", _INVISIBLE.sub("", text))


def strip_prc(name: str) -> str:
    """去掉开头的「中华人民共和国」。"""
    return re.sub("^中华人民共和国", "", name)


def short_title(title: str) -> str:
    """文件名和数据库里的法规名：去掉开头和书名号里的「中华人民共和国」。

    「关于适用《中华人民共和国民事诉讼法》的解释」→「关于适用《民事诉讼法》的解释」，
    「外国人在中华人民共和国收养子女登记办法」这种句中的保留。
    """
    return re.sub("([《〈])中华人民共和国", r"\1", strip_prc(clean(title)))


def title_key(title: str) -> str:
    """比较两个标题是不是同一部法规：去掉空白，〈〉当作《》，再按 short_title 去掉「中华人民共和国」。

    正文引用「《最高人民法院关于适用〈中华人民共和国婚姻法〉若干问题的解释（三）》」
    和文件名「最高人民法院关于适用《婚姻法》若干问题的解释（三）」是同一部。
    """
    return short_title(re.sub(r"\s", "", title).replace("〈", "《").replace("〉", "》"))


# ---------- 繁简转换 ----------

_T2S = None
# 繁转简后有变化的字占汉字的比例超过这个值，才当作繁体文本。
# 简体文本里也有少数字会被繁转简规则改动（如「乾」「徵」），不能每份都转。
TRADITIONAL_RATIO = 0.01


def _t2s():
    global _T2S
    if _T2S is None:
        from opencc import OpenCC
        _T2S = OpenCC("t2s")
    return _T2S


def is_traditional(text: str) -> bool:
    han = [ch for ch in text if "一" <= ch <= "鿿"]
    if not han:
        return False
    sample = "".join(han[:20000])
    changed = sum(1 for a, b in zip(sample, _t2s().convert(sample), strict=False) if a != b)
    return changed / len(sample) > TRADITIONAL_RATIO


def to_simplified(text: str) -> str:
    return _t2s().convert(text)
