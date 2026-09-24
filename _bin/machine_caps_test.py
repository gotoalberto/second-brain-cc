#!/usr/bin/env python3
"""Tests for machine_caps: the `## This machine` block every session starts with.

`render()` is pure: a fixed dict in, exact text out. `probe()` gets every effect injected (which,
exists, the command runner, the identity, the registry, the tasks pinned here), so no real PATH,
process list, Chrome, hostname or registry is consulted. Every name below is invented for this test. Run standalone:

    python3 _bin/machine_caps_test.py
"""
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import machine_caps as M

ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


CAPS = {
    "key": "laptop-a-aaaaaaaa", "os": "Linux", "user": "someone",
    "registered": True, "claude_account": "someone@example.com",
    "scheduler": "systemd",
    "tools": [("git", True), ("gh", False), ("python3", True)],
    "chrome": {"installed": True, "paired": True, "running": True, "remote_control": "with",
               "desktop": ("vnc-desktop", "active"), "login": "present",
               "own": [("dev-1111", "the work profile")], "picker_blocks": False},
    "tasks_here": ["daily-digest", "weekly-review"],
}


def test_render():
    text = M.render(CAPS)
    check("the block opens with its heading", text.startswith("\n## This machine\n"), text)
    check("it names the machine key, the OS and the user",
          "- **laptop-a-aaaaaaaa** (Linux, user `someone`)" in text, text)
    check("and the Claude account the registry recorded", "Claude account `someone@example.com`" in text, text)
    check("the scheduler is named", "- Scheduler: systemd" in text, text)
    check("tools present and absent are listed apart",
          "- Tools: present `git`, `python3`; absent `gh`" in text, text)
    check("a paired, running Chrome is said to be usable, with what backs it",
          "**usable**: Chrome paired, running, Remote Control has `--chrome`, X `vnc-desktop` active, "
          "CLI logged in." in text, text)
    check("the browser line says it describes the machine, not the session",
          "This line describes the MACHINE, not your session." in text
          and "`mcp__claude-in-chrome__*` tools" in text and "claude --chrome --continue" in text, text)
    check("and points at the tool and service catalogue",
          "[[2026-09-12-reference-tool-and-service-catalogue]]" in text, text)
    check("the tasks pinned here are counted, named and pointed at their preflight",
          "2 enabled agent task(s) run here (daily-digest, weekly-review)" in text
          and "routine_requires.py here" in text, text)
    check("it says never to infer a capability from the OS", "Never decide from the OS alone" in text, text)

    text = M.render(dict(CAPS, registered=False, claude_account=""))
    check("an unregistered machine says how to register", "not registered (`python3 ~/Brain/_bin/machines.py register`)"
          in text, text)
    text = M.render(dict(CAPS, chrome={"installed": True, "paired": False}))
    check("an unpaired Chrome says how to pair it, and that it is not usable",
          "Chrome NOT paired (`claude --chrome` once)" in text and "**not usable now**" in text, text)
    text = M.render(dict(CAPS, chrome=dict(CAPS["chrome"], running=False)))
    check("a Chrome that is not running is not usable", "NOT running" in text and "**not usable now**" in text, text)
    text = M.render(dict(CAPS, chrome=dict(CAPS["chrome"], remote_control="without")))
    check("a Remote Control server without --chrome says so, with the systemd restart",
          "Remote Control WITHOUT `--chrome` (restart: `systemctl --user restart second-brain-remote-control`)"
          in text, text)
    text = M.render(dict(CAPS, scheduler="launchd", chrome=dict(CAPS["chrome"], remote_control="without")))
    check("and with the launchd restart on macOS",
          "launchctl kickstart -k gui/$(id -u)/com.secondbrain.remote-control" in text, text)
    text = M.render(dict(CAPS, chrome=dict(CAPS["chrome"], remote_control=None, desktop=None)))
    check("no Remote Control server and no desktop unit add nothing",
          "Remote Control" not in text and "X `" not in text, text)
    text = M.render(dict(CAPS, chrome=dict(CAPS["chrome"], login="absent")))
    check("a missing CLI login says browser routines need it",
          "no CLI login for browser routines (`claude auth login`)" in text, text)
    text = M.render(dict(CAPS, chrome=dict(CAPS["chrome"], login="check")))
    check("on macOS the login is pointed at `claude auth status`", "`claude auth status`" in text, text)
    text = M.render(dict(CAPS, chrome={"installed": False, "paired": False}))
    check("no local Chrome says so, and that another machine's may still be listed",
          "no local Chrome" in text and "list_connected_browsers" in text, text)
    text = M.render(dict(CAPS, tasks_here=[]))
    check("no tasks pinned here adds no task line", "task(s) run here" not in text, text)
    text = M.render(dict(CAPS, tasks_here=None))
    check("an unreadable task list adds no task line either", "task(s) run here" not in text, text)
    text = M.render(dict(CAPS, scheduler=""))
    check("no scheduler found says so", "- Scheduler: none found" in text, text)
    text = M.render(dict(CAPS, tools=[("git", True)]))
    check("nothing absent adds no absent list", "- Tools: present `git`\n" in text + "\n", text)
    check("the block stays short", len(M.render(CAPS)) < 1200, len(M.render(CAPS)))
    worst = dict(CAPS, key="x" * 24, chrome=dict(CAPS["chrome"], paired=False, login="absent", remote_control="without",
                                                 own=[], picker_blocks=True))
    check("even with every browser problem at once", len(M.render(worst)) < 1700, len(M.render(worst)))


