import logging
import re
from typing import List

from common import DATE_RE, INDENT_RE, NUMBER_RE, PREFACE_RE, clean, norm

logger = logging.getLogger(__name__)

HEADING_PREFIX = re.compile(rf"^(序言|第{NUMBER_RE}+(?:分编|编|章|节)|[A-Z]{{1,2}}章)")
DOC_NUMBER = re.compile(r"^(?:法释|高检发释字|法发|高检发)〔\d{4}〕\d+号$")
ARTICLE_PREFIX = re.compile(
    rf"^(第{NUMBER_RE}{{1,6}}[条章节篇](?:之{NUMBER_RE}{{1,2}})*)\s*")
TOC_SCAN_LINES = 60
ANNOUNCEMENT_SCAN_LINES = 40


def parse_desc(desc: str) -> List[str]:
    """把「（2020年…通过　根据2021年…修正）」拆成每行「日期 事件」。"""
    desc = clean(desc)
    desc = re.sub(r"^[（(]|[）)]$", "", desc).strip()
    ret = []
    for part in re.split(rf"\s*(?={DATE_RE})", desc):
        prev = None
        while prev != part:
            prev = part
            # 按日期切开后挂在末尾的「根据」「并经」「于」等连接词和标点
            part = re.sub(r"(?:[\s，,；;、。（(]|根据|并经|经|于|自)+$", "", part)
            # 只去掉没有配对的右括号，「（试行）」这类保留
            if part.endswith(("）", ")")) and part.count("）") + part.count(")") > part.count("（") + part.count("("):
                part = part[:-1]
        if not re.match(DATE_RE, part):
            continue
        date = re.match(DATE_RE, part).group(0)
        event = part[len(date):].strip()
        # 「起实施」「实施」「起执行」都按施行写，database.py 从「X年X月X日 施行」读生效日期
        event = re.sub(r"^(?:起施行|起?实施|起?执行)$", "施行", event.replace("起施行", "施行"))
        if not event:
            # 只有日期没有事件，如「（国家林业局令第2号 1999年4月22日）」拆开后的残留
            continue
        ret.append(norm(date) + " " + event)
    return ret


def _toc_key(line: str) -> str:
    """目录项和正文标题经常一边有「第一章」一边没有，比较时只看标题文字。"""
    text = HEADING_PREFIX.sub("", norm(line))
    return re.sub(r"[.…·\-—\d]+$", "", text)


def _is_toc_entry(line: str) -> bool:
    text = norm(line)
    return len(text) <= 60 and not re.search("[。；]", text) and not re.match(rf"^第{NUMBER_RE}+条", text)


def drop_toc(lines: List[str]) -> List[str]:
    """删掉从「目录」到正文起点之前的内容。找不到正文起点就不删。"""
    for i, line in enumerate(lines[:TOC_SCAN_LINES]):
        if not re.fullmatch("目录[：:]?", norm(line)):
            continue
        if i + 1 >= len(lines):
            return lines
        first = lines[i + 1]
        # 目录里只有短标题，碰到条文或句子说明已经进入正文
        rest = []
        for j in range(i + 2, len(lines)):
            if not _is_toc_entry(lines[j - 1]):
                break
            rest.append(j)
        # 1. 第一个目录项在正文里再次出现
        end = next((j for j in rest if _toc_key(first) and _toc_key(lines[j]) == _toc_key(first)), None)
        # 2. 目录项写在一行里或带页码时，按「第一章」「序言」这样的前缀找
        if end is None and (m := HEADING_PREFIX.match(norm(first))):
            end = next((j for j in rest if norm(lines[j]).startswith(m.group(1))), None)
        # 3. 第一条，紧挨着的章节标题不在目录里时属于正文
        if end is None:
            end = next((j for j in range(i + 1, len(lines)) if re.match(rf"^第[一1]条", norm(lines[j]))), None)
            if end is not None and end - 1 > i and _is_heading(lines[end - 1]):
                keys = {_toc_key(x) for x in lines[i + 1:end - 1]}
                if _toc_key(lines[end - 1]) not in keys:
                    end -= 1
        if end is None:
            logger.warning("找到目录但找不到正文起点，未删除目录")
            return lines
        return lines[:i] + lines[end:]
    return drop_unmarked_toc(lines)


def _is_heading(line: str) -> bool:
    text = norm(line)
    return bool(HEADING_PREFIX.match(text)) and len(text) <= 30 and not re.search("[，。；：]", text)


def drop_unmarked_toc(lines: List[str]) -> List[str]:
    """没有「目录」二字的目录：第一条之前同一个章节标题出现两次，中间全是标题行。"""
    first_article = next((j for j, line in enumerate(lines) if re.match(r"^第[一1]条", norm(line))), len(lines))
    for i in range(first_article):
        if not _is_heading(lines[i]):
            continue
        key = _toc_key(lines[i])
        for j in range(i + 1, first_article):
            if not _is_heading(lines[j]):
                break
            if _toc_key(lines[j]) == key:
                return lines[:i] + lines[j:]
        return lines
    return lines


