#!/usr/bin/env python3
"""Where Brain keeps files: deliverables, intermediate steps and source material. Resolved here and nowhere else.

  BRAIN_FILES_DIR                        when set (a leading ~ is expanded)
  "dir" in <brain state>/files-dir.json  written by the first run's files step
  neither                                unconfigured: files.py stops and says to run the first run

The files directory is a choice the user makes once, at the first run, and it is not machine
plumbing: that is why it is its own module and not part of brain_paths.py. The first run proposes
~/BrainFiles on every platform, so the files are easy to find, back up or point at a synced folder.

Usage:  brain_files.py      prints the files directory in use, or says it is not configured
"""
import json
import os
import sys

if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brain_paths  # noqa: E402

CONFIG_NAME = "files-dir.json"
UNCONFIGURED = ("no local files directory configured; run "
                "`integrations/first-run/first_run.py run` (step: files)")


def _expand(value, home):
    if value == "~" or value.startswith("~/"):
        return home + value[1:]
    return value


def config_file(environ=None, home=None, platform=None):
    """<brain state>/files-dir.json, the state directory as every other script sees it today."""
    return os.path.join(brain_paths.effective_state_dir(environ, home, platform), CONFIG_NAME)


def default_files_dir(home=None):
    """What the first run proposes: ~/BrainFiles, on macOS and Linux alike."""
    home = os.path.expanduser("~") if home is None else home
    return os.path.join(home, "BrainFiles")


def files_dir(environ=None, home=None, config_path=None):
    """The files directory, or None when nothing configures one."""
    environ = os.environ if environ is None else environ
    home = os.path.expanduser("~") if home is None else home

    explicit = (environ.get("BRAIN_FILES_DIR") or "").strip()
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


def set_files_dir(path, config_path=None):
    """Record the files directory: an atomic, private (0600) write. Returns the file written."""
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
    found = files_dir()
    print("files directory: %s" % (found or "not configured"))
    print("config file:     %s" % config_file())
    return 0 if found else 1


if __name__ == "__main__":
    sys.exit(main())
