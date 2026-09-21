#!/usr/bin/env python3
"""first_run.py — the first run on a machine: connect what you want, install nothing you did not accept.

  first_run.py run [--dry-run]   ask the steps not answered yet, one at a time (needs a terminal);
                                 --dry-run shows what would be installed and saves no answer
  first_run.py status            every step and its answer; exit 0 when all are answered, 3 when not
  first_run.py reset <step>      ask one step again next time (with the steps that depend on it)
  first_run.py skip-all          answer every unanswered step without asking (CI, unattended machines):
                                 files gets the default directory, created and recorded; the rest is declined

Steps, in order: kdbx, google, files, multi_machine, alert_email, mcp, scheduler, remote_control, routines.
files cannot be declined: it records the local directory files.py keeps files in (proposed: ~/BrainFiles).
multi_machine is opt-in: a shared folder (Dropbox, iCloud, a NAS) over which this machine coordinates
presence and file claims with others (brain_shared.py, presence.py, claims_sync.py); declined by default.
remote_control makes the machine reachable from the Claude app: a dedicated git repository (proposed:
~/<host name>), one start on the terminal for the server's one-time prompts, then a launchd agent or a
systemd user unit that keeps `claude remote-control --chrome` running (remote_control.py).
Answers live in <brain state>/first-run.json; the guardian installs and repairs only the scheduled
jobs accepted here. A run and skip-all both end by registering this machine in the machine registry
(machines.py register --daily), which the guardian's scheduled repair then keeps fresh.
BRAIN_FAKE_SCHEDULER=1 writes job files under HOME without telling launchctl, systemctl or cron.
Usually started through setup.sh.
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.environ.get("BRAIN_VAULT") or os.path.dirname(os.path.dirname(HERE))
for path in (HERE, os.path.join(VAULT, "_bin")):
    if path not in sys.path:
        sys.path.insert(0, path)

from first_run_core import adapters as AD  # noqa: E402
from first_run_core import application as A  # noqa: E402
from first_run_core import domain as D  # noqa: E402

INTRO = """Second Brain: first run on this machine

Each step asks whether to connect one optional piece. Answer no to anything you do not want: nothing
is installed, created or registered without a yes, and every answer is remembered, so running this
again only asks what is left. One step is required: the directory where Brain keeps files, which is
created for you. Ctrl+C stops at any point; the steps already answered are kept.
"""


def main(argv=None):
    ap = argparse.ArgumentParser(prog="first_run.py", description="the first run on this machine")
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("run", help="ask the steps not answered yet")
    r.add_argument("--dry-run", action="store_true", help="show what would be installed; save nothing")
    sub.add_parser("status", help="every step and its answer; exit 3 while any is unanswered")
    rs = sub.add_parser("reset", help="ask one step again next time")
    rs.add_argument("step")
    sub.add_parser("skip-all", help="set up the default files directory and decline every other unanswered step")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)
    if not args.cmd:
        ap.print_help(sys.stderr)
        return 2
    ports = AD.build_ports(VAULT)

    if args.cmd == "status":
        complete, lines = A.run_status(ports)
        print("\n".join(lines))
        return 0 if complete else 3

    if args.cmd == "reset":
        if args.step not in D.STEPS:
            print("first_run.py: unknown step %r (steps: %s)" % (args.step, ", ".join(D.STEPS)), file=sys.stderr)
            return 2
        A.reset(ports, args.step)
        print("%s will be asked again on the next run" % args.step)
        return 0

    if args.cmd == "skip-all":
        state, failed = A.skip_all(ports)
        files = state["steps"].get("files", {})
        if files.get("status") == "done":
            print("files directory: %s" % files.get("dir"))
        for step, why in failed:
            print("first_run.py: %s is required and could not be set up: %s" % (step, why), file=sys.stderr)
        print("every other unanswered step recorded as declined; first_run.py reset <step> asks one again")
        return 1 if failed else 0

    if ports.prompt.interactive():
        print(INTRO)
    try:
        result = A.run(ports, dry_run=args.dry_run)
    except (KeyboardInterrupt, EOFError):
        print("\nStopped. The answers given so far are kept; run it again to continue.")
        return 0
    if ports.prompt.interactive():
        if result.failed:
            print("Not completed, asked again on the next run: %s" % ", ".join(s for s, _ in result.failed))
        print("First run %s." % ("complete" if result.complete else "not complete yet"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
