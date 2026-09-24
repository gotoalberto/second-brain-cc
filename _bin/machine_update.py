#!/usr/bin/env python3
"""What needs updating on this machine for Claude, and how. The same script on macOS and Linux.

  machine_update.py            report only: every component, its version, what is stale
  machine_update.py apply      update what is safe to update from here, then report again
  machine_update.py --json     the report as JSON (also with apply)

Components it looks at:

  cli      the native Claude Code install, ~/.local/bin/claude (a symlink into
           ~/.local/share/claude/versions/<v>). With `autoUpdates` off it drifts behind the
           release channel until someone runs `claude update`.
  rc       the Remote Control server (launchd com.secondbrain.remote-control on macOS, the
           systemd user unit second-brain-remote-control on Linux). It resolves the CLI symlink
           ONCE at startup, so after an update every session it hands out keeps the old binary,
           and the old binary's model list, until the server restarts. This is how a new model
           shows up in local sessions and not in the ones opened from the Claude app.
  app      the Claude desktop app's bundled Claude Code (macOS). It updates itself; only reported.
  brew     a Homebrew `claude-code` cask (macOS). remote_control.py prefers the native install,
           so it is usually unused; only reported.

What `apply` does on its own, and what it never does:

  * `claude update` on the CLI: always, it only moves a symlink.
  * macOS rc restart (`launchctl kickstart -k`): only when the server has no session child AND
    this process is not one of its descendants (restarting would kill ourselves).
  * Linux rc restart: NEVER. `systemctl --user restart` stops the unit's whole cgroup: every
    session and everything a session ever started inside it (a dev server, an OAuth flow
    waiting on a local port), including processes that outlived the session that started them,
    so "no child session" does not mean idle there. It must come from a shell outside the
    service (a terminal or a plain SSH login), never from a session the server handed out. The
    report prints the commands; a person runs them. Detail:
    30-Knowledge/2026-09-23-runbook-claude-code-update-on-a-linux-server.md

`plan()` is pure (facts in, report items out); `gather()` collects the facts. See
machine_update_test.py.
"""
from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
import time
import urllib.request

HOME = os.path.expanduser("~")
CLI = os.path.join(HOME, ".local", "bin", "claude")
# The native installer's public release channel files: each holds the current version string.
RELEASES = ("https://storage.googleapis.com/claude-code-dist-86c565f3-f756-42ad-8dfa-"
            "d59b1c096819/claude-code-releases/%s")
LAUNCHD_LABEL = "com.secondbrain.remote-control"
SYSTEMD_UNIT = "second-brain-remote-control"
APP_CC_DIR = os.path.join(HOME, "Library", "Application Support", "Claude", "claude-code")
VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")
# Model ids as the CLI binary carries them, claude-<family>-<major>[-<minor>]. Dated snapshot ids
# (claude-<family>-4-20250514) are cut at the family and version, so a stale dated alias never
# sorts after the real newest id. Any lowercase family name matches: no family is hard coded.
MODEL_RE = re.compile(rb"claude-[a-z]+-\d+(?:-\d{1,2})?(?!\d)")
WORK = ("outdated", "stale", "missing")


# ---------------------------------------------------------------- pure logic


def parse_version(text):
    m = VERSION_RE.search(text or "")
    return tuple(int(x) for x in m.groups()) if m else None


def fmt(v):
    return ".".join(map(str, v)) if v else "?"


def newest_models(ids):
    """Newest id per family, e.g. {'alpha': 'claude-alpha-5-5'}, from the ids found in a binary."""
    best = {}
    for mid in ids:
        parts = mid.split("-")
        try:
            family, nums = parts[1], tuple(int(p) for p in parts[2:])
        except (IndexError, ValueError):
            continue
        if family not in best or nums > best[family][0]:
            best[family] = (nums, mid)
    return {f: v[1] for f, v in sorted(best.items())}


def _item(component, state, detail, action=None, auto=False):
    return dict(component=component, state=state, detail=detail, action=action, auto=auto)


