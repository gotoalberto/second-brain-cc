#!/usr/bin/env python3
"""Acceptance test for the whole agent pipeline, run by hand in a FRESH Claude Code session.

  pipeline_acceptance.py setup   [--dir DIR]   build the scenario and print what to type
  pipeline_acceptance.py check   [--dir DIR]   verify the result objectively
  pipeline_acceptance.py cleanup [--dir DIR]   remove the scenario and the note it planted

The scenario is a tiny CLI repo, `reportcli`, created under DIR (default ~/git/pipeline-demo;
the /task skill puts its worktrees next to the repo, as DIR/.wt-*). `setup` also plants one
convention in the vault, through vw.py: sorted listings break ties on amount by product name.
That convention lives ONLY in the vault, not in the code and not in the prompt you type. If
the code the session produces honours it, context travelled from the vault to the executor.

The planted note is a test fixture, so `cleanup` deletes it instead of superseding it, and
reindexes. The name ends in `_acceptance`, not `_test`, so run_all_tests.py never runs it:
it needs a person, a fresh session and a real vault. Its pure parts are covered by
pipeline_acceptance_test.py.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DIR = os.path.join(os.path.expanduser("~"), "git", "pipeline-demo")
STAMP = os.path.join(B.STATE, "pipeline-acceptance.json")
NOTE_SLUG = "decision-reportcli-deterministic-ordering"
NOTE_TITLE = "reportcli sorted listings break ties by product name"
TIE_DATA = "product\tamount\nzeta\t10.00\nalpha\t10.00\nmonitor\t180.00\nbeta\t10.00\n"
TIE_EXPECTED = ["monitor", "alpha", "beta", "zeta"]
LEAK_NAMES = (".env", ".env.local", "CONTEXT-PACK", "BRAIN-PROTOCOL", "plan.md")

PROMPT = ("/task add a `top` subcommand showing the N products with the highest amount, "
          "with N=5 by default and a --limit option, plus its tests")


# ------------------------------------------------------------------ the scenario
def scenario_files():
    """Relative path -> content of the starting repo. Three passing tests, no `top`."""
    return {
        "reportcli/__init__.py": '"""reportcli: quick reports over sales files."""\n',
        "reportcli/errors.py": 'class ReportError(Exception):\n    """reportcli business error."""\n',
        "reportcli/core.py": '''import csv
from .errors import ReportError


def load_rows(path):
    """Read a sales file. Returns a list of dicts with 'product' and 'amount'."""
    try:
        with open(path, newline="") as fh:
            rows = list(csv.DictReader(fh, delimiter="\\t"))
    except FileNotFoundError:
        raise ReportError("file not found: %s" % path)
    out = []
    for i, row in enumerate(rows, start=2):
        try:
            out.append({"product": row["product"], "amount": float(row["amount"])})
        except (KeyError, ValueError):
            raise ReportError("invalid row %d in %s" % (i, path))
    return out


def total(rows):
    """Sum of amounts."""
    return sum(r["amount"] for r in rows)


def by_product(rows):
    """Aggregates amounts by product."""
    agg = {}
    for r in rows:
        agg[r["product"]] = agg.get(r["product"], 0.0) + r["amount"]
    return agg
''',
        "reportcli/cli.py": '''import argparse
import sys

from .core import load_rows, total, by_product
from .errors import ReportError


def cmd_total(args):
    rows = load_rows(args.file)
    print("total\\t%.2f" % total(rows))


def cmd_products(args):
    rows = load_rows(args.file)
    for product, amount in sorted(by_product(rows).items()):
        print("%s\\t%.2f" % (product, amount))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="reportcli")
    sub = ap.add_subparsers(dest="cmd")
    sub.required = True

    p = sub.add_parser("total", help="total amount")
    p.add_argument("file")
    p.set_defaults(func=cmd_total)

    p = sub.add_parser("products", help="amount by product")
    p.add_argument("file")
    p.set_defaults(func=cmd_products)

    args = ap.parse_args(argv)
    try:
        args.func(args)
    except ReportError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
''',
        "tests/test_core.py": '''import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from reportcli.core import load_rows, total, by_product
from reportcli.errors import ReportError

DATA = "product\\tamount\\nkeyboard\\t25.50\\nmouse\\t10.00\\nkeyboard\\t25.50\\n"


def temp_file(content=DATA):
    fh = tempfile.NamedTemporaryFile("w", suffix=".tsv", delete=False)
    fh.write(content)
    fh.close()
    return fh.name


class TestCore(unittest.TestCase):
    def test_total(self):
        self.assertAlmostEqual(total(load_rows(temp_file())), 61.0)

    def test_by_product(self):
        agg = by_product(load_rows(temp_file()))
        self.assertAlmostEqual(agg["keyboard"], 51.0)

    def test_missing_file(self):
        with self.assertRaises(ReportError):
            load_rows("/no/such/file.tsv")


if __name__ == "__main__":
    unittest.main()
''',
        "README.md": '''# reportcli

Quick reports over TSV sales files.

    python3 -m reportcli.cli total sales.tsv
    python3 -m reportcli.cli products sales.tsv

Tests: `python3 -m unittest discover -s tests -v`
''',
        ".gitignore": "__pycache__/\n*.pyc\n",
        "sales.tsv": "product\tamount\nkeyboard\t25.50\nmouse\t10.00\nkeyboard\t25.50\nmonitor\t180.00\n",
    }


def convention_note_body():
    """The body of the planted note. vw.py adds the frontmatter."""
    return """## What was decided

