import re
from pathlib import Path
import shutil

def find_laws():
    bypass = ["scripts"]
    base = Path("./")
    ret = []
    for file in base.glob("**/*.md"):
        if "_index.md" == file.parts[-1]:
            continue
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
        if re.match(".*《[^中].*法》.*", str(file)):
            print(file)
    return ret

laws = find_laws()
print(laws)