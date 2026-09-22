#!/usr/bin/env python3
"""Tests for kp_backend — routing between keepassxc-cli and kpcli, and the argv translation
that lets kp.py's central cli() speak to either. Pure logic: every filesystem or subprocess
effect (which(), whether a fallback path "exists", the actual process run) is injected, so
this never touches a real keepassxc-cli or kpcli install. Run standalone:

    python3 _bin/kp_backend_test.py
"""
import os
import stat
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import kp_backend as K

ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def which_none(name):
    return None


def which_all(name):
    return "/found/bin/" + name


def fallback_none(kind):
    return []


def fallback_kpcli_only(kind):
    return ["/opt/kpcli/bin/kpcli"] if kind == "kpcli" else []


def test_resolve():
    print("\n== _resolve: precedence ==")
    check("BRAIN_KP_BACKEND wins outright, even over a which() hit for the other backend",
          K._resolve({"BRAIN_KP_BACKEND": "kpcli"}, which_all, fallback_none) == ("kpcli", "/found/bin/kp_kdbx.pl"))
    check("BRAIN_KP_BACKEND=keepassxc is honoured the same way",
          K._resolve({"BRAIN_KP_BACKEND": "keepassxc"}, which_all, fallback_none)
          == ("keepassxc", "/found/bin/keepassxc-cli"))
    check("an unrecognised BRAIN_KP_BACKEND is ignored, falling through to detection",
          K._resolve({"BRAIN_KP_BACKEND": "nonsense"}, which_all, fallback_none) == ("keepassxc", "/found/bin/keepassxc-cli"))
    check("with nothing forced, which() beats the fallback list: keepassxc-cli preferred when both exist",
          K._resolve({}, which_all, fallback_none) == ("keepassxc", "/found/bin/keepassxc-cli"))

    def which_kpcli_only(name):
        return "/found/bin/kp_kdbx.pl" if name == "kp_kdbx.pl" else None

    check("with nothing forced and no keepassxc-cli on the PATH, kpcli is used if which() finds kp_kdbx.pl",
          K._resolve({}, which_kpcli_only, fallback_none) == ("kpcli", "/found/bin/kp_kdbx.pl"))
    check("which() beats the fallback list even for the forced backend",
          K._resolve({"BRAIN_KP_BACKEND": "kpcli"}, which_kpcli_only, fallback_none) == ("kpcli", "/found/bin/kp_kdbx.pl"))

    check("forced, which() empty: the fallback list is tried next",
          K._resolve({"BRAIN_KP_BACKEND": "kpcli"}, which_none, fallback_kpcli_only)
          == ("kpcli", "/opt/kpcli/bin/kpcli"))
    check("unforced, which() empty for both: the fallback list is tried, keepassxc first",
          K._resolve({}, which_none, lambda kind: ["/opt/x/keepassxc-cli"] if kind == "keepassxc" else ["/opt/x/kpcli"])
          == ("keepassxc", "/opt/x/keepassxc-cli"))
    check("nothing found anywhere: the bare binary name is the last resort, keepassxc-cli by default",
          K._resolve({}, which_none, fallback_none) == ("keepassxc", "keepassxc-cli"))
    check("forced with nothing found anywhere: the bare name of the FORCED backend",
          K._resolve({"BRAIN_KP_BACKEND": "kpcli"}, which_none, fallback_none) == ("kpcli", "kp_kdbx.pl"))


def test_default_fallback_paths_never_silently_picks_kpcli():
    print("\n== default_fallback_paths: kp_kdbx.pl existing in the checkout is not a usability signal ==")
    check("kp_kdbx.pl really is on disk in this checkout (the scenario the bug depends on)",
          os.path.exists(K.KP_KDBX_PL), K.KP_KDBX_PL)
    check("default_fallback_paths('kpcli') is empty even though the file exists",
          K.default_fallback_paths("kpcli") == [], K.default_fallback_paths("kpcli"))
    result = K._resolve({}, which_none, K.default_fallback_paths)
    check("on a machine with no keepassxc-cli and no BRAIN_KP_BACKEND (a bare CI checkout), "
          "_resolve with the REAL default_fallback_paths still picks keepassxc, not kpcli",
          result[0] == "keepassxc", result)


def test_translate_ls():
    print("\n== translate: ls ==")
    db = "/db/path.kdbx"
    check("plain ls", K.translate(["ls", db], db) == ["ls"])
    check("ls -R -f with a group", K.translate(["ls", "-R", "-f", db, "Brain"], db)
          == ["ls", "--recursive", "--flatten", "--group", "Brain"])
    check("ls -R only", K.translate(["ls", "-R", db], db) == ["ls", "--recursive"])
    check("ls with a group and no flags", K.translate(["ls", db, "Brain/apis"], db)
          == ["ls", "--group", "Brain/apis"])


