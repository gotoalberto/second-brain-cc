#!/usr/bin/env python3
"""Tests for machine_identity — the key that tells apart two machines sharing a hostname.

Pure: no disk, no subprocess, no real hardware UUID. Every fixture below is invented for this
test (`AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE`, `laptop-a`); none is a real machine's identity.
Run standalone:

    python3 _bin/machine_identity_test.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import machine_identity as M

ok, fail = [], []

FAKE_UUID = "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def test_sanitize_hostname():
    check("a plain hostname is kept as-is", M.sanitize_hostname("laptop-a") == "laptop-a")
    check("only the first label of a FQDN is kept", M.sanitize_hostname("laptop-a.local") == "laptop-a")
    check("a slash cannot smuggle a path component in", M.sanitize_hostname("weird/name") == "weird_name")
    check("a backslash is treated the same way", M.sanitize_hostname("weird\\name") == "weird_name")
    check("an empty hostname falls back to a placeholder", M.sanitize_hostname("") == "machine")
    check("None is handled the same way as empty", M.sanitize_hostname(None) == "machine")
    check("surrounding whitespace is trimmed", M.sanitize_hostname("  laptop-a  ") == "laptop-a")


def test_machine_key():
    check("hostname plus the first 8 hex of the uuid, lowercased",
          M.machine_key("laptop-a", FAKE_UUID) == "laptop-a-aaaaaaaa", M.machine_key("laptop-a", FAKE_UUID))
    check("a uuid with no dashes works the same way",
          M.machine_key("laptop-a", FAKE_UUID.replace("-", "")) == "laptop-a-aaaaaaaa")
    check("no uuid at all: the key is just the sanitised hostname",
          M.machine_key("laptop-a", "") == "laptop-a")
    check("None for the uuid is the same as no uuid", M.machine_key("laptop-a", None) == "laptop-a")
    check("a uuid that is not hex falls back to the hostname alone",
          M.machine_key("laptop-a", "not-a-hex-value-at-all-zzzzzzzz") == "laptop-a")
    check("a uuid shorter than 8 hex characters falls back too",
          M.machine_key("laptop-a", "AB12") == "laptop-a")
    check("the hostname is sanitised inside machine_key as well",
          M.machine_key("laptop-a.local", FAKE_UUID) == "laptop-a-aaaaaaaa")
    check("two different fake machines never collide",
          M.machine_key("laptop-a", FAKE_UUID) != M.machine_key("laptop-b", FAKE_UUID))
    check("the same hostname with two different fake uuids does not collide either",
          M.machine_key("laptop-a", FAKE_UUID) != M.machine_key("laptop-a", "BBBBBBBB-0000-0000-0000-000000000000"))


def test_parse_ioreg_uuid():
    fixture = ('+-o J293AP  <class IOPlatformExpertDevice, id 0x100000200>\n'
               '    "IOPlatformUUID" = "%s"\n'
               '    "IOPlatformSerialNumber" = "FAKE-SERIAL-0001"\n' % FAKE_UUID)
    check("the uuid is pulled out of a realistic ioreg block", M.parse_ioreg_uuid(fixture) == FAKE_UUID, fixture)
    check("no IOPlatformUUID line: empty string, not an exception", M.parse_ioreg_uuid("nothing here") == "")
    check("empty input: empty string", M.parse_ioreg_uuid("") == "")
    check("None input: empty string, no exception", M.parse_ioreg_uuid(None) == "")


def test_parse_machine_id():
    bare = FAKE_UUID.replace("-", "").lower()
    check("a bare 32-hex line is accepted", M.parse_machine_id(bare + "\n") == bare)
    check("dashes are not the /etc/machine-id shape and are rejected", M.parse_machine_id(FAKE_UUID) == "")
    check("too short is rejected", M.parse_machine_id("abc123") == "")
    check("empty is rejected", M.parse_machine_id("") == "")
    check("None is rejected, not an exception", M.parse_machine_id(None) == "")


def test_parse_product_uuid():
    check("a dashed uuid line is accepted", M.parse_product_uuid(FAKE_UUID + "\n") == FAKE_UUID)
    check("lowercase is accepted too", M.parse_product_uuid(FAKE_UUID.lower()) == FAKE_UUID.lower())
    check("garbage is rejected", M.parse_product_uuid("not-a-uuid\n") == "")
    check("empty is rejected", M.parse_product_uuid("") == "")
    check("None is rejected, not an exception", M.parse_product_uuid(None) == "")


def test_current_key_override():
    check("BRAIN_MACHINE_KEY forces the answer, no hardware read at all",
          M.current_key(environ={"BRAIN_MACHINE_KEY": "laptop-a1b2c3d4"}, run=lambda cmd: 1 / 0,
                       open_=lambda p: 1 / 0) == "laptop-a1b2c3d4")
    check("a blank BRAIN_MACHINE_KEY is ignored, not treated as a real override",
          M.current_key(hostname="laptop-a", platform="linux", run=lambda cmd: (1, "", ""),
                       open_=lambda p: (_ for _ in ()).throw(OSError()),
                       environ={"BRAIN_MACHINE_KEY": "  "}) == "laptop-a")


def test_read_uuid():
    def run_ok(cmd):
        return 0, '"IOPlatformUUID" = "%s"\n' % FAKE_UUID, ""

    def run_fail(cmd):
        return 1, "", "no such device"

    check("macOS: the uuid comes from a successful ioreg call",
          M.read_uuid("darwin", run_ok, open) == FAKE_UUID)
    check("macOS: a failed ioreg call gives no uuid, not an exception",
          M.read_uuid("darwin", run_fail, open) == "")

    class FakeFile(object):
        def __init__(self, text):
            self.text = text

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return self.text

    machine_id_bare = FAKE_UUID.replace("-", "").lower()

    def open_machine_id(path):
        if path == "/etc/machine-id":
            return FakeFile(machine_id_bare + "\n")
        raise OSError("no such file: %s" % path)

    check("Linux: /etc/machine-id wins when it is readable",
          M.read_uuid("linux", run_fail, open_machine_id) == machine_id_bare)

    def open_product_uuid_only(path):
        if path == "/sys/class/dmi/id/product_uuid":
            return FakeFile(FAKE_UUID + "\n")
        raise OSError("no such file: %s" % path)

    check("Linux: falls back to /sys/class/dmi/id/product_uuid when machine-id is unreadable",
          M.read_uuid("linux", run_fail, open_product_uuid_only) == FAKE_UUID)

    def open_neither(path):
        raise OSError("no such file: %s" % path)

    check("Linux: neither file readable gives no uuid, not an exception",
          M.read_uuid("linux", run_fail, open_neither) == "")


def test_machine_label():
    check("the label is the sanitised short hostname", M.machine_label("laptop-a.local") == "laptop-a")
    check("an empty hostname still gives a label", M.machine_label("") == "machine")
    check("the label carries no uuid fragment", M.machine_label("laptop-a") == "laptop-a")


def test_id8():
    check("the first 8 hex of a dashed uuid, lowercased", M.id8(FAKE_UUID) == "aaaaaaaa")
    check("a bare 32-hex id works the same way", M.id8(FAKE_UUID.replace("-", "")) == "aaaaaaaa")
    check("fewer than 8 hex characters give no fragment", M.id8("AB12") == "")
    check("None gives no fragment, not an exception", M.id8(None) == "")


def test_historical_keys():
    check("no variable, no historical keys", M.historical_keys({}) == ())
    check("a comma-separated list is split and trimmed",
          M.historical_keys({"BRAIN_MACHINE_ALIASES": " old-name , older-name-12345678 "})
          == ("old-name", "older-name-12345678"))
    check("empty items are dropped", M.historical_keys({"BRAIN_MACHINE_ALIASES": ",, ,"}) == ())
    check("the same alias listed twice is kept once",
          M.historical_keys({"BRAIN_MACHINE_ALIASES": "a,a"}) == ("a",))


def test_machine_is_mine():
    key = M.machine_key("laptop-a", FAKE_UUID)

    def mine(value, historical=()):
        return M.machine_is_mine(value, current=key, uuid=FAKE_UUID, label="laptop-a", historical=historical)

    check("the current key is mine", mine(key))
    check("the current key in another case is mine", mine(key.upper()))
    check("the raw uuid is mine", mine(FAKE_UUID))
    check("the raw uuid without dashes and lowercased is mine", mine(FAKE_UUID.replace("-", "").lower()))
    check("the bare label is mine (what brainlib._machine() writes locally)", mine("laptop-a"))
    check("a key written under an older hostname, same uuid fragment, is mine", mine("old-laptop-aaaaaaaa"))
    check("a listed historical key is mine", mine("renamed-once", historical=("renamed-once",)))
    check("another machine's key is not mine", not mine("laptop-b-bbbbbbbb"))
    check("the same hostname with another uuid fragment is not mine", not mine("laptop-a-bbbbbbbb"))
    check("another uuid is not mine", not mine("BBBBBBBB-0000-0000-0000-000000000000"))
    check("an empty value is never mine", not mine("") and not mine(None) and not mine("   "))
    check("a partial uuid is not mine", not mine("aaaaaaaa-bbbb"))
    check("with no uuid, a key ending in some fragment is not taken as mine",
          not M.machine_is_mine("laptop-a-aaaaaaaa", current="laptop-a", uuid="", label="laptop-a"))
    check("with no uuid, the bare label still is",
          M.machine_is_mine("laptop-a", current="laptop-a", uuid="", label="laptop-a"))


def test_machine_is_mine_override():
    env = {"BRAIN_MACHINE_KEY": "laptop-a-12345678"}
    boom = lambda *a: 1 / 0
    check("BRAIN_MACHINE_KEY: the forced key is mine, no hardware read at all",
          M.machine_is_mine("laptop-a-12345678", environ=env, run=boom, open_=boom))
    check("BRAIN_MACHINE_KEY: an old form of the forced key (same fragment) is mine",
          M.machine_is_mine("old-name-12345678", environ=env, run=boom, open_=boom))
    check("BRAIN_MACHINE_KEY: any other key is not",
          not M.machine_is_mine("laptop-b-87654321", environ=env, run=boom, open_=boom))
    check("BRAIN_MACHINE_ALIASES is honoured when no historical list is passed",
          M.machine_is_mine("alias-x", environ=dict(env, BRAIN_MACHINE_ALIASES="alias-x"), run=boom, open_=boom))


def main():
    for t in (test_sanitize_hostname, test_machine_key, test_parse_ioreg_uuid, test_parse_machine_id,
              test_parse_product_uuid, test_current_key_override, test_read_uuid, test_machine_label, test_id8,
              test_historical_keys, test_machine_is_mine, test_machine_is_mine_override):
        print("\n== %s ==" % t.__name__)
        try:
            t()
        except Exception as exc:
            check("%s ran without raising" % t.__name__, False, repr(exc))
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
