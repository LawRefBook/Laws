import re
from typing import Dict, Optional, Tuple

from common import DATE_RE, LINE_RE, clean, norm
from docx import Document
from docx.document import Document as _Document
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table, _Cell, _Row
from docx.text.paragraph import Paragraph


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


_DRAWING = {f"{_W}drawing", f"{_W}pict", f"{_W}txbxContent",
            "{http://schemas.openxmlformats.org/markup-compatibility/2006}AlternateContent"}


def _in_drawing(node, root) -> bool:
    """文本框、图形里的文字不算段落正文（兼容格式下还会各存两份）。"""
    parent = node.getparent()
    while parent is not None and parent is not root:
        if parent.tag in _DRAWING:
            return True
        parent = parent.getparent()
    return False


def paragraph_text(paragraph: Paragraph) -> str:
    """段落的全部文字。

    python-docx 0.8.11 的 Paragraph.text 只拼接段落的直接子节点，超链接（w:hyperlink）
    和域（w:fldSimple）里的文字会丢，比如「具有刑事诉讼法第十六条规定」读成「具有第规定」。
    """
    parts = []
    for node in paragraph._p.iter(f"{_W}t", f"{_W}tab", f"{_W}br", f"{_W}cr"):
        if _in_drawing(node, paragraph._p):
            continue
        if node.tag == f"{_W}t":
            parts.append(node.text or "")
        elif node.tag == f"{_W}tab":
            parts.append("\t")
        else:
            parts.append("\n")
    return "".join(parts)


_CN_DIGITS = "〇一二三四五六七八九"


def _chinese_counting(n: int) -> str:
    """1 → 一，10 → 十，21 → 二十一，105 → 一百零五。"""
    if n <= 0:
        return str(n)
    units = [(1000, "千"), (100, "百"), (10, "十")]
    ret, zero = "", False
    for value, unit in units:
        d, n = divmod(n, value)
        if d:
            if zero:
                ret += "零"
            ret += ("" if d == 1 and unit == "十" and not ret else _CN_DIGITS[d]) + unit
            zero = False
        elif ret:
            zero = True
    if n:
        ret += ("零" if zero else "") + _CN_DIGITS[n]
    return ret


def _roman_counts(n: int):
    """1 ≤ n < 40 拆成 x、ix、v、iv、i 各几个。"""
    for value in (10, 9, 5, 4, 1):
        count, n = divmod(n, value)
        yield count


def _format_number(n: int, fmt: str) -> Optional[str]:
    if fmt in ("chineseCounting", "chineseCountingThousand", "chineseLegalSimplified",
               "taiwaneseCounting", "taiwaneseCountingThousand", "japaneseCounting"):
        return _chinese_counting(n)
    if fmt in ("ideographDigital", "taiwaneseDigital"):
        return "".join(_CN_DIGITS[int(c)] for c in str(n))
    if fmt in ("decimal", "decimalZero", "decimalFullWidth", "decimalHalfWidth"):
        return str(n)
    if fmt == "decimalEnclosedCircle" and 1 <= n <= 20:
        return chr(0x2460 + n - 1)
    if fmt in ("lowerRoman", "upperRoman") and 1 <= n < 40:
        roman = "".join(r * c for r, c in zip(("x", "ix", "v", "iv", "i"), _roman_counts(n)))
        return roman.upper() if fmt == "upperRoman" else roman
    if fmt == "lowerLetter" and n <= 26:
        return chr(ord("a") + n - 1)
    if fmt == "upperLetter" and n <= 26:
        return chr(ord("A") + n - 1)
    # bullet、none 等不是编号
    return None


