"""打开数据库文件，找到每条记录对应的法规文件。"""
import sqlite3
from pathlib import Path

from lawref.db.models import Category, Law, Relationship, database
from lawref.repo import pack_files

TABLES = [Category, Law, Relationship]

# 后来加的列。create_tables 不会给已有的表加列，旧数据库在这里补上
ADDED_COLUMNS = {
    "law": ["flags INTEGER NOT NULL DEFAULT 0"],
}

# 只有 implements 可以指向本体数据库，这些关系的 target 必须在本库里
LOCAL_TARGET_TYPES = (Relationship.AMENDS, Relationship.ABOLISHES)


class Database:
    """一个数据包的 db.sqlite3。法规文件在它所在的目录下：本体是仓库根目录，DLC 是 DLC/<名称>/。

    模型都绑定在同一个连接上，同一时间只能打开一个；可以用 with 语句，结束时关闭。
    """

    def __init__(self, sqlite_file: Path, readonly: bool = False) -> None:
        self.sqlite_file = sqlite_file.resolve()
        self.db = database
        if readonly:
            # 只读打开，不补表，check 不会改动数据库文件
            self.db.init(f"{self.sqlite_file.as_uri()}?mode=ro", uri=True)
        else:
            if self.sqlite_file.exists():
                assert self.sqlite_file.is_file()
            else:
                assert self.sqlite_file.name == "db.sqlite3"
            self.db.init(str(self.sqlite_file))
            self.prepare()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if not self.db.is_closed():
            self.db.close()

    def prepare(self):
        """建表；已有的表不动，旧数据库会补上新加的表和列。"""
        self.db.create_tables(TABLES)
        for table, columns in ADDED_COLUMNS.items():
            existing = {c.name for c in self.db.get_columns(table)}
            for column in columns:
                if column.split(" ", 1)[0] not in existing:
                    self.db.execute_sql(f"ALTER TABLE {table} ADD COLUMN {column}")

    def reset(self):
        """清空重建。所有法规会重新生成 ID。"""
        self.db.drop_tables(TABLES)
        self.db.create_tables(TABLES)

    @property
    def lookup_path(self) -> Path:
        return self.sqlite_file.parent

    @property
    def base_sqlite_file(self) -> Path | None:
        """DLC（<仓库>/DLC/<名称>/db.sqlite3）对应的本体数据库，本体自己返回 None。"""
        parts = self.sqlite_file.parts
        if "DLC" not in parts[:-1]:
            return None
        root = Path(*parts[:len(parts) - 1 - parts[::-1].index("DLC")])
        return root / "db.sqlite3"

    @property
    def is_dlc(self) -> bool:
        return self.base_sqlite_file is not None

    def base_laws(self) -> tuple[list[Law], dict]:
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

    def law_files(self) -> list[Path]:
        return pack_files(self.lookup_path)

    def resolve(self, law: Law, categories: dict) -> Path | None:
        """记录对应的文件，找不到返回 None。"""
        category = categories.get(law.category_id)
        if category is None:
            return None
        for stem in law.stems():
            path = self.lookup_path / category.folder / f"{stem}.md"
            if path.exists():
                return path
        return None

    def resolved_laws(self) -> list[tuple[Law, Path]]:
        categories = {c.id: c for c in Category.select()}
        ret = []
        for law in Law.select():
            if path := self.resolve(law, categories):
                ret.append((law, path))
        return ret

    def check(self) -> list[str]:
        """发布前的校验，返回问题列表。"""
        if not Relationship.table_exists():
            return []
        names = {law.id: law.name for law in Law.select(Law.id, Law.name)}
        return [f"{r.type}：{names.get(r.source_id, r.source_id)} → target {r.target_id.hex} 不在本库里"
                for r in Relationship.select().where(Relationship.type.in_(LOCAL_TARGET_TYPES))
                if r.target_id not in names]
