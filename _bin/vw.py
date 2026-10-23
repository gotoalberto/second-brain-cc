#!/usr/bin/env python3
"""vw — vault write. The only permitted path for writing shared notes.

  vw.py append <rel-path>            (content on stdin)
  vw.py new    <rel-path> --title T [--type decision] [--project p] [--area a] [--tag t]
  vw.py set    <rel-path> --section H | --match TEXT   (content on stdin)

The body is read only from a pipe, a heredoc or `< file`. Any other stdin (a terminal, a
socket that never closes, /dev/null) is no body: `new` writes the note without one, and
`append` and `set` exit 2 at once instead of waiting.

It does three things Write/Edit do not:
  1. redacts credentials before writing,
  2. serialises with a per-file lock (several sessions at once),
  3. writes atomically (os.replace), so it does not fight Obsidian's buffer.
"""
import os, stat, sys, time, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B

# Notes written in this run. They get reindexed at the end, OUTSIDE the flock:
# doing it inside hung the process waiting on the database.
_WRITTEN = []

LOG_HEADING = "## Log"


def normalize(rel, vault=None):
    """The note's path relative to the vault, or (None, why) when it is not a note's path.

    A relative path is relative to the vault root, wherever the caller stands. A session in
    $HOME that writes `Brain/10-Projects/x.md` means `10-Projects/x.md`, and taking it as
    typed made `<vault>/Brain/10-Projects/x.md`: a second tree inside the vault that no
    search, project lookup or sync rule reads. So a leading `<vault folder name>/` is
    dropped, and the first folder must be one of the vault's note folders, or the write is
    refused.
    """
    vault = os.path.normpath(vault or B.VAULT)
    rel = os.path.expanduser(rel)
    path = os.path.normpath(rel if os.path.isabs(rel) else os.path.join(vault, rel))
    if not B.is_within(path, vault):
        return None, "path outside the vault: %s" % rel
    parts = os.path.relpath(path, vault).split(os.sep)
    while len(parts) > 1 and parts[0] == os.path.basename(vault) and parts[1] in B.VAULT_NOTES:
        parts = parts[1:]
    if len(parts) < 2 or parts[0] not in B.VAULT_NOTES:
        return None, ("not inside a note folder of the vault (%s): %s"
                      % (", ".join(B.VAULT_NOTES), rel))
    return os.sep.join(parts), None


def resolve(rel):
    norm, why = normalize(rel)
    if norm is None:
        sys.stderr.write("vw: %s\n" % why)
        sys.exit(1)
    return os.path.join(B.VAULT, norm)


def frontmatter(title, ntype, projects, areas, tags, source="agent", provenance=""):
    today = time.strftime("%Y-%m-%d")
    slug = "".join(c if c.isalnum() else "-" for c in title.lower())[:60].strip("-")
    return ("---\nid: %s-%s\ntitle: %s\ntype: %s\narea: [%s]\nprojects: [%s]\n"
            "tags: [%s]\nstatus: active\nconfidence: medium\nsource: %s\n"
            "provenance: %s\nupdated: %s\nsupersedes: []\n---\n\n"
            % (today, slug, title, ntype, ", ".join(areas), ", ".join(projects),
               ", ".join(tags), source, provenance, today))


