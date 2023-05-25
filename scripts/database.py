from collections import defaultdict
from pathlib import Path
from uuid import uuid4
import sys
import re
from typing import List
import peewee

from datetime import datetime
from sqlite3 import Cursor

database = peewee.SqliteDatabase(None)  # Defer initialization


class BaseModel(peewee.Model):
    class Meta:
        database = database  # This model uses the "people.db" database.


class Category(BaseModel):
    id = peewee.UUIDField(primary_key=True, default=uuid4)
    name = peewee.TextField()
    folder = peewee.TextField()
    isSubFolder = peewee.BooleanField(default=False)
    group = peewee.TextField(null=True)
    order = peewee.IntegerField(null=True)

    @staticmethod
    def get_or_create_category(folder: Path) -> "Category":
        try:
            return Category.get(folder=folder)
        except Category.DoesNotExist:
            pass
        return Category.create(**{"name": folder.parts[-1], "folder": folder})


class Law(BaseModel):
    id = peewee.UUIDField(primary_key=True, default=uuid4)
    level = peewee.TextField()
    name = peewee.TextField(index=True)
    subtitle = peewee.TextField(null=True)

    filename = peewee.TextField(null=True)
    publish = peewee.DateField(formats="%Y-%m-%d", null=True)
    valid_from = peewee.DateField(formats="%Y-%m-%d", null=True)
    expired = peewee.BooleanField(default=False)
    order = peewee.IntegerField(null=True)
    ver = peewee.IntegerField(null=False, default=0)

    tags = peewee.TextField(null=True)

    category_id = peewee.UUIDField(null=False)

    def __repr__(self) -> str:
        return f"<Law {self.name}>"

    __str__ = __repr__

    @staticmethod
    def query_all() -> List["Law"]:
        return Law.select()

    @staticmethod
    def query(name: str = None, publish_at: str | datetime = None) -> List["Law"]:
        if publish_at and isinstance(publish_at, datetime):
            publish_at = publish_at.strftime("%Y-%m-%d")
        expr = None
        if name:
            expr = (Law.name == name) | (Law.subtitle == name)
        if publish_at:
            expr = expr & (Law.publish == publish_at)
        if expr:
            return Law.select().where(expr)
        return []


def get_law_level_by_folder(folder: Path) -> str:
    root_folder = folder.parts[0]
    r = re.match("^((司法解释)|(地方性法规)|(宪法)|(案例)|(行政法规)|(部门规章))$", root_folder)
    if r:
        return root_folder
    return "法律"


class Database(object):
    def __init__(self, sqlite_file: Path) -> None:
        self.tables = [Category, Law]
        self.sqlite_file = sqlite_file
        self.db = database
        self.db.init(sqlite_file)
        self.prepare()

    def prepare(self):
        if self.sqlite_file.exists():
            assert self.sqlite_file.is_file()
        else:
            assert self.sqlite_file.name == "db.sqlite3"
            self.db.create_tables(self.tables)

    def reset(self):
        yes = False
        for _ in range(0, 3):
            yes = input("Are you sure to reset database? [y/N]").lower() == "y"
            if not yes:
                break
        if yes:
            self.db.drop_tables(self.tables)
            self.db.create_tables(self.tables)

    # 更新法律版本
    # 如果任意法律有多个版本（即同名，但多个 publish, 则将 ver 设为其数量）
    # 除最新版本的法律, 其余均设为 expired.
    def update_versions(self):
        self.db.execute_sql(
            "update law set ver = (select count(1) from law t where t.name = law.name)"
        )
        laws_multi_version = Law.select().where(Law.ver > 1)
        m = defaultdict(list)
        for law in laws_multi_version:
            m[law.name].append(law)
        expired_laws = []
        for _, laws in m.items():
            laws.sort(key=lambda x: x.publish)
            expired_laws += laws[:-1]
        for law in expired_laws:
            law.expired = True
            law.save()

    @property
    def lookup_path(self) -> Path:
        return self.sqlite_file.parent

    def load_ignore_folders(self):
        ignore_file = self.lookup_path / ".lawignore"
        if not ignore_file.exists():
            return []
        with open(ignore_file, "r") as f:
            return [self.lookup_path / line.strip() for line in f.readlines()]

    def __ignore(self, ignore_folders: List[Path], file: Path) -> bool:
        for ignore_folder in ignore_folders:
            if ignore_folder in file.parents:
                return True

    def load_laws(self):
        ignore_folders = self.load_ignore_folders()
        for markdown_file in self.lookup_path.glob("**/**/*.md"):
            if self.__ignore(ignore_folders, markdown_file):
                # print(f"ignore {markdown_file}")
                continue
            r = re.search(r"\((\d{4,4}\-\d{2,2}\-\d{2,2})\)", markdown_file.stem)
            if not r:
                continue
            yield markdown_file, r.group(1), markdown_file.stem[: r.span()[0]]

    def update_law_level(self, laws: List[Law], level: str) -> int:
        updated_count = 0
        for law in filter(lambda x: x.level != level, laws):
            updated_count += 1
            law.level = level
            law.save()
        return updated_count

    def validate(self):
        for law_file, publish_at, law_name in self.load_laws():
            content = law_file.read_text(encoding="utf-8")
            lines = content.splitlines()
            titles = list(filter(lambda x: x.startswith("## "), lines))
            if not titles:
                continue

            if len(titles) == len(set(titles)):
                continue

            print(f"Duplicate titles in {law_file}")

            # find line idx == <!-- INFO END -->
            info_end_idx = None
            for idx, line in enumerate(lines):
                if line.strip().startswith("<!-- INFO END -->"):
                    info_end_idx = idx
                    break
            info_end_idx = info_end_idx + 1
            first_title = list(
                filter(
                    lambda x: x[1].replace(" ", "") == titles[0].replace(" ", ""),
                    enumerate(lines),
                )
            )
            start_idx = first_title[-1][0]
            # remove lines betwween info_end_idx and start_idx
            lines = lines[:info_end_idx] + lines[start_idx:]
            law_file.write_text("\n".join(lines), encoding="utf-8")

    def update_database(self):
        count = {
            "laws": self.get_law_count(),
            "handled": 0,
            "updated": 0,
            "created": 0,
        }
        for law_file, publish_at, law_name in self.load_laws():
            count["handled"] += 1

            folder = law_file.relative_to(self.lookup_path).parent
            law_level = get_law_level_by_folder(folder)
            in_db_laws = Law.query(name=law_name, publish_at=publish_at)
            if in_db_laws:
                updated = self.update_law_level(in_db_laws, law_level)
                count["updated"] += updated
                continue
            # Law 不存在于数据库中
            category = Category.get_or_create_category(folder)
            Law.create(
                name=law_name,
                publish=publish_at,
                category_id=category.id,
                level=law_level,
            )
            count["created"] += 1
        return count

    def get_law_count(self):
        return Law.select().count()


def main():
    args = sys.argv[1:]
    if len(args) != 2:
        print("Usage: python3 database.py <command(update/drop)> <sqlite_file>")
        return
    command = args[0]
    sqlite_file = Path(args[1])
    db = Database(sqlite_file)

    if command == "drop":
        db.reset()
        return

    if command == "update":
        count = db.update_database()
        print(f"Total: {count['laws']}")
        print(f"Handled: {count['handled']}")
        print(f"Updated: {count['updated']}")
        print(f"Created: {count['created']}")
        return

    if command == "validate":
        db.validate()
        return

    print("Unknown command")


if __name__ == "__main__":
    main()