def drop_announcement(lines: List[str]) -> List[str]:
    """司法解释开头的「公告…法释〔…〕号」。没有法释行时不删，避免丢掉正文。"""
    for i, line in enumerate(lines[:ANNOUNCEMENT_SCAN_LINES]):
        if not re.match(r"公\s*告", line):
            continue
        end = next((j for j in range(i + 1, len(lines)) if re.match("法释", lines[j])), None)
        if end is None:
            return lines
        return lines[:i] + lines[end + 1:]
    return lines


def normalize_heading(line: str) -> str:
    """「序　言」→「序言」，「第一章　总　　则」→「第一章 总则」。"""
    if not _is_heading(line):
        return line
    text = norm(line)
    m = HEADING_PREFIX.match(text)
    rest = text[len(m.group(1)):]
    return m.group(1) + (f" {rest}" if rest else "")


_HALF_PUNCT = {",": "，", ";": "；", ":": "："}
# 中文之间或句末的半角标点，原文偶有录错；数字之间的（如 10:30）不动
_HALF_PUNCT_RE = re.compile(r"(?<=[\u4e00-\u9fff）》”])[,;:](?=[\u4e00-\u9fff（《“]|$)")


def normalize_punctuation(line: str) -> str:
    if line.startswith(("|", "<!--")):
        return line
    # 列举项「(一)」统一为「（一）」
    line = re.sub(r"^\(([一二三四五六七八九十]+)\)", r"（\1）", line)
    return _HALF_PUNCT_RE.sub(lambda m: _HALF_PUNCT[m.group(0)], line)


def drop_distribution_table(lines: List[str]) -> List[str]:
    """公文末尾的版记表格（主送、抄送、印发）不是条文。"""
    if not lines or lines[-1] != "<!-- TABLE END -->" or "<!-- TABLE -->" not in lines:
        return lines
    start = len(lines) - 1 - lines[::-1].index("<!-- TABLE -->")
    table = "".join(lines[start:])
    if "印发" in table and ("主送" in table or "抄送" in table):
        return lines[:start]
    return lines


# 修改决定里「第二十二条改为第二十一条」「第五条中的“…”」不是条文，条号后不加空格
_AMENDMENT = re.compile(rf"^(?:改为|修改为|中的|中“|第{NUMBER_RE}+[款项目]|后增加|增加|作为|和第|、第|至第)")


def normalize_article(line: str) -> str:
    """「第一条　内容」→「第一条 内容」。"""
    m = ARTICLE_PREFIX.match(line)
    if m and _AMENDMENT.match(line[m.end():]):
        return line.strip()
    return ARTICLE_PREFIX.sub(lambda x: x.group(0).strip() + " ", line).strip()


def assign_headings(lines: List[str]) -> List[str]:
    """给编、章、节等标题行加上 Markdown 标题级别。

    层级看所在的上级标题：编下面直接是章时章为三级，编下面有分编时章为四级。
    """
    ret = []
    parents: List[int] = []
    for line in lines:
        if re.match(PREFACE_RE, line):
            parents = []
            ret.append(f"## {line}")
            continue
        rank = next((n for n, r in enumerate(INDENT_RE) if re.match(r, line)), None)
        if rank is None:
            ret.append(line)
            continue
        while parents and parents[-1] >= rank:
            parents.pop()
        ret.append(f"{'#' * (len(parents) + 2)} {line}")
        parents.append(rank)
    return ret


class ContentParser(object):

    def filter_content(self, title: str, content: List[str]) -> List[str]:
        lines = [line for line in map(clean, content) if line]
        # 正文开头重复的标题
        for i, line in enumerate(lines[:10]):
            if norm(line) == norm(title):
                del lines[i]
                break
            # 标题分成两段：「大同市人民代表大会常务委员会」「讨论决定重大事项的规定」
            if i + 1 < len(lines) and norm(line + lines[i + 1]) == norm(title):
                del lines[i:i + 2]
                break
        lines = drop_toc(lines)
        lines = drop_announcement(lines)
        lines = drop_distribution_table(lines)
        return [normalize_punctuation(normalize_article(normalize_heading(line))) for line in lines]

    def parse(self, title: str, desc, content: List[str]) -> List[str]:
        header = parse_desc(desc)
        content = self.filter_content(title, content)
        # 正文开头的文号放到头部信息末尾，和仓库里已有的司法解释一致
        while content and DOC_NUMBER.match(norm(content[0])):
            header.append(norm(content.pop(0)))
        if len(content) == 0:
            logger.warning(f"{title} has no content")
            return []

        return [f"# {clean(title)}", *header, "<!-- INFO END -->", *assign_headings(content)]
