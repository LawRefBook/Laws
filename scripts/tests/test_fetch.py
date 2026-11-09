import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lawref.fetch import pipeline
from lawref.fetch.models import LawItem, Page
from lawref.fetch.sources import FlkQuery, NationalLawDatabaseProvider, Provider, flk

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class FlkRequestTest(unittest.IsolatedAsyncioTestCase):
    """检索条件拼成的请求，和改成 FlkQuery 之前的一样。"""

    async def payload(self, call):
        with mock.patch("lawref.fetch.net.get_json", return_value={"rows": [], "total": 0}) as get_json:
            await call(NationalLawDatabaseProvider())
        return get_json.call_args.args[1], get_json.call_args.kwargs["json"]

    async def test_list(self):
        query = FlkQuery(categories=flk.LOCAL_REGULATIONS, lawmakers=(170,))
        url, payload = await self.payload(lambda p: p.search(query, 2))
        self.assertTrue(url.endswith("/law-search/search/list"))
        self.assertEqual(payload, {
            "searchRange": 1, "sxrq": [], "gbrq": [], "searchType": 2, "sxx": [4, 3], "gbrqYear": [],
            "flfgCodeId": [230], "zdjgCodeId": [170], "searchContent": "",
            "orderByParam": {"order": "gbrq", "sort": "DESC"}, "pageNum": 2, "pageSize": 20})

    async def test_title_fallback(self):
        query = FlkQuery(categories=(), validity=flk.ALL_VALIDITY, keyword="某法", search_type=flk.TITLE_SEARCH)
        _, payload = await self.payload(lambda p: p.search(query, page_size=50))
        self.assertEqual((payload["searchType"], payload["sxx"], payload["flfgCodeId"], payload["searchContent"],
                          payload["pageSize"]), (1, [4, 3, 2, 1], [], "某法", 50))

    async def test_high_search(self):
        url, payload = await self.payload(lambda p: p.search_title("监狱法"))
        self.assertTrue(url.endswith("/law-search/highSearch/highSearch"))
        self.assertEqual(payload, {
            "dataList": [{"fieldName": "title", "values": ["监狱法"], "link": 0, "searchType": 1, "index": 0}],
            "orderByParam": {}, "pageNum": 1, "pageSize": 20})

    def test_page(self):
        page = NationalLawDatabaseProvider._page({"total": 1, "rows": [{
            "bbbs": "abc", "title": "中华人民共和国<em>监狱</em>法", "zdjgName": "全国人大常委会",
            "gbrq": "2012-10-26", "sxrq": "2013-01-01", "flxz": "法律", "flfgCodeId": 120}]})
        item = page.items[0]
        self.assertEqual((page.total, item.id, item.title, item.folder, item.publication_date),
                         (1, "abc", "中华人民共和国监狱法", "法律", "2012-10-26"))


class FakeProvider(Provider):
    """监狱法返回 fixture 里的 Word 原文，其余的下载失败。"""

    async def fetch_document(self, item: LawItem) -> Path:
        if item.short_title != "监狱法":
            raise TimeoutError()
        return FIXTURES / "监狱法.docx"


PRISON_LAW = "中华人民共和国监狱法"


def item(title, date="2012-10-26", folder="法律"):
    return LawItem(id=title, title=title, released_by="", folder=folder, publication_date=date)


class PipelineTest(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        patcher = mock.patch.object(pipeline, "OUT_DIR", self.out)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    async def test_run(self):
        result = await pipeline.run(FakeProvider(), [item(PRISON_LAW), item("某条例")], jobs=2)
        self.assertEqual(result.written, [self.out / "法律/监狱法(2012-10-26).md"])
        want = (FIXTURES / "监狱法.md").read_text(encoding="utf-8").strip()
        self.assertEqual(result.written[0].read_text(encoding="utf-8").strip(), want)
        # 超时之类的异常 str() 是空的，用 repr
        self.assertEqual(result.failures, [("某条例", "下载失败：TimeoutError()")])

    async def test_place(self):
        place = lambda i: Path("北京地方法规/地方性法规/北京") / pipeline.item_filename(i)  # noqa: E731
        result = await pipeline.run(FakeProvider(), [item(PRISON_LAW)], place=place)
        self.assertEqual(result.written, [self.out / "北京地方法规/地方性法规/北京/监狱法(2012-10-26).md"])

    async def test_run_pages(self):
        pages = {1: [item("国务院关于修改部分行政法规的决定"), item(PRISON_LAW)], 2: [item(PRISON_LAW, "2000-01-01")], 3: []}
        requested = []

        async def list_page(n):
            requested.append(n)
            return Page(total=3, items=pages[n])

        with mock.patch.object(pipeline, "known_laws", return_value={"监狱法": {"2000-01-01"}}):
            result = await pipeline.run_pages(FakeProvider(), list_page)
        # 决定不下载，2000 年的版本已收录
        self.assertEqual([p.name for p in result.written], ["监狱法(2012-10-26).md"])
        self.assertEqual(requested, [1, 2, 3])

    async def test_run_pages_limit(self):
        async def list_page(n):
            return Page(total=2, items=[item(PRISON_LAW), item("某条例")])

        with mock.patch.object(pipeline, "known_laws", return_value={}):
            result = await pipeline.run_pages(FakeProvider(), list_page, limit=1)
        self.assertEqual(len(result.written) + len(result.failures), 1)