def test_own_chrome():
    text = M.render(CAPS)
    check("a recorded deviceId is named as this machine's own Chrome, with what it is",
          "- Own Chrome: `dev-1111` (the work profile);" in text, text)
    check("and sessions are told to select it, never another machine's",
          "`select_browser` it when several are listed, never another machine's" in text, text)
    check("a running Chrome gets no restart advice", "pkill" not in text and "open -a" not in text, text)
    stopped = dict(CAPS["chrome"], running=False)
    text = M.render(dict(CAPS, chrome=stopped))
    check("on Linux a stopped Chrome is brought back through the keepalive", "`pkill -x chrome`" in text, text)
    text = M.render(dict(CAPS, os="macOS", scheduler="launchd", chrome=stopped))
    check("on macOS by opening it", 'open -a "Google Chrome"' in text and "pkill" not in text, text)
    text = M.render(dict(CAPS, chrome=dict(CAPS["chrome"], own=[("a", "first"), ("b", "")])))
    check("two recorded ids are both named", "`a` (first); `b`;" in text, text)
    text = M.render(dict(CAPS, chrome=dict(CAPS["chrome"], own=[])))
    check("with nothing recorded it says how to confirm and record the id",
          "not recorded" in text and "machine_caps.py learn-chrome <deviceId>" in text
          and "ask before driving" in text, text)
    text = M.render(dict(CAPS, chrome=dict(CAPS["chrome"], picker_blocks=True)))
    check("a profile picker that would block the extension is flagged",
          "Chrome would stop at the profile picker" in text and "--profile-directory=Default" in text, text)
    text = M.render(dict(CAPS, chrome={"installed": False, "paired": False}))
    check("no local Chrome adds no Own Chrome line", "Own Chrome" not in text, text)


def test_devices_file():
    check("parse: a well formed file", M.parse_devices('{"devices": [["d1", "one"], ["d2", ""]]}')
          == [("d1", "one"), ("d2", "")])
    check("parse: missing, empty, corrupt or wrongly shaped files are empty lists",
          M.parse_devices(None) == [] and M.parse_devices("") == [] and M.parse_devices("{ nope") == []
          and M.parse_devices('{"devices": {"x": 1}}') == [] and M.parse_devices('[1]') == []
          and M.parse_devices('{"devices": [[""], [3], "x"]}') == [])
    check("add: the same id is replaced in place of duplicated",
          M.add_device([("d1", "old"), ("d2", "two")], "d1", "new") == [("d2", "two"), ("d1", "new")])
    root = tempfile.mkdtemp(prefix="caps-")
    try:
        path = os.path.join(root, "state", M.CHROME_DEVICES)
        M.learn_chrome("d1", "first", path=path)
        M.learn_chrome("d1", "corrected", path=path)
        out = M.learn_chrome("d2", "second", path=path)
        with open(path) as fh:
            data = json.load(fh)
        check("learn_chrome writes, then replaces the same id", data == {"devices": [["d1", "corrected"],
                                                                                     ["d2", "second"]]}, data)
        check("and says what it recorded", "recorded d2" in out, out)
        with open(path, "w") as fh:
            fh.write("{ not json")
        M.learn_chrome("d3", "after corruption", path=path)
        with open(path) as fh:
            check("a corrupt file is overwritten, not fatal", json.load(fh) == {"devices": [["d3", "after corruption"]]})
        check("an empty id records nothing", "nothing recorded" in M.learn_chrome("  ", "x", path=path))
        check("main: learn-chrome without a description is a usage error", M.main(["learn-chrome", "d9"]) == 2)
        check("main: an unknown argument is a usage error", M.main(["nope"]) == 2)
        env = {"BRAIN_STATE": os.path.join(root, "bs")}
        check("the file lives in the brain state directory",
              M.devices_path(env, "/h", "linux") == os.path.join(root, "bs", M.CHROME_DEVICES))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_picker():
    two = json.dumps({"profile": {"info_cache": {"Default": {}, "Profile 1": {}}}})
    one = json.dumps({"profile": {"info_cache": {"Default": {}}}})
    off = json.dumps({"profile": {"info_cache": {"Default": {}, "Profile 1": {}}, "show_picker_on_startup": False}})
    check("two profiles and an unpinned keepalive stop at the picker",
          M.picker_blocks(two, "google-chrome --no-first-run\n") is True)
    check("a keepalive pinned with --profile-directory is fine",
          M.picker_blocks(two, "google-chrome --profile-directory=Default\n") is False)
    check("one profile is fine", M.picker_blocks(one, "google-chrome\n") is False)
    check("a picker switched off is fine", M.picker_blocks(off, None) is False)
    check("no Local State, or one that does not parse, is not flagged",
          M.picker_blocks(None, None) is False and M.picker_blocks("{", "") is False)


