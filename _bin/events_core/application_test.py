#!/usr/bin/env python3
"""Tests for events_core.application — the watch tick and the generators.

Every port is an in-memory fake: a dict-backed snapshot and state, a process runner that
records argv instead of running anything, a fixed session id, an alert sink that records,
a git probe with a settable answer and a dict-backed file store. Run standalone:

    python3 _bin/events_core/application_test.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[0] = os.path.dirname(HERE)

ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


REGISTRY = {
    "version": 1,
    "watch": {"paths": ["30-Knowledge", "_bin"], "debounce_s": 120, "unsynced_alert_s": 3600,
              "unsaved_alert_s": 7200, "save_prefixes": ["30-Knowledge"], "unsaved_ignore": []},
    "events": [
        {"id": "post-write-ledger", "description": "credit written notes", "handler": "vault_ledger",
         "triggers": [{"kind": "file-watch", "action": "ledger-update", "command": "vault_ledger.py"}]},
        {"id": "reindex", "description": "index", "handler": "index_vault",
         "triggers": [{"kind": "file-watch", "action": "index-trigger", "command": "index_vault.py"}]},
        {"id": "sync", "description": "sync", "handler": "vault_sync",
         "triggers": [
             {"kind": "claude-hook", "event": "Stop", "command": "vault_sync.py --hook", "async": True},
             {"kind": "file-watch", "action": "sync-debounce", "command": "vault_sync.py --hook"}]},
        {"id": "pre-write-gate", "description": "gate", "handler": "gate_write",
         "triggers": [{"kind": "git-hook", "hook": "pre-commit", "command": "events_core/git_pre_commit.py"}]},
        {"id": "post-commit-dirty", "description": "dirty", "handler": "git_post_commit",
         "triggers": [{"kind": "git-hook", "hook": "post-commit", "command": "events_core/git_post_commit.py"}]},
    ],
}


class FakeSnapshot:
    def __init__(self, mtimes):
        self.mtimes = dict(mtimes)
        self.asked = []

    def read(self, paths):
        self.asked.append(list(paths))
        return {p: m for p, m in self.mtimes.items() if p.split("/")[0] in paths}


class FakeState:
    def __init__(self):
        self.data = {}
        self.saves = 0

    def load(self):
        return json.loads(json.dumps(self.data))

    def save(self, data):
        self.saves += 1
        self.data = json.loads(json.dumps(data))


class FakeRunner:
    def __init__(self, explode_on=None):
        self.calls = []
        self.explode_on = explode_on

    def run(self, argv, timeout):
        self.calls.append(list(argv))
        if self.explode_on and any(self.explode_on in a for a in argv):
            raise OSError("cannot run %s" % self.explode_on)
        return 0, "", ""


class FakeSession:
    def __init__(self, sid="system"):
        self.sid = sid

    def resolve(self):
        return self.sid


class FakeAlerts:
    def __init__(self):
        self.raised, self.cleared, self.severity = [], [], {}

    def raise_alert(self, key, summary, severity="warn"):
        self.raised.append((key, summary))
        self.severity[key] = severity

    def clear_alert(self, key):
        self.cleared.append(key)


class FakeGit:
    def __init__(self, oldest=None):
        self.oldest = oldest

    def oldest_unsynced_mtime(self):
        return self.oldest


class FakeFiles:
    def __init__(self, files=None):
        self.files = dict(files or {})
        self.writes = []

    def read(self, rel):
        return self.files.get(rel)

    def write(self, rel, text, executable=False):
        self.writes.append((rel, executable))
        self.files[rel] = text


class FakeClock:
    def __init__(self, t):
        self.t = t

    def now(self):
        return self.t


def make(mtimes, t=1000.0, **over):
    kw = dict(snapshot=FakeSnapshot(mtimes), state=FakeState(), runner=FakeRunner(),
              session=FakeSession(), alerts=FakeAlerts(), git=FakeGit(), files=FakeFiles(),
              clock=FakeClock(t), python=["/usr/bin/env", "python3"], bin_dir="/v/_bin")
    kw.update(over)
    return A.Ports(**kw)


def scripts(ports):
    return [c[2] if len(c) > 2 else c for c in ports.runner.calls]


def test_tick():
    print("\n== run_watch_tick ==")
    reg = D.load_registry(json.dumps(REGISTRY))
    base = {"30-Knowledge/a.md": 100.0, "_bin/x.py": 100.0}
    p = make(base)
    acts = A.run_watch_tick(p, reg)
    check("the first tick takes a baseline and runs nothing", acts == [] and p.runner.calls == [], p.runner.calls)
    check("it reads only the registry's watch paths", p.snapshot.asked == [["30-Knowledge", "_bin"]], p.snapshot.asked)
    check("and remembers the snapshot", p.state.data.get("snapshot") == base, p.state.data)

    p.snapshot.mtimes["30-Knowledge/a.md"] = 1050.0
    p.clock.t = 1060.0
    A.run_watch_tick(p, reg)
    check("a changed note runs the ledger and the index commands from the registry",
          scripts(p) == ["/v/_bin/vault_ledger.py", "/v/_bin/index_vault.py"], p.runner.calls)
    check("every command is an argv list starting with the interpreter, never a shell string",
          all(isinstance(c, list) and c[:2] == ["/usr/bin/env", "python3"] for c in p.runner.calls), p.runner.calls)
    check("the ledger gets the session id and the changed paths",
          p.runner.calls[0][3:] == ["--sid", "system", "--paths", "30-Knowledge/a.md"], p.runner.calls[0])

    p.runner.calls = []
    p.clock.t = 1060.0 + 60
    A.run_watch_tick(p, reg)
    check("no sync inside the debounce window", p.runner.calls == [], p.runner.calls)
    p.clock.t = 1060.0 + 120
    A.run_watch_tick(p, reg)
    check("the sync runs once the window passes, with its registry arguments",
          p.runner.calls == [["/usr/bin/env", "python3", "/v/_bin/vault_sync.py", "--hook"]], p.runner.calls)
    p.runner.calls = []
    p.clock.t = 1060.0 + 300
    A.run_watch_tick(p, reg)
    check("and not again", p.runner.calls == [], p.runner.calls)

    p = make(base, session=FakeSession("abc12345"))
    A.run_watch_tick(p, reg)
    p.snapshot.mtimes["30-Knowledge/new.md"] = 1050.0
    A.run_watch_tick(p, reg)
    check("a resolved session id is passed through", "abc12345" in p.runner.calls[0], p.runner.calls)
    check("an action the registry gives no command for is skipped (linkfix here)",
          not any("linkfix" in " ".join(c) for c in p.runner.calls), p.runner.calls)

    p = make(base, runner=FakeRunner(explode_on="vault_ledger.py"))
    A.run_watch_tick(p, reg)
    p.snapshot.mtimes["30-Knowledge/a.md"] = 1050.0
    try:
        A.run_watch_tick(p, reg)
        broke = None
    except Exception as exc:
        broke = exc
    check("a command that cannot run does not stop the tick", broke is None, repr(broke))
    check("the next command still runs", any("index_vault.py" in " ".join(c) for c in p.runner.calls), p.runner.calls)
    check("and the state is still saved", p.state.data["snapshot"]["30-Knowledge/a.md"] == 1050.0)

    p = make(base, git=FakeGit(oldest=1000.0 - 4000))
    A.run_watch_tick(p, reg)
    check("unsynced changes past the threshold raise an alert through the sink",
          [k for k, _ in p.alerts.raised] == ["watch:unsynced"], p.alerts.raised)
    p.git.oldest = None
    p.clock.t = 1100.0
    A.run_watch_tick(p, reg)
    check("and clear it once synced", p.alerts.cleared == ["watch:unsynced"], p.alerts.cleared)
    check("the last tick time is recorded for status", p.state.data.get("last_tick") == 1100.0, p.state.data)


def test_generate():
    print("\n== generate_* ==")
    reg = D.load_registry(json.dumps(REGISTRY))
    p = make({})
    res = A.generate_claude_hooks(p, reg)
    expected = json.dumps(D.render_claude_hooks_json(reg), indent=2, ensure_ascii=False)
    check("hooks.json is written from the registry into the plugin",
          res.changed and p.files.files.get("integrations/claude-code/plugin/brain/hooks/hooks.json") == expected
          and res.path == "integrations/claude-code/plugin/brain/hooks/hooks.json", res)
    p.files.writes = []
    res = A.generate_claude_hooks(p, reg)
    check("unchanged content is not rewritten (its mtime must be allowed to settle)",
          not res.changed and p.files.writes == [], (res, p.files.writes))

    res = A.generate_git_hooks(p, reg)
    check("both git hooks are written, executable",
          sorted(p.files.writes) == [("githooks/post-commit", True), ("githooks/pre-commit", True)]
          and all(r.changed for r in res), p.files.writes)
    check("with the rendered content",
          p.files.files["githooks/pre-commit"] == D.render_git_pre_commit(reg))
    p.files.writes = []
    check("and not rewritten when unchanged",
          not any(r.changed for r in A.generate_git_hooks(p, reg)) and p.files.writes == [])

    res = A.generate_agents_md(p, reg, "Search first.", {"file-watch", "git-hook", "launchd"})
    check("AGENTS.md is written at the vault root",
          res.changed and "Search first." in p.files.files["AGENTS.md"], res)
    p.files.writes = []
    A.generate_agents_md(p, reg, "Search first.", {"file-watch", "git-hook", "launchd"})
    check("and not rewritten when unchanged", p.files.writes == [])

    res = A.generate_claude_md(p)
    check("CLAUDE.md is the fixed pointer to AGENTS.md",
          res.changed and p.files.files["CLAUDE.md"] == D.CLAUDE_MD_POINTER, p.files.files.get("CLAUDE.md"))
    p.files.writes = []
    A.generate_claude_md(p)
    check("and not rewritten when unchanged", p.files.writes == [])
    check("none of the generators runs a process", p.runner.calls == [])


class FakeSettingsHooks:
    def __init__(self, hooks):
        self._hooks, self.calls = hooks, 0

    def hooks(self):
        self.calls += 1
        return self._hooks


class FakeHookLiveness:
    def __init__(self, answers, explode=False):
        self.answers, self.calls, self.explode = list(answers), [], explode

    def findings(self, now):
        self.calls.append(now)
        if self.explode:
            raise OSError("heartbeat log unreadable")
        return self.answers.pop(0) if self.answers else []


class FakeMainLog:
    def __init__(self, chunks):
        self.chunks = list(chunks)

    def read_new(self):
        return self.chunks.pop(0) if self.chunks else ("", False)


OLD = "11111111-5e1f-4c1a-9d0e-000000000001"
NEW = "22222222-2b7a-4f3e-8a11-000000000002"
CONNECT_OLD = "[claude-in-chrome] Connecting to bridge: wss://bridge.claudeusercontent.com/chrome/%s" % OLD
SWITCH = "[account] Login-state transition (loggedOut: false → false, uuid: %s → %s)" % (OLD, NEW)


def test_agent_watch():
    from events_core import domain as D

    print("\n== the agent watch: wiped hooks ==")
    reg = D.load_registry(json.dumps(REGISTRY))
    wired = {"Stop": [{"hooks": [{"type": "command", "command": "/usr/bin/python3 /home/x/Brain/_bin/vault_sync.py --hook"}]}]}
    p = make({}, settings_hooks=FakeSettingsHooks(wired), main_log=FakeMainLog([]))
    did = A.run_agent_watch(p, reg)
    check("hooks in place trigger nothing", p.runner.calls == [] and "hooks-repair" not in did, (p.runner.calls, did))

    p = make({}, t=5000.0, settings_hooks=FakeSettingsHooks({}))
    did = A.run_agent_watch(p, reg)
    check("wiped hooks trigger the guardian's hooks-only repair",
          p.runner.calls == [["/usr/bin/env", "python3", "/v/_bin/guardian.py", "repair", "--hooks-only"]],
          p.runner.calls)
    check("and the tick says so", "hooks-repair" in did, did)
    check("the trigger time is remembered", p.state.data.get("last_hooks_repair_trigger") == 5000.0, p.state.data)
    p.clock.t = 5100.0
    A.run_agent_watch(p, reg)
    check("a tick within five minutes does not trigger again", len(p.runner.calls) == 1, p.runner.calls)
    p.clock.t = 5300.0
    A.run_agent_watch(p, reg)
    check("five minutes later it does", len(p.runner.calls) == 2, p.runner.calls)

    p = make({}, settings_hooks=FakeSettingsHooks(None))
    A.run_agent_watch(p, reg)
    check("no Claude Code here, or settings it cannot read, triggers nothing", p.runner.calls == [])
    p = make({}, settings_hooks=FakeSettingsHooks({}), runner=FakeRunner(explode_on="guardian.py"))
    try:
        A.run_agent_watch(p, reg)
        broke = None
    except Exception as exc:
        broke = exc
    check("a repair that cannot start never breaks the tick", broke is None, repr(broke))

    print("\n== the agent watch: Claude Desktop account switches ==")
    p = make({}, main_log=FakeMainLog([("\n".join([CONNECT_OLD, SWITCH]), False), ("", False)]))
    A.run_agent_watch(p, reg)
    check("a switch and a stale bridge raise their alerts",
          sorted(k for k, _ in p.alerts.raised) == ["account:switch", "bridge:stale"], p.alerts.raised)
    A.run_agent_watch(p, reg)
    check("the switch notice clears on the next tick", p.alerts.cleared == ["account:switch"], p.alerts.cleared)
    check("the account watch memory lives in the watch state",
          (p.state.data.get("account_watch") or {}).get("bridge_stale") is True, p.state.data)
    A.run_watch_tick(p, reg)
    check("and the file-watch tick keeps it", "account_watch" in p.state.data, sorted(p.state.data))
    p = make({}, main_log=FakeMainLog([("\n".join([CONNECT_OLD, SWITCH]), True)]))
    A.run_agent_watch(p, reg)
    check("the first read of an old log raises no historical switch",
          "account:switch" not in [k for k, _ in p.alerts.raised], p.alerts.raised)
    print("\n== the agent watch: hook liveness ==")
    live = FakeHookLiveness([[("hooks:not-firing", "fail", "2 active sessions fired no Brain hook")], []])
    p = make({}, t=10000.0, hook_liveness=live)
    did = A.run_agent_watch(p, reg)
    check("hook liveness findings are raised into the guardian's channel with their severity",
          p.alerts.raised == [("hooks:not-firing", "2 active sessions fired no Brain hook")]
          and p.alerts.severity.get("hooks:not-firing") == "fail", (p.alerts.raised, p.alerts.severity))
    check("and the tick says so", "hooks:not-firing" in did, did)
    p.clock.t = 10100.0
    A.run_agent_watch(p, reg)
    check("it runs at most every five minutes", live.calls == [10000.0], live.calls)
    p.clock.t = 10400.0
    A.run_agent_watch(p, reg)
    check("five minutes later it runs again and clears what is gone",
          live.calls == [10000.0, 10400.0] and p.alerts.cleared == ["hooks:not-firing"], (live.calls, p.alerts.cleared))
    p = make({}, hook_liveness=FakeHookLiveness([], explode=True))
    try:
        A.run_agent_watch(p, reg)
        broke = None
    except Exception as exc:
        broke = exc
    check("a liveness check that breaks never breaks the tick", broke is None, repr(broke))

    p = make({})
    check("with neither watch wired the use case does nothing", A.run_agent_watch(p, reg) == [] and p.runner.calls == [])


def main():
    global A, D
    try:
        from events_core import application as A
        from events_core import domain as D
        from events_core import ports as P  # noqa: F401 — the ports module must exist
    except Exception as exc:
        check("events_core.application and ports import", False, "%s: %s" % (type(exc).__name__, exc))
    else:
        for t in (test_tick, test_generate, test_agent_watch):
            try:
                t()
            except Exception as exc:
                import traceback
                traceback.print_exc()
                check("%s ran to the end" % t.__name__, False, "%s: %s" % (type(exc).__name__, exc))
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
