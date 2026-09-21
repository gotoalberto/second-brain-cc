#!/usr/bin/env python3
"""Tests for routine_requires — the preflight that refuses a routine this machine cannot run.

Every probe is a fake (no real PATH lookup, no real disk outside a temporary folder), and `--fix`
gets a fake `run`, so no real `git clone` ever happens. Every path and name below is invented.
Run standalone:

    python3 _bin/routine_requires_test.py
"""
import contextlib
import io
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import routine_requires as R

ok, fail = [], []
TMP = []

VAULT, HOME = "/vault", "/home/someone"


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


class FakeProbe(object):
    """A machine made of sets: programs on PATH, directories, files, executables."""

    def __init__(self, programs=(), dirs=(), files=(), execs=()):
        self.programs, self.dirs, self.files, self.execs = set(programs), set(dirs), set(files), set(execs)

    def which(self, name):
        return "/usr/bin/" + name if name in self.programs else None

    def is_dir(self, path):
        return path in self.dirs

    def exists(self, path):
        return path in self.dirs or path in self.files

    def is_exec(self, path):
        return path in self.execs


def routine(front):
    return "---\nid: r\n%s---\n\nbody\n" % front


FULL = routine('requires: {"repos": ["~/code/tool", {"path": "repos/data", "url": "https://example.com/data.git"}], '
               '"programs": ["jq"], "paths": ["~/input.csv"]}\n'
               'agent_args: ["--add-dir", "~/work", "--allowedTools", '
               '"Read,Bash(python3 ~/Brain/_bin/query.py:*),Bash(bun run --cwd ~/code/cli src/main.ts:*),'
               'Bash(/opt/tools/bin/thing --flag:*)"]\n')


def test_requirements():
    items, problem = R.requirements(FULL)
    kinds = [(k, t) for k, t, _h in items]
    check("no parse problem for a well-formed routine", problem is None, problem)
    check("declared repos, programs and paths are all listed",
          ("repo", "~/code/tool") in kinds and ("repo", "repos/data") in kinds and ("program", "jq") in kinds
          and ("path", "~/input.csv") in kinds, kinds)
    check("a repo's clone url travels as its hint",
          [h for k, t, h in items if t == "repos/data"] == ["https://example.com/data.git"], items)
    check("an --add-dir directory is required", ("dir", "~/work") in kinds, kinds)
    check("the program of every allowed Bash command is required",
          ("program", "python3") in kinds and ("program", "bun") in kinds, kinds)
    check("an absolute program path is required as such", ("program", "/opt/tools/bin/thing") in kinds, kinds)
    check("a script path in an allowed command is required", ("path", "~/Brain/_bin/query.py") in kinds, kinds)
    check("a --cwd directory in an allowed command is required", ("dir", "~/code/cli") in kinds, kinds)
    check("nothing is listed twice", len(kinds) == len(set(kinds)), kinds)
    check("no frontmatter requires nothing", R.requirements("just a prompt") == ([], None))
    items, problem = R.requirements(routine("requires: [\"bin:git\"]\n"))
    check("a malformed requires is a problem, not a silent pass",
          problem and "requires is not a JSON object" in problem, problem)


def test_resolve():
    check("~ is the home directory", R.resolve("~/code/tool", VAULT, HOME) == "/home/someone/code/tool")
    check("a relative path is relative to the vault", R.resolve("repos/data", VAULT, HOME) == "/vault/repos/data")
    check("'.' is the vault itself", R.resolve(".", VAULT, HOME) == "/vault")
    check("an absolute path stays", R.resolve("/opt/x", VAULT, HOME) == "/opt/x")


def everything_present():
    return FakeProbe(programs={"jq", "python3", "bun"},
                     dirs={"/home/someone/code/tool", "/home/someone/code/tool/.git", "/vault/repos/data",
                           "/vault/repos/data/.git", "/home/someone/work", "/home/someone/code/cli"},
                     files={"/home/someone/input.csv", "/home/someone/Brain/_bin/query.py"},
                     execs={"/opt/tools/bin/thing"})


def test_check():
    items, _ = R.requirements(FULL)
    rows = R.check(items, everything_present(), VAULT, HOME)
    check("everything present: every row passes", rows and all(r["ok"] for r in rows), [r for r in rows if not r["ok"]])
    check("and there are no problems", R.problems(FULL, everything_present(), VAULT, HOME) == [])

    bare = FakeProbe(dirs={"/home/someone/code/tool", "/vault/repos/data"})
    probs = R.problems(FULL, bare, VAULT, HOME)
    joined = "\n".join(probs)
    check("a folder with no .git is not a repo, and the fix names the clone",
          "repo `repos/data` is not a git checkout: git clone https://example.com/data.git repos/data" in joined, joined)
    check("a repo with no url says to clone it by hand", "repo `~/code/tool` is not a git checkout: clone it" in joined,
          joined)
    check("a missing program says to install it", "program `jq` not found" in joined and "install it" in joined, joined)
    check("a missing absolute program is reported", "/opt/tools/bin/thing" in joined, joined)
    check("a missing --add-dir directory is reported", "directory `~/work` missing" in joined, joined)
    check("a missing path is reported", "`~/input.csv` missing" in joined, joined)
    check("a missing script is reported", "`~/Brain/_bin/query.py` missing" in joined, joined)
    probs = R.problems(routine("requires: {\"programs\": [1]}\n"), everything_present(), VAULT, HOME)
    check("a requires line that does not parse is itself a problem",
          len(probs) == 1 and "requires is not a JSON object" in probs[0], probs)


