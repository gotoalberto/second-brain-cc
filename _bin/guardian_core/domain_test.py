#!/usr/bin/env python3
"""Tests for guardian_core.domain — the pure rules of the Brain guardian.

Nothing here touches the disk, a subprocess or the clock: every input is a literal and
every "now" is passed in. Run standalone:

    python3 _bin/guardian_core/domain_test.py
"""
import datetime as dt
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[0] = os.path.dirname(HERE)          # _bin, so `guardian_core` imports as a package

ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


PY = "/usr/bin/python3"
V = "/home/brain-origin/Brain/_bin"


def cmd(script, args=""):
    return ("%s %s/%s %s" % (PY, V, script, args)).strip()


def canonical():
    return {
        "SessionStart": [{"matcher": "startup|resume", "hooks": [
            {"type": "command", "command": cmd("compass.py"), "timeout": 8}]}],
        "Stop": [{"hooks": [
            {"type": "command", "command": cmd("gate_memory.py"), "timeout": 10},
            {"type": "command", "command": cmd("vault_sync.py", "--hook"), "async": True}]}],
    }


def test_hook_identity(D):
    print("\n== hook identity ==")
    check("identity is the script basename plus its arguments",
          D.hook_identity(cmd("vault_sync.py", "--hook")) == "vault_sync.py --hook",
          D.hook_identity(cmd("vault_sync.py", "--hook")))
    check("identity survives a different interpreter and vault path",
          D.hook_identity("/opt/homebrew/bin/python3 /tmp/elsewhere/_bin/compass.py")
          == D.hook_identity(cmd("compass.py")))
    check("a command that runs no python script has no identity",
          D.hook_identity("echo hello") is None)


def test_merge_hooks(D):
    print("\n== merge_hooks ==")
    can = canonical()

    merged, changes = D.merge_hooks(can, {})
    check("empty settings get every canonical hook",
          merged == can, merged)
    check("each added hook is reported as a change",
          sorted((c.kind, c.event, c.identity) for c in changes)
          == [("added", "SessionStart", "compass.py"), ("added", "Stop", "gate_memory.py"),
              ("added", "Stop", "vault_sync.py --hook")],
          [(c.kind, c.event, c.identity) for c in changes])

    merged, changes = D.merge_hooks(can, can)
    check("settings already canonical produce no change", changes == [], changes)
    check("and come back equal", merged == can)

    foreign = {"type": "command", "command": "/usr/local/bin/my-own-hook --x"}
    current = {
        "Stop": [{"hooks": [
            foreign,
            {"type": "command", "command": "/usr/bin/python3 /old/place/_bin/gate_memory.py",
             "timeout": 3}]}],
        "Notification": [{"hooks": [{"type": "command", "command": "say hi"}]}],
    }
    before = repr(current)
    merged, changes = D.merge_hooks(can, current)
    stop_cmds = [h["command"] for g in merged["Stop"] for h in g["hooks"]]
    check("a foreign hook in a Brain event is left untouched",
          foreign in merged["Stop"][0]["hooks"], merged["Stop"])
    check("a foreign event is left untouched",
          merged.get("Notification") == current["Notification"])
    check("a Brain hook with a broken path is fixed in place, not duplicated",
          stop_cmds.count(cmd("gate_memory.py")) == 1
          and "/usr/bin/python3 /old/place/_bin/gate_memory.py" not in stop_cmds, stop_cmds)
    check("its fix carries the canonical options (timeout)",
          any(h.get("timeout") == 10 for g in merged["Stop"] for h in g["hooks"]
              if h["command"] == cmd("gate_memory.py")))
    check("the fix is reported as 'fixed'",
          ("fixed", "Stop", "gate_memory.py") in [(c.kind, c.event, c.identity) for c in changes],
          [(c.kind, c.event, c.identity) for c in changes])
    check("merge does not mutate its inputs", repr(current) == before)

    dup = {"Stop": [{"hooks": [
        {"type": "command", "command": cmd("gate_memory.py"), "timeout": 10},
        {"type": "command", "command": cmd("gate_memory.py"), "timeout": 10},
        {"type": "command", "command": cmd("vault_sync.py", "--hook"), "async": True}]}],
        "SessionStart": can["SessionStart"]}
    merged, changes = D.merge_hooks(can, dup)
    check("a Brain hook wired twice is de-duplicated",
          [h["command"] for g in merged["Stop"] for h in g["hooks"]].count(cmd("gate_memory.py")) == 1)
    check("the de-duplication is reported",
          [c.kind for c in changes] == ["deduplicated"], [c.kind for c in changes])

    wrong = {"SessionStart": [{"matcher": "startup", "hooks": [
        {"type": "command", "command": cmd("compass.py"), "timeout": 8}]}],
        "Stop": can["Stop"]}
    merged, changes = D.merge_hooks(can, wrong)
    check("a Brain hook under the wrong matcher moves to the canonical matcher",
          merged["SessionStart"] == can["SessionStart"], merged["SessionStart"])
    check("the move is reported",
          [c.kind for c in changes] == ["moved"], [c.kind for c in changes])

    extra = {"Stop": [{"hooks": [
        {"type": "command", "command": cmd("gate_memory.py"), "timeout": 10},
        {"type": "command", "command": cmd("vault_sync.py", "--hook"), "async": True},
        {"type": "command", "command": cmd("retired_script.py")}]}],
        "SessionStart": can["SessionStart"]}
    merged, changes = D.merge_hooks(can, extra)
    check("a Brain-looking hook that canonical does not know is never removed",
          cmd("retired_script.py") in [h["command"] for g in merged["Stop"] for h in g["hooks"]])
    check("every change has readable text naming event and script",
          all(c.event in c.text and c.identity in c.text for c in D.merge_hooks(can, {})[1]))
    check("every change has a stable key",
          len({c.key for c in D.merge_hooks(can, {})[1]}) == 3)


VAULT = "/home/brain-origin/Brain"