Any `reportcli` subcommand that sorts results by amount sorts by **amount descending and, on
equal amounts, by product name ascending**.

## Why

Its output is compared line by line across runs of the same day. On ties, the order of a sort
by amount alone depends on insertion order and produces phantom differences that cost time to
investigate. Breaking ties by name makes the output reproducible.

## Consequences

- `sorted(agg.items(), key=lambda kv: -kv[1])` is not enough.
- It applies to future subcommands, not only the current ones.
- `products` sorts alphabetically and stays as it is: it does not sort by amount.
- Listings print TSV lines with two decimals and no header, like the existing commands.
"""


def note_rel(day):
    return "30-Knowledge/%s-%s.md" % (day, NOTE_SLUG)


# ------------------------------------------------------------------ pure checks
def parse_worktrees(porcelain, repo):
    """Worktree paths from `git worktree list --porcelain`, the main checkout excluded."""
    main = os.path.realpath(repo)
    out = []
    for line in (porcelain or "").splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):].strip()
            if os.path.realpath(path) != main:
                out.append(path)
    return out


def tsv_first_column(out):
    return [l.split("\t")[0] for l in (out or "").splitlines() if "\t" in l]


def tests_ran(out):
    """How many tests unittest says it ran, or None."""
    for line in (out or "").splitlines():
        if line.startswith("Ran "):
            try:
                return int(line.split()[1])
            except (IndexError, ValueError):
                return None
    return None


def leaked(dry_run_add):
    """Names from LEAK_NAMES that `git add -A --dry-run` would stage."""
    return [n for n in LEAK_NAMES
            if ("'%s'" % n) in dry_run_add or ("/%s'" % n) in dry_run_add]


def newer_than(paths, t0, getmtime=os.path.getmtime, exclude=()):
    return [p for p in paths if p not in exclude and getmtime(p) > t0]


def check_code(wt, tie_file, run):
    """The checks on the code the session produced. `run(cmd, cwd) -> (rc, output)`.

    Returns [(name, ok, detail)]. Needs no git and no vault, so it runs on a fake worktree."""
    res = []
    core = os.path.join(wt, "reportcli", "core.py")
    cli = os.path.join(wt, "reportcli", "cli.py")
    src = ""
    for f in (core, cli):
        if os.path.exists(f):
            src += open(f, errors="replace").read()
    res.append(("the top subcommand exists", '"top"' in src.replace("'", '"'),
                "no `top` subcommand in reportcli/"))
    rc, out = run([sys.executable, "-m", "reportcli.cli", "top", tie_file], wt)
    lines = tsv_first_column(out)
    res.append(("the top command works", rc == 0 and bool(lines), out[:200]))
    res.append(("ALPHABETICAL TIE-BREAK (the acid test)", lines[:4] == TIE_EXPECTED,
                "got %s, expected %s" % (lines[:4], TIE_EXPECTED)))
    first = out.splitlines()[0] if out else ""
    res.append(("output has no header and is TSV with 2 decimals",
                bool(out) and "product" not in first and ".00" in out, first))
    rc, out = run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], wt)
    res.append(("the suite passes", rc == 0, out[-300:]))
    n = tests_ran(out)
    res.append(("there are new tests (more than the initial 3)", bool(n) and n > 3,
                "ran %s" % n))
    rc, out = run([sys.executable, "-m", "reportcli.cli", "products", os.path.join(wt, "sales.tsv")], wt)
    res.append(("no regression in `products` (still alphabetical)",
                out.splitlines()[:3] == ["keyboard\t51.00", "monitor\t180.00", "mouse\t10.00"], out[:120]))
    return res


# ------------------------------------------------------------------ adapters
def git():
    g = shutil.which("git")
    if not g:
        sys.exit("git is not on PATH")
    return g


def sh(cmd, cwd=None, stdin=None):
    p = subprocess.run(cmd, cwd=cwd, input=stdin.encode() if stdin is not None else None,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return p.returncode, p.stdout.decode("utf-8", "replace").strip()


def load_stamp():
    try:
        with open(STAMP) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def resolve_dir(arg):
    if arg:
        return os.path.abspath(os.path.expanduser(arg))
    return load_stamp().get("dir") or DEFAULT_DIR


def reindex():
    sh([sys.executable, os.path.join(HERE, "index_vault.py")])


def remove_scenario(base):
    """Remove the repo, every worktree git knows about, and any DIR/.wt-* left behind."""
    repo = os.path.join(base, "reportcli")
    if os.path.isdir(os.path.join(repo, ".git")):
        _, out = sh([git(), "worktree", "list", "--porcelain"], cwd=repo)
        for wt in parse_worktrees(out, repo):
            sh([git(), "worktree", "remove", "--force", wt], cwd=repo)
            shutil.rmtree(wt, ignore_errors=True)
        sh([git(), "worktree", "prune"], cwd=repo)
    shutil.rmtree(repo, ignore_errors=True)
    if os.path.isdir(base):
        for name in os.listdir(base):
            if name.startswith(".wt-"):
                shutil.rmtree(os.path.join(base, name), ignore_errors=True)


def remove_note(stamp):
    rel = stamp.get("note")
    if not rel:
        return False
    path = os.path.join(B.VAULT, rel)
    if os.path.exists(path):
        os.remove(path)
        reindex()
        return True
    return False


def setup(base):
    old = load_stamp()
    remove_scenario(base)
    if old.get("dir") and old["dir"] != base:
        remove_scenario(old["dir"])
    remove_note(old)

    repo = os.path.join(base, "reportcli")
    for rel, content in scenario_files().items():
        path = os.path.join(repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(content)
    g = git()
    sh([g, "init", "-q", "."], cwd=repo)
    sh([g, "checkout", "-q", "-b", "main"], cwd=repo)
    sh([g, "config", "user.email", "pipeline-demo@example.com"], cwd=repo)
    sh([g, "config", "user.name", "Pipeline Demo"], cwd=repo)
    sh([g, "add", "-A"], cwd=repo)
    sh([g, "commit", "-qm", "reportcli: total and products commands"], cwd=repo)
    rc, _ = sh([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=repo)

    rel = note_rel(time.strftime("%Y-%m-%d"))
    nrc, nout = sh([sys.executable, os.path.join(HERE, "vw.py"), "new", rel, "--title", NOTE_TITLE,
                    "--type", "decision", "--project", "reportcli", "--area", "tooling",
                    "--tag", "reportcli", "--tag", "ordering", "--tag", "convention",
                    "--provenance", "planted by pipeline_acceptance.py setup", "--force"],
                   stdin=convention_note_body())
    if nrc != 0:
        print("could not plant the convention note: %s" % nout)
        return 1
    reindex()
    os.makedirs(os.path.dirname(STAMP), exist_ok=True)
    B.atomic_write(STAMP, json.dumps({"dir": base, "note": rel, "t0": time.time()}))

    print("Scenario built at %s" % repo)
    print("  starting tests: %s" % ("3 passing" if rc == 0 else "FAILING"))
    print("  convention planted ONLY in the vault: %s" % rel)
    print("  (ties on amount break by product name; the prompt below does not mention it)\n")
    print("Now open a FRESH Claude Code session in %s and type:\n" % repo)
    print("  %s\n" % PROMPT)
    print("When it finishes, come back and run:")
    print("  %s %s check" % (sys.executable, os.path.abspath(__file__)))
    print("and afterwards, to remove the scenario and the planted note:")
    print("  %s %s cleanup" % (sys.executable, os.path.abspath(__file__)))
    return 0


def check(base):
    repo = os.path.join(base, "reportcli")
    stamp = load_stamp()
    if not os.path.isdir(repo):
        print("No scenario at %s. Run setup first." % repo)
        return 1
    t0 = float(stamp.get("t0") or 0)
    note = os.path.join(B.VAULT, stamp["note"]) if stamp.get("note") else ""
    ok, fail = [], []

    def chk(name, cond, detail=""):
        (ok if cond else fail).append(name)
        print("  %s %s%s" % ("✓" if cond else "✗", name,
                             ("\n      → " + str(detail)) if detail and not cond else ""))

    g = git()
    print("\n== 1. Isolation ==")
    _, out = sh([g, "worktree", "list", "--porcelain"], cwd=repo)
    wts = parse_worktrees(out, repo)
    chk("a worktree was created for the task", bool(wts), out)
    wt = wts[0] if wts else repo
    _, dirty = sh([g, "status", "--porcelain"], cwd=repo)
    chk("the main checkout was left untouched", not dirty.strip(), dirty[:200])
    _, branch = sh([g, "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo)
    chk("the main checkout is still on main", branch == "main", branch)

    print("\n== 2. The convention that only lived in the vault, and quality ==")
    tie = os.path.join(B.STATE, "pipeline-acceptance-tie.tsv")
    B.atomic_write(tie, TIE_DATA)
    for name, cond, detail in check_code(wt, tie, lambda cmd, cwd: sh(cmd, cwd=cwd)):
        chk(name, cond, detail)

    print("\n== 3. The system did its job ==")

    def md(folder):
        out = []
        for dp, _, fns in os.walk(os.path.join(B.VAULT, folder)):
            out += [os.path.join(dp, f) for f in fns if f.endswith(".md")]
        return out

    packs = newer_than(md("60-Context-Packs"), t0)
    chk("context-scout wrote a pack", bool(packs), "none new")
    if packs:
        text = " ".join(open(p, errors="replace").read().lower() for p in packs)
        chk("the pack picked up the vault's convention",
            any(k in text for k in ("tie-break", "tie break", "tiebreak", "break ties", NOTE_SLUG)),
            packs[0])
    notes = newer_than(md("30-Knowledge") + md("10-Projects"), t0, exclude=(note,))
    chk("the librarian wrote or updated notes", bool(notes), "no new note since setup")
    traces = newer_than(md("50-Sessions"), t0)
    chk("a trace of the subagents was left", bool(traces), "no trace")

    print("\n== 4. Nothing leaked into the repository ==")
    _, staged = sh([g, "add", "-A", "--dry-run"], cwd=wt)
    bad = leaked(staged)
    chk("neither .env nor Brain artifacts are committable", not bad, "would slip in: %s" % bad)

    print("\n" + "=" * 62)
    print("pipeline: %d passed, %d failed" % (len(ok), len(fail)))
    if fail:
        print("\nFailed:")
        for f in fail:
            print("  ✗ " + f)
        print("\nThe one that matters is the ALPHABETICAL TIE-BREAK: if it fails and the rest")
        print("pass, the pipeline works but the vault's context never reached the executor.")
    else:
        print("\nFull pipeline verified end to end.")
    return 1 if fail else 0


def cleanup(base):
    stamp = load_stamp()
    remove_scenario(base)
    removed = remove_note(stamp)
    for p in (STAMP, os.path.join(B.STATE, "pipeline-acceptance-tie.tsv")):
        try:
            os.remove(p)
        except OSError:
            pass
    try:
        os.rmdir(base)      # only when empty: DIR may be a folder the user already had
    except OSError:
        pass
    print("removed the scenario under %s%s" % (base, " and the planted note" if removed else ""))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pipeline_acceptance.py",
                                 description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=("setup", "check", "cleanup"))
    ap.add_argument("--dir", default="", help="where the scenario lives (default %s)" % DEFAULT_DIR)
    a = ap.parse_args(argv)
    if not B.enabled():
        print("vault unavailable")
        return 1
    base = resolve_dir(a.dir)
    return {"setup": setup, "check": check, "cleanup": cleanup}[a.cmd](base)


if __name__ == "__main__":
    sys.exit(main())
