#!../.venv/bin/python

import click
from providers import NationalLawDatabaseProvider, Provider, CultureAndTourismDatabaseProvider
import re
from model.law import LawListItem
from docx import Document
from parsers.word import WordParser
from parsers.content import ContentParser
from pathlib import Path
import tqdm
import sys
import subprocess
from common import REGION_CODE_MAP
from typing import Callable

paging_options = [
    click.option('--limit', type=int, default=10)
]


def add_options(options):
    def _add_options(func):
        for option in reversed(options):
            func = option(func)
        return func
    return _add_options


def should_ignore(name) -> bool:
    title = name.replace("中华人民共和国", "")
    if re.search(r"的(决定|复函|批复|答复|批复)$", title):
        return True
    return False


def convert_to_docx(p: Path) -> Path:
    print(f"Converting {p} to .docx", file=sys.stderr)
    subprocess.run(
        [
            "soffice",
            "--headless",
            "--convert-to",
            "docx",
            "--outdir",
            str(p.parent),
            str(p),
        ],
        check=True,
    )
    p = p.with_suffix(".docx")
    if p.exists():
        return p
    raise ValueError(f"无法转换文件: {p}")


def process_item(provider: Provider, item: LawListItem, path_modifier: Callable[[Path], Path] = lambda x: x):
    try:
        response = provider.fetch_document(item)
    except Exception as e:
        print(f"无法获取文件: {item.title} {e}", file=sys.stderr)
        return False
    if not response or not response.path_to_file:
        raise ValueError(f"无法获取文件: {item.title}")

    path_to_file = response.path_to_file
    if path_to_file.suffix == ".doc":
        path_to_file = convert_to_docx(path_to_file)

    with open(path_to_file, "rb") as f:
        try:
            document = Document(f)
        except Exception as e:
            print(f"无法解析文件: {item.title} {e}", file=sys.stderr)
            return False
    parser = WordParser()

    _, desc, content = parser.parse_document(document, item.title)
    filedata = ContentParser().parse(item.title, desc, content)
    if not filedata:
        return

    filename = item.title.replace("中华人民共和国", "")
    if item.publication_date:
        filename = f"{filename}({item.publication_date})"
    filename = f"{filename}.md"

    ret = Path(".") / item.type / filename.strip()
    if path_modifier:
        ret = path_modifier(ret)

    provider.cache_manager.write_law(ret, filedata)

    return ret


@click.group()
def cli():
    pass


@cli.command()
@click.argument("law_name")
def download(law_name):
    """Search for a specific law by name and download it."""
    print(f"Searching {law_name}", file=sys.stderr)
    p: Provider = NationalLawDatabaseProvider()
    ret = p.fetch(
        use_high_search=True,
        dataList=[
            ("title", law_name)
        ]
    )
    for item in ret.items:
        process_item(p, item)


def _download_all(p: Provider, limit: int, **kwargs):
    path_modifier: Callable[[Path], Path] = kwargs.pop(
        "path_modifier", lambda x: x)

    click.echo(
        f"Downlaoding {limit if limit > 0 else 'all'} with params: {kwargs}")
    downloaded_laws = p.cache_manager.get_all_laws()

    def is_downloaded(title, published_at):
        if title not in downloaded_laws:
            return False
        return published_at in downloaded_laws[title]

    def loop_laws():
        page = 1
        while True:
            ret = p.fetch(page_num=page, **kwargs)
            if len(ret.items) <= 0:
                break
            for item in ret.items:
                if should_ignore(item.title):
                    continue
                if is_downloaded(item.title, item.publication_date):
                    continue
                yield item
            page += 1

    bar = tqdm.tqdm(total=0, unit="laws", unit_scale=True)
    for count, item in enumerate(loop_laws()):
        bar.set_description(f"Processing: {item.short_title}")
        try:
            process_item(p, item, path_modifier=path_modifier)
        except Exception as e:
            print(f"Failed to process {item.title}: {e}", file=sys.stderr)
        bar.update(1)


@add_options(paging_options)
@cli.command()
def download_all(limit: int):
    """Iterate through all laws and download them."""
    kwargs = {
        "flfgCodeId": [
            101, 102, 110, 120, 130, 140, 150, 155, 160, 170, 180, 190, 195, 200,  # 法律
            210,  # 行政法规
            311, 320, 330, 340, 350  # 司法解释
        ],
        "orderByParam": {"order": "gbrq", "sort": "DESC"},
    }
    _download_all(NationalLawDatabaseProvider(), limit, **kwargs)


@add_options(paging_options)
@cli.command()
@click.argument("region")
def download_dlc(region: str, limit: int):
    if region in REGION_CODE_MAP:
        __download_regional_dlc(region, limit)
        return
    if region == "文化与旅游部":
        def path_modifier(path: Path):
            return Path(".") / region / "部门规章" / region / path.name
        _download_all(CultureAndTourismDatabaseProvider(), limit,
                      path_modifier=path_modifier)
        return


def __download_regional_dlc(region: str, limit: int):
    kwargs = {
        "flfgCodeId": [
            230,  # 地方性法规
        ],
        "zdjgCodeId": [
            REGION_CODE_MAP[region]
        ],
    }

    def path_modifier(path: Path):
        return Path(".") / f"{region}地方法规" / "地方性法规" / region / path.name

    _download_all(NationalLawDatabaseProvider(), limit,
                  path_modifier=path_modifier, **kwargs)


if __name__ == "__main__":
    cli()
