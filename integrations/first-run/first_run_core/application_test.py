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
        self.answers, self.asked, self.said = list(answers), [], []
        self._interactive = interactive

    def interactive(self):
        return self._interactive

    def _next(self, question):
        self.asked.append(question)
        if not self.answers:
            raise OutOfAnswers(question)
        return self.answers.pop(0)

    def yes_no(self, question, default=False):
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


SIDE_EFFECTS = ("init", "unlock", "add", "authorize", "test", "save", "register_claude", "append_profile",
                "install", "add_token")


def ports(answers=(), state=None, interactive=True, **over):
    kw = dict(
        prompt=FakePrompt(answers, interactive),
        state=MemoryState(state),
        kdbx=Recorder(configured="", exists=False),
        google=Recorder(accounts=[]),
        storage=Recorder(),
        mail=Recorder(save="/state/guardian-mail.json"),
        mcp=Recorder(snippets={"claude-code": "claude mcp add brain -- python3 /v/integrations/mcp/server.py"},
                     claude_available=True, profile_path="/home/u/.zshrc", vault="/v"),
        scheduler=Recorder(detect="systemd", preview="[Unit] preview",
                           install=lambda kind, jobs: [(D.job_label(kind, j), True, "installed") for j in jobs]),
        routines=Recorder(agent_available=(True, "~/.local/bin/claude")),
        clock=Clock(),
        home="/home/u",
        platform="linux",
    )
    kw.update(over)
    return A.Ports(**kw)


def side_effects(p):
    out = []
    for name in ("kdbx", "google", "storage", "mail", "mcp", "scheduler", "routines"):
        out += ["%s.%s" % (name, c[0]) for c in getattr(p, name).calls if c[0] in SIDE_EFFECTS]
    return out


NO_TO_ALL = [False] * 7


def test_decline_everything():
    print("\n== a user who says no to everything ==")
    p = ports(NO_TO_ALL)
    res = A.run(p)
    check("nothing is installed, created, registered or written", side_effects(p) == [], side_effects(p))
    check("every step is recorded as declined",
          all(p.state.data["steps"][s]["status"] == "declined" for s in D.STEPS), p.state.data)
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
               False, False, False, False, False]
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

    answers = [True, "", True, True, True, "1", "Bad Name", "personal", "", "cid", "sec", False] + [False] * 5
    p = ports(answers)
    A.run(p)
    check("an invalid account name is asked again", ("add", "personal", "cid", "sec", "") in p.google.calls,
          (p.google.calls, p.prompt.said))

    p = ports([False] + [False] * 4)
    A.run(p)
    check("declining the database declines what needs it: Google is not asked and is recorded with the reason",
          p.state.data["steps"]["google"]["status"] == "declined" and "KeePass" in p.state.data["steps"]["google"]["reason"]
          and not any("Google" in q for q in p.prompt.asked) and A.run_status(p)[0], (p.prompt.asked, p.state.data["steps"]))
    p = ports([True, "", True] + [False] * 4, kdbx=Recorder(configured="", exists=False, init=(False, "no cli")))
    A.run(p)
    check("a database step that failed leaves Google unasked and unrecorded, so a later run asks it",
          "google" not in p.state.data["steps"] and not A.run_status(p)[0], p.state.data["steps"])


def test_failure_resumes():
    print("\n== a step that fails is asked again next time ==")
    p = ports([True, "", True] + [False] * 5, kdbx=Recorder(configured="", exists=False, init=(False, "keepassxc-cli not found")))
    res = A.run(p)
    check("a failed step is reported and not recorded",
          "kdbx" not in p.state.data["steps"] and ("kdbx", "keepassxc-cli not found") in res.failed, (res, p.state.data))
    p2 = ports([True, "", True, False, False] + [False] * 5, state=p.state.data)
    A.run(p2)
    check("the next run starts with it again", p2.prompt.asked and "KeePass" in p2.prompt.asked[0], p2.prompt.asked)


