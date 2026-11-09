"""从法规正文、名称里读出数据库要的信息：施行日期、废止和修改了哪些法规、实施的是哪部法律。都是纯函数。"""
import re
from pathlib import Path

from lawref.dates import SPACED_DATE_RE, iso_of
from lawref.document import INFO_END, body_of
from lawref.text import strip_prc


def content_flags(content: str) -> tuple[bool, bool]:
    """正文有没有目录、信息，返回 (has_toc, has_info)。

    规则必须和 App 的 LawContentParser 一致（App 的单元测试会核对）：逐行去掉首尾空白，跳过空行；
    - 第一个词正好是「#」的是标题，跳过（信息部分里也一样）
    - 「<!-- INFO END -->」结束信息部分
    - 「<!-- FORCE BREAK -->」「<!-- TABLE END -->」是标记，跳过
    - 信息部分里剩下的任何一行都算信息
    - 信息部分之后，第一个词以「#」开头（##、### …）的进目录
    没有「<!-- INFO END -->」的文件全文都算信息，目录为空。
    """
    is_desc = True
    has_toc = False
    has_info = False
    for line in content.split("\n"):
        text = line.strip()
        if not text:
            continue
        first = text.split(" ", 1)[0]
        if first == "#":
            continue
        if text.startswith(INFO_END):
            is_desc = False
            continue
        if text.startswith(("<!-- FORCE BREAK -->", "<!-- TABLE END -->")):
            continue
        if is_desc:
            has_info = True
            continue
        if first.startswith("#"):
            has_toc = True
    return has_toc, has_info


def get_law_level_by_folder(folder: Path) -> str:
    root_folder = folder.parts[0] if folder.parts else ""
    if root_folder in ("司法解释", "地方性法规", "宪法", "案例", "行政法规", "部门规章"):
        return root_folder
    return "法律"


# ---------- 生效日期 ----------

_HEADER_EFFECTIVE = re.compile(rf"^{SPACED_DATE_RE}\s*起?施行$")
_EFFECTIVE = re.compile(rf"自\s*{SPACED_DATE_RE}\s*起?施行|自(?:公布|发布)之日起施行")
# 施行条款的主语：本法、本条例、本规定、本补充安排……
_SUBJECT = re.compile(
    r"本[^\s，。；：、]{0,8}?(?:法|条例|规定|解释|办法|细则|决定|规则|意见|通知|批复|章程|准则|纲要|修正案|编|标准|答复|规范|纪要|制度|安排)")


def _to_date(m: re.Match, publish: str | None) -> str | None:
    if m.group(1):
        return iso_of(m)
    return publish  # 自公布之日起施行


def extract_valid_from(content: str, publish: str | None) -> str | None:
    """从正文找施行日期，找不到返回 None。

    依次看：头部的「2022年1月1日 施行」；正文里以「本法」「本规定」等开头的施行句，取最后一处；
    最后几段里的施行条款。不在全文里找「自公布之日起施行」，条文里叙述别的法规怎么施行时也会这样写。
    """
    head, _, body = content.partition(INFO_END)
    if not body:
        head, body = "", content

    found = None
    for line in head.splitlines():
        if m := _HEADER_EFFECTIVE.match(line.strip()):
            found = _to_date(m, publish)
    if found:
        return found

    for sentence in re.split(r"[。；\n]", body):
        m = _EFFECTIVE.search(sentence)
        if m and _SUBJECT.search(sentence[:m.start()]):
            found = _to_date(m, publish)
    if found:
        return found

    paragraphs = [line for line in body.splitlines() if line.strip() and not line.startswith(("#", "|", "<!--"))]
    matches = list(_EFFECTIVE.finditer("\n".join(paragraphs[-6:])))
    return _to_date(matches[-1], publish) if matches else None


def effective_date(content: str, publish: str | None) -> str | None:
    """生效日期。早于发布日期的是修订版沿用的原施行日期，这时取发布日期。"""
    found = extract_valid_from(content, publish)
    if publish and (not found or found < publish):
        return publish
    return found


