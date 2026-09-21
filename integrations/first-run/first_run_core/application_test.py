#!/usr/bin/env python3
"""Tests for first_run_core.application: the first run's flow, on in-memory ports.

Every port is a fake that records its calls. The prompter answers from a script and fails the
test if asked anything the script did not expect, so "nothing is asked" and "nothing is installed
without a yes" are both checked. Run standalone:

    python3 integrations/first-run/first_run_core/application_test.py
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


class OutOfAnswers(Exception):
    pass


class FakePrompt:
    """Answers are consumed in order; yes_no takes booleans, ask and secret take strings."""

    def __init__(self, answers=(), interactive=True):
        self.answers, self.asked, self.said, self.yes_nos = list(answers), [], [], []
        self._interactive = interactive

    def interactive(self):
        return self._interactive

    def _next(self, question):
        self.asked.append(question)
        if not self.answers:
            raise OutOfAnswers(question)
        return self.answers.pop(0)

    def yes_no(self, question, default=False):
        self.yes_nos.append(question)
        return self._next(question)

    def ask(self, question, default=""):
        value = self._next(question)
        return default if value == "" else value

    def secret(self, question):
        return self._next(question)

    def say(self, text):
        self.said.append(text)


class Recorder:
    def __init__(self, **results):
        self.calls, self.results = [], results

    def __getattr__(self, name):
        if name.startswith("_") or name in ("calls", "results"):
            raise AttributeError(name)

        def call(*args):
            self.calls.append((name,) + args)
            value = self.results.get(name, (True, "ok"))
            return value(*args) if callable(value) else value

        return call

    def names(self):
        return [c[0] for c in self.calls]


class MemoryState:
    def __init__(self, data=None):
        self.data, self.saves = data, 0

    def load(self):
        return D.parse_state("") if self.data is None else self.data

    def save(self, data):
        self.saves += 1
        self.data = data


class Clock:
    def now(self):
        return dt.datetime(2026, 9, 15, 18, 0, tzinfo=dt.timezone.utc)


SIDE_EFFECTS = ("init", "unlock", "add", "authorize", "check", "persist", "save", "register_claude", "append_profile",
                "install", "add_token", "prepare", "first_start", "configure", "linger")


def ports(answers=(), state=None, interactive=True, **over):
    kw = dict(
        prompt=FakePrompt(answers, interactive),
        state=MemoryState(state),
        kdbx=Recorder(configured="", exists=False),
        google=Recorder(accounts=[]),
        files=Recorder(propose_default="/home/u/BrainFiles", check=lambda path: (True, path),
                       persist=(True, "/state/files-dir.json")),
        multi_machine=Recorder(check=lambda path: (True, path), persist=(True, "/state/shared-dir.json")),
        mail=Recorder(save="/state/guardian-mail.json"),
        mcp=Recorder(snippets={"claude-code": "claude mcp add brain -- python3 /v/integrations/mcp/server.py"},
                     claude_available=True, profile_path="/home/u/.zshrc", vault="/v"),
        scheduler=Recorder(detect="systemd", preview="[Unit] preview",
                           install=lambda kind, jobs: [(D.job_label(kind, j), True, "installed") for j in jobs]),
        routines=Recorder(agent_available=(True, "~/.local/bin/claude")),
        remote=Recorder(default_label="workstation", vault="/home/u/Brain", preflight=([], []),
                        prepare=lambda path: (True, path), first_start=(True, "claude exit 0"),
                        configure=(True, "/state/remote-control.json"), linger=(True, "lingering is on")),
        clock=Clock(),
        home="/home/u",
        platform="linux",
    )
    kw.update(over)
    return A.Ports(**kw)


def side_effects(p):
    out = []
    for name in ("kdbx", "google", "files", "multi_machine", "mail", "mcp", "scheduler", "routines", "remote"):
        out += ["%s.%s" % (name, c[0]) for c in getattr(p, name).calls if c[0] in SIDE_EFFECTS]
    return out


NO_TO_ALL = [False, "", False, False, False, False, False]  # kdbx, files (default dir), multi_machine, alert email, MCP,
                                                           # scheduler, remote_control


def test_decline_everything():
    print("\n== a user who says no to everything ==")
    p = ports(NO_TO_ALL)
    res = A.run(p)
    check("nothing is installed, created, registered or written but the files directory, which cannot be declined",
          side_effects(p) == ["files.check", "files.persist"] and ("check", "/home/u/BrainFiles") in p.files.calls,
          side_effects(p))
    check("every other step is recorded as declined, and files as done with the default directory",
          all(p.state.data["steps"][s]["status"] == "declined" for s in D.STEPS if s != "files")
          and p.state.data["steps"]["files"]["status"] == "done"
          and p.state.data["steps"]["files"]["dir"] == "/home/u/BrainFiles", p.state.data)
    check("the first run is complete and was saved", res.complete and p.state.saves >= 1, res)
    check("the scheduler answer says nothing was accepted", p.state.data.get("scheduler", {}).get("jobs", []) == [])
    p2 = ports([], state=p.state.data)
    res2 = A.run(p2)
    check("running it again asks nothing", p2.prompt.asked == [] and res2.complete, p2.prompt.asked)


def test_not_a_terminal():
    print("\n== without a terminal ==")
    p = ports([], interactive=False)
    res = A.run(p)
    check("it changes nothing and says how to run it later",
          p.state.saves == 0 and side_effects(p) == [] and not res.complete
          and any("setup.sh" in s for s in p.prompt.said), (p.prompt.said, res))


def test_kdbx_and_google():
    print("\n== KeePass, then Google ==")
    answers = [True, "", True, True,            # kdbx: yes, default path, create it, arm the cache
               True, "1", "personal", "me@example.com", "cid-1", "sec-1", True,   # google: one account, authorise
               "", False, False, False, False, False, False]   # files, multi_machine, alert email, MCP, scheduler,
                                                               # remote_control, routines
    p = ports(answers, kdbx=Recorder(configured="", exists=False))
    A.run(p)
    db = "/home/u/.local/share/brain/brain.kdbx"
    check("the database is created at the default path after a yes",
          ("init", db, True) in p.kdbx.calls and ("unlock",) in p.kdbx.calls, p.kdbx.calls)
    check("the kdbx step records the database", p.state.data["steps"]["kdbx"].get("db") == db, p.state.data["steps"]["kdbx"])
    check("the Google account is added with its client and authorised",
          ("add", "personal", "cid-1", "sec-1", "me@example.com") in p.google.calls
          and ("authorize", "personal") in p.google.calls, p.google.calls)
    check("the google step records the account names, never the secret",
          p.state.data["steps"]["google"].get("accounts") == ["personal"]
          and "sec-1" not in repr(p.state.data), p.state.data["steps"]["google"])

    answers = [True, "", True, True, True, "1", "Bad Name", "personal", "", "cid", "sec", False,
              "", False, False, False, False, False, False]
    p = ports(answers)
    A.run(p)
    check("an invalid account name is asked again", ("add", "personal", "cid", "sec", "") in p.google.calls,
          (p.google.calls, p.prompt.said))

    p = ports([False, "", False, False, False, False, False])
    A.run(p)
    check("declining the database declines what needs it: Google is not asked and is recorded with the reason",
          p.state.data["steps"]["google"]["status"] == "declined" and "KeePass" in p.state.data["steps"]["google"]["reason"]
          and not any("Google" in q for q in p.prompt.asked) and A.run_status(p)[0], (p.prompt.asked, p.state.data["steps"]))
    p = ports([True, "", True, "", False, False, False, False, False],
             kdbx=Recorder(configured="", exists=False, init=(False, "no cli")))
    A.run(p)
    check("a database step that failed leaves Google unasked and unrecorded, so a later run asks it",
          "google" not in p.state.data["steps"] and not A.run_status(p)[0], p.state.data["steps"])


def test_failure_resumes():
    print("\n== a step that fails is asked again next time ==")
    p = ports([True, "", True, "", False, False, False, False, False],
             kdbx=Recorder(configured="", exists=False, init=(False, "keepassxc-cli not found")))
    res = A.run(p)
    check("a failed step is reported and not recorded",
          "kdbx" not in p.state.data["steps"] and ("kdbx", "keepassxc-cli not found") in res.failed, (res, p.state.data))
    p2 = ports([True, "", True, False, False] + [False] * 5, state=p.state.data)
    A.run(p2)
    check("the next run starts with it again", p2.prompt.asked and "KeePass" in p2.prompt.asked[0], p2.prompt.asked)


def test_scheduler_step():
    print("\n== scheduled jobs ==")
    answers = [False, "", False, False, False] + [True, True, True, False, False, True, False]   # yes; guardian, sync; install; no server
    p = ports(answers)
    A.run(p)
    check("only the accepted jobs are installed, with the detected scheduler",
          [c for c in p.scheduler.calls if c[0] == "install"] == [("install", "systemd", ["guardian", "sync"])],
          p.scheduler.calls)
    check("what would be installed is shown before the last yes",
          any("[Unit] preview" in s for s in p.prompt.said), p.prompt.said)
    check("the accepted jobs are recorded where the guardian reads them",
          p.state.data["scheduler"] == {"kind": "systemd", "jobs": ["guardian", "sync"]}, p.state.data.get("scheduler"))

    answers = [False, "", False, False, False] + [True, True, False, False, False, False, False]  # accepted guardian, refused install
    p = ports(answers)
    A.run(p)
    check("refusing the final install installs nothing and accepts no job",
          "install" not in p.scheduler.names() and p.state.data["scheduler"]["jobs"] == [], p.state.data.get("scheduler"))

    answers = [False, "", False, False, False] + [True, True, True, True, True, False]
    p = ports(answers)
    res = A.run(p, dry_run=True)
    check("a dry run shows the units and installs nothing", "install" not in p.scheduler.names()
          and any("[Unit] preview" in s for s in p.prompt.said), p.scheduler.calls)
    check("and saves no answer", p.state.saves == 0 and not res.complete, p.state.saves)

    p = ports([False, "", False, False, False], scheduler=Recorder(detect="none"))
    A.run(p)
    check("with no supported scheduler the step is not asked and is recorded as declined",
          p.state.data["steps"]["scheduler"]["status"] == "declined"
          and not any("scheduled" in q.lower() for q in p.prompt.asked), (p.prompt.asked, p.state.data["steps"]))

    def partly(kind, jobs):
        return [(D.job_label(kind, "guardian"), True, "ok"), (D.job_label(kind, "sync"), False, "systemctl failed")]

    p = ports([False, "", False, False, False] + [True, True, True, False, False, True, False],
             scheduler=Recorder(detect="systemd", preview="x", install=partly))
    res = A.run(p)
    check("a job that failed to install is not recorded as accepted and the step is asked again",
          p.state.data.get("scheduler", {}).get("jobs") == ["guardian"] and "scheduler" not in p.state.data["steps"]
          and any(step == "scheduler" for step, _ in res.failed), (p.state.data, res.failed))


def test_multi_machine_step():
    print("\n== multi-machine coordination, over a shared path ==")
    p = ports(NO_TO_ALL)
    A.run(p)
    check("declining it records it as declined, and nothing on the port is called",
          p.state.data["steps"]["multi_machine"]["status"] == "declined"
          and [c for c in p.multi_machine.calls if c[0] in ("check", "persist")] == [],
          (p.state.data["steps"].get("multi_machine"), p.multi_machine.calls))

    answers = [False, "", True, "/srv/shared", False, False, False, False]   # kdbx, files, multi_machine: yes + a path
    p = ports(answers)
    A.run(p)
    check("a yes asks for a path and persists it",
          ("check", "/srv/shared") in p.multi_machine.calls and ("persist", "/srv/shared") in p.multi_machine.calls
          and p.state.data["steps"]["multi_machine"] == {"status": "done", "at": "2026-09-15T18:00:00+00:00",
                                                          "dir": "/srv/shared"},
          (p.multi_machine.calls, p.state.data["steps"].get("multi_machine")))
    check("the step never offers a proposed default the way the files step does",
          not any("propose_default" in c for c in p.multi_machine.calls))

    shared = Recorder(check=lambda path: (False, "no such device") if path == "/gone" else (True, path),
                      persist=(True, "/state/shared-dir.json"))
    p = ports([False, "", True, "/gone", "/srv/shared", False, False, False, False], multi_machine=shared)
    A.run(p)
    check("a path that cannot be used is refused and asked again",
          [c for c in shared.calls if c[0] == "check"] == [("check", "/gone"), ("check", "/srv/shared")],
          shared.calls)

    p = ports([False, "", True, "/srv/shared", False, False, False, False])
    A.run(p, dry_run=True)
    check("a dry run creates nothing and records nothing",
          [c for c in p.multi_machine.calls if c[0] in ("check", "persist")] == [] and p.state.saves == 0,
          p.multi_machine.calls)

    failing = Recorder(check=lambda path: (True, path), persist=(False, "PermissionError: state"))
    p = ports([False, "", True, "/srv/shared", False, False, False, False], multi_machine=failing)
    res = A.run(p)
    check("when the choice cannot be saved the step is not recorded, and the next run asks it again",
          "multi_machine" not in p.state.data["steps"] and ("multi_machine", "PermissionError: state") in res.failed
          and not res.complete, (res, p.state.data["steps"]))

    p = ports([], interactive=False)
    state, failed = A.skip_all(p)
    check("skip-all declines it like every other optional step, with no special-casing",
          state["steps"]["multi_machine"]["status"] == "declined", state["steps"].get("multi_machine"))


BEFORE_RC = [False, "", False, False, False, False]   # kdbx, files, multi_machine, alert email, MCP, scheduler: no


def test_remote_control_step():
    print("\n== Remote Control, so the Claude app can reach this machine ==")
    p = ports(NO_TO_ALL)
    A.run(p)
    check("declining it records it as declined and touches nothing",
          p.state.data["steps"]["remote_control"]["status"] == "declined"
          and [c for c in p.remote.calls if c[0] in SIDE_EFFECTS] == [] and "install" not in p.scheduler.names(),
          (p.state.data["steps"].get("remote_control"), p.remote.calls))
    check("the question says what it is for", any("Remote Control" in q for q in p.prompt.yes_nos), p.prompt.yes_nos)

    order = []

    def logged(name, value):
        def call(*args):
            order.append(name)
            return value(*args) if callable(value) else value
        return call

    remote = Recorder(default_label="workstation", vault="/home/u/Brain", preflight=([], []),
                      prepare=logged("prepare", lambda path: (True, path)), first_start=logged("first_start", (True, "0")),
                      configure=logged("configure", (True, "/state/remote-control.json")),
                      linger=logged("linger", (True, "on")))
    sched = Recorder(detect="systemd", preview="[Service] Restart=always",
                     install=logged("install", lambda kind, jobs: [(D.job_label(kind, j), True, "installed") for j in jobs]))
    p = ports(BEFORE_RC + [True, "", "", True, True], remote=remote, scheduler=sched)
    A.run(p)
    check("a yes checks the machine first", ("preflight",) in remote.calls, remote.calls)
    check("the name defaults to this machine's, the repository to a folder of that name in the home directory",
          ("prepare", "/home/u/workstation") in remote.calls
          and ("configure", "/home/u/workstation", "workstation") in remote.calls, remote.calls)
    check("the supervisor is shown before anything is set up", any("Restart=always" in t for t in p.prompt.said),
          p.prompt.said)
    check("the one-time prompts are explained: trust, enable, same-dir spawn mode",
          any("same-dir" in t and "Enable Remote Control" in t for t in p.prompt.said), p.prompt.said)
    check("it is started once in the terminal to answer them, before the supervisor exists",
          order.index("first_start") < order.index("install") and ("first_start", "/home/u/workstation", "workstation")
          in remote.calls, order)
    check("the directory and name are recorded before the supervisor starts the server",
          order.index("configure") < order.index("install"), order)
    check("on systemd lingering is turned on, so the server runs with no one logged in", "linger" in order, order)
    check("the server is installed through the scheduler adapters, as the one remote-control job",
          ("install", "systemd", ["remote-control"]) in sched.calls, sched.calls)
    check("the step records where the guardian will look",
          p.state.data["steps"]["remote_control"] == {"status": "done", "at": "2026-09-15T18:00:00+00:00",
                                                      "kind": "systemd", "dir": "/home/u/workstation",
                                                      "name": "workstation"}, p.state.data["steps"].get("remote_control"))
    check("the periodic jobs are left as the scheduler step recorded them",
          p.state.data["scheduler"]["jobs"] == [], p.state.data["scheduler"])
    check("and it closes with how to check it from the phone",
          any("Claude app" in t and "+" in t for t in p.prompt.said), p.prompt.said)

    p = ports(BEFORE_RC + [True, "build-box", "/srv/rc", True, False])
    A.run(p)
    check("a name and a directory can be chosen", ("configure", "/srv/rc", "build-box") in p.remote.calls,
          p.remote.calls)
    check("declining the first start in the terminal says how to do it by hand",
          not any(c[0] == "first_start" for c in p.remote.calls)
          and any("claude remote-control --chrome --name build-box" in t for t in p.prompt.said), p.prompt.said)

    p = ports(BEFORE_RC + [True, "two words", "workstation", "", True, True])
    A.run(p)
    check("a name that cannot be a folder is asked again", ("configure", "/home/u/workstation", "workstation")
          in p.remote.calls, (p.prompt.said, p.remote.calls))

    p = ports(BEFORE_RC + [True, "", "", True, True],
              scheduler=Recorder(detect="launchd", preview="plist",
                                 install=lambda kind, jobs: [(D.job_label(kind, j), True, "ok") for j in jobs]))
    A.run(p)
    check("on launchd there is no lingering to turn on", "linger" not in p.remote.names()
          and ("install", "launchd", ["remote-control"]) in p.scheduler.calls, (p.remote.calls, p.scheduler.calls))

    p = ports(BEFORE_RC + [True, "", "", True, True], remote=Recorder(
        default_label="workstation", vault="/home/u/Brain", preflight=([], []), prepare=lambda path: (True, path),
        first_start=(True, "0"), configure=(True, "/s"), linger=(False, "Access denied")))
    A.run(p)
    check("lingering that cannot be turned on is a warning with the command to run, not a failure",
          p.state.data["steps"]["remote_control"]["status"] == "done"
          and any("sudo loginctl enable-linger" in t for t in p.prompt.said), p.prompt.said)

    p = ports(BEFORE_RC, scheduler=Recorder(detect="cron"))
    A.run(p)
    check("with cron alone it is not asked and is recorded as declined, saying why",
          p.state.data["steps"]["remote_control"]["status"] == "declined"
          and "cron" in p.state.data["steps"]["remote_control"]["reason"]
          and not any("Remote Control" in q for q in p.prompt.yes_nos), (p.prompt.yes_nos, p.state.data["steps"]))

    blocked = Recorder(default_label="workstation", vault="/home/u/Brain",
                       preflight=(["the claude CLI is not logged in: run `claude auth login`"], ["DO_NOT_TRACK is set"]))
    p = ports(BEFORE_RC + [True], remote=blocked)
    res = A.run(p)
    check("what stops the server fails the step, says why, and the next run asks it again",
          "remote_control" not in p.state.data["steps"] and any(s == "remote_control" for s, _ in res.failed)
          and any("claude auth login" in r for _, r in res.failed), (res.failed, p.state.data["steps"]))
    check("warnings are shown too", any("DO_NOT_TRACK" in t for t in p.prompt.said), p.prompt.said)
    check("and nothing was set up", [c for c in blocked.calls if c[0] in SIDE_EFFECTS] == [], blocked.calls)

    p = ports(BEFORE_RC + [True, "", "", False])
    A.run(p)
    check("refusing the set-up after seeing it declines the step and sets nothing up",
          p.state.data["steps"]["remote_control"]["status"] == "declined"
          and [c for c in p.remote.calls if c[0] in SIDE_EFFECTS] == [] and "install" not in p.scheduler.names(),
          (p.remote.calls, p.state.data["steps"]))

    p = ports(BEFORE_RC + [True, "", ""])
    res = A.run(p, dry_run=True)
    check("a dry run shows the supervisor and sets nothing up",
          [c for c in p.remote.calls if c[0] in SIDE_EFFECTS] == [] and "install" not in p.scheduler.names()
          and any("[Unit] preview" in t for t in p.prompt.said) and p.state.saves == 0, (p.remote.calls, p.prompt.said))

    p = ports(BEFORE_RC + [True, "", "", True, True],
              scheduler=Recorder(detect="systemd", preview="x",
                                 install=lambda kind, jobs: [(D.job_label(kind, j), False, "daemon-reload failed")
                                                             for j in jobs]))
    res = A.run(p)
    check("a supervisor that did not install fails the step, so it is asked again",
          "remote_control" not in p.state.data["steps"]
          and any(s == "remote_control" and "daemon-reload failed" in r for s, r in res.failed), res.failed)

    p = ports([], interactive=False)
    state, _ = A.skip_all(p)
    check("skip-all declines it like every other optional step",
          state["steps"]["remote_control"]["status"] == "declined", state["steps"].get("remote_control"))


def test_mail_mcp_files_routines():
    print("\n== alert email, MCP, the files directory, routines ==")
    answers = [False, "", False,                                # kdbx, files, multi_machine (google not asked without kdbx)
               True, "smtp.example.com", "587", "me@example.com", "mail/smtp", "me@example.com", "me@example.com",
               False, False, False]
    p = ports(answers)
    A.run(p)
    saves = [c for c in p.mail.calls if c[0] == "save"]
    check("with no Google account, alerts go through SMTP with the password as a KeePass reference",
          len(saves) == 1 and saves[0][1] == {"enabled": True, "adapter": "smtp", "from": "me@example.com",
                                              "to": "me@example.com", "smtp": {"host": "smtp.example.com", "port": 587,
                                                                               "user": "me@example.com", "security": "starttls",
                                                                               "kp_ref": "kp://mail/smtp#Password"}},
          saves)

    answers = ["", False, True, "me@example.com", "", False, False, False, False]
    p = ports(answers, google=Recorder(accounts=["personal"]), kdbx=Recorder(configured="/k.kdbx", exists=True),
              state=D.record(D.record(D.new_state(), "kdbx", "done", {"db": "/k.kdbx"}, Clock().now()),
                             "google", "done", {"accounts": ["personal"]}, Clock().now()))
    A.run(p)
    saves = [c for c in p.mail.calls if c[0] == "save"]
    check("with a Google account connected, alerts go through the Gmail API as that account",
          saves and saves[0][1]["adapter"] == "gmail-api" and saves[0][1]["account"] == "personal"
          and saves[0][1]["to"] == "me@example.com", saves)

    answers = [False, "", False, False, True, True, True, False, False]   # ..., MCP yes x3, scheduler, remote_control
    p = ports(answers)
    A.run(p)
    check("the MCP step shows the snippets, registers with Claude Code and exports BRAIN_VAULT only after a yes each",
          ("register_claude",) in p.mcp.calls and ("append_profile", 'export BRAIN_VAULT="/v"') in p.mcp.calls
          and any("claude mcp add" in s for s in p.prompt.said), (p.mcp.calls, p.prompt.said))

    files = Recorder(propose_default="/home/u/BrainFiles", persist=(True, "/state/files-dir.json"),
                     check=lambda path: (False, "read-only file system") if path == "/ro" else (True, path))
    p = ports([False, "/ro", "/data/files", False, False, False, False, False], files=files)
    A.run(p)
    check("a directory that cannot be used is refused and the question is asked again",
          [c for c in files.calls if c[0] == "check"] == [("check", "/ro"), ("check", "/data/files")]
          and any("read-only file system" in s for s in p.prompt.said), (files.calls, p.prompt.said))
    check("the usable directory is persisted and recorded",
          ("persist", "/data/files") in files.calls
          and p.state.data["steps"]["files"] == {"status": "done", "at": "2026-09-15T18:00:00+00:00", "dir": "/data/files"},
          (files.calls, p.state.data["steps"].get("files")))
    check("the files step never asks a yes or no it could be declined with",
          # "directory", not "file": the multi_machine step's own yes/no legitimately mentions
          # file claims, and this check is about `_files` never gaining a yes/no of its own.
          not any("directory" in q.lower() for q in p.prompt.yes_nos), p.prompt.yes_nos)

    p = ports([False, "", False, False, False, False, False], files=Recorder(propose_default="/home/u/BrainFiles",
                                                                       check=lambda path: (True, path),
                                                                       persist=(False, "PermissionError: state")))
    res = A.run(p)
    check("when the choice cannot be saved the step is not recorded, and the next run asks it again",
          "files" not in p.state.data["steps"] and ("files", "PermissionError: state") in res.failed
          and not res.complete, (res, p.state.data["steps"]))

    p = ports([False, "", False, False, False, False, False])
    A.run(p, dry_run=True)
    check("a dry run creates no directory and records nothing",
          [c for c in p.files.calls if c[0] in ("check", "persist")] == [] and p.state.saves == 0, p.files.calls)

    p = ports([], interactive=False)
    state, failed = A.skip_all(p)
    check("skip-all asks nothing, creates and records the default files directory, and declines the rest",
          p.prompt.asked == [] and failed == [] and state["steps"]["files"]["status"] == "done"
          and state["steps"]["files"]["dir"] == "/home/u/BrainFiles"
          and all(state["steps"][s]["status"] == "declined" for s in D.STEPS if s != "files")
          and p.state.data == state, (state, failed))
    p = ports([], interactive=False, files=Recorder(propose_default="/ro", check=(False, "read-only file system")))
    state, failed = A.skip_all(p)
    check("when the default directory is not usable skip-all leaves files unanswered and says why",
          "files" not in state["steps"] and failed == [("files", "read-only file system")]
          and not D.is_complete(state), (state, failed))

    answers = [False, "", False, False, False, False, False, True, "2"]
    p = ports(answers, state=D.record(D.new_state(), "kdbx", "done", {"db": "/k.kdbx"}, Clock().now()))
    A.run(p)
    tokens = [c for c in p.routines.calls if c[0] == "add_token"]
    check("routines add numbered token references to the pool, never token values",
          tokens == [("add_token", "routines-1", "kp://apis/agent-routines-token-1", "2026-09-15", "routines"),
                     ("add_token", "routines-2", "kp://apis/agent-routines-token-2", "2026-09-15", "routines")],
          (tokens, p.prompt.asked))
    check("and say how to store each token in KeePass",
          any("kp.py put apis/agent-routines-token-1 --stdin" in s for s in p.prompt.said), p.prompt.said)


def main():
    global A, D
    try:
        from first_run_core import application as A
        from first_run_core import domain as D
    except Exception as exc:
        check("first_run_core.application and domain import", False, "%s: %s" % (type(exc).__name__, exc))
    else:
        for t in (test_decline_everything, test_not_a_terminal, test_kdbx_and_google, test_failure_resumes,
                  test_scheduler_step, test_multi_machine_step, test_remote_control_step,
                  test_mail_mcp_files_routines):
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
