#!/usr/bin/env python3
"""Tests for google.py, the command line over google_core.

google.py runs as a subprocess with a scratch HOME and BRAIN_STATE and a fake kp.py
(BRAIN_GOOGLE_KP). No command here reaches Google: only the ones that fail before any
network call, or that never make one, are run. Run standalone:

    python3 _bin/google_test.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
G = os.path.join(HERE, "google.py")

ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


FAKE_KP = r'''import json, os, sys
store = %(store)r
data = json.load(open(store)) if os.path.exists(store) else {}
args = sys.argv[1:]
if args[0] in ("put", "set"):
    data[args[1] + "#Password"] = sys.stdin.read()
    if "-u" in args:
        data[args[1] + "#UserName"] = args[args.index("-u") + 1]
    json.dump(data, open(store, "w")); sys.exit(0)
if args[0] == "get":
    attr = args[args.index("-a") + 1] if "-a" in args else "Password"
    if args[1] + "#" + attr in data:
        print(data[args[1] + "#" + attr]); sys.exit(0)
    sys.exit(4)
sys.exit(2)
'''


def main():
    root = tempfile.mkdtemp(prefix="google-cli-")
    try:
        if not os.path.exists(G):
            check("google.py exists", False, G)
            print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
            return 1
        state, store = os.path.join(root, "state"), os.path.join(root, "store.json")
        kp = os.path.join(root, "kp.py")
        with open(kp, "w") as fh:
            fh.write(FAKE_KP % {"store": store})
        env = {k: v for k, v in os.environ.items() if not k.startswith("BRAIN_")}
        env.update(HOME=os.path.join(root, "home"), BRAIN_STATE=state, BRAIN_GOOGLE_KP=kp, BRAIN_KP_NOPROMPT="1")

        def run(*args, stdin=""):
            p = subprocess.run([sys.executable, G] + list(args), env=env, input=stdin, capture_output=True,
                               text=True, timeout=60)
            return p.returncode, p.stdout, p.stderr

        rc, out, err = run("--help")
        check("--help exits 0 and names every subcommand",
              rc == 0 and all(c in out for c in ("accounts", "add", "auth", "token", "api", "send", "slots")), (rc, out, err))
        src = open(G, encoding="utf-8").read()
        check("no account, address, client id or project is baked into the script",
              "@gmail.com" not in src and ".apps.googleusercontent.com" not in src and "CLIENT_ID =" not in src)

        rc, out, err = run("accounts")
        check("with nothing connected, accounts says so and exits 0", rc == 0 and "no accounts" in out, (rc, out, err))

        rc, out, err = run("add", "--account", "work", "--client-id", "cid-1", "--login-hint", "me@example.com",
                           "--scopes", "gmail,calendar", stdin="sec-1\n")
        registry = os.path.join(state, "google-accounts.json")
        data = json.load(open(registry)) if os.path.exists(registry) else {}
        check("add records the account in the state directory", rc == 0 and "work" in data.get("accounts", {}),
              (rc, out, err, data))
        stored = json.load(open(store)) if os.path.exists(store) else {}
        check("and files the client secret (from stdin) and client id in KeePass",
              stored.get("google/work/oauth-client#Password") == "sec-1"
              and stored.get("google/work/oauth-client#UserName") == "cid-1", stored)
        check("the secret never appears in the output", "sec-1" not in out + err, out + err)
        rc, out, err = run("accounts")
        check("accounts lists it with its login hint", rc == 0 and "work" in out and "me@example.com" in out, out)

        rc, out, err = run("add", "--account", "Bad Name", "--client-id", "c", stdin="s\n")
        check("a bad account name exits 2", rc == 2, (rc, err))
        rc, out, err = run("token", "--account", "nobody")
        check("an unknown account exits 2 and says how to add it", rc == 2 and "google.py add" in err, (rc, err))
        rc, out, err = run("token", "--account", "work")
        check("an account never authorised exits 1 and says to run auth", rc == 1 and "auth" in err, (rc, err))
        rc, out, err = run("api", "--account", "work", "https://www.googleapis.com/calendar/v3/users/me/calendarList")
        check("api without a usable token exits 1", rc == 1, (rc, out, err))
        rc, out, err = run("send", "--account", "work", "--to", "a@b.co, c@d.co", "--subject", "s", stdin="body")
        check("send to two recipients is a usage error, exit 2", rc == 2 and "one email address" in err, (rc, err))
        rc, out, err = run("send", "--account", "work", "--to", "a@b.co", "--subject", "s", stdin="")
        check("send with an empty body is a usage error, exit 2", rc == 2, (rc, err))
        rc, out, err = run("send", "--account", "work", "--to", "a@b.co", "--subject", "s", stdin="body")
        check("send that cannot get a token exits 1 with one line on stderr",
              rc == 1 and len(err.strip().splitlines()) == 1, (rc, err))
        body = os.path.join(root, "event.json")
        with open(body, "w") as fh:
            json.dump({"start": {"dateTime": "2030-01-07T16:30:00+01:00"},
                       "end": {"dateTime": "2030-01-07T17:00:00+01:00"}}, fh)
        rc, out, err = run("api", "--account", "work", "--method", "POST", "--body-file", body,
                           "https://www.googleapis.com/calendar/v3/calendars/primary/events")
        check("creating an event when the conflict check cannot look exits 1, nothing written",
              rc == 1 and out == "", (rc, out, err))
        rc, out, err = run("slots", "--account", "work", "--start", "2030-01-07T16:30:00+01:00", "--hours", "20-9")
        check("slots with a backwards window is a usage error, exit 2", rc == 2 and "--hours" in err, (rc, err))
        rc, out, err = run("slots", "--account", "work", "--start", "tomorrow")
        check("slots with a start that is not ISO is a usage error, exit 2", rc == 2 and "--start" in err, (rc, err))
        rc, out, err = run("slots", "--account", "work", "--start", "2030-01-07T16:30:00+01:00", "--tz", "UTC")
        check("slots that cannot get a token exits 1", rc == 1, (rc, out, err))
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
