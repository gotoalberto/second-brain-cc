#!/usr/bin/env python3
"""Tests for vault_sync's multi-machine pieces: stale index.lock, lock failures, jitter, unmerged files.

No real repository and no real git process: a temporary directory and injected fakes.
Run standalone:

    python3 _bin/vault_sync_test.py
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail and not cond else ""))


def main():
    import vault_sync as V

    print("== a leftover .git/index.lock ==")
    with tempfile.TemporaryDirectory() as vault:
        os.makedirs(os.path.join(vault, ".git"))
        lock = os.path.join(vault, ".git", "index.lock")
        check("no lock, nothing to do", V.clear_stale_index_lock(vault, running=lambda: False) is False)

        open(lock, "w").close()
        now = time.time()
        check("a fresh lock is left alone",
              V.clear_stale_index_lock(vault, now_=now, running=lambda: False) is False and os.path.exists(lock))
        later = now + V.STALE_INDEX_LOCK_S + 5
        check("an old lock is left alone while any git process runs",
              V.clear_stale_index_lock(vault, now_=later, running=lambda: True) is False and os.path.exists(lock))
        check("an old lock with no git running is removed",
              V.clear_stale_index_lock(vault, now_=later, running=lambda: False) is True and not os.path.exists(lock))

    print("== a lock failure is not a conflict ==")
    err = ("error: Unable to create '/home/user/Brain/.git/index.lock': File exists.\n"
           "Another git process seems to be running in this repository")
    check("git's index.lock message is recognised", V.is_lock_failure(err))
    check("a real rebase conflict is not", not V.is_lock_failure("CONFLICT (content): Merge conflict in a.md"))

    print("== scheduled jitter ==")
    slept = []
    check("a pass started by hand does not wait",
          V.scheduled_jitter(sleep=slept.append, ppid=lambda: 4242, environ={}) == 0.0 and slept == [])
    wait = V.scheduled_jitter(sleep=slept.append, ppid=lambda: 1, environ={})
    check("a launchd pass (parent pid 1) waits a random time within the bound",
          0.0 <= wait <= V.SYNC_JITTER_S and slept == [wait], (wait, slept))
    slept = []
    wait = V.scheduled_jitter(sleep=slept.append, ppid=lambda: 4242,
                              environ={"BRAIN_JOB_LABEL": "second-brain-sync"})
    check("a systemd or cron pass (BRAIN_JOB_LABEL set) waits too",
          0.0 <= wait <= V.SYNC_JITTER_S and slept == [wait], (wait, slept))
    saved = V.SYNC_JITTER_S
    V.SYNC_JITTER_S = 0
    try:
        check("a zero bound turns it off",
              V.scheduled_jitter(sleep=slept.append, ppid=lambda: 1, environ={}) == 0.0)
    finally:
        V.SYNC_JITTER_S = saved

    print("== looking for a running git ==")
    check("with no pgrep on this machine, assume git is running",
          V.git_running(which=lambda _: None) is True)

    class P:
        def __init__(self, rc):
            self.returncode = rc
    seen = []
    check("pgrep is looked up on PATH, and exit 1 means no git",
          V.git_running(run=lambda cmd, **k: seen.append(cmd) or P(1), which=lambda _: "/x/pgrep") is False
          and seen == [["/x/pgrep", "-x", "git"]], seen)


    print("== unmerged files left by pull --autostash ==")
    import shutil
    import subprocess

    def sh(cwd, *a):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t"] + list(a), cwd=cwd,
                              capture_output=True, text=True)

    def git_in(cwd):
        def g(*a):
            r = sh(cwd, *a)
            return r.returncode, r.stdout.strip(), r.stderr.strip()
        return g

    def two_clones(root):
        sh(root, "init", "-q", "--bare", "-b", "main", "remote.git")
        sh(root, "clone", "-q", "remote.git", "a")
        a = os.path.join(root, "a")
        os.makedirs(os.path.join(a, "90-Meta", "presence"))
        for rel, body in (("90-Meta/presence/p.md", "v1"), ("n.md", "x")):
            with open(os.path.join(a, rel), "w") as fh:
                fh.write(body)
        sh(a, "add", "-A"); sh(a, "commit", "-qm", "init"); sh(a, "push", "-q", "origin", "HEAD:main")
        sh(root, "clone", "-q", "-b", "main", "remote.git", "b")
        return a, os.path.join(root, "b")

    check("nothing is the machinery's own by default in this vault",
          V.EPHEMERAL_PREFIXES == () and not V.is_ephemeral("90-Meta/presence/p.md"))

    with tempfile.TemporaryDirectory() as root:
        a, b = two_clones(root)
        sh(a, "rm", "-q", "90-Meta/presence/p.md"); sh(a, "commit", "-qm", "del"); sh(a, "push", "-q")
        with open(os.path.join(b, "90-Meta/presence/p.md"), "w") as fh:
            fh.write("v2")
        sh(b, "pull", "-q", "--rebase", "--autostash")
        g = git_in(b)
        left = V.settle_unmerged(g)
        check("with no machine prefixes, even a machine-looking file is left for a person",
              left == ["90-Meta/presence/p.md"], left)

    V.EPHEMERAL_PREFIXES = ("90-Meta/presence/",)
    with tempfile.TemporaryDirectory() as root:
        a, b = two_clones(root)
        sh(a, "rm", "-q", "90-Meta/presence/p.md"); sh(a, "commit", "-qm", "del"); sh(a, "push", "-q")
        with open(os.path.join(b, "90-Meta/presence/p.md"), "w") as fh:
            fh.write("v2")
        with open(os.path.join(b, "n.md"), "w") as fh:
            fh.write("local edit")
        pulled = sh(b, "pull", "-q", "--rebase", "--autostash")
        g = git_in(b)
        check("reproduced: the pull exits 0 and leaves the presence file unmerged",
              pulled.returncode == 0 and V.unmerged_paths(g) == ["90-Meta/presence/p.md"], V.unmerged_paths(g))
        left = V.settle_unmerged(g)
        check("a conflict on a declared machine file is settled with nothing left for a person", left == [], left)
        check("the remote's deletion wins", not os.path.exists(os.path.join(b, "90-Meta/presence/p.md")))
        check("the other local edit survives", open(os.path.join(b, "n.md")).read() == "local edit")
        check("the autostash entry is dropped", g("stash", "list")[1] == "")
        check("and the next pull works", sh(b, "pull", "-q", "--rebase", "--autostash").returncode == 0)

    with tempfile.TemporaryDirectory() as root:
        a, b = two_clones(root)
        with open(os.path.join(a, "n.md"), "w") as fh:
            fh.write("remote edit")
        sh(a, "commit", "-qam", "edit"); sh(a, "push", "-q")
        with open(os.path.join(b, "n.md"), "w") as fh:
            fh.write("local edit")
        sh(b, "pull", "-q", "--rebase", "--autostash")
        g = git_in(b)
        left = V.settle_unmerged(g)
        check("a conflict on a note is returned, never settled", left == ["n.md"], left)
        check("and its autostash is kept", "autostash" in g("stash", "list")[1])

    check("only declared prefixes count as the machinery's own",
          V.is_ephemeral("90-Meta/presence/x.md") and not V.is_ephemeral("30-Knowledge/x.md"))
    V.EPHEMERAL_PREFIXES = ()

    print("== a stop on unmerged files leaves a note ==")
    with tempfile.TemporaryDirectory() as vault:
        os.makedirs(os.path.join(vault, "00-Inbox"))
        old_vault, old_mark = V.B.VAULT, V.B.mark_git_touched
        V.B.VAULT, V.B.mark_git_touched = vault, (lambda rels: None)
        try:
            V.report_unmerged(["30-Knowledge/n.md"])
        finally:
            V.B.VAULT, V.B.mark_git_touched = old_vault, old_mark
        notes = os.listdir(os.path.join(vault, "00-Inbox"))
        body = open(os.path.join(vault, "00-Inbox", notes[0])).read() if notes else ""
        check("a CONFLICT note in 00-Inbox names the file and the command to look",
              len(notes) == 1 and notes[0].startswith("CONFLICT-sync-") and "`30-Knowledge/n.md`" in body
              and "git status" in body, (notes, body))

    print("\n== commit_message ==")
    msg = lambda paths: V.commit_message(paths, "2026-09-22 20:24")

    # One file: name it outright. `vault: 1 file(s)` said strictly less than the path.
    s, b = msg(["30-Knowledge/note.md"])
    check("a single file is named in the subject", s == "vault: 30-Knowledge/note.md (2026-09-22 20:24)", s)
    check("and needs no body", b == "", b)

    # Several: the folders are what make a line scannable.
    s, b = msg(["30-Knowledge/a.md", "_bin/x.py", "_bin/y.py"])
    check("several files are summarised by folder",
          s == "vault: 30-Knowledge, _bin (3 files) (2026-09-22 20:24)", s)
    check("the body lists every path, so --stat is not needed",
          b == "30-Knowledge/a.md\n_bin/x.py\n_bin/y.py", b)

    # The distinction the history was missing: routine upkeep against work.
    s, _ = msg(["40-Skills/a.md", "40-Skills/b.md"])
    check("pure harness upkeep is chore:", s.startswith("chore: "), s)
    # One real file among the noise makes the whole commit real: `git log | grep -v chore:`
    # must never hide a decision just because it travelled with a catalogue refresh.
    s, _ = msg(["40-Skills/a.md", "30-Knowledge/decision.md"])
    check("one real file among routine ones keeps it vault:", s.startswith("vault: "), s)

    s, _ = msg(["a/1", "b/2", "c/3", "d/4"])
    check("more than three folders are elided", "\u2026" in s and "(4 files)" in s, s)
    check("a file at the vault root is its own folder",
          msg(["README.md", "x/y.md"])[0].startswith("vault: README.md, x"), msg(["README.md", "x/y.md"])[0])
    check("the message names no machine: the commit is pushed",
          V.commit_message.__code__.co_argcount == 2)
    print()
    print("RESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
