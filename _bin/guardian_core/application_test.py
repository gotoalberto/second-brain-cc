#!/usr/bin/env python3
"""Tests for guardian_core.application — the check / repair / status use cases.

Every port is an in-memory fake that records what was asked of it. No file, subprocess,
network, notification or clock is touched. Run standalone:

    python3 _bin/guardian_core/application_test.py
"""
import datetime as dt
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[0] = os.path.dirname(HERE)

ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


V = "/v/_bin"
MISSING_HOOK = ("hooks:Stop:gate_memory.py", "hook Stop gate_memory.py: missing")


# ---------------------------------------------------------------- fakes


class FakeAgent:
    """One agent's event wiring. `changes` are what check() reports and repair() applies."""

    def __init__(self, name="claude-code", present=True, changes=(), unreadable=None,
                 missing=(), repair_errors=(), explode=False):
        self._name, self._present = name, present
        self.changes, self.unreadable = list(changes), unreadable
        self.missing, self.repair_errors, self.explode = list(missing), list(repair_errors), explode
        self.checks = 0
        self.repairs = 0

    def name(self):
        return self._name

    def present(self):
        return self._present

    def check(self):
        self.checks += 1
        if self.explode:
            raise RuntimeError("agent config exploded")
        return D.AgentWiring(self._name, self.unreadable, list(self.changes), list(self.missing))

    def repair(self):
        self.repairs += 1
        applied = [text for _, text in self.changes]
        self.changes = []
        return D.AgentRepair(self._name, applied, list(self.repair_errors),
                             "/fake/%s.bak" % self._name if applied else None)


class FakeLaunchd:
    def __init__(self, jobs=None, self_label=""):
        # label -> dict(installed, loaded, last_ok, detail, install_ok, drifted)
        self.jobs = jobs or {}
        self.calls = []
        self._self = self_label

    def labels(self):
        return sorted(self.jobs)

    def installed(self, label):
        return self.jobs[label]["installed"]

    def is_loaded(self, label):
        return self.jobs[label]["loaded"]

    def last_exit_ok(self, label):
        j = self.jobs[label]
        return j.get("last_ok", True), j.get("detail", "")

    def drifted(self, label):
        return self.jobs[label].get("drifted", False)

    def self_label(self):
        return self._self

    def install(self, label):
        self.calls.append(("install", label))
        if self.jobs[label].get("install_ok", True):
            self.jobs[label]["installed"] = True
            return True, "installed"
        return False, "permission denied"

    def reinstall(self, label):
        self.calls.append(("reinstall", label))
        self.jobs[label]["drifted"] = False
        self.jobs[label]["loaded"] = True
        return True, "previous plist in /state/plist-backups/%s.plist.1" % label

    def bootstrap(self, label):
        self.calls.append(("bootstrap", label))
        self.jobs[label]["loaded"] = True
        return True, "bootstrapped"


class FakeClock:
    def __init__(self, t):
        self.t = t

    def now(self):
        return self.t


class FakeNotifier:
    def __init__(self, explode=False):
        self.sent = []
        self.explode = explode

    def notify(self, title, message):
        if self.explode:
            raise RuntimeError("osascript exploded")
        self.sent.append((title, message))


class FakeOutbox:
    def __init__(self, enabled=False, pending=0, oldest=None, explode=False):
        self.queued = []
        self.flushes = 0
        self._enabled, self._pending, self._oldest = enabled, pending, oldest
        self.explode = explode

    def enqueue(self, to, subject, body):
        if self.explode:
            raise OSError("disk full")
        self.queued.append((to, subject, body))

    def flush(self):
        self.flushes += 1
        return 0, len(self.queued)

    def pending(self):
        return self._pending + len(self.queued)

    def oldest_age_s(self):
        return self._oldest

    def enabled(self):
        return self._enabled


class FakeVault:
    def __init__(self, sync=None, index_age=10.0, broken=0, explode=False):
        self.sync = sync
        self.index_age = index_age
        self.broken = broken
        self.explode = explode

    def sync_status(self):
        if self.explode:
            raise RuntimeError("git is gone")
        return self.sync or D.SyncStatus(pending=0, unpushed_age_s=None, remote_ok=True)

    def index_age_s(self):
        return self.index_age

    def broken_links(self):
        return self.broken


class FakeInterp:
    def __init__(self, statuses=None):
        self.statuses = statuses

    def python3_health(self):
        return self.statuses or [D.InterpreterStatus("/usr/bin/python3", True, "3.9.6")]


class FakeState:
    def __init__(self):
        self.data = {}
        self.saves = 0

    def load(self):
        return dict(self.data)

    def save(self, data):
        self.saves += 1
        self.data = data


class FakeRaised:
    def __init__(self, alerts=None):
        self.alerts = alerts or {}

    def load(self):
        return dict(self.alerts)


class FakeRoutines:
    def __init__(self, routines=None, last=None):
        self._r = routines or []
        self._last = last or {}

    def host(self):
        return "box"

    def routines(self):
        return list(self._r)

    def last_runs(self):
        return dict(self._last)


