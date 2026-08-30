#!/usr/bin/env python3
"""vw — vault write. The only permitted path for writing shared notes.

  vw.py append <rel-path>            (content on stdin)
  vw.py new    <rel-path> --title T [--type decision] [--project p] [--area a] [--tag t]

It does three things Write/Edit do not:
  1. redacts credentials before writing,
  2. serialises with a per-file lock (several sessions at once),
  3. writes atomically (os.replace), so it does not fight Obsidian's buffer.
"""
import os, sys, time, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B

# Notes written in this run. They get reindexed at the end, OUTSIDE the flock:
# doing it inside hung the process waiting on the database.
_ESCRITAS = []

LOG_HEADING = "## Log"


def resolve(rel):
    path = rel if os.path.isabs(rel) else os.path.join(B.VAULT, rel)
    if not B.in_vault(path):
        sys.stderr.write("vw: path outside the vault: %s\n" % rel)
        sys.exit(1)
    return path


def frontmatter(title, ntype, projects, areas, tags, source="agent", provenance=""):
    today = time.strftime("%Y-%m-%d")
    slug = "".join(c if c.isalnum() else "-" for c in title.lower())[:60].strip("-")
    return ("---\nid: %s-%s\ntitle: %s\ntype: %s\narea: [%s]\nprojects: [%s]\n"
            "tags: [%s]\nstatus: active\nconfidence: medium\nsource: %s\n"
            "provenance: %s\nupdated: %s\nsupersedes: []\n---\n\n"
            % (today, slug, title, ntype, ", ".join(areas), ", ".join(projects),
               ", ".join(tags), source, provenance, today))


def _lease_redirect(path, sid):
    """If another machine holds this note's lease, where do we write instead?

    Returns (alternative_path, owner) or (None, None). It is a LOCAL lookup — an open()
    on the cache lease.py leaves behind — so it adds no network and no wait: if the cache
    is not there, it says nothing and we write where we always do.

    The redirect is not a restriction, it is how the text survives: two machines
    appending to the end of the same note produce a merge conflict git cannot resolve,
    and the work ends up in a `.rej` or in a hand resolution. A new linked note says the
    same thing and merges by itself.
    """
    rel = os.path.relpath(path, B.VAULT)
    if rel.split("/")[0] not in ("10-Projects", "70-Entities"):
        return None, None
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import lease as L
        if L.local_state(rel, sid or "") != "foreign":
            return None, None
        owner = L.local_owner(rel, sid or "")
    except Exception:
        return None, None
    base = os.path.splitext(os.path.basename(rel))[0]
    alt = os.path.join(B.VAULT, "30-Knowledge", "%s-note-by-%s-about-%s.md"
                       % (time.strftime("%Y-%m-%d"), B.sid8(sid or "session"), base[:60]))
    return alt, owner


def cmd_append(args):
    path = resolve(args.path)
    content = sys.stdin.read()
    content, redacted = B.scrub_secrets(content)
    if redacted:
        sys.stderr.write("vw: " + B.redaction_notice(redacted))
    stamp = time.strftime("%Y-%m-%d %H:%M")
    entry = "\n- **%s**%s — %s\n" % (stamp, (" · " + args.sid) if args.sid else "",
                                    content.strip())

    alt, owner = _lease_redirect(path, args.sid)
    if alt:
        source = os.path.relpath(path, B.VAULT)
        sys.stderr.write(
            "vw: %s is leased by %s. Writing to a new linked note instead, to avoid\n"
            "    causing a merge conflict: %s\n"
            % (source, owner, os.path.relpath(alt, B.VAULT)))
        B.log("lease", "desvio", de=source, a=os.path.relpath(alt, B.VAULT), owner=owner)
        with B.flock(alt):
            if os.path.exists(alt):
                text = open(alt, errors="replace").read()
            else:
                text = frontmatter(
                    "Notes from this session about %s" % os.path.splitext(
                        os.path.basename(source))[0],
                    "session", [], [], [],
                    provenance="written separately because %s held the lease on [[%s]]"
                               % (owner, os.path.splitext(os.path.basename(source))[0]))
                text += ("This would go in [[%s]], but another machine held it. Merge it\n"
                         "by hand or leave it linked here.\n\n%s\n"
                         % (os.path.splitext(os.path.basename(source))[0], LOG_HEADING))
            text = text.rstrip() + entry
            B.atomic_write(alt, text)
            _ESCRITAS.append(alt)
        B.mark_wrote(args.sid)
        print(os.path.relpath(alt, B.VAULT))
        return

    with B.flock(path):
        if os.path.exists(path):
            text = open(path, errors="replace").read()
        else:
            text = frontmatter(os.path.splitext(os.path.basename(path))[0],
                               "project", [], [], [])
        if LOG_HEADING not in text:
            text = text.rstrip() + "\n\n" + LOG_HEADING + "\n"
        text = text.rstrip() + entry
        B.atomic_write(path, text)
        _ESCRITAS.append(path)
    B.mark_wrote(args.sid)
    print(os.path.relpath(path, B.VAULT))


