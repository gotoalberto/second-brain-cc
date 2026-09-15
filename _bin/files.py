#!/usr/bin/env python3
"""files — the vault's file store, in a local directory.

The git vault holds the MEMORY (notes, relations, decisions). The files (deliverables,
intermediate steps, source material) live in the files directory, outside the repository, and
every note that explains one carries a pointer to it. That way the memory never has to shrink.

    files.py put <file...> --to <note> --project <slug> [--kind deliverable|intermediate|material]
                 [--caption "..."] [--date YYYY-MM-DD]
    files.py ls [--project <slug>]
    files.py get <key> [--out <dir>]
    files.py check                    # broken references and orphaned files

The directory is BRAIN_FILES_DIR when set, otherwise the one chosen in the first run's files step
(brain_files.py). The rules (keys, anchoring, the manifest, the check) are in files_core.py; this
file only reads and writes. See 30-Knowledge/2026-09-15-decision-file-vault-in-a-local-directory.md.
"""
import argparse
import datetime as dt
import hashlib
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brain_files  # noqa: E402
import brainlib as B  # noqa: E402
import files_core as F  # noqa: E402


def die(msg, code=1):
    sys.stderr.write("files: %s\n" % msg)
    sys.exit(code)


def files_root():
    root = brain_files.files_dir()
    if not root:
        die(brain_files.UNCONFIGURED, 3)
    return root


def existing_root():
    root = files_root()
    if not os.path.isdir(root):
        die("the files directory does not exist: %s" % root)
    return root


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def note_path(rel):
    full = os.path.abspath(os.path.join(B.VAULT, rel))
    if not full.startswith(os.path.abspath(B.VAULT) + os.sep) or not os.path.isfile(full):
        die("the note does not exist in the vault: %s" % rel)
    return full


def stored_keys(root, project=None):
    """Every content key under the files directory, or under one project's folder."""
    top = os.path.join(root, project) if project else root
    keys = []
    for dirpath, dirnames, filenames in os.walk(top):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for fn in sorted(filenames):
            k = os.path.relpath(os.path.join(dirpath, fn), root).replace(os.sep, "/")
            if F.is_content_key(k):
                keys.append(k)
    return keys


def store(src, dest, dg):
    """Copy src to dest through a temporary name. False when dest already holds this content."""
    if os.path.isfile(dest):
        if sha256(dest) == dg:
            return False
        die("%s already exists with different content: nothing is replaced" % dest)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = "%s.tmp.%d" % (dest, os.getpid())
    try:
        shutil.copyfile(src, tmp)
        shutil.copymode(src, tmp)
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return True