class FakeGitHooks:
    """The vault repository's git hooks: core.hooksPath and the hook files' modes."""

    def __init__(self, hooks_path="githooks", executable=("pre-commit", "post-commit"),
                 present=("pre-commit", "post-commit"), set_ok=True, explode=False):
        self.hooks_path = hooks_path
        self.executable, self.present = set(executable), set(present)
        self.set_ok, self.explode = set_ok, explode
        self.calls = []

    def status(self):
        if self.explode:
            raise RuntimeError("not a git repository")
        return D.GitHooksStatus(self.hooks_path, [
            D.GitHookFile(n, n in self.present, n in self.present and n in self.executable)
            for n in ("pre-commit", "post-commit")])

    def set_hooks_path(self):
        self.calls.append(("set-hooks-path",))
        if not self.set_ok:
            return False, "could not lock config file"
        self.hooks_path = "githooks"
        return True, "core.hooksPath = githooks"

    def make_executable(self, name):
        self.calls.append(("chmod", name))
        self.executable.add(name)
        return True, "0755"


class FakeTokenPool:
    """The routine token pool as routine_auth_core left it: read-only, never a token value."""

    def __init__(self, pool=None, explode=False):
        self._pool = pool if pool is not None else D.TokenPool([])
        self.explode = explode
        self.calls = 0

    def pool(self):
        self.calls += 1
        if self.explode:
            raise RuntimeError("state file exploded")
        return self._pool


NOW = dt.datetime(2026, 9, 15, 10, 0)


def healthy_jobs():
    return {"com.x.sync": {"installed": True, "loaded": True}}


def make(**over):
    kw = dict(
        agents=[FakeAgent()],
        launchd=FakeLaunchd(healthy_jobs()),
        clock=FakeClock(NOW),
        notifier=FakeNotifier(),
        outbox=FakeOutbox(),
        vault=FakeVault(),
        interpreter=FakeInterp(),
        state=FakeState(),
        raised=FakeRaised(),
        routines=FakeRoutines(),
        mail_to="me@example.com",
    )
    kw.update(over)
    return A.Ports(**kw)


def keys(report):
    return sorted(f.key for f in report.findings)


# ---------------------------------------------------------------- tests


def test_collect():
    print("\n== collect / check ==")
    p = make()
    r = A.run_check(p)
    check("a healthy machine produces an empty report", r.findings == [], r.findings)
    check("and says nothing", p.notifier.sent == [] and p.outbox.queued == [])

    agent = FakeAgent(changes=[MISSING_HOOK])
    p = make(agents=[agent])
    r = A.run_check(p)
    check("a missing wiring entry is a repairable failure keyed by agent",
          keys(r) == ["agent:claude-code:hooks:Stop:gate_memory.py"]
          and r.findings[0].severity == "fail" and r.findings[0].repairable, r.findings)
    check("check never repairs an agent", agent.repairs == 0)
    check("the new problem pops one notification", len(p.notifier.sent) == 1, p.notifier.sent)
    check("and queues one email to the configured address",
          len(p.outbox.queued) == 1 and p.outbox.queued[0][0] == "me@example.com", p.outbox.queued)
    check("the outbox is flushed during the run", p.outbox.flushes >= 1)
    check("alert state is saved", p.state.saves == 1)

    A.run_check(p)
    check("a second check with the same problem stays quiet",
          len(p.notifier.sent) == 1 and len(p.outbox.queued) == 1,
          (p.notifier.sent, p.outbox.queued))

    p = make(agents=[FakeAgent(unreadable="settings.json: Expecting value")])
    r = A.run_check(p)
    check("unreadable agent wiring is a failure repair will not touch",
          keys(r) == ["agent:claude-code:unreadable"] and not r.findings[0].repairable, r.findings)

    p = make(agents=[FakeAgent(missing=[V + "/gate_memory.py"])])
    check("a wired command whose script is missing on disk is a failure",
          keys(A.run_check(p)) == ["agent:claude-code:path:%s/gate_memory.py" % V])

    absent = FakeAgent(name="other-agent", present=False, changes=[MISSING_HOOK])
    p = make(agents=[absent])
    check("an agent that is not installed on this machine is not checked at all",
          keys(A.run_check(p)) == [] and absent.checks == 0, absent.checks)

    p = make(agents=[FakeAgent(changes=[MISSING_HOOK]),
                     FakeAgent(name="second", changes=[("rules:x", "rule x missing")])])
    check("every present agent is checked",
          keys(A.run_check(p)) == ["agent:claude-code:hooks:Stop:gate_memory.py", "agent:second:rules:x"])

    p = make(agents=[FakeAgent(explode=True), FakeAgent(name="second", changes=[("rules:x", "x")])])
    r = A.run_check(p)
    check("an agent whose check raises is a warning for that agent only",
          keys(r) == ["agent:second:rules:x", "probe:agent:claude-code"], keys(r))

    p = make(launchd=FakeLaunchd({"com.x.sync": {"installed": True, "loaded": False}}))
    check("an unloaded launchd job is reported", keys(A.run_check(p)) == ["launchd:com.x.sync"])
    p = make(launchd=FakeLaunchd({"com.x.sync": {"installed": True, "loaded": True, "drifted": True}}))
    check("a drifted launchd plist is reported", keys(A.run_check(p)) == ["launchd-drift:com.x.sync"])

    p = make(interpreter=FakeInterp([D.InterpreterStatus("/usr/bin/python3", False, "exit 69"),
                                     D.InterpreterStatus("/opt/homebrew/bin/python3", True, "ok")]))
    check("a broken hook interpreter is reported", keys(A.run_check(p)) == ["interpreter:hooks"])

    p = make(vault=FakeVault(sync=D.SyncStatus(1, 8 * 3600, True)))
    check("unpushed vault commits are reported", keys(A.run_check(p)) == ["vault:unpushed"])

    p = make(raised=FakeRaised({"routine:daily-digest-agent": {
        "severity": "fail", "summary": "routine daily-digest-agent failed: exit=127"}}))
    r = A.run_check(p)
    check("an alert raised by another process becomes a finding",
          keys(r) == ["routine:daily-digest-agent"], keys(r))
    title, message = p.notifier.sent[0]
    check("the desktop notification carries no detail (it can show on a shared screen)",
          "job" not in (title + message).lower() and "routine" not in (title + message).lower(),
          (title, message))
    check("the email carries the detail",
          "daily-digest-agent" in p.outbox.queued[0][2], p.outbox.queued)

    p = make(outbox=FakeOutbox(enabled=True, pending=2, oldest=7 * 3600))
    check("email enabled but stuck for hours is a warning",
          keys(A.run_check(p)) == ["mail:undelivered"])
    p = make(outbox=FakeOutbox(enabled=False, pending=2, oldest=7 * 3600))
    check("email disabled with messages queued is not a problem",
          keys(A.run_check(p)) == [])

    p = make(vault=FakeVault(explode=True), agents=[FakeAgent(changes=[MISSING_HOOK])])
    r = A.run_check(p)
    check("a probe that raises becomes a warning instead of killing the run",
          "probe:vault" in keys(r), keys(r))
    check("and the other sections are still checked",
          "agent:claude-code:hooks:Stop:gate_memory.py" in keys(r), keys(r))

    p = make(agents=[FakeAgent(changes=[MISSING_HOOK])], notifier=FakeNotifier(explode=True),
             outbox=FakeOutbox(explode=True))
    try:
        A.run_check(p)
        raised = None
    except Exception as exc:
        raised = exc
    check("a failing notifier and outbox never make check raise", raised is None, raised)


