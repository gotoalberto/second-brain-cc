#!/usr/bin/env python3
"""Tests for lease_core — the decisions behind lease.py's advisory write leases.

lease.py reads and writes one small file per note under <state>/locks/ while holding
B.flock. Which file a note maps to, what a lease record looks like, whether an acquirer takes,
renews, steals or backs off, who may release, and what the local cache says a session holds
are decided here. Pure: no disk, no clock, no subprocess. Run standalone:

    python3 _bin/lease_core_test.py
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import lease_core as C

ok, fail = [], []

TTL, GUARD, CUSHION = 1200.0, 120.0, 60.0
FLOCK_NAME = re.compile(r"^[0-9a-f]{16}\.lock$")


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def test_slug_and_filename():
    check("slug keeps the whole path readable", C.slug("10-Projects/my note.md") == "10-Projects__my_note.md")
    a, b = C.filename("10-Projects/a/b.md"), C.filename("10-Projects/a__b.md")
    check("two paths with the same slug get different lease files", a != b, (a, b))
    check("the same path always maps to the same file", C.filename("10-Projects/x.md") == C.filename("10-Projects/x.md"))
    check("a lease file is one path component", "/" not in C.filename("10-Projects/deep/er/x.md"))
    check("a lease file ends in .lease", C.filename("10-Projects/x.md").endswith(".lease"))
    for rel in ("10-Projects/x.md", "0123456789abcdef", "0123456789abcdef.lock", "a" * 16):
        name = C.filename(rel)
        check("a lease file never has the shape of a B.flock lock file (%s)" % rel[:24],
              not FLOCK_NAME.match(name), name)
    long_rel = "10-Projects/" + "ñ" * 400 + ".md"
    check("a very long note path still fits in one file name (255 bytes)",
          len(C.filename(long_rel).encode("utf-8")) <= 255, len(C.filename(long_rel).encode("utf-8")))
    check("a note path cannot produce a hidden or empty name", not C.filename(".hidden.md").startswith("."))


def test_record_round_trip():
    rec = C.record("laptop", "abcd1234", 1000.0)
    check("a record holds machine, sid and time", rec == {"machine": "laptop", "sid": "abcd1234", "at": 1000.0}, rec)
    check("dumps and parse round-trip", C.parse(C.dumps(rec)) == rec)
    for bad, why in (("", "empty text"), ("{", "broken JSON"), ("[]", "not an object"),
                     ('{"machine": "m", "sid": "s"}', "no time"), ('{"machine": "m", "at": 1}', "no sid"),
                     ('{"sid": "s", "at": 1}', "no machine"), ('{"machine": "m", "sid": "s", "at": "x"}', "a text time"),
                     ('{"machine": "m", "sid": "s", "at": true}', "a boolean time"), (None, "None")):
        check("parse rejects %s" % why, C.parse(bad) is None, C.parse(bad))


def test_decide():
    now = 10000.0
    mine = C.record("laptop", "s1", now - 100)
    check("absent: take", C.decide(None, "laptop", "s1", now, TTL, CUSHION) == "take")
    check("held by this session: renew", C.decide(mine, "laptop", "s1", now, TTL, CUSHION) == "renew")
    check("held by this session even long expired: renew",
          C.decide(C.record("laptop", "s1", 0), "laptop", "s1", now, TTL, CUSHION) == "renew")
    fresh = C.record("laptop", "s2", now - TTL)
    check("another session, within TTL + cushion: foreign", C.decide(fresh, "laptop", "s1", now, TTL, CUSHION) == "foreign")
    edge = C.record("laptop", "s2", now - TTL - CUSHION)
    check("another session exactly at TTL + cushion: still foreign",
          C.decide(edge, "laptop", "s1", now, TTL, CUSHION) == "foreign")
    stale = C.record("laptop", "s2", now - TTL - CUSHION - 1)
    check("another session past TTL + cushion: steal", C.decide(stale, "laptop", "s1", now, TTL, CUSHION) == "steal")
    check("same sid on another machine name is not this session",
          C.decide(C.record("other", "s1", now), "laptop", "s1", now, TTL, CUSHION) == "foreign")
    check("outcome: take, renew and steal make the caller the holder",
          [C.outcome(d) for d in ("take", "renew", "steal")] == ["mine"] * 3)
    check("outcome: foreign stays foreign", C.outcome("foreign") == "foreign")


def test_release_and_owner():
    rec = C.record("laptop", "s1", 1.0)
    check("the holder may release", C.may_release(rec, "laptop", "s1") is True)
    check("another session may not", C.may_release(rec, "laptop", "s2") is False)
    check("nothing to release when absent", C.may_release(None, "laptop", "s1") is False)
    check("owner names the machine and the short sid",
          C.owner(C.record("laptop", "abcdef1234567890", 1.0)) == "laptop/abcdef12")
    check("no record, unknown owner", C.owner(None) == "?")


def test_cache_rows():
    now = 5000.0
    check("a session's row key carries the sid", C.row_key("10-Projects/x.md", "s1") == "10-Projects__x.md|s1")
    check("without a sid the row key is the slug", C.row_key("10-Projects/x.md", "") == "10-Projects__x.md")
    row = C.row("mine", "laptop/s1", "10-Projects/x.md", "s1", now, TTL, GUARD)
    check("a 'mine' row is valid until TTL - GUARD", row["valid_until"] == now + TTL - GUARD, row)
    check("a 'foreign' row has no validity of its own",
          C.row("foreign", "laptop/s2", "10-Projects/x.md", "s1", now, TTL, GUARD)["valid_until"] == 0)
    check("a row remembers note, sid, owner and when it was seen",
          (row["note"], row["sid"], row["owner"], row["seen"]) == ("10-Projects/x.md", "s1", "laptop/s1", now), row)
    cache = {"10-Projects__x.md|s1": row, "10-Projects__x.md": {"state": "foreign", "seen": now}}
    check("select_row prefers this session's row", C.select_row(cache, "10-Projects/x.md", "s1") is row)
    check("select_row falls back to the shared row",
          C.select_row(cache, "10-Projects/x.md", "s9").get("state") == "foreign")
    check("select_row with nothing gives an empty row", C.select_row({}, "10-Projects/y.md", "s1") == {})
    check("mine, before valid_until", C.row_state(row, now + 10, TTL) == "mine")
    check("mine, after valid_until, says nothing", C.row_state(row, now + TTL - GUARD, TTL) == "")
    foreign = {"state": "foreign", "seen": now}
    check("foreign, seen within TTL", C.row_state(foreign, now + TTL - 1, TTL) == "foreign")
    check("foreign, seen too long ago, says nothing", C.row_state(foreign, now + TTL, TTL) == "")
    check("an empty or released row says nothing",
          C.row_state({}, now, TTL) == "" and C.row_state({"state": ""}, now, TTL) == "")
    check("a row with None times says nothing, not an error",
          C.row_state({"state": "mine", "valid_until": None}, now, TTL) == ""
          and C.row_state({"state": "foreign", "seen": None}, now, TTL) == "")


def main():
    for t in (test_slug_and_filename, test_record_round_trip, test_decide, test_release_and_owner, test_cache_rows):
        print("\n== %s ==" % t.__name__)
        try:
            t()
        except Exception as exc:
            check("%s ran without raising" % t.__name__, False, repr(exc))
    return finish()


def finish():
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
