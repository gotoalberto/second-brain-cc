#!/usr/bin/env python3
"""Tests for claims_core — the decisions behind cross-machine file claims.

claims_sync.py keeps one small JSON record per (resource, machine, session) under
`<shared>/claims/<resource>/<machine>__<sid>.json` on a shared filesystem path the user
configures (Dropbox, iCloud, a NAS — never S3). Which resource a file maps to, what a record
looks like, what a sync pass must write and delete, which foreign claims are worth a warning
and which records are old enough to reap are decided here. Pure: no disk, no clock, no
subprocess, no git. Run standalone:

    python3 _bin/claims_core_test.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import claims_core as C

ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def test_normalize_remote():
    want = "github.com/example-org/example-repo"
    for url in ("git@github.com:example-org/example-repo.git",
                "git@github.com:example-org/example-repo",
                "https://github.com/example-org/example-repo.git",
                "https://github.com/example-org/example-repo",
                "https://user@github.com/example-org/example-repo.git",
                "ssh://git@github.com/example-org/example-repo.git",
                "ssh://git@github.com:22/example-org/example-repo.git"):
        check("normalises %s" % url, C.normalize_remote(url) == want, C.normalize_remote(url))
    check("a trailing slash is stripped", C.normalize_remote("https://github.com/org/repo/") == "github.com/org/repo")
    check("an unrecognised shape gives no resource", C.normalize_remote("not a url") == "")
    check("empty gives no resource", C.normalize_remote("") == "")
    check("None gives no resource, not an exception", C.normalize_remote(None) == "")


def test_resource_for():
    origin = "git@github.com:example-org/example-repo.git"
    check("a file inside a repo maps under the normalised origin",
          C.resource_for(origin, "src/x.ts") == "github.com/example-org/example-repo/src/x.ts")
    check("leading and trailing slashes in the relative path do not matter",
          C.resource_for(origin, "/src/x.ts/") == "github.com/example-org/example-repo/src/x.ts")
    check("backslashes from a Windows-style path are normalised",
          C.resource_for(origin, "src\\x.ts") == "github.com/example-org/example-repo/src/x.ts")
    check("the repo root itself (no relative path) is just the origin",
          C.resource_for(origin, "") == "github.com/example-org/example-repo")
    check("no origin at all (outside any repo): no resource, nothing is shared for it",
          C.resource_for("", "src/x.ts") == "")
    check("an origin that does not parse: no resource either",
          C.resource_for("not a url", "src/x.ts") == "")


def test_filename_and_record_round_trip():
    check("a claim file is <machine>__<sid>.json", C.filename("laptop-a1b2c3d4", "abcd1234")
          == "laptop-a1b2c3d4__abcd1234.json")
    check("a machine name holding the separator cannot shift the sid",
          C.parse_record_name(C.filename("odd__host", "s1")) == ("odd_host", "s1"),
          C.parse_record_name(C.filename("odd__host", "s1")))
    for bad, why in (("no-json-suffix", "no .json suffix"), ("__s1.json", "no machine"),
                     ("laptop.json", "no separator"), ("laptop__.json", "no sid"), ("", "empty")):
        check("parse_record_name rejects %s" % why, C.parse_record_name(bad) is None, C.parse_record_name(bad))

    check("a resource path round-trips into (resource, machine, sid)",
          C.parse_resource_path("github.com/o/r/src/x.ts/laptop-a1b2c3d4__abcd1234.json")
          == ("github.com/o/r/src/x.ts", "laptop-a1b2c3d4", "abcd1234"))
    for bad, why in (("laptop__s1.json", "no resource directory"), ("", "empty"),
                     ("a/b/no-json-suffix", "not a claim file name")):
        check("parse_resource_path rejects %s" % why, C.parse_resource_path(bad) is None, C.parse_resource_path(bad))

    rec = C.record("laptop-a1b2c3d4", "abcd1234", 1000.0)
    check("a record holds machine, sid and time",
          rec == {"machine": "laptop-a1b2c3d4", "sid": "abcd1234", "at": 1000.0}, rec)
    check("dumps and parse round-trip", C.parse(C.dumps(rec)) == rec)
    for bad, why in (("", "empty text"), ("{", "broken JSON"), ("[]", "not an object"),
                     ('{"machine": "m", "sid": "s"}', "no time"), ('{"machine": "m", "at": 1}', "no sid"),
                     ('{"sid": "s", "at": 1}', "no machine"), ('{"machine": "m", "sid": "s", "at": "x"}', "a text time"),
                     ('{"machine": "m", "sid": "s", "at": true}', "a boolean time"), (None, "None")):
        check("parse rejects %s" % why, C.parse(bad) is None, C.parse(bad))


def _row(resource, machine, sid, at):
    return {"resource": resource, "machine": machine, "sid": sid, "at": at,
            "key": "%s/%s" % (resource, C.filename(machine, sid))}


def test_plan():
    now, ttl = 10000.0, 900.0
    remote = [
        _row("repo/a.ts", "laptop-a1b2c3d4", "s1", now - 10),      # mine, fresh, still wanted: untouched
        _row("repo/b.ts", "laptop-a1b2c3d4", "s1", now - 10),      # mine, fresh, no longer wanted: to_delete
        _row("repo/c.ts", "laptop-a1b2c3d4", "s1", now - ttl - 1), # mine, stale: renewed (to_put)
        _row("repo/d.ts", "laptop-b5e6f7a8", "s1", now - 10),      # somebody else's machine: never touched
        _row("repo/f.ts", "laptop-a1b2c3d4", "s2", now - 10),      # my machine, a DIFFERENT session: never touched
    ]
    local = ["repo/a.ts", "repo/c.ts", "repo/e.ts"]   # e.ts is brand new
    to_put, to_delete = C.plan(local, remote, "laptop-a1b2c3d4", "s1", now, ttl)
    check("a brand new local claim is published", "repo/e.ts" in to_put, to_put)
    check("a stale claim of mine is renewed", "repo/c.ts" in to_put, to_put)
    check("a fresh claim of mine that is still wanted is left alone", "repo/a.ts" not in to_put, to_put)
    check("nothing else is proposed for publishing", sorted(to_put) == ["repo/c.ts", "repo/e.ts"], to_put)
    check("a claim of mine no longer wanted is released", to_delete == ["repo/b.ts"], to_delete)
    check("another machine's claim is never proposed for deletion", "repo/d.ts" not in to_delete, to_delete)
    check("a DIFFERENT session's claim on my own machine is never proposed for deletion either",
          "repo/f.ts" not in to_delete, to_delete)

    check("nothing local and nothing remote: nothing to do",
          C.plan([], [], "laptop-a1b2c3d4", "s1", now, ttl) == ([], []))
    only_foreign = [_row("repo/d.ts", "laptop-b5e6f7a8", "s1", now)]
    check("only a foreign claim on the remote: nothing of mine to delete, nothing of mine to renew",
          C.plan([], only_foreign, "laptop-a1b2c3d4", "s1", now, ttl) == ([], []))


def test_foreign_claims():
    now, ttl = 10000.0, 900.0
    remote = [_row("repo/a.ts", "laptop-a1b2c3d4", "s1", now - 10),          # mine: excluded
              _row("repo/b.ts", "laptop-b5e6f7a8", "s2", now - 10),          # foreign, fresh: included
              _row("repo/c.ts", "laptop-b5e6f7a8", "s3", now - ttl - 1)]     # foreign, stale: excluded
    got = C.foreign_claims(remote, "laptop-a1b2c3d4", now, ttl)
    check("only a fresh claim held by another machine is reported",
          [r["resource"] for r in got] == ["repo/b.ts"], got)
    check("the row carries its age", got[0]["age"] == 10.0, got)
    check("nothing foreign gives nothing", C.foreign_claims([], "laptop-a1b2c3d4", now, ttl) == [])


def test_purgeable():
    now, ttl, margin = 10000.0, 900.0, 120.0
    remote = [_row("repo/a.ts", "m", "s1", now - ttl),                # exactly at ttl: not purgeable
              _row("repo/b.ts", "m", "s2", now - ttl - margin + 1),   # one second short of the margin: not yet
              _row("repo/c.ts", "m", "s3", now - ttl - margin),       # exactly at ttl + margin: purgeable
              _row("repo/d.ts", "m", "s4", now - ttl - margin - 1)]   # past it: purgeable
    keys = C.purgeable(remote, now, ttl, margin)
    check("only records at or past ttl + margin are purgeable",
          sorted(keys) == sorted([remote[2]["key"], remote[3]["key"]]), keys)
    check("nothing remote, nothing purgeable", C.purgeable([], now, ttl, margin) == [])
    check("a record with no readable time is skipped, not an error",
          C.purgeable([{"resource": "x", "machine": "m", "sid": "s", "at": "nope", "key": "x/m__s.json"}],
                     now, ttl, margin) == [])


def main():
    for t in (test_normalize_remote, test_resource_for, test_filename_and_record_round_trip, test_plan,
              test_foreign_claims, test_purgeable):
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