def test_stale_hooks(D):
    print("\n== stale Brain hooks ==")
    can = canonical()
    dirs = D.brain_script_dirs(VAULT)
    check("Brain's script dirs are the vault's _bin, githooks and integrations",
          sorted(dirs) == sorted([VAULT + "/_bin/", VAULT + "/githooks/", VAULT + "/integrations/"]), dirs)

    broken = cmd("retrieve_BROKEN.py")
    foreign_missing = "/usr/bin/python3 /opt/other/tool_gone.py"
    elsewhere = "/usr/bin/python3 /old/path/Brain/_bin/retired_elsewhere.py"
    current = {
        "UserPromptSubmit": [{"hooks": [{"type": "command", "command": broken, "timeout": 8}]}],
        "Stop": [{"hooks": [
            {"type": "command", "command": foreign_missing},
            {"type": "command", "command": "/usr/bin/python3 /old/path/Brain/_bin/gate_memory.py",
             "timeout": 10},
            {"type": "command", "command": elsewhere},
            {"type": "command", "command": cmd("vault_sync.py", "--hook"), "async": True},
            {"type": "command", "command": cmd("still_here.py")}]}],
        "SessionStart": can["SessionStart"],
    }
    paths = D.brain_hook_paths(current, dirs)
    check("only paths under the vault's Brain dirs are candidates to check on disk",
          sorted(paths) == sorted([V + "/retrieve_BROKEN.py", V + "/vault_sync.py", V + "/still_here.py",
                                   V + "/compass.py"]), paths)

    missing = {V + "/retrieve_BROKEN.py"}
    before = repr(current)
    merged, changes = D.reconcile_hooks(can, current, dirs, missing)
    commands = [h["command"] for groups in merged.values() for g in groups for h in g["hooks"]]
    check("a hook running a Brain script that no longer exists is removed", broken not in commands, commands)
    check("its event is dropped once it has no hooks left", "UserPromptSubmit" not in merged, merged)
    check("the removal is reported as a change naming event and script",
          ("removed", "UserPromptSubmit", "retrieve_BROKEN.py") in [(c.kind, c.event, c.identity) for c in changes]
          and any("retrieve_BROKEN.py" in c.text and "does not exist" in c.text for c in changes),
          [(c.kind, c.event, c.identity, c.text) for c in changes])
    check("a missing script outside the vault is never touched", foreign_missing in commands, commands)
    check("a Brain-looking script from another vault directory is never removed", elsewhere in commands, commands)
    check("a Brain script that exists but canonical does not list is kept", cmd("still_here.py") in commands)
    check("a canonical hook from a wrong vault directory is rewritten to the canonical path",
          cmd("gate_memory.py") in commands
          and "/usr/bin/python3 /old/path/Brain/_bin/gate_memory.py" not in commands, commands)
    check("reconcile does not mutate its inputs", repr(current) == before)

    again, changes2 = D.reconcile_hooks(can, merged, dirs, set())
    check("reconciling the result again changes nothing", changes2 == [] and again == merged, changes2)

    gone = {V + "/compass.py"}
    merged, changes = D.reconcile_hooks(can, can, dirs, gone)
    check("a canonical hook whose script is missing is left for the missing-path finding, not churned",
          changes == [] and merged == can, changes)

    sneaky = "/usr/bin/python3 %s/_bin/../../elsewhere/x.py" % VAULT
    cur = {"Stop": [{"hooks": [{"type": "command", "command": sneaky}]}]}
    check("a path that climbs out of the vault with .. is not Brain's",
          D.brain_hook_paths(cur, dirs) == []
          and sneaky in [h["command"] for g in D.reconcile_hooks({}, cur, dirs, {sneaky.split()[1]})[0]["Stop"]
                         for h in g["hooks"]])

    cli = "%s/integrations/cli/brain recall" % VAULT
    cur = {"Stop": [{"hooks": [{"type": "command", "command": cli},
                               {"type": "command", "command": "say hi"}]}]}
    merged, changes = D.reconcile_hooks({}, cur, dirs, {VAULT + "/integrations/cli/brain"})
    check("a missing Brain integration command is stale too, and its group keeps the rest",
          merged == {"Stop": [{"hooks": [{"type": "command", "command": "say hi"}]}]}
          and [c.kind for c in changes] == ["removed"], (merged, changes))


def test_localize(D):
    print("\n== localize_hooks and command paths ==")
    loc = D.localize_hooks(canonical(), vault="/home/x/Vault", home="/home/x")
    cmds = [h["command"] for ev in loc.values() for g in ev for h in g["hooks"]]
    check("the original vault path is rewritten to this machine's vault",
          all("/home/x/Vault/_bin/" in c for c in cmds), cmds)
    check("nothing from the original home survives",
          not any("/home/brain-origin" in c for c in cmds), cmds)
    same = D.localize_hooks(canonical(), vault="/home/brain-origin/Brain", home="/home/brain-origin")
    check("on the original machine localize is the identity", same == canonical())
    paths = D.hook_command_paths(canonical())
    check("command paths lists interpreter and scripts once each, in order",
          paths == [PY, V + "/compass.py", V + "/gate_memory.py", V + "/vault_sync.py"], paths)


def test_schedule(D):
    print("\n== parse_days, routine_due ==")
    check("`*` is every day", D.parse_days("*") == set(range(1, 8)))
    check("ranges and lists", D.parse_days("1-3,6") == {1, 2, 3, 6})
    mon_0700 = dt.datetime(2026, 9, 14, 7, 0)            # a Monday
    r = {"id": "x", "machine": "*", "time": "06:00", "days": "*", "type": "agent",
         "enabled": True}
    check("an enabled agent routine past its time is due",
          D.routine_due(r, None, mon_0700, "box") == (True, ""))
    check("not before its time",
          D.routine_due(dict(r, time="08:00"), None, mon_0700, "box") == (False, "not yet (08:00)"))
    check("not twice the same day",
          D.routine_due(r, "2026-09-14", mon_0700, "box") == (False, "already ran today"))
    check("again the next day",
          D.routine_due(r, "2026-09-13", mon_0700, "box")[0] is True)
    check("not on an unscheduled weekday",
          D.routine_due(dict(r, days="2-5"), None, mon_0700, "box") == (False, "not scheduled today"))
    check("disabled is never due",
          D.routine_due(dict(r, enabled=False), None, mon_0700, "box") == (False, "disabled"))
    check("another machine's routine is never due here",
          D.routine_due(dict(r, machine="other"), None, mon_0700, "box") == (False, "belongs to other"))
    check("a manual-only routine is never due",
          D.routine_due(dict(r, time="--"), None, mon_0700, "box") == (False, "manual only (no schedule)"))
    check("shell rows are due too",
          D.routine_due(dict(r, type="shell"), None, mon_0700, "box")[0] is True)
    check("claude-app rows are not run by this runner",
          D.routine_due(dict(r, type="claude-app"), None, mon_0700, "box")
          == (False, "type 'claude-app' is not run by this runner"))


