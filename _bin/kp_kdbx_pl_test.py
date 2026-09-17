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
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    for t in (test_syntax, test_functional):
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