def anchor(note_rel, entries):
    """Write the references into the note, inside the same flock vw.py uses, then reindex it."""
    full = note_path(note_rel)
    lines = [F.entry_line(k, caption, size, dg) for k, caption, size, dg in entries]
    # --caption is free text: a credential pasted into it never reaches the vault.
    clean, redacted = B.scrub_secrets("\n".join(lines))
    if redacted:
        sys.stderr.write("files: " + B.redaction_notice(redacted))
    with B.flock(full):
        with open(full, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        new_text, added = F.anchor(text, clean.splitlines())
        if added:
            B.atomic_write(full, new_text)
    # The reindex goes outside the flock: inside it, the process could hang waiting on the database.
    if added:
        B.reindex_notes([full])
    return len(added)


def write_manifest(root, project, fresh):
    path = F.key_path(root, F.manifest_key(project))
    with B.flock(path):
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            text = ""
        prev, readable = F.parse_manifest(text)
        if not readable:
            sys.stderr.write("files: %s is not a valid manifest; rebuilding it from the directory listing "
                             "(descriptions are lost)\n" % path)
        doc = F.merge_manifest(project, prev, fresh, stored_keys(root, project), dt.datetime.now().astimezone())
        B.atomic_write(path, F.render_manifest(doc))
    return len(doc["objects"])


def cmd_put(a):
    note_path(a.to)
    date = a.date or dt.date.today().isoformat()
    root = files_root()
    entries, for_manifest = [], []
    for f in a.file:
        if not os.path.isfile(f):
            die("does not exist: %s" % f)
        size, dg = os.path.getsize(f), sha256(f)
        try:
            k = F.key(a.project, a.kind, os.path.basename(f), date, dg)
            dest = F.key_path(root, k)
        except ValueError as exc:
            die(str(exc), 2)
        copied = store(f, dest, dg)
        caption = " ".join((a.caption or os.path.basename(f)).split())
        entries.append((k, caption, size, dg))
        for_manifest.append((k, caption, size, dg, a.to, a.kind))
        print("%s %s  (%s)" % ("stored" if copied else "already stored", k, F.human(size)))
    n = anchor(a.to, entries)
    print("anchored in %s (%d new reference(s))" % (a.to, n))
    print("manifest for %s: %d objects" % (a.project, write_manifest(root, a.project, for_manifest)))
    return 0


def cmd_ls(a):
    root = existing_root()
    if a.project and not F.valid_slug(a.project):
        die("not a project slug: %r" % a.project, 2)
    keys = stored_keys(root, a.project)
    for k in keys:
        st = os.stat(F.key_path(root, k))
        print("  %-10s %-10s %s" % (F.human(st.st_size), dt.date.fromtimestamp(st.st_mtime).isoformat(), k))
    if not keys:
        print("(empty)")
        return 0
    print("\n%d file(s)" % len(keys))
    return 0


def cmd_get(a):
    root = existing_root()
    try:
        src = F.key_path(root, a.key)
    except ValueError as exc:
        die(str(exc), 2)
    if not os.path.isfile(src):
        alt = F.variant(a.key, stored_keys(root, a.key.split("/", 1)[0]))
        if not alt:
            die("no such file in the store: %s" % a.key)
        sys.stderr.write("files: %s is not there; copying %s\n" % (a.key, alt))
        src = F.key_path(root, alt)
    out = a.out or os.getcwd()
    os.makedirs(out, exist_ok=True)
    dest = os.path.join(out, os.path.basename(src))
    shutil.copyfile(src, dest)
    print("copied: %s (%s)" % (dest, F.human(os.path.getsize(dest))))
    return 0


def vault_notes():
    for dirpath, dirnames, filenames in os.walk(B.VAULT):
        dirnames[:] = [d for d in dirnames if not d.startswith((".", "_")) or d == "_assets"]
        for fn in filenames:
            if fn.endswith(".md"):
                full = os.path.join(dirpath, fn)
                with open(full, encoding="utf-8", errors="replace") as fh:
                    yield os.path.relpath(full, B.VAULT), fh.read()


def cmd_check(a):
    """References in notes to files no longer in the store, and stored files nobody cites."""
    root = existing_root()
    cited = F.cited_keys(vault_notes())
    stored = stored_keys(root)
    broken, orphans = F.check(cited, stored)
    print("files stored: %d   cited by notes: %d" % (len(stored), len(cited)))
    print("\nbroken references (the note cites something no longer there): %d" % len(broken))
    for k in broken[:10]:
        print("  %s  <- %s" % (k, ", ".join(cited[k])))
    print("\norphans (stored but nobody cites them): %d" % len(orphans))
    for k in orphans[:10]:
        print("  %s" % k)
    return 1 if (broken or orphans) else 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="files.py", description="the vault's file store, in a local directory")
    sub = p.add_subparsers(dest="cmd")

    q = sub.add_parser("put", help="stores files and anchors them to a note")
    q.add_argument("file", nargs="+")
    q.add_argument("--to", required=True, help="note that explains them (path relative to the vault)")
    q.add_argument("--project", required=True, help="project slug")
    q.add_argument("--kind", default="deliverable", choices=F.KINDS, help="deliverable (default), intermediate or material")
    q.add_argument("--caption", help="shared description")
    q.add_argument("--date", help="folder date, YYYY-MM-DD (defaults to today)")
    q.set_defaults(fn=cmd_put)

    q = sub.add_parser("ls", help="what is stored")
    q.add_argument("--project")
    q.set_defaults(fn=cmd_ls)

    q = sub.add_parser("get", help="copies a stored file out")
    q.add_argument("key")
    q.add_argument("--out", help="directory to copy into (defaults to the current one)")
    q.set_defaults(fn=cmd_get)

    q = sub.add_parser("check", help="broken references and orphaned files")
    q.set_defaults(fn=cmd_check)

    a = p.parse_args(sys.argv[1:] if argv is None else argv)
    if not a.cmd:
        p.print_help(sys.stderr)
        return 2
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
