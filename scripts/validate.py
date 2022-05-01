import os
from pathlib import Path
import re

from numpy import full
import database
import json
from functools import reduce

with open("../data.json", "r") as f:
    data = json.load(f)
laws = reduce(lambda x, y: x + y["laws"], data, [])

for law in laws:
    db_law = database.Law.get_or_none(database.Law.id == law["id"])
    if not db_law:
        print("不存在", law)
        continue

        # db_law = database.Law.get_or_none(database.Law.name == law["name"]) or database.Law.get_or_none(database.Law.name == law["subtitle"])
        # db_law.id = law["id"].replace("-", "")
        # db_law.save(force_insert=True)

    if law["name"] != db_law.name and law["subtitle"] != db_law.name:
        print("不一致", law)

rel_path = Path("../")
no_law = []
for law in database.Law.select():
    category = law.category_id
    fullpath: Path = None
    if law.filename:
        fullpath = rel_path / category.folder / (law.filename + ".md")
    elif law.publish:
        fullpath = rel_path / category.folder / \
            (law.name + f"({law.publish})" + ".md")
    else:
        fullpath = rel_path / category.folder / (law.name + ".md")

    if not fullpath.exists():
        no_law.append(law)
        # print(fullpath)

for law in no_law:
    category = law.category_id
    p: Path = rel_path / category.folder
    print(law.name)
    for filename in map(lambda x: x.split(".")[0], os.listdir(p)):
        if filename.startswith(law.name):
            ret = re.search("\((\d{4,4}\-\d{2,2}\-\d{2,2})\)", filename)
            if not ret:
                continue
            pub_at = ret.group(1)
            law.publish = pub_at
            law.save()