def F(D, key, sev="fail", summary=None):
    return D.Finding(key=key, severity=sev, summary=summary or ("problem " + key))


def test_decide(D):
    print("\n== decide (alert de-duplication) ==")
    t0 = dt.datetime(2026, 9, 15, 10, 0)
    st, actions = D.decide(None, [], t0)
    check("healthy first run says nothing", actions == [], actions)

    st1, actions = D.decide(st, [F(D, "a")], t0)
    check("a new problem notifies a change", [a.kind for a in actions] == ["notify-change"], actions)
    check("the change names the problem", "problem a" in actions[0].body, actions[0].body)

    st2, actions = D.decide(st1, [F(D, "a", summary="problem a, reworded")], t0 + dt.timedelta(minutes=15))
    check("the same problem fifteen minutes later stays quiet", actions == [], actions)

    st3, actions = D.decide(st2, [F(D, "a")], t0 + dt.timedelta(hours=25))
    check("a problem still open a day later sends a digest",
          [a.kind for a in actions] == ["notify-digest"], actions)
    _, actions = D.decide(st3, [F(D, "a")], t0 + dt.timedelta(hours=26))
    check("and the digest does not repeat an hour later", actions == [], actions)

    _, actions = D.decide(st2, [F(D, "a"), F(D, "b")], t0 + dt.timedelta(minutes=30))
    check("a second problem notifies again",
          [a.kind for a in actions] == ["notify-change"] and "problem b" in actions[0].body, actions)

    _, actions = D.decide(st2, [], t0 + dt.timedelta(minutes=30))
    check("a resolved problem is announced once",
          [a.kind for a in actions] == ["notify-change"] and "resolved" in actions[0].body.lower(),
          actions)

    _, actions = D.decide(st2, [F(D, "a", sev="warn")], t0 + dt.timedelta(minutes=30))
    check("a severity change of the same problem is quiet when it softens", actions == [], actions)
    stw, _ = D.decide(None, [F(D, "w", sev="warn")], t0)
    _, actions = D.decide(stw, [F(D, "w", sev="fail")], t0 + dt.timedelta(minutes=15))
    check("but notifies when it escalates to fail",
          [a.kind for a in actions] == ["notify-change"], actions)

    check("the first_seen time of an open problem is kept across runs",
          st2["active"]["a"]["first_seen"] == st1["active"]["a"]["first_seen"], st2)


def test_report_and_rules(D):
    print("\n== Report and finding rules ==")
    check("no findings: exit 0", D.Report([]).exit_code == 0)
    check("only warnings: exit 1", D.Report([F(D, "w", "warn")]).exit_code == 1)
    check("any failure: exit 2", D.Report([F(D, "w", "warn"), F(D, "f")]).exit_code == 2)
    check("healthy means no failures", D.Report([F(D, "w", "warn")]).healthy
          and not D.Report([F(D, "f")]).healthy)

    fs = D.interpreter_findings([D.InterpreterStatus("/usr/bin/python3", False, "exit 69"),
                                 D.InterpreterStatus("/opt/homebrew/bin/python3", True, "3.14")])
    check("a broken hook interpreter with a working fallback is one failure",
          [f.severity for f in fs] == ["fail"] and "/usr/bin/python3" in fs[0].summary, fs)
    fs = D.interpreter_findings([D.InterpreterStatus("/usr/bin/python3", False, "exit 69"),
                                 D.InterpreterStatus("/opt/homebrew/bin/python3", False, "missing")])
    check("no working interpreter at all adds a second failure",
          len(fs) == 2 and all(f.severity == "fail" for f in fs), fs)
    check("a healthy hook interpreter raises nothing",
          D.interpreter_findings([D.InterpreterStatus("/usr/bin/python3", True, "3.9")]) == [])

    fs = D.launchd_findings("com.x.job", installed=False, loaded=False, last_ok=True, detail="")
    check("an uninstalled job is a repairable failure",
          len(fs) == 1 and fs[0].severity == "fail" and fs[0].repairable, fs)
    fs = D.launchd_findings("com.x.job", installed=True, loaded=False, last_ok=True, detail="")
    check("an installed but unloaded job is a repairable failure",
          len(fs) == 1 and fs[0].repairable and "not loaded" in fs[0].summary, fs)
    fs = D.launchd_findings("com.x.job", installed=True, loaded=True, last_ok=False, detail="exit 1")
    check("a loaded job whose last run failed is a warning, not repairable",
          len(fs) == 1 and fs[0].severity == "warn" and not fs[0].repairable, fs)
    check("a healthy job raises nothing",
          D.launchd_findings("com.x.job", installed=True, loaded=True, last_ok=True, detail="") == [])

    check("the guardian's own launchd label is a domain constant",
          getattr(D, "GUARDIAN_LABEL", None) == "com.secondbrain.guardian", getattr(D, "GUARDIAN_LABEL", None))
    check("the guardian's own systemd unit is not judged by its exit status either",
          D.launchd_findings("second-brain-guardian", True, True, False, "Result=exit-code") == [],
          D.launchd_findings("second-brain-guardian", True, True, False, "Result=exit-code"))
    own = getattr(D, "GUARDIAN_LABEL", "com.secondbrain.guardian")
    fs = D.launchd_findings(own, installed=True, loaded=True, last_ok=False, detail="LastExitStatus=256")
    check("the guardian never judges its own job by its last exit status (findings used to set it)",
          fs == [], fs)
    fs = D.launchd_findings(own, installed=True, loaded=False, last_ok=False, detail="LastExitStatus=256")
    check("but its own job not being loaded is still a repairable failure",
          [(f.key, f.severity, f.repairable) for f in fs] == [("launchd:" + own, "fail", True)], fs)
    fs = D.launchd_findings("com.secondbrain.sync", installed=True, loaded=True, last_ok=False,
                            detail="LastExitStatus=256")
    check("any other job's failed last run is still a warning",
          [f.key for f in fs] == ["launchd-exit:com.secondbrain.sync"], fs)

    rx = getattr(D, "repair_exit_code", None)
    check("the scheduled repair's exit code is a domain rule", callable(rx), rx)
    if callable(rx):
        check("a repair that completed exits 0 whatever it found", rx([]) == 0)
        check("a repair whose own work errored exits 1", rx(["could not load com.x"]) == 1)

    fs = D.vault_findings(D.SyncStatus(pending=3, unpushed_age_s=7 * 3600, remote_ok=True),
                          index_age_s=60)
    check("commits unpushed for hours are a warning",
          [f.key for f in fs] == ["vault:unpushed"] and fs[0].severity == "warn", fs)
    fs = D.vault_findings(D.SyncStatus(pending=0, unpushed_age_s=None, remote_ok=False),
                          index_age_s=3 * 86400)
    check("no upstream and a stale index are two warnings",
          sorted(f.key for f in fs) == ["vault:index-stale", "vault:no-upstream"], fs)
    check("a fresh, pushed vault raises nothing",
          D.vault_findings(D.SyncStatus(pending=2, unpushed_age_s=120, remote_ok=True), 30) == [])


