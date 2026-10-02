#!/usr/bin/env python3
"""Vault search for the agents. Replaces grep/rg: it uses the FTS5 index.

  query.py "terms"                    -> retrievable notes only (10/20/30/70)
  query.py "terms" --all              -> includes sessions, packs, inbox, meta
  query.py "terms" --limit 20 --type decision --project brain
  query.py --recent 10                -> most recently updated notes
  query.py "terms" --person "Dana"    -> also that person's entity note and notes

When the terms name a person (or --person is given), the results end with the person's entity
note and the notes about them; with --project too, the notes they share are merged so each is
listed once (people_core).
"""
import os, sys, argparse, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B


def main():
    ap = argparse.ArgumentParser(prog="query")
    ap.add_argument("terms", nargs="*")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--all", action="store_true", help="include 50-Sessions and 60-Context-Packs")
    ap.add_argument("--type", default="")
    ap.add_argument("--project", default="")
    ap.add_argument("--recent", type=int, default=0)
    ap.add_argument("--full", action="store_true", help="print the whole note")
    ap.add_argument("--person", action="append", default=[],
                    help="a person whose entity note and notes to add (repeatable)")
    args = ap.parse_args()

    if not B.enabled():
        print("vault unavailable"); return 0
    con = B.db()
    # Every search looks for broken links and fixes what has a safe fix (a standing
    # rule). Before searching, so the results already use the fixed graph.
    links = None
    try:
        import linkfix as LF
        links = LF.run(con)
    except Exception as e:
        B.log_error("query.linkfix", e)

    if args.recent:
        rows = con.execute(
            "SELECT path, title, ntype, updated, excerpt FROM notes "
            "WHERE status='active' ORDER BY updated DESC, mtime DESC LIMIT ?",
            (args.recent,)).fetchall()
        for p, t, ty, u, e in rows:
            print("%s  [%s]  %s\n    %s\n" % (t, ty or "-", p, (e or "")[:150]))
        return 0

    query = " ".join(args.terms)
    san = B.sanitize_fts(query, max_terms=16)
    if not san and args.person:
        return people_section(con, query, args)
    if not san:
        print("empty query after sanitising"); return 0
    sql = ("SELECT f.path, bm25(notes_fts) s, n.title, n.ntype, n.updated, n.excerpt, "
           "n.projects, n.status, n.source FROM notes_fts f JOIN notes n ON n.path=f.path "
           "WHERE notes_fts MATCH ?")
    params = [san[0]]
    if not args.all:
        sql += " AND n.retrievable = 1"
    if args.type:
        sql += " AND n.ntype = ?"; params.append(args.type)
    if args.project:
        sql += " AND n.projects LIKE ?"; params.append("%" + args.project + "%")
    sql += " ORDER BY s LIMIT ?"; params.append(args.limit)
    try:
        rows = con.execute(sql, params).fetchall()
    except Exception as exc:
        print("query error: %r" % exc); return 1

    if links:
        res, changed, fixed = links
        if fixed:
            print("(links: fixed %d broken link(s) in %d note(s) before searching)\n"
                  % (fixed, len(changed)))
        if res["broken"]:
            print(LF.notice(res, limit=5) + "\n")
    if not rows:
        print("no results for: %s" % query)
        print("(try --all to include sessions and context packs)")
        return people_section(con, query, args)
    for path, s, title, ntype, updated, excerpt, projects, status, source in rows:
        flags = [x for x in (ntype, status if status != "active" else "",
                             "source:" + source if source != "human" else "") if x]
        print("── %s  [%s]" % (title, " ".join(flags)))
        print("   %s   (updated %s)" % (path, updated or "?"))
        if args.full:
            try:
                print("\n" + open(os.path.join(B.VAULT, path), errors="replace").read() + "\n")
            except Exception:
                pass
        elif excerpt:
            print("   %s" % excerpt[:200])
        print()
    return people_section(con, query, args)


def people_section(con, query, args, limit=8):
    """The people the query names (or --person gives), their entity note and the notes about
    them, merged with --project's notes so a shared note is listed once. Silent when nobody is
    named."""
    try:
        import people_core as P
        projects = [args.project] if args.project else []
        detected, project_paths, merged = P.context(con, query, projects, args.person)
    except Exception as e:
        B.log_error("query.people", e)
        return 0
    if not detected:
        return 0
    print("── people named")
    for p, _strength, ambiguous in detected:
        print("   %s  %s%s" % (p.name, p.note, "  (ambiguous name, confirm who)" if ambiguous else ""))
    c = P.summary(merged)
    tail = (", %(common)d shared with the project, %(unique)d to read once" % c) if project_paths else ""
    print("   notes: %d%s" % (c["person"], tail))
    for m in merged[:limit]:
        side = ("  (person and project)" if m["people"] and m["projects"]
                else "  (project only)" if m["projects"] else "")
        print("   %s  %s%s" % (m["date"], m["path"], side))
    if len(merged) > limit:
        print("   ... all of them: python3 ~/Brain/_bin/people.py context %s%s"
              % (" ".join('--person "%s"' % p.name for p, _s, _a in detected),
                 ' --project "%s"' % args.project if args.project else ""))
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