def test_repair():
    print("\n== repair ==")
    agent = FakeAgent(changes=[MISSING_HOOK])
    p = make(agents=[agent])
    res = A.run_repair(p)
    check("an agent with repairable wiring is repaired once", agent.repairs == 1, agent.repairs)
    check("the change and the backup are reported",
          res.changes and "gate_memory.py" in res.changes[0] and res.backups == ["/fake/claude-code.bak"],
          res)
    check("the report after repair is clean", res.report.findings == [], res.report.findings)

    agent = FakeAgent()
    p = make(agents=[agent])
    res = A.run_repair(p)
    check("healthy wiring is not repaired", agent.repairs == 0 and res.changes == [])

    agent = FakeAgent(unreadable="settings.json: Expecting value")
    p = make(agents=[agent])
    res = A.run_repair(p)
    check("unreadable wiring is never repaired", agent.repairs == 0)
    check("and the refusal is reported as an error", res.errors, res)

    agent = FakeAgent(changes=[MISSING_HOOK], repair_errors=["could not write settings"])
    res = A.run_repair(make(agents=[agent]))
    check("an agent's repair errors are reported", "could not write settings" in " ".join(res.errors), res)

    absent = FakeAgent(present=False, changes=[MISSING_HOOK])
    A.run_repair(make(agents=[absent]))
    check("an agent that is not installed is never repaired", absent.repairs == 0)

    lj = FakeLaunchd({"com.x.a": {"installed": False, "loaded": False},
                      "com.x.b": {"installed": True, "loaded": False},
                      "com.x.c": {"installed": True, "loaded": True, "last_ok": False,
                                  "detail": "exit 1"},
                      "com.x.d": {"installed": True, "loaded": True, "drifted": True}})
    p = make(launchd=lj)
    res = A.run_repair(p)
    check("an uninstalled job is installed and then loaded",
          ("install", "com.x.a") in lj.calls and ("bootstrap", "com.x.a") in lj.calls, lj.calls)
    check("an installed but unloaded job is only loaded",
          ("bootstrap", "com.x.b") in lj.calls and ("install", "com.x.b") not in lj.calls, lj.calls)
    check("a loaded job that failed its last run is left alone",
          not any(c[1] == "com.x.c" for c in lj.calls), lj.calls)
    check("a drifted job is reinstalled from the template",
          ("reinstall", "com.x.d") in lj.calls and ("install", "com.x.d") not in lj.calls, lj.calls)
    check("after repair only the non-repairable warning remains",
          keys(res.report) == ["launchd-exit:com.x.c"], keys(res.report))

    own = getattr(D, "GUARDIAN_LABEL", "com.secondbrain.guardian")
    stale_key = "launchd-exit:" + own
    prior, _ = D.decide(None, [D.Finding(stale_key, D.WARN,
                                         "launchd job %s: last run failed (LastExitStatus=256)" % own)], NOW)
    st = FakeState()
    st.data = {"alerts": prior}
    outbox = FakeOutbox()
    lj = FakeLaunchd({own: {"installed": True, "loaded": True, "last_ok": False, "detail": "LastExitStatus=256"}},
                     self_label=own)
    res = A.run_repair(make(launchd=lj, state=st, outbox=outbox))
    check("the guardian's own job exiting non-zero is no finding on the next run",
          stale_key not in keys(res.report), keys(res.report))
    check("a stale alert about the guardian's own exit resolves on the first run after the fix",
          stale_key not in ((st.data.get("alerts") or {}).get("active") or {}), st.data)
    check("and that run says it resolved, announcing nothing new",
          [q[1] for q in outbox.queued] == ["Brain guardian: 1 resolved"], outbox.queued)

    lj = FakeLaunchd({"com.x.guardian": {"installed": True, "loaded": True, "drifted": True}},
                     self_label="com.x.guardian")
    res = A.run_repair(make(launchd=lj))
    check("the guardian's own drifted job is not reloaded from inside itself",
          ("reinstall", "com.x.guardian") not in lj.calls, lj.calls)
    check("and says to repair it from a terminal",
          any("terminal" in e for e in res.errors), res.errors)

    lj = FakeLaunchd({"com.x.a": {"installed": False, "loaded": False, "install_ok": False}})
    res = A.run_repair(make(launchd=lj))
    check("an install that fails is reported and not bootstrapped",
          res.errors and ("bootstrap", "com.x.a") not in lj.calls, (res.errors, lj.calls))
    check("and the job is still a finding", keys(res.report) == ["launchd:com.x.a"])

    lj = FakeLaunchd({"com.x.a": {"installed": False, "loaded": False}})
    agent = FakeAgent(changes=[MISSING_HOOK])
    p = make(agents=[agent], launchd=lj)
    res = A.run_repair(p, agents_only=True)
    check("agents-only repairs agents", agent.repairs == 1)
    check("agents-only leaves launchd alone", lj.calls == [], lj.calls)
    check("agents-only neither notifies, emails nor saves alert state",
          p.notifier.sent == [] and p.outbox.queued == [] and p.outbox.flushes == 0
          and p.state.saves == 0)
    check("agents-only reports only on agents", keys(res.report) == [], keys(res.report))


