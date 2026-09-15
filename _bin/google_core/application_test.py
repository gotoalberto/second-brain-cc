#!/usr/bin/env python3
"""Tests for google_core.application: google.py's use cases, on in-memory ports.

No KeePass, no browser, no network: the secret store, HTTP, the account store, the consent
receiver, the mailer and the send log are fakes. Run standalone:

    python3 _bin/google_core/application_test.py
"""
import datetime as dt
import os
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[0] = os.path.dirname(HERE)

ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def outcome(fn, *a, **kw):
    try:
        return fn(*a, **kw), None
    except Exception as exc:
        return None, exc


class FakeSecrets:
    def __init__(self, values=None, locked=False):
        self.values = dict(values or {})
        self.locked = locked
        self.reads, self.writes = [], []

    def read(self, entry, attr="Password", timeout=20):
        self.reads.append((entry, attr))
        if self.locked:
            raise P.Unavailable("kp://%s: KeePass is locked" % entry)
        if (entry, attr) not in self.values:
            raise P.Unavailable("kp://%s#%s unreadable" % (entry, attr))
        return self.values[(entry, attr)]

    def write(self, entry, value, username=None, notes=None):
        self.writes.append((entry, value, username))
        self.values[(entry, "Password")] = value
        if username is not None:
            self.values[(entry, "UserName")] = username


class FakeHttp:
    def __init__(self, form=None, request=None):
        self.form = form or (lambda url, fields: {"access_token": "at-1"})
        self.req = request or (lambda method, url, token, body: {"ok": True})
        self.posts, self.requests = [], []

    def post_form(self, url, fields, timeout=20):
        self.posts.append((url, dict(fields)))
        return self.form(url, fields)

    def request(self, method, url, token, body=None, timeout=30):
        self.requests.append((method, url, token, body))
        return self.req(method, url, token, body)


class FakeAccounts:
    def __init__(self, accounts=None):
        self.accounts = dict(accounts or {})
        self.saves = 0

    def load(self):
        return dict(self.accounts)

    def save(self, accounts):
        self.saves += 1
        self.accounts = dict(accounts)


class FakeReceiver:
    def __init__(self, params):
        self.params, self.calls = params, []

    def wait(self, port, url, state, timeout):
        self.calls.append((port, url, state, timeout))
        params = dict(self.params)
        if params.get("state") == "<same>":
            params["state"] = state
        return params


class FakeMailer:
    def __init__(self, explode=None, message_id="m-1"):
        self.explode, self.message_id, self.sent = explode, message_id, []

    def send(self, to, subject, body, html=False):
        if self.explode:
            raise self.explode
        self.sent.append((to, subject, body, html))
        return self.message_id


class FakeLog:
    def __init__(self, explode=False):
        self.records, self.explode = [], explode

    def append(self, record):
        if self.explode:
            raise OSError("read-only")
        self.records.append(record)


class FixedClock:
    def now(self):
        return dt.datetime(2026, 9, 15, 7, 30, tzinfo=dt.timezone.utc)


def configured(D, **over):
    acct = D.Account("work", login_hint="me@example.com", scopes=D.scopes_for(["gmail"]), port=8767)
    secrets = FakeSecrets({(D.client_entry("work"), "UserName"): "cid-1", (D.client_entry("work"), "Password"): "sec-1",
                           (D.refresh_entry("work"), "Password"): "rt-1"})
    kw = dict(secrets=secrets, http=FakeHttp(), accounts=FakeAccounts({"work": acct}), receiver=None,
              send_log=FakeLog(), clock=FixedClock())
    kw.update(over)
    return A.Ports(**kw)


def test_add_and_list():
    print("\n== add and list accounts ==")
    p = A.Ports(secrets=FakeSecrets(), http=FakeHttp(), accounts=FakeAccounts())
    acct = A.add_account(p, "personal", "cid-9", "sec-9", login_hint="me@example.com", scope_sets=["gmail", "drive"])
    check("add stores the client secret in the account's client entry, with the client id as its user name",
          p.secrets.writes == [(D.client_entry("personal"), "sec-9", "cid-9")], p.secrets.writes)
    check("and records the account in the registry, with no secret in it",
          p.accounts.accounts == {"personal": acct} and acct.scopes == D.scopes_for(["gmail", "drive"]), p.accounts.accounts)
    check("list returns the accounts by name", [a.name for a in A.list_accounts(p)] == ["personal"])
    A.add_account(p, "work", "cid-w", "sec-w")
    check("a second account keeps the first", sorted(p.accounts.accounts) == ["personal", "work"])
    _, exc = outcome(A.add_account, p, "Bad Name", "c", "s")
    check("a bad account name is a usage error and writes nothing",
          isinstance(exc, D.UsageError) and len(p.secrets.writes) == 2, repr(exc))
    _, exc = outcome(A.add_account, p, "x", "", "s")
    check("an empty client id is a usage error", isinstance(exc, D.UsageError), repr(exc))
    _, exc = outcome(A.add_account, p, "x", "c", "")
    check("an empty client secret is a usage error", isinstance(exc, D.UsageError), repr(exc))


