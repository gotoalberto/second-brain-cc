#!/usr/bin/env python3
"""Tests for handoff_core.domain: the pure rules of the one-time handoff for a new machine.

No IO: the token, the MAC, expiry, the transport choice, the payload manifest, the archive
member check, the sweep and where redeemed files land. Run standalone:

    python3 _bin/handoff_core/domain_test.py
"""
import json
import os
import sys

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
    except Exception:
        return None
    return None


ID = "0123456789abcdef0123456789abcdef"


def test_token(D):
    print("\n== the token ==")
    t = D.Token(transport="shared", id=ID, passphrase="p" * 32, issued_at=1000, ttl=1200, mac="ab" * 32,
                directory="/srv/sync/handoff")
    s = D.encode_token(t)
    check("a token starts with the version prefix", s.startswith(D.TOKEN_PREFIX), s[:10])
    check("a token is one string with no spaces, quotes or padding",
          all(ch not in s for ch in " \n'\"=") and len(s.split()) == 1, s)
    check("a file token round trips", D.decode_token(s) == t, D.decode_token(s))
    inline = D.Token(transport="inline", id=ID, passphrase="q" * 32, issued_at=5, ttl=60, mac="cd" * 32,
                     ciphertext=b"\x00\x01binary\xff" * 50)
    s2 = D.encode_token(inline)
    check("an inline token round trips with its ciphertext", D.decode_token(s2) == inline)
    check("the inline ciphertext rides in its own segment, not base64 inside base64",
          s2.count(".") == 2 and len(s2) < len(inline.ciphertext) * 1.5 + 400, len(s2))
    check("surrounding whitespace from a paste is forgiven", D.decode_token("  %s\n" % s) == t)
    for bad in ("", "sbh1.", "sbh2." + s[5:], s[:-3] + "!!!", "hello", s[:20]):
        check("%r is refused as a token" % bad[:24], raises(D.decode_token, D.HandoffError, bad) is not None)
    body = json.dumps({"v": 1, "t": "carrier-pigeon", "id": ID, "p": "x" * 32, "iat": 1, "ttl": 60, "mac": "ab" * 32})
    check("an unknown transport is refused", raises(D.decode_token, D.HandoffError, D.TOKEN_PREFIX + D.b64e(body.encode()))
          is not None)
    body = json.dumps({"v": 1, "t": "shared", "id": "../../etc", "p": "x" * 32, "iat": 1, "ttl": 60, "mac": "ab" * 32})
    check("an id that is not hex is refused (it becomes a file name)",
          raises(D.decode_token, D.HandoffError, D.TOKEN_PREFIX + D.b64e(body.encode())) is not None)
    check("an inline token without its ciphertext is refused",
          raises(D.decode_token, D.HandoffError, D.encode_token(inline).rsplit(".", 1)[0]) is not None)


def test_mac(D):
    print("\n== the MAC over the ciphertext ==")
    m = D.mac("pass-one", b"ciphertext")
    check("the MAC is hex SHA-256", len(m) == 64 and int(m, 16) >= 0, m)
    check("the same passphrase and ciphertext give the same MAC", m == D.mac("pass-one", b"ciphertext"))
    check("a verified MAC passes", D.mac_ok("pass-one", b"ciphertext", m))
    check("one flipped byte fails", not D.mac_ok("pass-one", b"ciphertexu", m))
    check("another passphrase fails", not D.mac_ok("pass-two", b"ciphertext", m))
    check("a malformed MAC fails instead of raising", not D.mac_ok("pass-one", b"ciphertext", "zz"))
    check("the MAC key is derived, not the passphrase itself",
          D.mac_key("pass-one") != b"pass-one" and len(D.mac_key("pass-one")) == 32)


def test_expiry(D):
    print("\n== expiry ==")
    check("inside the ttl is fine", D.expiry_problem("shared", 1000, 1200, 1000 + 1199, False) is None)
    msg = D.expiry_problem("shared", 1000, 1200, 1000 + 1201, False)
    check("after the ttl it is refused and says to issue a new one", msg and "issue" in msg, msg)
    check("--ignore-expiry lets a file token through inside the hour",
          D.expiry_problem("shared", 1000, 1200, 1000 + 1800, True) is None)
    msg = D.expiry_problem("path", 1000, 1200, 1000 + 3601, True)
    check("--ignore-expiry is refused for a file token older than an hour", msg and "hour" in msg, msg)
    check("--ignore-expiry lets an old inline token through (the token is the payload)",
          D.expiry_problem("inline", 1000, 1200, 1000 + 86400, True) is None)
    check("a clock a little behind the issuer is not an error", D.expiry_problem("inline", 1000, 60, 990, False) is None)
    check("a ttl in minutes becomes seconds", D.ttl_seconds(20) == 1200)
    for bad in (0, -1, 61, "x"):
        check("a ttl of %r minutes is refused" % (bad,), raises(D.ttl_seconds, D.UsageError, bad) is not None)


