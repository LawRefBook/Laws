"""让 db.sqlite3 与仓库里的法规文件保持一致。

    python3 database.py update <db.sqlite3>   # 入库、同步目录、计算生效和失效日期
    python3 database.py drop <db.sqlite3>     # 清空重建，会重新生成全部 ID
    python3 database.py check <db.sqlite3>    # 发布前校验，有问题时退出码为 1

update 在一个事务里完成，中途出错不会留下改了一半的数据。
"""
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union
from uuid import uuid4

import peewee

database = peewee.SqliteDatabase(None)  # Defer initialization

FOREVER = "2099-12-31"
# 已失效、但不知道哪天失效的手工标记，update 不改动
UNKNOWN_EXPIRY = "1970-01-01"
SKIP_FILES = {"README.md", "法律法规模版.md"}
DATED_FILE = re.compile(r"\((\d{4}-\d{2}-\d{2})\)$")


class DateText(peewee.TextField):
    """日期列，按 'YYYY-MM-DD' 字符串读写，比较时不经过 datetime。"""
    field_type = "DATE"


class BaseModel(peewee.Model):
    class Meta:
        database = database


class Category(BaseModel):
    id = peewee.UUIDField(primary_key=True, default=uuid4)
    name = peewee.TextField()
    folder = peewee.TextField()
    isSubFolder = peewee.BooleanField(default=False)
    group = peewee.TextField(null=True)
    order = peewee.IntegerField(null=True)

    def __repr__(self) -> str:
        return f"<Category {self.name}>"

    __str__ = __repr__

    @staticmethod
    def get_or_create_category(folder: Path) -> "Category":
        try:
            return Category.get(folder=str(folder))
        except Category.DoesNotExist:
            pass
        return Category.create(name=folder.parts[-1], folder=str(folder))


class Law(BaseModel):
    id = peewee.UUIDField(primary_key=True, default=uuid4)
    level = peewee.TextField()
    name = peewee.TextField(index=True)
    subtitle = peewee.TextField(null=True)

    filename = peewee.TextField(null=True)
    publish = DateText(null=True)
    valid_from = DateText(null=True)
    valid_to = DateText(null=False, default=FOREVER)
    order = peewee.IntegerField(null=True)
    ver = peewee.IntegerField(null=False, default=0)

    tags = peewee.TextField(null=True)

    category_id = peewee.UUIDField(null=False)

    def __repr__(self) -> str:
        return f"<Law {self.name} {self.publish}>"

    __str__ = __repr__

    def stems(self) -> List[str]:
        """与 App 的 TLaw.getNames 一致：filename 或 name(publish)，再退到 name、subtitle。"""
        first = self.filename or (f"{self.name}({self.publish})" if self.publish else self.name)
        return list(dict.fromkeys(filter(None, (first, self.name, self.subtitle))))


class Relationship(BaseModel):
    """法规之间的关系，source 对 target，每次 update 重新生成。

    supersedes  同一部法规的新版本取代旧版本（同名修订）
    abolishes   另一部法规写明「《某法》同时废止」
    amends      国务院修改行政法规的决定修改了 target，target 是修改前的版本
    implements  source 是 target 的实施条例、实施细则或解释，按名称判断；
                部门规章、行政法规、地方性法规还看第一条「根据《某法》…制定本办法」写明的立法依据
    date 是 target 失效的日期；amends 是决定施行的日期；implements 为空。

    DLC 数据库里 implements 的 target 可以是本体数据库的法规（如「北京市实施《义务教育法》办法」
    指向本体的义务教育法），target_id 是本体里的 ID，在 DLC 数据库里查不到。
    """
    SUPERSEDES = "supersedes"
    ABOLISHES = "abolishes"
    IMPLEMENTS = "implements"
    AMENDS = "amends"
    TYPES = (SUPERSEDES, ABOLISHES, AMENDS, IMPLEMENTS)

    source_id = peewee.UUIDField(index=True)
    target_id = peewee.UUIDField(index=True)
    type = peewee.TextField()
    date = DateText(null=True)

    class Meta:
        indexes = ((("source_id", "target_id", "type"), True),)

    def __repr__(self) -> str:
        return f"<Relationship {self.source_id} {self.type} {self.target_id}>"

    __str__ = __repr__

    @staticmethod
    def relate(source: "Law", target: "Law", type: str, date: Optional[str] = None):
        Relationship.insert(source_id=source.id, target_id=target.id, type=type, date=date).on_conflict_ignore().execute()


