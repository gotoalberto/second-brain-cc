#!/usr/bin/env python3
"""Tests for google_core.domain: the pure rules behind google.py's named Google accounts.

No IO: account names, KeePass entry names, the consent URL, token responses, the callback,
the account registry, the send record. Run standalone:

    python3 _bin/google_core/domain_test.py
"""
import datetime as dt
import json
import os
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[0] = os.path.dirname(HERE)

ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def raises(fn, exc_type, *a, **kw):
    try:
        fn(*a, **kw)
    except exc_type as exc:
        return exc
    except Exception as exc:
        return None if not isinstance(exc, exc_type) else exc
    return None


def test_accounts(D):
    print("\n== account names and entries ==")
    for good in ("personal", "work", "side-project-2"):
        check("%r is a valid account name" % good, D.valid_account(good))
    for bad in ("", "Personal", "has space", "../x", "a" * 40, "-lead"):
        check("%r is not" % bad, not D.valid_account(bad))
    check("the OAuth client lives in its own entry per account",
          D.client_entry("work") == "google/work/oauth-client")
    check("the refresh token lives in another, whose name shares no prefix with the client's leaf",
          D.refresh_entry("work") == "google/work/refresh-token"
          and not D.refresh_entry("work").rsplit("/", 1)[1].startswith("oauth"))
    check("scope sets expand in order and without duplicates",
          D.scopes_for(["gmail", "calendar", "gmail"]) == D.SCOPES["gmail"] + D.SCOPES["calendar"],
          D.scopes_for(["gmail", "calendar", "gmail"]))
    check("the default sets are read and write Gmail, Calendar and Drive",
          tuple(D.DEFAULT_SCOPE_SETS) == ("gmail", "calendar", "drive")
          and D.GMAIL_SEND_SCOPE in D.scopes_for(D.DEFAULT_SCOPE_SETS)
          and "https://www.googleapis.com/auth/gmail.modify" in D.scopes_for(D.DEFAULT_SCOPE_SETS)
          and "https://www.googleapis.com/auth/calendar" in D.scopes_for(D.DEFAULT_SCOPE_SETS)
          and "https://www.googleapis.com/auth/drive" in D.scopes_for(D.DEFAULT_SCOPE_SETS))
    check("an unknown scope set is a usage error", raises(D.scopes_for, D.UsageError, ["gmail", "fax"]) is not None)


def test_registry(D):
    print("\n== the account registry ==")
    acct = D.Account("work", login_hint="me@example.com", scopes=D.scopes_for(["gmail"]), port=8767)
    text = D.render_registry({"work": acct})
    back = D.parse_registry(text)
    check("the registry round-trips", back == {"work": acct}, back)
    check("it holds no secret, only names, hints, scopes and ports",
          set(json.loads(text)["accounts"]["work"]) == {"login_hint", "scopes", "port"}, text)
    check("an empty registry parses as no accounts", D.parse_registry("") == {} and D.parse_registry("{}") == {})
    for why, bad in (("not json", "{nope"), ("a bad name", json.dumps({"accounts": {"Bad Name": {}}})),
                     ("a bad port", json.dumps({"accounts": {"x": {"port": "eighty"}}})),
                     ("scopes not a list", json.dumps({"accounts": {"x": {"scopes": "all"}}}))):
        check("a registry with %s is refused" % why, raises(D.parse_registry, D.AccountError, bad) is not None)
    stamped = D.Account("work", authorized_at="2026-09-15T07:30:00+00:00")
    text = D.render_registry({"work": stamped})
    check("the consent instant round-trips when there is one",
          D.parse_registry(text) == {"work": stamped} and "authorized_at" in json.loads(text)["accounts"]["work"], text)
    check("a registry written before the stamp existed parses with no instant",
          D.parse_registry(json.dumps({"accounts": {"x": {}}}))["x"].authorized_at == "")
    defaults = D.parse_registry(json.dumps({"accounts": {"x": {}}}))["x"]
    check("an account with no scopes or port gets the defaults",
          defaults.scopes == D.scopes_for(D.DEFAULT_SCOPE_SETS) and defaults.port == D.DEFAULT_PORT, defaults)


