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
_NOTE = re.compile(rf"^[（(]{DATE_RE}.*[）)]$")


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
            # 标题后面的题注：「（2023年8月23日教育部令第53号公布 自2023年10月15日起施行）」
            if not desc and _NOTE.match(line) and len(content) <= 1:
                desc = line
                continue
            content.append(line)

        if not title and content:
            title = content[0]
        # 标题在正文里重复时 ContentParser 会去掉；这里只去掉开头完全相同的一行
        if content and norm(content[0]) == norm(title):
            content.pop(0)
        return title, desc, content
