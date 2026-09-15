#!/usr/bin/env python3
"""Tests for google_core.adapters: the code behind google.py that touches the machine.

KeePass is a fake kp.py written in a temporary directory, HTTP is a fake urlopen, the consent
receiver listens on an ephemeral 127.0.0.1 port and is called by the test itself. Nothing reaches
the real KeePass database, a browser or the network. Run standalone:

    python3 _bin/google_core/adapters_test.py
"""
import io
import json
import os
import shutil
import stat
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[0] = os.path.dirname(HERE)

ok, fail = [], []
TMP = []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def tmpdir():
    d = tempfile.mkdtemp(prefix="google-adapters-")
    TMP.append(d)
    return d


def write(path, text, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)
    if mode is not None:
        os.chmod(path, mode)
    return path


def outcome(fn, *a, **kw):
    try:
        return fn(*a, **kw), None
    except Exception as exc:
        return None, exc


FAKE_KP = r'''import json, os, sys
log = %(log)r
args = sys.argv[1:]
stdin = sys.stdin.read() if "--stdin" in args else ""
with open(log, "a") as fh:
    fh.write(json.dumps({"args": args, "stdin": stdin, "noprompt": os.environ.get("BRAIN_KP_NOPROMPT", "")}) + "\n")
store = %(store)r
data = json.load(open(store)) if os.path.exists(store) else {}
cmd, entry = args[0], args[1]
if cmd == "get":
    attr = args[args.index("-a") + 1] if "-a" in args else "Password"
    if entry + "#" + attr not in data:
        sys.stderr.write("kp: no entry\n"); sys.exit(1)
    sys.stdout.write(data[entry + "#" + attr] + "\n"); sys.exit(0)
if cmd == "put":
    if entry + "#Password" in data:
        sys.stderr.write("kp: already exists\n"); sys.exit(1)
if cmd in ("put", "set"):
    data[entry + "#Password"] = stdin
    if "-u" in args:
        data[entry + "#UserName"] = args[args.index("-u") + 1]
    json.dump(data, open(store, "w")); sys.exit(0)
sys.exit(2)
'''


def fake_kp(d, data=None):
    log, store = os.path.join(d, "kp.log"), os.path.join(d, "store.json")
    if data is not None:
        write(store, json.dumps(data))
    return write(os.path.join(d, "kp.py"), FAKE_KP % {"log": log, "store": store}), log, store


def calls(log):
    return [json.loads(l) for l in open(log)] if os.path.exists(log) else []


def test_secret_store():
    print("\n== KpSecretStore ==")
    d = tmpdir()
    kp, log, store = fake_kp(d, {"google/work/oauth-client#UserName": "cid-1", "google/work/oauth-client#Password": "sec-1"})
    s = AD.KpSecretStore(kp, headless=True)
    check("a read returns the stored value without its newline",
          s.read("google/work/oauth-client", "UserName") == "cid-1")
    c = calls(log)[-1]
    check("reads go through kp.py get with the attribute, piped, and headless (no prompt)",
          c["args"][:4] == ["get", "google/work/oauth-client", "-a", "UserName"] and "--pipe" in c["args"]
          and c["noprompt"] == "1", c)
    _, exc = outcome(s.read, "google/nobody/refresh-token")
    check("an unreadable entry is Unavailable naming the kp:// reference and never its value",
          isinstance(exc, P.Unavailable) and "google/nobody/refresh-token" in str(exc), repr(exc))
    s.write("google/work/refresh-token", "rt-1")
    c = calls(log)
    check("a new secret is written with put, value on stdin, never in argv",
          c[-1]["args"][:2] == ["put", "google/work/refresh-token"] and c[-1]["stdin"] == "rt-1"
          and "rt-1" not in c[-1]["args"], c[-1])
    s.write("google/work/refresh-token", "rt-2")
    c = calls(log)
    check("an existing one is put first, and edited with set only when put refuses",
          [x["args"][0] for x in c[-2:]] == ["put", "set"] and json.load(open(store))["google/work/refresh-token#Password"] == "rt-2",
          [x["args"] for x in c[-2:]])
    s.write("google/new/oauth-client", "sec-n", username="cid-n")
    c = calls(log)[-1]
    check("a client is written with its client id as user name", "-u" in c["args"] and "cid-n" in c["args"], c)
    check("an interactive store does not set the headless switch",
          AD.KpSecretStore(kp, headless=False).read("google/work/oauth-client", "UserName") == "cid-1"
          and calls(log)[-1]["noprompt"] == "", calls(log)[-1])
    bad = write(os.path.join(d, "kpfail.py"), "import sys\nsys.exit(4)\n")
    _, exc = outcome(AD.KpSecretStore(bad).write, "x", "v")
    check("a write kp.py refuses twice is a GoogleError", isinstance(exc, D.GoogleError), repr(exc))


class FakeResponse:
    def __init__(self, body, status=200):
        self.body, self.status = body, status

    def read(self):
        return self.body


