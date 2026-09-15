#!/usr/bin/env python3
"""Tests for brain_files — where Brain keeps files (deliverables, intermediates, material).

Environment, home and the config file path are passed in. The only disk touched is a
temporary directory for the config file set_files_dir writes. Run standalone:

    python3 _bin/brain_files_test.py
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
        import brain_files as BF
        BF.files_dir
    except Exception as exc:
        check("brain_files.files_dir imports", False, "%s: %s" % (type(exc).__name__, exc))
        print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
        return 1

    tmp = tempfile.mkdtemp(prefix="brain-files-test-")
    try:
        home = "/home/someone"
        cfg = os.path.join(tmp, "state", "files-dir.json")
        missing = os.path.join(tmp, "nowhere", "files-dir.json")

        print("\n== resolution order ==")
        got = BF.files_dir(environ={}, home=home, config_path=missing)
        check("with no variable and no config file the files directory is unconfigured", got is None, got)

        got = BF.files_dir(environ={"BRAIN_FILES_DIR": "/srv/files"}, home=home, config_path=missing)
        check("BRAIN_FILES_DIR is used when set", got == "/srv/files", got)

        got = BF.files_dir(environ={"BRAIN_FILES_DIR": "~/Files"}, home=home, config_path=missing)
        check("a BRAIN_FILES_DIR starting with ~ expands against the given home", got == "/home/someone/Files", got)

        got = BF.files_dir(environ={"BRAIN_FILES_DIR": "   "}, home=home, config_path=missing)
        check("a blank BRAIN_FILES_DIR is ignored", got is None, got)

        written = BF.set_files_dir("/data/brain-files", config_path=cfg)
        check("set_files_dir returns the file it wrote", written == cfg, written)
        check("the config file holds the directory under \"dir\"",
              json.load(open(cfg)) == {"dir": "/data/brain-files"}, open(cfg).read())
        check("and is private (0600)", stat.S_IMODE(os.stat(cfg).st_mode) == 0o600,
              oct(stat.S_IMODE(os.stat(cfg).st_mode)))
        check("no temporary file is left beside it", os.listdir(os.path.dirname(cfg)) == ["files-dir.json"],
              os.listdir(os.path.dirname(cfg)))

        got = BF.files_dir(environ={}, home=home, config_path=cfg)
        check("the config file is used when no variable is set", got == "/data/brain-files", got)

        got = BF.files_dir(environ={"BRAIN_FILES_DIR": "/override"}, home=home, config_path=cfg)
        check("BRAIN_FILES_DIR wins over the config file", got == "/override", got)

        BF.set_files_dir("~/BrainFiles", config_path=cfg)
        got = BF.files_dir(environ={}, home=home, config_path=cfg)
        check("a config value starting with ~ expands against the given home", got == "/home/someone/BrainFiles", got)

        BF.set_files_dir("/second", config_path=cfg)
        check("writing again replaces the value", BF.files_dir(environ={}, home=home, config_path=cfg) == "/second")

        print("\n== a broken config file ==")
        for label, text in (("not JSON", "{nope"), ("JSON without dir", '{"other": 1}'),
                            ("a blank dir", '{"dir": "  "}'), ("a dir that is not text", '{"dir": 5}'),
                            ("a list", "[1]"), ("empty", "")):
            with open(cfg, "w") as fh:
                fh.write(text)
            got = BF.files_dir(environ={}, home=home, config_path=cfg)
            check("%s reads as unconfigured" % label, got is None, got)

        print("\n== where the config file lives ==")
        got = BF.config_file(environ={"BRAIN_STATE": "/srv/state"}, home=home, platform="linux")
        check("it sits in the Brain state directory", got == "/srv/state/files-dir.json", got)
        got = BF.config_file(environ={}, home="/home/x", platform="linux")
        check("which on Linux follows brain_paths: ~/.local/state/brain",
              got == "/home/x/.local/state/brain/files-dir.json", got)

        state = os.path.join(tmp, "st")
        BF.set_files_dir("/from-default-path", config_path=BF.config_file(environ={"BRAIN_STATE": state}))
        got = BF.files_dir(environ={"BRAIN_STATE": state}, home=home)
        check("with no config_path given both sides agree on the file", got == "/from-default-path", got)

        check("the proposed default is ~/BrainFiles on macOS and Linux alike",
              BF.default_files_dir(home) == "/home/someone/BrainFiles", BF.default_files_dir(home))

        check("the unconfigured message names the first-run step",
              "first_run.py" in BF.UNCONFIGURED and "files" in BF.UNCONFIGURED, BF.UNCONFIGURED)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
