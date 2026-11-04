import re

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

            line = clean(paragraph_text(block))
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
