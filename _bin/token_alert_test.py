#!/usr/bin/env python3
"""Tests for token_alert.py: a refused Google token mails the owner once a day, never through itself.

The state directory, the mail config and the account registry are temporary; the mailers are
fakes, so nothing is sent. Run standalone:

    python3 _bin/token_alert_test.py
"""
import datetime as dt
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

ok, fail = [], []
TMP = []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail and not cond else ""))


def tmpdir():
    d = tempfile.mkdtemp(prefix="token-alert-")
    TMP.append(d)
    return d


class FakeMailer:
    def __init__(self, fails=False, env_seen=None):
        self.fails, self.sent, self.env_seen = fails, [], env_seen

    def send(self, to, subject, body, html=False):
        if self.env_seen is not None:
            self.env_seen.append(os.environ.get("BRAIN_TOKEN_ALERT_OFF"))
        if self.fails:
            raise RuntimeError("smtp down")
        self.sent.append((to, subject, body, html))


DAY1 = dt.datetime(2026, 10, 17, 9, 0, tzinfo=dt.timezone.utc)
DAY2 = DAY1 + dt.timedelta(days=1)


def test_alert(T):
    print("\n== once a day per token, never through the dead one ==")
    env = {"BRAIN_STATE": tmpdir()}
    first, second = FakeMailer(), FakeMailer()
    route = lambda account, environ: ("owner@example.com", [("google:home", first), ("google:club", second)])
    res = T.alert("work", "refresh refused (400): invalid_grant", caller="digest", environ=env, now=DAY1, route=route)
    check("the first sender that works carries the alert", res == "sent:google:home" and len(first.sent) == 1
          and not second.sent, res)
    to, subject, body, html = first.sent[0]
    check("to the owner, as HTML, naming the account", to == "owner@example.com" and html is True
          and "work" in subject, (to, subject))
    check("with the command that fixes it and the escaped reason",
          "google.py auth --account work" in body and "invalid_grant" in body and "digest" in body, body)
    res = T.alert("work", "invalid_grant", environ=env, now=DAY1, route=route)
    check("a second alert for the same token the same day is skipped",
          res == "already-sent-today" and len(first.sent) == 1, res)
    res = T.alert("home", "invalid_grant", environ=env, now=DAY1, route=route)
    check("another token has its own daily mark", res.startswith("sent"), res)
    res = T.alert("work", "invalid_grant", environ=env, now=DAY2, route=route)
    check("the next day it mails again", res == "sent:google:home", res)

    env = {"BRAIN_STATE": tmpdir()}
    down, up = FakeMailer(fails=True), FakeMailer()
    res = T.alert("work", "x", environ=env, now=DAY1, route=lambda a, e: ("o@example.com", [("smtp", down), ("google:club", up)]))
    check("a sender that fails falls through to the next", res == "sent:google:club" and len(up.sent) == 1, res)
    res = T.alert("work", "x", environ={"BRAIN_STATE": tmpdir()}, now=DAY1,
                  route=lambda a, e: ("o@example.com", [("smtp", FakeMailer(fails=True))]))
    check("every sender down reports failed, never raises", res == "failed", res)
    res = T.alert("work", "x", environ={"BRAIN_STATE": tmpdir()}, now=DAY1, route=lambda a, e: None)
    check("no alert channel configured says so", res == "no-route", res)

    def boom(account, environ):
        raise RuntimeError("boom")

    check("a crash anywhere is 'error', never an exception",
          T.alert("work", "x", environ={"BRAIN_STATE": tmpdir()}, now=DAY1, route=boom) == "error")
    check("the off switch silences an alert raised from inside a send",
          T.alert("work", "x", environ={"BRAIN_STATE": tmpdir(), T.OFF_ENV: "1"}, now=DAY1, route=route) == "off")
    seen = []
    saved = os.environ.pop(T.OFF_ENV, None)
    T.alert("work", "x", environ={"BRAIN_STATE": tmpdir()}, now=DAY1,
            route=lambda a, e: ("o@example.com", [("google:club", FakeMailer(env_seen=seen))]))
    check("the switch is on while the alert sends, and off again after",
          seen == ["1"] and os.environ.get(T.OFF_ENV) is None, (seen, os.environ.get(T.OFF_ENV)))
    if saved is not None:
        os.environ[T.OFF_ENV] = saved


def test_route(T):
    print("\n== where the alert goes, and through whom ==")
    state = tmpdir()
    env = {"BRAIN_STATE": state}
    check("with no mail config there is no route", T.route("work", env) is None)
    with open(os.path.join(state, "guardian-mail.json"), "w") as fh:
        json.dump({"enabled": True, "adapter": "gmail-api", "account": "work", "from": "me@example.com",
                   "to": "owner@example.com"}, fh)
    send = "https://www.googleapis.com/auth/gmail.send"
    with open(os.path.join(state, "google-accounts.json"), "w") as fh:
        json.dump({"accounts": {
            "work": {"login_hint": "me@example.com", "scopes": [send], "port": 8766},
            "club": {"login_hint": "desk@example.org", "scopes": [send], "port": 8767},
            "readonly": {"login_hint": "r@example.org", "scopes": ["https://www.googleapis.com/auth/drive"],
                         "port": 8768}}}, fh)
    to, senders = T.route("work", env)
    labels = [label for label, _ in senders]
    check("the alert goes to the guardian's address", to == "owner@example.com", to)
    check("never through the account whose token died, even when the guardian sends through it",
          "google:work" not in labels and "guardian" not in labels, labels)
    check("but through another account that can send", labels == ["google:club"], labels)
    to, senders = T.route("club", env)
    check("when another account died, the guardian's own channel comes first",
          [label for label, _ in senders][:1] == ["guardian"], [label for label, _ in senders])


def test_compose(T):
    print("\n== the message ==")
    subject, body = T.compose("work", "refresh refused (400): <invalid_grant>", "nightly-digest")
    check("the subject names the account", "work" in subject and "Google" in subject, subject)
    check("the body carries the command first and escapes the reason",
          body.find("google.py auth --account work") < body.find("&lt;invalid_grant&gt;")
          and "<invalid_grant>" not in body, body)


def main():
    try:
        import token_alert as T
    except Exception as exc:
        check("token_alert imports", False, "%s: %s" % (type(exc).__name__, exc))
    else:
        for t in (test_alert, test_route, test_compose):
            try:
                t(T)
            except Exception as exc:
                import traceback
                traceback.print_exc()
                check("%s ran to the end" % t.__name__, False, "%s: %s" % (type(exc).__name__, exc))
    for d in TMP:
        shutil.rmtree(d, ignore_errors=True)
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
