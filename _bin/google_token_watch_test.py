#!/usr/bin/env python3
"""Tests for google_token_watch: when a warning is owed, who sends it, and that it is sent once a day.

No KeePass, no Google, no mail: the registry, the token probe and the sender are fakes passed to
main(), and the state file lives in a temporary directory. Run standalone:

    python3 _bin/google_token_watch_test.py
"""
import datetime as dt
import io
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import google_token_watch as W
from google_core import domain as D

ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


UTC = dt.timezone.utc
NOW = dt.datetime(2030, 1, 10, 9, 0, tzinfo=UTC)


def test_assess_and_due():
    s = W.assess("work", "2030-01-05T09:00:00+00:00", True, "ok", NOW)
    check("expiry is the consent plus 7 days", s["expires"] == dt.datetime(2030, 1, 12, 9, 0, tzinfo=UTC), s)
    check("days left are counted from now", s["days_left"] == 2.0, s)
    check("2 days left is inside the 3 day window", W.due(s, None, "2030-01-10") == "expiring")
    check("but not twice on the same day", W.due(s, "2030-01-10", "2030-01-10") is None)
    fresh = W.assess("work", "2030-01-09T09:00:00+00:00", True, "ok", NOW)
    check("a fresh consent needs no warning", W.due(fresh, None, "2030-01-10") is None, fresh)
    dead = W.assess("work", "2030-01-09T09:00:00+00:00", False, "invalid_grant", NOW)
    check("a token that no longer refreshes is dead, whatever the clock says", W.due(dead, None, "2030-01-10") == "dead")
    nostamp = W.assess("work", "", True, "ok", NOW)
    check("no consent stamp means unknown, never a warning by itself",
          nostamp["days_left"] is None and W.due(nostamp, None, "2030-01-10") is None, nostamp)
    check("a naive instant is read as UTC", W.parse_instant("2030-01-05T09:00:00").tzinfo is not None)
    check("garbage is no instant", W.parse_instant("yesterday") is None and W.parse_instant(None) is None)


def test_sender():
    a = {"account": "a", "alive": True}
    b = {"account": "b", "alive": True}
    c = {"account": "c", "alive": False}
    check("--via always wins", W.pick_sender([a, b], {"a": "expiring"}, "other") == "other")
    check("an alive account with no trouble of its own sends", W.pick_sender([a, b], {"a": "expiring"}) == "b")
    check("else the account in trouble, while it still works", W.pick_sender([a], {"a": "expiring"}) == "a")
    check("a dead account never sends", W.pick_sender([c], {"c": "dead"}) is None)


def test_compose():
    s = W.assess("work", "2030-01-08T09:00:00+00:00", True, "ok", NOW)
    subject, body = W.compose([s], {"work": "expiring"})
    check("an expiring token says when, in the subject", subject == "Google token expires in 5 days: work", subject)
    check("the body carries the command to renew it", "google.py auth --account work" in body, body)
    check("and is HTML", body.startswith("<div") and "<ul>" in body)
    dead = W.assess("home", "", False, "refused <invalid_grant>", NOW)
    subject, body = W.compose([s, dead], {"home": "dead"})
    check("a dead token leads the subject", subject == "Google token no longer works: home", subject)
    check("and Google's message is escaped", "&lt;invalid_grant&gt;" in body, body)
    check("only the accounts in trouble are in it", "--account work" not in body, body)


class Registry:
    def __init__(self, stamp):
        self.authorized_at = stamp


def run(argv, accounts, probes, root, sent=None):
    out = io.StringIO()
    calls = []

    def send(via, to, subject, body):
        calls.append((via, to, subject))
        return sent if sent is not None else (True, "sent")
    code = W.main(argv, now=NOW, accounts=accounts, probe_fn=lambda n: probes[n], send_fn=send,
                  path=os.path.join(root, "state.json"), out=out)
    return code, out.getvalue(), calls


def test_main():
    root = tempfile.mkdtemp(prefix="token-watch-")
    try:
        accounts = {"work": Registry("2030-01-05T09:00:00+00:00"), "home": Registry("2030-01-09T09:00:00+00:00"),
                    "other": Registry("")}
        probes = {"work": (True, "ok"), "home": (True, "ok"), "other": (True, "ok")}
        code, out, calls = run(["--to", "me@example.com"], accounts, probes, root)
        check("by default the stamped accounts are watched, and one warning goes out for the expiring one",
              code == 0 and calls == [("home", "me@example.com", "Google token expires in 2 days: work")], (out, calls))
        with open(os.path.join(root, "state.json")) as fh:
            check("the day is recorded per account", json.load(fh) == {"last_sent_day": {"work": "2030-01-10"}})
        code, out, calls = run(["--to", "me@example.com"], accounts, probes, root)
        check("the same day, nothing more is sent", code == 0 and calls == [] and "no warning due" in out, out)
        code, out, calls = run([], accounts, dict(probes, home=(False, "revoked")), root)
        check("without --to the warning is printed, never sent",
              code == 0 and calls == [] and "Google token no longer works: home" in out and "not sent" in out, out)
        code, out, calls = run(["--to", "me@example.com", "--account", "home"], accounts,
                               dict(probes, home=(False, "revoked")), root)
        check("a warning that cannot be sent (no account alive to send it) exits 1",
              code == 1 and calls == [] and "NOT sent" in out, out)
        code, out, calls = run(["--to", "me@example.com", "--account", "home", "--via", "work"], accounts,
                               dict(probes, home=(False, "revoked")), root, sent=(False, "HTTP 401"))
        check("a failed send exits 1 and records nothing", code == 1 and "NOT sent via work: HTTP 401" in out, out)
        code, out, calls = run(["--account", "nobody"], accounts, probes, root)
        check("an unknown account is a usage error", code == 2)
        code, out, calls = run(["--account", "other", "--to", "me@example.com", "--force", "--dry-run"],
                               accounts, probes, root)
        check("--force with --dry-run prints a message and sends nothing",
              code == 0 and calls == [] and "--- SUBJECT ---" in out, out)
        code, out, calls = run([], {"x": Registry("")}, {"x": (True, "ok")}, root)
        check("with no stamped account it says how to get one", code == 0 and "google.py auth" in out, out)
        check("a bad flag is a usage error", run(["--bogus"], accounts, probes, root)[0] == 2)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_stamp_is_what_google_py_writes():
    acct = D.Account("work", authorized_at="2030-01-05T09:00:00+00:00")
    back = D.parse_registry(D.render_registry({"work": acct}))["work"]
    s = W.assess("work", back.authorized_at, True, "ok", NOW)
    check("the watch reads the registry stamp google.py auth writes", s["days_left"] == 2.0, s)


def main():
    for t in (test_assess_and_due, test_sender, test_compose, test_main, test_stamp_is_what_google_py_writes):
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
