#!/usr/bin/env python3
"""Presence heartbeat over S3: who is working, on what, and since when.

There was already a git-based presence — one `.md` per session in `90-Meta/presence/` —
and it is still there, because it works with no network and no credentials. What it does
not do is arrive in time: it travels in a commit, so the other machine finds out **up to
600 s later**, plus whatever its own push takes. To warn that two sessions are about to
collide on the same note, 600 s is not warning at all.

Here the heartbeat goes over S3 and takes ~130 ms. Two decisions make it cheap:

1. **Everything lives in the KEY, not in the body.** `presencia/<project>/<machine>__<sid>`
   with an empty body. A single listing of one prefix returns who is there and their
   `LastModified`, which IS the heartbeat. Zero downloads, one call.
2. **The clock is AWS's, nobody else's.** Age is computed from the `LastModified` the
   listing itself returns, so clock skew between machines stops mattering entirely.

And the rule that governs the rest: **there is never network on a hook's path.** This is
always invoked detached (`Popen(start_new_session=True)`), leaves the result in a local
cache, and the hooks read that cache, which is an `open()`. With no credentials, no SMB
mount or no network, no cache is written and the system behaves as before: git presence
and nothing more.
"""
import os, sys, json, time, subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B

BUCKET = os.environ.get("BRAIN_S3_BUCKET", "CHANGE-ME-your-bucket")
REGION = "eu-west-1"
# S3 credentials, via the optional 1Password module (or the standard AWS environment).
# The Secret Access Key is resolved through secret.py from a 1Password reference; the
# Access Key ID comes from $AWS_ACCESS_KEY_ID or its own reference. Override with envs.
SECRET_REF = os.environ.get("BRAIN_AWS_SECRET_REF", "op://Private/aws-brain-s3/credential")
SECRET_ID_REF = os.environ.get("BRAIN_AWS_KEYID_REF", "op://Private/aws-brain-s3/username")
SECRET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "secret.py")
AWS = "/opt/homebrew/bin/aws"

# DO NOT TRANSLATE. This string keys objects already in the bucket AND the AWS
# lifecycle rules that expire them. It is read in two more places — s3v.py
# `coordination_lifecycle()` and s3v.py `cmd_check()` (COORD) — which must agree.
PREFIX = "presencia/"
CACHE = os.path.join(B.STATE, "presence-s3.json")
TTL = 900.0            # no heartbeat in 15 min and the session counts as gone
EVERY = 120.0          # never beat more than once every two minutes
TIMEOUT = 6            # if S3 takes longer, give up: this is never urgent


# One derivation, in brainlib. Three copies of the same body is how `skills_index.py`
# came to carry a comment asserting "the machine name comes from brainlib … so the two
# places cannot disagree" while three other copies quietly existed.
_machine = B._machine


def _aws(*args):
    try:
        p = subprocess.run([AWS] + list(args), capture_output=True, text=True,
                           timeout=TIMEOUT)
        return p.returncode, p.stdout, p.stderr
    except Exception as e:
        return 1, "", repr(e)


def _key(project, sid):
    return "%s%s/%s__%s" % (PREFIX, project or "-", _machine(), sid)


def announce(sid, project):
    """Record that this session is alive and which project it is on.

    Empty body on purpose: what gets consulted is the key and its date. A PUT on our own
    key competes with nobody — one file per session, same as in git — so no condition is
    needed.
    """
    # No `--body`: the object ends up zero bytes, which is exactly what we want.
    # `--body /dev/null` does not work — the CLI demands a regular file and rejects the
    # device with ParamValidation.
    rc, _, err = _aws("s3api", "put-object", "--bucket", BUCKET,
                      "--key", _key(project, sid))
    return rc == 0, err


def withdraw(sid, project):
    rc, _, _ = _aws("s3api", "delete-object", "--bucket", BUCKET,
                    "--key", _key(project, sid))
    return rc == 0


def read(own_sid=None):
    """Who is alive, according to S3. One call, downloading no bodies."""
    # `s3 ls` does NOT work here: on an empty prefix it returns **rc=1 with empty
    # stderr**, indistinguishable from a real error. `list-objects-v2` returns rc=0 and
    # the string "None", which genuinely means "nobody there". Verified against the real
    # bucket.
    rc, out, err = _aws("s3api", "list-objects-v2", "--bucket", BUCKET,
                        "--prefix", PREFIX,
                        "--query", "Contents[].[Key,LastModified]", "--output", "text")
    if rc != 0:
        return None, err            # None = "unknown", different from "nobody there"
    now_ = time.time()
    alive_ones, expired_ones = [], []
    for line in out.splitlines():
        if not line.strip() or line.strip() == "None":
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        key, sello = parts[0].strip(), parts[1].strip()
        try:
            # Server ISO stamp: one clock for every machine, so skew between local
            # clocks stops mattering.
            from datetime import datetime
            t = datetime.fromisoformat(sello).timestamp()
        except ValueError:
            continue
        rest = key[len(PREFIX):]
        if "/" not in rest or "__" not in rest:
            continue
        project, who = rest.split("/", 1)
        machine, _, sid = who.partition("__")
        row = {"machine": machine, "sid": sid, "project": project,
                "age": round(now_ - t, 1), "key": key}
        (alive_ones if now_ - t <= TTL else expired_ones).append(row)
    return {"alive": [v for v in alive_ones if v["sid"] != own_sid],
            "expired": expired_ones, "read_at": now_}, ""