def _lease_redirect(path, sid):
    """If another session on this machine holds this note's lease, where do we write instead?

    Returns (alternative_path, owner) or (None, None). It is a local lookup of the lease
    files lease.py keeps in the Brain state directory, so it adds no wait: if there is no
    lease, it says nothing and we write where we always do.

    The redirect is not a restriction, it is how the text survives: two sessions
    appending to the end of the same note produce a merge conflict git cannot resolve,
    and the work ends up in a `.rej` or in a hand resolution. A new linked note says the
    same thing and merges by itself. Across machines git is the safety net.
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


def read_body(required):
    """Body from stdin, without hanging when nothing is ever going to arrive.

    Claude Code's Bash tool hands the process a unix socket on fd 0 that never reaches EOF, so
    a plain sys.stdin.read() blocks for ever, and killing it mid-write leaves a stub note
    behind. Only a regular file or a pipe can carry a body, so anything else (a socket, a
    terminal, /dev/null) is treated as no body at all: `new` goes on without one and
    `append`/`set` fail fast instead of waiting.
    """
    mode = None
    try:
        if sys.stdin is not None and not sys.stdin.closed and not sys.stdin.isatty():
            mode = os.fstat(sys.stdin.fileno()).st_mode
    except (OSError, ValueError):
        mode = None
    if mode is not None and (stat.S_ISREG(mode) or stat.S_ISFIFO(mode)):
        return sys.stdin.read()
    if required:
        sys.stderr.write("vw: nothing on stdin. Pass the body with a heredoc, "
                         "a pipe or '< file'.\n")
        sys.exit(2)
    return ""


def cmd_append(args):
    path = resolve(args.path)
    content = read_body(required=True)
    content, redacted = B.scrub_secrets(content)
    if redacted:
        sys.stderr.write("vw: " + B.redaction_notice(redacted))
    stamp = time.strftime("%Y-%m-%d %H:%M")
    # A colon and not a dash: the write-like-a-person convention bans dashes as punctuation
    # in vault notes too, and this line is written into a note every time anything is logged.
    entry = "\n- **%s**%s: %s\n" % (stamp, (" · " + args.sid) if args.sid else "",
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
                text += ("This would go in [[%s]], but another session held it. Merge it\n"
                         "by hand or leave it linked here.\n\n%s\n"
                         % (os.path.splitext(os.path.basename(source))[0], LOG_HEADING))
            text = text.rstrip() + entry
            B.atomic_write(alt, text)
            _WRITTEN.append(alt)
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
        _WRITTEN.append(path)
    B.mark_wrote(args.sid)
    print(os.path.relpath(path, B.VAULT))


def cmd_new(args):
    path = resolve(args.path)
    body = read_body(required=False)
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
        _WRITTEN.append(path)
    B.mark_wrote(args.sid)
    print(os.path.relpath(path, B.VAULT))


def cmd_set(args):
    """Replace a section or one specific line, instead of only appending at the end.

    Without this a shared note only grows: the librarian spotted a MOC header going stale
    while the log below it said the opposite.
    """
    path = resolve(args.path)
    new_one = read_body(required=True)
    new_one, redacted = B.scrub_secrets(new_one)
    if redacted:
        sys.stderr.write("vw: " + B.redaction_notice(redacted))
    with B.flock(path):
        if not os.path.exists(path):
            sys.stderr.write("vw: does not exist: %s\n" % path)
            sys.exit(1)
        text = open(path, errors="replace").read()
        if args.section:
            # The section ends at the next heading of the SAME OR HIGHER level, not at any
            # "#" line: a "## Entries" section whose entries are "### 1. Company" was being
            # cut short at its own first entry, so every replacement appended a fresh copy
            # and left the old one behind. That silently duplicated the applications log.
            target = args.section.strip()
            level = len(target) - len(target.lstrip("#"))
            lines, out, inside, done = text.splitlines(True), [], False, False
            for line in lines:
                if line.strip() == target:
                    out.append(line)
                    out.append("\n" + new_one.strip() + "\n")
                    inside, done = True, True
                    continue
                if inside and line.startswith("#"):
                    own_level = len(line) - len(line.lstrip("#"))
                    if level == 0 or own_level <= level:
                        inside = False
                if not inside:
                    out.append(line)
            if not done:
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
        _WRITTEN.append(path)
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
    for _p in _WRITTEN:                # so vault_ledger can tell this from a raw write
        B.note_vw_write(_p)
    if _WRITTEN:                       # the graph is updated on every write
        B.reindex_notes(_WRITTEN)
