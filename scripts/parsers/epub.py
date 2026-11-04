"""解析 epub，目前按维基文库（zh.wikisource.org）导出的格式处理。

和 WordParser 一样返回 (title, desc, content)，再交给 ContentParser。
"""
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import List, Optional, Tuple

import bs4

from common import DATE_RE, NUMBER_RE, clean, is_traditional, to_simplified

_BLOCKS = ["h1", "h2", "h3", "h4", "h5", "h6", "p", "table"]
# 维基文库页面里不属于正文的部分：姊妹计划、导航框、版权声明
_NOISE_CLASSES = {"noprint", "navbox", "navbox-inner", "licenseContainer", "licensetpl", "mw-collapsible"}
# 正文结束：维基文库的版权声明
_END = re.compile(r"^本作品(是|在|来自|由)")
_ARTICLE = re.compile(rf"^\s*第{NUMBER_RE}+条", re.M)


def _is_noise(node: bs4.Tag) -> bool:
    for parent in [node, *node.parents]:
        if isinstance(parent, bs4.Tag) and _NOISE_CLASSES & set(parent.get("class") or []):
            return True
    return False


def _text(node: bs4.Tag) -> str:
    # 脚注编号、编者注不是原文
    for sup in node.find_all("sup"):
        sup.decompose()
    return clean(node.get_text(""))


def _header_note(table: bs4.Tag) -> str:
    """维基文库开头的题注表格，按 <br/> 分行，只取以日期开头的行：

    「（1979年7月1日…通过　1997年3月14日…修订　根据…修正）」，或者不带括号、一行一个日期。
    上一版、下一版的导航表格（带 ← →）和题注后面的编者说明不算。
    """
    if "←" in table.get_text() or "→" in table.get_text():
        return ""
    table = bs4.BeautifulSoup(str(table), "html.parser")
    for node in table.find_all(["ul", "sup"]):
        node.decompose()
    for br in table.find_all("br"):
        br.replace_with("\n")
    lines = [clean(line) for line in table.get_text("").split("\n")]
    return " ".join(line for line in lines if re.match(rf"[（(]?{DATE_RE}", line))


def _table_lines(table: bs4.Tag) -> List[str]:
    """正文里的表格，格式同 WordParser：「| 甲  |乙  |」，第一行后面是分隔行。"""
    lines = ["<!-- TABLE -->"]
    for i, tr in enumerate(table.find_all("tr")):
        cells = [_text(td) for td in tr.find_all(["td", "th"])]
        lines.append("| " + "".join(f"{c}  |" for c in cells))
        if i == 0:
            lines.append("|" + "-----|" * len(cells))
    lines.append("<!-- TABLE END -->")
    return lines


def _is_content(body: bs4.Tag) -> bool:
    """有条文，或者有两段以上较长的中文段落（只列名单的废止决定没有条文）。封面只有标题，说明页是英文。"""
    if _ARTICLE.search(body.get_text("\n")):
        return True
    long = [p for p in body.find_all("p") if len(re.findall("[\u4e00-\u9fff]", p.get_text())) >= 20]
    return len(long) >= 2


class EpubParser:

    def read(self, path: Path) -> Tuple[str, List[bs4.Tag]]:
        """返回 epub 的标题和按阅读顺序排列的正文 body。繁体来源（如维基文库的 1954 年宪法）转成简体。"""
        with zipfile.ZipFile(path) as z:
            container = bs4.BeautifulSoup(z.read("META-INF/container.xml"), "xml")
            opf_path = PurePosixPath(container.find("rootfile")["full-path"])
            opf = bs4.BeautifulSoup(z.read(str(opf_path)), "xml")
            title = clean(opf.find("dc:title").get_text()) if opf.find("dc:title") else path.stem
            manifest = {item["id"]: item for item in opf.find_all("item")}
            pages = []
            for ref in opf.find("spine").find_all("itemref"):
                item = manifest.get(ref["idref"])
                if item is None or "html" not in item.get("media-type", "") or "nav" in (item.get("properties") or ""):
                    continue
                pages.append(z.read(str(opf_path.parent / item["href"])).decode("utf-8"))
        if is_traditional("".join(pages)):
            title, pages = to_simplified(title), [to_simplified(page) for page in pages]
        bodies = []
        for page in pages:
            soup = bs4.BeautifulSoup(page, "html.parser")
            if soup.body:
                bodies.append(soup.body)
        return title, bodies

    def parse_document(self, path: Path, title: Optional[str] = None) -> Tuple[str, str, List[str]]:
        """返回 (title, desc, content)。title 不传时取 epub 的标题，去掉「 (1998年)」「 (2001年8月)」这类版本后缀。"""
        epub_title, bodies = self.read(path)
        title = title or re.sub(r"\s*[（(]\d{4}年(?:\d{1,2}月)?[）)]$", "", epub_title)

        desc = ""
        content = []
        for body in bodies:
            # 封面、说明页跳过
            if not _is_content(body):
                continue
            for node in body.find_all(_BLOCKS):
                # 表格里的段落、标题由表格自己处理
                if node.find_parent("table") or _is_noise(node):
                    continue
                if node.name == "table":
                    if not desc and not content:
                        desc = _header_note(node)
                    elif content and "wikitable" in (node.get("class") or []):
                        content.extend(_table_lines(node))
                    continue
                line = _text(node)
                if not line:
                    continue
                if _END.match(line):
                    return title, desc, content
                content.append(line)
        return title, desc, content
