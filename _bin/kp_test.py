#!/usr/bin/env python3
"""Tests for kp.py — the vault's only path to the local KeePass database.

Everything runs against a scratch HOME and state directory. keepassxc-cli is a fake shell
script that records what it was given; no real database, keychain, dialog or clipboard is
touched (BRAIN_KP_CACHE_BACKEND=none, BRAIN_KP_NOPROMPT=1). Run standalone:

    python3 _bin/kp_test.py
"""
import json
import re
import os
import shutil
import stat
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
KP = os.path.join(HERE, "kp.py")

ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


FAKE_CLI = """#!/bin/sh
# Fake keepassxc-cli: records argv and stdin, answers like a database that opens.
printf '%s\\n' "$@" > "{dir}/argv"
cat > "{dir}/stdin"
exit 0
"""


def world(root, db=None):
    home, state = os.path.join(root, "home"), os.path.join(root, "state")
    os.makedirs(home, exist_ok=True)
    os.makedirs(state, exist_ok=True)
    fake = os.path.join(root, "keepassxc-cli")
    with open(fake, "w") as fh:
        fh.write(FAKE_CLI.replace("{dir}", root))
    os.chmod(fake, 0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith("BRAIN_")}
    env.update(HOME=home, BRAIN_STATE=state, BRAIN_KP_STATE=state, BRAIN_VAULT=os.path.dirname(HERE),
               BRAIN_KP_CLI=fake, BRAIN_KP_NOPROMPT="1", BRAIN_KP_CACHE_BACKEND="none")
    if db:
        env["BRAIN_KP_DB"] = db
    return env, state


def run(env, *args, stdin=""):
    p = subprocess.run([sys.executable, KP] + list(args), env=env, input=stdin, capture_output=True,
                       text=True, timeout=60)
    return p.returncode, p.stdout, p.stderr


def import_kp(env):
    saved = dict(os.environ)
    os.environ.clear()
    os.environ.update(env)
    try:
        sys.modules.pop("kp", None)
        sys.path.insert(0, HERE)
        import kp  # noqa: F401
        return sys.modules["kp"]
    finally:
        os.environ.clear()
        os.environ.update(saved)


