#!/usr/bin/env python3
"""Tests for kp_kdbx.pl — the kpcli backend's direct File::KDBX binding.

Not Python, so it is not exercised by the rest of the suite unless this file asks for it. Two
tiers, from least to most demanding of the machine running the suite:

  1. Syntax only (`perl -c`): always attempted; skipped with an explicit message, not a
     failure, when `perl` itself is not on this machine.
  2. A functional round trip through File::KDBX, building a tiny KDBX fixture with Perl
     itself: only attempted when `perl -MFile::KDBX -e1` succeeds (the module is installed).
     Skipped with an explicit message otherwise — `cpanm --local-lib=~/perl5 File::KDBX` is
     optional, only needed for the kpcli backend, and most machines running this suite will
     not have it.

Either way this never makes run_all_tests.py fail on a machine with no Perl or no
File::KDBX: a skip prints RESULT: N passed, 0 failed, same as any other file. Run standalone:

    python3 _bin/kp_kdbx_pl_test.py
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "kp_kdbx.pl")

ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def run(argv, **kw):
    return subprocess.run(argv, capture_output=True, text=True, timeout=30, **kw)


def perl_available():
    return shutil.which("perl") is not None


def kdbx_module_available():
    try:
        p = run(["perl", "-MFile::KDBX", "-e1"])
    except OSError:
        return False
    return p.returncode == 0


def test_syntax():
    print("\n== perl -c: syntax ==")
    if not perl_available():
        print("  (skipped: perl is not installed on this machine)")
        return
    p = run(["perl", "-c", SCRIPT])
    check("kp_kdbx.pl parses as valid Perl", p.returncode == 0, p.stderr)


FIXTURE_PL = r'''
use strict; use warnings;
use File::KDBX;
my ($db, $master) = @ARGV;
my $kdbx = File::KDBX->new;
my $e = $kdbx->root->add_entry(title => "example");
$e->username("someone");
$e->url("https://example.com");
$e->password("swordfish-test");
$kdbx->dump_file($db, $master);
'''


FIXTURE_KEYED_PL = r'''
use strict; use warnings;
use File::KDBX; use File::KDBX::Key::File;
my ($db, $keyfile, $master) = @ARGV;
open(my $fh, '>:raw', $keyfile) or die $!; print $fh join('', map { chr(int(rand(256))) } 1..64); close $fh;
my $kf = File::KDBX::Key::File->new($keyfile);
my $key = (defined $master && length $master) ? [$master, $kf] : $kf;
my $kdbx = File::KDBX->new;
my $e = $kdbx->root->add_entry(title => "keyed");
$e->password("keyed-secret");
$kdbx->dump_file($db, $key);
'''


def test_keyfile():
    print("\n== key files: keyfile-only and password plus key file ==")
    if not perl_available() or not kdbx_module_available():
        print("  (skipped: File::KDBX is not installed, `cpanm --local-lib=~/perl5 File::KDBX`)")
        return
    tmp = tempfile.mkdtemp(prefix="kp-kdbx-pl-key-")
    try:
        fixture = os.path.join(tmp, "fixture.pl")
        with open(fixture, "w") as fh:
            fh.write(FIXTURE_KEYED_PL)
        empty = os.path.join(tmp, "empty")
        open(empty, "w").close()
        withpw = os.path.join(tmp, "withpw")
        with open(withpw, "w") as fh:
            fh.write("swordfish-test")

        def kp(db, pwfile, keyfile, *args, **kw):
            env = dict(os.environ, BRAIN_KP_KEYFILE=keyfile)
            return run([SCRIPT] + list(args) + ["--db", db, "--pwfile", pwfile], env=env, **kw)

        only_db, only_key = os.path.join(tmp, "only.kdbx"), os.path.join(tmp, "only.key")
        p = run(["perl", fixture, only_db, only_key])
        check("a keyfile-only fixture was created", p.returncode == 0, (p.stdout, p.stderr))
        p = kp(only_db, empty, only_key, "show", "--entry", "keyed", "--attr", "Password", "--reveal")
        check("a keyfile-only store opens with the key file alone and an empty password file",
              p.returncode == 0 and p.stdout.strip() == "keyed-secret", (p.stdout, p.stderr))
        p = kp(only_db, empty, only_key, "add", "--entry", "second", "--stdin-secret", input="n-secret")
        check("and a write keeps it keyfile-only", p.returncode == 0, (p.stdout, p.stderr))
        p = kp(only_db, empty, only_key, "show", "--entry", "second", "--attr", "Password", "--reveal")
        check("the store still opens with the key file alone after the write",
              p.returncode == 0 and p.stdout.strip() == "n-secret", (p.stdout, p.stderr))
        # Asked of File::KDBX directly: the helper itself refuses to try an empty password with
        # no key file, so only a direct load can prove the write did not drop the key.
        p = run(["perl", "-MFile::KDBX", "-e", 'exit(eval { File::KDBX->load_file($ARGV[0], ""); 1 } ? 0 : 1)',
                 only_db])
        check("and after the write it does NOT open with an empty password and no key file",
              p.returncode != 0, (p.stdout, p.stderr))
        p = kp(only_db, empty, "", "ls")
        check("with neither a master nor a key file it refuses", p.returncode != 0, (p.stdout, p.stderr))

        both_db, both_key = os.path.join(tmp, "both.kdbx"), os.path.join(tmp, "both.key")
        p = run(["perl", fixture, both_db, both_key, "swordfish-test"])
        check("a password plus key file fixture was created", p.returncode == 0, (p.stdout, p.stderr))
        p = kp(both_db, withpw, both_key, "ls")
        check("password plus key file opens with both", p.returncode == 0 and "keyed" in p.stdout,
              (p.stdout, p.stderr))
        p = kp(both_db, empty, both_key, "ls")
        check("the key file alone does not open a store that also has a password", p.returncode != 0,
              (p.stdout, p.stderr))
        p = kp(both_db, withpw, "", "ls")
        check("the password alone does not open it either, and the error says wrong key",
              p.returncode != 0 and "wrong key" in p.stderr, (p.stdout, p.stderr))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_functional():
    print("\n== a real File::KDBX round trip ==")
    if not perl_available() or not kdbx_module_available():
        print("  (skipped: File::KDBX is not installed — `cpanm --local-lib=~/perl5 File::KDBX`)")
        return

    tmp = tempfile.mkdtemp(prefix="kp-kdbx-pl-test-")
    try:
        db = os.path.join(tmp, "test.kdbx")
        master = "swordfish-test"
        fixture = os.path.join(tmp, "fixture.pl")
        with open(fixture, "w") as fh:
            fh.write(FIXTURE_PL)
        p = run(["perl", fixture, db, master])
        check("the fixture database was created", p.returncode == 0 and os.path.isfile(db), (p.stdout, p.stderr))
        if p.returncode != 0:
            return    # nothing else can run without the fixture; main() prints RESULT once

        pwfile = os.path.join(tmp, "pwfile")
        with open(pwfile, "w") as fh:
            fh.write(master)
        os.chmod(pwfile, 0o600)

        def kp(*args):
            return run([SCRIPT] + list(args) + ["--db", db, "--pwfile", pwfile])

        p = kp("ls")
        check("ls lists the fixture entry", p.returncode == 0 and "example" in p.stdout, (p.stdout, p.stderr))

        p = kp("search", "--text", "examp")
        check("search finds it by a substring", p.returncode == 0 and "example" in p.stdout, (p.stdout, p.stderr))

        p = kp("show", "--entry", "example")
        check("show without --attr prints the fields, password masked",
              p.returncode == 0 and "someone" in p.stdout and "Password: ****" in p.stdout, (p.stdout, p.stderr))

        p = kp("show", "--entry", "example", "--attr", "UserName")
        check("show --attr UserName without --reveal prints the real value, not masked",
              p.returncode == 0 and p.stdout.strip() == "someone", (p.stdout, p.stderr))

        p = kp("show", "--entry", "example", "--attr", "Password")
        check("show --attr Password without --reveal is masked", p.returncode == 0 and p.stdout.strip() == "****",
              (p.stdout, p.stderr))

        p = kp("show", "--entry", "example", "--attr", "Password", "--reveal")
        check("show --attr Password --reveal prints the real secret",
              p.returncode == 0 and p.stdout.strip() == master, (p.stdout, p.stderr))

        p = kp("mkdir", "--group", "Brain/apis")
        check("mkdir creates a nested group", p.returncode == 0, (p.stdout, p.stderr))
        p = kp("ls", "--recursive")
        check("the entry still lists after a write", p.returncode == 0 and "example" in p.stdout, p.stdout)

        p = kp("add", "--entry", "Brain/apis/new-one", "--user", "svc", "--notes", "hi",
               "--generate", "--length", "10")
        check("add creates an entry under the new group with a generated password",
              p.returncode == 0 and "created" in p.stdout, (p.stdout, p.stderr))
        p = kp("show", "--entry", "Brain/apis/new-one", "--attr", "Password", "--reveal")
        check("the generated password is exactly the requested length",
              p.returncode == 0 and len(p.stdout.strip()) == 10, (p.stdout, p.stderr))

        p = run([SCRIPT, "add", "--entry", "Brain/apis/from-stdin", "--db", db, "--pwfile", pwfile,
                "--stdin-secret"], input="stdin-secret-test")
        check("add --stdin-secret reads the new secret from stdin, already de-duplicated by kp_backend.py",
              p.returncode == 0, (p.stdout, p.stderr))
        p = kp("show", "--entry", "Brain/apis/from-stdin", "--attr", "Password", "--reveal")
        check("the stdin secret was NOT stored twice (this script trusts split_confirmation ran upstream)",
              p.returncode == 0 and p.stdout.strip() == "stdin-secret-test", (p.stdout, p.stderr))

        p = kp("add", "--entry", "example")
        check("adding an entry that already exists is refused", p.returncode != 0, (p.stdout, p.stderr))

        p = kp("show", "--entry", "no/such/entry")
        check("showing an entry that does not exist is refused, not a crash", p.returncode != 0, (p.stdout, p.stderr))

        # ---- reorganising: mv relocates, edit --title renames, rm deletes, rmdir drops an empty group
        p = kp("mv", "--entry", "Brain/apis/new-one", "--group", "Brain/infra")
        check("mv relocates an entry into another group, creating it", p.returncode == 0, (p.stdout, p.stderr))
        p = kp("ls", "--recursive")
        check("after mv the entry lists under the new group and not the old one",
              "Brain/infra/new-one" in p.stdout and "Brain/apis/new-one" not in p.stdout, p.stdout)
        p = kp("edit", "--entry", "Brain/infra/new-one", "--title", "renamed")
        check("edit --title renames in place", p.returncode == 0, (p.stdout, p.stderr))
        p = kp("show", "--entry", "Brain/infra/renamed", "--attr", "UserName")
        check("the renamed entry keeps its fields", p.returncode == 0 and p.stdout.strip() == "svc",
              (p.stdout, p.stderr))
        p = kp("rmdir", "--group", "Brain/infra")
        check("rmdir refuses a group that still holds an entry", p.returncode != 0, (p.stdout, p.stderr))
        p = kp("rm", "--entry", "Brain/infra/renamed")
        check("rm deletes the entry", p.returncode == 0, (p.stdout, p.stderr))
        p = kp("show", "--entry", "Brain/infra/renamed")
        check("and it is gone", p.returncode != 0, (p.stdout, p.stderr))
        p = kp("rmdir", "--group", "Brain/infra")
        check("rmdir drops the group once it is empty", p.returncode == 0, (p.stdout, p.stderr))
        p = kp("rm", "--entry", "Brain/infra/renamed")
        check("rm of an entry that is not there is refused", p.returncode != 0, (p.stdout, p.stderr))
        p = kp("rmdir", "--group", "")
        check("rmdir never removes the root", p.returncode != 0, (p.stdout, p.stderr))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    for t in (test_syntax, test_functional, test_keyfile):
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
