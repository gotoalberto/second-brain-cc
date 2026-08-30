#!/usr/bin/env python3
"""Write lease on a note, arbitrated by S3.

**What it actually solves.** Two sessions on the same project don't collide over code:
they collide over the project NOTE, because both append to its end and git cannot merge
two appends on the same line. Presence already warns about that within ~3 s (see
presence.py), but a warning only helps if someone reads it. This one **acts**: if
another machine holds the note, `vw.py append` redirects itself to a new linked note.

**What it is NOT.** It is not mutual exclusion over the file. Obsidian desktop, Obsidian
mobile, Working Copy and a hand-typed `git commit` will never consult an object in S3,
so the lease is *advisory* by construction: it decides **where** the harness writes,
never **whether** it may write. The real safety net is still git, which on two edits to
the same note gives a loud, aborted conflict rather than a silent merge.

**The primitive.** `put-object --if-none-match "*"` is a server-arbitrated atomic
create-if-absent: among N machines racing for it, one gets a 200 and the rest get 412.
Renew, steal and release all go through `--if-match <ETag>`, so **every** state
transition is a compare-and-swap. There is no unconditional operation anywhere, and in
particular **DELETE is never used**: an unconditional `delete-object` would fire on
stale local state and wipe out the lease another machine had just legitimately acquired.
Releasing means writing a tombstone.

**The invariant the whole thing hangs on**, worth reading twice:

    Nobody declares themselves holder without a 200 from their OWN conditional PUT.
    A 200 from a GET confirms existence and ownership, never freshness.

Without it you get double ownership: a branch that "adopts" the object because it
recognises its own name restarts the clock on the client without refreshing anything on
the server, and both machines believe they hold it for minutes.
"""
import os, sys, json, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B
import presence as P

BUCKET = P.BUCKET
PREFIX = "locks/"
CACHE = os.path.join(B.STATE, "leases.json")

TTL = 1200.0        # without renewal, the lease expires after 20 min
GUARD = 120.0       # the holder stops believing it holds at TTL-120...
CUSHION = 60.0      # ...and the thief waits until TTL+60. 180 s of margin.
LEASED_FOLDERS = ("10-Projects", "70-Entities")


def slug(rel):
    """The whole note path identifies the resource: two projects can share a basename
    in different folders."""
    return rel.replace("/", "__").replace(" ", "_")


def _key(rel):
    return PREFIX + slug(rel)


def _me():
    return P._machine()


def _peek(rel):
    """Server-side state: (exists, etag, owner, age). One single call.

    The owner lives in the object metadata, not in the body: `head-object` returns it
    alongside the ETag and LastModified, so knowing who holds it, since when, and with
    which witness costs a single round trip.
    """
    rc, out, err = P._aws("s3api", "head-object", "--bucket", BUCKET,
                          "--key", _key(rel), "--output", "json")
    if rc != 0:
        if "404" in (err or "") or "Not Found" in (err or ""):
            return False, None, None, None
        raise RuntimeError((err or "").strip()[:200])
    d = json.loads(out)
    meta = d.get("Metadata") or {}
    from datetime import datetime
    t = datetime.fromisoformat(d["LastModified"].replace("Z", "+00:00")).timestamp()
    return True, d.get("ETag"), meta, time.time() - t


def _put(rel, cond, sid, free=False):
    """The conditional PUT. `cond` is the only way to become the holder."""
    # Written as `machine`/`free`, read as both: a machine still on the old code
    # writes `maquina`/`libre`, and until it pulls `_bin/` the two must understand
    # each other or they would both believe the lease is theirs.
    meta = "machine=%s,sid=%s%s" % (_me(), sid, ",free=1" if free else "")
    rc, _, err = P._aws("s3api", "put-object", "--bucket", BUCKET, "--key", _key(rel),
                        "--metadata", meta, *cond)
    if rc == 0:
        return True, ""
    return False, (err or "").strip()[:200]


def acquire(rel, sid):
    """Try to become the holder. Returns 'mine' | 'foreign' | 'unknown'.

    These four branches are all there is, and none declares itself holder without its
    own 200:
      absent           -> --if-none-match "*"   (race: one wins, the rest get 412)
      held by me       -> --if-match <etag>     (renew: refreshes the SERVER clock)
      free or expired  -> --if-match <etag>     (steal, atomic against the witness)
      held and fresh   -> foreign, untouched
    """
    try:
        exists, etag, meta, age = _peek(rel)
    except RuntimeError as e:
        B.log("lease", "peek-fails", note=rel, err=str(e))
        return "unknown"

    if not exists:
        ok, err = _put(rel, ["--if-none-match", "*"], sid)
        if ok:
            return "mine"
        # A 412 here means someone else created it between the head and the put: not a
        # failure, the race working as designed. It gets re-checked on the next pass.
        B.log("lease", "create-race", note=rel, err=err[:80])
        return "foreign"

    holder = meta.get("machine") or meta.get("maquina")
    mine_ = holder == _me() and meta.get("sid") == sid
    free = (meta.get("free") or meta.get("libre")) == "1"
    expired_ = age is not None and age > TTL + CUSHION

    if mine_ and not free:
        ok, _ = _put(rel, ["--if-match", etag], sid)
        return "mine" if ok else "unknown"
    if free or expired_:
        ok, _ = _put(rel, ["--if-match", etag], sid)
        if ok:
            B.log("lease", "stolen", note=rel, a=holder,
                  age="%.0f" % (age or 0))
            return "mine"
        return "foreign"                   # someone else got to the steal first
    return "foreign"