def test_fix():
    items, _ = R.requirements(FULL)
    rows = R.check(items, FakeProbe(), VAULT, HOME)
    calls = []

    def run(cmd):
        calls.append(cmd)
        return 0, "", ""
    cloned = R.fix(rows, run)
    check("--fix clones a missing repo that carries a url, into its resolved path",
          calls == [["git", "clone", "-q", "https://example.com/data.git", "/vault/repos/data"]], calls)
    check("and reports what it cloned", cloned == ["repos/data"], cloned)
    check("it never tries to install a program", not any("jq" in " ".join(c) for c in calls), calls)
    calls[:] = []
    R.fix(R.check(items, everything_present(), VAULT, HOME), run)
    check("nothing missing, nothing cloned", calls == [], calls)


REGISTRY = """
| id | machine | time | days | type | command | enabled | notes |
|----|---------|------|------|------|---------|---------|-------|
| mine-agent | laptop-a | 07:00 | * | agent | 90-Meta/routines/a.md | yes | pinned here |
| everywhere | * | 07:00 | * | agent | 90-Meta/routines/b.md | yes | every machine |
| `ticked` | laptop-a | 07:00 | * | agent | `90-Meta/routines/c.md` | yes | code ticks |
| off | laptop-a | 07:00 | * | agent | 90-Meta/routines/d.md | no | disabled |
| shell-row | laptop-a | 07:00 | * | shell | echo hi | yes | not an agent |
| other | laptop-b | 07:00 | * | agent | 90-Meta/routines/e.md | yes | another machine |
"""


def test_tasks_here():
    rows = R.tasks_from_registry(REGISTRY, lambda m: m == "laptop-a")
    check("enabled agent rows for this machine or every machine, code ticks stripped",
          rows == [("mine-agent", "90-Meta/routines/a.md"), ("everywhere", "90-Meta/routines/b.md"),
                   ("ticked", "90-Meta/routines/c.md")], rows)
    check("an empty registry has no tasks", R.tasks_from_registry("", lambda m: True) == [])


def test_main():
    root = tempfile.mkdtemp(prefix="routine-requires-test-")
    TMP.append(root)
    vault = os.path.join(root, "vault")
    os.makedirs(os.path.join(vault, "90-Meta", "routines"))
    good = os.path.join(vault, "90-Meta", "routines", "good.md")
    bad = os.path.join(vault, "90-Meta", "routines", "bad.md")
    with open(good, "w") as fh:
        fh.write(routine('requires: {"programs": ["jq"]}\n'))
    with open(bad, "w") as fh:
        fh.write(routine('requires: {"programs": ["not-installed-here"]}\n'))
    with open(os.path.join(vault, "90-Meta", "scheduled-tasks.md"), "w") as fh:
        fh.write("| good | * | 07:00 | * | agent | 90-Meta/routines/good.md | yes | |\n"
                 "| bad | * | 07:00 | * | agent | 90-Meta/routines/bad.md | yes | |\n")
    probe = FakeProbe(programs={"jq"})

    def run_main(argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = R.main(argv, probe=probe, vault=vault, home=root, is_mine=lambda m: False,
                        run=lambda cmd: (0, "", ""))
        return rc, buf.getvalue()

    rc, out = run_main(["check", good])
    check("check: every requirement met is exit 0 and a tick", rc == 0 and "✓" in out, (rc, out))
    rc, out = run_main(["check", bad])
    check("check: a gap is exit 2, a cross and the fix", rc == 2 and "✗" in out and "not-installed-here" in out,
          (rc, out))
    rc, out = run_main(["check", os.path.join(vault, "nope.md")])
    check("check: a missing routine file is a gap too", rc == 2 and "routine file missing" in out, (rc, out))
    rc, out = run_main(["here"])
    check("here: every enabled agent task for this machine is checked",
          rc == 2 and "good" in out and "bad" in out, (rc, out))
    rc, out = run_main([])
    check("no arguments prints the usage", rc == 0 and "here" in out, (rc, out))
    rc, out = run_main(["bogus"])
    check("an unknown command is exit 2 with the usage", rc == 2 and "check" in out, (rc, out))


def main():
    for t in (test_requirements, test_resolve, test_check, test_fix, test_tasks_here, test_main):
        print("\n== %s ==" % t.__name__)
        try:
            t()
        except Exception as exc:
            import traceback
            traceback.print_exc()
            check("%s ran without raising" % t.__name__, False, repr(exc))
    for d in TMP:
        shutil.rmtree(d, ignore_errors=True)
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
