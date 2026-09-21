#!/usr/bin/env python3
"""Tests for machine_caps — the `## This machine` block every session starts with.

`render()` is pure: a fixed dict in, exact text out. `probe()` gets every effect injected (which,
exists, the identity, the registry, the tasks pinned here), so no real PATH, Chrome, hostname or
registry is consulted. Every name below is invented for this test. Run standalone:

    python3 _bin/machine_caps_test.py
"""
import os
import sys
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
    "chrome": {"installed": True, "paired": True},
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
    check("a paired local Chrome is said to be usable",
          "- Browser: local Chrome installed, paired with Claude Code" in text, text)
    check("the tasks pinned here are counted, named and pointed at their preflight",
          "2 enabled agent task(s) run here (daily-digest, weekly-review)" in text
          and "routine_requires.py here" in text, text)
    check("it says never to infer a capability from the OS", "never from the OS alone" in text, text)

    text = M.render(dict(CAPS, registered=False, claude_account=""))
    check("an unregistered machine says how to register", "not registered (`python3 ~/Brain/_bin/machines.py register`)"
          in text, text)
    text = M.render(dict(CAPS, chrome={"installed": True, "paired": False}))
    check("an unpaired Chrome says how to pair it", "NOT paired with Claude Code" in text and "claude --chrome" in text,
          text)
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
    check("the block stays short", len(M.render(CAPS)) < 900, len(M.render(CAPS)))


def fs(paths):
    return lambda p: p in paths


def test_probe_linux():
    home = "/home/someone"
    paired = home + "/.config/google-chrome/NativeMessagingHosts/com.anthropic.claude_code_browser_extension.json"
    which = {"git": "/usr/bin/git", "python3": "/usr/bin/python3", "systemctl": "/usr/bin/systemctl",
             "google-chrome-stable": "/usr/bin/google-chrome-stable"}
    caps = M.probe(which=which.get, exists=fs({paired}), platform="linux", home=home,
                   environ={"USER": "someone"}, key=lambda: "box-aaaaaaaa",
                   here=lambda: {"claude_account": "someone@example.com"}, tasks_here=lambda: ["t1"])
    check("Linux: the key, OS and user come from the injected probes",
          caps["key"] == "box-aaaaaaaa" and caps["os"] == "Linux" and caps["user"] == "someone", caps)
    check("Linux: a registry record means registered, with its account",
          caps["registered"] and caps["claude_account"] == "someone@example.com", caps)
    check("Linux: systemctl on PATH is a systemd scheduler", caps["scheduler"] == "systemd", caps)
    check("Linux: google-chrome-stable on PATH plus the native host file is a paired Chrome",
          caps["chrome"] == {"installed": True, "paired": True}, caps["chrome"])
    tools = dict(caps["tools"])
    check("Linux: tools on PATH are present, others absent",
          tools.get("git") and tools.get("python3") and tools.get("gh") is False, caps["tools"])
    check("Linux: the tasks pinned here are passed through", caps["tasks_here"] == ["t1"], caps)


def test_probe_macos():
    home = "/Users/someone"
    caps = M.probe(which={"launchctl": "/bin/launchctl"}.get,
                   exists=fs({"/Applications/Google Chrome.app"}), platform="darwin", home=home,
                   environ={"USER": "someone"}, key=lambda: "mac-bbbbbbbb", here=lambda: None,
                   tasks_here=lambda: [])
    check("macOS: named as such, launchd is the scheduler", caps["os"] == "macOS" and caps["scheduler"] == "launchd",
          caps)
    check("macOS: the app bundle is an installed Chrome, not paired without the host file",
          caps["chrome"] == {"installed": True, "paired": False}, caps["chrome"])
    check("macOS: no registry record is not registered", caps["registered"] is False and caps["claude_account"] == "",
          caps)


def test_probe_never_raises():
    def boom(*a, **k):
        raise RuntimeError("probe failed")
    caps = M.probe(which=lambda n: None, exists=lambda p: False, platform="linux", home="/h", environ={},
                   key=boom, here=boom, tasks_here=boom)
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
    check("a probe that raises gives no section, never an exception", M.section(probe_fn=boom) is None)


def test_real_probe_is_fast():
    env = dict(os.environ, BRAIN_MACHINE_KEY="test-box-12345678")
    t0 = time.time()
    caps = M.probe(environ=env, key=lambda: "test-box-12345678", here=lambda: None, tasks_here=lambda: [])
    took = time.time() - t0
    check("the real PATH and file probes finish well inside the startup budget", took < 0.5, took)
    check("and produce a renderable dict", "## This machine" in M.render(caps))


def main():
    for t in (test_render, test_probe_linux, test_probe_macos, test_probe_never_raises, test_section,
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
