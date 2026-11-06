"""在仓库根目录运行：.venv/bin/python -m unittest discover scripts/tests"""
import sys
import unittest
from pathlib import Path

from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from providers import net  # noqa: E402


class GetJsonTest(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.calls = 0
        self.bad_times = 0
        self.backoff = net.BACKOFF, net.BLOCKED_BACKOFF
        net.BACKOFF = net.BLOCKED_BACKOFF = 0

        async def handler(request):
            self.calls += 1
            if self.calls <= self.bad_times:
                return web.Response(text="")  # 被限流时 200 + 空白
            return web.json_response({"ok": True})

        app = web.Application()
        app.router.add_post("/", handler)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        self.url = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/"

    async def asyncTearDown(self):
        net.BACKOFF, net.BLOCKED_BACKOFF = self.backoff
        await self.runner.cleanup()

    async def test_retries_non_json(self):
        self.bad_times = 2
        async with net.client():
            self.assertEqual(await net.get_json("POST", self.url, json={}), {"ok": True})
        self.assertEqual(self.calls, 3)

    async def test_gives_up_as_network_error(self):
        self.bad_times = 100
        async with net.client():
            with self.assertRaises(net.NetworkError):
                await net.get_json("POST", self.url, json={})
        self.assertEqual(self.calls, net.RETRIES + 1)


if __name__ == "__main__":
    unittest.main()