def test_transport(D):
    print("\n== choosing the transport ==")
    check("with a shared dir the default is shared", D.choose_transport(None, "/sync") == ("shared", "/sync/handoff"))
    check("without one the default is inline", D.choose_transport(None, None) == ("inline", None))
    check("--to inline stays inline even with a shared dir", D.choose_transport("inline", "/sync") == ("inline", None))
    check("--to shared without a shared dir is refused",
          raises(D.choose_transport, D.UsageError, "shared", None) is not None)
    check("--to PATH writes into that directory", D.choose_transport("/media/usb", None) == ("path", "/media/usb"))
    check("--to with a relative path is refused (it would depend on the working directory)",
          raises(D.choose_transport, D.UsageError, "usb", None) is not None)
    check("the file name carries the id", D.handoff_file_name(ID) == "handoff-%s.enc" % ID)
    check("a fresh id is 32 hex characters", D.valid_id(ID) and not D.valid_id("xyz") and not D.valid_id(ID[:-1]))


def test_inline_limit(D):
    print("\n== the inline size limit ==")
    check("a small inline payload is fine", D.inline_problem(1000) is None)
    msg = D.inline_problem(D.INLINE_MAX + 1)
    check("an inline payload over the limit is refused and points at --to PATH", msg and "--to" in msg, msg)
    check("the limit is about 64 KiB", D.INLINE_MAX == 64 * 1024)


def test_manifest(D):
    print("\n== the payload manifest ==")
    src = D.Source(db="/home/a/Sync/vault/brain.kdbx", keyfile="/home/a/.config/brain/brain.key", group="Brain",
                   shared_dir="/home/a/Sync", files_dir="/home/a/BrainFiles", google_accounts=["work", "personal"],
                   home="/home/a")
    s = D.settings_for(src, with_db=False)
    check("the settings record the kdbx path, its place under the shared dir and under home",
          s["db"] == src.db and s["db_shared_rel"] == "vault/brain.kdbx" and s["db_home_rel"] == "Sync/vault/brain.kdbx", s)
    check("the settings record the shared dir, files dir, group and account names",
          s["shared_dir"] == "/home/a/Sync" and s["files_dir"] == "/home/a/BrainFiles" and s["kp_group"] == "Brain"
          and s["google_accounts"] == ["personal", "work"], s)
    check("the keyfile is named and placed home-relative", s["keyfile_name"] == "brain.key"
          and s["keyfile_home_rel"] == ".config/brain/brain.key", s)
    check("the database is not carried unless asked", s["db_carried"] is False)
    check("no field could hold a secret", not any(k in s for k in ("password", "master", "token", "refresh_token")), s)
    check("the members are the settings and the keyfile", D.expected_members(s) == ["keyfile", "settings.json"],
          D.expected_members(s))
    s2 = D.settings_for(src, with_db=True)
    check("with the database the members include it", D.expected_members(s2) == ["database.kdbx", "keyfile", "settings.json"])
    bare = D.settings_for(D.Source(db="/elsewhere/x.kdbx", keyfile="", home="/home/a"), with_db=False)
    check("no keyfile, no shared dir: only settings, and nothing relative",
          D.expected_members(bare) == ["settings.json"] and bare["db_shared_rel"] is None and bare["db_home_rel"] is None,
          bare)
    check("a path merely sharing a prefix is not under the dir", D.relative_under("/home/ab/x", "/home/a") is None)
    check("the dir itself is not a file under it", D.relative_under("/home/a", "/home/a") is None)
    check("a db not under the shared dir and not carried is flagged", D.db_needs_copy(bare) is True)
    check("a db under the shared dir is not flagged", D.db_needs_copy(s) is False)
    check("a carried db is not flagged", D.db_needs_copy(D.settings_for(D.Source(db="/x/y.kdbx"), with_db=True)) is False)
    check("settings parse back", D.parse_settings(json.dumps(s).encode()) == s)
    check("settings that are not an object are refused",
          raises(D.parse_settings, D.HandoffError, b"[1]") is not None)