# 部门规章目录的顺序：国家规章库的部门列表（国务院机构序列），目录名按仓库里的写法
DEPARTMENT_ORDER = [
    "外交部", "国家发展和改革委员会", "教育部", "科学技术部", "工业和信息化部", "国家民族事务委员会",
    "公安部", "国家安全部", "民政部", "司法部", "财政部", "人力资源社会保障部", "自然资源部", "生态环境部",
    "住房和城乡建设部", "交通运输部", "水利部", "农业农村部", "商务部", "文化和旅游部", "国家卫生健康委员会",
    "退役军人事务部", "应急管理部", "中国人民银行", "审计署", "国务院国有资产监督管理委员会", "海关总署",
    "国家税务总局", "市场监督管理总局", "国家金融监督管理总局", "中国银行保险监督管理委员会",
    "中国证券监督管理委员会", "国家广播电视总局", "国家体育总局", "国家统计局", "国家知识产权局",
    "国家国际发展合作署", "国家医疗保障局", "国家机关事务管理局", "国家新闻出版署", "国家版权局",
    "国家宗教事务局", "国家互联网信息办公室", "中国气象局", "国家国防科技工业局", "国家林业和草原局",
    "国家档案局", "国家保密局", "国家密码管理局", "国家电影局", "中国地震局",
]
DEPARTMENT_ORDER_START = 500
DEPARTMENT_ORDER_UNKNOWN = 599


def get_law_level_by_folder(folder: Path) -> str:
    root_folder = folder.parts[0] if folder.parts else ""
    if root_folder in ("司法解释", "地方性法规", "宪法", "案例", "行政法规", "部门规章"):
        return root_folder
    return "法律"


# ---------- 生效日期 ----------

_DATE = r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"
_HEADER_EFFECTIVE = re.compile(rf"^{_DATE}\s*起?施行$")
_EFFECTIVE = re.compile(rf"自\s*{_DATE}\s*起?施行|自(?:公布|发布)之日起施行")
# 施行条款的主语：本法、本条例、本规定、本补充安排……
_SUBJECT = re.compile(
    r"本[^\s，。；：、]{0,8}?(?:法|条例|规定|解释|办法|细则|决定|规则|意见|通知|批复|章程|准则|纲要|修正案|编|标准|答复|规范|纪要|制度|安排)")


def _to_date(m: re.Match, publish: Optional[str]) -> Optional[str]:
    if m.group(1):
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return publish  # 自公布之日起施行


def extract_valid_from(content: str, publish: Optional[str]) -> Optional[str]:
    """从正文找施行日期，找不到返回 None。

    依次看：头部的「2022年1月1日 施行」；正文里以「本法」「本规定」等开头的施行句，取最后一处；
    最后几段里的施行条款。不在全文里找「自公布之日起施行」，条文里叙述别的法规怎么施行时也会这样写。
    """
    head, _, body = content.partition("<!-- INFO END -->")
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


def effective_date(content: str, publish: Optional[str]) -> Optional[str]:
    """生效日期。早于发布日期的是修订版沿用的原施行日期，这时取发布日期。"""
    found = extract_valid_from(content, publish)
    if publish and (not found or found < publish):
        return publish
    return found


