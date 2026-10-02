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

The session-start hook does not probe: it reads the block from a cache in the Brain state
directory (`cached_section`). What the block describes does not change between two sessions
minutes apart, and the probe's forks cost far more on a busy machine than on an idle one; a
hook killed at its deadline leaves the session with no startup block at all. A fresh cache is
served as is, a stale one is served at once and re-probed in a detached process, and with no
cache (a new machine, or the guardian's hook probe in its scratch state) the probe runs for
`COLD_BUDGET` seconds at most. An answer that could not tell something (the process list was
unreadable, the probe was cut short) is shown but never cached: the machine was busy, not
changed.

The block must never go missing: a probe or a line that fails is reported in its own line, and
if everything fails the block still says which machine this is and that the probe failed. A
session that silently gets no block guesses the machine from the OS, which is what this exists
to prevent.

Several machines on one Claude account all show up in `list_connected_browsers`, and nothing in
that list says which Chrome is this machine's (the "Browser N" names are reassigned, `isLocal`
only means "same OS"). So a session that has confirmed its machine's Chrome records the
deviceId in <brain state>/chrome-devices.json with `learn-chrome`, and the block names it from
then on. The file is local to the machine and never enters the vault.

    machine_caps.py                                   print the block (from the cache when fresh)
    machine_caps.py --fresh                           probe now, ignoring the cache
    machine_caps.py learn-chrome <deviceId> '<what>'  record this machine's own Chrome
"""
import json
import os
import platform as _platform
import shutil
import subprocess
import sys
import threading
import time

if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TOOLS = ("git", "gh", "python3", "claude", "keepassxc-cli", "jq", "rg")
PRIORITY = 92
CACHE = "machine-caps.json"   # in the Brain state directory: {"text": ..., "at": epoch seconds}
CACHE_TTL = 900               # what the block describes does not change within a quarter hour
COLD_BUDGET = 1.0             # the most a hook spends probing when nothing is cached
PROBE_BUDGET = 3.0            # a refresh or `--fresh`, where nobody waits on a hook
REFRESH_EVERY = 60            # no second background refresh within this many seconds
UNSURE_RUNNING = "could not tell whether it is running (the process list could not be read)"
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
CHROME_DEVICES = "chrome-devices.json"
KEEPALIVE = os.path.join(".local", "bin", "chrome-keepalive.sh")
LOCAL_STATE = os.path.join(".config", "google-chrome", "Local State")
SCRIPT = "python3 ~/Brain/_bin/machine_caps.py"
SESSION_RULE = ("This line describes the MACHINE, not your session. Listed `mcp__claude-in-chrome__*` tools "
                "(deferred counts) mean you have the browser: use them, whatever this block, `claude mcp list` or "
                "`~/.claude.json` say. None listed: started without `--chrome`, offer "
                "`claude --chrome --continue`.")


def _browser_line(chrome, scheduler):
    """The Browser line for a probe's chrome dict. Pure."""
    if not chrome.get("installed"):
        return "- Browser: no local Chrome. Another machine's may still be listed by `list_connected_browsers`."
    running = chrome.get("running")
    parts = ["Chrome paired" if chrome.get("paired") else "Chrome NOT paired (`claude --chrome` once)"]
    # Unknown is not "no": a process list that could not be read leaves the answer open
    # instead of telling the session it has no browser when it may well have one.
    parts.append("running" if running else ("NOT running" if running is False else UNSURE_RUNNING))
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
    if not chrome.get("paired") or running is False:
        head = "**not usable now**"
    else:
        head = "**usable**" if running else "**cannot tell right now**"
    return "- Browser (the user's logged-in sessions): %s: %s. %s" % (head, ", ".join(parts), SESSION_RULE)


def _own_chrome_line(chrome, mac):
    """Which connected Chrome is this machine's, and how to bring it back. Pure; None without Chrome.

    Kept short: it is read at every session start. How to bring Chrome back is only added when
    the probe saw it not running."""
    if not chrome.get("installed"):
        return None
    own = chrome.get("own") or []
    if own:
        line = ("- Own Chrome: %s; `select_browser` it when several are listed, never another machine's "
                "without asking." % "; ".join("`%s` (%s)" % (d, what) if what else "`%s`" % d for d, what in own))
    else:
        line = ("- Own Chrome: not recorded. Confirm it on a page only this machine's profile is signed in to, "
                "then `machine_caps.py learn-chrome <deviceId> '<what>'`; until then ask before driving "
                "another machine's Chrome.")
    if chrome.get("running") is False:
        line += (" Start it: `open -a \"Google Chrome\"`." if mac else
                 " `pkill -x chrome` and the keepalive relaunches it; else check the desktop unit.")
    if chrome.get("picker_blocks"):
        line += (" **Chrome would stop at the profile picker** (several profiles, keepalive without "
                 "`--profile-directory=Default`): the extension cannot load.")
    return line


