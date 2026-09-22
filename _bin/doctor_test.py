#!/usr/bin/env python3
"""Tests for doctor.py: the test-harness section never runs the suite unless asked, and the
periodic jobs and transcripts are read the same way on every OS.

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


class FakeJobs:
    def __init__(self, labels, installed=(), loaded=()):
        self._labels, self._installed, self._loaded = list(labels), set(installed), set(loaded)

    def labels(self):
        return list(self._labels)

    def installed(self, label):
        return label in self._installed

    def is_loaded(self, label):
        return label in self._loaded


class SystemdUserControl(FakeJobs):
    pass


def test_pure():
    import doctor
    lines = doctor.job_lines(FakeJobs([]))
    check("no accepted jobs is said as no supervisor on this machine",
          len(lines) == 1 and "no supervisor on this machine" in lines[0], lines)
    lines = doctor.job_lines(SystemdUserControl(["second-brain-sync", "second-brain-guardian"],
                                                installed={"second-brain-sync"}, loaded={"second-brain-sync"}))
    check("each job gets a line under its supervisor's name",
          lines[0] == "periodic jobs (systemd):" and len(lines) == 3
          and "second-brain-sync" in lines[1] and "installed=yes" in lines[1] and "loaded=yes" in lines[1]
          and "installed=NO" in lines[2] and "loaded=no" in lines[2], lines)

    home = tempfile.mkdtemp(prefix="doctor-home-")
    try:
        for rel in ("-home-me/a.jsonl", "-home-me-code-app/b.jsonl", "-srv-repo/c.jsonl",
                    "-home-me-code-app/b/subagents/agent-1.jsonl", "-home-me/notes.txt"):
            path = os.path.join(home, ".claude", "projects", rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "w").close()
        names = [os.path.relpath(p, os.path.join(home, ".claude", "projects")) for p in doctor.transcript_files(home)]
        check("transcripts are read from every project directory, top level only",
              names == ["-home-me-code-app/b.jsonl", "-home-me/a.jsonl", "-srv-repo/c.jsonl"], names)
    finally:
        shutil.rmtree(home, ignore_errors=True)


def main():
    sys.path.insert(0, HERE)
    try:
        test_pure()
    except Exception as exc:
        check("the pure checks ran to the end", False, "%s: %s" % (type(exc).__name__, exc))
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

        # A worktree grades its own copy: the suite beside doctor.py, whatever BRAIN_VAULT says.
        os.remove(marker)
        other = os.path.join(root, "other")
        shutil.copytree(vault, other, ignore=shutil.ignore_patterns("_index", "__pycache__"))
        with open(os.path.join(other, "_bin", "run_all_tests.py"), "w") as fh:
            fh.write("print('RESULT: 9 passed, 0 failed')\n")
        rc, out = run("--tests", extra={"BRAIN_VAULT": other})
        check("--tests runs the suite beside doctor.py, not the one in BRAIN_VAULT",
              os.path.exists(marker) and "RESULT: 1 passed" in out and "9 passed" not in out, out[-600:])
        check("the periodic jobs line never looks for a launchd plist by path",
              "launchd daemon:" not in out and "periodic jobs" in out, out[:2000])
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
