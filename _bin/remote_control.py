#!/usr/bin/env python3
"""remote_control.py — the Remote Control server this machine keeps running, so the Claude app can reach it.

  remote_control.py serve   start `claude remote-control --chrome --name <name>` from the dedicated
                            repository; what the launchd agent and the systemd user unit run
  remote_control.py show    print the recorded directory, name and command, and anything in the way

Every machine Brain is installed on is a Remote Control machine: it appears in the Claude app under
Remote Control and a session opened there runs on this machine, with its files, credentials and
browser. The server is a long-lived process, supervised (launchd KeepAlive on macOS, systemd
Restart=always on Linux), because it gives up and exits after about ten minutes without network.

The supervisor templates (`com.secondbrain.remote-control.plist`, `systemd/second-brain-remote-control.service`)
carry nothing per machine, so the guardian can keep them in step like every other job. What is per
machine lives in <brain state>/remote-control.json, written by the first run's remote_control step:

  dir    a small dedicated git repository, not the vault and not the home directory: the app lists the
         machine under that repository's name, and workspace trust is only ever kept for a repository
  name   passed as --name; it titles the sessions

Three things are not arbitrary:
  --chrome is always passed. The claudeInChromeDefaultEnabled setting does not cover server mode, and
           without the flag every session has no browser tools.
  --spawn  is never passed. A worktree spawn mode conflicts with Brain's WorktreeCreate hook
           (seed_worktree.py) and every session dies at birth, hanging on "Connecting...".
  env      DISABLE_TELEMETRY, DO_NOT_TRACK, CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC and DISABLE_GROWTHBOOK
           switch off the feature flags Remote Control depends on; serve drops them before starting.
"""
import json
import os
import shutil
import sys

if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brain_paths  # noqa: E402

CONFIG_NAME = "remote-control.json"
BLOCKING_ENV = ("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "DISABLE_GROWTHBOOK", "DISABLE_TELEMETRY", "DO_NOT_TRACK")
EX_CONFIG = 78


def config_file(environ=None, home=None, platform=None):
    """<brain state>/remote-control.json."""
    return os.path.join(brain_paths.effective_state_dir(environ, home, platform), CONFIG_NAME)


def load(path):
    """{"dir", "name"} as recorded, or None when nothing usable is."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    folder, name = data.get("dir"), data.get("name")
    if not (isinstance(folder, str) and folder.strip() and isinstance(name, str) and name.strip()):
        return None
    return {"dir": folder.strip(), "name": name.strip()}


def save(folder, name, config_path=None):
    """Record the working directory and name: an atomic, private (0600) write. Returns the file written."""
    target = config_path or config_file()
    parent = os.path.dirname(target)
    if parent:
        os.makedirs(parent, mode=0o700, exist_ok=True)
    tmp = "%s.tmp.%d" % (target, os.getpid())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"dir": folder, "name": name}, ensure_ascii=False) + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, target)
    return target


def command(name, claude="claude"):
    return [claude, "remote-control", "--chrome", "--name", name]


def blocking_env(environ):
    """The variables set here that would stop Remote Control from working."""
    return sorted(k for k in BLOCKING_ENV if (environ.get(k) or "").strip())


def server_env(environ):
    return {k: v for k, v in environ.items() if k not in BLOCKING_ENV}


def find_claude(environ, home, which=shutil.which):
    """The claude CLI: on PATH, or in ~/.local/bin where its installer puts it."""
    found = which("claude", path=environ.get("PATH"))
    if found:
        return found
    local = os.path.join(home, ".local", "bin", "claude")
    return local if os.path.isfile(local) and os.access(local, os.X_OK) else None


def problems(config, exists, is_root, claude):
    """Why the server cannot start here, one line each; [] when it can."""
    out = []
    if is_root:
        out.append("running as root: Claude Code refuses to bypass permissions there; use a normal user")
    if not claude:
        out.append("no claude CLI on PATH or in ~/.local/bin")
    if config is None:
        out.append("nothing recorded: run the first run's remote_control step "
                   "(python3 integrations/first-run/first_run.py reset remote_control, then run)")
        return out
    if not exists(config["dir"]):
        out.append("the working directory %s is not there" % config["dir"])
    elif not exists(os.path.join(config["dir"], ".git")):
        out.append("%s is not a git repository: workspace trust is only kept for one" % config["dir"])
    return out


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if args not in (["serve"], ["show"]):
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        return 2
    environ, home = os.environ, os.path.expanduser("~")
    path = config_file(environ, home)
    config = load(path)
    claude = find_claude(environ, home)
    is_root = hasattr(os, "geteuid") and os.geteuid() == 0
    found = problems(config, os.path.exists, is_root, claude)
    if args == ["show"]:
        print("config:    %s" % path)
        if config:
            print("directory: %s" % config["dir"])
            print("command:   %s" % " ".join(command(config["name"], claude or "claude")))
        for line in found:
            print("problem:   %s" % line)
        for name in blocking_env(environ):
            print("note:      %s is set in this shell; serve drops it before starting" % name)
        return 1 if found else 0
    if found:
        for line in found:
            print("remote_control.py: %s" % line, file=sys.stderr)
        return EX_CONFIG
    os.chdir(config["dir"])
    os.execve(claude, command(config["name"], claude), server_env(environ))


if __name__ == "__main__":
    sys.exit(main())