def with_git_hooks(fake, **over):
    """Ports carrying a git hooks port. Set after construction so an older Ports still runs."""
    p = make(**over)
    p.git_hooks = fake
    return p


def test_git_hooks():
    print("\n== vault git hooks ==")
    gh = FakeGitHooks(hooks_path=None)
    p = with_git_hooks(gh)
    r = A.run_check(p)
    check("an unset core.hooksPath on the vault is a repairable failure",
          keys(r) == ["githooks:hooks-path"] and r.findings[0].severity == "fail"
          and r.findings[0].repairable, r.findings)
    check("check never writes git config", gh.calls == [], gh.calls)

    gh = FakeGitHooks(executable=("post-commit",))
    check("a hook file that is not executable is reported",
          keys(A.run_check(with_git_hooks(gh))) == ["githooks:mode:pre-commit"])

    gh = FakeGitHooks(hooks_path=None, executable=("post-commit",))
    p = with_git_hooks(gh)
    res = A.run_repair(p)
    check("repair sets core.hooksPath and fixes the mode",
          gh.calls == [("set-hooks-path",), ("chmod", "pre-commit")], gh.calls)
    check("and reports both changes",
          any("core.hooksPath" in c for c in res.changes) and any("pre-commit" in c for c in res.changes),
          res.changes)
    check("the report after repair has no git hooks finding",
          not any(k.startswith("githooks:") for k in keys(res.report)), keys(res.report))

    gh = FakeGitHooks()
    A.run_repair(with_git_hooks(gh))
    check("healthy git hooks are not touched", gh.calls == [], gh.calls)

    gh = FakeGitHooks(present=("pre-commit",))
    res = A.run_repair(with_git_hooks(gh))
    check("a missing hook file is not repaired, and stays a finding",
          gh.calls == [] and "githooks:missing:post-commit" in keys(res.report), (gh.calls, keys(res.report)))

    gh = FakeGitHooks(hooks_path=None, set_ok=False)
    res = A.run_repair(with_git_hooks(gh))
    check("a failed git config write is reported as an error",
          any("core.hooksPath" in e and "lock" in e for e in res.errors), res.errors)

    gh = FakeGitHooks(hooks_path=None)
    res = A.run_repair(with_git_hooks(gh), agents_only=True)
    check("agents-only repair leaves git hooks alone", gh.calls == [], gh.calls)

    r = A.run_check(with_git_hooks(FakeGitHooks(explode=True)))
    check("a git hooks probe that raises is a warning, not a crash", keys(r) == ["probe:githooks"], keys(r))

    text = A.run_status(with_git_hooks(FakeGitHooks(hooks_path=None)))
    check("status shows the vault's core.hooksPath",
          "git hooks" in text and "core.hooksPath" in text and "unset" in text, text)


