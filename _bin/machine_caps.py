#!/usr/bin/env python3
"""What THIS machine is and what it has right now: the `## This machine` startup block.

A session that guesses its machine from the OS guesses wrong ("this is Linux, so there is no
browser" while that machine had its own Chrome with the Claude extension). compass.py prints this
block at the start of every session so nobody has to guess, and the protocol says to trust it or
probe, never the OS alone.

Only local, cheap probes: tools on PATH, a few files, the machine key, this machine's registry
record (machines.py) and the agent tasks pinned here (routine_requires.py). No network, no Claude
call, no subprocess beyond what `machine_identity.current_key()` already does. SessionStart has an
8 s budget and this stays far inside it.

`render()` is pure (a dict in, text out) and `probe()` takes every effect as a parameter, the
same split as the rest of `_bin/`. See machine_caps_test.py.

    machine_caps.py        print the block
"""
import os
import shutil
import sys

if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TOOLS = ("git", "gh", "python3", "claude", "keepassxc-cli", "jq", "rg")
PRIORITY = 92
NATIVE_HOST = "com.anthropic.claude_code_browser_extension.json"
_LINUX_CHROME = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")
_MAC_CHROME = "/Applications/Google Chrome.app"


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

    chrome = caps.get("chrome") or {}
    if not chrome.get("installed"):
        lines.append("- Browser: no local Chrome. Another machine's may still be listed by `list_connected_browsers`.")
    elif chrome.get("paired"):
        lines.append("- Browser: local Chrome installed, paired with Claude Code.")
    else:
        lines.append("- Browser: local Chrome installed, NOT paired with Claude Code (run `claude --chrome` once).")

    tasks = caps.get("tasks_here")
    if tasks:
        lines.append("- %d enabled agent task(s) run here (%s); preflight: "
                     "`python3 ~/Brain/_bin/routine_requires.py here`" % (len(tasks), ", ".join(tasks)))
    lines.append("- Decide what this machine can do from this block or a probe, never from the OS alone.")
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


def probe(which=None, exists=None, platform=None, home=None, environ=None, key=None, here=None, tasks_here=None):
    """What this machine has right now, as a plain dict for render(). Never raises.

    Every effect is a parameter: `which(name)` like shutil.which, `exists(path)`, and three
    callables for the machine key, this machine's registry record and the ids of the enabled
    agent tasks pinned here. A probe that fails degrades to "unknown", never to an exception.
    """
    which = which or shutil.which
    exists = exists or os.path.exists
    platform = sys.platform if platform is None else platform
    home = os.path.expanduser("~") if home is None else home
    environ = os.environ if environ is None else environ
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
    return {
        "key": _safe(key or _default_key, "?") or "?",
        "os": "macOS" if mac else ("Linux" if platform.startswith("linux") else platform),
        "user": environ.get("USER") or environ.get("LOGNAME") or "?",
        "registered": bool(record),
        "claude_account": (record or {}).get("claude_account", "") if isinstance(record, dict) else "",
        "scheduler": scheduler,
        "tools": [(n, bool(which(n))) for n in TOOLS],
        "chrome": {"installed": bool(chrome_installed), "paired": bool(paired)},
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
