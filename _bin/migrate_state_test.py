#!/usr/bin/env python3
"""Tests for migrate_state.py — moving Brain's state out of ~/.claude/state/brain.

Every case runs in a temporary directory standing in for HOME: a legacy
`.claude/state/brain` with files, the new directory brain_paths.state_dir() names for this
platform (`Library/Application Support/brain` on macOS, `.local/state/brain` elsewhere) that
may already hold the guardian's own state, and the backup directory. The real machine's state
is never read or moved; the actual cutover happens later, during integration. Run
standalone:

    python3 _bin/migrate_state_test.py
"""
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import brain_paths

ok, fail = [], []
TMP = []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)
    return path


def read(path):
    with open(path) as fh:
        return fh.read()


def home():
    root = tempfile.mkdtemp(prefix="migrate-state-")
    TMP.append(root)
    h = os.path.join(root, "home")
    legacy = os.path.join(h, ".claude", "state", "brain")
    new = brain_paths.state_dir(environ={}, home=h)
    backups = os.path.join(root, "backups")
    return h, legacy, new, backups


def populate(legacy, new):
    write(os.path.join(legacy, "tasks-state.json"), '{"from": "legacy"}')
    write(os.path.join(legacy, "logs", "daemon.log"), "legacy daemon log\n")
    write(os.path.join(legacy, "logs", "tasks", "daily.log"), "task log\n")
    write(os.path.join(legacy, "linkfix.json"), "{}")
    write(os.path.join(new, "guardian-state.json"), '{"from": "guardian"}')
    write(os.path.join(new, "logs", "guardian.log"), "guardian log\n")
    write(os.path.join(new, "tasks-state.json"), '{"from": "new"}')


def test_plan(M):
    print("\n== plan ==")
    h, legacy, new, _ = home()
    check("no legacy directory: a fresh setup", M.plan(legacy, new) == "fresh")
    os.makedirs(legacy)
    check("a real legacy directory: migrate", M.plan(legacy, new) == "migrate")
    shutil.rmtree(legacy)
    os.makedirs(new)
    os.symlink(new, legacy)
    check("legacy already a symlink to the new directory: done", M.plan(legacy, new) == "done")
    os.remove(legacy)
    other = os.path.join(h, "elsewhere")
    os.makedirs(other)
    os.symlink(other, legacy)
    check("legacy a symlink somewhere else: refuse", M.plan(legacy, new) == "foreign-symlink")


def test_migrate(M):
    print("\n== migrate ==")
    h, legacy, new, backups = home()
    populate(legacy, new)
    dry = M.migrate(legacy, new, backups, dry_run=True)
    check("a dry run changes nothing", os.path.isdir(legacy) and not os.path.islink(legacy)
          and not os.path.exists(backups) and dry["action"] == "migrate", dry)

    r = M.migrate(legacy, new, backups)
    check("the migration reports success", r.get("ok") is True and r["action"] == "migrate", r)
    check("every legacy file is now in the new directory",
          read(os.path.join(new, "logs", "daemon.log")) == "legacy daemon log\n"
          and read(os.path.join(new, "logs", "tasks", "daily.log")) == "task log\n"
          and os.path.isfile(os.path.join(new, "linkfix.json")), sorted(os.listdir(new)))
    check("files the new directory already had are kept",
          read(os.path.join(new, "guardian-state.json")) == '{"from": "guardian"}'
          and read(os.path.join(new, "logs", "guardian.log")) == "guardian log\n")
    kept = [f for f in os.listdir(new) if f.startswith("tasks-state.json.legacy-")]
    check("a file both sides had keeps the new copy and the legacy one alongside",
          read(os.path.join(new, "tasks-state.json")) == '{"from": "new"}' and len(kept) == 1
          and read(os.path.join(new, kept[0])) == '{"from": "legacy"}', (kept, r))
    check("~/.claude/state/brain is now a symlink to the new directory",
          os.path.islink(legacy) and os.path.realpath(legacy) == os.path.realpath(new), os.path.realpath(legacy))
    check("so a script still using the old path reads the moved files",
          read(os.path.join(legacy, "logs", "daemon.log")) == "legacy daemon log\n")
    bk = r.get("backup")
    check("the legacy directory was backed up to a tar.gz outside both locations",
          bk and os.path.isfile(bk) and not bk.startswith(legacy) and not os.path.realpath(bk).startswith(os.path.realpath(new)),
          bk)
    if bk and os.path.isfile(bk):
        with tarfile.open(bk) as tar:
            names = tar.getnames()
        check("and the backup holds the legacy files", any(n.endswith("logs/daemon.log") for n in names), names)

    again = M.migrate(legacy, new, backups)
    check("running it again is a no-op", again["action"] == "done" and again.get("ok") is True, again)

    rb = M.rollback(legacy, new, bk)
    check("rollback restores the legacy directory from the backup",
          rb.get("ok") is True and os.path.isdir(legacy) and not os.path.islink(legacy)
          and read(os.path.join(legacy, "tasks-state.json")) == '{"from": "legacy"}', rb)
    check("and leaves the new directory in place", os.path.isfile(os.path.join(new, "guardian-state.json")))