def test_http():
    print("\n== UrllibHttp ==")
    seen = {}

    def good(req, timeout=None):
        seen.update(req=req, timeout=timeout)
        return FakeResponse(b'{"access_token": "at"}')

    h = AD.UrllibHttp(urlopen=good)
    res = h.post_form(D.TOKEN_URL, {"grant_type": "refresh_token", "refresh_token": "r"}, timeout=7)
    check("a form post returns the JSON reply", res == {"access_token": "at"}, res)
    check("with a form-encoded body and the timeout",
          seen["req"].data == b"grant_type=refresh_token&refresh_token=r" and seen["timeout"] == 7, seen)

    def forbidden(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO(b'{"error": "nope"}'))

    _, exc = outcome(AD.UrllibHttp(urlopen=forbidden).request, "GET", "https://x", "tok")
    check("an HTTP error is HttpError carrying status and body",
          isinstance(exc, P.HttpError) and exc.status == 403 and "nope" in exc.body, repr(exc))

    def offline(req, timeout=None):
        raise urllib.error.URLError("no route")

    _, exc = outcome(AD.UrllibHttp(urlopen=offline).post_form, "https://x", {})
    check("no network is Unavailable", isinstance(exc, P.Unavailable), repr(exc))

    def created(req, timeout=None):
        seen.update(req=req)
        return FakeResponse(b"", status=204)

    res = AD.UrllibHttp(urlopen=created).request("DELETE", "https://x/events/1", "tok")
    check("an empty reply comes back as its status", res == {"_status": 204}, res)
    AD.UrllibHttp(urlopen=created).request("POST", "https://x", "tok", {"a": 1})
    check("a request carries the bearer token and a JSON body",
          seen["req"].get_header("Authorization") == "Bearer tok" and json.loads(seen["req"].data) == {"a": 1}
          and seen["req"].get_method() == "POST", seen["req"].header_items())


def test_files():
    print("\n== JsonAccountStore and JsonlSendLog ==")
    d = tmpdir()
    store = AD.JsonAccountStore(os.path.join(d, "state", "google-accounts.json"))
    check("no registry file means no accounts", store.load() == {})
    acct = D.Account("work", login_hint="me@example.com")
    store.save({"work": acct})
    check("the registry round-trips", store.load() == {"work": acct})
    check("and is private (0600)", stat.S_IMODE(os.stat(store.path).st_mode) == 0o600)
    log = AD.JsonlSendLog(os.path.join(d, "state", "logs", "mail-sent.jsonl"))
    log.append({"to": "a@b.co"})
    log.append({"to": "c@d.co"})
    lines = open(log.path).read().splitlines()
    check("the send log gets one JSON line per send", [json.loads(l)["to"] for l in lines] == ["a@b.co", "c@d.co"], lines)
    check("and is private (0600)", stat.S_IMODE(os.stat(log.path).st_mode) == 0o600)
    env = {"BRAIN_STATE": os.path.join(d, "s")}
    check("the send log path is BRAIN_MAIL_SENT_LOG when set",
          AD.sent_log_path(dict(env, BRAIN_MAIL_SENT_LOG="/x/log.jsonl")) == "/x/log.jsonl")
    check("else it is under the Brain state logs", AD.sent_log_path(env) == os.path.join(d, "s", "logs", "mail-sent.jsonl"),
          AD.sent_log_path(env))
    check("the account registry is in the Brain state directory",
          AD.accounts_path(env) == os.path.join(d, "s", "google-accounts.json"), AD.accounts_path(env))


def test_receiver():
    print("\n== LoopbackReceiver ==")
    r = AD.LoopbackReceiver()
    port = r.free_port()
    got = {}

    def wait():
        got["params"] = r.wait(port, "https://accounts.example/consent", "st-1", timeout=10)

    t = threading.Thread(target=wait)
    t.start()
    reply = None
    for _ in range(50):
        try:
            reply = urllib.request.urlopen("http://127.0.0.1:%d/?code=c-1&state=st-1" % port, timeout=2).read()
            break
        except Exception:
            time.sleep(0.1)
    t.join(15)
    check("the receiver hands back the callback's parameters", got.get("params") == {"code": "c-1", "state": "st-1"}, got)
    check("and tells the browser it can close the tab", reply is not None and b"close" in reply.lower(), reply)
    _, exc = outcome(AD.LoopbackReceiver().wait, AD.LoopbackReceiver().free_port(), "u", "s", timeout=1)
    check("nobody coming back within the timeout is an error", isinstance(exc, D.GoogleError), repr(exc))


def main():
    global AD, D, P
    try:
        from google_core import adapters as AD
        from google_core import domain as D
        from google_core import ports as P
    except Exception as exc:
        check("google_core.adapters, domain and ports import", False, "%s: %s" % (type(exc).__name__, exc))
    else:
        for t in (test_secret_store, test_http, test_files, test_receiver):
            try:
                t()
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