def test_agents_and_drift(D):
    print("\n== agent wiring findings and plist drift ==")
    w = D.AgentWiring(name="claude-code", unreadable=None,
                      changes=[("hooks:Stop:gate_memory.py", "hook Stop gate_memory.py: missing")],
                      missing_paths=["/v/_bin/x.py"])
    fs = D.agent_findings(w)
    check("each wiring change is a repairable failure keyed by agent",
          [f.key for f in fs] == ["agent:claude-code:hooks:Stop:gate_memory.py",
                                  "agent:claude-code:path:/v/_bin/x.py"]
          and fs[0].severity == "fail" and fs[0].repairable, fs)
    check("the change text is the summary", fs[0].summary.endswith("gate_memory.py: missing"), fs)
    check("a missing command path is a failure repair cannot fix",
          fs[1].severity == "fail" and not fs[1].repairable and "/v/_bin/x.py" in fs[1].summary, fs)
    fs = D.agent_findings(D.AgentWiring("claude-code", "settings.json: Expecting value", [], []))
    check("unreadable wiring is one non-repairable failure",
          [(f.key, f.severity, f.repairable) for f in fs]
          == [("agent:claude-code:unreadable", "fail", False)], fs)
    check("healthy wiring raises nothing", D.agent_findings(D.AgentWiring("claude-code", None, [], [])) == [])
    r = D.AgentRepair("claude-code")
    check("an agent repair result starts empty",
          r.changes == [] and r.errors == [] and r.backup is None, r)

    fs = D.launchd_findings("com.x.job", installed=True, loaded=True, last_ok=True, detail="",
                            drifted=True)
    check("an installed plist that differs from the vault template is a repairable warning",
          [(f.key, f.severity, f.repairable) for f in fs] == [("launchd-drift:com.x.job", "warn", True)]
          and "template" in fs[0].summary, fs)
    fs = D.launchd_findings("com.x.job", installed=True, loaded=True, last_ok=False, detail="x",
                            drifted=True)
    check("drift and a failed last run are reported together",
          sorted(f.key for f in fs) == ["launchd-drift:com.x.job", "launchd-exit:com.x.job"], fs)
    fs = D.launchd_findings("com.x.job", installed=False, loaded=False, last_ok=True, detail="",
                            drifted=True)
    check("an uninstalled job is reported as uninstalled only", [f.key for f in fs] == ["launchd:com.x.job"], fs)


def test_git_hooks(D):
    print("\n== vault git hooks ==")
    def status(path="githooks", pre=(True, True), post=(True, True)):
        return D.GitHooksStatus(hooks_path=path, files=[D.GitHookFile("pre-commit", *pre),
                                                         D.GitHookFile("post-commit", *post)])

    check("core.hooksPath = githooks with executable hooks raises nothing",
          D.git_hooks_findings(status()) == [] and D.git_hooks_repairs(status()) == [])
    for value in (None, "", ".git/hooks", "/elsewhere/githooks"):
        fs = D.git_hooks_findings(status(path=value))
        check("core.hooksPath %r is a repairable failure" % (value,),
              [(f.key, f.severity, f.repairable) for f in fs] == [("githooks:hooks-path", "fail", True)]
              and "core.hooksPath" in fs[0].summary, fs)
    check("repair sets core.hooksPath when it is not githooks",
          D.git_hooks_repairs(status(path=None)) == [("set-hooks-path", None)],
          D.git_hooks_repairs(status(path=None)))

    fs = D.git_hooks_findings(status(pre=(True, False)))
    check("a hook file that is not executable is a repairable failure",
          [(f.key, f.severity, f.repairable) for f in fs] == [("githooks:mode:pre-commit", "fail", True)], fs)
    check("repair makes it executable",
          D.git_hooks_repairs(status(pre=(True, False))) == [("chmod", "pre-commit")])

    fs = D.git_hooks_findings(status(post=(False, False)))
    check("a missing hook file is a failure repair cannot fix, pointing at brain_watch.py generate",
          [(f.key, f.severity, f.repairable) for f in fs] == [("githooks:missing:post-commit", "fail", False)]
          and "brain_watch.py generate" in fs[0].summary, fs)
    check("and repair does not try to chmod it", D.git_hooks_repairs(status(post=(False, False))) == [])

    both = status(path=None, pre=(True, False))
    check("problems are reported and repaired together",
          sorted(f.key for f in D.git_hooks_findings(both)) == ["githooks:hooks-path", "githooks:mode:pre-commit"]
          and D.git_hooks_repairs(both) == [("set-hooks-path", None), ("chmod", "pre-commit")])


def test_repair_alert(D):
    print("\n== repair alert ==")
    check("a repair that changed nothing has nothing to say", D.repair_alert([], ["/s.json.bak"]) is None)
    changes = ["hook Stop gate_memory.py: missing", "loaded launchd job com.x.sync"]
    a = D.repair_alert(changes, ["/c/settings.json.bak-guardian-1"])
    check("a repair that changed something is one notify-repair action", a and a.kind == "notify-repair", a)
    check("its subject counts the repaired items",
          a and a.subject == "Brain guardian: repaired 2 item(s)", a and a.subject)
    check("its body lists every change exactly", a and all(c in a.body.splitlines()[i]
                                                            for i, c in enumerate(changes)), a and a.body)
    check("and every backup path", a and "/c/settings.json.bak-guardian-1" in a.body, a and a.body)
    check("with no backups the body says nothing about backups",
          "ackup" not in D.repair_alert(changes, []).body)

    change = D.AlertAction("notify-change", "Brain guardian: 1 resolved", "RESOLVED  hook gone")
    merged = D.merge_alerts(a, [change])
    check("a repair and a decided change in the same run go out as one message",
          len(merged) == 1 and merged[0].kind == "notify-repair", merged)
    check("that message's subject carries both",
          merged and merged[0].subject == "Brain guardian: repaired 2 item(s); 1 resolved", merged)
    check("and its body both", merged and changes[0] in merged[0].body and "RESOLVED  hook gone" in merged[0].body)
    check("without a repair the decided actions pass through unchanged", D.merge_alerts(None, [change]) == [change])
    check("a repair alone passes through", D.merge_alerts(a, []) == [a])
    check("nothing to say is nothing", D.merge_alerts(None, []) == [])


