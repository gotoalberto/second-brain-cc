#!/usr/bin/env python3
"""Tests for the git-hook adapters: events_core/git_pre_commit.py and git_post_commit.py.

Every run happens in a throwaway `git init` repository with HOME, BRAIN_VAULT and the git
global config pointed at temporary locations, so neither the real vault, its git config,
~/.claude nor the user's git settings are read or changed. Run standalone:

    python3 _bin/events_core/git_hooks_test.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.dirname(HERE)
sys.path[0] = BIN

ok, fail = [], []
TMP = []

PRE = os.path.join(HERE, "git_pre_commit.py")
POST = os.path.join(HERE, "git_post_commit.py")
FAKE_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"          # matches the aws-access-key pattern; not a real key


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def tmpdir():
    d = tempfile.mkdtemp(prefix="git-hooks-test-")
    TMP.append(d)
    return d


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)
    return path


def fixture():
    root = tmpdir()
    repo, home = os.path.join(root, "vault"), os.path.join(root, "home")
    os.makedirs(repo)
    os.makedirs(home)
    gcfg = write(os.path.join(root, "gitconfig"), "[user]\n\tname = t\n\temail = t@example.com\n")
    env = dict(os.environ, HOME=home, BRAIN_VAULT=repo, GIT_CONFIG_GLOBAL=gcfg, GIT_CONFIG_NOSYSTEM="1")
    env.pop("BRAIN_STATE", None)
    run(["git", "init", "-q", "-b", "main"], repo, env)
    write(os.path.join(repo, "README.md"), "fixture\n")
    run(["git", "add", "README.md"], repo, env)
    run(["git", "commit", "-qm", "base", "--no-verify"], repo, env)
    return repo, home, env


def run(argv, cwd, env, stdin=""):
    return subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, input=stdin, timeout=60)


def py(script, repo, env):
    return run([sys.executable, script], repo, env)


def head(repo, env):
    return run(["git", "rev-parse", "HEAD"], repo, env).stdout.strip()


def test_pre_commit_adapter():
    print("\n== git_pre_commit.py ==")
    repo, home, env = fixture()
    p = py(PRE, repo, env)
    check("nothing staged passes", p.returncode == 0, (p.returncode, p.stderr))

    write(os.path.join(repo, "30-Knowledge", "clean.md"), "---\nid: x\n---\nnothing secret\n")
    run(["git", "add", "30-Knowledge/clean.md"], repo, env)
    p = py(PRE, repo, env)
    check("a clean staged note passes silently", p.returncode == 0 and not p.stderr.strip(), (p.returncode, p.stderr))

    write(os.path.join(repo, "30-Knowledge", "leak.md"), "aws key: %s\n" % FAKE_KEY)
    run(["git", "add", "30-Knowledge/leak.md"], repo, env)
    p = py(PRE, repo, env)
    check("a staged secret blocks the commit", p.returncode != 0, (p.returncode, p.stderr))
    check("the message names the file and the kind of secret",
          "30-Knowledge/leak.md" in p.stderr and "aws-access-key" in p.stderr, p.stderr)
    check("the message never prints the secret, not even its start", FAKE_KEY[:8] not in p.stderr, p.stderr)
    check("the message documents --no-verify and its cost", "--no-verify" in p.stderr, p.stderr)

    write(os.path.join(repo, "30-Knowledge", "leak.md"), "fixed on disk\n")
    p = py(PRE, repo, env)
    check("a secret staged and then fixed only on disk still blocks (the index is what commits)",
          p.returncode != 0, (p.returncode, p.stderr))
    run(["git", "add", "30-Knowledge/leak.md"], repo, env)
    check("restaging the fix unblocks it", py(PRE, repo, env).returncode == 0)

    write(os.path.join(repo, "_bin", "synthetic_test.py"),
          '"""Harness.  brain:allow-secrets"""\nKEY = "%s"\n' % FAKE_KEY)
    run(["git", "add", "_bin/synthetic_test.py"], repo, env)
    check("a file declaring brain:allow-secrets in its first lines is exempt, like vault_sync's gate",
          py(PRE, repo, env).returncode == 0)
    write(os.path.join(repo, "_bin", "late_marker.py"), "KEY = '%s'\n" % FAKE_KEY + "\n" * 20 + "# brain:allow-secrets\n")
    run(["git", "add", "_bin/late_marker.py"], repo, env)
    check("a marker far down the file does not exempt it", py(PRE, repo, env).returncode != 0)
    run(["git", "rm", "-q", "--cached", "_bin/late_marker.py"], repo, env)

    with open(os.path.join(repo, "blob.bin"), "wb") as fh:
        fh.write(b"\0\1\2" + FAKE_KEY.encode() + b"\0")
    run(["git", "add", "blob.bin"], repo, env)
    check("binary files are not scanned", py(PRE, repo, env).returncode == 0)

    note = write(os.path.join(repo, "10-Projects", "2026-09-15-project-x.md"), "---\nid: p\n---\nupdate\n")
    run(["git", "add", "10-Projects/2026-09-15-project-x.md"], repo, env)
    p = py(PRE, repo, env)
    check("a protected note not written through vw.py warns",
          "10-Projects/2026-09-15-project-x.md" in p.stderr and "vw.py" in p.stderr, p.stderr)
    check("but never blocks", p.returncode == 0, p.returncode)

    state = os.path.join(home, ".claude", "state", "brain")
    os.makedirs(state, exist_ok=True)
    write(os.path.join(state, "vw_writes.json"), json.dumps({os.path.realpath(note): time.time() + 5}))
    p = py(PRE, repo, env)
    check("a protected note vw.py wrote last does not warn", "project-x" not in p.stderr, p.stderr)


def test_post_commit_adapter():
    print("\n== git_post_commit.py ==")
    repo, _, env = fixture()
    p = py(POST, repo, env)
    dirty = os.path.join(repo, "_index", ".dirty")
    check("post-commit marks the index dirty for the next reindex/sync pass",
          p.returncode == 0 and os.path.exists(dirty), (p.returncode, p.stderr))
    repo2, _, env2 = fixture()
    write(os.path.join(repo2, "_index"), "a file where the directory should be")
    p = py(POST, repo2, env2)
    check("post-commit never fails a commit, even when it cannot write", p.returncode == 0, (p.returncode, p.stderr))


REGISTRY = {"version": 1, "events": [
    {"id": "pre-write-gate", "description": "secrets block, protected paths warn", "handler": "gate_write",
     "triggers": [{"kind": "git-hook", "hook": "pre-commit", "command": "events_core/git_pre_commit.py"}]},
    {"id": "post-commit-dirty", "description": "mark the index dirty", "handler": "git_post_commit",
     "triggers": [{"kind": "git-hook", "hook": "post-commit", "command": "events_core/git_post_commit.py"}]},
]}


def test_end_to_end():
    print("\n== the rendered hooks, installed in a fixture repository ==")
    from events_core import domain as D
    repo, _, env = fixture()
    reg = D.load_registry(json.dumps(REGISTRY))
    for name, text in (("pre-commit", D.render_git_pre_commit(reg)), ("post-commit", D.render_git_post_commit(reg))):
        path = write(os.path.join(repo, "githooks", name), text)
        os.chmod(path, 0o755)
    os.symlink(BIN, os.path.join(repo, "_bin"))
    run(["git", "config", "core.hooksPath", "githooks"], repo, env)

    before = head(repo, env)
    write(os.path.join(repo, "30-Knowledge", "leak.md"), "token: %s\n" % FAKE_KEY)
    run(["git", "add", "30-Knowledge/leak.md"], repo, env)
    p = run(["git", "commit", "-qm", "leak"], repo, env)
    check("git commit with a staged secret is rejected", p.returncode != 0 and head(repo, env) == before,
          (p.returncode, p.stderr))
    check("with the adapter's explanation", "aws-access-key" in p.stderr, p.stderr)

    run(["git", "rm", "-q", "--cached", "30-Knowledge/leak.md"], repo, env)
    write(os.path.join(repo, "70-Entities", "2026-09-15-entity-someone.md"), "---\nid: e\n---\nhand edit\n")
    run(["git", "add", "70-Entities/2026-09-15-entity-someone.md"], repo, env)
    p = run(["git", "commit", "-qm", "entity by hand"], repo, env)
    check("a hand-edited protected note commits, with the warning shown",
          p.returncode == 0 and head(repo, env) != before and "vw.py" in p.stderr, (p.returncode, p.stderr))
    check("and post-commit marked the index dirty", os.path.exists(os.path.join(repo, "_index", ".dirty")))

    run(["git", "add", "30-Knowledge/leak.md"], repo, env)
    mid = head(repo, env)
    p = run(["git", "commit", "-qm", "forced", "--no-verify"], repo, env)
    check("--no-verify bypasses the hook (the documented escape hatch)", p.returncode == 0 and head(repo, env) != mid,
          (p.returncode, p.stderr))

    plain, _, env3 = fixture()
    for name, text in (("pre-commit", D.render_git_pre_commit(reg)),):
        path = write(os.path.join(plain, "githooks", name), text)
        os.chmod(path, 0o755)
    run(["git", "config", "core.hooksPath", "githooks"], plain, env3)
    write(os.path.join(plain, "notes.md"), "token: %s\n" % FAKE_KEY)
    run(["git", "add", "notes.md"], plain, env3)
    p = run(["git", "commit", "-qm", "no engine"], plain, env3)
    check("in a clone without Brain's _bin the hook steps aside instead of breaking commits",
          p.returncode == 0, (p.returncode, p.stderr))


def main():
    for t in (test_pre_commit_adapter, test_post_commit_adapter, test_end_to_end):
        if not os.path.exists(PRE) or not os.path.exists(POST):
            check("the git-hook adapters exist", False, (PRE, POST))
            break
        try:
            t()
        except Exception as exc:
            import traceback
            traceback.print_exc()
            check("%s ran to the end" % t.__name__, False, "%s: %s" % (type(exc).__name__, exc))
    for d in TMP:
        shutil.rmtree(d, ignore_errors=True)
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
