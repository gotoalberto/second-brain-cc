#!/usr/bin/env python3
"""Tests for brain_shared — where Brain keeps the path it coordinates with other machines over.

Environment, home and the config file path are passed in. The only disk touched is a temporary
directory for the config file set_shared_dir writes. Run standalone:

    python3 _bin/brain_shared_test.py
"""
import json
import os
import shutil
import stat
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def main():
    try:
        import brain_shared as BS
        BS.shared_dir
    except Exception as exc:
        check("brain_shared.shared_dir imports", False, "%s: %s" % (type(exc).__name__, exc))
        print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
        return 1

    tmp = tempfile.mkdtemp(prefix="brain-shared-test-")
    try:
        home = "/home/someone"
        cfg = os.path.join(tmp, "state", "shared-dir.json")
        missing = os.path.join(tmp, "nowhere", "shared-dir.json")

        print("\n== resolution order ==")
        got = BS.shared_dir(environ={}, home=home, config_path=missing)
        check("with no variable and no config file, coordination is unconfigured (opt-in, no default)",
              got is None, got)

        got = BS.shared_dir(environ={"BRAIN_SHARED_DIR": "/srv/shared"}, home=home, config_path=missing)
        check("BRAIN_SHARED_DIR is used when set", got == "/srv/shared", got)

        got = BS.shared_dir(environ={"BRAIN_SHARED_DIR": "~/Dropbox/Brain"}, home=home, config_path=missing)
        check("a BRAIN_SHARED_DIR starting with ~ expands against the given home",
              got == "/home/someone/Dropbox/Brain", got)

        got = BS.shared_dir(environ={"BRAIN_SHARED_DIR": "   "}, home=home, config_path=missing)
        check("a blank BRAIN_SHARED_DIR is ignored", got is None, got)

        check("unconfigured means not configured()", BS.configured(environ={}, home=home, config_path=missing) is False)
        check("BRAIN_SHARED_DIR set means configured()",
              BS.configured(environ={"BRAIN_SHARED_DIR": "/srv/shared"}, home=home, config_path=missing) is True)

        written = BS.set_shared_dir("/data/brain-shared", config_path=cfg)
        check("set_shared_dir returns the file it wrote", written == cfg, written)
        check("the config file holds the directory under \"dir\"",
              json.load(open(cfg)) == {"dir": "/data/brain-shared"}, open(cfg).read())
        check("and is private (0600)", stat.S_IMODE(os.stat(cfg).st_mode) == 0o600,
              oct(stat.S_IMODE(os.stat(cfg).st_mode)))
        check("no temporary file is left beside it", os.listdir(os.path.dirname(cfg)) == ["shared-dir.json"],
              os.listdir(os.path.dirname(cfg)))

        got = BS.shared_dir(environ={}, home=home, config_path=cfg)
        check("the config file is used when no variable is set", got == "/data/brain-shared", got)
        check("and configured() agrees", BS.configured(environ={}, home=home, config_path=cfg) is True)

        got = BS.shared_dir(environ={"BRAIN_SHARED_DIR": "/override"}, home=home, config_path=cfg)
        check("BRAIN_SHARED_DIR wins over the config file", got == "/override", got)

        BS.set_shared_dir("~/BrainShared", config_path=cfg)
        got = BS.shared_dir(environ={}, home=home, config_path=cfg)
        check("a config value starting with ~ expands against the given home", got == "/home/someone/BrainShared", got)

        BS.set_shared_dir("/second", config_path=cfg)
        check("writing again replaces the value", BS.shared_dir(environ={}, home=home, config_path=cfg) == "/second")

        print("\n== a broken config file ==")
        for label, text in (("not JSON", "{nope"), ("JSON without dir", '{"other": 1}'),
                            ("a blank dir", '{"dir": "  "}'), ("a dir that is not text", '{"dir": 5}'),
                            ("a list", "[1]"), ("empty", "")):
            with open(cfg, "w") as fh:
                fh.write(text)
            got = BS.shared_dir(environ={}, home=home, config_path=cfg)
            check("%s reads as unconfigured" % label, got is None, got)

        print("\n== where the config file lives ==")
        got = BS.config_file(environ={"BRAIN_STATE": "/srv/state"}, home=home, platform="linux")
        check("it sits in the Brain state directory", got == "/srv/state/shared-dir.json", got)
        got = BS.config_file(environ={}, home="/home/x", platform="linux")
        check("which on Linux follows brain_paths: ~/.local/state/brain",
              got == "/home/x/.local/state/brain/shared-dir.json", got)

        state = os.path.join(tmp, "st")
        BS.set_shared_dir("/from-default-path", config_path=BS.config_file(environ={"BRAIN_STATE": state}))
        got = BS.shared_dir(environ={"BRAIN_STATE": state}, home=home)
        check("with no config_path given both sides agree on the file", got == "/from-default-path", got)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