class Numbering:
    """Word 的自动编号：「第一章」「第十二条」不在段落文字里，按 numbering.xml 的定义数出来。

    python-docx 读不到自动编号，以前「第一章 总则」只剩「总则」。
    """

    def __init__(self, document: _Document):
        self.levels: Dict[Tuple[str, str], Tuple[int, str, str]] = {}
        self.counters: Dict[str, Dict[str, int]] = {}
        try:
            numbering = document.part.numbering_part.element
        except (KeyError, NotImplementedError, AttributeError):
            return
        abstract = {a.get(f"{_W}abstractNumId"): a for a in numbering.iterchildren(f"{_W}abstractNum")}
        for num in numbering.iterchildren(f"{_W}num"):
            num_id = num.get(f"{_W}numId")
            ref = num.find(f"{_W}abstractNumId")
            definition = abstract.get(ref.get(f"{_W}val")) if ref is not None else None
            if definition is None:
                continue
            overrides = {o.get(f"{_W}ilvl"): o for o in num.iterchildren(f"{_W}lvlOverride")}
            for lvl in definition.iterchildren(f"{_W}lvl"):
                ilvl = lvl.get(f"{_W}ilvl")
                start = self._val(lvl, "start", "1")
                if (o := overrides.get(ilvl)) is not None:
                    start = self._val(o, "startOverride", start)
                self.levels[(num_id, ilvl)] = (int(start), self._val(lvl, "numFmt", "decimal"), self._val(lvl, "lvlText", ""))

    @staticmethod
    def _val(node, tag: str, default: str) -> str:
        child = node.find(f"{_W}{tag}")
        return child.get(f"{_W}val", default) if child is not None else default

    @staticmethod
    def _num_pr(paragraph: Paragraph):
        """段落自己的编号，没有时看样式（及其 basedOn）上的编号。"""
        p_pr = paragraph._p.pPr
        if p_pr is not None and p_pr.numPr is not None:
            return p_pr.numPr
        style = paragraph.style
        while style is not None:
            pr = style.element.pPr
            if pr is not None and pr.numPr is not None:
                return pr.numPr
            style = style.base_style
        return None

    def label(self, paragraph: Paragraph) -> str:
        """段落的编号文字，如「第一章」；没有编号返回空串。每调用一次计数加一。"""
        num_pr = self._num_pr(paragraph)
        if num_pr is None or num_pr.numId is None:
            return ""
        num_id = str(num_pr.numId.val)
        ilvl = str(num_pr.ilvl.val) if num_pr.ilvl is not None else "0"
        if num_id == "0" or (num_id, ilvl) not in self.levels:
            return ""
        start, fmt, text = self.levels[(num_id, ilvl)]
        if _format_number(1, fmt) is None:
            return ""
        counters = self.counters.setdefault(num_id, {})
        counters[ilvl] = counters.get(ilvl, start - 1) + 1
        # 上一级加一时，下级重新计数
        for deeper in [k for k in counters if int(k) > int(ilvl)]:
            del counters[deeper]

        def level_number(m) -> str:
            # lvlText 里的 %1 是第 0 级，%2 是第 1 级……
            level = str(int(m.group(1)) - 1)
            level_start, level_fmt, _ = self.levels.get((num_id, level), (1, fmt, ""))
            return _format_number(counters.get(level, level_start), level_fmt) or ""

        return re.sub(r"%(\d)", level_number, text)


def isStartLine(line: str):
    for reg in LINE_RE:
        if re.match(reg, line):
            return True
    return False


class WordParser:

    def iter_block_items(self, parent):
        """
        Generate a reference to each paragraph and table child within *parent*,
        in document order. Each returned value is an instance of either Table or
        Paragraph. *parent* would most commonly be a reference to a main
        Document object, but also works for a _Cell object, which itself can
        contain paragraphs and tables.
        """
        if isinstance(parent, _Document):
            parent_elm = parent.element.body
        elif isinstance(parent, _Cell):
            parent_elm = parent._tc
        elif isinstance(parent, _Row):
            parent_elm = parent._tr
        else:
            raise ValueError(f"something's not right {parent} {type(parent)}")
        for child in parent_elm.iterchildren():
            if isinstance(child, CT_P):
                yield Paragraph(child, parent)
            elif isinstance(child, CT_Tbl):
                yield Table(child, parent)

    def parse_document(self, document, title):
        """返回 (title, desc, content)。content 不含空行，标题行由 ContentParser 去掉。"""
        if not isinstance(document, _Document):
            with open(document, "rb") as f:
                document = Document(f)

        desc = ""
        content = []
        isDesc = False
        numbering = Numbering(document)

        def write_row(row):
            arr = ["| "]
            for cell in row.cells:
                text = " ".join([clean(paragraph_text(p)) for p in cell.paragraphs])
                arr.append(f"{text}  |")
            content.append("".join(arr))
            return len(arr) - 1

        for block in self.iter_block_items(document):
            if isinstance(block, Table):
                content.append("<!-- TABLE -->")
                size = write_row(block.rows[0])
                content.append("".join(["|"] + ["-----|"] * size))
                for row in block.rows[1:]:
                    write_row(row)
                content.append("<!-- TABLE END -->")
                continue

            text = paragraph_text(block)
            label = numbering.label(block) if text.strip() else ""
            # 「第一章 总则」中间空一格，「（一）内容」「1.内容」不空
            sep = "" if re.search(r"[）)、.．]$", label) else " "
            line = clean(f"{label}{sep}{text.lstrip()}" if label else text)
            # 空段落会打乱「目录」等按相邻行判断的逻辑
            if not line:
                continue

            # 标题和信息行写在同一段里：「XX条例 （2017年12月1日…」
            m = re.match(rf"^(.+?)\s*([（(]{DATE_RE}.*)$", line)
            if not desc and m and norm(m.group(1)) == norm(title):
                content.append(m.group(1))
                line = m.group(2)

            # 信息行
            if re.match(rf"[（(]{DATE_RE}", line):
                isDesc = True
            # 信息行没有以括号收尾时，遇到「第一条」也算结束，这一行属于正文
            if isDesc and desc and isStartLine(line):
                isDesc = False

            if isDesc:
                desc += line
            else:
                content.append(line)

            # 信息行结束
            if isDesc and re.search(r"[）\)]$", line):
                isDesc = False
            if isDesc and re.search(r"目.*录", line):
                isDesc = False
            if isDesc and isStartLine(line):
                isDesc = False

        return title, desc, content
