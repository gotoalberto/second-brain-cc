#!/usr/bin/env python3
"""Tests for first_run_core.domain: the pure rules of the first run. No IO.

Run standalone:

    python3 integrations/first-run/first_run_core/domain_test.py
"""
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[0] = os.path.dirname(HERE)

ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


NOW = dt.datetime(2026, 9, 15, 18, 0, tzinfo=dt.timezone.utc)


def test_steps(D):
    print("\n== steps and state ==")
    check("the steps are asked in this order",
          D.STEPS == ("kdbx", "google", "files", "alert_email", "mcp", "scheduler", "routines"), D.STEPS)
    state = D.new_state()
    check("a new state has no answers and is not complete",
          state["steps"] == {} and not D.is_complete(state) and D.next_step(state) == "kdbx", state)
    s1 = D.record(state, "kdbx", "done", {"db": "~/x.kdbx"}, NOW)
    check("record returns a new state and leaves the old one alone", state["steps"] == {} and "kdbx" in s1["steps"])
    check("a recorded step carries its status, details and time",
          s1["steps"]["kdbx"] == {"status": "done", "at": "2026-09-15T18:00:00+00:00", "db": "~/x.kdbx"}, s1)
    check("the next step is the first one with no answer", D.next_step(s1) == "google")
    s2 = D.record(s1, "google", "declined", {}, NOW)
    check("declined counts as answered", D.next_step(s2) == "files")
    bad = None
    try:
        D.record(s2, "files", "maybe", {}, NOW)
    except ValueError as exc:
        bad = exc
    check("only done and declined are answers", bad is not None)
    check("the files step is the one that cannot be declined", D.REQUIRED == ("files",), D.REQUIRED)
    refused = None
    try:
        D.record(s2, "files", "declined", {}, NOW)
    except ValueError as exc:
        refused = exc
    check("recording files as declined is refused", refused is not None)
    check("a state file that says files was declined asks it again",
          "files" not in D.parse_state(json.dumps({"steps": {"files": {"status": "declined", "at": "x"}}}))["steps"])
    full = s2
    for step in D.STEPS[2:]:
        full = D.record(full, step, "done" if step in D.REQUIRED else "declined", {}, NOW)
    check("with every step answered the first run is complete",
          D.is_complete(full) and D.next_step(full) is None and D.status_exit(full) == 0)
    check("an incomplete one exits 3 on status", D.status_exit(s2) == 3)
    again = D.forget(full, "scheduler")
    check("forget makes one step ask again", D.next_step(again) == "scheduler" and not D.is_complete(again))
    check("a state round-trips through JSON", D.parse_state(json.dumps(full)) == full)
    check("a missing or corrupt state file is a new state",
          D.parse_state("") == D.new_state() and D.parse_state("{nope") == D.new_state())


def test_scheduler_rules(D):
    print("\n== scheduler ==")
    which_all = lambda n: "/usr/bin/" + n
    which_none = lambda n: None
    which_cron = lambda n: "/usr/bin/crontab" if n == "crontab" else None
    check("macOS uses launchd", D.detect_scheduler("darwin", which_none, {}) == "launchd")
    check("Linux with systemctl and a user session uses systemd user units",
          D.detect_scheduler("linux", which_all, {"XDG_RUNTIME_DIR": "/run/user/1000"}) == "systemd")
    check("Linux with systemctl but no user session falls back to cron",
          D.detect_scheduler("linux", which_all, {}) == "cron")
    check("Linux with only crontab uses cron", D.detect_scheduler("linux", which_cron, {}) == "cron")
    check("nothing at all is none", D.detect_scheduler("linux", which_none, {}) == "none")
    check("the jobs are the guardian, sync, tasks and the file watch, each described",
          [j for j, _ in D.JOBS] == ["guardian", "sync", "tasks", "watch"] and all(desc for _, desc in D.JOBS))
    check("labels match the job templates",
          D.job_label("launchd", "guardian") == "com.secondbrain.guardian"
          and D.job_label("systemd", "sync") == "second-brain-sync" and D.job_label("cron", "watch") == "second-brain-watch")
    check("the scheduler answer is the shape the guardian reads",
          D.scheduler_state("systemd", ["guardian", "sync"]) == {"kind": "systemd", "jobs": ["guardian", "sync"]})


def test_answers_and_text(D):
    print("\n== answers and generated text ==")
    for text, default, want in (("y", False, True), ("YES", False, True), ("n", True, False), ("", True, True),
                                ("", False, False), ("no", True, False)):
        check("%r with default %s is %s" % (text, default, want), D.parse_yes_no(text, default) is want)
    check("an unclear answer is None, so the question is asked again", D.parse_yes_no("perhaps", False) is None)
    check("one plain address is a valid email", D.valid_email("me@example.com") and not D.valid_email("me at example"))
    check("macOS keeps the default database in Documents",
          D.default_kdbx_path("darwin", "/home/u") == "/home/u/Documents/brain.kdbx")
    check("Linux keeps it under ~/.local/share/brain",
          D.default_kdbx_path("linux", "/home/u") == "/home/u/.local/share/brain/brain.kdbx")
    snippets = D.mcp_snippets("/srv/vault", "python3")
    check("MCP registration snippets exist for Claude Code, Claude Desktop, Cursor-style clients and OpenCode",
          set(snippets) == {"claude-code", "claude-desktop", "json-clients", "opencode"}, sorted(snippets))
    check("each names this vault's server.py",
          all("/srv/vault/integrations/mcp/server.py" in t for t in snippets.values()), snippets)
    check("the JSON ones parse", all(json.loads(snippets[k]) for k in ("claude-desktop", "json-clients", "opencode")))
    check("the shell profile line exports BRAIN_VAULT, quoted",
          D.profile_line("/srv/my vault") == 'export BRAIN_VAULT="/srv/my vault"')
    check("routine tokens are numbered KeePass references, never values",
          D.token_ref(2) == "kp://apis/agent-routines-token-2" and D.token_label(2) == "routines-2")


def main():
    try:
        from first_run_core import domain as D
    except Exception as exc:
        check("first_run_core.domain imports", False, "%s: %s" % (type(exc).__name__, exc))
    else:
        for t in (test_steps, test_scheduler_rules, test_answers_and_text):
            try:
                t(D)
            except Exception as exc:
                import traceback
                traceback.print_exc()
                check("%s ran to the end" % t.__name__, False, "%s: %s" % (type(exc).__name__, exc))
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