def _failed(label, exc):
    return "- %s: probe failed (%s: %s). Run `%s` to see it." % (
        label, type(exc).__name__, " ".join(str(exc).split())[:120], SCRIPT)


def _line(label, fn):
    """One line of the block; a line that raises becomes a line saying so, never a lost block."""
    try:
        return fn()
    except Exception as exc:
        return _failed(label, exc)


def _who(caps):
    who = "- **%s** (%s, user `%s`)" % (caps.get("key") or "?", caps.get("os") or "?", caps.get("user") or "?")
    if caps.get("registered"):
        account = caps.get("claude_account")
        who += ", Claude account `%s`" % account if account else ", registered"
    else:
        who += ", not registered (`python3 ~/Brain/_bin/machines.py register`)"
    return who


def _tools_line(tools):
    have = [n for n, present in tools if present]
    missing = [n for n, present in tools if not present]
    line = "- Tools: present " + (", ".join("`%s`" % n for n in have) or "none")
    if missing:
        line += "; absent " + ", ".join("`%s`" % n for n in missing)
    return line


def render(caps):
    """The startup block for a probe result. Pure: the same dict always gives the same text."""
    lines = ["", "## This machine", _line("Machine", lambda: _who(caps)),
             "- Scheduler: %s" % (caps.get("scheduler") or "none found"),
             _line("Tools", lambda: _tools_line(caps.get("tools") or []))]

    chrome = caps.get("chrome") or {}
    lines.append(_line("Browser", lambda: _browser_line(chrome, caps.get("scheduler"))))
    own = _line("Own Chrome", lambda: _own_chrome_line(chrome, caps.get("os") == "macOS"))
    if own:
        lines.append(own)

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


def parse_devices(text):
    """[(deviceId, what), ...] from chrome-devices.json text. Pure; anything unreadable is []."""
    try:
        rows = json.loads(text or "").get("devices") or []
    except (ValueError, AttributeError):
        return []
    out = []
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, (list, tuple)) and row and isinstance(row[0], str) and row[0].strip():
            out.append((row[0].strip(), str(row[1]) if len(row) > 1 and row[1] else ""))
    return out


def add_device(devices, device_id, what):
    """The list with `device_id` recorded once, its description replaced. Pure."""
    return [(d, w) for d, w in devices if d != device_id] + [(device_id, what)]


def render_devices(devices):
    return json.dumps({"devices": [[d, w] for d, w in devices]}, indent=2) + "\n"


def picker_blocks(local_state_text, keepalive_text):
    """True when Chrome on Linux would stop at "Who's using Chrome?" and never load the extension.

    That happens once a second profile exists, unless the keepalive pins one with
    `--profile-directory` or the picker was switched off. Pure: both file texts are passed in,
    None for a file that is not there."""
    try:
        prof = json.loads(local_state_text or "")["profile"]
    except (ValueError, KeyError, TypeError):
        return False
    if not isinstance(prof, dict) or len(prof.get("info_cache") or {}) < 2:
        return False
    if prof.get("show_picker_on_startup") is False:
        return False
    return "--profile-directory" not in (keepalive_text or "")


def _read(path):
    """A file's text, or None when it cannot be read."""
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError):
        return None


def devices_path(environ=None, home=None, platform=None):
    """<brain state>/chrome-devices.json."""
    import brain_paths
    return os.path.join(brain_paths.effective_state_dir(environ, home, platform), CHROME_DEVICES)


def learn_chrome(device_id, what, path=None, read=None):
    """Record `device_id` as this machine's own Chrome. Returns what was done, in one line."""
    device_id = (device_id or "").strip()
    if not device_id:
        return "no deviceId given; nothing recorded"
    path = path or devices_path()
    devices = add_device(parse_devices((read or _read)(path)), device_id, " ".join((what or "").split()))
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(render_devices(devices))
    os.replace(tmp, path)
    return "recorded %s as this machine's Chrome (%s) in %s" % (device_id, what or "no description", path)


