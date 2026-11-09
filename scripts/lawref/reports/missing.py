"""正文提到、仓库里却没有收录的法律，见 `laws report missing`。"""
import re
from pathlib import Path

from lawref.document import split_stem
from lawref.repo import law_files
from lawref.text import title_key

# 正文里用书名号引用、但不是法规的
NOT_LAWS = {"残疾军人证"}


def find_missing(path: Path) -> list[str]:
    """正文里以「中华人民共和国」引用、但 path 下没有收录的法律，按归一化后的名称排序，取正文里第一次出现的写法。"""
    pattern = re.compile(r"《(.*?)》")
    # 归一化后的名称 → 正文里第一次出现的写法
    all_mentioned_laws: dict[str, str] = {}
    all_laws: set[str] = set()
    for file in law_files(path):
        all_laws.add(title_key(split_stem(file.stem)[0]))

        content = file.read_text(encoding="utf-8")
        matches = pattern.findall(content)
        for match in matches:
            match: str = match.strip()
            if "中华人民共和国" not in match:
                continue
            # 决定不单独收录
            if match.endswith("决定"):
                continue
            if len(match) <= 3:
                continue
            if title_key(match) in NOT_LAWS:
                continue
            all_mentioned_laws.setdefault(title_key(match), match)

    def collected(key: str) -> bool:
        if key in all_laws:
            return True
        # 引用时常省略发布机关：「关于〈刑法〉第三十条的解释」→「全国人民代表大会常务委员会关于《刑法》第三十条的解释」
        return key.startswith("关于") and any(law.endswith(key) for law in all_laws)

    return [law for key, law in sorted(all_mentioned_laws.items()) if not collected(key)]
