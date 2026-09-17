#!/usr/bin/env python3
"""Where Brain coordinates with other machines: presence and file claims over a shared path.

  BRAIN_SHARED_DIR                        when set (a leading ~ is expanded)
  "dir" in <brain state>/shared-dir.json  written by the first run's multi_machine step
  neither                                 unconfigured: multi-machine coordination stays off

Unlike the files directory (brain_files.py), there is no proposed default here and no
required step: single-machine is the default this repo ships with, and every module that
might coordinate across machines (presence.py, claims_sync.py) checks `configured()` first and
behaves exactly as it does today when nothing is configured. The path itself is the user's own
synced folder — Dropbox, iCloud, a NAS mount, a USB drive — and this harness only reads and
writes files under it; syncing them to the other machine is that folder's job, not this one's.

Usage:  brain_shared.py      prints the shared path in use, or says it is not configured
"""
import json
import os
import sys

if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brain_paths  # noqa: E402

CONFIG_NAME = "shared-dir.json"


def _expand(value, home):
    if value == "~" or value.startswith("~/"):
        return home + value[1:]
    return value


def config_file(environ=None, home=None, platform=None):
    """<brain state>/shared-dir.json, the state directory as every other script sees it today."""
    return os.path.join(brain_paths.effective_state_dir(environ, home, platform), CONFIG_NAME)


def shared_dir(environ=None, home=None, config_path=None):
    """The shared coordination path, or None when nothing configures one (multi-machine off)."""
    environ = os.environ if environ is None else environ
    home = os.path.expanduser("~") if home is None else home

    explicit = (environ.get("BRAIN_SHARED_DIR") or "").strip()
    if explicit:
        return _expand(explicit, home)
    path = config_path or config_file(environ, home)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    value = data.get("dir") if isinstance(data, dict) else None
    if not isinstance(value, str) or not value.strip():
        return None
    return _expand(value.strip(), home)


def configured(environ=None, home=None, config_path=None):
    """The single on/off switch every cross-machine module checks before attempting anything."""
    return shared_dir(environ, home, config_path) is not None


def set_shared_dir(path, config_path=None):
    """Record the shared path: an atomic, private (0600) write. Returns the file written."""
    target = config_path or config_file()
    folder = os.path.dirname(target)
    if folder:
        os.makedirs(folder, mode=0o700, exist_ok=True)
    tmp = "%s.tmp.%d" % (target, os.getpid())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"dir": path}, ensure_ascii=False) + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, target)
    return target


def main():
    found = shared_dir()
    print("shared path: %s" % (found or "not configured (multi-machine coordination is off)"))
    print("config file: %s" % config_file())
    return 0 if found else 1


if __name__ == "__main__":
    sys.exit(main())
