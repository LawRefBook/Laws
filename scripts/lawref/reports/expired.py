"""列出已失效、但不知道被谁废止的法规，见 `laws report expired`。

已失效：失效日期早于今天，包括「已失效、日期未知」的 1970-01-01。
不知道被谁废止：没有新版本取代它（supersedes），也没有别的法规写明废止它（abolishes）。
"""
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path

from lawref.db.models import UNKNOWN_EXPIRY

QUERY = """
SELECT l.level, l.name, l.publish, l.valid_to, c.folder
FROM law l JOIN category c ON c.id = l.category_id
WHERE l.valid_to < ?
  AND NOT EXISTS (SELECT 1 FROM relationship r WHERE r.target_id = l.id AND r.type IN ('supersedes', 'abolishes'))
ORDER BY l.level, l.valid_to, l.name
"""


def run(db_path: Path) -> None:
    with closing(sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)) as db:
        rows = db.execute(QUERY, (date.today().isoformat(),)).fetchall()
    level = None
    for row_level, name, publish, valid_to, folder in rows:
        if row_level != level:
            level = row_level
            print(f"\n{level}")
        expired = "失效日期未知" if valid_to == UNKNOWN_EXPIRY else f"{valid_to} 失效"
        print(f"  {name}（{publish or '无发布日期'}，{expired}）  {folder}")
    print(f"\n共 {len(rows)} 部")

