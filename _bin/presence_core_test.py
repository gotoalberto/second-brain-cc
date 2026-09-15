#!/usr/bin/env python3
"""Tests for presence_core — the naming and age rules behind presence.py.

presence.py keeps one empty file per live session under <state>/presence/ and reads the file
names and mtimes back. What those names mean, how old a session is, who counts as alive and
which leftovers get purged is decided here, with no filesystem. Pure: no disk, no clock, no
subprocess. Run standalone:

    python3 _bin/presence_core_test.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import presence_core as C

ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def test_key_layout():
    check("a key is <project>/<machine>__<sid>", C.key("demo", "laptop", "abcd1234") == "demo/laptop__abcd1234",
          C.key("demo", "laptop", "abcd1234"))
    check("no project is written as '-'", C.key("", "laptop", "abcd1234") == "-/laptop__abcd1234")
    check("None as project is written as '-'", C.key(None, "laptop", "abcd1234") == "-/laptop__abcd1234")
    check("a slash in the project cannot add a directory level",
          C.key("a/b", "laptop", "s1").count("/") == 1, C.key("a/b", "laptop", "s1"))
    check("a project cannot climb out of the presence directory",
          not C.key("..", "laptop", "s1").startswith(".."), C.key("..", "laptop", "s1"))
    check("a hidden-looking project loses its leading dots",
          C.key(".secret", "laptop", "s1") == "secret/laptop__s1", C.key(".secret", "laptop", "s1"))
    check("a machine name holding the separator cannot shift the sid",
          C.parse_key(C.key("demo", "odd__host", "s1")) == ("demo", "odd_host", "s1"),
          C.parse_key(C.key("demo", "odd__host", "s1")))
    check("a sid with a slash stays one file name", C.key("demo", "laptop", "a/b").count("/") == 1)


def test_parse_key():
    check("a key round-trips", C.parse_key(C.key("demo", "laptop", "abcd1234")) == ("demo", "laptop", "abcd1234"))
    check("the sid keeps a later separator", C.parse_key("demo/laptop__ab__cd") == ("demo", "laptop", "ab__cd"))
    for bad, why in (("demo", "no directory level"), ("demo/laptop", "no separator"),
                     ("a/b/laptop__s1", "one level too deep"), ("demo/__s1", "no machine"),
                     ("demo/laptop__", "no sid"), ("/laptop__s1", "no project"), ("", "empty")):
        check("rejects a key with %s" % why, C.parse_key(bad) is None, C.parse_key(bad))


def test_rows():
    now = 10000.0
    entries = [("demo/laptop__mine", now - 10), ("demo/laptop__other", now - 899.9),
               ("-/laptop__edge", now - 900), ("demo/laptop__gone", now - 901),
               ("junk", now), ("demo/laptop__bad", "not-a-time")]
    got = C.rows(entries, now, 900.0, own_sid="mine")
    alive = sorted(r["sid"] for r in got["alive"])
    expired = sorted(r["sid"] for r in got["expired"])
    check("sessions within the TTL are alive, this session left out", alive == ["edge", "other"], got)
    check("a heartbeat exactly TTL old still counts as alive", "edge" in alive)
    check("older than the TTL is expired", expired == ["gone"], got)
    check("unparseable names and times are ignored", len(got["alive"]) + len(got["expired"]) == 3, got)
    check("read_at is the clock passed in", got["read_at"] == now)
    row = [r for r in got["alive"] if r["sid"] == "other"][0]
    check("a row carries machine, sid, project, rounded age and key",
          row == {"machine": "laptop", "sid": "other", "project": "demo", "age": 899.9,
                  "key": "demo/laptop__other"}, row)
    mine = C.rows([("demo/laptop__mine", now)], now, 900.0, own_sid="mine")
    check("this session is still reported when expired", C.rows([("demo/laptop__mine", 0)], now, 900.0,
                                                                 own_sid="mine")["expired"] != [])
    check("this session alone gives nobody else alive", mine["alive"] == [], mine)
    check("no own sid keeps everyone", len(C.rows(entries, now, 900.0)["alive"]) == 3)
    check("no entries, nobody", C.rows([], now, 900.0) == {"alive": [], "expired": [], "read_at": now})


def test_purgeable():
    expired = [{"key": "demo/a__1", "age": 3601.0}, {"key": "demo/a__2", "age": 3600.0},
               {"key": "demo/a__3", "age": 1000.0}, {"key": "demo/a__4"}]
    check("only heartbeats past four TTLs are purged", C.purgeable(expired, 900.0) == ["demo/a__1"],
          C.purgeable(expired, 900.0))
    check("the factor is adjustable", C.purgeable(expired, 900.0, factor=1) == ["demo/a__1", "demo/a__2", "demo/a__3"])
    check("nothing expired, nothing purged", C.purgeable([], 900.0) == [])


def test_beat_due():
    check("never attempted is due", C.beat_due(None, 1000.0, 120.0) is True)
    check("attempted a minute ago is not due", C.beat_due(940.0, 1000.0, 120.0) is False)
    check("attempted exactly EVERY ago is due", C.beat_due(880.0, 1000.0, 120.0) is True)
    check("an attempt stamped in the future is not due", C.beat_due(1100.0, 1000.0, 120.0) is False)


def test_cache_view():
    fresh = {"alive": [{"sid": "x"}], "read_at": 1000.0}
    check("a fresh cache is returned as is", C.cache_view(fresh, 1500.0, 900.0) is fresh)
    check("a stale cache says nothing", C.cache_view(fresh, 1901.0, 900.0) == {})
    check("no read_at is stale", C.cache_view({"alive": []}, 1000.0, 900.0) == {})
    check("a None read_at is stale, not an error", C.cache_view({"read_at": None}, 1000.0, 900.0) == {})
    check("something that is not a dict is nothing", C.cache_view(["x"], 1000.0, 900.0) == {})


def main():
    for t in (test_key_layout, test_parse_key, test_rows, test_purgeable, test_beat_due, test_cache_view):
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