def cmd_new(args):
    path = resolve(args.path)
    body = sys.stdin.read() if not sys.stdin.isatty() else ""
    body, redacted = B.scrub_secrets(body)
    if redacted:
        sys.stderr.write("vw: " + B.redaction_notice(redacted))
    with B.flock(path):
        if os.path.exists(path) and not args.force:
            sys.stderr.write("vw: already exists (use --force or append): %s\n" % path)
            sys.exit(1)
        text = frontmatter(args.title, args.type, args.project, args.area, args.tag,
                           provenance=args.provenance or "") + body.strip() + "\n"
        B.atomic_write(path, text)
        _ESCRITAS.append(path)
    B.mark_wrote(args.sid)
    print(os.path.relpath(path, B.VAULT))


def cmd_set(args):
    """Replace a section or one specific line, instead of only appending at the end.

    Without this a shared note only grows: the librarian spotted a MOC header going stale
    while the log below it said the opposite.
    """
    path = resolve(args.path)
    new_one = sys.stdin.read()
    new_one, redacted = B.scrub_secrets(new_one)
    if redacted:
        sys.stderr.write("vw: " + B.redaction_notice(redacted))
    with B.flock(path):
        if not os.path.exists(path):
            sys.stderr.write("vw: does not exist: %s\n" % path)
            sys.exit(1)
        text = open(path, errors="replace").read()
        if args.section:
            lines, out, dentro, hecho = text.splitlines(True), [], False, False
            for line in lines:
                if line.strip() == args.section.strip():
                    out.append(line)
                    out.append("\n" + new_one.strip() + "\n")
                    dentro, hecho = True, True
                    continue
                if dentro and line.startswith("#"):
                    dentro = False
                if not dentro:
                    out.append(line)
            if not hecho:
                sys.stderr.write("vw: section not found: %s\n" % args.section)
                sys.exit(1)
            text = "".join(out)
        elif args.match:
            if args.match not in text:
                sys.stderr.write("vw: text not found: %s\n" % args.match)
                sys.exit(1)
            text = text.replace(args.match, new_one.strip(), 1)
        else:
            sys.stderr.write("vw: use --section or --match\n")
            sys.exit(1)
        B.atomic_write(path, text)
        _ESCRITAS.append(path)
    B.mark_wrote(args.sid)
    print(os.path.relpath(path, B.VAULT))


def main():
    ap = argparse.ArgumentParser(prog="vw")
    sub = ap.add_subparsers(dest="cmd")
    a = sub.add_parser("append"); a.add_argument("path"); a.add_argument("--sid", default="")
    n = sub.add_parser("new")
    n.add_argument("path"); n.add_argument("--title", required=True)
    n.add_argument("--type", default="decision"); n.add_argument("--project", action="append", default=[])
    n.add_argument("--area", action="append", default=[]); n.add_argument("--tag", action="append", default=[])
    n.add_argument("--provenance", default=""); n.add_argument("--sid", default="")
    n.add_argument("--force", action="store_true")
    st = sub.add_parser("set", help="replace a section (--section) or a text (--match)")
    st.add_argument("path"); st.add_argument("--section", default="")
    st.add_argument("--match", default=""); st.add_argument("--sid", default="")

    args = ap.parse_args()
    if args.cmd == "set":
        cmd_set(args)
    elif args.cmd == "append":
        cmd_append(args)
    elif args.cmd == "new":
        cmd_new(args)
    else:
        ap.print_help(); sys.exit(1)


if __name__ == "__main__":
    main()
    if _ESCRITAS:                       # the graph is updated on every write
        B.reindex_notes(_ESCRITAS)
