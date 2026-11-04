#!/usr/bin/env python3
"""Generate the id and line maps the app migration needs.

Run again after any further edit to the law files and before releasing the
data pack, because the line map is only valid for the exact tree it was
generated from.

    python3 generate.py [baseline-commit]

The baseline is the commit recorded in release:alpha/metadata/laws.meta, that
is, the data pack installed on users' devices.
"""
import difflib
import json
import re
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import unicodedata
from io import BytesIO
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
NUMBERS = "一二三四五六七八九十零百千万"
LINE_START = re.compile(f"^((第[{NUMBERS}]+条)|[{NUMBERS}]+、)")
PUNCT = str.maketrans({",": "，", ";": "；", ":": "：", "?": "？", "!": "！", "(": "（", ")": "）", "<": "〈", ">": "〉"})
FULL = {chr(0xFF10 + i): str(i) for i in range(10)} | {chr(0xFF21 + i): chr(65 + i) for i in range(26)} | {chr(0xFF41 + i): chr(97 + i) for i in range(26)}
FULL = str.maketrans(FULL)


def trim(s):
    """String.trimmingCharacters(in: .whitespacesAndNewlines)."""
    def blank(c):
        return c in "\t\n\v\f\r\x85\u200b" or unicodedata.category(c).startswith("Z")
    a, b = 0, len(s)
    while a < b and blank(s[a]):
        a += 1
    while b > a and blank(s[b - 1]):
        b -= 1
    return s[a:b]


def parse(contents):
    """Port of LawContentParser.parse. Returns [(line, text)] in document order."""
    is_desc, is_fix, force_break = True, False, False
    no = 0
    paragraphs = []
    section_has_children = None  # None until the first section exists

    def add(text, new_line):
        nonlocal no, section_has_children
        if not section_has_children or new_line:
            paragraphs.append([no, text])
            section_has_children = True
            return True
        paragraphs[-1][1] += "\n" + text
        return False

    for raw in contents.split("\n"):
        text = trim(raw)
        if not text:
            continue
        out = [x for x in text.split(" ", 1) if x]
        if out[0] == "#":
            is_fix = is_fix or "修正" in text
            continue
        if text.startswith("<!-- INFO END -->"):
            is_desc = False
            continue
        if text.startswith("<!-- FORCE BREAK -->"):
            force_break = True
            continue
        new_line = force_break or (not text.startswith("-") if is_fix else LINE_START.search(text) is not None)
        force_break = False
        if text.startswith("<!-- TABLE -->"):
            new_line = True
        if text.startswith("<!-- TABLE END -->"):
            continue
        if is_desc:
            continue
        if out[0].startswith("#"):
            paragraphs.append([no, out[1] if len(out) > 1 else ""])
            section_has_children = False
            no += 1
            continue
        if section_has_children is None:
            paragraphs.append([no, ""])
            section_has_children = False
            no += 1
        if add(text, new_line):
            no += 1
    return [tuple(p) for p in paragraphs]


def canon(t):
    t = re.sub("[​-]", "", t).translate(PUNCT).translate(FULL)
    return re.sub(r"[\s　#]+", "", t)


def fuzzy(text, others):
    """Find the new paragraph a changed old paragraph became."""
    if len(text) < 8:
        return None
    for line, other in others:
        if len(other) >= 8 and (other.startswith(text) or text.startswith(other)):
            return line
    for line, other in others:
        if len(other) >= 20 and other in text:
            return line
    for line, other in others:
        if text in other:
            return line
    return None


def align(old, new):
    """Map each old (line, text) to a new line, or None when the text is gone."""
    a = [(n, canon(t)) for n, t in old]
    b = [(n, canon(t)) for n, t in new]
    matcher = difflib.SequenceMatcher(None, [t for _, t in a], [t for _, t in b], autojunk=False)
    result = {}
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for i, j in zip(range(i1, i2), range(j1, j2)):
                result[a[i][0]] = b[j][0]
            continue
        # one paragraph either side covers text merged into a matched neighbour
        scope = b[j1:j2] + b[max(j1 - 1, 0):j1] + b[j2:j2 + 1]
        for line, text in a[i1:i2]:
            if text:
                result[line] = fuzzy(text, scope)
    return result


def rows(path):
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    q = "select l.id,l.name,l.filename,l.publish,l.subtitle,c.folder from law l join category c on c.id=l.category_id"
    return {r[0]: r for r in db.execute(q)}


def resolve(row, base):
    """TLaw.getNames plus LawDatabase.getLawLocalFilePath."""
    _, name, filename, publish, subtitle, folder = row
    first = filename or (f"{name}({publish})" if publish else name)
    for stem in filter(None, (first, name, subtitle)):
        p = base / folder / f"{stem}.md"
        if p.exists():
            return p
    return None


def ranges(mapping):
    out, dropped = [], []
    for old in sorted(mapping):
        new = mapping[old]
        if new is None:
            dropped.append(old)
            continue
        delta = new - old
        if out and out[-1][1] + 1 == old and out[-1][2] == delta:
            out[-1][1] = old
        else:
            out.append([old, old, delta])
    return [r for r in out if r[2] != 0], dropped


def main():
    baseline = sys.argv[1] if len(sys.argv) > 1 else json.loads(subprocess.run(
        ["git", "show", "release:alpha/metadata/laws.meta"], cwd=ROOT, capture_output=True, text=True, check=True).stdout)["hash"]
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        data = subprocess.run(["git", "archive", baseline], cwd=ROOT, capture_output=True, check=True).stdout
        with tarfile.open(fileobj=BytesIO(data)) as tar:
            tar.extractall(tmp, filter="data", members=[m for m in tar if not m.name.startswith(("DLC/", "scrape/"))])
        old_rows, new_rows = rows(tmp / "db.sqlite3"), rows(ROOT / "db.sqlite3")
        removed = json.loads((HERE / "id_map.json").read_text())["removed"]
        line_map, stats = {}, {"laws_remapped": 0, "lines_dropped": 0, "missing": []}
        for law_id, row in old_rows.items():
            target = law_id if law_id in new_rows else removed[law_id]
            a, b = resolve(row, tmp), resolve(new_rows[target], ROOT)
            if a is None or b is None:
                stats["missing"].append(row[1])
                continue
            pa, pb = parse(a.read_text(encoding="utf-8")), parse(b.read_text(encoding="utf-8"))
            if pa == pb:
                continue
            mapping = align(pa, pb)
            moved, dropped = ranges(mapping)
            if moved or dropped:
                line_map[law_id] = {"ranges": moved, "dropped": dropped}
                stats["laws_remapped"] += 1
                stats["lines_dropped"] += len(dropped)
    (HERE / "line_map.json").write_text(json.dumps({"baseline": baseline, "laws": line_map}, ensure_ascii=False, separators=(",", ":")))
    print(json.dumps(stats, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