def last_mail(p):
    return (p.outbox.queued[-1][1], p.outbox.queued[-1][2]) if p.outbox.queued else ("", "")


def test_repair_notifies():
    print("\n== repair notifies what it changed ==")
    agent = FakeAgent(changes=[MISSING_HOOK])
    p = make(agents=[agent])
    res = A.run_repair(p)
    check("a repair that changed something pops exactly one notification",
          len(p.notifier.sent) == 1, p.notifier.sent)
    title, message = p.notifier.sent[0] if p.notifier.sent else ("", "")
    check("the notification counts what was repaired and carries no detail",
          "repaired 1 item(s)" in message.lower() and "gate_memory" not in title + message
          and "hook" not in (title + message).lower(), (title, message))
    check("one email goes to the configured address",
          len(p.outbox.queued) == 1 and p.outbox.queued[0][0] == "me@example.com", p.outbox.queued)
    subject, body = last_mail(p)
    check("the email lists exactly what changed",
          "repaired 1 item(s)" in subject and MISSING_HOOK[1] in body, (subject, body))
    check("and the backup path", "/fake/claude-code.bak" in body, body)
    check("the alert is handed back for the log",
          any("repaired 1 item(s)" in s for s in getattr(res, "alerts", [])), getattr(res, "alerts", None))

    A.run_repair(p)
    check("a later repair that changes nothing does not notify again",
          len(p.notifier.sent) == 1 and len(p.outbox.queued) == 1, (p.notifier.sent, p.outbox.queued))
    agent.changes = [MISSING_HOOK]
    A.run_repair(p)
    check("the same breakage later is a new event and notifies again",
          len(p.notifier.sent) == 2 and len(p.outbox.queued) == 2, (p.notifier.sent, p.outbox.queued))

    p = make()
    A.run_repair(p)
    check("a repair with zero changes never notifies", p.notifier.sent == [] and p.outbox.queued == [])

    p = make(launchd=FakeLaunchd({"com.x.a": {"installed": False, "loaded": False}}))
    A.run_repair(p)
    subject, body = last_mail(p)
    check("installing and loading a launchd job is one notification listing both",
          len(p.notifier.sent) == 1 and "repaired 2 item(s)" in subject
          and "installed launchd job com.x.a" in body and "loaded launchd job com.x.a" in body, (subject, body))

    p = make(launchd=FakeLaunchd({"com.x.d": {"installed": True, "loaded": True, "drifted": True}}))
    A.run_repair(p)
    subject, body = last_mail(p)
    check("a drifted plist fixed notifies and names the plist backup",
          len(p.notifier.sent) == 1 and "com.x.d" in body and "/state/plist-backups/com.x.d.plist.1" in body, body)

    p = with_git_hooks(FakeGitHooks(hooks_path=None))
    A.run_repair(p)
    subject, body = last_mail(p)
    check("setting the vault's core.hooksPath notifies", len(p.notifier.sent) == 1 and "core.hooksPath" in body, body)

    agent = FakeAgent(changes=[("plugin:skills/x", "skills/x: in the vault, to install into the agent")])
    p = make(agents=[agent])
    A.run_repair(p)
    check("installing a skill notifies", len(p.notifier.sent) == 1 and "skills/x" in last_mail(p)[1], last_mail(p))

    agent = FakeAgent(changes=[MISSING_HOOK])
    p = make(agents=[agent])
    A.run_check(p)
    A.run_repair(p)
    subject, body = last_mail(p)
    check("a repair that also resolves an announced finding sends one message, not two",
          len(p.notifier.sent) == 2 and len(p.outbox.queued) == 2, (p.notifier.sent, p.outbox.queued))
    check("and that message carries both the repair and the resolution",
          "repaired 1 item(s)" in subject and "resolved" in subject and "RESOLVED" in body
          and "/fake/claude-code.bak" in body, (subject, body))

    p = make(launchd=FakeLaunchd({"com.x.a": {"installed": False, "loaded": False, "install_ok": False}}))
    A.run_repair(p)
    text = " ".join(m for _, m in p.notifier.sent) + " ".join(s for _, s, _ in p.outbox.queued)
    check("a repair that only failed sends no repair notice, the finding path speaks instead",
          "repaired" not in text.lower() and len(p.notifier.sent) == 1, (p.notifier.sent, p.outbox.queued))

    p = make(agents=[FakeAgent(changes=[MISSING_HOOK])], mail_to="")
    A.run_repair(p)
    check("with no mail address the notification still goes out",
          len(p.notifier.sent) == 1 and p.outbox.queued == [], (p.notifier.sent, p.outbox.queued))

    p = make(agents=[FakeAgent(changes=[MISSING_HOOK])], notifier=FakeNotifier(explode=True),
             outbox=FakeOutbox(explode=True))
    try:
        A.run_repair(p)
        raised = None
    except Exception as exc:
        raised = exc
    check("a failing notifier and outbox never make repair raise", raised is None, raised)


