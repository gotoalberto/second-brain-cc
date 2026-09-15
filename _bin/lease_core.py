#!/usr/bin/env python3
"""The lease rules, with no filesystem and no clock.

lease.py keeps one small JSON record per leased note under <state>/locks/ and only reads or
writes it while holding B.flock on that file. What the file is called, what a record holds,
what an acquirer does with the record it finds, who may release it and what the local cache
says a session holds are decided here. Callers pass the clock in. See lease_core_test.py.
"""

import hashlib
import json

SUFFIX = ".lease"
SLUG_BYTES = 120          # readable part of the file name; the digest keeps it unique


def slug(rel):
    """The whole note path identifies the resource: two projects can share a basename in
    different folders. Also the key of the local cache rows."""
    return rel.replace("/", "__").replace(" ", "_")


def filename(rel):
    """`<slug>.<digest>.lease`: one path component per note.

    The slug alone is not injective (`a/b.md` and `a__b.md` share one) and a long note path
    can exceed a file name's 255 bytes, so a digest of the exact path follows a truncated
    slug. The `.lease` suffix keeps these files apart from B.flock's `<16 hex>.lock` files,
    which live in the same directory.
    """
    digest = hashlib.sha1(rel.encode("utf-8")).hexdigest()[:12]
    readable = slug(rel).encode("utf-8")[:SLUG_BYTES].decode("utf-8", "ignore").lstrip(".") or "-"
    return "%s.%s%s" % (readable, digest, SUFFIX)


def record(machine, sid, now):
    return {"machine": machine, "sid": sid, "at": now}


def dumps(rec):
    return json.dumps(rec, ensure_ascii=False)


def parse(text):
    """A record from the file's text, or None when it is absent or not a valid record."""
    try:
        rec = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(rec, dict):
        return None
    at = rec.get("at")
    if not isinstance(rec.get("machine"), str) or not isinstance(rec.get("sid"), str):
        return None
    if isinstance(at, bool) or not isinstance(at, (int, float)):
        return None
    return {"machine": rec["machine"], "sid": rec["sid"], "at": at}


def decide(rec, machine, sid, now, ttl, cushion):
    """What an acquirer holding the lock does with the record it found.

      absent             -> 'take'
      held by me         -> 'renew'   (restarts the clock)
      held, past ttl+cushion -> 'steal'
      held and fresh     -> 'foreign', untouched

    An unreadable record counts as absent (the caller passes None).
    """
    if rec is None:
        return "take"
    if rec["machine"] == machine and rec["sid"] == sid:
        return "renew"
    if now - rec["at"] > ttl + cushion:
        return "steal"
    return "foreign"


def outcome(decision):
    """'mine' | 'foreign' for a decision."""
    return "foreign" if decision == "foreign" else "mine"


def may_release(rec, machine, sid):
    """Only the holder releases: never remove a lease another session holds."""
    return rec is not None and rec["machine"] == machine and rec["sid"] == sid


def owner(rec):
    """Who holds it, as `<machine>/<sid8>`: on one machine the sid is what tells sessions apart."""
    if not rec:
        return "?"
    return "%s/%s" % (rec["machine"], rec["sid"][:8])


# ------------------------------------------------------------------- local cache rows
def row_key(rel, sid=""):
    return slug(rel) + "|" + sid if sid else slug(rel)


def select_row(cache, rel, sid=""):
    """This session's row, falling back to the shared pre-sid one."""
    if sid and row_key(rel, sid) in cache:
        return cache[row_key(rel, sid)]
    return cache.get(slug(rel)) or {}


def row(state, owner_name, rel, sid, now, ttl, guard):
    """The cache row after an acquire or release. `valid_until` only for 'mine': the holder
    stops believing it holds at ttl - guard, before any other session may steal."""
    return {"state": state, "owner": owner_name, "seen": now, "note": rel, "sid": sid,
            "valid_until": now + ttl - guard if state == "mine" else 0}


def row_state(entry, now, ttl):
    """'mine' | 'foreign' | '' for a cache row, by the clock passed in."""
    if entry.get("state") == "mine" and now < (entry.get("valid_until") or 0):
        return "mine"
    if entry.get("state") == "foreign" and now - (entry.get("seen") or 0) < ttl:
        return "foreign"
    return ""
