from pathlib import Path
from parsers import WordParser, ContentParser
from manager import CacheManager

FOLDER = Path("/Users/rankki/Downloads/2022年12月11发送医疗法律法规")
OUT_FOLDER = Path("./__cache__/out")

word_parser = WordParser()
content_parser = ContentParser()
cache = CacheManager()

def parse(doc_file: Path):
    print(doc_file)
    title, desc, content = word_parser.parse_document(doc_file, doc_file.stem)

    filedata = content_parser.parse(None, title, desc, content)
    if not filedata:
        return

    cache.write_law(f"{title}.md", filedata)


def main():
    for doc_file in FOLDER.glob("*.docx"):
        parse(doc_file)


if __name__ == "__main__":
    main()