def release_lease(rel, sid):
    """Conditional tombstone. Never DELETE: see the module docstring."""
    try:
        exists, etag, meta, _ = _peek(rel)
    except RuntimeError:
        return False
    if not exists or (meta.get("machine") or meta.get("maquina")) != _me() or meta.get("sid") != sid:
        return False                       # not ours: leave it alone
    ok, _ = _put(rel, ["--if-match", etag], sid, free=True)
    return ok


# ------------------------------------------------------------------- local cache
def cache_read():
    """What vw.py consults: an open(), no network, no exceptions."""
    try:
        with open(CACHE) as fh:
            return json.load(fh)
    except Exception:
        return {}


def _row(d, rel, sid=""):
    """This session's row, falling back to the shared pre-sid one."""
    if sid and (slug(rel) + "|" + sid) in d:
        return d[slug(rel) + "|" + sid]
    return d.get(slug(rel)) or {}


def local_state(rel, sid=""):
    """'mine' | 'foreign' | '' — using the LOCAL clock since our own last 200.

    The row is per SESSION, not just per note. Sharing one row per note meant a SECOND
    session on this same machine, told "foreign" by S3 because the sid differs, wrote
    that verdict over the row the true holder was reading — and `vw.py` then redirected
    the holder's own appends to a side note. Two sessions here are not two machines.

    `valid_until` is only written after our own PUT returned 200. That is why a laptop
    waking after two hours with the lid shut self-demotes for free, without detecting
    the suspend and without touching the network: local arithmetic already says it
    expired. Intervals use time.time() and NOT time.monotonic(), which on this
    interpreter does not advance while the machine sleeps — and that is exactly the
    time that has to be counted.
    """
    d = _row(cache_read(), rel, sid)
    if d.get("state") == "mine" and time.time() < (d.get("valid_until") or 0):
        return "mine"
    if d.get("state") == "foreign" and time.time() - (d.get("seen") or 0) < TTL:
        return "foreign"
    return ""


def local_owner(rel, sid=""):
    return _row(cache_read(), rel, sid).get("owner") or "?"


def _store(rel, state, owner="", sid=""):
    d = cache_read()
    key = slug(rel) + "|" + sid if sid else slug(rel)
    d[key] = {"state": state, "owner": owner, "seen": time.time(),
              "note": rel, "sid": sid,
              "valid_until": time.time() + TTL - GUARD if state == "mine" else 0}
    try:
        os.makedirs(B.STATE, exist_ok=True)
        B.atomic_write(CACHE, json.dumps(d, ensure_ascii=False))
    except Exception as e:
        B.log_error("lease._store", e)


# ------------------------------------------------------------------- execution
def _real():
    import argparse
    p = argparse.ArgumentParser(prog="lease")
    p.add_argument("action", choices=["acquire", "release", "status"])
    p.add_argument("note", nargs="?", default="")
    p.add_argument("--sid", default="")
    a = p.parse_args()

    if a.action == "status":
        print(json.dumps(cache_read(), ensure_ascii=False, indent=1))
        return 0
    if not a.note or not a.sid:
        return 2

    t0 = time.time()
    if a.action == "release":
        ok = release_lease(a.note, a.sid)
        _store(a.note, "", "", a.sid)
        B.log("lease", "release_lease", note=a.note, ok=ok,
              ms="%.0f" % ((time.time() - t0) * 1000))
        return 0

    r = acquire(a.note, a.sid)
    if r != "unknown":
        owner = _me() if r == "mine" else ""
        if r == "foreign":
            try:
                _, _, meta, _ = _peek(a.note)
                owner = (meta or {}).get("machine") or (meta or {}).get("maquina") or "?"
            except RuntimeError:
                owner = "?"
        _store(a.note, r, owner, a.sid)
    B.log("lease", "acquire", note=a.note, r=r, ms="%.0f" % ((time.time() - t0) * 1000))
    return 0


def worker():
    secret = sys.stdin.readline().strip()
    if not secret:
        sys.exit(4)
    try:
        import s3v
        key_id = s3v.access_key_id()
    except Exception as e:
        B.log_error("lease.key_id", e)
        sys.exit(4)
    os.environ.update({"AWS_ACCESS_KEY_ID": key_id,
                       "AWS_SECRET_ACCESS_KEY": secret,
                       "AWS_DEFAULT_REGION": P.REGION})
    sys.argv = [sys.argv[0]] + sys.argv[2:]
    sys.exit(_real() or 0)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "__worker":
        worker()
    if len(sys.argv) > 1 and sys.argv[1] == "status":
        return _real()                     # local cache only: no credentials, no network
    import shutil as _sh
    if not _sh.which("op"):
        B.log("lease", "no-secret")
        return 3
    cmd = "%s %s __worker %s" % (sys.executable, os.path.abspath(__file__),
                                 " ".join("'%s'" % x.replace("'", "'\\''")
                                          for x in sys.argv[1:]))
    os.execv(sys.executable, [sys.executable, P.SECRET, "get", P.SECRET_REF, "--pipe", cmd])


if __name__ == "__main__":
    sys.exit(main() or 0)