def test_consent(D):
    print("\n== consent URL, callback and code exchange ==")
    acct = D.Account("work", login_hint="me@example.com", scopes=D.scopes_for(["gmail"]), port=8767)
    url = D.consent_url("cid-123", acct, "st-1")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    check("consent goes to Google's OAuth endpoint", url.startswith(D.AUTH_URL + "?"), url)
    check("it asks for offline access with a forced consent, so a refresh token comes back",
          q.get("access_type") == ["offline"] and q.get("prompt") == ["consent"], q)
    check("the redirect is this machine's loopback on the account's port",
          q.get("redirect_uri") == ["http://127.0.0.1:8767"] and D.redirect_uri(8767) == "http://127.0.0.1:8767", q)
    check("it carries the client, the scopes, the login hint and the state",
          q.get("client_id") == ["cid-123"] and q.get("scope") == [" ".join(acct.scopes)]
          and q.get("login_hint") == ["me@example.com"] and q.get("state") == ["st-1"], q)
    no_hint = D.consent_url("cid", D.Account("x"), "s")
    check("no login hint means no login_hint parameter", "login_hint" not in no_hint, no_hint)

    check("a callback with the right state yields its code", D.parse_callback({"code": "c-9", "state": "st-1"}, "st-1") == "c-9")
    check("a denied consent is an error naming Google's reason",
          "access_denied" in str(raises(D.parse_callback, D.GoogleError, {"error": "access_denied"}, "st-1")))
    check("a callback with another state is refused",
          raises(D.parse_callback, D.GoogleError, {"code": "c", "state": "other"}, "st-1") is not None)
    check("a callback with no code is refused", raises(D.parse_callback, D.GoogleError, {"state": "st-1"}, "st-1") is not None)

    body = D.code_request("cid", "sec", "c-9", 8767)
    check("the code exchange sends client, secret, code, grant and the same redirect",
          body == {"client_id": "cid", "client_secret": "sec", "code": "c-9", "grant_type": "authorization_code",
                   "redirect_uri": "http://127.0.0.1:8767"}, body)
    check("the refresh request is the refresh_token grant",
          D.refresh_request("cid", "sec", "r-1") == {"client_id": "cid", "client_secret": "sec",
                                                    "refresh_token": "r-1", "grant_type": "refresh_token"})


def test_tokens(D):
    print("\n== token responses ==")
    check("an access token comes out of a good response", D.access_token_from({"access_token": "t"}) == "t")
    check("no access token is Unavailable", raises(D.access_token_from, D.Unavailable, {"expires_in": 3599}) is not None)
    check("a non-dict response is Unavailable", raises(D.access_token_from, D.Unavailable, "t") is not None)
    ok_scope = {"access_token": "t", "scope": "a %s b" % D.GMAIL_SEND_SCOPE}
    check("a token carrying the required scope passes", D.access_token_from(ok_scope, D.GMAIL_SEND_SCOPE) == "t")
    exc = raises(D.access_token_from, D.Unavailable, {"access_token": "t", "scope": "a b"}, D.GMAIL_SEND_SCOPE)
    check("a token lacking it is Unavailable, naming the scope", exc is not None and "gmail.send" in str(exc), exc)
    check("with no scope field there is nothing to check", D.access_token_from({"access_token": "t"}, D.GMAIL_SEND_SCOPE) == "t")
    check("a refresh token comes out of a code exchange", D.refresh_token_from({"refresh_token": "r"}) == "r")
    exc = raises(D.refresh_token_from, D.GoogleError, {"access_token": "t"})
    check("no refresh token explains how to get one", exc is not None and "consent" in str(exc), exc)


def test_send_rules(D):
    print("\n== send ==")
    check("one plain address is valid", D.valid_address("me@example.com"))
    for bad in ("", "me", "a@b.c, d@e.f", "Me <me@example.com>", "me@example.com\n"):
        check("%r is not one address" % bad, not D.valid_address(bad))
    when = dt.datetime(2026, 9, 15, 7, 30, 0, tzinfo=dt.timezone.utc)
    rec = D.sent_record("personal", "me@example.com", "Vault digest", "m-1", "digest-run-1", when)
    check("the send record names account, recipient, subject, message id, run id and time, never the body",
          rec == {"ts": "2026-09-15T07:30:00+00:00", "account": "personal", "to": "me@example.com",
                  "subject": "Vault digest", "message_id": "m-1", "run_id": "digest-run-1"}, rec)
    check("a send outside a routine carries no run id", "run_id" not in D.sent_record("p", "a@b.co", "s", "", None, when))
    check("an api result that is an HTTP error exits 1, anything else 0",
          D.api_exit_code({"_http_error": 403, "_body": "x"}) == 1 and D.api_exit_code({"items": []}) == 0)


def main():
    try:
        from google_core import domain as D
    except Exception as exc:
        check("google_core.domain imports", False, "%s: %s" % (type(exc).__name__, exc))
    else:
        for t in (test_accounts, test_registry, test_consent, test_tokens, test_send_rules):
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
