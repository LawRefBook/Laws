import re
from pathlib import Path
from typing import List

SCRIPTS_DIR = Path(__file__).resolve().parent
ROOT = SCRIPTS_DIR.parent
CACHE_DIR = SCRIPTS_DIR / "__cache__"

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

LINE_RE = [PREFACE_RE] + INDENT_RE + [f"^第{NUMBER_RE}+条"]

# 原文里有「2014 年 5 月 29 日」这样带空格的写法
DATE_RE = r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日"

_INVISIBLE = re.compile("[​‌‍⁠﻿\xad]")
_SPACE = re.compile(r"[\s　\xa0]+")


_PUA = "\ue000-\uf8ff"
# 私用区字符：数字之间的 \ue010 是小数点（「GB9959\ue0102-2001」「1\ue0104米」）；
# 在段首段尾、空白或标点旁边的是排版残留；夹在两个字中间的可能是生僻字，保留
_PUA_DOT = re.compile(r"(?<=\d)\ue010(?=\d)")
_PUA_STRAY = re.compile(rf"(?:^|(?<=[\s　，。；：、！？）)》”]))[{_PUA}]+|[{_PUA}]+(?=$|[\s　，。；：、！？（(《“])", re.M)


def fix_private_use(text: str) -> str:
    return _PUA_STRAY.sub("", _PUA_DOT.sub(".", text))


def clean(text: str) -> str:
    """去掉不可见字符和排版残留的私用区字符，连续空白合并为一个半角空格。"""
    return _SPACE.sub(" ", _INVISIBLE.sub("", fix_private_use(text))).strip()


def norm(text: str) -> str:
    """去掉全部空白和不可见字符，用于比较。"""
    return _SPACE.sub("", _INVISIBLE.sub("", text))


def short_title(title: str) -> str:
    """文件名和数据库里的法规名：去掉开头和书名号里的「中华人民共和国」。

    「关于适用《中华人民共和国民事诉讼法》的解释」→「关于适用《民事诉讼法》的解释」，
    「外国人在中华人民共和国收养子女登记办法」这种句中的保留。
    """
    title = re.sub("^中华人民共和国", "", clean(title))
    return re.sub("([《〈])中华人民共和国", r"\1", title)


# 刑法、民法典在仓库里按修正案、分编拆开手动维护，不自动下载
MANUAL_LAWS = re.compile(r"^(刑法|民法典)")


def is_manual_law(title: str) -> bool:
    return bool(MANUAL_LAWS.match(short_title(title)))


REGION_CODE_MAP = {
    "北京": 170,
    "天津": 180,
    "河北": 190,
    "山西": 200,
    "内蒙古": 210,
    "辽宁": 220,
    "吉林": 230,
    "黑龙江": 240,
    "上海": 250,
    "江苏": 260,
    "浙江": 270,
    "安徽": 280,
    "福建": 290,
    "江西": 300,
    "山东": 310,
    "河南": 320,
    "湖北": 330,
    "湖南": 340,
    "广东": 350,
    "广西": 360,
    "海南": 370,
    "重庆": 380,
    "四川": 390,
    "贵州": 400,
    "云南": 410,
    "西藏": 420,
    "陕西": 430,
    "甘肃": 440,
    "青海": 450,
    "宁夏": 460,
    "新疆": 470,
}


def parse_regions(spec: str) -> List[str]:
    """「7-31」「北京 3,5-8」→ 地区名。编号从 1 开始，顺序同 REGION_CODE_MAP，和 make shell 里列出的一样。"""
    names = list(REGION_CODE_MAP)
    spec = re.sub(r"\s*[-~～—]\s*", "-", spec.strip())
    result: List[str] = []
    for part in re.split(r"[,，、\s]+", spec):
        if not part:
            continue
        if part in REGION_CODE_MAP:
            picked = [part]
        elif m := re.fullmatch(r"(\d+)-(\d+)", part):
            start, end = int(m.group(1)), int(m.group(2))
            if not 1 <= start <= end <= len(names):
                raise ValueError(f"范围要在 1-{len(names)} 之间，且从小到大：{part}")
            picked = names[start - 1:end]
        elif part.isdigit() and 1 <= int(part) <= len(names):
            picked = [names[int(part) - 1]]
        else:
            raise ValueError(f"不支持的地区：{part}")
        result += [n for n in picked if n not in result]
    if not result:
        raise ValueError("没有选择地区")
    return result


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
    han = [ch for ch in text if "\u4e00" <= ch <= "\u9fff"]
    if not han:
        return False
    sample = "".join(han[:20000])
    changed = sum(1 for a, b in zip(sample, _t2s().convert(sample)) if a != b)
    return changed / len(sample) > TRADITIONAL_RATIO


def to_simplified(text: str) -> str:
    return _t2s().convert(text)
