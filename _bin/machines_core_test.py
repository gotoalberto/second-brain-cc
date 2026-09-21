#!/usr/bin/env python3
"""Tests for machines_core: the pure rules behind the machine registry.

machines.py keeps one JSON file per machine and reads them back. What a record looks like, how
`claude auth status` is read, how a new registration merges into the old one and how several
records of one machine collapse into one are decided here. Pure: no disk, no clock, no
subprocess. Every name and id below is invented for this test (`laptop-a`, `aaaaaaaa`); none is
a real machine's identity. Run standalone:

    python3 _bin/machines_core_test.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import machines_core as C

ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def info(**over):
    base = {"key": "laptop-a-aaaaaaaa", "id8": "aaaaaaaa", "label": "laptop-a", "os": "linux",
            "user": "someone", "claude_account": "someone@example.com", "claude_org": ""}
    base.update(over)
    return base


def test_parse_claude_auth():
    out = json.dumps({"loggedIn": True, "email": "someone@example.com", "orgName": "Example Org"})
    check("a logged-in answer gives the account and org",
          C.parse_claude_auth(out) == ("someone@example.com", "Example Org"), C.parse_claude_auth(out))
    check("logged out is said as such", C.parse_claude_auth(json.dumps({"loggedIn": False})) == ("logged out", ""))
    check("logged in with no email is unknown, not empty",
          C.parse_claude_auth(json.dumps({"loggedIn": True})) == (C.UNKNOWN_ACCOUNT, ""))
    check("output that is not JSON is unknown", C.parse_claude_auth("command not found") == (C.UNKNOWN_ACCOUNT, ""))
    check("a JSON list is unknown", C.parse_claude_auth("[1, 2]") == (C.UNKNOWN_ACCOUNT, ""))
    check("None is unknown, not an exception", C.parse_claude_auth(None) == (C.UNKNOWN_ACCOUNT, ""))


def test_parse_record():
    rec = C.merge(None, info(), "2026-01-02")[0]
    text = C.dump(rec)
    check("a dumped record parses back to itself", C.parse(text) == rec, (C.parse(text), rec))
    check("a record is one JSON object ending in a newline", text.endswith("}\n") and json.loads(text) == rec)
    check("garbage is not a record", C.parse("{not json") is None)
    check("a JSON object with no key is not a record", C.parse(json.dumps({"label": "x"})) is None)
    check("a JSON list is not a record", C.parse("[]") is None)
    check("None is not a record", C.parse(None) is None)
    check("unknown fields are dropped and missing ones read as empty",
          C.parse(json.dumps({"key": "k", "extra": 1})) == dict({f: "" for f in C.FIELDS}, key="k"),
          C.parse(json.dumps({"key": "k", "extra": 1})))
    check("the record carries no full uuid field", "uuid" not in C.FIELDS and "machine_uuid" not in C.FIELDS)


def test_filename():
    check("a key becomes <key>.json", C.filename("laptop-a-aaaaaaaa") == "laptop-a-aaaaaaaa.json")
    check("a slash cannot add a directory level", "/" not in C.filename("a/b") and "\\" not in C.filename("a\\b"))
    check("a key cannot climb out of the folder", not C.filename("..").startswith("."))
    check("an empty key still gives a file name", C.filename("") == "machine.json")


def test_merge():
    rec, changed = C.merge(None, info(), "2026-01-02")
    check("a first registration is a change", changed)
    check("first and last seen are today on a first registration",
          rec["first_seen"] == "2026-01-02" and rec["last_seen"] == "2026-01-02", rec)
    again, changed = C.merge(rec, info(), "2026-01-02")
    check("the same machine, the same day, nothing new: no write", not changed and again == rec, again)
    later, changed = C.merge(rec, info(), "2026-01-03")
    check("a new day refreshes last_seen and keeps first_seen",
          changed and later["last_seen"] == "2026-01-03" and later["first_seen"] == "2026-01-02", later)
    moved, changed = C.merge(rec, info(user="other"), "2026-01-02")
    check("a changed field is a change the same day", changed and moved["user"] == "other", moved)
    blind, changed = C.merge(rec, info(claude_account=C.UNKNOWN_ACCOUNT), "2026-01-02")
    check("a probe that could not answer keeps the account already known",
          not changed and blind["claude_account"] == "someone@example.com", blind)
    earliest, _ = C.merge(None, info(), "2026-01-05", first_seen="2025-12-30")
    check("a first_seen carried over from an older record of this machine is kept",
          earliest["first_seen"] == "2025-12-30", earliest)
    check("the input is not mutated", info()["claude_account"] == "someone@example.com" and rec["last_seen"] == "2026-01-02")


def test_same_machine():
    a = info()
    check("the same uuid fragment is the same machine under another name",
          C.same_machine(a, info(key="old-name-aaaaaaaa", label="old-name")))
    check("another fragment with the same hostname is another machine",
          not C.same_machine(a, info(key="laptop-a-bbbbbbbb", id8="bbbbbbbb")))
    check("with no fragment on either side, only the same key is the same machine",
          C.same_machine(info(key="box", id8=""), info(key="box", id8=""))
          and not C.same_machine(info(key="box", id8=""), info(key="box2", id8="")))
    check("a fragment on one side only is not enough", not C.same_machine(a, info(key="laptop-a", id8="")))


def test_first_seen_elsewhere():
    records = [C.merge(None, info(key="old-name-aaaaaaaa", label="old-name"), "2025-11-01")[0],
               C.merge(None, info(key="older-aaaaaaaa", label="older"), "2025-10-01")[0],
               C.merge(None, info(key="laptop-b-bbbbbbbb", id8="bbbbbbbb"), "2025-01-01")[0]]
    check("the earliest first_seen among this machine's older records",
          C.first_seen_elsewhere(records, info()) == "2025-10-01", C.first_seen_elsewhere(records, info()))
    check("another machine's record is never borrowed",
          C.first_seen_elsewhere(records[2:], info()) == "")


def test_dedupe():
    rows = [C.merge(None, info(key="old-name-aaaaaaaa", label="old-name"), "2026-01-01")[0],
            C.merge(None, info(), "2026-01-05")[0],
            C.merge(None, info(key="laptop-b-bbbbbbbb", id8="bbbbbbbb", label="laptop-b"), "2026-01-03")[0],
            C.merge(None, info(key="box", id8="", label="box"), "2026-01-04")[0]]
    got = C.dedupe(rows)
    check("four records of three machines collapse to three", len(got) == 3, got)
    check("newest first", [m["entry"]["key"] for m in got] == ["laptop-a-aaaaaaaa", "box", "laptop-b-bbbbbbbb"],
          [m["entry"]["key"] for m in got])
    check("the older name is kept as an alias of the newest record",
          got[0]["aliases"] == ["old-name-aaaaaaaa"], got[0])
    check("a machine with one record has no aliases", got[1]["aliases"] == [] and got[2]["aliases"] == [])
    check("nothing in, nothing out", C.dedupe([]) == [])


def test_days_since():
    check("days since last seen", C.days_since("2026-01-01", "2026-01-15") == 14)
    check("seen today is 0", C.days_since("2026-01-15", "2026-01-15") == 0)
    check("an unreadable date is None", C.days_since("garbage", "2026-01-15") is None)


def test_render_list():
    rows = [C.merge(None, info(key="old-name-aaaaaaaa", label="old-name"), "2026-01-01")[0],
            C.merge(None, info(), "2026-01-15")[0],
            C.merge(None, info(key="laptop-b-bbbbbbbb", id8="bbbbbbbb", label="laptop-b",
                               claude_account=C.UNKNOWN_ACCOUNT), "2025-12-01")[0]]
    text = C.render_list(C.dedupe(rows), lambda k: k == "laptop-a-aaaaaaaa", "2026-01-15")
    check("this machine is starred", "* laptop-a-aaaaaaaa" in text, text)
    check("another machine is not", "  laptop-b-bbbbbbbb" in text, text)
    check("an older name is shown as an alias", "also registered as old-name-aaaaaaaa" in text, text)
    check("a machine not seen for a while says so", "not seen in 45 days" in text, text)
    check("the count names machines and records", "2 machine(s), 3 record(s)" in text, text)
    check("an empty registry says how to fill it", "register" in C.render_list([], lambda k: False, "2026-01-15"))


def main():
    for t in (test_parse_claude_auth, test_parse_record, test_filename, test_merge, test_same_machine,
              test_first_seen_elsewhere, test_dedupe, test_days_since, test_render_list):
        print("\n== %s ==" % t.__name__)
        try:
            t()
        except Exception as exc:
            check("%s ran without raising" % t.__name__, False, repr(exc))
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
