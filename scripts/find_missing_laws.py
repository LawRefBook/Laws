
from pathlib import Path
import sys
from typing import Dict, List, Set
import re

from common import short_title


def title_key(title: str) -> str:
    """比较用：去掉空白，〈〉换成《》，去掉开头和书名号里的「中华人民共和国」。

    正文引用「《最高人民法院关于适用〈中华人民共和国婚姻法〉若干问题的解释（三）》」
    和文件名「最高人民法院关于适用《婚姻法》若干问题的解释（三）」是同一部。
    """
    title = re.sub(r"\s", "", title).replace("〈", "《").replace("〉", "》")
    return short_title(title)

def is_file_ignored(file: Path, ignore_folders: List[Path | re.Pattern]) -> bool:
    for folder in ignore_folders:
        if isinstance(folder, Path) and file.is_relative_to(folder):
            return True
        if isinstance(folder, re.Pattern) and folder.match(str(file)):
            return True
    return False

def look_files(path: Path):
    ignore_file = path / ".lawignore"
    ignore_folders: List[Path] = []
    if ignore_file.exists():
        with open(ignore_file, "r") as f:
            for line in f.readlines():
                line = line.strip()
                if line.startswith("^"):
                    ignore_folders.append(re.compile(line))
                else:
                    ignore_folders.append(path / line)
    for file in path.glob("**/*.md"):
        if is_file_ignored(file.relative_to(path), ignore_folders):
            continue
        yield file


def main():
    if len(sys.argv) < 2:
        print("Usage: python find_missing_laws.py <path>")
        return
    path = Path(sys.argv[1])
    if not path.exists():
        print("Path does not exist")
        return

    pattern = re.compile(r"《(.*?)》")
    # 归一化后的名称 → 正文里第一次出现的写法
    all_mentioned_laws: Dict[str, str] = {}
    all_laws: Set[str] = set()
    for file in look_files(path):
        filename = file.stem
        # 人力资源社会保障部办公厅关于订立电子劳动合同有关问题的函(2020-03-04).md
        filename = re.sub(r"\(\d{4,4}\-\d{2,2}\-\d{2,2}\)", "", filename)
        all_laws.add(title_key(filename))

        content = file.read_text(encoding="utf-8")
        matches = pattern.findall(content)
        for match in matches:
            match: str = match.strip()
            if "中华人民共和国" not in match:
                continue
            # match = match.replace("中华人民共和国", "")
            # Ignore 决定
            if match.endswith("决定"):
                continue
            if len(match) <= 3:
                continue
            all_mentioned_laws.setdefault(title_key(match), match)

    ignore_laws = set([
        "残疾军人证",
    ])

    def collected(key: str) -> bool:
        if key in all_laws:
            return True
        # 引用时常省略发布机关：「关于〈刑法〉第三十条的解释」→「全国人民代表大会常务委员会关于《刑法》第三十条的解释」
        return key.startswith("关于") and any(law.endswith(key) for law in all_laws)

    for key, law in sorted(all_mentioned_laws.items()):
        if not collected(key):
            print(law)


if __name__ == "__main__":
    main()

# import re
# from pathlib import Path

# from database import get_laws, law_db
# import jieba.analyse

# BASE_PATH = Path("../")

# def main():
#     for folder, f in get_laws():
#         file_path = BASE_PATH / folder / f"{f}.md"
#         if "案例" not in str(file_path):
#             continue
#         sentence = file_path.read_text(encoding="utf-8")
#         seg_list = jieba.analyse.textrank(sentence, topK=10, withWeight=False, allowPOS=('n', 'nz', 'nt', 'nw'))
#         exist_laws = law_db.get_laws(file_path.stem)
#         if not exist_laws:
#             continue
#         law = exist_laws[0]
#         law.tags = ",".join(seg_list)
#         law.save()


# if __name__ == "__main__":
#     main()
