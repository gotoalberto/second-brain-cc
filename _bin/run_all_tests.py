#!/usr/bin/env python3
"""run_all_tests.py — every test in the harness, each in its own scratch world.

  run_all_tests.py [--root DIR] [--jobs N] [-k TEXT] [--verbose]

Finds every `*_test.py` under `_bin/` and `integrations/`, runs each as its own process with a fresh
temporary HOME and BRAIN_STATE (BRAIN_VAULT is the repository, every other BRAIN_* variable is
dropped, stdin is closed), and adds up the `RESULT: N passed, M failed` line each one prints. A file
that exits non-zero, times out or prints no RESULT line counts as failed. Prints one line per file
and the total; exits 1 when anything failed. Standard library only; run it with each supported
interpreter (CI runs Python 3.9 and 3.14).
"""

import argparse
import concurrent.futures
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RESULT = re.compile(r"^RESULT: (\d+) passed, (\d+) failed\s*$", re.M)
SKIP_DIRS = {".git", "__pycache__", "node_modules", "_index"}
TIMEOUT = 900


def discover(root, pattern=None):
    found = []
    for top in ("_bin", "integrations"):
        for dp, dns, fns in os.walk(os.path.join(root, top)):
            dns[:] = sorted(d for d in dns if d not in SKIP_DIRS)
            for fn in sorted(fns):
                if fn.endswith("_test.py"):
                    rel = os.path.relpath(os.path.join(dp, fn), root)
                    if not pattern or pattern in rel:
                        found.append(rel)
    return sorted(found)


def run_one(root, rel, python=sys.executable):
    scratch = tempfile.mkdtemp(prefix="brain-tests-")
    home, state = os.path.join(scratch, "home"), os.path.join(scratch, "state")
    os.makedirs(home)
    env = {k: v for k, v in os.environ.items() if not k.startswith("BRAIN_")}
    env.update(HOME=home, BRAIN_STATE=state, BRAIN_VAULT=root, PYTHONDONTWRITEBYTECODE="1")
    start = time.time()
    try:
        p = subprocess.run([python, os.path.join(root, rel)], cwd=root, env=env, stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=TIMEOUT)
        out, rc = p.stdout, p.returncode
    except subprocess.TimeoutExpired as exc:
        out, rc = (exc.stdout or "") if isinstance(exc.stdout, str) else "", "timeout"
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    matches = RESULT.findall(out or "")
    passed, failed = (int(matches[-1][0]), int(matches[-1][1])) if matches else (0, 0)
    ok = rc == 0 and bool(matches) and failed == 0
    return {"file": rel, "rc": rc, "passed": passed, "failed": failed, "ok": ok, "has_result": bool(matches),
            "seconds": time.time() - start, "output": out or ""}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="run_all_tests.py", description="run every harness test in isolation")
    ap.add_argument("--root", default=os.path.dirname(HERE))
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("-k", dest="pattern", default=None, help="only files whose path contains this")
    ap.add_argument("--verbose", action="store_true", help="print the output of failed files")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)
    root = os.path.abspath(args.root)
    files = discover(root, args.pattern)
    if not files:
        print("no test files found under %s" % root)
        print("RESULT: 0 passed, 0 failed")
        return 1
    print("python %s, %d test files" % (sys.version.split()[0], len(files)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        results = list(pool.map(lambda rel: run_one(root, rel), files))
    total_passed = total_failed = 0
    broken = []
    for r in results:
        total_passed += r["passed"]
        total_failed += r["failed"]
        if not r["ok"]:
            broken.append(r)
            if not r["has_result"] or r["failed"] == 0:
                total_failed += 1          # a crash, a timeout or a missing RESULT line is a failure too
        status = "ok  " if r["ok"] else "FAIL"
        detail = "%d passed, %d failed" % (r["passed"], r["failed"]) if r["has_result"] else "no RESULT line"
        print("%s %-60s %-24s rc=%s %.1fs" % (status, r["file"], detail, r["rc"], r["seconds"]))
    if args.verbose:
        for r in broken:
            print("\n---- %s ----\n%s" % (r["file"], r["output"][-4000:]))
    print("RESULT: %d passed, %d failed" % (total_passed, total_failed))
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