def test_translate_search():
    print("\n== translate: search ==")
    db = "/db/path.kdbx"
    check("search", K.translate(["search", db, "example"], db) == ["search", "--text", "example"])
    bad = None
    try:
        K.translate(["search", db], db)
    except K.Unsupported:
        bad = True
    check("search with no text raises Unsupported instead of guessing", bad is True)


def test_translate_show():
    print("\n== translate: show ==")
    db = "/db/path.kdbx"
    check("show with an attribute", K.translate(["show", "-a", "Password", db, "Brain/example"], db)
          == ["show", "--entry", "Brain/example", "--attr", "Password"])
    check("show -s -a reveals", K.translate(["show", "-s", "-a", "Password", db, "Brain/example"], db)
          == ["show", "--entry", "Brain/example", "--attr", "Password", "--reveal"])
    check("show with no attribute (info / notes_of with no -a)", K.translate(["show", db, "Brain/example"], db)
          == ["show", "--entry", "Brain/example"])


def test_translate_mkdir():
    print("\n== translate: mkdir ==")
    db = "/db/path.kdbx"
    check("mkdir", K.translate(["mkdir", db, "Brain/apis"], db) == ["mkdir", "--group", "Brain/apis"])


def test_translate_add_edit():
    print("\n== translate: add, edit ==")
    db = "/db/path.kdbx"
    check("add with user, url, notes and a prompted secret (-p)",
          K.translate(["add", db, "Brain/example", "-u", "me", "--url", "https://example.com",
                      "--notes", "hi", "-p"], db)
          == ["add", "--entry", "Brain/example", "--user", "me", "--url", "https://example.com",
              "--notes", "hi", "--stdin-secret"])
    check("edit generating a new password",
          K.translate(["edit", db, "Brain/example", "-g", "-L", "24", "-l", "-U", "-n", "-s"], db)
          == ["edit", "--entry", "Brain/example", "--generate", "--length", "24"])
    check("add with only an entry (metadata-only put)",
          K.translate(["add", db, "Brain/example"], db) == ["add", "--entry", "Brain/example"])


def test_translate_unsupported():
    print("\n== translate: everything outside the six ==")
    db = "/db/path.kdbx"
    for args in (["clip", db, "Brain/example", "Password", "20"], ["db-create", db], ["mv", db, "a", "b"],
                ["rmdir", db, "Brain/old"], [], ["rm", db, "x"]):
        bad = None
        try:
            K.translate(args, db)
        except K.Unsupported as exc:
            bad = exc
        check("translate(%r) raises Unsupported" % (args[:1] or ["(empty)"],), bad is not None, bad)