def _rc_item(f, cli):
    mgr, rc_v, sessions = f.get("rc_manager"), f.get("rc_version"), f.get("rc_sessions", 0)
    if not f.get("rc_pid"):
        return _item("rc", "warn" if mgr else "info",
                     "Remote Control server not running" + ("" if mgr else " (no service installed here)"))
    if not (rc_v and cli and rc_v != cli):
        return _item("rc", "ok", "server runs %s, %d session(s)" % (fmt(rc_v), sessions))
    base = "server runs %s, CLI is %s" % (fmt(rc_v), fmt(cli))
    if mgr == "launchd":
        cmd = "launchctl kickstart -k gui/%s/%s" % (f.get("uid", "$(id -u)"), LAUNCHD_LABEL)
        if f.get("rc_is_ancestor"):
            return _item("rc", "stale", base + "; this session runs under it, restart it from a terminal "
                         "or a session the server did not start", cmd)
        if sessions:
            return _item("rc", "stale", base + "; %d session(s) open, restarting ends them" % sessions, cmd)
        return _item("rc", "stale", base + "; idle, safe to restart", cmd, auto=True)
    if mgr == "systemd":
        cmd = ("from a shell outside the service (a terminal or a plain SSH login, not a session it "
               "serves): systemctl --user status %s --no-pager; then systemctl --user restart %s"
               % (SYSTEMD_UNIT, SYSTEMD_UNIT))
        return _item("rc", "stale", base + "; %d session(s) open; a restart stops the unit's whole cgroup, "
                     "a person does it" % sessions, cmd)
    return _item("rc", "stale", base + "; not started by a service this script knows: restart it by hand")


def plan(f):
    """Turn gathered facts into report items. Each item: component, state (ok|outdated|stale|warn|
    info|missing), detail, action (a command or None) and auto (whether `apply` runs it by itself)."""
    items = []
    cli, latest, channel = f.get("cli_version"), f.get("latest_version"), f.get("channel") or "latest"
    if not cli:
        items.append(_item("cli", "missing", "no native Claude Code at %s" % f.get("cli_path", CLI)))
    elif latest and cli < latest:
        items.append(_item("cli", "outdated", "%s installed, %s on channel %s" % (fmt(cli), fmt(latest), channel),
                           "%s update" % f.get("cli_path", CLI), auto=True))
    else:
        items.append(_item("cli", "ok", "%s (channel %s: %s)" % (fmt(cli), channel, fmt(latest))))

    items.append(_rc_item(f, cli))

    app = f.get("app_version")
    if app:
        items.append(_item("app", "info" if latest and app < latest else "ok",
                           "desktop app bundles %s; it updates itself, restart the app to pick up a newer one"
                           % fmt(app)))
    brew = f.get("brew_version")
    if brew:
        items.append(_item("brew", "info", "Homebrew cask claude-code %s is installed but unused "
                           "(the native install wins)" % fmt(brew), "brew uninstall --cask claude-code"))
    return items


def has_work(items):
    return any(i["state"] in WORK for i in items)


def render(facts, items, node=""):
    """The text report. Pure."""
    lines = ["machine: %s  (%s)" % (node or "?", facts.get("platform") or "?")]
    for i in items:
        lines.append("  %-5s %-9s %s" % (i["component"], i["state"], i["detail"]))
        if i["action"] and i["state"] != "ok":
            lines.append("        %s %s" % ("auto:" if i["auto"] else "run: ", i["action"]))
    if facts.get("cli_models"):
        lines.append("  models known to the CLI: %s" % ", ".join(facts["cli_models"].values()))
    lines.append("  => %s" % ("needs work" if has_work(items) else "up to date"))
    return "\n".join(lines)


def rc_pid(procs):
    """The pid of the Remote Control server in {pid: (ppid, command)}, or None."""
    for pid, (_, cmd) in sorted(procs.items()):
        if re.search(r"claude\S*\s+remote-control(\s|$)", cmd) and "--help" not in cmd:
            return pid
    return None


def is_ancestor(pid, procs, me):
    """Is `pid` among the ancestors of `me` (or `me` itself)?"""
    cur, seen = me, set()
    while cur and cur not in seen:
        if cur == pid:
            return True
        seen.add(cur)
        cur = procs.get(cur, (0, ""))[0]
    return False


# ---------------------------------------------------------------- adapters


def sh(args, timeout=20):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def cli_version():
    try:
        return parse_version(os.path.basename(os.path.realpath(CLI))) or parse_version(sh([CLI, "--version"]))
    except OSError:
        return None


def channel():
    for path in (os.path.join(HOME, ".claude", "settings.json"), os.path.join(HOME, ".claude.json")):
        try:
            with open(path, encoding="utf-8") as fh:
                ch = json.load(fh).get("autoUpdatesChannel")
            if ch:
                return ch
        except (OSError, ValueError, AttributeError):
            pass
    return "latest"


