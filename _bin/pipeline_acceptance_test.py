#!/usr/bin/env python3
"""Tests for the pure parts of pipeline_acceptance: the scenario it builds and the checks it
runs on a worktree. The worktree here is a fake one in a temp dir, with a `top` subcommand
written by the test, so no git, no vault and no Claude session are involved. Run standalone:

    python3 _bin/pipeline_acceptance_test.py
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import pipeline_acceptance as P

ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def run(cmd, cwd):
    p = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return p.returncode, p.stdout.decode("utf-8", "replace").strip()


def build(root):
    for rel, content in P.scenario_files().items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(content)


TOP_CORE = '''

def top(rows, limit=5):
    agg = by_product(rows)
    return sorted(agg.items(), key=lambda kv: (%s))[:limit]
'''
TOP_CLI = '''

def cmd_top(args):
    for product, amount in top(load_rows(args.file), args.limit):
        print("%s\\t%.2f" % (product, amount))
'''
TOP_TEST = '''import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from reportcli.core import top


class TestTop(unittest.TestCase):
    def test_limit(self):
        rows = [{"product": "a", "amount": 1.0}, {"product": "b", "amount": 2.0}]
        self.assertEqual(top(rows, 1), [("b", 2.0)])
'''


def add_top(root, key):
    """Give the fake worktree a `top` subcommand sorted by `key`, plus one more test."""
    with open(os.path.join(root, "reportcli", "core.py"), "a") as fh:
        fh.write(TOP_CORE % key)
    cli = os.path.join(root, "reportcli", "cli.py")
    src = open(cli).read()
    src = src.replace("from .core import load_rows, total, by_product",
                      "from .core import load_rows, total, by_product, top")
    src = src.replace("\n\ndef main(argv=None):", TOP_CLI + "\n\ndef main(argv=None):")
    src = src.replace("    args = ap.parse_args(argv)",
                      '    p = sub.add_parser("top", help="highest amounts")\n'
                      '    p.add_argument("file")\n'
                      '    p.add_argument("--limit", type=int, default=5)\n'
                      '    p.set_defaults(func=cmd_top)\n\n'
                      '    args = ap.parse_args(argv)')
    with open(cli, "w") as fh:
        fh.write(src)
    with open(os.path.join(root, "tests", "test_top.py"), "w") as fh:
        fh.write(TOP_TEST)


def verdicts(root, tie):
    return {name: cond for name, cond, _ in P.check_code(root, tie, run)}


def test_scenario_builds_and_passes():
    files = P.scenario_files()
    check("the scenario has the package, its tests and the sample data",
          {"reportcli/core.py", "reportcli/cli.py", "tests/test_core.py", "sales.tsv"} <= set(files))
    check("the starting code has no top subcommand", '"top"' not in files["reportcli/cli.py"])
    check("the convention is not in the code", "tie" not in "".join(files.values()).lower())
    root = tempfile.mkdtemp(prefix="pipeline-")
    try:
        build(root)
        rc, out = run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], root)
        check("the three starting tests pass", rc == 0 and P.tests_ran(out) == 3, out[-200:])
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_check_code_on_fake_worktrees():
    scratch = tempfile.mkdtemp(prefix="pipeline-")
    try:
        tie = os.path.join(scratch, "tie.tsv")
        with open(tie, "w") as fh:
            fh.write(P.TIE_DATA)

        good = os.path.join(scratch, "good")
        build(good)
        add_top(good, "-kv[1], kv[0]")
        v = verdicts(good, tie)
        check("a correct top passes every code check", all(v.values()), v)

        naive = os.path.join(scratch, "naive")
        build(naive)
        add_top(naive, "-kv[1]")
        v = verdicts(naive, tie)
        check("sorting by amount alone fails the acid test", not v["ALPHABETICAL TIE-BREAK (the acid test)"], v)
        check("and only the acid test", sum(1 for c in v.values() if not c) == 1, v)

        bare = os.path.join(scratch, "bare")
        build(bare)
        v = verdicts(bare, tie)
        check("a worktree without top fails its existence and the command",
              not v["the top subcommand exists"] and not v["the top command works"], v)
        check("an unchanged suite is not counted as new tests",
              not v["there are new tests (more than the initial 3)"], v)
        check("products stays alphabetical in the untouched scenario",
              v["no regression in `products` (still alphabetical)"], v)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def test_parsers():
    porcelain = ("worktree /tmp/demo/reportcli\nHEAD 1111111\nbranch refs/heads/main\n\n"
                 "worktree /tmp/demo/.wt-top-4f2a9c1e\nHEAD 2222222\nbranch refs/heads/feat/top-4f2a9c1e\n")
    check("worktrees exclude the main checkout",
          P.parse_worktrees(porcelain, "/tmp/demo/reportcli") == ["/tmp/demo/.wt-top-4f2a9c1e"])
    check("no worktrees in empty output", P.parse_worktrees("", "/tmp/x") == [])
    check("the test count is read from unittest", P.tests_ran("...\nRan 5 tests in 0.01s\n\nOK") == 5)
    check("no count when unittest printed none", P.tests_ran("boom") is None)
    check("the first TSV column is read", P.tsv_first_column("a\t1.00\nnoise\nb\t2.00") == ["a", "b"])
    staged = "add 'reportcli/top.py'\nadd '.env'\nadd 'docs/plan.md'\n"
    check("leaks are named", P.leaked(staged) == [".env", "plan.md"], P.leaked(staged))
    check("clean staging leaks nothing", P.leaked("add 'reportcli/core.py'\n") == [])
    times = {"a": 5.0, "b": 15.0, "c": 20.0}
    check("only files newer than setup count, the planted note excluded",
          P.newer_than(["a", "b", "c"], 10.0, getmtime=times.get, exclude=("c",)) == ["b"])
    check("the planted note lives in 30-Knowledge under a stable slug",
          P.note_rel("2026-01-02") == "30-Knowledge/2026-01-02-decision-reportcli-deterministic-ordering.md")


def test_never_a_unit_test_file():
    check("the acceptance tool is not named like a unit test",
          not os.path.basename(P.__file__).endswith("_test.py"))


def main():
    for t in (test_scenario_builds_and_passes, test_check_code_on_fake_worktrees, test_parsers,
              test_never_a_unit_test_file):
        print("\n== %s ==" % t.__name__)
        try:
            t()
        except Exception as exc:
            check("%s ran without raising" % t.__name__, False, repr(exc))
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