def test_build():
    print("\n== build ==")
    tmp = tempfile.mkdtemp(prefix="kp-backend-test-")
    try:
        argv, prefix, cleanup, env = K.build("keepassxc", "/bin/keepassxc-cli", ["ls", "-R"], "/db.kdbx",
                                             "swordfish-test", os.path.join(tmp, "pw"))
        check("keepassxc-cli: argv passes through with the binary prepended",
              argv == ["/bin/keepassxc-cli", "ls", "-R"], argv)
        check("keepassxc-cli: the master is the first line on stdin", prefix == "swordfish-test\n", prefix)
        cleanup()   # must be a harmless no-op

        argv, prefix, cleanup, env = K.build("kpcli", "/bin/kp_kdbx.pl", ["ls"], "/db.kdbx", "swordfish-test",
                                             os.path.join(tmp, "pw"))
        check("kpcli: argv carries --db and --pwfile, not the master itself",
              argv[:2] == ["/bin/kp_kdbx.pl", "ls"] and "--db" in argv and "/db.kdbx" in argv
              and "--pwfile" in argv, argv)
        pwfile = argv[argv.index("--pwfile") + 1]
        check("kpcli: the master lands in a private 0600 file under pwfile_dir",
              os.path.isfile(pwfile) and open(pwfile).read() == "swordfish-test"
              and stat.S_IMODE(os.stat(pwfile).st_mode) == 0o600, pwfile)
        check("kpcli: stdin is left free (no master prefix) for a new secret", prefix == "", prefix)
        check("kpcli: a call with no key file still sets BRAIN_KP_KEYFILE, empty, so an inherited "
              "value cannot leak in", env is not None and env.get("BRAIN_KP_KEYFILE") == "",
              env and env.get("BRAIN_KP_KEYFILE"))
        cleanup()
        check("kpcli: cleanup shreds the pwfile", not os.path.exists(pwfile))
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_keyfile():
    print("\n== key files: keepassxc-cli takes -k itself, kp_kdbx.pl gets it through the environment ==")
    tmp = tempfile.mkdtemp(prefix="kp-backend-test-")
    saved = os.environ.get("BRAIN_KP_KEYFILE")
    os.environ["BRAIN_KP_KEYFILE"] = "/stale/inherited.key"
    try:
        argv, prefix, cleanup, env = K.build("keepassxc", "/bin/keepassxc-cli",
                                             ["ls", "-k", "/k/store.key", "/db.kdbx"], "/db.kdbx",
                                             "swordfish-test", os.path.join(tmp, "pw"))
        check("keepassxc-cli: -k stays in argv, where keepassxc-cli reads it",
              argv == ["/bin/keepassxc-cli", "ls", "-k", "/k/store.key", "/db.kdbx"], argv)
        check("keepassxc-cli: no environment of its own is needed", env is None, env)
        argv, prefix, cleanup, env = K.build("keepassxc", "/bin/keepassxc-cli",
                                             ["ls", "-k", "/k/store.key", "--no-password", "/db.kdbx"],
                                             "/db.kdbx", "", os.path.join(tmp, "pw"))
        check("keepassxc-cli with --no-password: nothing is prefixed on stdin, not even a newline "
              "(it would be read as the next secret)", prefix == "", repr(prefix))

        argv, prefix, cleanup, env = K.build("kpcli", "/bin/kp_kdbx.pl",
                                             ["ls", "--group", "Brain", "-k", "/k/store.key"],
                                             "/db.kdbx", "swordfish-test", os.path.join(tmp, "pw"))
        check("kpcli: build() strips -k <path> before the helper sees its arguments",
              "-k" not in argv and "/k/store.key" not in argv, argv)
        check("kpcli: the key file path reaches the helper as BRAIN_KP_KEYFILE",
              env.get("BRAIN_KP_KEYFILE") == "/k/store.key", env.get("BRAIN_KP_KEYFILE"))
        pwfile = argv[argv.index("--pwfile") + 1]
        check("kpcli: the master still goes through the 0600 file, never the environment",
              open(pwfile).read() == "swordfish-test"
              and "swordfish-test" not in "".join(str(v) for v in env.values()))
        cleanup()

        argv, prefix, cleanup, env = K.build("kpcli", "/bin/kp_kdbx.pl",
                                             ["ls", "-k", "/k/store.key", "--no-password"],
                                             "/db.kdbx", "stray-master", os.path.join(tmp, "pw"))
        pwfile = argv[argv.index("--pwfile") + 1]
        check("kpcli with --no-password: the password file is empty, so the key file alone is the key "
              "(an empty password plus a key file is a different key)",
              open(pwfile).read() == "" and "--no-password" not in argv, (open(pwfile).read(), argv))
        cleanup()

        rest, keyflags = K.take_key_flags(["ls", "-k", "/k/store.key", "--no-password", "/db.kdbx", "Brain"])
        check("take_key_flags separates the key flags from what translate() reads",
              rest == ["ls", "/db.kdbx", "Brain"] and keyflags == ["-k", "/k/store.key", "--no-password"],
              (rest, keyflags))

        seen = {}

        def fake_run(argv, input=None, capture_output=None, text=None, timeout=None, env=None):
            seen.update(argv=argv, env=env, input=input)
            import types
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        real = K.subprocess.run
        K.subprocess.run = fake_run
        try:
            K.run("kpcli", "/bin/kp_kdbx.pl", ["ls", "-k", "/k/store.key", "/db.kdbx", "Brain"], "/db.kdbx",
                  "swordfish-test", pwfile_dir=os.path.join(tmp, "pw"))
        finally:
            K.subprocess.run = real
        check("run(): a keepassxc-shaped call with -k translates cleanly and carries the key file",
              seen.get("argv", [])[1:4] == ["ls", "--group", "Brain"]
              and (seen.get("env") or {}).get("BRAIN_KP_KEYFILE") == "/k/store.key", seen)
    finally:
        if saved is None:
            os.environ.pop("BRAIN_KP_KEYFILE", None)
        else:
            os.environ["BRAIN_KP_KEYFILE"] = saved
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_split_confirmation():
    print("\n== split_confirmation: the kpcli double-write bug fix ==")
    check("two identical lines collapse to one (this is the actual bug: -p sends the secret twice)",
          K.split_confirmation("swordfish-test\nswordfish-test\n") == "swordfish-test")
    check("mismatched halves are returned unchanged, not guessed at", K.split_confirmation("a\nb\n") == "a\nb\n")
    check("empty stays empty", K.split_confirmation("") == "")
    check("a single line with no trailing newline is unchanged", K.split_confirmation("solo") == "solo")
    check("three genuinely different lines are unchanged", K.split_confirmation("a\nb\nc\n") == "a\nb\nc\n")


def main():
    for t in (test_resolve, test_default_fallback_paths_never_silently_picks_kpcli, test_translate_ls,
              test_translate_search, test_translate_show, test_translate_mkdir,
              test_translate_add_edit, test_translate_unsupported, test_build, test_keyfile,
              test_split_confirmation):
        try:
            t()
        except Exception as exc:
            import traceback
            traceback.print_exc()
            check("%s ran without raising" % t.__name__, False, repr(exc))
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
