#!/usr/bin/env python3
"""Tests for chatgpt_image.py with a fake clipboard (no browser, no display, no real clipboard).

Run: python3 chatgpt_image_test.py
"""
import io
import json
import os
import struct
import sys
import tempfile
import unittest
import zlib
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import chatgpt_image as C  # noqa: E402


def tiny_png(width, height):
    """A valid PNG header plus a minimal body; only the IHDR size matters to the script."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    chunk = lambda kind, data: (struct.pack(">I", len(data)) + kind + data
                                + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IEND", b"")


class FakeClipboard:
    def __init__(self, data=None):
        self.data = data
        self.cleared = 0

    def has_png(self):
        return self.data is not None

    def read_png(self):
        return self.data

    def clear(self):
        self.cleared += 1
        self.data = None

    def problems(self):
        return []


class Args:
    def __init__(self, **kw):
        self.name = kw.get("name", "image")
        self.out = kw.get("out")
        self.prompt = kw.get("prompt")
        self.chat_url = kw.get("chat_url")


class ChatgptImageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.env = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env)

    def export(self, clip, **kw):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = C.export(Args(**kw), clip, out_root=self.tmp, today="2026-01-02")
        return rc, json.loads(buf.getvalue().strip().splitlines()[-1])

    def test_slugify(self):
        self.assertEqual(C.slugify("Bakery Hero, Warm Light!"), "bakery-hero-warm-light")
        self.assertEqual(C.slugify("***"), "image")
        self.assertEqual(len(C.slugify("a" * 200)), 60)

    def test_png_size(self):
        self.assertEqual(C.png_size(tiny_png(1254, 941)), (1254, 941))
        self.assertIsNone(C.png_size(b"GIF89a not a png at all......"))

    def test_export_writes_png_and_sidecar_then_clears(self):
        clip = FakeClipboard(tiny_png(800, 450))
        rc, info = self.export(clip, name="Gym Poster", prompt="a quiet gym at dawn",
                               chat_url="https://chatgpt.com/c/0f0f0f0f")
        self.assertEqual(rc, 0)
        self.assertTrue(info["ok"])
        self.assertEqual(info["path"], os.path.join(self.tmp, "2026-01-02", "gym-poster.png"))
        self.assertEqual((info["width"], info["height"]), (800, 450))
        with open(info["path"], "rb") as fh:
            self.assertEqual(fh.read(), tiny_png(800, 450))
        with open(os.path.join(self.tmp, "2026-01-02", "gym-poster.json")) as fh:
            side = json.load(fh)
        self.assertEqual(side["prompt"], "a quiet gym at dawn")
        self.assertEqual(side["chat_url"], "https://chatgpt.com/c/0f0f0f0f")
        self.assertEqual(clip.cleared, 1)

    def test_export_never_overwrites(self):
        paths = []
        for _ in range(3):
            rc, info = self.export(FakeClipboard(tiny_png(10, 10)), name="cake")
            paths.append(os.path.basename(info["path"]))
        self.assertEqual(paths, ["cake.png", "cake-2.png", "cake-3.png"])

    def test_export_exact_out_path(self):
        out = os.path.join(self.tmp, "site", "public", "hero.png")
        rc, info = self.export(FakeClipboard(tiny_png(20, 10)), out=out)
        self.assertEqual(info["path"], out)
        self.assertTrue(os.path.isfile(out))

    def test_export_refuses_empty_clipboard(self):
        rc, info = self.export(FakeClipboard(None))
        self.assertEqual(rc, 1)
        self.assertFalse(info["ok"])
        self.assertIn("real mouse click", info["error"])
        self.assertEqual(os.listdir(self.tmp), [])

    def test_export_refuses_non_png(self):
        rc, info = self.export(FakeClipboard(b"definitely not a png image body"))
        self.assertEqual(rc, 1)
        self.assertIn("not a PNG", info["error"])

    def test_config_from_environment(self):
        os.environ["CHATGPT_IMAGE_PROJECT_URL"] = "https://chatgpt.com/g/g-p-1a2b3c4d/project"
        os.environ["CHATGPT_IMAGE_DIR"] = os.path.join(self.tmp, "imgs")
        cfg = C.config()
        self.assertEqual(cfg["project_url"], "https://chatgpt.com/g/g-p-1a2b3c4d/project")
        self.assertEqual(cfg["start_url"], cfg["project_url"])
        self.assertEqual(cfg["out_dir"], os.path.join(self.tmp, "imgs"))

    def test_config_without_project_starts_a_plain_chat(self):
        os.environ.pop("CHATGPT_IMAGE_PROJECT_URL", None)
        os.environ.pop("CHATGPT_IMAGE_DIR", None)
        cfg = C.config()
        self.assertIsNone(cfg["project_url"])
        self.assertEqual(cfg["start_url"], "https://chatgpt.com/")
        self.assertEqual(cfg["out_dir"], os.path.expanduser("~/chatgpt-images"))

    def test_config_rejects_a_project_url_off_chatgpt(self):
        os.environ["CHATGPT_IMAGE_PROJECT_URL"] = "https://example.com/g/g-p-1a2b3c4d/project"
        cfg = C.config()
        self.assertIsNone(cfg["project_url"])
        self.assertTrue(any("chatgpt.com" in p for p in cfg["problems"]))

    def test_backend_choice(self):
        self.assertIsInstance(C.clipboard_for("darwin"), C.MacClipboard)
        self.assertIsInstance(C.clipboard_for("linux"), C.XClipboard)
        self.assertIsNone(C.clipboard_for("win32"))


def main():
    """unittest, plus the `RESULT: N passed, M failed` line _bin/run_all_tests.py adds up."""
    result = unittest.TextTestRunner(verbosity=1).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(ChatgptImageTest))
    failed = len(result.failures) + len(result.errors)
    print("\nRESULT: %d passed, %d failed" % (result.testsRun - failed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