def test_scheduler_step():
    print("\n== scheduled jobs ==")
    answers = [False] * 4 + [True, True, True, False, False, True]   # yes; guardian, sync; install
    p = ports(answers)
    A.run(p)
    check("only the accepted jobs are installed, with the detected scheduler",
          [c for c in p.scheduler.calls if c[0] == "install"] == [("install", "systemd", ["guardian", "sync"])],
          p.scheduler.calls)
    check("what would be installed is shown before the last yes",
          any("[Unit] preview" in s for s in p.prompt.said), p.prompt.said)
    check("the accepted jobs are recorded where the guardian reads them",
          p.state.data["scheduler"] == {"kind": "systemd", "jobs": ["guardian", "sync"]}, p.state.data.get("scheduler"))

    answers = [False] * 4 + [True, True, False, False, False, False]  # accepted guardian, refused the install
    p = ports(answers)
    A.run(p)
    check("refusing the final install installs nothing and accepts no job",
          "install" not in p.scheduler.names() and p.state.data["scheduler"]["jobs"] == [], p.state.data.get("scheduler"))

    answers = [False] * 4 + [True, True, True, True, True]
    p = ports(answers)
    res = A.run(p, dry_run=True)
    check("a dry run shows the units and installs nothing", "install" not in p.scheduler.names()
          and any("[Unit] preview" in s for s in p.prompt.said), p.scheduler.calls)
    check("and saves no answer", p.state.saves == 0 and not res.complete, p.state.saves)

    p = ports([False] * 4, scheduler=Recorder(detect="none"))
    A.run(p)
    check("with no supported scheduler the step is not asked and is recorded as declined",
          p.state.data["steps"]["scheduler"]["status"] == "declined"
          and not any("scheduled" in q.lower() for q in p.prompt.asked), (p.prompt.asked, p.state.data["steps"]))

    def partly(kind, jobs):
        return [(D.job_label(kind, "guardian"), True, "ok"), (D.job_label(kind, "sync"), False, "systemctl failed")]

    p = ports([False] * 4 + [True, True, True, False, False, True], scheduler=Recorder(detect="systemd", preview="x", install=partly))
    res = A.run(p)
    check("a job that failed to install is not recorded as accepted and the step is asked again",
          p.state.data.get("scheduler", {}).get("jobs") == ["guardian"] and "scheduler" not in p.state.data["steps"]
          and any(step == "scheduler" for step, _ in res.failed), (p.state.data, res.failed))


def test_mail_mcp_storage_routines():
    print("\n== alert email, MCP, object storage, routines ==")
    answers = [False, False,                                   # kdbx, storage (google not asked without kdbx)
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

    answers = [False, True, "me@example.com", "", False, False, False]
    p = ports(answers, google=Recorder(accounts=["personal"]), kdbx=Recorder(configured="/k.kdbx", exists=True),
              state=D.record(D.record(D.new_state(), "kdbx", "done", {"db": "/k.kdbx"}, Clock().now()),
                             "google", "done", {"accounts": ["personal"]}, Clock().now()))
    A.run(p)
    saves = [c for c in p.mail.calls if c[0] == "save"]
    check("with a Google account connected, alerts go through the Gmail API as that account",
          saves and saves[0][1]["adapter"] == "gmail-api" and saves[0][1]["account"] == "personal"
          and saves[0][1]["to"] == "me@example.com", saves)

    answers = [False, False, False, True, True, True, False, False]
    p = ports(answers)
    A.run(p)
    check("the MCP step shows the snippets, registers with Claude Code and exports BRAIN_VAULT only after a yes each",
          ("register_claude",) in p.mcp.calls and ("append_profile", 'export BRAIN_VAULT="/v"') in p.mcp.calls
          and any("claude mcp add" in s for s in p.prompt.said), (p.mcp.calls, p.prompt.said))

    answers = [False, True, "my-bucket", "eu-west-1", "aws/s3-access-key", False, False, False, False]
    p = ports(answers)
    A.run(p)
    check("object storage is tested with the bucket, region and KeePass entry before it counts",
          ("test", "my-bucket", "eu-west-1", "aws/s3-access-key") in p.storage.calls
          and p.state.data["steps"]["storage"].get("bucket") == "my-bucket", (p.storage.calls, p.state.data["steps"]))

    answers = [False] * 5 + [True, "2"]
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
                  test_scheduler_step, test_mail_mcp_storage_routines):
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