def extract_abolished_law_names(content: str) -> list[str]:
    # 匹配紧邻「（同时）废止」之前、由、和，分隔的连续《...》法律名
    # 避免匹配「修改或者废止」「修订、废止」等无具体法律名的情形
    # 头部是本法自己的沿革，「2008年1月1日 《某法》废止、…本条例废止」不是本法废止某法
    _, sep, body = content.partition(INFO_END)
    text = body if sep else content
    found = []
    clause = re.compile(r"((?:《[^》]+》[、和，]?)+)(?:同时)?废止")
    for m in clause.finditer(text):
        found += re.findall(r"《([^》]+)》", m.group(1))
    # 「1991年…通过的《A》和1993年…发布的《B》同时废止」：名称之间隔着日期和机关，取这一句里的全部
    for m in re.finditer(r"([^。；\n]*)同时废止", text):
        # 「《…解释（一）》（法释〔2020〕26号）第三十二条第一款同时废止」只废止其中一款，不算；
        # 「《劳动保险条例》中有关女工人、女职员生育待遇的规定…同时废止」只废止其中一部分，也不算
        for name_m in re.finditer(r"《([^》]+)》([^《]*)", m.group(1)):
            rest = name_m.group(2)
            if not re.search(r"第[一二三四五六七八九十百千\d]+[条款项]", rest) and not re.match(r"\s*中", rest):
                found.append(name_m.group(1))
    # 刑法附件一：「…下列条例、补充规定和决定…予以废止：」之后逐条列出，名称不带书名号
    listing = False
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if re.search(r"废止[：:]$", line):
            listing = True
        elif listing and (item := _LIST_ITEM.match(line)):
            found.append(item.group(1).strip("《》。；; "))
        else:
            listing = False
    # 去除「中华人民共和国」前缀以匹配数据库中存储的法律名
    return list(dict.fromkeys(strip_prc(n) for n in found))



# 国务院废止行政法规的决定里的名单
# 「一、…」「（一）…」
_LIST_ITEM = re.compile(r"^(?:[一二三四五六七八九十百]+、|（[一二三四五六七八九十百]+）|\d+[.．、]\s*)(.+)$")
# 修改条目：「将《城市绿化条例》第十一条…」「删去《…》第三十四条」「《…》第五条修改为…」
_AMEND_ITEM = re.compile(r"^(?:将|删去|在|修改|对)?《([^》]+)》")
_ABOLISHES = re.compile(r"废止|失效")
# 修改附件的标题、总述：「附件1：国务院决定修改的行政法规」「对36部行政法规的部分条款予以修改」
_AMENDS = re.compile(r"修改的|予以修改|作出修改")
# 「二、废止《产品质量监督试行办法》（…）。」
_INLINE_ABOLISH = re.compile(r"^(?:予以)?废止((?:《[^》]+》[、和]?)+)")


def _section_title(line: str) -> bool:
    """附件、标题、「…以下行政法规：」这类开始一段的行。"""
    return (line.startswith(("附件", "#")) or line.endswith("：")
            or (len(line) <= 30 and line.endswith("行政法规")))


def extract_decision_abolished_names(content: str) -> list[str]:
    """国务院废止、宣布失效行政法规的决定里列出的法规名。"""
    return scan_decision(content)[0]


def decision_listed_date(content: str, name: str) -> str | None:
    """废止名单里这一项写的最后一个发布、修订日期，没有就是 None。

    「三、危险化学品安全管理条例（2002年1月26日…公布 根据2013年12月7日…第二次修订）」→ 2013-12-07；
    表格「| 59 | 广播电视设施保护条例 | 1987年4月24日国务院发布 | … | 被2000年11月5日…公布的《…》明令废止 |」
    只看名称后面那一栏 → 1987-04-24。比库里最新版本早，废止的是更早的同名版本。
    """
    dates = []  # 同一部法规的几个版本可能各占一行，取所有行里最晚的
    for line in body_of(content).splitlines():
        line = line.strip()
        if line.startswith("|"):
            cells = [_normalize_name(c.strip()) for c in line.strip("|").split("|")]
            if name not in cells or cells.index(name) + 1 >= len(cells):
                continue
            text = cells[cells.index(name) + 1]
        elif (item := _LIST_ITEM.match(line)) and _normalize_name(item.group(1)).startswith(name):
            # 一项占一行，名称后面的都是这一项的发布、修订记录
            text = _normalize_name(item.group(1))[len(name):]
        else:
            continue
        dates += [iso_of(m) for m in re.finditer(SPACED_DATE_RE, text)]
    return max(dates) if dates else None


def extract_decision_amended_names(content: str) -> list[str]:
    """国务院修改行政法规的决定里修改的法规名。"""
    return scan_decision(content)[1]


