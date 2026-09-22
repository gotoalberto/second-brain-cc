#!/usr/bin/env python3
"""Tests for log_subagent.py (the SubagentStop trace) and linkfix.apply's write record.

Each case runs in a subprocess whose HOME, BRAIN_STATE and BRAIN_VAULT are temporary
directories, with BRAIN_OFFLINE set, so nothing reaches the real vault or state. Run standalone:

    python3 _bin/log_subagent_test.py
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail and not cond else ""))


def scratch(root):
    paths = {n: os.path.join(root, n) for n in ("home", "state", "vault")}
    for p in paths.values():
        os.makedirs(p)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": paths["home"], "TMPDIR": root,
           "BRAIN_STATE": paths["state"], "BRAIN_VAULT": paths["vault"], "BRAIN_OFFLINE": "1",
           "PYTHONDONTWRITEBYTECODE": "1", "GIT_CEILING_DIRECTORIES": root}
    return env, paths


def test_log_subagent(root):
    print("== the subagent trace ==")
    env, paths = scratch(os.path.join(root, "a"))
    script = os.path.join(HERE, "log_subagent.py")
    p = subprocess.run([sys.executable, script], input=json.dumps({"agent_type": "verifier"}),
                       env=env, capture_output=True, text=True, timeout=60)
    traces = glob.glob(os.path.join(paths["vault"], "50-Sessions", "*", "*.md"))
    check("a payload with no session id exits 0", p.returncode == 0, (p.returncode, p.stderr[-400:]))
    check("and leaves no nosess trace in 50-Sessions", traces == [], traces)
    p = subprocess.run([sys.executable, script],
                       input=json.dumps({"session_id": "3ac18522-ed92-4c1a-9d0e-000000000001",
                                         "agent_type": "verifier", "cwd": "/nonexistent"}),
                       env=env, capture_output=True, text=True, timeout=60)
    traces = glob.glob(os.path.join(paths["vault"], "50-Sessions", "*", "*.md"))
    body = open(traces[0]).read() if traces else ""
    check("a real session gets its trace line",
          p.returncode == 0 and [os.path.basename(t) for t in traces] == ["3ac18522.md"]
          and "subagent `verifier` finished" in body, (p.returncode, traces, p.stderr[-400:]))


LINKFIX = r'''
import json, os, sys
sys.path.insert(0, %(bin)r)
import brainlib as B
import linkfix
changed = linkfix.apply(B.db(), [("10-Projects/a.md", "old-name", "new-name", "alias")])
try:
    record = json.load(open(os.path.join(B.STATE, "vw_writes.json")))
except (OSError, ValueError):
    record = {}
print(json.dumps({"changed": changed, "record": sorted(record)}))
'''


def test_linkfix_records(root):
    print("== linkfix records its own write ==")
    env, paths = scratch(os.path.join(root, "b"))
    note = os.path.join(paths["vault"], "10-Projects", "a.md")
    os.makedirs(os.path.dirname(note))
    with open(note, "w") as fh:
        fh.write("---\ntitle: a\n---\n\nSee [[old-name]].\n")
    p = subprocess.run([sys.executable, "-c", LINKFIX % {"bin": HERE}], env=env, capture_output=True,
                       text=True, timeout=60, stdin=subprocess.DEVNULL)
    try:
        out = json.loads(p.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        out = {}
    check("the link is rewritten", out.get("changed") == ["10-Projects/a.md"]
          and "[[new-name]]" in open(note).read(), (out, p.stderr[-600:]))
    check("and the write is recorded the way vw.py records one, so the ledger does not flag it",
          os.path.realpath(note) in (out.get("record") or []), out)


def main():
    root = tempfile.mkdtemp(prefix="log-subagent-test-")
    try:
        for t in (test_log_subagent, test_linkfix_records):
            try:
                t(root)
            except Exception as exc:
                check("%s ran to the end" % t.__name__, False, "%s: %s" % (type(exc).__name__, exc))
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