def test_agent_conflicts(D):
    print("\n== agent conflicts ==")
    check("an agent's wiring starts with no conflicts", D.AgentWiring("x").conflicts == [])
    w = D.AgentWiring("claude-code", None, [], [], conflicts=[("plugin:skills/x", "skills/x changed on both sides")])
    fs = D.agent_findings(w)
    check("a conflict is a failure repair will not resolve, keyed by agent",
          [(f.key, f.severity, f.repairable) for f in fs] == [("agent:claude-code:conflict:plugin:skills/x", "fail", False)]
          and "both sides" in fs[0].summary, fs)


def test_token_pool(D):
    print("\n== routine token pool ==")
    now = dt.datetime(2026, 9, 15, 13, 0)
    renew = "claude setup-token (copy the token it prints), then: RESTORE-CMD"

    def tok(label="routines-1", **kw):
        base = dict(label=label, account="routines", kp_ref="kp://Brain/apis/claude-code-oauth-%s" % label,
                    status="healthy", expires="2027-09-15", renew=renew, restore="RESTORE-CMD")
        base.update(kw)
        return D.TokenHealth(**base)

    def pool(*tokens, error=None):
        return D.TokenPool(list(tokens), error)

    check("a fresh healthy token is no finding", D.token_pool_findings(pool(tok()), now) == [])
    check("an empty pool with no error is no finding", D.token_pool_findings(pool(), now) == [])

    fs = D.token_pool_findings(pool(tok(status="dead", last_kind="auth_invalid", last_at="2026-09-15T12:00:00")), now)
    keys = [(f.key, f.severity, f.repairable) for f in fs]
    check("a refused token is a failure repair cannot fix, keyed by label",
          ("routine-auth:token:routines-1", "fail", False) in keys, keys)
    token_f = [f for f in fs if f.key == "routine-auth:token:routines-1"]
    check("its summary names the account and the renewal",
          token_f and "routines" in token_f[0].summary and renew in token_f[0].summary, token_f)

    fs = D.token_pool_findings(pool(tok(status="dead", last_kind="token_malformed",
                                        detail="contains whitespace (2 word(s), 110 characters)")), now)
    token_f = [f for f in fs if f.key == "routine-auth:token:routines-1"]
    check("a malformed stored value is a failure naming the shape and the re-store command",
          token_f and token_f[0].severity == "fail" and "whitespace" in token_f[0].summary
          and "RESTORE-CMD" in token_f[0].summary and "kp://Brain/apis/claude-code-oauth-routines-1" in token_f[0].summary,
          token_f)

    fs = D.token_pool_findings(pool(tok(status="limited-until", until="2026-09-15T16:00:00", last_kind="usage_limit"),
                                    tok("routines-2")), now)
    check("a token resting until later is a warning with the time",
          [(f.key, f.severity) for f in fs] == [("routine-auth:limited:routines-1", "warn")]
          and "16:00" in fs[0].summary and "usage_limit" in fs[0].summary, fs)
    check("a token whose rest has ended is no finding",
          D.token_pool_findings(pool(tok(status="limited-until", until="2026-09-15T12:00:00")), now) == [])

    fs = D.token_pool_findings(pool(tok(expires="2026-10-15")), now)
    check("30 days before expiry is a warning with the renewal",
          [(f.key, f.severity) for f in fs] == [("routine-auth:expiry:routines-1", "warn")]
          and "2026-10-15" in fs[0].summary and "30" in fs[0].summary and renew in fs[0].summary, fs)
    check("31 days before is nothing", D.token_pool_findings(pool(tok(expires="2026-10-16")), now) == [])
    check("warn_days is configurable", len(D.token_pool_findings(pool(tok(expires="2026-12-01")), now, warn_days=90)) == 1)
    fs = D.token_pool_findings(pool(tok(expires="2026-09-14")), now)
    check("an expired token is a failure", [(f.key, f.severity) for f in fs] == [("routine-auth:expiry:routines-1", "fail")]
          and "expired" in fs[0].summary, fs)

    fs = D.token_pool_findings(pool(error="token 1 has unknown key(s) token"), now)
    check("an invalid pool config is one failure naming the file",
          [(f.key, f.severity) for f in fs] == [("routine-auth:config", "fail")]
          and "routine-tokens.json" in fs[0].summary and "unknown key" in fs[0].summary, fs)

    fs = D.token_pool_findings(pool(tok(status="dead", last_kind="auth_invalid"),
                                    tok("routines-2", status="limited-until", until="2026-09-15T18:00:00")), now)
    check("no usable token at all is its own failure",
          ("routine-auth:pool", "fail") in [(f.key, f.severity) for f in fs], [(f.key, f.severity) for f in fs])
    fs = D.token_pool_findings(pool(tok(status="dead", last_kind="auth_invalid"), tok("routines-2")), now)
    check("one usable token left is not", "routine-auth:pool" not in [f.key for f in fs], [f.key for f in fs])


