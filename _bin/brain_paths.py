#!/usr/bin/env python3
"""Where Brain keeps its own machine-local state. Resolved here and nowhere else.

  BRAIN_STATE                          when set (a leading ~ is expanded)
  ~/Library/Application Support/brain  on macOS
  $XDG_STATE_HOME/brain                elsewhere, or ~/.local/state/brain

Deliberately not under ~/.claude. State, logs, queues and ledgers belong to Brain, and
must survive an agent being uninstalled, reset, logged into another account or
replaced by a different one. Everything that needs the directory asks this module, so
moving it is one environment variable, not a hunt through every script.

Before the move, ~/.claude/state/brain is still where every existing script keeps its state:
`effective_state_dir()` returns that until migrate_state.py has moved it and left a symlink.

Usage:  brain_paths.py      prints the Brain state directory and the one in use today
"""
import os
import sys


def state_dir(environ=None, home=None, platform=None):
    environ = os.environ if environ is None else environ
    home = os.path.expanduser("~") if home is None else home
    platform = sys.platform if platform is None else platform

    explicit = (environ.get("BRAIN_STATE") or "").strip()
    if explicit:
        if explicit == "~" or explicit.startswith("~/"):
            explicit = home + explicit[1:]
        return explicit
    if platform == "darwin":
        return os.path.join(home, "Library", "Application Support", "brain")
    xdg = (environ.get("XDG_STATE_HOME") or "").strip()
    return os.path.join(xdg if xdg else os.path.join(home, ".local", "state"), "brain")


def legacy_state_dir(home=None):
    """Where Brain's state lived before it had its own directory: ~/.claude/state/brain."""
    home = os.path.expanduser("~") if home is None else home
    return os.path.join(home, ".claude", "state", "brain")


def effective_state_dir(environ=None, home=None, platform=None, isdir=os.path.isdir, islink=os.path.islink):
    """The state directory scripts should use today, migration taken into account.

    While ~/.claude/state/brain is still a real directory, the move has not happened on
    this machine and every script keeps using it — switching some scripts to an empty new
    directory while others still write the old one would split the state in two. Once
    migrate_state.py has moved it and left a symlink there, or on a machine that never had
    it, the new directory is used. BRAIN_STATE, when set, wins over both.
    """
    environ = os.environ if environ is None else environ
    if (environ.get("BRAIN_STATE") or "").strip():
        return state_dir(environ, home, platform)
    legacy = legacy_state_dir(home)
    if isdir(legacy) and not islink(legacy):
        return legacy
    return state_dir(environ, home, platform)


def main():
    print("brain state directory: %s" % state_dir())
    print("in use today:          %s" % effective_state_dir())
    return 0


if __name__ == "__main__":
    sys.exit(main())
