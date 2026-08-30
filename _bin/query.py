#!/usr/bin/env python3
"""Vault search for the agents. Replaces grep/rg: it uses the FTS5 index.

  query.py "terms"                    -> retrievable notes only (10/20/30/70)
  query.py "terms" --all              -> includes sessions, packs, inbox, meta
  query.py "terms" --limit 20 --type decision --project brain
  query.py --recent 10                -> most recently updated notes
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
    args = ap.parse_args()

    if not B.enabled():
        print("vault unavailable"); return 0
    con = B.db()

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

    if not rows:
        print("no results for: %s" % query)
        print("(try --all to include sessions and context packs)")
        return 0
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
