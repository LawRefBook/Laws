"""`laws db update`：让数据库与法规文件保持一致，每一步一个函数，update 在一个事务里依次执行。"""
import itertools
from collections import Counter, defaultdict
from pathlib import Path

from lawref.db.analysis import (
    BASIS_TARGET_LEVELS,
    content_flags,
    decision_listed_date,
    effective_date,
    extract_abolished_law_names,
    extract_basis_law_names,
    extract_decision_abolished_names,
    extract_decision_amended_names,
    extract_implemented_law_names,
    get_law_level_by_folder,
)
from lawref.db.models import FOREVER, UNKNOWN_EXPIRY, Category, Law, LawFlag, Relationship
from lawref.db.store import Database
from lawref.document import split_stem

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


def update(db: Database) -> dict[str, int]:
    """依次执行各步，返回各项计数。关系每次重建；中途出错整个回滚。"""
    with db.db.atomic():
        Relationship.delete().execute()
        count = sync_files(db)
        count["versions"] = update_versions(db)
        update_dlc_category(db)
        update_department_categories(db)
        count["invalidated"] = invalidate_laws(db)
        count["restored"] = restore_unexplained_expiry(db)
        update_amendments(db)
        update_implementations(db)
        # 用到上面生成的关系，放在最后
        count["flags"] = update_flags(db)
        for type in Relationship.TYPES:
            count[type] = Relationship.select().where(Relationship.type == type).count()
    return count


def sync_files(db: Database) -> dict[str, int]:
    """新文件入库；文件移动后同步目录和层级；报告找不到文件的记录。"""
    categories = {c.id: c for c in Category.select()}
    laws = list(Law.select())
    count = {"laws": len(laws), "created": 0, "moved": 0, "updated": 0, "missing": 0, "unindexed": 0}

    claimed: dict[Path, Law] = {}
    missing: list[Law] = []
    for law in laws:
        path = db.resolve(law, categories)
        if path is None:
            missing.append(law)
            continue
        if path in claimed:
            print(f"⚠️ {law} 与 {claimed[path]} 指向同一个文件 {path.relative_to(db.lookup_path)}")
            continue
        claimed[path] = law
        # 文件名没有日期的（民法典、刑法、案例等）是手工入库的，层级也是手工设的
        if split_stem(path.stem)[1] is None:
            continue
        level = get_law_level_by_folder(path.parent.relative_to(db.lookup_path))
        if law.level != level:
            law.level = level
            law.save()
            count["updated"] += 1

    for path in db.law_files():
        if path in claimed:
            continue
        rel = path.relative_to(db.lookup_path)
        name, publish = split_stem(path.stem)
        if publish is None:
            print(f"⚠️ 文件名没有日期，没有入库：{rel}")
            count["unindexed"] += 1
            continue
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


def update_flags(db: Database) -> int:
    """按修订关系和文件写入 law.flags，返回改动的条数。

    历史按修订链算（同一部法规的各个版本相同），和 App 的判断一致：
    修订链由 supersedes 连起来，链的根是最早的版本。
    """
    laws = list(Law.select())

    previous = {r.source_id: r.target_id
                for r in Relationship.select().where(Relationship.type == Relationship.SUPERSEDES)}

    def root(id):
        seen = {id}
        # 数据有环时停在环上
        while id in previous and previous[id] not in seen:
            id = previous[id]
            seen.add(id)
        return id

    roots = {law.id: root(law.id) for law in laws}
    chain_size = Counter(roots.values())

    files = {law.id: path for law, path in db.resolved_laws()}
    changed = 0
    for law in laws:
        flags = LawFlag(0)
        if chain_size[roots[law.id]] > 1:
            flags |= LawFlag.HISTORY
        if path := files.get(law.id):
            has_toc, has_info = content_flags(path.read_text(encoding="utf-8"))
            if has_toc:
                flags |= LawFlag.TOC
            if has_info:
                flags |= LawFlag.INFO
        if law.flags != flags:
            law.flags = int(flags)
            law.save()
            changed += 1
    return changed


def update_versions(db: Database) -> int:
    """所有法规写入生效日期；同名多个版本时，上一版本在下一版本生效时失效。"""
    categories = {c.id: c for c in Category.select()}
    changed = set()
    groups = defaultdict(list)
    for law in Law.select():
        groups[law.name].append(law)
        if path := db.resolve(law, categories):
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
        for previous, law in itertools.pairwise(laws):
            Relationship.relate(law, previous, Relationship.SUPERSEDES, law.valid_from)
            if law.valid_from and previous.valid_to != law.valid_from:
                previous.valid_to = law.valid_from
                changed.add(previous)
                print(f"✅ {previous} 失效于 {law.valid_from}")

    for law in changed:
        law.save()
    return len(changed)


def update_dlc_category(db: Database):
    """DLC 只有一个目录，在 App 里作为「地方法规」分组下的子目录显示。"""
    if not db.is_dlc:
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


def update_department_categories(db: Database):
    """部门规章下每个部门一个目录，按 DEPARTMENT_ORDER 排序，不在列表里的排在最后。"""
    for category in Category.select().where(Category.folder.startswith("部门规章/")):
        department = category.folder.split("/")[1]
        order = DEPARTMENT_ORDER_START + DEPARTMENT_ORDER.index(department) \
            if department in DEPARTMENT_ORDER else DEPARTMENT_ORDER_UNKNOWN
        changed = category.order != order or category.group != "部门规章" or not category.isSubFolder
        if changed:
            category.order, category.group, category.isSubFolder = order, "部门规章", True
            category.save()


def update_amendments(db: Database):
    """修改法规的决定 → 被修改的法规。

    指向决定施行前已发布的最新版本，也就是修改前的那一版；库里只收了之后的版本时，指向最早的那一版。
    """
    by_name = defaultdict(list)
    for law in Law.select():
        by_name[law.name].append(law)
    for law, path in db.resolved_laws():
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


def restore_unexplained_expiry(db: Database) -> int:
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


def invalidate_laws(db: Database) -> int:
    """正文写明「《某法》同时废止」的，某法最后一个版本在本法生效时失效。案例只是引述，不算。

    新法的后续版本往往保留「《某法》同时废止」，几部法规都写了的，取最早生效的那一部。
    """
    count = 0
    # 被废止的版本 id → (生效日期, 废止它的法规, 被废止的版本)
    earliest: dict = {}
    for law, path in db.resolved_laws():
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
            # 名单里这一项的日期比最新版本早：废止的是库里没有的旧版本（如 1987 年的《广播电视设施保护条例》）
            listed = decision_listed_date(content, name) if "决定" in law.name else None
            if listed and last.publish and last.publish > listed:
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


def update_implementations(db: Database):
    """实施条例、司法解释、法律解释指向它实施或解释的法律。

    同名多个版本时取本文件生效时已发布的最新版本，都晚于本文件的取最早的版本。
    民法典这类按编拆开的，名称里写了哪一编就指向那一编，否则指向第一编。
    DLC 还会在本体数据库里找 target，source 只来自自己。
    """
    base_laws, base_categories = db.base_laws()
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

    def version_at(name: str, date: str | None) -> "Law":
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
    for law, path in db.resolved_laws():
        levels = BASIS_TARGET_LEVELS.get(law.level)
        if not levels:
            continue
        date = law.valid_from or law.publish
        for name in extract_basis_law_names(path.read_text(encoding="utf-8")):
            if name in by_name and by_name[name][-1].level in levels:
                relate(law, version_at(name, date))
            elif name in parts and parts[name][0].level in levels:
                relate(law, parts[name][0])