def test_duplicates_and_degraded(D):
    print("\n== routine frontmatter ==")
    text = ("---\nid: routine-x\nroutine_id: x\napp_task: daily-digest\n"
            "needs_bridge: [example-bridge, claude-in-chrome, vault-write]\n---\n\nbody\napp_task: not-this\n")
    m = D.routine_meta(text)
    check("app_task and needs_bridge come from the frontmatter only",
          m == {"app_task": "daily-digest", "needs_bridge": ["example-bridge", "claude-in-chrome", "vault-write"]}, m)
    check("no frontmatter is no metadata", D.routine_meta("just a prompt") == {"app_task": None, "needs_bridge": []})
    check("needs_bridge: none is an empty list",
          D.routine_meta("---\nneeds_bridge: none\n---\n")["needs_bridge"] == [])

    print("\n== a routine enabled twice ==")
    rows = [{"id": "daily-digest-agent", "enabled": True, "app_task": "daily-digest"},
            {"id": "example-routine-b-agent", "enabled": False, "app_task": "example-routine-b"},
            {"id": "weekly-report-agent", "enabled": True, "app_task": "weekly-report"},
            {"id": "no-app-agent", "enabled": True, "app_task": None}]
    desktop = [("daily-digest", "acct-1111"), ("example-routine-b", "acct-1111"),
               ("daily-digest", "acct-2222")]
    fs = D.duplicate_task_findings(desktop, rows)
    check("an agent row enabled while its Claude app task is enabled is a failure repair never touches",
          [(f.key, f.severity, f.repairable) for f in fs] == [("duplicate:daily-digest-agent", "fail", False)], fs)
    check("naming the app task, every account it is enabled under, and the manual step",
          fs and "daily-digest" in fs[0].summary and "acct-1111" in fs[0].summary and "acct-2222" in fs[0].summary
          and "by hand" in fs[0].summary, fs)
    check("nothing is enabled twice when either side is off",
          D.duplicate_task_findings([("weekly-report", "a")], [dict(rows[2], enabled=False)]) == []
          and D.duplicate_task_findings([], rows) == [])

    print("\n== routines degraded by a stale browser bridge ==")
    rows = [{"id": "example-routine-b-agent", "enabled": True, "needs_bridge": ["example-bridge", "claude-in-chrome"]},
            {"id": "daily-digest-agent", "enabled": True, "needs_bridge": ["email", "skill-defined"]},
            {"id": "off-agent", "enabled": False, "needs_bridge": ["browser"]}]
    fs = D.degraded_routine_findings(rows, bridge_stale=True)
    check("an enabled routine that needs the browser is a warning while the bridge is stale",
          [(f.key, f.severity) for f in fs] == [("degraded:example-routine-b-agent", "warn")]
          and "browser" in fs[0].summary and "restart" in fs[0].summary, fs)
    check("a healthy bridge degrades nothing", D.degraded_routine_findings(rows, bridge_stale=False) == [])
    check("degraded ids are listed for the status report",
          D.degraded_routine_ids(rows, bridge_stale=True) == ["example-routine-b-agent"])


def test_routine_permissions(D):
    print("\n== routine permissions ==")
    rows = [{"id": "open-agent", "enabled": False,
             "permission_problem": "--allowedTools grants bare Bash (unrestricted shell)"},
            {"id": "narrow-agent", "enabled": True, "permission_problem": None}]
    fs = D.routine_permission_findings(rows)
    check("a routine whose agent_args grant unrestricted permissions is a failure repair never touches, even disabled",
          [(f.key, f.severity, f.repairable) for f in fs] == [("routine-permissions:open-agent", "fail", False)], fs)
    check("naming the routine, its agent_args and the problem",
          fs and "open-agent" in fs[0].summary and "agent_args" in fs[0].summary and "bare Bash" in fs[0].summary, fs)
    check("narrow permissions are no finding", D.routine_permission_findings(rows[1:]) == [])


HOOK_EVENT = {"session-start": "SessionStart", "prompt-submit": "UserPromptSubmit", "stop-memory-gate": "Stop",
              "pre-write-gate": "PreToolUse", "worktree-seed": "WorktreeCreate", "sync": "Stop"}


