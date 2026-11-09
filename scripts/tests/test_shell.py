import io
import re
import unittest
from contextlib import redirect_stdout
from unittest import mock

from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from lawref import shell
from lawref.cli import cli

CANCEL = object()  # 按 Esc
DOWN, ENTER, ESC, SPACE = "\x1b[B", "\r", "\x1b", " "


class Script:
    """按顺序给出答案。select 写选项标题（不含 ›），checkbox 写选中的值，CANCEL 表示按 Esc。"""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.asked = []

    def _next(self, message):
        self.asked.append(message)
        if not self.answers:
            raise AssertionError(f"没有准备答案：{message}")
        answer = self.answers.pop(0)
        if answer is CANCEL:
            raise shell.Cancelled
        return answer

    def select(self, message, options):
        answer = self._next(message)
        for o in options:
            if o.title.removesuffix(" ›") == answer:
                return o.value if o.value is not None else o.title
        raise AssertionError(f"「{message}」里没有「{answer}」：{[o.title for o in options]}")

    def checkbox(self, message, options, required=False):
        return self._next(message)

    def text(self, message, default="", validate=None):
        return self._next(message)

    path = text

    def confirm(self, message, default=False):
        return self._next(message)


class ShellTest(unittest.TestCase):

    def play(self, *answers, codes=()):
        """按 answers 操作菜单，返回运行过的 laws 命令。codes 依次是这些命令的退出码，不够时为 0。"""
        script, calls, codes = Script(*answers), [], list(codes)

        def laws(*args):
            calls.append(args)
            return codes.pop(0) if codes else 0

        with mock.patch.object(shell, "prompt", script), mock.patch.object(shell, "laws", laws), \
                redirect_stdout(io.StringIO()) as out:
            shell.browse(shell.MENU)
        self.assertEqual(script.answers, [], "有答案没用上")
        self.output, self.asked = out.getvalue(), script.asked
        return calls

    def test_menu_commands_exist(self):
        """每一项都有对应的命令，命令里的 laws 子命令都存在，同一级菜单里没有重名。"""
        def walk(menu):
            titles = [item.title for item in menu.items]
            self.assertEqual(len(titles), len(set(titles)), menu.title)
            for item in menu.items:
                if isinstance(item, shell.Menu):
                    yield from walk(item)
                else:
                    yield item

        actions = list(walk(shell.MENU))
        self.assertGreater(len(actions), 20)
        for action in actions:
            self.assertTrue(callable(action.run) and action.command, action.title)
            for name in re.findall(r"laws ([a-z-]+)", action.command):
                self.assertIn(name, cli.commands, action.command)

    def test_submenus(self):
        calls = self.play("抓取", "地方性法规", "按地区下载", ["北京", "上海"], "5",
                          CANCEL,     # Esc：回到「抓取」
                          "← 返回",   # 回到主菜单
                          "退出")
        self.assertEqual(calls, [("download-dlc", "北京", "上海", "--limit", "5")])
        self.assertIn("LawRefBook 数据工具 › 抓取 › 地方性法规", self.asked)

    def test_stays_in_menu_after_action(self):
        calls = self.play("数据", "报告", "正文提到但没有收录的法律", "已失效但不知道被谁废止的法规", CANCEL, CANCEL, CANCEL)
        self.assertEqual(calls, [("report", "missing"), ("report", "expired")])

    def test_cancel_question(self):
        calls = self.play("抓取", "法律、行政法规、司法解释", "按名称下载", CANCEL, CANCEL, CANCEL, CANCEL)
        self.assertEqual(calls, [])
        self.assertIn("已取消", self.output)

    def test_lint_fix(self):
        calls = self.play("数据", "检查格式（lint）", ["--dlc", "--warnings"], True, True, CANCEL, CANCEL, codes=[1])
        self.assertEqual(calls, [("lint", "--dlc", "--warnings"), ("lint", "--dlc", "--diff"),
                                 ("lint", "--dlc", "--warnings", "--fix")])

    def test_organize_then_update(self):
        calls = self.play("抓取", "把抓取结果整理进仓库", True, False, True, CANCEL, CANCEL)
        self.assertEqual(calls, [("organize",), ("organize", "--apply"), ("db", "update")])

    def test_release_needs_typed_confirmation(self):
        with mock.patch.object(shell.releaser, "dirty_files", return_value=[]), \
                mock.patch.object(shell.releaser, "local_hash", return_value="a" * 40), \
                mock.patch.object(shell.releaser, "published_hash", return_value="b" * 40):
            calls = self.play("发布", "发布本体", "yes", "发布本体", "release", CANCEL, CANCEL)
        self.assertEqual(calls, [("release", "--main", "--channel", "alpha")])

    def test_needs_terminal(self):
        with mock.patch("sys.stdin.isatty", return_value=False), \
                mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            self.assertEqual(shell.main(), 1)
        self.assertIn("终端", err.getvalue())


class PrompterTest(unittest.TestCase):
    """真的按键：方向键、空格、回车、Esc。"""

    def ask(self, keys, method, *args, **kwargs):
        with create_pipe_input() as inp:
            inp.send_text(keys)
            return getattr(shell.Prompter(input=inp, output=DummyOutput()), method)(*args, **kwargs)

    def test_select(self):
        options = [shell.Option("甲", 1), shell.Option("乙", 2), shell.Option("丙", 3)]
        self.assertEqual(self.ask(DOWN + DOWN + ENTER, "select", "选", options), 3)
        with self.assertRaises(shell.Cancelled):
            self.ask(ESC, "select", "选", options)

    def test_checkbox(self):
        options = [shell.Option("北京", "北京"), shell.Option("天津", "天津"), shell.Option("河北", "河北")]
        self.assertEqual(self.ask(SPACE + DOWN + DOWN + SPACE + ENTER, "checkbox", "选", options), ["北京", "河北"])

    def test_text(self):
        self.assertEqual(self.ask("12" + ENTER, "text", "几部", default=""), "12")
        with self.assertRaises(shell.Cancelled):
            self.ask("\x03", "text", "几部")
