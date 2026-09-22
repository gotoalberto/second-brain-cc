#!/usr/bin/env python3
"""handoff.py: a one-time handoff of the credentials a new machine needs: the KeePass keyfile, the
database itself when asked, and a few non-secret settings. No cloud service, no account, no server.

  handoff.py issue [--to shared|inline|PATH] [--with-db] [--ttl-min 20]
      on a machine that already works. Encrypts the payload with a random one-time passphrase and
      prints one token plus the exact command to run on the new machine.
        shared  (the default when a shared directory is configured) writes handoff-<id>.enc into
                <shared>/handoff/; the token carries the id and the passphrase
        PATH    the same, into a directory you name (a USB stick, a synced folder)
        inline  (the default otherwise) the token carries the ciphertext itself, for pasting once;
                refused over 64 KiB, use --to PATH then
      Every issue deletes handoff files older than an hour.
  handoff.py redeem TOKEN [--force] [--from DIR] [--ignore-expiry]
      on the new machine, from any directory. Checks the MAC, decrypts, writes the keyfile (and the
      database if it was carried) mode 600, refuses to overwrite without --force, records them with
      `kp.py init`, and deletes the handoff file, so it works once.

Security model: the token is as sensitive as the keyfile. It expires (20 minutes by default), the
payload is encrypted (openssl enc -aes-256-cbc -pbkdf2 -iter 200000, the passphrase passed to openssl
through its environment, never argv) and authenticated (HMAC-SHA256, checked before decrypting), and
a handoff through a file is deleted when redeemed. The master password is never carried, asked for
or handled: the human types it where kp.py asks, and only there.

Exit status: 0 done, 1 not done (expired, tampered, missing, would overwrite), 2 asked wrongly.
Design: 30-Knowledge/2026-09-22-decision-one-time-handoff-for-new-machine-credentials.md
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from handoff_core import adapters as AD  # noqa: E402
from handoff_core import application as A  # noqa: E402
from handoff_core import domain as D  # noqa: E402

WARNING = """\
This token is as sensitive as the keyfile it carries. Paste it once, into the new machine's
terminal. Never put it in a chat, a note, a ticket, an email or git. It is not a password to
remember: if it expires or leaks, issue a new one."""


class _Parser(argparse.ArgumentParser):
    """argparse, but a usage error is one line and exit 2, never a usage dump."""

    def error(self, message):
        raise D.UsageError(message)


def make_parser():
    ap = _Parser(prog="handoff.py", description="one-time handoff of a new machine's credentials",
                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", metavar="{issue,redeem}", parser_class=_Parser)
    p = sub.add_parser("issue", help="on a machine that works: encrypt the keyfile and settings, print a token")
    p.add_argument("--to", default=None, help="shared, inline or an absolute directory (default: shared when "
                                              "a shared directory is configured, else inline)")
    p.add_argument("--with-db", action="store_true", help="carry the .kdbx too (off by default)")
    p.add_argument("--ttl-min", type=int, default=D.DEFAULT_TTL_MIN, help="minutes the token is valid (1 to 60)")
    p = sub.add_parser("redeem", help="on the new machine: place the files and record them with kp.py init")
    p.add_argument("token")
    p.add_argument("--force", action="store_true", help="overwrite files that already exist")
    p.add_argument("--from", dest="from_dir", default=None, help="the directory holding the handoff file, when "
                                                                  "it is not where the issuer wrote it")
    p.add_argument("--ignore-expiry", action="store_true",
                   help="redeem after the ttl (never for a handoff file older than an hour)")
    return ap


def _tilde(path):
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path == home or path.startswith(home + os.sep) else path


def _script(name):
    return _tilde(os.path.join(HERE, name))


def cmd_issue(ports, a):
    res = A.issue(ports, to=a.to, with_db=a.with_db, ttl_min=a.ttl_min)
    minutes = res.ttl // 60
    if res.location:
        print("One-time handoff written to %s" % res.location)
        print("valid %d minutes, deleted when redeemed, and swept after an hour if it never is." % minutes)
    else:
        print("One-time handoff, inline: the token below is the encrypted payload itself, valid %d minutes." % minutes)
    if res.swept:
        print("(swept %d stale handoff file%s)" % (res.swept, "" if res.swept == 1 else "s"))
    print()
    print(WARNING)
    print()
    print("On the new machine, with the vault cloned, run:")
    print()
    print("  python3 %s redeem '%s'" % (_script("handoff.py"), res.token))
    print()
    for note in res.notes:
        print("note: %s" % note)
    return 0


def _next_steps(res):
    s = res.settings
    lines = []
    for member, path in sorted(res.written.items()):
        lines.append("placed %-9s: %s (mode 600)" % ("keyfile" if member == D.KEYFILE else "database", path))
    if res.deleted:
        lines.append("deleted handoff : %s (it works once)" % res.deleted)
    kp_cmd = "python3 %s %s" % (_script("kp.py"), " ".join(res.kp_args))
    if res.kp_result is None:
        lines.append("kp.py init      : not run, the database is not on this machine yet (%s)." % (s.get("db") or "?"))
        lines.append("                  Copy it here, or wait for the shared folder to sync, then run:")
        lines.append("                  %s" % kp_cmd)
    elif res.kp_result[0]:
        lines.append("kp.py init      : %s" % (res.kp_result[1].splitlines()[-1] if res.kp_result[1] else "done"))
    else:
        lines.append("kp.py init      : failed (%s). Run it by hand:" % res.kp_result[1])
        lines.append("                  %s" % kp_cmd)
    carried = []
    shared = s.get("shared_dir")
    if shared:
        here = res.local_shared or "not configured here: the first run's multi_machine step, or BRAIN_SHARED_DIR"
        carried.append("  shared directory : %s (this machine: %s)" % (shared, here))
    if s.get("files_dir"):
        carried.append("  files directory  : %s" % s["files_dir"])
    if s.get("kp_group"):
        carried.append("  KeePass group    : %s" % s["kp_group"])
    if s.get("google_accounts"):
        carried.append("  Google accounts  : %s (only the names travel; their secrets are in the database)"
                       % ", ".join(s["google_accounts"]))
    if carried:
        lines.append("")
        lines.append("From the machine that issued it (not applied here; the first run sets them if you want them):")
        lines.extend(carried)
    lines.append("")
    lines.append("Next:")
    lines.append("  python3 %s status" % _script("kp.py"))
    lines.append("  python3 %s unlock    # when the database also has a master password: you type it, "
                 "nobody else" % _script("kp.py"))
    return "\n".join(lines)


def cmd_redeem(ports, a):
    res = A.redeem(ports, a.token, force=a.force, ignore_expiry=a.ignore_expiry, from_dir=a.from_dir)
    print(_next_steps(res))
    return 0 if (res.kp_result is None or res.kp_result[0]) else 1


def main(argv=None, ports=None):
    try:
        a = make_parser().parse_args(sys.argv[1:] if argv is None else argv)
        if not a.cmd:
            raise D.UsageError("say issue or redeem (handoff.py --help)")
        ports = ports or AD.build_ports()
        return cmd_issue(ports, a) if a.cmd == "issue" else cmd_redeem(ports, a)
    except D.UsageError as exc:
        sys.stderr.write("handoff: %s\n" % exc)
        return 2
    except D.HandoffError as exc:
        sys.stderr.write("handoff: %s\n" % exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