def probe(which=None, exists=None, platform=None, home=None, environ=None, key=None, here=None, tasks_here=None,
          run=None, read=None):
    """What this machine has right now, as a plain dict for render(). Never raises.

    Every effect is a parameter: `which(name)` like shutil.which, `exists(path)`, `run(cmd)`
    returning (returncode, stdout), and three callables for the machine key, this machine's
    registry record and the ids of the enabled agent tasks pinned here; `read(path)` returns a
    file's text or None. A probe that fails degrades to "unknown", never to an exception.
    """
    which = which or shutil.which
    exists = exists or os.path.exists
    platform = sys.platform if platform is None else platform
    home = os.path.expanduser("~") if home is None else home
    environ = os.environ if environ is None else environ
    run = run or _run
    read = read or _read
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
        chrome["own"] = _safe(lambda: parse_devices(read(devices_path(environ, home, platform))), [])
        if not mac:
            chrome["picker_blocks"] = _safe(lambda: picker_blocks(read(os.path.join(home, LOCAL_STATE)),
                                                                  read(os.path.join(home, KEEPALIVE))), False)
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


def fallback(exc, node=None, system=None):
    """The block when the probe itself failed: still the machine's name, and that the probe failed."""
    node = node if node is not None else _platform.node().split(".")[0]
    system = system if system is not None else _platform.system()
    return "\n".join(["", "## This machine", "- **%s** (%s), identity from the hostname only" % (node or "?", system or "?"),
                      _failed("Probe", exc),
                      "- Tools, keys, MCP servers per machine: [[%s]]. Never decide from the OS alone." % CATALOGUE_NOTE])


def section(probe_fn=None):
    """("machine", text, PRIORITY) for compass.build_sections(). Never raises and never goes missing:
    a probe that fails still gives a block that says so."""
    try:
        return ("machine", render((probe_fn or probe)()), PRIORITY)
    except Exception as exc:
        try:
            return ("machine", fallback(exc), PRIORITY)
        except Exception:
            return ("machine", "\n## This machine\n- probe failed. Run `%s` to see it." % SCRIPT, PRIORITY)


def complete(caps):
    """True when a probe answered everything it was asked. Pure.

    A probe that did not finish, or whose process list could not be read, describes a busy
    moment rather than the machine, so its block is shown once and never cached."""
    if not isinstance(caps, dict):
        return False
    chrome = caps.get("chrome") or {}
    return not (chrome.get("installed") and chrome.get("running") is None)


def probe_within(budget, probe_fn=None):
    """probe_fn()'s answer, or None when it did not answer within `budget` seconds.

    A plain daemon thread and not a ThreadPoolExecutor: the executor's workers are joined at
    interpreter exit, so a slow probe would keep the hook process alive after it had already
    printed its answer, and the deadline would bound the output but not the run. A daemon
    thread cut off mid-probe loses nothing: every probe here only reads."""
    got = {}

    def work():
        try:
            got["caps"] = (probe_fn or probe)()
        except Exception as exc:
            got["error"] = exc

    t = threading.Thread(target=work, daemon=True, name="machine_caps:probe")
    t.start()
    t.join(budget)
    if "error" in got:
        raise got["error"]
    return got.get("caps")


def timed_out(budget, node=None, system=None):
    """The block when the probe did not answer in time: the machine's name and how to see the rest."""
    node = node if node is not None else _platform.node().split(".")[0]
    system = system if system is not None else _platform.system()
    return "\n".join(["", "## This machine", "- **%s** (%s), identity from the hostname only" % (node or "?", system or "?"),
                      "- Probe: did not answer within %.1f s. Run `%s --fresh` to see it." % (budget, SCRIPT),
                      "- Tools, keys, MCP servers per machine: [[%s]]. Never decide from the OS alone." % CATALOGUE_NOTE])


def cache_path(state_dir=None):
    """<brain state>/machine-caps.json."""
    if state_dir is None:
        import brain_paths
        state_dir = brain_paths.effective_state_dir()
    return os.path.join(state_dir, CACHE)


def _cache_read(state_dir=None, now=None):
    """(text, age in seconds) of the cached block, or ("", inf) when there is none."""
    try:
        with open(cache_path(state_dir), encoding="utf-8") as fh:
            data = json.load(fh)
        text, made = data["text"], float(data["at"])
    except (OSError, ValueError, KeyError, TypeError):
        return "", float("inf")
    if not isinstance(text, str) or not text:
        return "", float("inf")
    return text, max(0.0, (now or time.time)() - made)


