import re
from pathlib import Path

from database import get_laws, law_db
import jieba.analyse

BASE_PATH = Path("../")

def main():
    for folder, f in get_laws():
        file_path = BASE_PATH / folder / f"{f}.md"
        if "案例" not in str(file_path):
            continue
        sentence = file_path.read_text(encoding="utf-8")
        seg_list = jieba.analyse.textrank(sentence, topK=10, withWeight=False, allowPOS=('n', 'nz', 'nt', 'nw'))
        exist_laws = law_db.get_laws(file_path.stem)
        if not exist_laws:
            continue
        law = exist_laws[0]
        law.tags = ",".join(seg_list)
        law.save()


if __name__ == "__main__":
    main()