def latest_version(ch):
    try:
        with urllib.request.urlopen(RELEASES % ch, timeout=10) as r:
            return parse_version(r.read().decode())
    except Exception:
        return None


def processes():
    """{pid: (ppid, command)} for every process."""
    out = {}
    for line in sh(["ps", "-A", "-o", "pid=,ppid=,command="]).splitlines():
        parts = line.split(None, 2)
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            out[int(parts[0])] = (int(parts[1]), parts[2] if len(parts) > 2 else "")
    return out


def rc_binary_version(pid):
    """The version the running server was started from: its executable points into versions/<v>."""
    if sys.platform == "darwin":
        for line in sh(["lsof", "-a", "-p", str(pid), "-d", "txt", "-Fn"]).splitlines():
            if line.startswith("n") and "/versions/" in line:
                return parse_version(os.path.basename(line))
        return None
    try:
        return parse_version(os.path.basename(os.readlink("/proc/%d/exe" % pid)))
    except OSError:
        return None


def rc_manager():
    if sys.platform == "darwin":
        path = os.path.join(HOME, "Library", "LaunchAgents", LAUNCHD_LABEL + ".plist")
        return "launchd" if os.path.exists(path) else None
    config = os.environ.get("XDG_CONFIG_HOME") or os.path.join(HOME, ".config")
    path = os.path.join(config, "systemd", "user", SYSTEMD_UNIT + ".service")
    return "systemd" if os.path.exists(path) else None


def app_version():
    try:
        vs = [parse_version(d) for d in os.listdir(APP_CC_DIR)]
    except OSError:
        return None
    vs = [v for v in vs if v]
    return max(vs) if vs else None


def brew_version():
    if sys.platform != "darwin":
        return None
    for brew in ("/opt/homebrew/bin/brew", "/usr/local/bin/brew"):
        if os.path.exists(brew):
            return parse_version(sh([brew, "list", "--cask", "--versions", "claude-code"]))
    return None


def cli_models():
    try:
        with open(os.path.realpath(CLI), "rb") as fh:
            ids = {m.decode() for m in MODEL_RE.findall(fh.read())}
        return newest_models(ids)
    except OSError:
        return {}


def gather():
    ch = channel()
    procs = processes()
    pid = rc_pid(procs)
    f = dict(platform=sys.platform, channel=ch, cli_path=CLI, cli_version=cli_version(),
             latest_version=latest_version(ch), rc_manager=rc_manager(), rc_pid=pid, uid=os.getuid(),
             app_version=app_version(), brew_version=brew_version(), cli_models=cli_models())
    if pid:
        f["rc_version"] = rc_binary_version(pid)
        f["rc_sessions"] = sum(1 for _p, (pp, _c) in procs.items() if pp == pid)
        f["rc_is_ancestor"] = is_ancestor(pid, procs, os.getpid())
    return f


# ---------------------------------------------------------------- cli


def apply(items):
    for i in items:
        if not i["auto"]:
            continue
        print("applying %s: %s" % (i["component"], i["action"]))
        try:
            r = subprocess.run(i["action"].split(), capture_output=True, text=True, timeout=600)
            print(((r.stdout or "") + (r.stderr or "")).strip()[-600:])
        except (OSError, subprocess.SubprocessError) as exc:
            print("failed: %s: %s" % (type(exc).__name__, exc))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    unknown = [a for a in argv if a not in ("apply", "--json", "status")]
    if unknown:
        sys.stderr.write("usage: machine_update.py [status | apply] [--json]\n")
        return 2
    f = gather()
    items = plan(f)
    if "apply" in argv:
        apply([i for i in items if i["component"] == "cli"])
        # Re-read after the CLI moved: the server is only stale against the NEW version.
        f = gather()
        items = plan(f)
        restart = [i for i in items if i["component"] == "rc" and i["auto"]]
        apply(restart)
        if restart:
            time.sleep(8)
            f = gather()
            items = plan(f)
    if "--json" in argv:
        facts = {k: (fmt(v) if k.endswith("_version") else v) for k, v in f.items()}
        print(json.dumps(dict(facts=facts, items=items, needs_work=has_work(items)), indent=2, default=str))
    else:
        print(render(f, items, platform.node().split(".")[0]))
    return 1 if has_work(items) else 0


if __name__ == "__main__":
    sys.exit(main())