def test_hook_liveness(D):
    print("\n== hook liveness ==")
    need = ("Heartbeat", "SessionTranscript", "HookEventSpec", "LivenessConfig", "hook_liveness",
            "heartbeat_from_record", "session_sid", "PROBE_SESSION_ID")
    missing = [n for n in need if not hasattr(D, n)]
    check("the liveness rules are in the domain", missing == [], missing)
    if missing:
        return
    specs = [D.HookEventSpec("session-start", "SessionStart", "compass.py", "session"),
             D.HookEventSpec("prompt-submit", "UserPromptSubmit", "retrieve.py", "session"),
             D.HookEventSpec("stop-memory-gate", "Stop", "gate_memory.py", "session"),
             D.HookEventSpec("pre-write-gate", "PreToolUse", "gate_write.py", "regular"),
             D.HookEventSpec("worktree-seed", "WorktreeCreate", "seed_worktree.py", "conditional")]
    now = 1_800_000_000.0
    since = now - 30 * 86400          # liveness has run for longer than the silent window
    young = now - 86400               # liveness started yesterday: no silent-window judgement yet

    def tr(sid, started_ago, mtime_ago=60, project="-Users-me-code-app"):
        return D.SessionTranscript(sid, project, now - started_ago, now - mtime_ago)

    def hb(sid, event, ago, status="ok", exc=""):
        return D.Heartbeat(now - ago, event, sid, status, exc, 12, HOOK_EVENT[event])

    def ks(rep):
        return sorted((f.key, f.severity) for f in rep.findings)

    turn = [hb("aaaa1111", "session-start", 590), hb("aaaa1111", "prompt-submit", 500),
            hb("aaaa1111", "pre-write-gate", 450), hb("aaaa1111", "stop-memory-gate", 400)]
    rep = D.hook_liveness([tr("aaaa1111", 600)], turn, specs, now, since)
    check("a session whose hooks fired is healthy, and counted", rep.findings == [] and rep.checked == 1,
          (rep.findings, rep.checked))
    check("the last heartbeat of each event is kept for status",
          rep.last_by_event.get("prompt-submit") is not None and rep.last_by_event["prompt-submit"].ts == now - 500,
          rep.last_by_event)

    rep = D.hook_liveness([tr("aaaa1111", 600)], [], specs, now, since)
    check("an active session with no heartbeat at all is hooks:not-firing, a failure",
          ks(rep) == [("hooks:not-firing", "fail")], rep.findings)
    check("naming how many sessions and one of them",
          rep.findings and "1 " in rep.findings[0].summary and "aaaa1111" in rep.findings[0].summary, rep.findings)
    check("a session inside its first two minutes is not judged yet",
          D.hook_liveness([tr("aaaa1111", 30, 5)], [], specs, now, young).findings == [])
    check("a session idle for longer than the window is not checked",
          D.hook_liveness([tr("aaaa1111", 9000, 7200)], [], specs, now, young).checked == 0)
    check("a session that started before liveness began is not judged",
          D.hook_liveness([tr("aaaa1111", 600)], [], specs, now, now - 300).findings == [])
    check("no liveness epoch yet means no judgement",
          D.hook_liveness([tr("aaaa1111", 600)], [], specs, now, None).findings == [])
    for label, t in (("the macOS temporary directory", tr("aaaa1111", 600, project="-private-var-folders-xy-abc-T-tmpq1")),
                     ("/var/folders", tr("aaaa1111", 600, project="-var-folders-xy-abc-T-tmpq1")),
                     ("/tmp", tr("aaaa1111", 600, project="-private-tmp-scratch")),
                     ("the guardian's own probe", tr(D.session_sid(D.PROBE_SESSION_ID), 600))):
        check("a session in %s is ignored by rule" % label, D.hook_liveness([t], [], specs, now, young).checked == 0)
    check("the short session id is the transcript uuid's first eight hex digits",
          D.session_sid("3ac18522-ed92-4c1a-9d0e-000000000001") == "3ac18522")

    partial = [hb("aaaa1111", "session-start", 590), hb("aaaa1111", "stop-memory-gate", 400)]
    rep = D.hook_liveness([tr("aaaa1111", 600)], partial, specs, now, young)
    check("a session that finished a turn without a prompt-submit heartbeat is hooks:silent:prompt-submit, a warning",
          ks(rep) == [("hooks:silent:prompt-submit", "warn")], rep.findings)
    rep = D.hook_liveness([tr("aaaa1111", 600)], [hb("aaaa1111", "session-start", 590)], specs, now, young)
    check("a session that has not finished a turn yet is not held to the per-turn hooks", rep.findings == [], rep.findings)
    rep = D.hook_liveness([tr("aaaa1111", 600)], [hb("aaaa1111", "session-start", 590),
                                                  hb("aaaa1111", "stop-memory-gate", 30)], specs, now, young)
    check("nor is one whose first turn ended moments ago (async hooks may still be running)",
          rep.findings == [], rep.findings)

    def runs(statuses):
        return [hb("bbbb2222", "prompt-submit", 100 + i * 10, s, "ValueError" if s == "error" else "")
                for i, s in enumerate(statuses)]

    rep = D.hook_liveness([], runs(["error", "ok", "error", "error", "ok"]), specs, now, since)
    check("three errors in an event's last five runs is hooks:failing:<event>, a failure",
          ks(rep) == [("hooks:failing:prompt-submit", "fail")], rep.findings)
    check("naming the count and the exception",
          rep.findings and "3 of its last 5" in rep.findings[0].summary and "ValueError" in rep.findings[0].summary,
          rep.findings)
    check("two errors in five is not", D.hook_liveness([], runs(["error", "ok", "ok", "error", "ok"]), specs, now, since).findings == [])
    check("errors older than the last five clean runs are forgiven",
          D.hook_liveness([], runs(["ok"] * 5 + ["error"] * 5), specs, now, since).findings == [])
    check("blocked and off are not errors",
          D.hook_liveness([], runs(["blocked", "off", "blocked", "off", "ok"]), specs, now, since).findings == [])

    in_use = [tr("cccc3333", 3 * 86400, 2 * 86400)]
    recent = [hb("cccc3333", "session-start", 2 * 86400), hb("cccc3333", "prompt-submit", 2 * 86400 - 10),
              hb("cccc3333", "stop-memory-gate", 2 * 86400 - 20)]
    rep = D.hook_liveness(in_use, recent, specs, now, since)
    check("a regular hook with no heartbeat for the whole silent window while hooks fired is hooks:silent:<event>, a warning",
          ks(rep) == [("hooks:silent:pre-write-gate", "warn")], rep.findings)
    check("a conditional hook (worktree-seed) is never called silent", not any("worktree-seed" in f.key for f in rep.findings))
    check("not before liveness has run for a whole silent window",
          D.hook_liveness(in_use, recent, specs, now, now - 4 * 86400).findings == [])
    check("nor when Claude Code was not used at all", D.hook_liveness([], recent, specs, now, since).findings == [])
    check("the cheap mode (the file watch) skips the silent window",
          D.hook_liveness(in_use, recent, specs, now, since, include_silent=False).findings == [])

    rec = {"ts": 1800000000.5, "event": "prompt-submit", "sid": "aaaa1111", "status": "ok", "exit": 0, "exc": "",
           "ms": 41, "hook_event": "UserPromptSubmit"}
    h = D.heartbeat_from_record(rec)
    check("a heartbeat record becomes a Heartbeat",
          h == D.Heartbeat(1800000000.5, "prompt-submit", "aaaa1111", "ok", "", 41, "UserPromptSubmit"), h)
    check("a record without an event, a sid or a numeric ts is dropped",
          all(D.heartbeat_from_record(dict(rec, **bad)) is None for bad in ({"event": ""}, {"sid": None}, {"ts": "yesterday"})))
    check("anything that is not a record is dropped", D.heartbeat_from_record(["x"]) is None)


