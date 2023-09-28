import logging
import re
from typing import List, Tuple

from docx.document import Document as _Document
from docx import Document
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.oxml import CT_SectPr
from docx.table import Table, _Cell, _Row
from docx.text.paragraph import Paragraph
from parsers.base import Parser
from common import LINE_RE

logger = logging.getLogger(__name__)


def isStartLine(line: str):
    for reg in LINE_RE:
        if re.match(reg, line):
            return True
    return False


class WordParser(Parser):
    def __init__(self) -> None:
        super().__init__("WORD")

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

    def parse(self, result, detail) -> Tuple[str, str, List[str]]:
        document = self.request.get_word(detail["path"])
        if not document:
            logger.warning(f"document {detail['path']} not exists")
            return

        title = result["title"].strip()
        return self.parse_document(document, title)

    def parse_document(self, document, title):
        if not isinstance(document, _Document):
            with open(document, "rb") as f:
                document = Document(f)

        if not isinstance(document, _Document):
            raise Exception("document is not a _Document")

        desc = ""
        content = []
        isDesc = False

        lines = list(filter(lambda x: x, self.iter_block_items(document)))

        def write_row(row):
            arr = ["| "]
            for cell in row.cells:
                text = "\n".join([p.text for p in cell.paragraphs])
                arr.append(f"{text}  |")
            content.append("".join(arr))
            return len(arr) - 1

        hasDesc = False
        for n, line in enumerate(lines):
            if isinstance(line, Table):
                content.append("<!-- TABLE -->")
                table = line

                size = write_row(table.rows[0])
                content.append("".join(["|"] + ["-----|"] * size))

                """
                | Item         | Price     | # In stock |
                |--------------|-----------|------------|
                | Juicy Apples | 1.99      | *7*        |
                | Bananas      | **1.89**  | 5234       |
                """

                for row in table.rows[1:]:
                    write_row(row)
                content.append("<!-- TABLE END -->")
                continue

            if isinstance(line, Paragraph):
                line = line.text.strip()

            # 信息行
            if re.match(r"[（\(]\d{4,4}年\d{1,2}月\d{1,2}日", line):
                isDesc = True
                hasDesc = True

            if isDesc:
                desc += line
            elif n > 0:
                content.append(line)

            # 信息行结束
            if isDesc and re.search("[）\)]$", line):
                isDesc = False
            if isDesc and re.search(r"目.*录", line):
                isDesc = False
            if isDesc and isStartLine(line):
                isDesc = False

            if not hasDesc and re.search("^法释", line):
                hasDesc = True

        return title, desc, content