def scan_decision(content: str) -> tuple[list[str], list[str]]:
    """国务院修改、废止行政法规的决定 → (废止的法规名, 修改的法规名)。

    废止名单写法：「一、计划生育技术服务管理条例（2001年6月13日…公布）」，
    「| 1 | 铁路留用土地办法 | 1950年6月24日政务院公布 | … |」的表格，
    或者直接「二、废止《产品质量监督试行办法》（…）」。编号和表格只看讲废止、失效的那一段。
    其余段落里「一、将《城市绿化条例》第十一条…」「4. 删去《…》第三十四条」这样的条目是修改。
    """
    lines = [line.strip().lstrip("#").strip() for line in body_of(content).splitlines()]
    # 「一、对2部行政法规予以废止。（附件1）」：附件1 是废止名单，附件里可能没有标题
    abolish_attachments = {n for line in lines if _ABOLISHES.search(line)
                           for n in re.findall(r"附件\s*(\d+)", line)}
    names, amended, active, name_column = [], [], False, None
    for line in lines:
        if not line:
            continue
        item = _LIST_ITEM.match(line)
        if item and (m := _INLINE_ABOLISH.match(item.group(1))):
            names += re.findall(r"《([^》]+)》", m.group(1))
            continue
        if item and not active and (m := _AMEND_ITEM.match(item.group(1))):
            amended.append(m.group(1))
            continue
        # 「二、废止5件行政法规」这样的条目是一段的标题
        heading_item = item and re.match(r"(?:予以)?(?:废止|宣布失效)[0-9一二三四五六七八九十百]*[件部]", item.group(1))
        if heading_item or (not item and not line.startswith("|") and _section_title(line)):
            if m := re.fullmatch(r"附件\s*(\d*)[：:]?", line):
                # 「附件2」单独一行：看总述里它是不是废止名单，否则等下一行的标题
                active = m.group(1) in abolish_attachments
            else:
                active = bool(_ABOLISHES.search(line)) and not _AMENDS.search(line)
            name_column = None
            continue
        if not active:
            continue
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if name_column is None:
                name_column = next((i for i, c in enumerate(cells) if "名称" in c), None)
            elif name_column is not None and not set(line) <= set("|-") and name_column < len(cells):
                names.append(cells[name_column])
            continue
        if item:
            # 名称到第一个带年份的括号为止，「（试行）」这类保留
            names.append(re.split(r"（(?=[^（）]*\d{4}年)", item.group(1), maxsplit=1)[0].strip("《》"))
    def normalize(names: list[str]) -> list[str]:
        # 「〈中外合资…规定〉的补充规定」→ 库里的写法「《中外合资…规定》的补充规定」
        names = [_normalize_name(n.replace("〈", "《").replace("〉", "》")) for n in names if n]
        return list(dict.fromkeys(names))

    abolished = normalize(names)
    return abolished, [n for n in normalize(amended) if n not in abolished]


# 「最高人民法院关于适用《民法典》……的解释」「全国人民代表大会常务委员会关于《刑法》第三十条的解释」
_IMPLEMENTED_QUOTED = re.compile(r"(?:适用|实施|执行|贯彻|关于)《([^》]+)》")
# 「外商投资法实施条例」「专利法实施细则」
_IMPLEMENTED_SUFFIX = re.compile(r"^(.+?法)实施(?:条例|细则|办法)")


def _normalize_name(name: str) -> str:
    return strip_prc(name).replace("(", "（").replace(")", "）")


def extract_implemented_law_names(name: str) -> list[tuple[str, str]]:
    """从名称判断实施或解释的是哪部法律，返回 (法律名, 书名号后面的文字)。修改、印发、转发、废止某文件的不算。"""
    ret = []
    for m in _IMPLEMENTED_QUOTED.finditer(name):
        if name[:m.start()].endswith(("修改", "印发", "转发", "废止")):
            continue
        ret.append((_normalize_name(m.group(1)), name[m.end():]))
    if not ret and (m := _IMPLEMENTED_SUFFIX.match(name)):
        ret.append((_normalize_name(m.group(1)), ""))
    return ret


# 第一条的立法依据：「根据《中华人民共和国统计法》及其实施细则…，制定本办法。」
_BASIS = re.compile(r"(?:根据|依据|依照)(.*?)制定本")
# 立法依据能指向的层级，以及可以写立法依据的层级
BASIS_TARGET_LEVELS = {
    "部门规章": ("法律", "行政法规"),
    "行政法规": ("法律",),
    "地方性法规": ("法律", "行政法规"),
}


def extract_basis_law_names(content: str) -> list[str]:
    """第一条写明的立法依据里的法规名，去重、保持顺序。"""
    first = next((line for line in body_of(content).splitlines() if line.startswith("第一条")), "")
    m = _BASIS.search(first)
    if not m:
        return []
    names = (_normalize_name(n) for n in re.findall(r"《([^》]+)》", m.group(1)))
    return list(dict.fromkeys(names))