def test_members(D):
    print("\n== archive members ==")
    good = [D.Member("settings.json", "file"), D.Member("keyfile", "file")]
    check("the expected regular files pass", D.member_problem(good, ["keyfile", "settings.json"]) is None)
    cases = [
        ("an absolute path", [D.Member("/etc/passwd", "file")]),
        ("a .. component", [D.Member("../keyfile", "file")]),
        ("a nested path", [D.Member("sub/keyfile", "file")]),
        ("a symlink", [D.Member("keyfile", "symlink")]),
        ("a hard link", [D.Member("keyfile", "hardlink")]),
        ("a directory", [D.Member("keyfile", "dir")]),
        ("an unexpected name", [D.Member("authorized_keys", "file")]),
        ("a duplicate", [D.Member("keyfile", "file"), D.Member("keyfile", "file")]),
    ]
    for what, extra in cases:
        members = [D.Member("settings.json", "file")] + extra
        check("%s is refused" % what, D.member_problem(members, ["keyfile", "settings.json"]) is not None)
    check("a missing member is refused", D.member_problem([D.Member("settings.json", "file")],
                                                          ["keyfile", "settings.json"]) is not None)
    check("the settings are always required", D.member_problem([D.Member("keyfile", "file")], ["keyfile"]) is not None)


def test_sweep(D):
    print("\n== the sweep ==")
    entries = [("handoff-%s.enc" % ID, 1000.0), ("handoff-%s.enc" % ("f" * 32), 4000.0),
               ("notes.txt", 0.0), ("handoff-short.enc", 0.0)]
    check("only handoff files older than an hour are swept, nothing else in the folder",
          D.to_sweep(entries, now=1000.0 + 3601) == ["handoff-%s.enc" % ID], D.to_sweep(entries, now=4601))
    check("nothing is swept inside the hour", D.to_sweep(entries, now=1500.0) == [])


def test_targets(D):
    print("\n== where redeemed files land ==")
    s = D.settings_for(D.Source(db="/home/a/Documents/brain.kdbx", keyfile="/home/a/.config/brain/brain.key",
                                home="/home/a"), with_db=True)
    t = D.redeem_targets(s, home="/home/b", state="/state")
    check("files under the issuer's home land at the same place under this home",
          t == {"keyfile": "/home/b/.config/brain/brain.key", "database.kdbx": "/home/b/Documents/brain.kdbx"}, t)
    s = D.settings_for(D.Source(db="/srv/db/brain.kdbx", keyfile="/srv/keys/k.key", home="/home/a"), with_db=True)
    t = D.redeem_targets(s, home="/home/b", state="/state")
    check("files outside the issuer's home land in the state dir",
          t == {"keyfile": "/state/k.key", "database.kdbx": "/state/brain.kdbx"}, t)
    s = D.settings_for(D.Source(db="/home/a/Sync/brain.kdbx", keyfile="/home/a/k.key", shared_dir="/home/a/Sync",
                                home="/home/a"), with_db=False)
    check("a database not carried gets no target", "database.kdbx" not in D.redeem_targets(s, "/home/b", "/state"))
    c = D.db_candidates(s, home="/home/b", local_shared="/mnt/sync")
    check("the database is looked for under this machine's shared dir first, then home, then as recorded",
          c == ["/mnt/sync/brain.kdbx", "/home/b/Sync/brain.kdbx", "/home/a/Sync/brain.kdbx"], c)
    check("without a local shared dir the issuer's shared dir is tried as recorded",
          D.db_candidates(s, home="/home/b", local_shared=None)[0] == "/home/a/Sync/brain.kdbx",
          D.db_candidates(s, home="/home/b", local_shared=None))
    evil = dict(s, keyfile_name="../../x", keyfile_home_rel="../../etc/x")
    check("a keyfile name with a path in it is refused",
          raises(D.redeem_targets, D.HandoffError, evil, "/home/b", "/state") is not None)


def test_kp_init(D):
    print("\n== the kp.py init command ==")
    check("with a keyfile it passes --keyfile", D.kp_init_args("/d.kdbx", "/k") == ["init", "--db", "/d.kdbx", "--keyfile", "/k"])
    check("without one it does not", D.kp_init_args("/d.kdbx", None) == ["init", "--db", "/d.kdbx"])
    check("the issuer's group is kept", D.kp_init_args("/d", None, "Agents") == ["init", "--db", "/d", "--group", "Agents"])
    check("an old kp.py without --keyfile is recognised by its usage error",
          D.kp_lacks_keyfile_flag(2, "kp.py: error: unrecognized arguments: --keyfile /k")
          and not D.kp_lacks_keyfile_flag(0, "") and not D.kp_lacks_keyfile_flag(6, "no database"))
    merged = D.merged_kp_config({"db": "/old", "inbox": "/i"}, "/d.kdbx", "/k", "Brain")
    check("the fallback config merges db, keyfile and group into what is there",
          merged == {"db": "/d.kdbx", "inbox": "/i", "keyfile": "/k", "group": "Brain"}, merged)


def main():
    try:
        from handoff_core import domain as D
    except Exception as exc:
        check("handoff_core.domain imports", False, "%s: %s" % (type(exc).__name__, exc))
    else:
        for t in (test_token, test_mac, test_expiry, test_transport, test_inline_limit, test_manifest, test_members,
                  test_sweep, test_targets, test_kp_init):
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
