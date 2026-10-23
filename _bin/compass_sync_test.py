#!/usr/bin/env python3
"""Tests for the live sync notice compass.py puts first in the startup block.

BRAIN_STATE, BRAIN_VAULT and HOME point at temporary directories before compass is imported,
and BRAIN_OFFLINE is set. The git calls are faked. Run standalone:

    python3 _bin/compass_sync_test.py
"""
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = tempfile.mkdtemp(prefix="brain-compass-sync-")
PATHS = {n: os.path.join(ROOT, n) for n in ("home", "state", "vault")}
for _p in PATHS.values():
    os.makedirs(_p)
os.environ.update({"HOME": PATHS["home"], "BRAIN_STATE": PATHS["state"], "BRAIN_VAULT": PATHS["vault"],
                   "BRAIN_OFFLINE": "1", "BRAIN_MACHINE_KEY": "test-box-12345678"})
sys.path.insert(0, HERE)

ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail and not cond else ""))


def main():
    import compass as C

    vault = PATHS["vault"]
    git_dir = os.path.join(vault, ".git")
    os.makedirs(git_dir)
    now = time.time()
    nothing = lambda args: (0, "", "")

    print("== a healthy vault ==")
    check("adds nothing", C.sync_section(vault, now, nothing) is None)
    recent = lambda args: (0, "%d\n" % int(now - 300), "")
    check("a commit the daemon pushes in the next few minutes is not news",
          C.sync_section(vault, now, recent) is None)
    check("no upstream (git fails) adds nothing either",
          C.sync_section(vault, now, lambda a: (128, "", "no upstream")) is None)

    print("== unpushed for hours ==")
    old = lambda args: (0, "%d\n%d\n" % (int(now - 5 * 3600), int(now - 4000)), "")
    sec = C.sync_section(vault, now, old)
    check("is reported with the count and the age", sec and "2 commit(s) not pushed" in sec[1]
          and "5 h" in sec[1], sec)

    print("== stuck mid-rebase ==")
    rb = os.path.join(git_dir, "rebase-merge")
    os.makedirs(rb)
    then = now - 3 * 86400
    os.utime(rb, (then, then))
    sec = C.sync_section(vault, now, nothing)
    check("is the first thing a session reads: priority just under the header",
          sec and sec[0] == "sync" and sec[2] == 99, sec)
    check("says how long and since when", "3 days" in sec[1]
          and time.strftime("%Y-%m-%d", time.localtime(then)) in sec[1], sec[1])
    check("and, with no marker, what a person has to do", "rebase --continue" in sec[1], sec[1])
    open(os.path.join(git_dir, "brain-sync-rebase"), "w").close()
    sec = C.sync_section(vault, now, nothing)
    check("with the sync's marker it says the sync recovers it", "recovers it" in sec[1], sec[1])
    check("and the git calls are not made while stuck",
          C.sync_section(vault, now, lambda a: (_ for _ in ()).throw(AssertionError("called"))) is not None)
    shutil.rmtree(rb)
    os.remove(os.path.join(git_dir, "brain-sync-rebase"))

    print("== a merge in progress ==")
    open(os.path.join(git_dir, "MERGE_HEAD"), "w").close()
    sec = C.sync_section(vault, now, nothing)
    check("is reported too", sec and "merge is in progress" in sec[1], sec)
    os.remove(os.path.join(git_dir, "MERGE_HEAD"))

    print("== never breaks the startup ==")
    check("an exploding git call adds nothing and raises nothing",
          C.sync_section(vault, now, lambda a: 1 / 0) is None)

    print("== in the startup block ==")
    import brainlib as B
    os.makedirs(rb)
    os.utime(rb, (then, then))
    secs = C.build_sections(B.db(), sid="aaaa1111", cwd=vault)
    names = [s[0] for s in secs]
    check("the sync notice comes right after the header", names[:2] == ["header", "sync"], names)
    check("and the budget report (no session) leaves it out",
          "sync" not in [s[0] for s in C.build_sections(B.db())])
    shutil.rmtree(rb)
    secs = C.build_sections(B.db(), sid="aaaa1111", cwd=vault)
    check("and it is gone once the vault syncs", "sync" not in [s[0] for s in secs])

    shutil.rmtree(ROOT, ignore_errors=True)
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