def test_hook_probe(D):
    print("\n== synthetic hook probe ==")
    need = ("ProbeCase", "ProbeResult", "probe_cases", "probe_verdict", "probe_findings", "PROBE_SESSION_ID",
            "PROBE_MAX_TIMEOUT", "HookEventSpec")
    missing = [n for n in need if not hasattr(D, n)]
    check("the probe rules are in the domain", missing == [], missing)
    if missing:
        return
    specs = [D.HookEventSpec("session-start", "SessionStart", "compass.py", "session"),
             D.HookEventSpec("skills-catalogue", "SessionStart", "skills_index.py", "session"),
             D.HookEventSpec("pre-write-gate", "PreToolUse", "gate_write.py", "regular"),
             D.HookEventSpec("sync", "Stop", "vault_sync.py --hook", "session")]
    hooks = {"SessionStart": [{"matcher": "startup|resume", "hooks": [
                 {"type": "command", "command": "/usr/bin/python3 /v/_bin/compass.py", "timeout": 8},
                 {"type": "command", "command": "/usr/bin/python3 /v/_bin/skills_index.py", "async": True}]}],
             "PreToolUse": [{"matcher": "Bash|Edit|Write|NotebookEdit", "hooks": [
                 {"type": "command", "command": "/usr/bin/python3 /v/_bin/gate_write.py", "timeout": 5}]}],
             "Stop": [{"hooks": [{"type": "command", "command": "/usr/bin/python3 /v/_bin/vault_sync.py --hook"}]}],
             "Other": [{"hooks": [{"type": "command", "command": "/usr/bin/python3 /elsewhere/not_brain.py"}]}]}
    cases = D.probe_cases(hooks, specs, "/scratch/work")
    got = [(c.event_id, c.hook_event, c.command, c.timeout) for c in cases]
    check("each canonical Brain hook is one probe case, with its event id, command and timeout (capped)",
          got == [("session-start", "SessionStart", "/usr/bin/python3 /v/_bin/compass.py", 8),
                  ("skills-catalogue", "SessionStart", "/usr/bin/python3 /v/_bin/skills_index.py", D.PROBE_MAX_TIMEOUT),
                  ("pre-write-gate", "PreToolUse", "/usr/bin/python3 /v/_bin/gate_write.py", 5),
                  ("sync", "Stop", "/usr/bin/python3 /v/_bin/vault_sync.py --hook", D.PROBE_MAX_TIMEOUT)], got)
    check("a hook that is not in the registry is not probed", not any("not_brain" in c.command for c in cases))
    if len(cases) != 4:
        return
    ss, pre, stop = cases[0].stdin, cases[2].stdin, cases[3].stdin
    check("the canned stdin is Claude Code's shape for that event, under the probe's own session id",
          ss.get("session_id") == D.PROBE_SESSION_ID and ss.get("hook_event_name") == "SessionStart"
          and ss.get("cwd") == "/scratch/work" and ss.get("source") == "startup", ss)
    check("a tool-use probe writes a harmless file inside the scratch directory",
          pre.get("tool_name") == "Write" and (pre.get("tool_input") or {}).get("file_path", "").startswith("/scratch/work/"), pre)
    check("a Stop probe says no stop hook is active yet",
          stop.get("hook_event_name") == "Stop" and stop.get("stop_hook_active") is False, stop)

    R, v = D.ProbeResult, D.probe_verdict
    ctx = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "# Brain"}}
    check("exit 0 with the SessionStart context is a pass",
          v(cases[0], R("session-start", 0, '{"hookSpecificOutput": {}}', "", parsed=ctx)) == "")
    r = v(cases[0], R("session-start", 0, "{}", "", parsed={}))
    check("session-start without additionalContext fails, saying so", "additionalContext" in r, r)
    r = v(cases[0], R("session-start", 1, "", 'Traceback (most recent call last):\n  File "compass.py", line 3\nSyntaxError: invalid syntax\n'))
    check("a non-zero exit fails with the last line of stderr", "exit 1" in r and "SyntaxError: invalid syntax" in r, r)
    check("a timeout fails", "timed out" in v(cases[2], R("pre-write-gate", None, timed_out=True)))
    r = v(cases[2], R("pre-write-gate", None, error="FileNotFoundError: /usr/bin/python3"))
    check("an interpreter that cannot start fails with the reason", "/usr/bin/python3" in r, r)
    r = v(cases[2], R("pre-write-gate", 0, "{not json", "", parse_error="Expecting property name"))
    check("JSON-looking output that does not parse fails", "JSON" in r, r)
    deny = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": "no"}}
    check("a PreToolUse probe that denies a harmless scratch write fails",
          "den" in v(cases[2], R("pre-write-gate", 0, '{"x": 1}', "", parsed=deny)))
    check("and so does one that exits 2 (a block)", "exit 2" in v(cases[2], R("pre-write-gate", 2, "", "blocked")))
    wrong = {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "x"}}
    check("output for another hook event fails", "PostToolUse" in v(cases[0], R("session-start", 0, '{"x": 1}', "", parsed=wrong)))
    check("plain text from a Stop hook passes (Claude Code accepts it)",
          v(cases[3], R("sync", 0, "the vault is not a git repo\n", "")) == "")
    check("a Stop hook may exit 2: blocking the stop is its job", v(cases[3], R("sync", 2, "", "run /save")) == "")
    check("an async SessionStart hook with no output passes", v(cases[1], R("skills-catalogue", 0, "", "")) == "")

    fs = D.probe_findings([(cases[0], R("session-start", 1, "", "SyntaxError: invalid syntax")),
                           (cases[2], R("pre-write-gate", 0, "", ""))])
    check("a failing probe is hooks:probe:<event>, a failure, one line naming the hook and the reason",
          [(f.key, f.severity) for f in fs] == [("hooks:probe:session-start", "fail")]
          and "compass.py" in fs[0].summary and "SyntaxError" in fs[0].summary and "\n" not in fs[0].summary, fs)


def test_health_notice(D):
    print("\n== session-start health notice ==")
    fn = getattr(D, "health_notice", None)
    check("the notice is a domain rule", callable(fn), fn)
    if not callable(fn):
        return
    check("nothing open, nothing said", fn({}, {}) == "" and fn(None, None) == "")
    active = {"launchd-drift:com.x": {"severity": "warn", "summary": "plist drifted", "first_seen": "x"},
              "hooks:not-firing": {"severity": "fail", "summary": "2 sessions fired no Brain hook", "first_seen": "x"}}
    raised = {"bridge:stale": {"severity": "warn", "summary": "bridge stale\nsecond line", "at": "x"},
              "hooks:not-firing": {"severity": "fail", "summary": "duplicate wording", "at": "x"}}
    text = fn(active, raised)
    lines = text.splitlines()
    check("a heading, one line per open finding, failures first",
          lines and lines[0] == "## Brain health" and lines[1] == "- [fail] 2 sessions fired no Brain hook"
          and "- [warn] plist drifted" in lines and "- [warn] bridge stale second line" in lines, lines)
    check("a key open in both places is listed once", "duplicate wording" not in text, text)
    check("and the command to inspect it", lines and lines[-1].endswith("`python3 ~/Brain/_bin/guardian.py status`"), lines[-1:])
    many = {"k%02d" % i: {"severity": "warn", "summary": "problem %d " % i + "x" * 400} for i in range(12)}
    text = fn(many, {})
    items = [line for line in text.splitlines() if line.startswith("- [")]
    check("at most five findings, then how many more", len(items) == 5 and "7 more" in text, text)
    check("each line short", all(len(line) <= 140 for line in text.splitlines()), [len(line) for line in text.splitlines()])
    check("a malformed entry is skipped, not fatal",
          fn({"x": "not a dict"}, {"y": {"summary": "only a summary"}}).count("- [") == 1)


def main():
    try:
        from guardian_core import domain as D
    except Exception as exc:
        check("guardian_core.domain imports", False, "%s: %s" % (type(exc).__name__, exc))
    else:
        for t in (test_hook_identity, test_merge_hooks, test_stale_hooks, test_localize, test_schedule,
                  test_decide, test_report_and_rules, test_agents_and_drift, test_agent_conflicts, test_git_hooks,
                  test_repair_alert, test_token_pool, test_duplicates_and_degraded, test_routine_permissions,
                  test_hook_liveness, test_hook_probe, test_health_notice):
            try:
                t(D)
            except Exception as exc:
                check("%s ran to the end" % t.__name__, False, "%s: %s" % (type(exc).__name__, exc))
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