def purge(expired_ones):
    """Withdraw heartbeats of sessions that are gone. No separate reaper: it happens in
    passing, when someone comes through here, and only for the long-expired ones."""
    n = 0
    for c in expired_ones:
        if c["age"] > TTL * 4:
            rc, _, _ = _aws("s3api", "delete-object", "--bucket", BUCKET, "--key", c["key"])
            n += 1 if rc == 0 else 0
    return n


def cache_read():
    """What the hooks consult: an open(), no network. Never raises."""
    try:
        with open(CACHE) as fh:
            d = json.load(fh)
        if time.time() - d.get("read_at", 0) > TTL:
            return {}               # stale cache: better to say nothing than to lie
        return d
    except Exception:
        return {}


def cache_write(d):
    try:
        os.makedirs(B.STATE, exist_ok=True)
        B.atomic_write(CACHE, json.dumps(d, ensure_ascii=False))
    except Exception as e:
        B.log_error("presence.cache_write", e)


STAMP = os.path.join(B.STATE, "presence-s3.attempt")


def should_beat():
    """True at most once every EVERY seconds. Stamps the ATTEMPT, not the result.

    It used to read the mtime of `presence-s3.json`, which is written only at the END of
    the happy path. So on any failure — no 1Password item, no network, a throttled bucket — the
    throttle never advanced and EVERY prompt forked a detached interpreter that did
    nothing but log and exit. Measured in this log: 2,722 `no-secret` lines against 100
    successful beats. Anchoring on the attempt makes the throttle hold whether the beat
    works or not.
    """
    try:
        if time.time() - os.path.getmtime(STAMP) < EVERY:
            return False
    except OSError:
        pass
    try:
        os.makedirs(B.STATE, exist_ok=True)
        open(STAMP, "w").close()
    except OSError:
        pass
    return True


def worker():
    secret = sys.stdin.readline().strip()
    if not secret:
        sys.exit(4)
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import s3v
        key_id = s3v.access_key_id()
    except Exception as e:
        B.log_error("presence.key_id", e)
        sys.exit(4)
    os.environ.update({"AWS_ACCESS_KEY_ID": key_id,
                       "AWS_SECRET_ACCESS_KEY": secret,
                       "AWS_DEFAULT_REGION": REGION})
    sys.argv = [sys.argv[0]] + sys.argv[2:]
    sys.exit(_real() or 0)


def _real():
    import argparse
    p = argparse.ArgumentParser(prog="presence")
    p.add_argument("action", choices=["beat", "withdraw", "view"])
    p.add_argument("--sid", default="")
    p.add_argument("--project", default="-")
    a = p.parse_args()

    t0 = time.time()
    if a.action == "withdraw":
        ok = withdraw(a.sid, a.project)
        B.log("presence", "withdraw", sid=a.sid, ok=ok, ms="%.0f" % ((time.time()-t0)*1000))
        return 0

    if a.action == "beat" and a.sid:
        ok, err = announce(a.sid, a.project)
        if not ok:
            B.log("presence", "beat-fails", err=err[:150])

    status, err = read(a.sid)
    if status is None:
        B.log("presence", "read-fails", err=err[:150])
        return 1
    status["machine"] = _machine()
    cache_write(status)
    if status["expired"]:
        purge(status["expired"])
    B.log("presence", a.action, alive_ones=len(status["alive"]),
          ms="%.0f" % ((time.time() - t0) * 1000))
    if a.action == "view":
        print(json.dumps(status, ensure_ascii=False, indent=1))
    return 0


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "__worker":
        worker()
    # Without the credentials volume there is nothing to do, and mounting it is NOT
    # attempted: this runs unattended and a Finder dialog here would be unacceptable.
    import shutil as _sh
    if not _sh.which("op"):
        B.log("presence", "no-secret")
        return 3
    cmd = "%s %s __worker %s" % (sys.executable, os.path.abspath(__file__),
                                 " ".join("'%s'" % x.replace("'", "'\\''")
                                          for x in sys.argv[1:]))
    os.execv(sys.executable, [sys.executable, SECRET, "get", SECRET_REF, "--pipe", cmd])


if __name__ == "__main__":
    sys.exit(main() or 0)
