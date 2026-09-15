#!/usr/bin/env python3
"""Tests for pywrap.sh — the interpreter picker launchd starts every Brain daemon with.

Fake python3 executables are built in a temporary directory and handed to pywrap.sh
through BRAIN_PY_CANDIDATES / BRAIN_PY_CLT, so no real interpreter is judged and nothing
outside the temporary directory is touched. Run standalone:

    python3 _bin/pywrap_test.py
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PYWRAP = os.path.join(HERE, "pywrap.sh")

ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def fake(tmp, name, body):
    path = os.path.join(tmp, name)
    with open(path, "w") as fh:
        fh.write("#!/bin/sh\n" + body)
    os.chmod(path, 0o755)
    return path


# A working interpreter: answers `-c ...` with 0, otherwise reports how it was called.
GOOD = r'''
if [ "$1" = "-c" ]; then exit 0; fi
if [ "$1" = "-" ]; then cat; exit 0; fi
if [ "$1" = "fail" ]; then exit 7; fi
echo "NAME=%s ARGS=$* DEV=${DEVELOPER_DIR:-unset}"
'''
BROKEN = 'echo "xcrun: error: license not accepted" >&2\nexit 69\n'
NEEDS_DEV = r'''
if [ "$DEVELOPER_DIR" != "%s" ]; then echo "xcrun: license" >&2; exit 69; fi
''' + GOOD


def run(candidates, args, clt, stdin="", extra_env=None):
    env = {"PATH": "/usr/bin:/bin", "HOME": os.environ.get("HOME", "/tmp"),
           "BRAIN_PY_CANDIDATES": ":".join(candidates), "BRAIN_PY_CLT": clt}
    env.update(extra_env or {})
    p = subprocess.run([PYWRAP] + args, env=env, input=stdin, capture_output=True, text=True,
                       timeout=20)
    return p.returncode, p.stdout, p.stderr


def main():
    tmp = tempfile.mkdtemp(prefix="pywrap-test-")
    try:
        clt = os.path.join(tmp, "CommandLineTools")
        os.mkdir(clt)
        good = fake(tmp, "good", GOOD % "good")
        good2 = fake(tmp, "good2", GOOD % "good2")
        broken = fake(tmp, "broken", BROKEN)
        needs_dev = fake(tmp, "needs_dev", NEEDS_DEV % (clt, "needs_dev"))
        missing = os.path.join(tmp, "does-not-exist")

        check("pywrap.sh exists and is executable",
              os.path.isfile(PYWRAP) and os.access(PYWRAP, os.X_OK), PYWRAP)
        if not os.path.isfile(PYWRAP):
            return finish()

        rc, out, err = run([broken, good], ["script.py", "--flag", "two words"], clt)
        check("a broken candidate is skipped and the next working one runs",
              rc == 0 and "NAME=good " in out, (rc, out, err))
        check("the arguments reach the interpreter intact",
              "ARGS=script.py --flag two words" in out, out)

        rc, out, _ = run([good, good2], ["x.py"], clt)
        check("candidates are tried in order", "NAME=good " in out, out)

        rc, out, _ = run([missing, good2], ["x.py"], clt)
        check("a candidate that does not exist is skipped", rc == 0 and "NAME=good2" in out, out)

        rc, out, err = run([needs_dev, good2], ["x.py"], clt)
        check("a candidate that only works with DEVELOPER_DIR set is chosen with it",
              rc == 0 and "NAME=needs_dev" in out, (rc, out, err))
        check("and DEVELOPER_DIR is exported to the chosen interpreter",
              "DEV=%s" % clt in out, out)

        rc, out, _ = run([needs_dev, good2], ["x.py"], os.path.join(tmp, "no-clt-here"))
        check("without a CommandLineTools directory that candidate is skipped",
              rc == 0 and "NAME=good2" in out, out)

        rc, out, _ = run([good], ["x.py"], clt, extra_env={"DEVELOPER_DIR": "/custom/dev"})
        check("a DEVELOPER_DIR the caller already set is respected",
              "DEV=/custom/dev" in out, out)

        rc, out, err = run([broken, missing], ["x.py"], clt)
        check("when nothing works it exits 69", rc == 69, (rc, out, err))
        check("with a one-line explanation on stderr naming what it tried",
              broken in err and len(err.strip().splitlines()) == 1, err)

        rc, _, _ = run([good], ["fail"], clt)
        check("the chosen interpreter's exit code comes back unchanged", rc == 7, rc)

        rc, out, _ = run([good], ["-"], clt, stdin="print('from stdin')\n")
        check("stdin reaches the interpreter (bootstrap.sh feeds heredocs)",
              "from stdin" in out, out)

        env = {"PATH": "/usr/bin:/bin", "HOME": os.environ.get("HOME", "/tmp")}
        p = subprocess.run(["/bin/sh", "-n", PYWRAP], env=env, capture_output=True, text=True)
        check("pywrap.sh is valid POSIX sh", p.returncode == 0, p.stderr)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return finish()


def finish():
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
