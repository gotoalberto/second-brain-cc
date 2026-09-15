#!/usr/bin/env python3
"""Tests for brain_paths.state_dir — where Brain keeps its own state.

Every input (environment, home, platform) is passed in; nothing on disk is read or
created. Run standalone:

    python3 _bin/brain_paths_test.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def main():
    try:
        import brain_paths as BP
        BP.state_dir
    except Exception as exc:
        check("brain_paths.state_dir imports", False, "%s: %s" % (type(exc).__name__, exc))
    else:
        home = "/home/someone"
        got = BP.state_dir(environ={}, home=home, platform="darwin")
        check("on macOS the default is ~/Library/Application Support/brain",
              got == "/home/someone/Library/Application Support/brain", got)
        check("the default is never under ~/.claude", ".claude" not in got, got)

        got = BP.state_dir(environ={"BRAIN_STATE": "/srv/brain-state"}, home=home, platform="darwin")
        check("BRAIN_STATE wins over the default", got == "/srv/brain-state", got)

        got = BP.state_dir(environ={"BRAIN_STATE": "~/state/brain"}, home=home, platform="darwin")
        check("a BRAIN_STATE starting with ~ expands against the given home",
              got == "/home/someone/state/brain", got)

        got = BP.state_dir(environ={"BRAIN_STATE": "  "}, home=home, platform="darwin")
        check("a blank BRAIN_STATE is ignored",
              got == "/home/someone/Library/Application Support/brain", got)

        got = BP.state_dir(environ={}, home="/home/x", platform="linux")
        check("elsewhere the default follows XDG: ~/.local/state/brain",
              got == "/home/x/.local/state/brain", got)
        got = BP.state_dir(environ={"XDG_STATE_HOME": "/var/xdg"}, home="/home/x", platform="linux")
        check("and honours XDG_STATE_HOME when set", got == "/var/xdg/brain", got)

        print("\n== effective_state_dir (migration-aware) ==")
        legacy = "/home/someone/.claude/state/brain"
        new_dir = "/home/someone/Library/Application Support/brain"
        check("the legacy location is ~/.claude/state/brain", BP.legacy_state_dir(home) == legacy,
              BP.legacy_state_dir(home))

        def world(dirs=(), links=()):
            return dict(isdir=lambda p: p in dirs or p in links, islink=lambda p: p in links)

        got = BP.effective_state_dir(environ={}, home=home, platform="darwin", **world(dirs={legacy}))
        check("before migration (legacy is a real directory) brainlib keeps using it", got == legacy, got)
        got = BP.effective_state_dir(environ={}, home=home, platform="darwin", **world(dirs={legacy, new_dir}))
        check("even when the new directory already exists (the guardian created it)", got == legacy, got)
        got = BP.effective_state_dir(environ={}, home=home, platform="darwin", **world(dirs={new_dir}, links={legacy}))
        check("after migration (legacy is a symlink) the new directory is used", got == new_dir, got)
        got = BP.effective_state_dir(environ={}, home=home, platform="darwin", **world())
        check("on a fresh machine the new directory is used", got == new_dir, got)
        got = BP.effective_state_dir(environ={"BRAIN_STATE": "/srv/x"}, home=home, platform="darwin",
                                     **world(dirs={legacy}))
        check("BRAIN_STATE wins over both", got == "/srv/x", got)

        real = BP.state_dir()
        check("called with no arguments it resolves from the real environment",
              isinstance(real, str) and os.path.isabs(real), real)
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