def test_edges(M):
    print("\n== fresh and refusal ==")
    h, legacy, new, backups = home()
    r = M.migrate(legacy, new, backups)
    check("on a fresh machine it creates the new directory and the compatibility symlink",
          r.get("ok") is True and os.path.isdir(new) and os.path.islink(legacy)
          and os.path.realpath(legacy) == os.path.realpath(new), r)

    h, legacy, new, backups = home()
    other = os.path.join(h, "elsewhere")
    os.makedirs(other)
    os.makedirs(os.path.dirname(legacy))
    os.symlink(other, legacy)
    r = M.migrate(legacy, new, backups)
    check("a legacy symlink pointing elsewhere is refused and left alone",
          r.get("ok") is False and os.path.realpath(legacy) == os.path.realpath(other) and not os.path.exists(new), r)

    h, legacy, new, backups = home()
    write(os.path.join(legacy, "a.json"), "{}")
    try:
        M.rollback(legacy, new, os.path.join(backups, "missing.tar.gz"))
        refused = False
    except M.MigrationError:
        refused = True
    check("rollback refuses when legacy is not the migration's symlink", refused and os.path.isdir(legacy))


def test_cli():
    print("\n== migrate_state.py command line ==")
    h, legacy, new, _ = home()
    write(os.path.join(legacy, "tasks-state.json"), "{}")
    env = dict(os.environ, HOME=h)
    env.pop("BRAIN_STATE", None)
    env.pop("XDG_STATE_HOME", None)
    p = subprocess.run([sys.executable, os.path.join(HERE, "migrate_state.py"), "status"], env=env,
                       capture_output=True, text=True, timeout=60)
    check("status names both locations and the pending migration, changing nothing",
          p.returncode == 0 and legacy in p.stdout and new in p.stdout and "migrate" in p.stdout
          and not os.path.islink(legacy), (p.returncode, p.stdout, p.stderr))
    probe = [sys.executable, "-c", "import brainlib; print(brainlib.STATE)"]
    before = subprocess.run(probe, cwd=HERE, env=env, capture_output=True, text=True, timeout=60).stdout.strip()
    p = subprocess.run([sys.executable, os.path.join(HERE, "migrate_state.py"), "migrate"], env=env,
                       capture_output=True, text=True, timeout=60)
    after = subprocess.run(probe, cwd=HERE, env=env, capture_output=True, text=True, timeout=60).stdout.strip()
    check("migrate moves the state and links the old path", p.returncode == 0 and os.path.islink(legacy),
          (p.returncode, p.stdout, p.stderr))
    check("brainlib used the legacy directory before and the new one after",
          before == legacy and after == new, (before, after))


def main():
    try:
        import migrate_state as M
        M.plan, M.migrate, M.rollback, M.MigrationError
    except Exception as exc:
        check("migrate_state imports", False, "%s: %s" % (type(exc).__name__, exc))
        return finish()
    for t in (test_plan, test_migrate, test_edges):
        try:
            t(M)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            check("%s ran to the end" % t.__name__, False, "%s: %s" % (type(exc).__name__, exc))
    try:
        test_cli()
    except Exception as exc:
        check("test_cli ran to the end", False, "%s: %s" % (type(exc).__name__, exc))
    return finish()


def finish():
    for d in TMP:
        shutil.rmtree(d, ignore_errors=True)
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
