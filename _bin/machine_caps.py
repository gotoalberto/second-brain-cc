#!/usr/bin/env python3
"""What THIS machine is and what it has right now: the `## This machine` startup block.

A session that guesses its machine from the OS guesses wrong ("this is Linux, so there is no
browser" while that machine had its own Chrome with the Claude extension). compass.py prints this
block at the start of every session so nobody has to guess, and the protocol says to trust it or
probe, never the OS alone.

Only local, cheap probes: tools on PATH, a few files, the machine key, this machine's registry
record (machines.py), the agent tasks pinned here (routine_requires.py), one `ps -eo command` (is
Chrome running, does the Remote Control server carry `--chrome`) and on Linux one `systemctl
is-active` for the X desktop unit. No network and no Claude call; every subprocess is bounded by a
short timeout. SessionStart has an 8 s budget and this stays far inside it.

`render()` is pure (a dict in, text out) and `probe()` takes every effect as a parameter, the
same split as the rest of `_bin/`. See machine_caps_test.py.

    machine_caps.py        print the block
"""
import os
import shutil
import subprocess
import sys

if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TOOLS = ("git", "gh", "python3", "claude", "keepassxc-cli", "jq", "rg")
PRIORITY = 92
NATIVE_HOST = "com.anthropic.claude_code_browser_extension.json"
_LINUX_CHROME = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")
_MAC_CHROME = "/Applications/Google Chrome.app"
_MAC_CHROME_MAIN = "Google Chrome.app/Contents/MacOS/Google Chrome"
_LINUX_CHROME_PROCS = ("chrome", "chromium", "chromium-browser", "google-chrome", "google-chrome-stable")
# The X desktop Chrome lives in on Linux, a system unit (the install runbook calls it vnc-desktop).
DESKTOP_UNIT_ENV = "BRAIN_DESKTOP_UNIT"
DEFAULT_DESKTOP_UNIT = "vnc-desktop"
CATALOGUE_NOTE = "2026-09-12-reference-tool-and-service-catalogue"
RC_RESTART = {
    "launchd": "launchctl kickstart -k gui/$(id -u)/com.secondbrain.remote-control",
    "systemd": "systemctl --user restart second-brain-remote-control",
}
# What decides whether a SESSION has the browser. The block describes the machine; only the tool
# list of the session itself answers for the session (detail: the where-claude-in-chrome note).
SESSION_RULE = ("This line describes the MACHINE, not your session. Listed `mcp__claude-in-chrome__*` tools "
                "(deferred counts) mean you have the browser: use them, whatever this block, `claude mcp list` or "
                "`~/.claude.json` say. None listed: started without `--chrome`, offer "
                "`claude --chrome --continue`.")


def _browser_line(chrome, scheduler):
    """The Browser line for a probe's chrome dict. Pure."""
    if not chrome.get("installed"):
        return "- Browser: no local Chrome. Another machine's may still be listed by `list_connected_browsers`."
    running = chrome.get("running")
    usable = chrome.get("paired") and running is not False
    parts = ["Chrome paired" if chrome.get("paired") else "Chrome NOT paired (`claude --chrome` once)"]
    if running is not None:
        parts.append("running" if running else "NOT running")
    rc = chrome.get("remote_control")
    if rc == "with":
        parts.append("Remote Control has `--chrome`")
    elif rc == "without":
        hint = RC_RESTART.get(scheduler)
        parts.append("Remote Control WITHOUT `--chrome`" +
                     (" (restart: `%s`)" % hint if hint else ""))
    desktop = chrome.get("desktop")
    if desktop:
        parts.append("X `%s` %s" % (desktop[0], desktop[1] or "unknown"))
    login = chrome.get("login")
    if login == "present":
        parts.append("CLI logged in")
    elif login == "absent":
        parts.append("no CLI login for browser routines (`claude auth login`)")
    elif login == "check":
        parts.append("CLI login: `claude auth status`")
    return "- Browser (the user's logged-in sessions): %s: %s. %s" % (
        "**usable**" if usable else "**not usable now**", ", ".join(parts), SESSION_RULE)


def render(caps):
    """The startup block for a probe result. Pure: the same dict always gives the same text."""
    who = "- **%s** (%s, user `%s`)" % (caps.get("key") or "?", caps.get("os") or "?", caps.get("user") or "?")
    if caps.get("registered"):
        account = caps.get("claude_account")
        who += ", Claude account `%s`" % account if account else ", registered"
    else:
        who += ", not registered (`python3 ~/Brain/_bin/machines.py register`)"
    lines = ["", "## This machine", who, "- Scheduler: %s" % (caps.get("scheduler") or "none found")]

    tools = caps.get("tools") or []
    have = [n for n, present in tools if present]
    missing = [n for n, present in tools if not present]
    line = "- Tools: present " + (", ".join("`%s`" % n for n in have) or "none")
    if missing:
        line += "; absent " + ", ".join("`%s`" % n for n in missing)
    lines.append(line)

    lines.append(_browser_line(caps.get("chrome") or {}, caps.get("scheduler")))

    tasks = caps.get("tasks_here")
    if tasks:
        lines.append("- %d enabled agent task(s) run here (%s); preflight: "
                     "`python3 ~/Brain/_bin/routine_requires.py here`" % (len(tasks), ", ".join(tasks)))
    lines.append("- Tools, keys, MCP servers per machine: [[%s]]. Never decide from the OS alone." % CATALOGUE_NOTE)
    return "\n".join(lines)


