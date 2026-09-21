#!/usr/bin/env python3
"""The machines running Brain: who they are, and which Claude account each one's CLI uses.

  machines.py              list every registered machine, newest first, this one starred
  machines.py register     write or refresh this machine's record
  machines.py here         print this machine's own record as JSON

Presence only shows machines with a session open right now. This registry keeps one record per
machine, `<registry>/<machine key>.json`, so two machines never write the same file. Where the
registry lives follows the same switch as presence and claims:

  <shared path>/machines   when brain_shared.configured() (the user's synced folder)
  <brain state>/machines   otherwise: single-machine, this machine only

Never a git-tracked vault folder: a record names a hostname, and that must not travel in a
public commit. The key is `machine_identity.current_key()`; the record keeps only the uuid's
8-hex fragment, never the full uuid. A record is rewritten when something about the machine
changes, or once a day for `last_seen`. The rules (merge, dedupe, rendering) live in
machines_core.py, which touches no disk; this file only reads, writes and asks the CLI.
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys

if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brain_paths  # noqa: E402
import brain_shared  # noqa: E402
import machine_identity  # noqa: E402
import machines_core as C  # noqa: E402

_KEY_FRAGMENT = re.compile(r"^(.*)-([0-9a-f]{8})$")


def registry_dir(environ=None, home=None, config_path=None):
    """<shared path>/machines when multi-machine is configured, else <brain state>/machines."""
    shared = brain_shared.shared_dir(environ, home, config_path)
    if shared:
        return os.path.join(shared, "machines")
    return os.path.join(brain_paths.effective_state_dir(environ, home), "machines")


def _run(cmd):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return p.returncode, p.stdout, p.stderr
    except Exception:
        return 1, "", "error"


def claude_account(run=None):
    """(account, org) this machine's CLI is signed into; (UNKNOWN_ACCOUNT, "") when it cannot say."""
    try:
        code, out, _err = (run or _run)(["claude", "auth", "status"])
    except Exception:
        return C.UNKNOWN_ACCOUNT, ""
    if code != 0:
        return C.UNKNOWN_ACCOUNT, ""
    return C.parse_claude_auth(out)


def describe(environ=None, run=None, platform=None, hostname=None, open_=None):
    """What this machine is, as plain strings. Nothing secret, and never the full uuid."""
    environ = os.environ if environ is None else environ
    platform = sys.platform if platform is None else platform
    forced = (environ.get("BRAIN_MACHINE_KEY") or "").strip()
    if forced:
        key = forced
        m = _KEY_FRAGMENT.match(forced.lower())
        frag, label = (m.group(2), forced[:len(m.group(1))]) if m else ("", forced)
    else:
        hostname = hostname if hostname is not None else os.uname().nodename
        uuid = machine_identity.read_uuid(platform, machine_identity._run, open_ or open)
        key, frag, label = machine_identity.machine_key(hostname, uuid), machine_identity.id8(uuid), \
            machine_identity.machine_label(hostname)
        uuid = None                      # read, folded into the key, let go
    account, org = claude_account(run)
    return {"key": key, "id8": frag, "label": label,
            "os": "macos" if platform == "darwin" else ("linux" if platform.startswith("linux") else platform),
            "user": environ.get("USER") or environ.get("LOGNAME") or "",
            "claude_account": account, "claude_org": org}


def _atomic_write(path, text):
    folder = os.path.dirname(path)
    os.makedirs(folder, mode=0o700, exist_ok=True)
    tmp = "%s.tmp.%d" % (path, os.getpid())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def read_all(folder=None):
    """Every valid record in the registry folder. A missing folder is an empty registry."""
    folder = folder or registry_dir()
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    out = []
    for name in names:
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(folder, name), encoding="utf-8") as fh:
                rec = C.parse(fh.read())
        except OSError:
            continue
        if rec:
            out.append(rec)
    return out


def register(today=None, info=None, folder=None):
    """Write this machine's record if it is new, changed or not seen today: (changed, path)."""
    today = today or dt.date.today().isoformat()
    folder = folder or registry_dir()
    info = info or describe()
    path = os.path.join(folder, C.filename(info["key"]))
    existing = None
    try:
        with open(path, encoding="utf-8") as fh:
            existing = C.parse(fh.read())
    except OSError:
        pass
    first = "" if existing else C.first_seen_elsewhere(read_all(folder), info)
    record, changed = C.merge(existing, info, today, first_seen=first)
    if changed:
        _atomic_write(path, C.dump(record))
    return changed, path


def list_machines(folder=None):
    """One entry per machine, newest first: {"entry": record, "aliases": [older keys]}."""
    return C.dedupe(read_all(folder))


def here(folder=None, environ=None):
    """This machine's own newest record, or None when it has not registered."""
    mine = [r for r in read_all(folder)
            if machine_identity.machine_is_mine(r["key"], environ=environ)]
    mine.sort(key=lambda r: r.get("last_seen") or "", reverse=True)
    return mine[0] if mine else None


def main(argv=None, environ=None, run=None, today=None):
    argv = sys.argv[1:] if argv is None else argv
    environ = os.environ if environ is None else environ
    today = today or dt.date.today().isoformat()
    cmd = argv[0] if argv else "list"
    folder = registry_dir(environ)
    if cmd == "register":
        changed, path = register(today, describe(environ, run), folder)
        print(("registered: %s" if changed else "unchanged: %s") % path)
        return 0
    if cmd == "here":
        rec = here(folder, environ)
        if rec is None:
            print("this machine has not registered yet: python3 _bin/machines.py register")
            return 1
        print(json.dumps(rec, ensure_ascii=False, indent=1))
        return 0
    if cmd != "list":
        print(__doc__)
        return 2
    print(C.render_list(list_machines(folder),
                        lambda k: machine_identity.machine_is_mine(k, environ=environ), today))
    return 0


if __name__ == "__main__":
    sys.exit(main())
