#!/usr/bin/env python3
"""Tests for machine_update: what it calls stale, and above all what it refuses to restart by itself.

Only the pure parts run here (plan, render, the process-tree helpers, version and model parsing).
No network, no process list, no restart. Run standalone:

    python3 _bin/machine_update_test.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import machine_update as M

ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def facts(**kw):
    f = dict(platform="darwin", channel="latest", cli_path="/h/.local/bin/claude", cli_version=(2, 1, 281),
             latest_version=(2, 1, 281), rc_manager="launchd", rc_pid=123, uid=501,
             rc_version=(2, 1, 281), rc_sessions=0, rc_is_ancestor=False)
    f.update(kw)
    return f


def item(items, component):
    return next(i for i in items if i["component"] == component)


def test_cli():
    i = item(M.plan(facts(cli_version=(2, 1, 278))), "cli")
    check("behind the channel is outdated, and apply updates it by itself",
          (i["state"], i["auto"]) == ("outdated", True) and i["action"] == "/h/.local/bin/claude update", i)
    check("current is ok", item(M.plan(facts()), "cli")["state"] == "ok")
    check("an unknown latest version does not invent work",
          item(M.plan(facts(latest_version=None)), "cli")["state"] == "ok")
    i = item(M.plan(facts(cli_version=None)), "cli")
    check("no native install is missing, never auto", (i["state"], i["auto"]) == ("missing", False), i)


def test_remote_control():
    i = item(M.plan(facts(rc_version=(2, 1, 278))), "rc")
    check("macOS: an idle stale server restarts by itself",
          (i["state"], i["auto"]) == ("stale", True) and "kickstart -k gui/501/com.secondbrain.remote-control"
          in i["action"], i)
    i = item(M.plan(facts(rc_version=(2, 1, 278), rc_sessions=2)), "rc")
    check("macOS: with sessions open it is never auto", (i["state"], i["auto"]) == ("stale", False), i)
    i = item(M.plan(facts(rc_version=(2, 1, 278), rc_is_ancestor=True)), "rc")
    check("it never restarts the server this session runs under", i["auto"] is False, i)
    i = item(M.plan(facts(platform="linux", rc_manager="systemd", rc_version=(2, 1, 278))), "rc")
    check("Linux: never auto, even when idle", (i["state"], i["auto"]) == ("stale", False), i)
    check("Linux: the commands are the user unit's, from a shell outside the service",
          "systemctl --user restart second-brain-remote-control" in i["action"]
          and "outside the service" in i["action"] and "sudo" not in i["action"], i)
    i = item(M.plan(facts(rc_manager=None, rc_version=(2, 1, 278))), "rc")
    check("a server no known service started is stale, never auto", (i["state"], i["auto"]) == ("stale", False), i)
    check("not running with a service installed warns", item(M.plan(facts(rc_pid=None)), "rc")["state"] == "warn")
    check("not running with no service is only info",
          item(M.plan(facts(rc_pid=None, rc_manager=None)), "rc")["state"] == "info")
    check("the same version is ok, and nothing needs work",
          item(M.plan(facts()), "rc")["state"] == "ok" and not M.has_work(M.plan(facts())))


def test_app_and_brew():
    items = M.plan(facts(app_version=(2, 1, 280), brew_version=(2, 1, 267)))
    check("an older bundled app is info, not work", item(items, "app")["state"] == "info"
          and not M.has_work(items), items)
    check("a Homebrew cask is reported with how to remove it, never auto",
          item(items, "brew")["action"] == "brew uninstall --cask claude-code" and not item(items, "brew")["auto"])


def test_models_and_versions():
    blob = (b"x claude-alpha-4-20250514 claude-alpha-4-5-20251101-v1 claude-alpha-5-5 "
            b"claude-beta-5 claude-gamma-4-5-20251001 claude-code-releases y")
    best = M.newest_models({m.decode() for m in M.MODEL_RE.findall(blob)})
    check("dated snapshot ids do not beat the real newest id",
          best == {"alpha": "claude-alpha-5-5", "beta": "claude-beta-5", "gamma": "claude-gamma-4-5"}, best)
    check("a version comes out of a versions path",
          M.parse_version("/x/.local/share/claude/versions/2.1.281") == (2, 1, 281))
    check("no version is None", M.parse_version("nothing here") is None and M.fmt(None) == "?")


def test_processes():
    procs = {1: (0, "init"), 50: (1, "/h/.local/bin/claude remote-control --chrome --name box"),
             60: (50, "/h/.local/share/claude/versions/2.1.281 --print"), 70: (60, "bash"),
             80: (1, "claude remote-control --help")}
    check("the server is found by its command line", M.rc_pid(procs) == 50)
    check("a --help run is not a server", M.rc_pid({80: (1, "claude remote-control --help")}) is None)
    check("a shell inside a session is a descendant of the server", M.is_ancestor(50, procs, 70))
    check("a process outside is not", not M.is_ancestor(50, procs, 80))


def test_render():
    f = facts(rc_version=(2, 1, 278), cli_models={"alpha": "claude-alpha-5-5"})
    text = M.render(f, M.plan(f), "box")
    check("the report names the machine, each component and the command apply runs",
          text.startswith("machine: box  (darwin)") and "auto: launchctl kickstart" in text, text)
    check("and the models the CLI knows, and the verdict",
          "models known to the CLI: claude-alpha-5-5" in text and text.endswith("=> needs work"), text)
    check("an up to date machine says so", M.render(facts(), M.plan(facts()), "box").endswith("=> up to date"))
    check("an unknown argument is a usage error", M.main(["bogus"]) == 2)


def main():
    for t in (test_cli, test_remote_control, test_app_and_brew, test_models_and_versions, test_processes,
              test_render):
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