def test_authorize():
    print("\n== authorize (loopback consent) ==")
    opened = []
    http = FakeHttp(form=lambda url, fields: {"refresh_token": "rt-new", "access_token": "at"})
    p = configured(D, http=http, receiver=FakeReceiver({"code": "c-1", "state": "<same>"}), open_url=opened.append)
    p.secrets.values.pop((D.refresh_entry("work"), "Password"))
    entry = A.authorize(p, "work", timeout=120)
    port, url, state, timeout = p.receiver.calls[0]
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    check("the consent URL is opened and the receiver waits on the account's port",
          opened == [url] and port == 8767 and timeout == 120 and q.get("state") == [state], (opened, p.receiver.calls))
    check("the code is exchanged at the token endpoint with the same redirect",
          http.posts and http.posts[0][0] == D.TOKEN_URL and http.posts[0][1]["code"] == "c-1"
          and http.posts[0][1]["redirect_uri"] == "http://127.0.0.1:8767", http.posts)
    check("the refresh token is stored in the account's refresh entry",
          entry == D.refresh_entry("work") and (D.refresh_entry("work"), "rt-new", None) in p.secrets.writes, p.secrets.writes)

    p = configured(D, http=FakeHttp(form=lambda url, fields: {"access_token": "at"}),
                   receiver=FakeReceiver({"code": "c-1", "state": "<same>"}))
    _, exc = outcome(A.authorize, p, "work")
    check("a consent that returns no refresh token is an error and stores nothing",
          isinstance(exc, D.GoogleError) and p.secrets.writes == [], repr(exc))
    p = configured(D, receiver=FakeReceiver({"error": "access_denied"}))
    _, exc = outcome(A.authorize, p, "work")
    check("a denied consent is an error", isinstance(exc, D.GoogleError) and "access_denied" in str(exc), repr(exc))
    _, exc = outcome(A.authorize, configured(D, receiver=FakeReceiver({})), "nobody")
    check("an unknown account is an AccountError that says how to add it",
          isinstance(exc, D.AccountError) and "google.py add" in str(exc), repr(exc))


def test_access_token():
    print("\n== access tokens ==")
    p = configured(D)
    tok = A.access_token(p, "work")
    check("a token is the refresh grant with the account's client and refresh token",
          tok == "at-1" and p.http.posts == [(D.TOKEN_URL, D.refresh_request("cid-1", "sec-1", "rt-1"))], p.http.posts)
    check("the client id is read from the client entry's user name",
          (D.client_entry("work"), "UserName") in p.secrets.reads, p.secrets.reads)

    def refused(url, fields):
        raise P.HttpError(400, '{"error": "invalid_grant"}')

    _, exc = outcome(A.access_token, configured(D, http=FakeHttp(form=refused)), "work")
    check("a refused refresh is Unavailable and names the re-authorisation command",
          isinstance(exc, D.Unavailable) and "400" in str(exc) and "google.py auth --account work" in str(exc), repr(exc))
    _, exc = outcome(A.access_token, configured(D, secrets=FakeSecrets(locked=True)), "work")
    check("a locked KeePass is Unavailable, never a prompt", isinstance(exc, D.Unavailable), repr(exc))
    p = configured(D, http=FakeHttp(form=lambda url, fields: {"access_token": "t", "scope": "x"}))
    _, exc = outcome(A.access_token, p, "work", D.GMAIL_SEND_SCOPE)
    check("a token without the required scope is Unavailable", isinstance(exc, D.Unavailable), repr(exc))


def test_api():
    print("\n== api ==")
    p = configured(D, http=FakeHttp(request=lambda m, u, t, b: {"items": [1]}))
    res = A.api(p, "work", "POST", "https://www.googleapis.com/calendar/v3/calendars/primary/events", {"summary": "x"})
    check("api calls the URL with the method, the token and the JSON body",
          res == {"items": [1]} and p.http.requests == [("POST", "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                                                         "at-1", {"summary": "x"})], p.http.requests)

    def forbidden(m, u, t, b):
        raise P.HttpError(403, '{"error": {"message": "insufficient scopes"}}')

    res = A.api(configured(D, http=FakeHttp(request=forbidden)), "work", "GET", "https://x")
    check("an HTTP error comes back as a _http_error result carrying Google's message",
          res.get("_http_error") == 403 and "insufficient" in res.get("_body", "") and D.api_exit_code(res) == 1, res)


def test_send():
    print("\n== send ==")
    p = configured(D)
    mailer = FakeMailer()
    rec = A.send(p, mailer, "work", "you@example.com", "Vault digest", "body", html=True, run_id="digest-1")
    check("send hands the message to the mailer", mailer.sent == [("you@example.com", "Vault digest", "body", True)])
    check("and logs one record with the account, the message id and the run id",
          p.send_log.records == [rec] and rec["account"] == "work" and rec["message_id"] == "m-1"
          and rec["run_id"] == "digest-1" and "body" not in rec, p.send_log.records)
    for why, args in (("two recipients", ("a@b.co, c@d.co", "s", "b")), ("an empty subject", ("a@b.co", " ", "b")),
                      ("a subject on two lines", ("a@b.co", "s\nt", "b")), ("an empty body", ("a@b.co", "s", "  "))):
        m = FakeMailer()
        _, exc = outcome(A.send, configured(D), m, "work", *args)
        check("%s is a usage error and sends nothing" % why, isinstance(exc, D.UsageError) and m.sent == [], repr(exc))
    p = configured(D)
    _, exc = outcome(A.send, p, FakeMailer(explode=RuntimeError("gmail send refused (403)")), "work", "a@b.co", "s", "b")
    check("a delivery failure raises and logs nothing", isinstance(exc, Exception) and p.send_log.records == [], repr(exc))
    p = configured(D, send_log=FakeLog(explode=True))
    rec, exc = outcome(A.send, p, FakeMailer(), "work", "a@b.co", "s", "b")
    check("a send log that cannot be written does not undo a delivered message",
          exc is None and rec.get("log_error"), (rec, repr(exc)))


def main():
    global A, D, P
    try:
        from google_core import application as A
        from google_core import domain as D
        from google_core import ports as P
    except Exception as exc:
        check("google_core.application, domain and ports import", False, "%s: %s" % (type(exc).__name__, exc))
    else:
        for t in (test_add_and_list, test_authorize, test_access_token, test_api, test_send):
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
