#!/usr/bin/env python3
"""Tests for x_items.py, the JSONL collector of tweets read through the browser.

Run: python3 x_items_test.py
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "x_items.py")


def rec(sid, handle="bookclub_example", **kw):
    out = {"url": "https://x.com/%s/status/%s" % (handle, sid), "handle": handle, "name": "Book Club",
           "text": "Chapter %s notes" % sid, "kind": "post", "full": False}
    out.update(kw)
    return out


class XItemsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.file = os.path.join(self.tmp, "items.jsonl")

    def run_it(self, *args, stdin=""):
        return subprocess.run([sys.executable, SCRIPT, *args], input=stdin, capture_output=True,
                              text=True, timeout=30)

    def add(self, *records):
        return self.run_it("add", self.file, stdin="\n".join(json.dumps(r) for r in records) + "\n")

    def items(self):
        with open(self.file) as fh:
            return [json.loads(l) for l in fh if l.strip()]

    def test_add_dedupes_by_status_id_and_sorts_newest_first(self):
        r = self.add(rec("100"), rec("300"), rec("200"), rec("300"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("merged 4, total 3, pending 3", r.stdout)
        self.assertEqual([i["url"].rsplit("/", 1)[1] for i in self.items()], ["300", "200", "100"])

    def test_relative_url_is_made_absolute(self):
        self.add(dict(rec("42"), url="/bookclub_example/status/42"))
        self.assertEqual(self.items()[0]["url"], "https://x.com/bookclub_example/status/42")

    def test_merge_keeps_longest_text_and_upgrades_full(self):
        self.add(rec("7", text="Short text"))
        self.add(rec("7", text="Short", full=False))
        self.assertEqual(self.items()[0]["text"], "Short text")
        self.add(rec("7", text="Short text, now complete with the whole paragraph", full=True,
                     time="2026-01-02T10:00:00Z"))
        item = self.items()[0]
        self.assertTrue(item["full"])
        self.assertEqual(item["time"], "2026-01-02T10:00:00Z")
        self.add(rec("7", full=False, text=""))
        self.assertTrue(self.items()[0]["full"])

    def test_empty_values_never_overwrite(self):
        self.add(rec("8", title="Reading list", counts={"likes": 3}))
        self.add(rec("8", title="", counts={}))
        item = self.items()[0]
        self.assertEqual(item["title"], "Reading list")
        self.assertEqual(item["counts"], {"likes": 3})

    def test_pending_lists_only_incomplete(self):
        self.add(rec("1", full=True), rec("2"), rec("3"))
        r = self.run_it("pending", self.file)
        self.assertEqual(r.stdout.split(), ["https://x.com/bookclub_example/status/3",
                                            "https://x.com/bookclub_example/status/2"])

    def test_render_markdown(self):
        self.add(rec("5", kind="article", title="Spring picks", text="line one\nline two",
                     quoted_url="https://x.com/other_example/status/4"))
        r = self.run_it("render", self.file, "--md")
        self.assertIn("(https://x.com/bookclub_example/status/5)", r.stdout)
        self.assertIn("**Spring picks**", r.stdout)
        self.assertIn("  line two", r.stdout)
        self.assertIn("Quoted: https://x.com/other_example/status/4", r.stdout)

    def test_stats(self):
        self.add(rec("1", full=True), rec("2", kind="reply"), rec("3", handle="gym_example"))
        r = self.run_it("stats", self.file)
        self.assertIn("total 3 full 1", r.stdout)
        self.assertIn("'reply': 1", r.stdout)

    def test_record_without_status_url_is_refused(self):
        r = self.add({"url": "https://x.com/bookclub_example", "text": "profile, not a tweet"})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("status url", r.stderr)
        self.assertFalse(os.path.exists(self.file))

    def test_missing_file_reads_as_empty(self):
        r = self.run_it("pending", self.file)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, "")


def main():
    """unittest, plus the `RESULT: N passed, M failed` line _bin/run_all_tests.py adds up."""
    result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(XItemsTest))
    failed = len(result.failures) + len(result.errors)
    print("\nRESULT: %d passed, %d failed" % (result.testsRun - failed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
