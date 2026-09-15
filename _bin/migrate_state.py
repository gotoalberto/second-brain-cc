#!/usr/bin/env python3
"""Moves Brain's machine-local state out of ~/.claude/state/brain, and back if needed.

  migrate_state.py status                      both locations and what migrate would do
  migrate_state.py migrate [--dry-run] [--backup-dir DIR]
  migrate_state.py rollback <backup.tar.gz>    undo, from the backup migrate wrote

The state (logs, the task runner's state, markers, caches) belongs to Brain, not to any
agent, so it moves to brain_paths.state_dir() — ~/Library/Application Support/brain unless
BRAIN_STATE says otherwise. ~/.claude/state/brain becomes a symlink to it, so any script or
plist still naming the old path keeps working.

What migrate does, in order:
  1. a tar.gz of the whole legacy directory, written OUTSIDE both locations;
  2. every entry moved into the new directory. Directories both sides have are merged. A file
     both sides have keeps the new copy, and the legacy one is kept beside it as
     `<name>.legacy-<timestamp>`: nothing is overwritten or dropped;
  3. the emptied legacy directory replaced by the symlink, and the link verified.

Run it with Brain's launchd jobs stopped and no agent session open, so nothing writes the
legacy directory while it moves. It is idempotent: once linked, it reports `done`.
"""

import argparse
import os
import shutil
import sys
import tarfile
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


class MigrationError(Exception):
    """The migration or its rollback cannot proceed safely; nothing was changed."""


def plan(legacy, new):
    if os.path.islink(legacy):
        return "done" if os.path.realpath(legacy) == os.path.realpath(new) else "foreign-symlink"
    if not os.path.lexists(legacy):
        return "fresh"
    return "migrate"


def _move(src, dst):
    try:
        os.rename(src, dst)
    except OSError:
        shutil.move(src, dst)            # across filesystems


def _merge(src_dir, dst_dir, rel, stamp, moved, kept):
    for name in sorted(os.listdir(src_dir)):
        src, dst = os.path.join(src_dir, name), os.path.join(dst_dir, name)
        path = os.path.join(rel, name) if rel else name
        if os.path.isdir(src) and not os.path.islink(src) and os.path.isdir(dst) and not os.path.islink(dst):
            _merge(src, dst, path, stamp, moved, kept)
            os.rmdir(src)
        elif not os.path.lexists(dst):
            _move(src, dst)
            moved.append(path)
        else:
            alt = "%s.legacy-%s" % (dst, stamp)
            _move(src, alt)
            kept.append(path + ".legacy-" + stamp)


def migrate(legacy, new, backup_dir, dry_run=False, clock=time.time):
    action = plan(legacy, new)
    report = {"action": action, "legacy": legacy, "new": new, "moved": [], "kept_legacy": []}
    if action == "foreign-symlink":
        report.update(ok=False, error="%s is a symlink to %s, not to %s: left alone"
                      % (legacy, os.path.realpath(legacy), new))
        return report
    if dry_run or action == "done":
        report.update(ok=True, dry_run=dry_run)
        return report
    try:
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(clock()))
        if action == "migrate":
            os.makedirs(backup_dir, exist_ok=True)
            backup = os.path.join(backup_dir, "brain-state-%s.tar.gz" % stamp)
            with tarfile.open(backup, "w:gz") as tar:
                tar.add(legacy, arcname="brain")
            report["backup"] = backup
            os.makedirs(new, exist_ok=True)
            _merge(legacy, new, "", stamp, report["moved"], report["kept_legacy"])
            os.rmdir(legacy)
        else:
            os.makedirs(new, exist_ok=True)
            os.makedirs(os.path.dirname(legacy), exist_ok=True)
        os.symlink(new, legacy)
        if os.path.realpath(legacy) != os.path.realpath(new):
            raise MigrationError("the symlink %s does not resolve to %s" % (legacy, new))
        report["ok"] = True
    except Exception as exc:
        report.update(ok=False, error="%s: %s" % (type(exc).__name__, exc))
    return report


def rollback(legacy, new, backup):
    if not (os.path.islink(legacy) and os.path.realpath(legacy) == os.path.realpath(new)):
        raise MigrationError("%s is not the migration's symlink to %s: nothing to roll back" % (legacy, new))
    if not os.path.isfile(backup):
        raise MigrationError("backup not found: %s" % backup)
    parent = os.path.dirname(legacy)
    staging = tempfile.mkdtemp(prefix=".brain-rollback-", dir=parent)
    try:
        with tarfile.open(backup) as tar:
            for member in tar.getmembers():
                if member.name.startswith("/") or ".." in member.name.split("/"):
                    raise MigrationError("unsafe path in backup: %s" % member.name)
            try:
                tar.extractall(staging, filter="data")
            except TypeError:            # Python before the extraction filters
                tar.extractall(staging)
        restored = os.path.join(staging, "brain")
        if not os.path.isdir(restored):
            raise MigrationError("backup does not hold a brain/ directory: %s" % backup)
        os.remove(legacy)
        os.rename(restored, legacy)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return {"ok": True, "restored": legacy, "new_kept": new}


def _locations():
    import brain_paths

    new = brain_paths.state_dir()
    return brain_paths.legacy_state_dir(), new, os.path.join(os.path.dirname(new), "brain-state-migration-backups")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="migrate_state.py", description="move Brain's state out of ~/.claude")
    sub = ap.add_subparsers(dest="cmd", metavar="{status,migrate,rollback}")
    sub.add_parser("status", help="both locations and what migrate would do")
    m = sub.add_parser("migrate", help="move the state and link the old path")
    m.add_argument("--dry-run", action="store_true")
    m.add_argument("--backup-dir", default=None)
    r = sub.add_parser("rollback", help="restore the legacy directory from a migration backup")
    r.add_argument("backup")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)
    if not args.cmd:
        ap.print_help(sys.stderr)
        return 2
    legacy, new, backups = _locations()
    if args.cmd == "status":
        print("legacy: %s" % legacy)
        print("new:    %s" % new)
        print("plan:   %s" % plan(legacy, new))
        return 0
    if args.cmd == "migrate":
        report = migrate(legacy, new, args.backup_dir or backups, dry_run=args.dry_run)
        for key in ("action", "backup", "error"):
            if report.get(key):
                print("%-7s %s" % (key + ":", report[key]))
        print("moved:  %d entries; kept both copies of %d" % (len(report["moved"]), len(report["kept_legacy"])))
        for k in report["kept_legacy"]:
            print("  kept legacy copy: %s" % k)
        return 0 if report.get("ok") else 1
    try:
        print("restored: %s" % rollback(legacy, new, args.backup)["restored"])
        return 0
    except MigrationError as exc:
        print("rollback refused: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
