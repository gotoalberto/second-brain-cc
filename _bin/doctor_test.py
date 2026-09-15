#!/usr/bin/env python3
"""Tests for doctor.py's test-harness section: it never runs the suite unless asked.

bootstrap.sh runs doctor.py, and the suite runs bootstrap.sh: a doctor that ran the suite on its
own would start that loop. doctor.py runs against a scratch copy of the vault whose
run_all_tests.py is a stub that only leaves a marker file. Run standalone:

    python3 _bin/doctor_test.py
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def main():
    root = tempfile.mkdtemp(prefix="doctor-test-")
    try:
        vault = os.path.join(root, "vault")
        shutil.copytree(REPO, vault, ignore=shutil.ignore_patterns(".git", "_index", "__pycache__", "*.pyc"))
        marker = os.path.join(root, "suite-ran")
        with open(os.path.join(vault, "_bin", "run_all_tests.py"), "w") as fh:
            fh.write("open(%r, 'w').write('ran')\nprint('RESULT: 1 passed, 0 failed')\n" % marker)
        home, state = os.path.join(root, "home"), os.path.join(root, "state")
        os.makedirs(home)
        env = {k: v for k, v in os.environ.items() if not k.startswith("BRAIN_") and k != "SECOND_BRAIN_TEST_RUN"}
        env.update(HOME=home, BRAIN_STATE=state, BRAIN_VAULT=vault)
        doctor = os.path.join(vault, "_bin", "doctor.py")

        def run(*args, extra=None):
            p = subprocess.run([sys.executable, doctor] + list(args), env=dict(env, **(extra or {})),
                               stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=240)
            return p.returncode, p.stdout + p.stderr

        rc, out = run()
        check("doctor.py on its own does not run the test suite", not os.path.exists(marker), out[-600:])
        check("it says how to run it", "run_all_tests.py" in out, out[-600:])
        rc, out = run("--tests", extra={"SECOND_BRAIN_TEST_RUN": "1"})
        check("inside a test run it never runs the suite, even with --tests", not os.path.exists(marker), out[-600:])
        rc, out = run("--tests")
        check("with --tests it runs the suite and shows its result",
              os.path.exists(marker) and "RESULT: 1 passed" in out, out[-600:])
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
