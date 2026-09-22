#!/usr/bin/env python3
"""remote_control.py: the Remote Control server this machine keeps running, so the Claude app can reach it.

  remote_control.py serve   start `claude remote-control --chrome --name <name>` from the recorded
                            working directory; what the launchd agent and the systemd user unit run
  remote_control.py show    print the recorded directory, name and command, and anything in the way

Every machine Brain is installed on is a Remote Control machine: it appears in the Claude app under
Remote Control and a session opened there runs on this machine, with its files, credentials and
browser. The server is a long-lived process, supervised (launchd KeepAlive on macOS, systemd
Restart=always on Linux), because it gives up and exits after about ten minutes without network.

The supervisor templates (`com.secondbrain.remote-control.plist`, `systemd/second-brain-remote-control.service`)
carry nothing per machine, so the guardian can keep them in step like every other job. What is per
machine lives in <brain state>/remote-control.json, written by the first run's remote_control step:

  dir    the working directory sessions open in: the home directory by default, so a session started
         from the app opens where you would open a terminal. A dedicated folder or repository works too.
         No git repository is needed, because spawn mode stays same-dir (see --spawn below). Workspace
         trust is kept per directory, the home directory included (projects[<dir>].hasTrustDialogAccepted
         in ~/.claude.json), and is accepted once, interactively.
  name   passed as --name; it titles the sessions. The label the app groups them under is the server's
         environment, which the server is assigned and which is renamed from the app.

Three things are not arbitrary:
  --chrome is always passed. The claudeInChromeDefaultEnabled setting does not cover server mode, and
           without the flag every session has no browser tools.
  --spawn  is never passed. A worktree spawn mode conflicts with Brain's WorktreeCreate hook
           (seed_worktree.py) and every session dies at birth, hanging on "Connecting...". It is also
           the only mode that would need the working directory to be a git repository.
  env      DISABLE_TELEMETRY, DO_NOT_TRACK, CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC and DISABLE_GROWTHBOOK
           switch off the feature flags Remote Control depends on, and ANTHROPIC_API_KEY or
           CLAUDE_CODE_OAUTH_TOKEN would replace the claude.ai login it needs; serve drops all of them.
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
# Remote Control takes only the CLI's claude.ai login; either of these in the environment takes precedence over it.
CREDENTIAL_ENV = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")
EX_CONFIG = 78
# Where the CLI is looked for after PATH: the native installer's ~/.local/bin first, then the Homebrew
# locations (Apple silicon, Intel). The native installer is preferred: the Homebrew cask can lag
# several releases behind, and an old CLI rejects --chrome.
CANDIDATES = ("~/.local/bin/claude", "/opt/homebrew/bin/claude", "/usr/local/bin/claude")
SHELLS = ("sh", "bash", "zsh", "dash", "ksh")


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


def credential_env(environ):
    """An API key or setup-token set here, which would stand in for the claude.ai login."""
    return sorted(k for k in CREDENTIAL_ENV if (environ.get(k) or "").strip())


def server_env(environ):
    return {k: v for k, v in environ.items() if k not in BLOCKING_ENV and k not in CREDENTIAL_ENV}


def _read_head(path, size=256):
    try:
        with open(path, "rb") as fh:
            return fh.read(size)
    except OSError:
        return b""


def is_wrapper(path, read=_read_head):
    """A shell script standing in for the CLI, like a ~/bin/claude that adds its own flags.

    The server must not go through one: whatever it adds (a permissions bypass, say) lands on the
    server too, and a wrapper that drops "$@" silently drops --chrome. The native binary, and the
    node script an npm install links, are not wrappers.
    """
    head = read(path) or b""
    if not head.startswith(b"#!"):
        return False
    words = head[2:].split(b"\n", 1)[0].decode("utf-8", "replace").split()
    if not words:
        return False
    interpreter = os.path.basename(words[0])
    if interpreter == "env" and len(words) > 1:
        interpreter = os.path.basename(words[-1])
    return interpreter in SHELLS


def find_claude(environ, home, which=shutil.which, read=_read_head):
    """The claude CLI: on PATH, then ~/.local/bin, /opt/homebrew/bin and /usr/local/bin.

    A real CLI wins over a shell wrapper wherever each is found; a wrapper is returned only when
    nothing else is there, and warnings() then says so.
    """
    seen = []
    first = which("claude", path=environ.get("PATH"))
    if first:
        seen.append(first)
    for candidate in CANDIDATES:
        path = os.path.join(home, candidate[2:]) if candidate.startswith("~/") else candidate
        if path not in seen and os.path.isfile(path) and os.access(path, os.X_OK):
            seen.append(path)
    for path in seen:
        if not is_wrapper(path, read):
            return path
    return seen[0] if seen else None


def warnings(claude, read=_read_head):
    """What does not stop the server but deserves a look, one line each."""
    if claude and is_wrapper(claude, read):
        return ["%s is a shell wrapper, not the CLI: the server gets whatever it adds, and loses --chrome if it "
                "does not pass \"$@\" through; install Claude Code with its native installer" % claude]
    return []


def problems(config, exists, is_root, claude):
    """Why the server cannot start here, one line each; [] when it can."""
    out = []
    if is_root:
        out.append("running as root: Claude Code refuses to bypass permissions there; use a normal user")
    if not claude:
        out.append("no claude CLI on PATH, in ~/.local/bin, /opt/homebrew/bin or /usr/local/bin")
    if config is None:
        out.append("nothing recorded: run the first run's remote_control step "
                   "(python3 integrations/first-run/first_run.py reset remote_control, then run)")
        return out
    if not exists(config["dir"]):
        out.append("the working directory %s is not there" % config["dir"])
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
        for line in warnings(claude):
            print("warning:   %s" % line)
        for name in blocking_env(environ):
            print("note:      %s is set in this shell; serve drops it before starting" % name)
        return 1 if found else 0
    if found:
        for line in found:
            print("remote_control.py: %s" % line, file=sys.stderr)
        return EX_CONFIG
    for line in warnings(claude):
        print("remote_control.py: warning: %s" % line, file=sys.stderr)
    os.chdir(config["dir"])
    os.execve(claude, command(config["name"], claude), server_env(environ))


if __name__ == "__main__":
    sys.exit(main())
