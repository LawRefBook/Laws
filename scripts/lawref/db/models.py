"""数据库的表。字段和 LawFlag 的各位是和 App 的约定，只能加，不能改含义。"""
import enum
from pathlib import Path
from uuid import uuid4

import peewee

# 模型都绑定在这一个连接上，由 store.Database 打开具体的文件
database = peewee.SqliteDatabase(None)

FOREVER = "2099-12-31"
# 已失效、但不知道哪天失效的手工标记，update 不改动
UNKNOWN_EXPIRY = "1970-01-01"


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


class LawFlag(enum.IntFlag):
    """law.flags 的各位。和 App 的 TLaw.Flags 一一对应，只能加新位，已有的位不能改含义。"""
    # 修订链上不止一个版本，可以看修订历史
    HISTORY = 1 << 0
    # 正文有目录，见 content_flags
    TOC = 1 << 1
    # 正文开头有信息，见 content_flags
    INFO = 1 << 2
    # 没有「有相关法律」：实施它的规定可能在用户装了的 DLC 里，只有 App 知道，整项由 App 算


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

    # LawFlag 按位组合，App 打开正文前据此决定显示哪些按钮
    flags = peewee.IntegerField(null=False, default=0)

    category_id = peewee.UUIDField(null=False)

    def __repr__(self) -> str:
        return f"<Law {self.name} {self.publish}>"

    __str__ = __repr__

    def stems(self) -> list[str]:
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
    def relate(source: "Law", target: "Law", type: str, date: str | None = None):
        Relationship.insert(source_id=source.id, target_id=target.id, type=type, date=date).on_conflict_ignore().execute()


# 部门规章目录的顺序：国家规章库的部门列表（国务院机构序列），目录名按仓库里的写法