def _safe(fn, default):
    try:
        return fn()
    except Exception:
        return default


def _default_key():
    import machine_identity
    return machine_identity.current_key()


def _default_here():
    import machines
    return machines.here()


def _default_tasks_here():
    import routine_requires
    return [task_id for task_id, _path in routine_requires.tasks_here()]


def _run(cmd, timeout=1.5):
    """(returncode, stdout) of a short local command; (127, "") when it cannot run."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "").strip()
    except (OSError, subprocess.SubprocessError):
        return 127, ""


def chrome_running(commands, mac):
    """Is Chrome's main process among these command lines? None when they could not be read."""
    if commands is None:
        return None
    for line in commands:
        if mac:
            if _MAC_CHROME_MAIN in line:
                return True
        else:
            words = line.split()
            if words and os.path.basename(words[0]) in _LINUX_CHROME_PROCS:
                return True
    return False


def remote_control_flag(commands):
    """"with" or "without" `--chrome` for a running Remote Control server, None when none runs.

    Only `--chrome` at launch attaches the browser tools, so for sessions handed out by the
    Claude app the server itself must carry it. Read from `ps -eo command`: BSD pgrep on macOS
    has no -a, and `pgrep -af` there prints only pids, which would silently drop the check.
    """
    for line in commands or ():
        words = line.split()
        if "remote-control" in words and "grep" not in words[0]:
            return "with" if "--chrome" in words else "without"
    return None


def probe(which=None, exists=None, platform=None, home=None, environ=None, key=None, here=None, tasks_here=None,
          run=None):
    """What this machine has right now, as a plain dict for render(). Never raises.

    Every effect is a parameter: `which(name)` like shutil.which, `exists(path)`, `run(cmd)`
    returning (returncode, stdout), and three callables for the machine key, this machine's
    registry record and the ids of the enabled agent tasks pinned here. A probe that fails
    degrades to "unknown", never to an exception.
    """
    which = which or shutil.which
    exists = exists or os.path.exists
    platform = sys.platform if platform is None else platform
    home = os.path.expanduser("~") if home is None else home
    environ = os.environ if environ is None else environ
    run = run or _run
    mac = platform == "darwin"

    record = _safe(here or _default_here, None) or None
    if mac:
        scheduler = "launchd" if which("launchctl") else ""
        chrome_installed = exists(_MAC_CHROME)
        hosts = [os.path.join(home, "Library", "Application Support", "Google", "Chrome", "NativeMessagingHosts")]
    else:
        scheduler = "systemd" if which("systemctl") else ("cron" if which("crontab") else "")
        chrome_installed = any(which(n) for n in _LINUX_CHROME)
        hosts = [os.path.join(home, ".config", "google-chrome", "NativeMessagingHosts"),
                 os.path.join(home, ".config", "chromium", "NativeMessagingHosts")]
    paired = chrome_installed and any(exists(os.path.join(h, NATIVE_HOST)) for h in hosts)
    chrome = {"installed": bool(chrome_installed), "paired": bool(paired)}
    if chrome_installed:
        code, out = _safe(lambda: run(["ps", "-eo", "command"]), (127, ""))
        commands = out.splitlines() if code == 0 else None
        chrome["running"] = chrome_running(commands, mac)
        chrome["remote_control"] = remote_control_flag(commands)
        if not mac and which("systemctl"):
            unit = environ.get(DESKTOP_UNIT_ENV) or DEFAULT_DESKTOP_UNIT
            _code, state = _safe(lambda: run(["systemctl", "is-active", unit]), (127, ""))
            chrome["desktop"] = (unit, state.splitlines()[0] if state else "")
        if mac:                      # the login lives in the Keychain, not in a file
            chrome["login"] = "check"
        else:
            chrome["login"] = ("present" if exists(os.path.join(home, ".claude", ".credentials.json"))
                               else "absent")
    return {
        "key": _safe(key or _default_key, "?") or "?",
        "os": "macOS" if mac else ("Linux" if platform.startswith("linux") else platform),
        "user": environ.get("USER") or environ.get("LOGNAME") or "?",
        "registered": bool(record),
        "claude_account": (record or {}).get("claude_account", "") if isinstance(record, dict) else "",
        "scheduler": scheduler,
        "tools": [(n, bool(which(n))) for n in TOOLS],
        "chrome": chrome,
        "tasks_here": _safe(tasks_here or _default_tasks_here, None),
    }


def section(probe_fn=None):
    """("machine", text, PRIORITY) for compass.build_sections(), or None. Never raises."""
    try:
        return ("machine", render((probe_fn or probe)()), PRIORITY)
    except Exception:
        return None


def main():
    print(render(probe()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