def _cache_write(text, state_dir=None, now=None):
    """Writes the cache atomically. A block nobody can cache is still a block: errors pass."""
    path = cache_path(state_dir)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = "%s.tmp.%d" % (path, os.getpid())
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"text": text, "at": (now or time.time)()}, fh)
        os.replace(tmp, path)
    except OSError:
        pass


def _spawn_detached(argv):
    """Starts argv in its own session, so it neither dies with the hook nor holds it."""
    subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


def _refresh_async(state_dir=None, now=None, spawn=None, environ=None):
    """Re-probes behind the session. True when a refresh was started.

    Throttled by a stamp beside the cache, or a machine whose probe keeps failing would start
    one per session. Never under BRAIN_OFFLINE: that is the guardian's hook probe, whose
    contract is that a hook starts no process."""
    environ = os.environ if environ is None else environ
    if environ.get("BRAIN_OFFLINE") in ("1", "true", "yes"):
        return False
    now = now or time.time
    stamp = cache_path(state_dir) + ".refresh"
    try:
        with open(stamp, encoding="utf-8") as fh:
            if now() - float(fh.read().strip() or 0) < REFRESH_EVERY:
                return False
    except (OSError, ValueError):
        pass
    try:
        os.makedirs(os.path.dirname(stamp), exist_ok=True)
        with open(stamp, "w", encoding="utf-8") as fh:
            fh.write("%f\n" % now())
        argv = [sys.executable, os.path.abspath(__file__), "--refresh"]
        if state_dir is not None:
            argv[2:2] = ["--state-dir", state_dir]
        (spawn or _spawn_detached)(argv)
        return True
    except (OSError, ValueError):
        return False


def refresh(state_dir=None, probe_fn=None, now=None, budget=PROBE_BUDGET):
    """Probes and caches the block when the answer is complete. True when the cache was written.

    An incomplete answer leaves the cache as it was: an older complete block describes the
    same machine and is not missing a line."""
    caps = probe_within(budget, probe_fn)
    if not complete(caps):
        return False
    _cache_write(render(caps), state_dir, now)
    return True


def cached_section(max_age=CACHE_TTL, state_dir=None, budget=COLD_BUDGET, probe_fn=None, now=None, spawn=None,
                   environ=None):
    """("machine", text, PRIORITY) for compass, cheap on every path. Never raises.

    A fresh cache is returned untouched; a stale one is returned at once and re-probed behind
    the session; with nothing cached it probes for `budget` seconds and returns whatever came
    back, caching it only when complete."""
    try:
        text, age = _cache_read(state_dir, now)
        if text and age < max_age:
            return ("machine", text, PRIORITY)
        if text:
            _refresh_async(state_dir, now, spawn, environ)
            return ("machine", text, PRIORITY)
        caps = probe_within(budget, probe_fn)
        if caps is None:
            _refresh_async(state_dir, now, spawn, environ)
            return ("machine", timed_out(budget), PRIORITY)
        fresh = render(caps)
        if complete(caps):
            _cache_write(fresh, state_dir, now)
        else:
            _refresh_async(state_dir, now, spawn, environ)
        return ("machine", fresh, PRIORITY)
    except Exception as exc:
        try:
            return ("machine", fallback(exc), PRIORITY)
        except Exception:
            return ("machine", "\n## This machine\n- probe failed. Run `%s` to see it." % SCRIPT, PRIORITY)


USAGE = "usage: machine_caps.py [--fresh | learn-chrome <deviceId> '<what it is>']\n"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "learn-chrome":
        if len(argv) < 3:
            sys.stderr.write("usage: machine_caps.py learn-chrome <deviceId> '<what it is>'\n")
            return 2
        print(learn_chrome(argv[1], " ".join(argv[2:])))
        return 0
    state_dir = None
    if argv[:1] == ["--state-dir"] and len(argv) > 1:
        state_dir, argv = argv[1], argv[2:]
    if argv == ["--refresh"]:
        refresh(state_dir)                # the detached refresh `_refresh_async` starts
        return 0
    if argv == ["--fresh"]:
        print(render(probe()))            # a person at a terminal, not a hook
        return 0
    if argv:
        sys.stderr.write(USAGE)
        return 2
    print(cached_section()[1])
    return 0


if __name__ == "__main__":
    sys.exit(main())