def test_status():
    print("\n== status ==")
    routines = [{"id": "daily", "machine": "box", "time": "06:00", "days": "*", "type": "agent",
                 "enabled": False, "command": "90-Meta/routines/daily.md"},
                {"id": "weekly", "machine": "box", "time": "09:00", "days": "*", "type": "shell",
                 "enabled": True, "command": "true"}]
    agents = [FakeAgent(changes=[MISSING_HOOK]), FakeAgent(name="other-agent", present=False)]
    p = make(agents=agents, outbox=FakeOutbox(enabled=False, pending=2),
             routines=FakeRoutines(routines, {"weekly": {"last_run_date": "2026-09-15"}}),
             vault=FakeVault(broken=4))
    text = A.run_status(p)
    check("status lists the open problems", "gate_memory.py" in text, text)
    check("status lists each agent and whether it is present",
          "claude-code" in text and "other-agent" in text and "not present" in text, text)
    check("status says email is disabled and how much is queued",
          "disabled" in text.lower() and "2 queued" in text, text)
    check("status lists routines with why they are not due",
          "daily" in text and "disabled" in text and "already ran today" in text, text)
    check("status shows broken links", "4" in text and "broken" in text.lower(), text)
    check("status changes nothing",
          agents[0].repairs == 0 and p.state.saves == 0 and p.notifier.sent == []
          and p.outbox.queued == [] and p.outbox.flushes == 0)


def token(label="routines-1", **kw):
    base = dict(label=label, account="routines", kp_ref="kp://Brain/apis/claude-code-oauth-%s" % label,
                status="healthy", expires="2027-09-15", renew="RENEW-CMD", restore="RESTORE-CMD")
    base.update(kw)
    return D.TokenHealth(**base)


def test_token_pool():
    print("\n== routine token pool ==")
    check("no token pool port is no section", keys(A.run_check(make())) == [])
    p = make(token_pool=FakeTokenPool(D.TokenPool([token(status="dead", last_kind="auth_invalid")])))
    r = A.run_check(p)
    check("a refused routine token is reported by check",
          "routine-auth:token:routines-1" in keys(r) and len(p.notifier.sent) == 1, (keys(r), p.notifier.sent))
    check("and its email carries the renewal command", p.outbox.queued and "RENEW-CMD" in p.outbox.queued[0][2],
          p.outbox.queued)
    pool = FakeTokenPool(D.TokenPool([token(status="dead", last_kind="auth_invalid")]))
    res = A.run_repair(make(token_pool=pool))
    check("repair reports it and changes nothing about tokens",
          "routine-auth:token:routines-1" in keys(res.report) and not any("token" in c for c in res.changes),
          (keys(res.report), res.changes))
    r = A.run_check(make(token_pool=FakeTokenPool(explode=True)))
    check("a pool that cannot be read is a warning, not a crash", keys(r) == ["probe:token_pool"], keys(r))
    text = A.run_status(make(token_pool=FakeTokenPool(D.TokenPool([token(), token("routines-2", status="dead",
                                                                                   last_kind="token_malformed")]))))
    check("status lists each routine token with its state and expiry",
          "routines-1" in text and "healthy" in text and "2027-09-15" in text and "routines-2" in text
          and "dead" in text and "token_malformed" in text, text)
    text = A.run_status(make(token_pool=FakeTokenPool(D.TokenPool([], "the pool has no tokens"))))
    check("status says when the pool config is invalid", "invalid" in text and "no tokens" in text, text)


class FakeRoutinesMeta(FakeRoutines):
    def __init__(self, routines, meta, last=None):
        super().__init__(routines, last)
        self._meta = meta

    def meta(self, row):
        return self._meta.get(row["id"], {"app_task": None, "needs_bridge": []})


class FakeDesktopTasks:
    def __init__(self, enabled=(), explode=False):
        self._enabled, self.explode = list(enabled), explode

    def enabled(self):
        if self.explode:
            raise RuntimeError("sessions directory exploded")
        return list(self._enabled)


ROWS = [{"id": "daily-digest-agent", "machine": "box", "time": "06:06", "days": "*", "type": "agent",
         "enabled": True, "command": "90-Meta/routines/daily-digest.md"},
        {"id": "example-routine-b-agent", "machine": "box", "time": "07:45", "days": "*", "type": "agent",
         "enabled": True, "command": "90-Meta/routines/example-routine-b.md"},
        {"id": "daily-digest", "machine": "box", "time": "06:06", "days": "*", "type": "claude-app",
         "enabled": True, "command": "(Claude app scheduler)"}]
