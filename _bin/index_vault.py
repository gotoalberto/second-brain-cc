#!/usr/bin/env python3
"""Incremental vault indexer -> _index/vault.db (FTS5).

Walks the indexable folders, detects changes by mtime+size and updates only what
changed. Designed to run in < 100 ms on normal vaults.
"""
import os
import re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B


def note_files():
    for folder in B.INDEXED:
        base = os.path.join(B.VAULT, folder)
        if not os.path.isdir(base):
            continue
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if not d.startswith(".")
                       and d not in ("quarantine", "templates")]
            for fn in files:
                if fn.endswith(".md"):
                    yield os.path.join(root, fn)


def excerpt_of(body, limit=220):
    lines = []
    for line in body.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("<!--") or s.startswith("!["):
            continue
        lines.append(s)
        if sum(len(x) for x in lines) > limit:
            break
    return " ".join(lines)[:limit]


def without_code(text):
    """Strip code blocks and inline code before looking for wikilinks.

    A `[[something]]` inside backticks is an EXAMPLE, not a link. Without this
    the graph filled up with invented edges: the note documenting the
    link convention created an edge to `note-id`, and a Next.js route
    (`app/my-route/[[...slug]]/…`) created another to `...slug`. False edges to
    notes that do not exist, counted afterwards as broken links.
    """
    text = re.sub(r"(?ms)^```.*?^```", "", text)   # bloques cercados
    text = re.sub(r"`[^`\n]*`", "", text)          # inline code
    return text


def index_one(con, path):
    try:
        st = os.stat(path)
        with open(path, "r", errors="replace") as fh:
            text = fh.read()
    except Exception:
        return False
    meta, body = B.parse_frontmatter(text)
    rel = os.path.relpath(path, B.VAULT)
    folder = rel.split(os.sep)[0]
    title = meta.get("title") or os.path.splitext(os.path.basename(path))[0]
    if isinstance(title, list):
        title = " ".join(title)
    retrievable = 1 if (folder in B.RETRIEVABLE
                        and str(meta.get("source", "human")) != "external"
                        and str(meta.get("status", "active")) != "archived") else 0
    con.execute("DELETE FROM notes WHERE path=?", (rel,))
    con.execute("DELETE FROM notes_fts WHERE path=?", (rel,))
    con.execute(
        "INSERT INTO notes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (rel, st.st_mtime, st.st_size, str(title), str(meta.get("type", "")),
         ",".join(B.as_list(meta.get("area"))), ",".join(B.as_list(meta.get("projects"))),
         ",".join(B.as_list(meta.get("tags"))), str(meta.get("status", "active")),
         str(meta.get("confidence", "")), str(meta.get("source", "human")),
         str(meta.get("updated", "")), folder, excerpt_of(body), retrievable))
    searchable = " ".join([str(title),
                           " ".join(B.as_list(meta.get("tags"))),
                           " ".join(B.as_list(meta.get("projects"))),
                           " ".join(B.as_list(meta.get("area")))])
    con.execute("INSERT INTO notes_fts(path, title, body) VALUES(?,?,?)",
                (rel, searchable, body))
    # The graph: every [[target]] is an edge. The slug is stored, not the path,
    # because notes link by name and the path can change.
    con.execute("DELETE FROM links WHERE source=?", (rel,))
    # `![[file.png]]` is an EMBEDDED ATTACHMENT, not a link to another note: it will never
    # resolve to a slug and only adds noise to the graph —and counted as a broken link—.
    # The `(?<!!)` keeps it out; so do the ones with a slash, just in case.
    targets = {d.split("|")[0].split("#")[0].strip()
                for d in re.findall(r"(?<!!)\[\[([^\]]+)\]\]", without_code(body))}
    targets = {d for d in targets if d and "/" not in d}
    for d in targets:
        if d:
            con.execute("INSERT OR IGNORE INTO links VALUES(?,?)", (rel, d))
    return True


def reindex(full=False, quiet=True):
    t0 = time.time()
    con = B.db()
    known = {}
    for rel, mtime, size in con.execute("SELECT path, mtime, size FROM notes"):
        known[rel] = (mtime, size)
    seen, changed = set(), 0
    for path in note_files():
        rel = os.path.relpath(path, B.VAULT)
        seen.add(rel)
        try:
            st = os.stat(path)
        except Exception:
            continue
        prev = known.get(rel)
        if full or prev is None or abs(prev[0] - st.st_mtime) > 0.001 or prev[1] != st.st_size:
            if index_one(con, path):
                changed += 1
    gone = [r for r in known if r not in seen]
    for rel in gone:
        con.execute("DELETE FROM notes WHERE path=?", (rel,))
        con.execute("DELETE FROM notes_fts WHERE path=?", (rel,))
        # Its edges too. Without this the graph piles up links leaving deleted notes:
        # `neighbours()` keeps navigating them and graph retrieval leads to places that
        # are no longer there. There were 16 of those.
        con.execute("DELETE FROM links WHERE source=?", (rel,))
    con.commit()
    total = con.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
    ms = (time.time() - t0) * 1000
    B.metric(con, "indexer", "reindex", hits=changed, latency_ms=ms,
             extra="total=%d deleted=%d" % (total, len(gone)))
    con.close()
    if not quiet:
        print("indexed %d new/changed, %d deleted, %d total, %.0f ms"
              % (changed, len(gone), total, ms))
    return changed, len(gone), total


if __name__ == "__main__":
    if not B.enabled():
        sys.exit(0)
    reindex(full="--full" in sys.argv, quiet=False)
