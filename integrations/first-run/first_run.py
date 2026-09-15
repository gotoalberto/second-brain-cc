#!/usr/bin/env python3
"""first_run.py — the first run on a machine: connect what you want, install nothing you did not accept.

  first_run.py run [--dry-run]   ask the steps not answered yet, one at a time (needs a terminal);
                                 --dry-run shows what would be installed and saves no answer
  first_run.py status            every step and its answer; exit 0 when all are answered, 3 when not
  first_run.py reset <step>      ask one step again next time (with the steps that depend on it)
  first_run.py skip-all          record every unanswered step as declined (CI, unattended machines)

Steps, in order: kdbx, google, storage, alert_email, mcp, scheduler, routines. Answers live in
<brain state>/first-run.json; the guardian installs and repairs only the scheduled jobs accepted here.
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
again only asks what is left. Ctrl+C stops at any point; the steps already answered are kept.
"""


def main(argv=None):
    ap = argparse.ArgumentParser(prog="first_run.py", description="the first run on this machine")
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("run", help="ask the steps not answered yet")
    r.add_argument("--dry-run", action="store_true", help="show what would be installed; save nothing")
    sub.add_parser("status", help="every step and its answer; exit 3 while any is unanswered")
    rs = sub.add_parser("reset", help="ask one step again next time")
    rs.add_argument("step")
    sub.add_parser("skip-all", help="record every unanswered step as declined")
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
        state = ports.state.load()
        for step in D.STEPS:
            if step not in state["steps"]:
                state = D.record(state, step, "declined", {"reason": "skipped with first_run.py skip-all"},
                                 ports.clock.now())
        ports.state.save(state)
        print("every unanswered step recorded as declined; first_run.py reset <step> asks one again")
        return 0

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
