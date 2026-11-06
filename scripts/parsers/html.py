"""解析中国政府网（gov.cn）的规章网页。

和 WordParser 一样返回 (title, desc, content)，再交给 ContentParser。
"""
import re
from pathlib import Path
from typing import List, Optional, Tuple

import bs4

from common import DATE_RE, clean, norm

# 正文容器：gov.cn 文章页是 #UCAP-CONTENT
_CONTAINERS = ["#UCAP-CONTENT", ".pages_content", ".article", "body"]
_NOTE = re.compile(rf"^[（(]\s*{DATE_RE}.*[）)]$")
# 不以日期开头的题注：「（国家旅游局令第22号公布 …自2005年7月3日起施行）」「(中国银行业监督管理委员会令2007年第3号公布…)」
_UNDATED_NOTE = re.compile(r"^[（(].*(?:公布|发布|印发|施行|实施|令第|修正|修订|通过).*[）)]$")


def _is_note(line: str) -> bool:
    return bool(_NOTE.match(line) or (_UNDATED_NOTE.match(line) and len(line) < 600))


class HtmlParser:

    def parse_document(self, path: Path, title: Optional[str] = None) -> Tuple[str, str, List[str]]:
        soup = bs4.BeautifulSoup(path.read_bytes(), "html.parser", from_encoding="utf-8")
        container = next(el for el in map(soup.select_one, _CONTAINERS) if el is not None)
        if title is None:
            meta = soup.find("meta", attrs={"name": "ArticleTitle"})
            title = clean(meta["content"]) if meta and meta.get("content") else ""

        desc = ""
        content = []
        for node in container.find_all(["p", "table"]):
            if node.find_parent("table"):
                continue
            # 有的页面用一个 <p> 包住全文，里面才是逐段的 <p>；外层的文字会和里面重复一遍
            if node.name == "p" and node.find("p") is not None:
                continue
            if node.name == "table":
                # 附件表格交给 ContentParser 的表格格式
                rows = node.find_all("tr")
                if not rows:
                    continue
                content.append("<!-- TABLE -->")
                for i, tr in enumerate(rows):
                    cells = [clean(td.get_text("")) for td in tr.find_all(["td", "th"])]
                    content.append("| " + "  |".join(cells) + "  |")
                    if i == 0:
                        content.append("|" + "-----|" * len(cells))
                content.append("<!-- TABLE END -->")
                continue
            line = clean(node.get_text(""))
            if not line:
                continue
            # 标题和题注在同一段：「人民币单位存款管理办法 （1997年11月21日…印发 自…起实施）」
            m = re.match(r"^(.+?)\s*([（(].+[）)])$", line)
            if not desc and not content and m and title and norm(m.group(1)) == norm(title) and _is_note(m.group(2)):
                content.append(m.group(1))
                line = m.group(2)
            # 标题后面的题注：「（2023年8月23日教育部令第53号公布 自2023年10月15日起施行）」
            if not desc and _is_note(line) and len(content) <= 1:
                desc = line
                continue
            content.append(line)

        if not title and content:
            title = content[0]
        # 标题在正文里重复时 ContentParser 会去掉；这里只去掉开头完全相同的一行
        if content and norm(content[0]) == norm(title):
            content.pop(0)
        return title, desc, content