META = {"daily-digest-agent": {"app_task": "daily-digest", "needs_bridge": ["email"]},
        "example-routine-b-agent": {"app_task": "example-routine-b",
                                          "needs_bridge": ["example-bridge", "claude-in-chrome"]}}


def test_permissions():
    print("\n== routine permissions ==")
    meta = dict(META)
    meta["example-routine-b-agent"] = dict(META["example-routine-b-agent"],
                                                 permission_problem="--allowedTools grants bare Bash")
    r = A.run_check(make(routines=FakeRoutinesMeta(ROWS, meta)))
    check("a routine granting unrestricted permissions is a failure in check",
          "routine-permissions:example-routine-b-agent" in keys(r)
          and not any(f.repairable for f in r.findings if f.key.startswith("routine-permissions:")), keys(r))
    check("narrow ones are not", "routine-permissions:daily-digest-agent" not in keys(r), keys(r))


def test_duplicates_and_degraded():
    print("\n== Claude app tasks enabled twice, routines degraded ==")
    p = make(routines=FakeRoutinesMeta(ROWS, META), desktop_tasks=FakeDesktopTasks([("daily-digest", "acct-1111")]))
    r = A.run_check(p)
    dup = [f for f in r.findings if f.key == "duplicate:daily-digest-agent"]
    check("an agent row enabled alongside its Claude app task is a failure", dup and dup[0].severity == "fail"
          and not dup[0].repairable, keys(r))
    desktop = FakeDesktopTasks([("daily-digest", "acct-1111")])
    res = A.run_repair(make(routines=FakeRoutinesMeta(ROWS, META), desktop_tasks=desktop))
    check("repair leaves it to him: still reported, nothing changed",
          "duplicate:daily-digest-agent" in keys(res.report) and not any("daily-digest" in c for c in res.changes),
          (keys(res.report), res.changes))
    check("no Claude app tasks port is no duplicate section",
          not any(k.startswith("duplicate:") for k in keys(A.run_check(make(routines=FakeRoutinesMeta(ROWS, META))))))
    r = A.run_check(make(routines=FakeRoutinesMeta(ROWS, META), desktop_tasks=FakeDesktopTasks(explode=True)))
    check("a sessions directory that cannot be read is a warning", "probe:duplicates" in keys(r), keys(r))
    r = A.run_check(make(routines=FakeRoutines(ROWS), desktop_tasks=FakeDesktopTasks([("daily-digest", "a")])))
    check("a routine source without frontmatter metadata finds nothing and does not crash",
          not any(k.startswith(("duplicate:", "probe:")) for k in keys(r)), keys(r))

    stale = FakeRaised({"bridge:stale": {"severity": "warn", "summary": "bridge stale"}})
    p = make(routines=FakeRoutinesMeta(ROWS, META), raised=stale)
    r = A.run_check(p)
    check("while the bridge is stale, an enabled routine needing the browser is degraded",
          "degraded:example-routine-b-agent" in keys(r) and "degraded:daily-digest-agent" not in keys(r), keys(r))
    text = A.run_status(p)
    line = [l for l in text.splitlines() if "example-routine-b-agent" in l]
    check("and status marks that routine degraded", line and "degraded" in line[0].lower(), text)
    text = A.run_status(make(routines=FakeRoutinesMeta(ROWS, META),
                             desktop_tasks=FakeDesktopTasks([("daily-digest", "acct-1111"), ("x", "acct-2222")])))
    check("status counts the enabled Claude app tasks and their accounts",
          "claude app scheduled tasks: 2 enabled across 2 account(s)" in text, text)


class FakeHookLiveness:
    """Transcripts, heartbeats, the registry's hook events and the liveness epoch, in memory."""

    def __init__(self, sessions=None, heartbeats=None, specs=None, epoch=None, explode=False):
        self._sessions, self._hbs = list(sessions or []), list(heartbeats or [])
        self._specs, self._epoch, self.explode = specs, epoch, explode
        self.started = []

    def sessions(self, since):
        if self.explode:
            raise OSError("projects directory unreadable")
        return [x for x in self._sessions if x.mtime >= since]

    def heartbeats(self, since):
        return [h for h in self._hbs if h.ts >= since]

    def events(self):
        if self._specs is not None:
            return list(self._specs)
        return [D.HookEventSpec("session-start", "SessionStart", "compass.py", "session"),
                D.HookEventSpec("prompt-submit", "UserPromptSubmit", "retrieve.py", "session"),
                D.HookEventSpec("stop-memory-gate", "Stop", "gate_memory.py", "session")]

    def epoch(self):
        return self._epoch

    def start_epoch(self, ts):
        self.started.append(ts)
        if self._epoch is None:
            self._epoch = ts
        return self._epoch

    def config(self):
        return D.LivenessConfig()


class FakeProbe:
    def __init__(self, pairs=None, explode=False):
        self.pairs, self.explode, self.calls = list(pairs or []), explode, 0

    def results(self):
        self.calls += 1
        if self.explode:
            raise RuntimeError("scratch directory could not be created")
        return list(self.pairs)