def main():
    root = tempfile.mkdtemp(prefix="kp-test-")
    try:
        if not os.path.exists(KP):
            check("kp.py exists", False, KP)
            print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
            return 1

        src = open(KP, encoding="utf-8").read()
        check("no absolute or remote database path is hardcoded as a default",
              not re.search(r"[\"'](?:/Users/|/home/|/Volumes/)", src)
              and not re.search(r"[\"'](?!kp://)[a-z][a-z0-9+.-]*://", src))
        check("no 1Password reference remains", "op://" not in src and "1Password" not in src)

        # ------------------------------------------------ where the database is
        env, state = world(os.path.join(root, "a"))
        K = import_kp(env)
        check("with nothing configured there is no database",
              K.resolve_db({}, {}) == "", K.resolve_db({}, {}))
        check("the first-run config names it",
              K.resolve_db({}, {"db": "~/vault.kdbx"}) == os.path.join(env["HOME"], "vault.kdbx")
              or K.resolve_db({}, {"db": "~/vault.kdbx"}).endswith("/vault.kdbx"),
              K.resolve_db({}, {"db": "~/vault.kdbx"}))
        check("BRAIN_KP_DB wins over the config",
              K.resolve_db({"BRAIN_KP_DB": "/srv/x.kdbx"}, {"db": "/srv/y.kdbx"}) == "/srv/x.kdbx")
        check("the config lives in the state directory",
              os.path.dirname(K.CONFIG) == state, K.CONFIG)
        check("the inbox defaults inside the state directory, not a cloud drive",
              K.INBOX.startswith(state), K.INBOX)
        check("the default group is Brain", K.GROUP_DEF == "Brain", K.GROUP_DEF)

        rc, out, err = run(env, "get", "apis/example")
        check("with no database configured a read exits EXIT_NODB and says how to configure one",
              rc == K.EXIT_NODB and ("kp.py init" in err or "first run" in err.lower()), (rc, err))

        rc, out, err = run(env, "status")
        check("status works with no database configured", rc == 0 and "not configured" in out, (rc, out, err))

        # ------------------------------------------------ init
        db = os.path.join(root, "a", "creds.kdbx")
        rc, out, err = run(env, "init", "--db", db)
        cfg_path = os.path.join(state, "kp-config.json")
        cfg = json.load(open(cfg_path)) if os.path.exists(cfg_path) else {}
        check("init records the database in the config", rc == 0 and cfg.get("db") == db, (rc, out, err, cfg))
        check("the config file is private (0600)",
              os.path.exists(cfg_path) and stat.S_IMODE(os.stat(cfg_path).st_mode) == 0o600)
        rc2, out2, _ = run(env, "init", "--db", db)
        check("init again with the same answer changes nothing", rc2 == 0 and "unchanged" in out2, out2)
        rc, out, err = run(env, "status")
        check("status shows the configured database", db in out, out)

        # ------------------------------------------------ headless: never prompts
        open(db, "wb").write(b"\x03\xd9\xa2\x9a" + b"\0" * 2048)
        rc, out, err = run(env, "get", "apis/example", "--pipe", "cat")
        check("headless with no cached master exits EXIT_NOMASTER instead of prompting",
              rc == K.EXIT_NOMASTER, (rc, err))

        # ------------------------------------------------ the master never reaches argv
        env_db = dict(env, BRAIN_KP_DB=db)
        K = import_kp(env_db)
        K.cli(["ls", K.DB], "correct-horse")
        argv = open(os.path.join(root, "a", "argv")).read()
        stdin = open(os.path.join(root, "a", "stdin")).read()
        check("keepassxc-cli gets the master on stdin", stdin.splitlines()[:1] == ["correct-horse"], stdin)
        check("and never in argv", "correct-horse" not in argv and db in argv, argv)

        # ------------------------------------------------ platform backends
        which_none = lambda name: None
        which_all = lambda name: "/usr/bin/" + name
        check("macOS caches the master in the Keychain", K.cache_backend("darwin", which_none, {}) == "keychain")
        check("Linux with secret-tool caches through libsecret",
              K.cache_backend("linux", which_all, {}) == "secret-tool")
        check("Linux without secret-tool does not cache", K.cache_backend("linux", which_none, {}) == "none")
        check("BRAIN_KP_CACHE_BACKEND overrides the choice",
              K.cache_backend("darwin", which_all, {"BRAIN_KP_CACHE_BACKEND": "none"}) == "none")
        check("macOS asks through an osascript dialog", K.dialog_backend("darwin", {}, which_none) == "osascript")
        check("Linux with a display and zenity asks through zenity",
              K.dialog_backend("linux", {"DISPLAY": ":0"}, which_all) == "zenity")
        check("Linux with no display falls back to the terminal",
              K.dialog_backend("linux", {}, which_all) == "tty")
        paste, copy = K.clipboard_commands("darwin", {}, which_none)
        check("macOS clipboard is pbpaste/pbcopy", paste[0].endswith("pbpaste") and copy[0].endswith("pbcopy"))
        paste, copy = K.clipboard_commands("linux", {"WAYLAND_DISPLAY": "w"}, which_all)
        check("Wayland clipboard is wl-paste/wl-copy", paste[0].endswith("wl-paste") and copy[0].endswith("wl-copy"))
        paste, copy = K.clipboard_commands("linux", {}, which_none)
        check("no clipboard tool means no clipboard", paste is None and copy is None)

        boot = os.path.join(root, "boot_id")
        open(boot, "w").write("abc-123\n")
        check("Linux boot id comes from the kernel's boot_id", K.boot_id("linux", proc_path=boot) == "abc-123")
        mac = K.ping_command("darwin", "host", which_all)
        lin = K.ping_command("linux", "host", which_all)
        check("ping waits in milliseconds on macOS and seconds on Linux",
              "1500" in mac and "2" in lin and "1500" not in lin, (mac, lin))
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