def fs(paths):
    return lambda p: p in paths


def runner(ps="", ps_code=0, units=None):
    """A fake `run`: `ps -eo command` prints `ps`, `systemctl is-active U` prints units[U]."""
    calls = []

    def run(cmd):
        calls.append(list(cmd))
        if cmd[:2] == ["ps", "-eo"]:
            return ps_code, ps
        if cmd[:2] == ["systemctl", "is-active"]:
            state = (units or {}).get(cmd[2])
            return (0, state) if state == "active" else (3, state or "inactive")
        return 127, ""
    run.calls = calls
    return run


LINUX_PS = "\n".join(["COMMAND", "/opt/google/chrome/chrome --type=renderer",
                      "/home/someone/.local/bin/claude remote-control --name box --chrome",
                      "grep remote-control"])
MAC_PS = "\n".join(["COMMAND", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                    "/usr/local/bin/claude remote-control --name mac"])


def test_probe_linux():
    home = "/home/someone"
    paired = home + "/.config/google-chrome/NativeMessagingHosts/com.anthropic.claude_code_browser_extension.json"
    which = {"git": "/usr/bin/git", "python3": "/usr/bin/python3", "systemctl": "/usr/bin/systemctl",
             "google-chrome-stable": "/usr/bin/google-chrome-stable"}
    creds = home + "/.claude/.credentials.json"
    run = runner(LINUX_PS, units={"vnc-desktop": "active"})
    files = {"/state/" + M.CHROME_DEVICES: '{"devices": [["dev-9", "its profile"]]}',
             home + "/.config/google-chrome/Local State": json.dumps({"profile": {"info_cache": {"a": {}, "b": {}}}}),
             home + "/.local/bin/chrome-keepalive.sh": "google-chrome\n"}
    caps = M.probe(which=which.get, exists=fs({paired, creds}), platform="linux", home=home,
                   environ={"USER": "someone", "BRAIN_STATE": "/state"}, key=lambda: "box-aaaaaaaa",
                   here=lambda: {"claude_account": "someone@example.com"}, tasks_here=lambda: ["t1"], run=run,
                   read=files.get)
    check("Linux: the key, OS and user come from the injected probes",
          caps["key"] == "box-aaaaaaaa" and caps["os"] == "Linux" and caps["user"] == "someone", caps)
    check("Linux: a registry record means registered, with its account",
          caps["registered"] and caps["claude_account"] == "someone@example.com", caps)
    check("Linux: systemctl on PATH is a systemd scheduler", caps["scheduler"] == "systemd", caps)
    chrome = caps["chrome"]
    check("Linux: google-chrome-stable on PATH plus the native host file is a paired Chrome",
          chrome["installed"] and chrome["paired"], chrome)
    check("Linux: the chrome process in ps means running", chrome["running"] is True, chrome)
    check("Linux: the Remote Control server's --chrome is read from its command line, grep ignored",
          chrome["remote_control"] == "with", chrome)
    check("Linux: the X desktop unit defaults to vnc-desktop and reports its state",
          chrome["desktop"] == ("vnc-desktop", "active"), chrome)
    check("Linux: the CLI login is the credentials file", chrome["login"] == "present", chrome)
    check("Linux: the recorded deviceIds come from the state file", chrome["own"] == [("dev-9", "its profile")], chrome)
    check("Linux: two profiles and an unpinned keepalive are flagged", chrome["picker_blocks"] is True, chrome)
    other = M.probe(which=which.get, exists=fs({paired}), platform="linux", home=home,
                   environ={"USER": "someone", "BRAIN_DESKTOP_UNIT": "my-desktop"}, key=lambda: "k",
                   here=lambda: None, tasks_here=lambda: [], run=runner("COMMAND\n/usr/bin/sleep 5"))
    chrome = other["chrome"]
    check("Linux: BRAIN_DESKTOP_UNIT names another desktop unit",
          chrome["desktop"] == ("my-desktop", "inactive"), chrome)
    check("Linux: no chrome and no server in ps, no credentials file",
          chrome["running"] is False and chrome["remote_control"] is None and chrome["login"] == "absent", chrome)
    blind = M.probe(which=which.get, exists=fs({paired}), platform="linux", home=home, environ={},
                   key=lambda: "k", here=lambda: None, tasks_here=lambda: [], run=runner("", ps_code=1))
    check("Linux: an unreadable process list is unknown, not NOT running",
          blind["chrome"]["running"] is None and blind["chrome"]["remote_control"] is None, blind["chrome"])
    tools = dict(caps["tools"])
    check("Linux: tools on PATH are present, others absent",
          tools.get("git") and tools.get("python3") and tools.get("gh") is False, caps["tools"])
    check("Linux: the tasks pinned here are passed through", caps["tasks_here"] == ["t1"], caps)