def test_hook_liveness():
    print("\n== hook liveness and the synthetic probe ==")
    need = ("SessionTranscript", "Heartbeat", "HookEventSpec", "LivenessConfig", "ProbeCase", "ProbeResult")
    if not all(hasattr(D, n) for n in need):
        check("the liveness and probe value types exist", False, [n for n in need if not hasattr(D, n)])
        return
    now = NOW.timestamp()
    session = D.SessionTranscript("aaaa1111", "-Users-me-code-app", now - 600, now - 60)

    src = FakeHookLiveness(sessions=[session])
    r = A.run_check(make(hook_liveness=src))
    check("the first check starts liveness now and judges no session from before it",
          src.started == [now] and "hooks:not-firing" not in keys(r), (src.started, keys(r)))

    p = make(hook_liveness=FakeHookLiveness(sessions=[session], epoch=now - 3600))
    r = A.run_check(p)
    check("an active session that fired no Brain hook is hooks:not-firing, a failure, from check",
          [(f.key, f.severity) for f in r.findings if f.key.startswith("hooks:")] == [("hooks:not-firing", "fail")],
          r.findings)
    check("it reaches the user through the guardian's channel: a notification without detail, the detail by email",
          p.notifier.sent and "aaaa1111" not in p.notifier.sent[0][1]
          and p.outbox.queued and "fired no Brain hook" in p.outbox.queued[0][2], (p.notifier.sent, p.outbox.queued))
    A.run_check(p)
    check("the next check does not tell it again", len(p.notifier.sent) == 1, p.notifier.sent)
    res = A.run_repair(make(hook_liveness=FakeHookLiveness(sessions=[session], epoch=now - 3600)))
    check("repair checks it too", "hooks:not-firing" in keys(res.report), keys(res.report))

    beats = [D.Heartbeat(now - 590, "session-start", "aaaa1111", "ok", "", 30, "SessionStart"),
             D.Heartbeat(now - 500, "prompt-submit", "aaaa1111", "ok", "", 12, "UserPromptSubmit")]
    r = A.run_check(make(hook_liveness=FakeHookLiveness(sessions=[session], heartbeats=beats, epoch=now - 3600)))
    check("a session whose hooks fired raises nothing", not any(k.startswith("hooks:") for k in keys(r)), keys(r))

    text = A.run_status(make(hook_liveness=FakeHookLiveness(sessions=[session], heartbeats=beats, epoch=now - 3600)))
    check("status has a hook liveness section: sessions checked and the last heartbeat per event",
          "hook liveness" in text and "1 session(s) checked" in text and "prompt-submit" in text and "never" in text, text)
    fresh = FakeHookLiveness(sessions=[session])
    text = A.run_status(make(hook_liveness=fresh))
    check("status never starts the liveness epoch, and says it has not started",
          fresh.started == [] and "not started" in text, (fresh.started, text))

    case = D.ProbeCase("session-start", "SessionStart", "compass.py", "/usr/bin/python3 /v/_bin/compass.py", 8, {})
    bad = D.ProbeResult("session-start", 1, "", "SyntaxError: invalid syntax")
    r = A.run_check(make(hook_probe=FakeProbe([(case, bad)])))
    check("a hook that fails the synthetic probe is hooks:probe:<event>, a failure",
          [(f.key, f.severity) for f in r.findings] == [("hooks:probe:session-start", "fail")], r.findings)
    text = A.run_status(make(hook_probe=FakeProbe([(case, bad)])))
    check("status lists the probe result with its reason", "hook probe" in text and "SyntaxError" in text, text)
    good = D.ProbeResult("session-start", 0, "{}", "",
                         parsed={"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "x"}})
    text = A.run_status(make(hook_probe=FakeProbe([(case, good)])))
    check("a passing probe shows as ok in status", "1 hook(s) ok" in text, text)

    r = A.run_check(make(hook_liveness=FakeHookLiveness(explode=True, epoch=now - 3600), hook_probe=FakeProbe(explode=True)))
    check("a liveness source or probe that breaks is a warning, never a crash",
          "probe:hook_liveness" in keys(r) and "probe:hook_probe" in keys(r), keys(r))
    quiet = FakeProbe([(case, bad)])
    A.run_repair(make(hook_probe=quiet), agents_only=True)
    check("repair --hooks-only (what the file watch triggers) runs no probe", quiet.calls == 0, quiet.calls)


def main():
    global A, P, D
    try:
        from guardian_core import application as A
        from guardian_core import ports as P
        from guardian_core import domain as D
        D.AgentWiring, D.AgentRepair
    except Exception as exc:
        check("guardian_core.application, ports and the agent value types import", False,
              "%s: %s" % (type(exc).__name__, exc))
    else:
        for t in (test_collect, test_repair, test_git_hooks, test_repair_notifies, test_status, test_token_pool,
                  test_duplicates_and_degraded, test_permissions, test_hook_liveness):
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