def extract_abolished_law_names(content: str) -> List[str]:
    # 匹配紧邻「（同时）废止」之前、由、和，分隔的连续《...》法律名
    # 避免匹配「修改或者废止」「修订、废止」等无具体法律名的情形
    # 头部是本法自己的沿革，「2008年1月1日 《某法》废止、…本条例废止」不是本法废止某法
    _, sep, body = content.partition("<!-- INFO END -->")
    text = body if sep else content
    found = []
    clause = re.compile(r"((?:《[^》]+》[、和，]?)+)(?:同时)?废止")
    for m in clause.finditer(text):
        found += re.findall(r"《([^》]+)》", m.group(1))
    # 「1991年…通过的《A》和1993年…发布的《B》同时废止」：名称之间隔着日期和机关，取这一句里的全部
    for m in re.finditer(r"([^。；\n]*)同时废止", text):
        # 「《…解释（一）》（法释〔2020〕26号）第三十二条第一款同时废止」只废止其中一款，不算
        for name_m in re.finditer(r"《([^》]+)》([^《]*)", m.group(1)):
            if not re.search(r"第[一二三四五六七八九十百千\d]+[条款项]", name_m.group(2)):
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
    return list(dict.fromkeys(re.sub(r"^中华人民共和国", "", n) for n in found))



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


def extract_decision_abolished_names(content: str) -> List[str]:
    """国务院废止、宣布失效行政法规的决定里列出的法规名。"""
    return scan_decision(content)[0]


def extract_decision_amended_names(content: str) -> List[str]:
    """国务院修改行政法规的决定里修改的法规名。"""
    return scan_decision(content)[1]


def scan_decision(content: str) -> Tuple[List[str], List[str]]:
    """国务院修改、废止行政法规的决定 → (废止的法规名, 修改的法规名)。

    废止名单写法：「一、计划生育技术服务管理条例（2001年6月13日…公布）」，
    「| 1 | 铁路留用土地办法 | 1950年6月24日政务院公布 | … |」的表格，
    或者直接「二、废止《产品质量监督试行办法》（…）」。编号和表格只看讲废止、失效的那一段。
    其余段落里「一、将《城市绿化条例》第十一条…」「4. 删去《…》第三十四条」这样的条目是修改。
    """
    _, _, body = content.partition("<!-- INFO END -->")
    lines = [line.strip().lstrip("#").strip() for line in (body or content).splitlines()]
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
    def normalize(names: List[str]) -> List[str]:
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
    return re.sub(r"^中华人民共和国", "", name).replace("(", "（").replace(")", "）")


def extract_implemented_law_names(name: str) -> List[Tuple[str, str]]:
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


def extract_basis_law_names(content: str) -> List[str]:
    """第一条写明的立法依据里的法规名，去重、保持顺序。"""
    _, _, body = content.partition("<!-- INFO END -->")
    first = next((line for line in (body or content).splitlines() if line.startswith("第一条")), "")
    m = _BASIS.search(first)
    if not m:
        return []
    names = (_normalize_name(n) for n in re.findall(r"《([^》]+)》", m.group(1)))
    return list(dict.fromkeys(names))


# ---------- 数据库 ----------

