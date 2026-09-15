#!/usr/bin/env python3
"""Tests for events_core.domain — Brain's own event registry and the rules built on it.

The registry text is a fixture in this file, not the vault's 90-Meta/events.json, so
these tests do not move when the vault does. Nothing here touches the disk. Run standalone:

    python3 _bin/events_core/domain_test.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.dirname(HERE)
sys.path[0] = BIN

ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


FIXTURE = {
    "version": 1,
    "watch": {"paths": ["10-Projects", "30-Knowledge", "_bin"], "debounce_s": 120,
              "unsynced_alert_s": 3600, "unsaved_alert_s": 7200,
              "save_prefixes": ["10-Projects", "30-Knowledge"], "unsaved_ignore": ["50-Sessions"]},
    "events": [
        {"id": "session-start", "description": "startup context", "handler": "compass",
         "triggers": [
             {"kind": "claude-hook", "event": "SessionStart", "matcher": "startup|resume",
              "command": "compass.py", "timeout": 8},
             {"kind": "cli", "command": "brain session-start"},
             {"kind": "mcp", "tool": "session_start"}]},
        {"id": "prompt-submit", "description": "per-prompt retrieval", "handler": "retrieve",
         "triggers": [
             {"kind": "claude-hook", "event": "UserPromptSubmit", "command": "retrieve.py",
              "timeout": 8, "statusMessage": "Querying the vault..."},
             {"kind": "cli", "command": "brain recall \"<terms>\""}]},
        {"id": "stop-memory-gate", "description": "blocks close without a saved note",
         "handler": "gate_memory",
         "triggers": [{"kind": "claude-hook", "event": "Stop", "command": "gate_memory.py", "timeout": 10}]},
        {"id": "sync", "description": "commit and push the vault", "handler": "vault_sync",
         "triggers": [
             {"kind": "claude-hook", "event": "Stop", "command": "vault_sync.py --hook",
              "statusMessage": "Syncing the vault...", "async": True},
             {"kind": "launchd", "label": "com.secondbrain.sync"},
             {"kind": "file-watch", "action": "sync-debounce", "command": "vault_sync.py --hook"}]},
        {"id": "reindex", "description": "keep the index current", "handler": "index_vault",
         "triggers": [{"kind": "file-watch", "action": "index-trigger", "command": "index_vault.py"}]},
        {"id": "pre-write-gate", "description": "protected paths and secrets", "handler": "gate_write",
         "triggers": [
             {"kind": "claude-hook", "event": "PreToolUse", "matcher": "Bash|Edit|Write",
              "command": "gate_write.py", "timeout": 5},
             {"kind": "git-hook", "hook": "pre-commit", "command": "events_core/git_pre_commit.py"}]},
        {"id": "post-commit-dirty", "description": "mark the index dirty", "handler": "git_post_commit",
         "triggers": [{"kind": "git-hook", "hook": "post-commit", "command": "events_core/git_post_commit.py"}]},
    ],
}

PY = "/usr/bin/python3"
BINP = "/home/brain-origin/Brain/_bin"

EXPECTED_HOOKS = {"hooks": {
    "SessionStart": [{"matcher": "startup|resume", "hooks": [
        {"type": "command", "command": "%s %s/compass.py" % (PY, BINP), "timeout": 8}]}],
    "UserPromptSubmit": [{"hooks": [
        {"type": "command", "command": "%s %s/retrieve.py" % (PY, BINP), "timeout": 8,
         "statusMessage": "Querying the vault..."}]}],
    "Stop": [{"hooks": [
        {"type": "command", "command": "%s %s/gate_memory.py" % (PY, BINP), "timeout": 10},
        {"type": "command", "command": "%s %s/vault_sync.py --hook" % (PY, BINP),
         "statusMessage": "Syncing the vault...", "async": True}]}],
    "PreToolUse": [{"matcher": "Bash|Edit|Write", "hooks": [
        {"type": "command", "command": "%s %s/gate_write.py" % (PY, BINP), "timeout": 5}]}],
}}


def raises(D, text):
    try:
        D.load_registry(text)
    except D.RegistryError as exc:
        return str(exc)
    except Exception as exc:
        return "WRONG EXCEPTION %s: %s" % (type(exc).__name__, exc)
    return None


def test_registry(D):
    print("\n== load_registry ==")
    reg = D.load_registry(json.dumps(FIXTURE))
    check("every event is loaded in order",
          [e.id for e in reg.events] == [e["id"] for e in FIXTURE["events"]], [e.id for e in reg.events])
    check("triggers of one kind can be listed with their event",
          [(e.id, t.spec["action"]) for e, t in reg.triggers("file-watch")]
          == [("sync", "sync-debounce"), ("reindex", "index-trigger")])
    check("the watch configuration is read",
          reg.watch.debounce_s == 120 and reg.watch.paths == ("10-Projects", "30-Knowledge", "_bin")
          and reg.watch.save_prefixes == ("10-Projects", "30-Knowledge")
          and reg.watch.unsaved_ignore == ("50-Sessions",), reg.watch)
    check("an event can be looked up by id", reg.event("sync").handler == "vault_sync")

    bad = json.loads(json.dumps(FIXTURE))
    bad["events"][0]["triggers"][0]["kind"] = "carrier-pigeon"
    err = raises(D, json.dumps(bad))
    check("an unknown trigger kind is rejected, naming it", err and "carrier-pigeon" in err, err)

    bad = json.loads(json.dumps(FIXTURE))
    bad["events"][1]["handler"] = "retreive"
    err = raises(D, json.dumps(bad))
    check("a handler that is not an approved module is rejected (a typo fails loud)",
          err and "retreive" in err, err)

    bad = json.loads(json.dumps(FIXTURE))
    bad["events"][1]["id"] = "session-start"
    check("duplicate event ids are rejected", raises(D, json.dumps(bad)))

    bad = json.loads(json.dumps(FIXTURE))
    bad["events"][3]["triggers"][2]["action"] = "reboot"
    check("an unknown file-watch action is rejected", raises(D, json.dumps(bad)))

    bad = json.loads(json.dumps(FIXTURE))
    del bad["events"][0]["triggers"][0]["event"]
    check("a claude-hook trigger without its Claude event is rejected", raises(D, json.dumps(bad)))

    bad = json.loads(json.dumps(FIXTURE))
    bad["events"][5]["triggers"][1]["hook"] = "pre-push"
    check("a git hook other than pre-commit/post-commit is rejected", raises(D, json.dumps(bad)))

    check("text that is not JSON is a RegistryError", raises(D, "{nope"))
    minimal = D.load_registry(json.dumps({"version": 1, "events": []}))
    check("the watch section has defaults when absent",
          minimal.watch.debounce_s > 0 and minimal.watch.unsynced_alert_s > 0 and minimal.watch.paths, minimal.watch)


def test_render_hooks(D):
    print("\n== render_claude_hooks_json ==")
    reg = D.load_registry(json.dumps(FIXTURE))
    got = D.render_claude_hooks_json(reg)
    check("the hooks.json shape is rendered exactly from the claude-hook triggers",
          got == EXPECTED_HOOKS, json.dumps(got, indent=1)[:600])
    check("events appear in first-use order, byte for byte",
          json.dumps(got, indent=2) == json.dumps(EXPECTED_HOOKS, indent=2))
    other = D.render_claude_hooks_json(reg, python="/opt/py", bin_dir="/v/_bin")
    check("interpreter and bin directory are parameters",
          other["hooks"]["Stop"][0]["hooks"][0]["command"] == "/opt/py /v/_bin/gate_memory.py", other)


def test_render_agents_md(D):
    print("\n== render_agents_md ==")
    reg = D.load_registry(json.dumps(FIXTURE))
    protocol = "---\nid: protocol\n---\n\nSearch the vault before answering.\n"
    independent = D.render_agents_md(reg, protocol, known_triggers={"file-watch", "git-hook", "launchd"})
    with_claude = D.render_agents_md(reg, protocol,
                                     known_triggers={"claude-hook", "file-watch", "git-hook", "launchd"})
    check("the protocol body is included without its frontmatter",
          "Search the vault before answering." in independent and "id: protocol" not in independent)
    check("it says it is generated", "Generated" in independent and "events.json" in independent)
    check("every event is listed", all(e["id"] in independent for e in FIXTURE["events"]))
    check("without an agent adapter the degraded-mode table appears",
          "Without an agent adapter" in independent, independent)
    check("and gives the manual equivalent (CLI or MCP) for events only an adapter fired",
          "brain session-start" in independent and "session_start" in independent
          and 'brain recall "<terms>"' in independent, independent)
    check("an event with no manual equivalent is named as lost, not hidden",
          "stop-memory-gate" in independent.split("Without an agent adapter", 1)[1], independent)
    check("with the Claude Code adapter the degraded-mode table is absent",
          "Without an agent adapter" not in with_claude, with_claude)
    check("the same registry renders the same text every time",
          D.render_agents_md(reg, protocol, {"file-watch"}) == D.render_agents_md(reg, protocol, {"file-watch"}))


def test_render_git_hooks(D):
    print("\n== render_git_pre_commit / render_git_post_commit ==")
    reg = D.load_registry(json.dumps(FIXTURE))
    pre, post = D.render_git_pre_commit(reg), D.render_git_post_commit(reg)
    check("the pre-commit script is POSIX sh that runs the registry's command through pywrap",
          pre.startswith("#!/bin/sh\n") and "pywrap.sh" in pre and "events_core/git_pre_commit.py" in pre, pre)
    check("it names the event it serves and says it is generated",
          "pre-write-gate" in pre and "Generated" in pre, pre)
    check("it documents --no-verify and its cost", "--no-verify" in pre and "secret" in pre.lower(), pre)
    check("it passes when Brain's _bin is not there (a clone without the engine)",
          "exit 0" in pre, pre)
    check("the post-commit script runs its own command",
          post.startswith("#!/bin/sh\n") and "events_core/git_post_commit.py" in post
          and "post-commit-dirty" in post, post)
    empty = D.load_registry(json.dumps({"version": 1, "events": []}))
    check("with no git-hook trigger the script is a harmless no-op",
          D.render_git_pre_commit(empty).rstrip().endswith("exit 0")
          and "git_pre_commit.py" not in D.render_git_pre_commit(empty))


def watch(D, **over):
    w = D.load_registry(json.dumps(FIXTURE)).watch
    return w if not over else D.WatchConfig(**dict(w.__dict__, **over))


def kinds(plan):
    return [a.kind for a in plan.actions]


def test_watch_tick(D):
    print("\n== plan_watch_tick ==")
    w = watch(D)
    m0 = D.WatchMemory()
    base = {"30-Knowledge/a.md": 100.0, "_bin/x.py": 100.0}

    p = D.plan_watch_tick(None, base, now=1000.0, memory=m0, watch=w)
    check("the first tick only takes a baseline", kinds(p) == [] and p.raise_alerts == [], p)

    p = D.plan_watch_tick(base, dict(base), now=1060.0, memory=m0, watch=w)
    check("nothing changed, nothing to do", kinds(p) == [], p)

    cur = dict(base, **{"30-Knowledge/a.md": 1050.0})
    p = D.plan_watch_tick(base, cur, now=1060.0, memory=m0, watch=w)
    check("a modified note updates the ledger and the index",
          kinds(p) == ["ledger-update", "index-trigger"], kinds(p))
    check("the ledger action carries the changed note",
          p.actions[0].paths == ("30-Knowledge/a.md",), p.actions[0])
    check("a modified note does not need linkfix", "linkfix-trigger" not in kinds(p))
    check("a change starts the sync debounce", p.memory.sync_pending and p.memory.last_change_at == 1060.0,
          p.memory)

    cur2 = dict(base, **{"30-Knowledge/new.md": 1050.0})
    check("an added note also triggers linkfix",
          "linkfix-trigger" in kinds(D.plan_watch_tick(base, cur2, 1060.0, m0, w)))
    gone = {"_bin/x.py": 100.0}
    check("a removed note also triggers linkfix and the index",
          {"linkfix-trigger", "index-trigger"} <= set(kinds(D.plan_watch_tick(base, gone, 1060.0, m0, w))))
    code = dict(base, **{"_bin/x.py": 1050.0})
    pc = D.plan_watch_tick(base, code, 1060.0, m0, w)
    check("a code change neither reindexes nor relinks, but still debounces a sync",
          kinds(pc) == [] and pc.memory.sync_pending, (kinds(pc), pc.memory))

    mem = p.memory
    p2 = D.plan_watch_tick(cur, dict(cur), now=1060.0 + 119, memory=mem, watch=w)
    check("no sync before the debounce window has passed", "sync-debounce" not in kinds(p2), kinds(p2))
    p3 = D.plan_watch_tick(cur, dict(cur), now=1060.0 + 120, memory=p2.memory, watch=w)
    check("a sync exactly at the debounce boundary", kinds(p3) == ["sync-debounce"], kinds(p3))
    check("and only once", not p3.memory.sync_pending
          and "sync-debounce" not in kinds(D.plan_watch_tick(cur, dict(cur), 1060.0 + 200, p3.memory, w)))
    later = dict(cur, **{"30-Knowledge/a.md": 1150.0})
    p4 = D.plan_watch_tick(cur, later, now=1160.0, memory=p2.memory, watch=w)
    check("a new change inside the window pushes the sync back",
          "sync-debounce" not in kinds(p4) and p4.memory.last_change_at == 1160.0, (kinds(p4), p4.memory))


def test_detection(D):
    print("\n== detection that replaces the Stop memory gate ==")
    w = watch(D)
    base = {"30-Knowledge/a.md": 100.0, "_bin/x.py": 100.0, "50-Sessions/s.md": 100.0}
    code = dict(base, **{"_bin/x.py": 1000.0})
    p = D.plan_watch_tick(base, code, now=1000.0, memory=D.WatchMemory(), watch=w)
    check("a write that is not a saved note starts the unsaved clock",
          p.memory.unsaved_since == 1000.0 and p.raise_alerts == [], p.memory)
    p2 = D.plan_watch_tick(code, dict(code), now=1000.0 + 7199, memory=p.memory, watch=w)
    check("no alert before the threshold", p2.raise_alerts == [], p2.raise_alerts)
    p3 = D.plan_watch_tick(code, dict(code), now=1000.0 + 7200, memory=p2.memory, watch=w)
    check("past the threshold with no note saved, an alert is raised",
          [k for k, _ in p3.raise_alerts] == ["watch:unsaved-writes"] and "system" in p3.raise_alerts[0][1],
          p3.raise_alerts)
    p4 = D.plan_watch_tick(code, dict(code), now=1000.0 + 7300, memory=p3.memory, watch=w)
    check("it is raised once, not every tick", p4.raise_alerts == [], p4.raise_alerts)
    saved = dict(code, **{"30-Knowledge/a.md": 9000.0})
    p5 = D.plan_watch_tick(code, saved, now=9000.0, memory=p4.memory, watch=w)
    check("saving a note clears the clock and the alert",
          p5.memory.unsaved_since is None and p5.clear_alerts == ["watch:unsaved-writes"], (p5.memory, p5.clear_alerts))
    machinery = dict(base, **{"50-Sessions/s.md": 1000.0})
    check("writes the machinery itself makes do not start the clock",
          D.plan_watch_tick(base, machinery, 1000.0, D.WatchMemory(), w).memory.unsaved_since is None)

    q = D.plan_watch_tick(base, dict(base), now=5000.0, memory=D.WatchMemory(), watch=w, unsynced_oldest=5000.0 - 3599)
    check("unsynced changes younger than the threshold raise nothing", q.raise_alerts == [], q.raise_alerts)
    q2 = D.plan_watch_tick(base, dict(base), now=5000.0, memory=q.memory, watch=w, unsynced_oldest=5000.0 - 3600)
    check("unsynced changes past the threshold raise an alert",
          [k for k, _ in q2.raise_alerts] == ["watch:unsynced"], q2.raise_alerts)
    q3 = D.plan_watch_tick(base, dict(base), now=5100.0, memory=q2.memory, watch=w, unsynced_oldest=None)
    check("once synced the alert is cleared", q3.clear_alerts == ["watch:unsynced"], q3.clear_alerts)
    q4 = D.plan_watch_tick(base, dict(base), now=5200.0, memory=q3.memory, watch=w, unsynced_oldest=None)
    check("and not cleared again", q4.clear_alerts == [], q4.clear_alerts)


def test_hooks_doc(D):
    print("\n== HOOKS-WITHOUT-CLAUDE.md ==")
    reg = D.load_registry(json.dumps(FIXTURE))
    doc = D.render_hooks_without_claude(reg)
    check("it is a generated Markdown page", doc.startswith("# Brain events without Claude Code")
          and "Generated by _bin/gen_instructions.py" in doc and doc.endswith("\n"), doc[:200])
    check("it is deterministic", D.render_hooks_without_claude(reg) == doc)
    check("every event has its own section", all("### `%s`" % e.id in doc for e in reg.events), doc)
    section = doc.split("### `session-start`", 1)[1].split("### ", 1)[0]
    check("an event with a Claude Code hook gets its brain hook equivalent",
          "`brain hook session-start`" in section and "`SessionStart`" in section, section)
    check("and every other trigger: CLI, MCP tool", "`brain session-start`" in section and "`session_start`" in section,
          section)
    check("and the exact handler command with its stdin contract",
          "_bin/compass.py" in section and "stdin" in section, section)
    sync = doc.split("### `sync`", 1)[1].split("### ", 1)[0]
    check("launchd jobs and file-watch actions are listed",
          "com.secondbrain.sync" in sync and "sync-debounce" in sync and "brain_watch.py tick" in sync, sync)
    check("the page says to verify a handler's JSON before wiring another agent to it",
          "verify" in doc.lower() and "session_id" in doc, doc)
    check("wiring examples for other agents are marked untested",
          "verify against that agent's current documentation, not tested here" in doc, doc)
    check("no long dashes in the prose", "—" not in doc and "–" not in doc)
    twice = json.loads(json.dumps(FIXTURE))
    for e in twice["events"]:
        if e["id"] == "stop-memory-gate":
            e["triggers"].append({"kind": "cli", "command": "brain hook stop-memory-gate"})
    doc2 = D.render_hooks_without_claude(D.load_registry(json.dumps(twice)))
    gate = doc2.split("### `stop-memory-gate`", 1)[1].split("### ", 1)[0]
    check("a cli trigger that is the brain hook command is not listed twice",
          gate.count("brain hook stop-memory-gate") == 1, gate)


def test_real_registry(D):
    print("\n== the vault's own 90-Meta/events.json ==")
    vault = os.path.dirname(BIN)
    path = os.path.join(vault, "90-Meta", "events.json")
    hooks = os.path.join(vault, "integrations", "claude-code", "plugin", "brain", "hooks", "hooks.json")
    if not os.path.exists(path):
        check("90-Meta/events.json exists", False, path)
        return
    reg = D.load_registry(open(path, encoding="utf-8").read())
    check("the real registry parses and validates", len(reg.events) >= 9, len(reg.events))
    rendered = json.dumps(D.render_claude_hooks_json(reg), indent=2, ensure_ascii=False)
    check("it renders the plugin's hooks.json byte for byte",
          rendered == open(hooks, encoding="utf-8").read(), rendered[:300])
    check("every Claude Code hook the plugin ships is an event in the registry",
          sorted(json.load(open(hooks))["hooks"]) == sorted({t.spec["event"] for _e, t in reg.triggers("claude-hook")}))
    kinds = {t.kind for e in reg.events for t in e.triggers}
    check("the real registry wires the agent-independent triggers",
          {"file-watch", "git-hook", "launchd", "cli", "mcp"} <= kinds, sorted(kinds))
    lost = [e.id for e in reg.events if any(t.kind == "claude-hook" for t in e.triggers)
            and not any(t.kind in ("cli", "mcp") for t in e.triggers)]
    check("every event with a Claude Code hook has a manual equivalent (brain hook <id> at least)", lost == [], lost)
    undeclared = [e.id for e in reg.events if any(t.kind == "claude-hook" for t in e.triggers)
                  and getattr(e, "liveness", "") not in getattr(D, "LIVENESS_CLASSES", ())]
    check("every event with a Claude Code hook declares its liveness", undeclared == [], undeclared)
    doc_path = os.path.join(vault, "90-Meta", "HOOKS-WITHOUT-CLAUDE.md")
    current = open(doc_path, encoding="utf-8").read() if os.path.exists(doc_path) else None
    check("the vault's 90-Meta/HOOKS-WITHOUT-CLAUDE.md is generated from this registry and current",
          current == D.render_hooks_without_claude(reg), doc_path)


OLD = "11111111-5e1f-4c1a-9d0e-000000000001"
NEW = "22222222-2b7a-4f3e-8a11-000000000002"
# Line shapes of the Claude Desktop main.log: "claude-in-chrome] Connecting to bridge" and
# "[account] Login-state transition". The timestamps and surrounding text are synthetic.
CONNECT_OLD = ("2000-01-01 10:07:12 [info] [claude-in-chrome] Connecting to bridge: "
               "wss://bridge.claudeusercontent.com/chrome/%s" % OLD)
SWITCH = "2000-01-01 12:12:40 [info] [account] Login-state transition (loggedOut: false \u2192 false, uuid: %s \u2192 %s)" % (OLD, NEW)
CONNECT_NEW = ("2000-01-01 14:40:02 [info] [claude-in-chrome] Connecting to bridge: "
               "wss://bridge.claudeusercontent.com/chrome/%s" % NEW)


def test_agent_watch(D):
    print("\n== hook presence and the repair trigger ==")
    reg = D.load_registry(json.dumps({"version": 1, "events": [
        {"id": "session-start", "description": "s", "handler": "compass",
         "triggers": [{"kind": "claude-hook", "event": "SessionStart", "command": "compass.py"}]},
        {"id": "sync", "description": "s", "handler": "vault_sync",
         "triggers": [{"kind": "claude-hook", "event": "Stop", "command": "vault_sync.py --hook"},
                      {"kind": "file-watch", "action": "sync-debounce", "command": "vault_sync.py --hook"}]},
        {"id": "sync-again", "description": "s", "handler": "vault_sync",
         "triggers": [{"kind": "claude-hook", "event": "SessionEnd", "command": "vault_sync.py --hook"}]}]}))
    expected = D.claude_hook_commands(reg)
    check("the claude-hook commands come from the registry, once each, in order",
          expected == ["compass.py", "vault_sync.py --hook"], expected)
    live = {"SessionStart": [{"hooks": [{"type": "command", "command": "/usr/bin/python3 /home/x/Brain/_bin/compass.py"}]}],
            "Stop": [{"hooks": [{"type": "command", "command": "/opt/homebrew/bin/python3 /v/_bin/vault_sync.py --hook"},
                                {"type": "command", "command": "say done"}]}]}
    check("hooks are present when every registry command is wired, whatever the interpreter or path",
          D.hooks_look_present(live, expected) is True)
    check("one missing Brain hook is enough to say no",
          D.hooks_look_present({"Stop": live["Stop"]}, expected) is False)
    check("a wiped hooks block is no", D.hooks_look_present({}, expected) is False
          and D.hooks_look_present(None, expected) is False)
    check("a command that only shares a suffix is not a match",
          D.hooks_look_present({"S": [{"hooks": [{"command": "/x/not_compass.py"}, {"command": "/x/vault_sync.py --hook"}]}]},
                               expected) is False)
    check("no expected commands means nothing to check", D.hooks_look_present({}, []) is True)
    check("the first repair trigger is due", D.repair_trigger_due(None, 1000.0) is True)
    check("a trigger five minutes after the last is due", D.repair_trigger_due(700.0, 1000.0) is True)
    check("a trigger sooner is not", D.repair_trigger_due(800.0, 1000.0) is False)
    check("the debounce is configurable", D.repair_trigger_due(990.0, 1000.0, min_interval_s=5) is True)

    print("\n== Claude Desktop main.log: account switches and the browser bridge ==")
    ts = D.parse_login_transitions("noise\n%s\nmore noise\n" % SWITCH)
    check("a Login-state transition line is parsed", [(t.old_uuid, t.new_uuid) for t in ts] == [(OLD, NEW)], ts)
    ascii_line = "[account] Login-state transition (loggedOut: true -> false, uuid: none -> %s)" % NEW
    ts = D.parse_login_transitions(ascii_line)
    check("an ASCII arrow parses too", [(t.old_uuid, t.new_uuid) for t in ts] == [("none", NEW)], ts)
    check("text with no transition parses to nothing, never raises",
          D.parse_login_transitions("[account] Login-state changed somehow\n\x00garbage") == [])

    m, switches = D.advance_account_watch(D.AccountWatch(), "\n".join([CONNECT_OLD, SWITCH]))
    check("a bridge connected to the account that was just switched away from is stale",
          m.bridge_stale is True and m.account_uuid == NEW and m.bridge_uuid == OLD, m)
    check("and the switch is reported", [(s.old_uuid, s.new_uuid) for s in switches] == [(OLD, NEW)], switches)
    m2, switches = D.advance_account_watch(m, CONNECT_NEW)
    check("a bridge that reconnects under the current account is no longer stale",
          m2.bridge_stale is False and switches == [], m2)
    m3, _ = D.advance_account_watch(D.AccountWatch(), "\n".join([SWITCH, CONNECT_NEW]))
    check("a bridge connected after the switch was never stale", m3.bridge_stale is False, m3)
    m4, _ = D.advance_account_watch(D.AccountWatch(), SWITCH)
    check("a switch with no bridge seen is not a stale bridge", m4.bridge_stale is False, m4)
    same = "[account] Login-state transition (loggedOut: true \u2192 false, uuid: %s \u2192 %s)" % (NEW, NEW)
    _, switches = D.advance_account_watch(D.AccountWatch(), same)
    check("logging back into the same account is not a switch", switches == [], switches)
    short = CONNECT_OLD.replace(OLD, OLD[:8])
    m5, _ = D.advance_account_watch(D.AccountWatch(), "\n".join([short, SWITCH]))
    check("a truncated uuid on one side still matches its account", m5.bridge_stale is True, m5)

    print("\n== what the account watch tells the guardian ==")
    plan = D.plan_account_watch({}, "\n".join([CONNECT_OLD, SWITCH]), fresh=False)
    raised = dict(plan.raise_alerts)
    check("a switch raises account:switch", D.ACCOUNT_SWITCH_KEY in raised and OLD[:8] in raised[D.ACCOUNT_SWITCH_KEY]
          and NEW[:8] in raised[D.ACCOUNT_SWITCH_KEY], raised)
    check("a stale bridge raises bridge:stale saying to restart the Claude app",
          D.BRIDGE_STALE_KEY in raised and "restart" in raised[D.BRIDGE_STALE_KEY].lower(), raised)
    plan2 = D.plan_account_watch(plan.memory, "", fresh=False)
    check("the switch notice clears on the next tick, the stale bridge stays",
          plan2.clear_alerts == [D.ACCOUNT_SWITCH_KEY] and plan2.raise_alerts == [], plan2)
    plan3 = D.plan_account_watch(plan2.memory, CONNECT_NEW, fresh=False)
    check("a reconnected bridge clears bridge:stale", plan3.clear_alerts == [D.BRIDGE_STALE_KEY], plan3)
    plan4 = D.plan_account_watch(plan3.memory, "", fresh=False)
    check("a quiet log is a quiet tick", plan4.raise_alerts == [] and plan4.clear_alerts == [], plan4)
    first = D.plan_account_watch({}, "\n".join([CONNECT_OLD, SWITCH]), fresh=True)
    check("the first read of an old log reports no historical switch, but a bridge that is stale now",
          D.ACCOUNT_SWITCH_KEY not in dict(first.raise_alerts) and D.BRIDGE_STALE_KEY in dict(first.raise_alerts),
          first.raise_alerts)
    check("the memory is plain data the state file can hold", json.loads(json.dumps(plan.memory)) == plan.memory,
          plan.memory)


def test_main_log_isolation(D):
    print("\n== a scratch main.log must not write real state ==")
    fn = getattr(D, "main_log_isolation_problem", None)
    check("the rule is in the domain", callable(fn), fn)
    if not callable(fn):
        return
    real_log = "/h/Library/Logs/Claude/main.log"
    real_states = ["/h/Library/Application Support/brain", "/h/.claude/state/brain"]
    check("the real main.log may use the real state", fn(real_log, real_log, real_states[0], real_states) == "")
    check("no override (empty) is the real main.log", fn("", real_log, real_states[0], real_states) == "")
    why = fn("/tmp/scratch/main.log", real_log, real_states[0], real_states)
    check("a scratch main.log with the default state directory is refused, in one line naming BRAIN_STATE",
          why and "\n" not in why and "BRAIN_STATE" in why and "BRAIN_CLAUDE_MAIN_LOG" in why, why)
    check("so is the legacy state directory",
          fn("/tmp/scratch/main.log", real_log, real_states[1], real_states) != "")
    check("a trailing slash does not hide the real state directory",
          fn("/tmp/scratch/main.log", real_log, real_states[0] + "/", real_states) != "")
    check("a scratch main.log with a scratch state directory is allowed",
          fn("/tmp/scratch/main.log", real_log, "/tmp/scratch/state", real_states) == "")


def test_liveness(D):
    print("\n== hook liveness in the registry ==")
    raw = json.loads(json.dumps(FIXTURE))
    raw["events"][0]["liveness"] = "session"
    reg = D.load_registry(json.dumps(raw))
    check("an event declares how often its hook is expected to fire",
          getattr(reg.events[0], "liveness", None) == "session", reg.events[0])
    check("an event that does not say has no liveness", getattr(reg.events[1], "liveness", "missing") == "", reg.events[1])
    check("the classes are session, regular and conditional",
          tuple(getattr(D, "LIVENESS_CLASSES", ())) == ("session", "regular", "conditional"))
    raw["events"][0]["liveness"] = "sometimes"
    try:
        D.load_registry(json.dumps(raw))
        err = None
    except D.RegistryError as exc:
        err = exc
    check("an unknown liveness class is a RegistryError", err is not None and "liveness" in str(err), err)
    raw["events"][0]["liveness"] = "session"
    doc = D.render_hooks_without_claude(D.load_registry(json.dumps(raw)))
    section = doc.split("### `session-start`", 1)[1].split("### ", 1)[0]
    check("the hooks page shows each hook's liveness", "Liveness: `session`" in section, section)
    check("and explains the heartbeat and where to look", "heartbeat.jsonl" in doc and "guardian.py status" in doc, doc[:2000])
    check("still with no long dashes", "—" not in doc and "–" not in doc)


def main():
    try:
        from events_core import domain as D
    except Exception as exc:
        check("events_core.domain imports", False, "%s: %s" % (type(exc).__name__, exc))
    else:
        for t in (test_registry, test_render_hooks, test_render_agents_md, test_render_git_hooks,
                  test_watch_tick, test_detection, test_hooks_doc, test_real_registry, test_agent_watch,
                  test_main_log_isolation, test_liveness):
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
