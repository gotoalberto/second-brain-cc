#!/usr/bin/env python3
"""Tests for run_all_tests.py, over a temporary tree of small test files.

Run standalone:

    python3 _bin/run_all_tests_test.py
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER = os.path.join(HERE, "run_all_tests.py")

ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


PASSING = 'import os, sys\nprint("home=" + os.environ["HOME"])\nprint("RESULT: 3 passed, 0 failed")\n'
FAILING = 'import sys\nprint("RESULT: 1 passed, 2 failed")\nsys.exit(1)\n'
SILENT = 'print("forgot the result line")\n'
ENV_PROBE = ('import os, sys\nleak = [k for k in os.environ if k.startswith("BRAIN_") and k not in '
             '("BRAIN_STATE", "BRAIN_VAULT")]\nprint("leak=%s state=%s" % (leak, os.environ.get("BRAIN_STATE")))\n'
             'print("RESULT: %d passed, %d failed" % ((1, 0) if not leak and sys.stdin.read() == "" else (0, 1)))\n'
             'sys.exit(0 if not leak else 1)\n')


def run(root, *args, extra_env=None):
    env = dict(os.environ, BRAIN_SECRET_THING="should-not-leak", **(extra_env or {}))
    p = subprocess.run([sys.executable, RUNNER, "--root", root] + list(args), env=env, capture_output=True,
                       text=True, timeout=120)
    return p.returncode, p.stdout


def main():
    root = tempfile.mkdtemp(prefix="run-all-tests-")
    try:
        if not os.path.exists(RUNNER):
            check("run_all_tests.py exists", False, RUNNER)
            print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
            return 1
        write(os.path.join(root, "_bin", "a_test.py"), PASSING)
        write(os.path.join(root, "_bin", "core", "b_test.py"), PASSING)
        write(os.path.join(root, "integrations", "x", "c_test.py"), ENV_PROBE)
        write(os.path.join(root, "_bin", "not_a_test.py.txt"), "raise SystemExit(1)\n")
        rc, out = run(root)
        check("every *_test.py under _bin and integrations is run, and green adds up",
              rc == 0 and "RESULT: 7 passed, 0 failed" in out and out.count("ok  ") == 3, out)
        homes = [l for l in out.splitlines() if l.startswith("home=")]
        check("the runner prints only its summary, not each file's output", homes == [], homes)
        check("each file gets its own HOME and state, no inherited BRAIN_ variable and no stdin",
              "c_test.py" in out and "0 failed" in out.split("c_test.py")[1].splitlines()[0], out)

        write(os.path.join(root, "_bin", "d_test.py"), FAILING)
        write(os.path.join(root, "_bin", "e_test.py"), SILENT)
        rc, out = run(root, "--verbose")
        check("a failing file makes the run exit 1", rc == 1, out)
        check("its failures are counted and a file with no RESULT line counts as one more",
              "RESULT: 8 passed, 3 failed" in out, out)
        check("each failing file is named, and --verbose shows its output",
              "FAIL _bin/d_test.py" in out and "no RESULT line" in out and "forgot the result line" in out, out)
        rc, out = run(root, "-k", "core")
        check("-k runs only the files whose path matches", rc == 0 and "RESULT: 3 passed, 0 failed" in out, out)
        empty = tempfile.mkdtemp(prefix="run-all-tests-empty-")
        rc, out = run(empty)
        shutil.rmtree(empty, ignore_errors=True)
        check("finding no test file is a failure, not a green run", rc == 1, out)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
