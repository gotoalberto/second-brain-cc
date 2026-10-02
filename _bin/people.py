#!/usr/bin/env python3
"""Context by person: who a name means, and their notes merged with a project's.

  people.py detect "<text>"                      -> the people the text names
  people.py context "<prompt>"                   -> the people named, the project it is about,
                                                    and their notes without repeats
  people.py context --person "Dana" --project garden-planner
  people.py context "..." --since 2026-03-01 --json

A person is an entity note in 70-Entities tagged `person`; their notes are the ones that link
`[[entity-<slug>]]` or name them in full. When a person and a project are both given, both lists
are merged by path: a note on both is listed once, marked `both`, and first. Read each listed
note once. Library and settings: people_core.py.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B  # noqa: E402
import people_core as P  # noqa: E402


def cmd_detect(con, args):
    found = P.detect(" ".join(args.text), P.directory(con), include_self=args.include_self)
    if args.json:
        print(json.dumps([{"slug": p.slug, "name": p.name, "note": p.note, "match": s, "ambiguous": a,
                           "linked_from": p.weight} for p, s, a in found], indent=1))
        return 0
    if not found:
        print("nobody named")
    for p, s, a in found:
        print("%s  [%s%s]  %s  (linked from %d note(s))" % (p.name, s, ", ambiguous" if a else "", p.note, p.weight))
    return 0


def cmd_context(con, args):
    text = " ".join(args.text)
    projects = list(args.project)
    if not projects and text and not args.no_auto_project:
        detected, _p, _m = P.context(con, text, (), args.person)
        projects = P.likely_projects(con, text, detected)
    detected, project_paths, merged = P.context(con, text, projects, args.person, args.since)
    counts = P.summary(merged)
    if args.json:
        print(json.dumps({"people": [{"slug": p.slug, "name": p.name, "note": p.note, "match": s, "ambiguous": a}
                                     for p, s, a in detected],
                          "projects": project_paths, "counts": counts, "notes": merged[:args.limit]}, indent=1))
        return 0
    if not detected and not project_paths:
        print("no person and no project found in: %s" % (text or " ".join(args.person)))
        return 0
    for p, _s, a in detected:
        print("person   %s  %s%s" % (p.name, p.note, "  AMBIGUOUS, confirm who" if a else ""))
    for path in project_paths:
        print("project  %s" % path)
    print("\nnotes: %(person)d by person, %(project)d by project, %(common)d in common, %(unique)d to read once"
          % counts)
    for m in merged[:args.limit]:
        side = "both   " if m["people"] and m["projects"] else ("person " if m["people"] else "project")
        who = ",".join(sorted(m["people"])).replace("entity-", "")
        print("  %s  %s  %s  %s" % (side, m["date"], m["path"], who))
    if len(merged) > args.limit:
        print("  ... %d more (raise --limit)" % (len(merged) - args.limit))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="people", description="who a name means, and the notes about them")
    sub = ap.add_subparsers(dest="cmd")
    d = sub.add_parser("detect", help="the people a text names")
    d.add_argument("text", nargs="+")
    d.add_argument("--include-self", action="store_true", help="also the user's own entity note")
    d.add_argument("--json", action="store_true")
    c = sub.add_parser("context", help="the people and project a text names, and their notes once each")
    c.add_argument("text", nargs="*")
    c.add_argument("--person", action="append", default=[])
    c.add_argument("--project", action="append", default=[])
    c.add_argument("--since", default="", help="only notes dated on or after YYYY-MM-DD")
    c.add_argument("--limit", type=int, default=25)
    c.add_argument("--no-auto-project", action="store_true", help="do not guess the project from the text")
    c.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd not in ("detect", "context"):
        ap.print_help()
        return 2
    if not B.enabled():
        print("vault unavailable")
        return 0
    con = B.db()
    try:
        return cmd_detect(con, args) if args.cmd == "detect" else cmd_context(con, args)
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
