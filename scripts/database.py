from collections import defaultdict
import json
import re
from datetime import datetime
from functools import reduce
from pathlib import Path
from typing import List
from uuid import uuid4

import peewee

import request

db = peewee.SqliteDatabase('../db.sqlite3')


def get_law_level_by_folder(folder: str) -> str:
    folder = folder.split("/")[0]
    if re.match("^((司法解释)|(地方性法规)|(宪法)|(案例)|(行政法规)|(部门规章))$", folder):
        return folder
    return "法律"


class BaseModel(peewee.Model):

    class Meta:
        database = db  # This model uses the "people.db" database.


class Category(BaseModel):

    id = peewee.IntegerField(primary_key=True)
    name = peewee.TextField()
    folder = peewee.TextField()
    isSubFolder = peewee.BooleanField(default=False)
    group = peewee.TextField(null=True)
    order = peewee.IntegerField()


class Law(BaseModel):

    id = peewee.UUIDField(primary_key=True, default=uuid4)
    level = peewee.TextField()
    name = peewee.TextField(index=True)
    subtitle = peewee.TextField(null=True)

    filename = peewee.TextField(null=True)
    publish = peewee.DateField(formats='%Y-%m-%d', null=True)
    valid_from = peewee.DateField(formats='%Y-%m-%d', null=True)
    expired = peewee.BooleanField(default=False)
    order = peewee.IntegerField(null=True)
    ver = peewee.IntegerField(null=False, default=0)

    category_id = peewee.ForeignKeyField(Category, backref="laws")

    def __repr__(self) -> str:
        return f"<Law {self.name}>"

    __str__ = __repr__


class LawDatabase(object):

    def __init__(self) -> None:
        self.db = db

    def get_or_create_category(self, folder: str) -> Category:
        try:
            return Category.get(folder=folder)
        except Category.DoesNotExist:
            pass
        return Category.create(**{
            "name": folder.split("/")[-1],
            "folder": folder
        })

    def get_laws(self, name: str = None, publish_at: datetime | str = None) -> List[Law]:
        if publish_at and isinstance(publish_at, datetime):
            publish_at = publish_at.strftime('%Y-%m-%d')
        expr = None
        if name:
            expr = Law.name == name
        if publish_at:
            expr = expr & (Law.publish == publish_at)
        if expr:
            return Law.select().where(expr)
        return Law.select().where(1 == 1)

    def delete_law(self, id):
        Law.delete_by_id(id)

    def create_law(self, name: str, category: Category, level: str, publish_at: str = None, id=None) -> Law:
        try:
            params = {
                "name": name,
            }
            if publish_at:
                params["publish"] = publish_at
            return Law.get(**params)
        except Law.DoesNotExist:
            pass
        params = {
            "name": name,
            "category_id": category.id,
            "level": level,
        }
        if publish_at:
            params["publish"] = publish_at
        if id:
            params["id"] = id
        return Law.create(**params)


def get_laws():
    bypass = ["scripts"]
    base = Path("../")
    ret = []
    for file in base.glob("**/*.md"):
        if "_index.md" == file.parts[-1]:
            continue
        file = file.relative_to("../")
        folder = "/".join(file.parts[:-1])
        if not folder:
            continue
        bypass_flag = False
        for by in bypass:
            if re.search(by, str(file)):
                bypass_flag = True
                break
        if bypass_flag:
            continue
        d = (folder, file.parts[-1].replace(".md", ""))
        ret.append(d)
    return ret


law_db = LawDatabase()


def update_database():
    for folder, f in get_laws():
        category = law_db.get_or_create_category(folder)
        ret = re.search("\((\d{4,4}\-\d{2,2}\-\d{2,2})\)", f)
        if not ret:
            continue
        pub_at = ret.group(1)
        name = f[:ret.span()[0]]

        exist_laws = law_db.get_laws(name, pub_at)
        if exist_laws:
            expected_level = get_law_level_by_folder(folder)
            for law in filter(lambda x: x.level != expected_level, exist_laws):
                law.level = expected_level
                law.save()

            continue

        param = {
            "name": name,
            "category": category,
            "level": get_law_level_by_folder(folder),
            "publish_at": pub_at,
        }
        law = law_db.create_law(**param)


def update_status():
    params = [
        # ('xlwj', ['02', '03', '04', '05', '06', '07', '08']),  # 法律法规
        # ("fgbt", "中华人民共和国澳门特别行政区基本法"),
        ("fgxlwj", "xzfg"),  # 行政法规
        ('type', 'sfjs'),
        ("zdjg", "4028814858a4d78b0158a50f344e0048&4028814858a4d78b0158a50fa2ba004c"),  # 北京
        ("zdjg", "4028814858b9b8e50158bed591680061&4028814858b9b8e50158bed64efb0065"),  # 河南
        ("zdjg", "4028814858b9b8e50158bec45e9a002d&4028814858b9b8e50158bec500350031"),  # 上海
        # ("zdjg", "4028814858b9b8e50158bec5c28a0035&4028814858b9b8e50158bec6abbf0039"), # 江苏
        ("zdjg", "4028814858b9b8e50158bec7c42f003d&4028814858b9b8e50158beca3c590041"),  # 浙江
        ("zdjg", "4028814858b9b8e50158bed40f6d0059&4028814858b9b8e50158bed4987a005d"),  # 山东
        # ("zdjg", "4028814858b9b8e50158bef1d72600b9&4028814858b9b8e50158bef2706800bd"), # 陕西省
    ]

    adding_pub = False

    req = request.LawParser()
    req.request.searchType = "1,9"
    for param in params:
        req.request.params = [param]
        for item in req.lawList():
            title = item["title"].replace("中华人民共和国", "")
            if "publish" in item and item["publish"]:
                item["publish"] = item["publish"].split(" ")[0]
            if "expiry" in item and item["expiry"]:
                item["expiry"] = item["expiry"].split(" ")[0]
            if adding_pub:
                laws = law_db.get_laws(title)
            else:
                laws = law_db.get_laws(title, item["publish"])
            if not laws:
                print(f"{title} 不存在")
                continue
            if len(laws) != 1:
                print(f"{title} 存在两份数据，请手动处理")
                continue
            law = laws[0]
            law.publish = item["publish"].strip()
            law.valid_from = item["expiry"].strip()
            law.expired = int(item["status"]) == 9
            law.save()
            print("saved", law)


def update_ver():
    db.execute_sql("""update law
set ver = (select count(1) from law t where t.name = law.name);""")


def update_status_same_name():
    law_map = defaultdict(list)
    for law in Law.select().where(Law.ver > 1):
        law_map[law.name].append(law)
    for name, laws in law_map.items():
        laws.sort(key=lambda x: x.publish)
        for i in range(0, len(laws) - 1):
            law = laws[i]
            law.expired = True
            law.save()


if __name__ == "__main__":
    tables = [Category, Law]

    # db.drop_tables(tables)
    # db.create_tables(tables)
    # recover()
    update_database()
    # update_status()

    update_ver()
    update_status_same_name()