def test_probe_macos():
    home = "/Users/someone"
    run = runner(MAC_PS)
    caps = M.probe(which={"launchctl": "/bin/launchctl"}.get,
                   exists=fs({"/Applications/Google Chrome.app"}), platform="darwin", home=home,
                   environ={"USER": "someone"}, key=lambda: "mac-bbbbbbbb", here=lambda: None,
                   tasks_here=lambda: [], run=run)
    check("macOS: named as such, launchd is the scheduler", caps["os"] == "macOS" and caps["scheduler"] == "launchd",
          caps)
    chrome = caps["chrome"]
    check("macOS: the app bundle is an installed Chrome, not paired without the host file",
          chrome["installed"] is True and chrome["paired"] is False, chrome)
    check("macOS: the main Chrome binary in ps means running", chrome["running"] is True, chrome)
    check("macOS: a Remote Control server without --chrome is reported as such",
          chrome["remote_control"] == "without", chrome)
    check("macOS: no desktop unit is asked for, and the login points at `claude auth status`",
          "desktop" not in chrome and chrome["login"] == "check"
          and not any(c[0] == "systemctl" for c in run.calls), (chrome, run.calls))
    check("macOS: no registry record is not registered", caps["registered"] is False and caps["claude_account"] == "",
          caps)


def test_probe_never_raises():
    def boom(*a, **k):
        raise RuntimeError("probe failed")
    caps = M.probe(which=lambda n: None, exists=lambda p: False, platform="linux", home="/h", environ={},
                   key=boom, here=boom, tasks_here=boom, run=boom)
    check("a failing identity, registry or task probe degrades, never raises",
          caps["key"] == "?" and caps["registered"] is False and caps["tasks_here"] is None, caps)
    check("no scheduler and no Chrome are reported as such",
          caps["scheduler"] == "" and caps["chrome"] == {"installed": False, "paired": False}, caps)


def test_section():
    sec = M.section(probe_fn=lambda: CAPS)
    check("section() is a compass section: (name, text, priority)",
          sec and sec[0] == "machine" and sec[1] == M.render(CAPS) and isinstance(sec[2], int), sec)

    def boom():
        raise RuntimeError("x")
    sec = M.section(probe_fn=boom)
    check("a probe that raises still gives the block, saying the probe failed",
          sec and sec[0] == "machine" and "## This machine" in sec[1] and "probe failed (RuntimeError: x)" in sec[1],
          sec)
    text = M.fallback(ValueError("bad"), node="box", system="Linux")
    check("the fallback names the machine from the hostname and says never to decide from the OS",
          "- **box** (Linux)" in text and "Never decide from the OS alone" in text, text)
    bad = dict(CAPS, tools=[("git",)])
    text = M.render(bad)
    check("one line that raises costs that line only, not the block",
          "- Tools: probe failed" in text and "- Browser (the user's" in text and "Own Chrome" in text, text)


def test_real_probe_is_fast():
    env = dict(os.environ, BRAIN_MACHINE_KEY="test-box-12345678")
    t0 = time.time()
    caps = M.probe(environ=env, key=lambda: "test-box-12345678", here=lambda: None, tasks_here=lambda: [])
    took = time.time() - t0
    check("the real PATH and file probes finish well inside the startup budget", took < 0.5, took)
    check("and produce a renderable dict", "## This machine" in M.render(caps))


def main():
    for t in (test_render, test_own_chrome, test_devices_file, test_picker, test_probe_linux, test_probe_macos, test_probe_never_raises, test_section,
              test_real_probe_is_fast):
        print("\n== %s ==" % t.__name__)
        try:
            t()
        except Exception as exc:
            import traceback
            traceback.print_exc()
            check("%s ran without raising" % t.__name__, False, repr(exc))
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