class Database(object):
    def __init__(self, sqlite_file: Path, readonly: bool = False) -> None:
        self.tables = [Category, Law, Relationship]
        self.sqlite_file = sqlite_file.resolve()
        self.db = database
        if readonly:
            # 只读打开，不补表，check 不会改动数据库文件
            self.db.init(f"{self.sqlite_file.as_uri()}?mode=ro", uri=True)
        else:
            self.db.init(str(self.sqlite_file))
            self.prepare()

    def prepare(self):
        if self.sqlite_file.exists():
            assert self.sqlite_file.is_file()
        else:
            assert self.sqlite_file.name == "db.sqlite3"
        # 已有的表不动，旧数据库会补上新加的表
        self.db.create_tables(self.tables)

    def reset(self):
        print("清空后所有法规会重新生成 ID，App 里用户的收藏、搜索记录都会失效。")
        yes = False
        for _ in range(0, 3):
            yes = input("Are you sure to reset database? [y/N]").lower() == "y"
            if not yes:
                break
        if yes:
            self.db.drop_tables(self.tables)
            self.db.create_tables(self.tables)

    @property
    def lookup_path(self) -> Path:
        return self.sqlite_file.parent

    @property
    def base_sqlite_file(self) -> Optional[Path]:
        """DLC（<仓库>/DLC/<名称>/db.sqlite3）对应的本体数据库，本体自己返回 None。"""
        parts = self.sqlite_file.parts
        if "DLC" not in parts[:-1]:
            return None
        root = Path(*parts[:len(parts) - 1 - parts[::-1].index("DLC")])
        return root / "db.sqlite3"

    def base_laws(self) -> Tuple[List["Law"], Dict]:
        """本体数据库里的法规和目录，只读，作为 DLC 里实施关系的 target。不入 DLC 数据库。"""
        base = self.base_sqlite_file
        if base is None:
            return [], {}
        if not base.exists():
            print(f"⚠️ 找不到本体数据库 {base}，DLC 只在自己内部查找实施关系")
            return [], {}
        conn = sqlite3.connect(f"{base.as_uri()}?mode=ro", uri=True)
        try:
            categories = {c.id: c for c in (
                Category(id=id, name=name, folder=folder)
                for id, name, folder in conn.execute('SELECT id, name, folder FROM category'))}
            laws = [Law(id=id, name=name, level=level, publish=publish, valid_from=valid_from,
                        order=order, category_id=category_id)
                    for id, name, level, publish, valid_from, order, category_id in conn.execute(
                        'SELECT id, name, level, publish, valid_from, "order", category_id FROM law')]
        finally:
            conn.close()
        return laws, categories

    # ---------- 文件 ----------

    def load_ignore_rules(self) -> List[Union[str, re.Pattern]]:
        """.lawignore：以 ^ 开头的是正则，匹配相对路径；其余是目录名。"""
        ignore_file = self.lookup_path / ".lawignore"
        if not ignore_file.exists():
            return []
        rules: List[Union[str, re.Pattern]] = []
        for line in ignore_file.read_text().splitlines():
            line = line.strip()
            if line:
                rules.append(re.compile(line) if line.startswith("^") else line)
        return rules

    def law_files(self) -> List[Path]:
        rules = self.load_ignore_rules()
        files = []
        for f in self.lookup_path.rglob("*.md"):
            rel = f.relative_to(self.lookup_path)
            if f.name in SKIP_FILES or f.name.startswith("_"):
                continue
            if any(rel.parts[0] == r if isinstance(r, str) else any(r.match(p) for p in rel.parts) for r in rules):
                continue
            files.append(f)
        return sorted(files)

    def resolve(self, law: Law, categories: Dict) -> Optional[Path]:
        """记录对应的文件，找不到返回 None。"""
        category = categories.get(law.category_id)
        if category is None:
            return None
        for stem in law.stems():
            path = self.lookup_path / category.folder / f"{stem}.md"
            if path.exists():
                return path
        return None

    def resolved_laws(self) -> List[Tuple[Law, Path]]:
        categories = {c.id: c for c in Category.select()}
        ret = []
        for law in Law.select():
            if path := self.resolve(law, categories):
                ret.append((law, path))
        return ret

    # ---------- check ----------

    # 只有 implements 可以指向本体数据库，这些关系的 target 必须在本库里
    LOCAL_TARGET_TYPES = (Relationship.AMENDS, Relationship.ABOLISHES)

    def check(self) -> List[str]:
        """发布前的校验，返回问题列表。"""
        if not Relationship.table_exists():
            return []
        names = {law.id: law.name for law in Law.select(Law.id, Law.name)}
        return [f"{r.type}：{names.get(r.source_id, r.source_id)} → target {r.target_id.hex} 不在本库里"
                for r in Relationship.select().where(Relationship.type.in_(self.LOCAL_TARGET_TYPES))
                if r.target_id not in names]

    # ---------- update ----------

    def update_database(self) -> Dict[str, int]:
        with self.db.atomic():
            Relationship.delete().execute()
            count = self.sync_files()
            count["versions"] = self.update_versions()
            self.update_category()
            self.update_department_categories()
            count["invalidated"] = self.invalidate_laws()
            count["restored"] = self.restore_unexplained_expiry()
            self.update_amendments()
            self.update_implementations()
            for type in Relationship.TYPES:
                count[type] = Relationship.select().where(Relationship.type == type).count()
        return count

    def sync_files(self) -> Dict[str, int]:
        """新文件入库；文件移动后同步目录和层级；报告找不到文件的记录。"""
        categories = {c.id: c for c in Category.select()}
        laws = list(Law.select())
        count = {"laws": len(laws), "created": 0, "moved": 0, "updated": 0, "missing": 0, "unindexed": 0}

        claimed: Dict[Path, Law] = {}
        missing: List[Law] = []
        for law in laws:
            path = self.resolve(law, categories)
            if path is None:
                missing.append(law)
                continue
            if path in claimed:
                print(f"⚠️ {law} 与 {claimed[path]} 指向同一个文件 {path.relative_to(self.lookup_path)}")
                continue
            claimed[path] = law
            # 文件名没有日期的（民法典、刑法、案例等）是手工入库的，层级也是手工设的
            if not DATED_FILE.search(path.stem):
                continue
            level = get_law_level_by_folder(path.parent.relative_to(self.lookup_path))
            if law.level != level:
                law.level = level
                law.save()
                count["updated"] += 1

        for path in self.law_files():
            if path in claimed:
                continue
            rel = path.relative_to(self.lookup_path)
            m = DATED_FILE.search(path.stem)
            if not m:
                print(f"⚠️ 文件名没有日期，没有入库：{rel}")
                count["unindexed"] += 1
                continue
            name, publish = path.stem[:m.start()], m.group(1)
            folder = rel.parent
            category = Category.get_or_create_category(folder)
            level = get_law_level_by_folder(folder)

            same = [law for law in missing if law.name == name and law.publish == publish]
            if len(same) == 1:
                law = same[0]
                missing.remove(law)
                law.category_id = category.id
                law.level = level
                law.save()
                count["moved"] += 1
                print(f"↪️ {law} 移到了 {folder}")
                continue
            if any(law.name == name and law.publish == publish for law in claimed.values()):
                print(f"⚠️ 与已有记录同名同日期，没有入库：{rel}")
                count["unindexed"] += 1
                continue
            claimed[path] = Law.create(name=name, publish=publish, category_id=category.id, level=level)
            count["created"] += 1

        for law in missing:
            print(f"⚠️ 找不到文件：{law}（{categories[law.category_id].folder if law.category_id in categories else '目录不存在'}）")
        count["missing"] = len(missing)
        return count

    def update_versions(self) -> int:
        """所有法规写入生效日期；同名多个版本时，上一版本在下一版本生效时失效。"""
        categories = {c.id: c for c in Category.select()}
        changed = set()
        groups = defaultdict(list)
        for law in Law.select():
            groups[law.name].append(law)
            if path := self.resolve(law, categories):
                valid_from = effective_date(path.read_text(encoding="utf-8"), law.publish)
                # 已有的值多数来自法规库的施行日期，修正版的施行日期往往不在正文里，所以保留。
                # 只补空值，以及更正「取了发布日期、正文却写明更晚施行」的旧结果。
                stale = bool(law.publish and law.valid_from == law.publish and valid_from and valid_from > law.publish)
                if valid_from and (law.valid_from is None or stale):
                    law.valid_from = valid_from
                    changed.add(law)

        for name, laws in groups.items():
            for law in laws:
                if law.ver != len(laws):
                    law.ver = len(laws)
                    changed.add(law)
            if len(laws) < 2:
                continue
            if len({law.level for law in laws}) > 1:
                print(f"Warning: laws with multiple versions but different levels: {name}")
                continue
            if any(law.publish is None for law in laws):
                print(f"Warning: laws with multiple versions but some has no publish date: {name}")
                continue
            laws.sort(key=lambda x: x.publish)
            for previous, law in zip(laws, laws[1:]):
                Relationship.relate(law, previous, Relationship.SUPERSEDES, law.valid_from)
                if law.valid_from and previous.valid_to != law.valid_from:
                    previous.valid_to = law.valid_from
                    changed.add(previous)
                    print(f"✅ {previous} 失效于 {law.valid_from}")

        for law in changed:
            law.save()
        return len(changed)

    def update_category(self):
        # if it's dlc, the filepath is ./DLC*/
        # then it should only has 1 category
        # and make sure the subfolder is True
        isDLC = "DLC" in self.sqlite_file.parts
        if not isDLC:
            return
        categories = Category.select()
        assert len(categories) == 1
        category = categories[0]

        changed = False

        if not category.isSubFolder:
            print("Setting subfolder to True")
            category.isSubFolder = True
            changed = True

        if not category.group:
            print("Setting group to 地方法规")
            category.group = "地方法规"
            changed = True

        if changed:
            category.save()

    def update_department_categories(self):
        """部门规章下每个部门一个目录，按 DEPARTMENT_ORDER 排序，不在列表里的排在最后。"""
        for category in Category.select().where(Category.folder.startswith("部门规章/")):
            department = category.folder.split("/")[1]
            order = DEPARTMENT_ORDER_START + DEPARTMENT_ORDER.index(department) \
                if department in DEPARTMENT_ORDER else DEPARTMENT_ORDER_UNKNOWN
            changed = category.order != order or category.group != "部门规章" or not category.isSubFolder
            if changed:
                category.order, category.group, category.isSubFolder = order, "部门规章", True
                category.save()

    def update_amendments(self):
        """修改法规的决定 → 被修改的法规。

        指向决定施行前已发布的最新版本，也就是修改前的那一版；库里只收了之后的版本时，指向最早的那一版。
        """
        by_name = defaultdict(list)
        for law in Law.select():
            by_name[law.name].append(law)
        for law, path in self.resolved_laws():
            if "决定" not in law.name or "修改" not in law.name:
                continue
            date = law.valid_from or law.publish
            # 修改后的新版本常和决定同一天发布、晚几天施行，所以按决定的发布日期找修改前的版本
            published = law.publish or date
            for name in extract_decision_amended_names(path.read_text(encoding="utf-8")):
                versions = sorted(by_name.get(name, []), key=lambda v: v.publish or "")
                before = [v for v in versions if v.publish and published and v.publish < published]
                target = before[-1] if before else (versions[0] if versions else None)
                if target and target.id != law.id:
                    Relationship.relate(law, target, Relationship.AMENDS, date)

    def restore_unexplained_expiry(self) -> int:
        """失效日期没有依据的恢复成长期有效。

        失效日期由版本链（supersedes）和废止条款（abolishes）决定。文件改名、拆开同名法规之后，
        原来的依据没了，旧的失效日期却还留着；这里在关系重建后把它们改回来。1970-01-01 是手工标记，不动。
        """
        explained = Relationship.select(Relationship.target_id).where(
            Relationship.type.in_([Relationship.SUPERSEDES, Relationship.ABOLISHES]))
        count = 0
        for law in Law.select().where(Law.valid_to.not_in([FOREVER, UNKNOWN_EXPIRY]), Law.id.not_in(explained)):
            print(f"↩️ {law} 失效于 {law.valid_to} 没有依据，恢复为长期有效")
            law.valid_to = FOREVER
            law.save()
            count += 1
        return count

    def invalidate_laws(self) -> int:
        """正文写明「《某法》同时废止」的，某法最后一个版本在本法生效时失效。案例只是引述，不算。

        新法的后续版本往往保留「《某法》同时废止」，几部法规都写了的，取最早生效的那一部。
        """
        count = 0
        # 被废止的版本 id → (生效日期, 废止它的法规, 被废止的版本)
        earliest: Dict = {}
        for law, path in self.resolved_laws():
            if law.level == "案例":
                continue
            content = path.read_text(encoding="utf-8")
            # 国务院的废止决定列名单，其余法规写「《某法》同时废止」
            if "决定" in law.name:
                abolished_names = extract_decision_abolished_names(content) or extract_abolished_law_names(content)
            else:
                abolished_names = extract_abolished_law_names(content)
            valid_from = law.valid_from or law.publish
            if not abolished_names or not valid_from:
                continue
            for name in abolished_names:
                # 同名版本之间的失效衔接由 update_versions 处理，此处只处理跨法律废止
                if name == law.name:
                    continue
                versions = sorted(Law.select().where(Law.name == name), key=lambda x: x.publish or "")
                if not versions:
                    continue
                last = versions[-1]
                # 仅当该版本在废止生效日期之前已发布时才失效；
                # 否则多为同名但实为另一部法律（如旧《国家安全法》→《反间谍法》）
                if last.publish and last.publish >= valid_from:
                    continue
                if last.id not in earliest or valid_from < earliest[last.id][0]:
                    earliest[last.id] = (valid_from, law, last)
        for valid_from, law, last in earliest.values():
            Relationship.relate(law, last, Relationship.ABOLISHES, valid_from)
            if last.valid_to != valid_from:
                last.valid_to = valid_from
                last.save()
                print(f"✅ {last} 因《{law.name}》废止于 {valid_from}")
                count += 1
        return count


    def update_implementations(self):
        """实施条例、司法解释、法律解释指向它实施或解释的法律。

        同名多个版本时取本文件生效时已发布的最新版本，都晚于本文件的取最早的版本。
        民法典这类按编拆开的，名称里写了哪一编就指向那一编，否则指向第一编。
        DLC 还会在本体数据库里找 target，source 只来自自己。
        """
        base_laws, base_categories = self.base_laws()
        categories = {**base_categories, **{c.id: c for c in Category.select()}}
        by_name = defaultdict(list)
        parts = defaultdict(list)
        for law in [*Law.select(), *base_laws]:
            by_name[law.name].append(law)
            category = categories.get(law.category_id)
            if category and law.name.startswith(f"{category.name} "):
                parts[category.name].append(law)
        for laws in by_name.values():
            laws.sort(key=lambda x: x.publish or "")
        for laws in parts.values():
            laws.sort(key=lambda x: x.order if x.order is not None else 1 << 30)

        def version_at(name: str, date: Optional[str]) -> "Law":
            versions = by_name[name]
            published = [v for v in versions if date and v.publish and v.publish <= date]
            return published[-1] if published else versions[0]

        def relate(law: "Law", target: "Law"):
            if target.id != law.id and target.name != law.name:
                Relationship.relate(law, target, Relationship.IMPLEMENTS)

        for law in Law.select().where(Law.level != "案例"):
            date = law.valid_from or law.publish
            for name, rest in extract_implemented_law_names(law.name):
                if name in by_name:
                    relate(law, version_at(name, date))
                elif name in parts:
                    named = [p for p in parts[name] if rest.startswith(p.name[len(name) + 1:].removesuffix("编"))]
                    relate(law, (named or parts[name])[0])

        # 部门规章、行政法规第一条写明的立法依据
        for law, path in self.resolved_laws():
            levels = BASIS_TARGET_LEVELS.get(law.level)
            if not levels:
                continue
            date = law.valid_from or law.publish
            for name in extract_basis_law_names(path.read_text(encoding="utf-8")):
                if name in by_name and by_name[name][-1].level in levels:
                    relate(law, version_at(name, date))
                elif name in parts and parts[name][0].level in levels:
                    relate(law, parts[name][0])


def main():
    args = sys.argv[1:]
    if len(args) != 2:
        print("Usage: python3 database.py <update|drop|check> <sqlite_file>")
        return 1
    command = args[0]
    if command == "check" and not Path(args[1]).is_file():
        print(f"找不到数据库 {args[1]}")
        return 1
    db = Database(Path(args[1]), readonly=command == "check")

    if command == "check":
        problems = db.check()
        for problem in problems:
            print(f"❌ {problem}")
        return 1 if problems else 0

    if command == "drop":
        db.reset()
        return 0

    if command == "update":
        count = db.update_database()
        print(f"Total: {count['laws']}")
        print(f"Created: {count['created']}")
        print(f"Moved: {count['moved']}")
        print(f"Level updated: {count['updated']}")
        print(f"Versions/dates updated: {count['versions']}")
        print(f"Invalidated: {count['invalidated']}")
        print(f"Expiry restored: {count['restored']}")
        print("Relationships: " + ", ".join(f"{type} {count[type]}" for type in Relationship.TYPES))
        print(f"Missing file: {count['missing']}")
        print(f"File not indexed: {count['unindexed']}")
        return 0

    print("Unknown command")
    return 1


if __name__ == "__main__":
    sys.exit(main())
