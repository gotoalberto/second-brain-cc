#!/usr/bin/env python3
"""va — vault asset. Puts a binary into the vault and anchors it to a note.

  va.py add <file...> --to <note.md> [--collection c] [--caption "..."] [--force]
  va.py list [--collection c]
  va.py check

Why it exists: the indexer only reads `.md`, so a loose file in `_assets/` is invisible
to `/recall` — it is on disk but not in memory. This tool
copies the binary and writes its reference inside a note, which is what makes it
findable. An asset with no note is not context, it is tidy rubbish.

Rules it enforces, and why:
  1. `--to` is mandatory: nothing enters `_assets/` without a note explaining it.
  2. Dedupes by SHA-256: the same image saved twice is a single file on disk.
  3. Size limit: the vault is a git repo cloned in full, not a CDN.
  4. Whitelisted extensions: an executable binary is not documentation.
  5. In `10-Projects/` and `70-Entities/` it delegates to vw.py, as the protocol requires.

SUPERSEDED by s3v.py (2026-08-26). Vault files no longer live in the repository:
they go to a private S3 bucket and the note keeps the key. See
30-Knowledge/2026-08-26-decision-file-vault-in-s3.md.

It stays because `_assets/` is still right for small images Obsidian has to render
inside a note; for everything else, s3v.py.
"""
import os, re, sys, time, shutil, hashlib, argparse, unicodedata, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B

# Notes written in this run. They get reindexed at the end, OUTSIDE the flock:
# doing it inside hung the process waiting on the database.
_ESCRITAS = []

ASSETS = os.path.join(B.VAULT, "_assets")
PROTECTED = ("10-Projects", "70-Entities")
HEADING = "## Attachments"

# Formats that make sense as a note's context. Everything else needs --force. The code
# group is here because the deliverables convention asks for the
# build scripts alongside the source: without them the deliverable cannot be rebuilt.
# They are plain text; if one carried a credential, vault_sync.py's secret_gate blocks
# it before it reaches the remote.
ALLOWED = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".svg", ".heic",
    ".pdf", ".html", ".csv", ".tsv", ".json", ".txt", ".md", ".srt", ".vtt",
    ".mp3", ".m4a", ".wav", ".mp4", ".mov", ".webm", ".zip",
    ".py", ".sh", ".js", ".ts", ".css", ".sql", ".yaml", ".yml", ".toml", ".ini",
}
EMBEDDABLE = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".svg"}
WARN_MB, MAX_MB = 2, 25


def die(msg):
    sys.stderr.write("va: %s\n" % msg)
    sys.exit(1)


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.0f %s" % (n, unit) if unit == "B" else "%.1f %s" % (n, unit)
        n /= 1024.0


def slugify(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    out = "".join(c if c.isalnum() else "-" for c in text.lower())
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")[:70] or "asset"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def note_files():
    """Every note in the vault, for resolving references. Includes 80-Private."""
    for root, dirs, files in os.walk(B.VAULT):
        dirs[:] = [d for d in dirs if not d.startswith(".")
                   and d not in ("_index", "_bin", "_assets", "plugin")]
        for fn in files:
            if fn.endswith(".md"):
                yield os.path.join(root, fn)


# A reference counts the same inside `backticks`, [[wikilinks]] or (parentheses), so it
# is cut at the first character that cannot be part of a path. Names are normalised by
# slugify(), so they never contain spaces.
REF = re.compile(r"_assets/[A-Za-z0-9._/-]+")


def references():
    """Map asset_rel -> [notes citing it]. Used for orphans and to avoid deleting
    blindly: before touching an asset you have to know who is using it."""
    refs = {}
    for note in note_files():
        try:
            text = open(note, errors="replace").read()
        except Exception:
            continue
        if "_assets/" not in text:
            continue
        rel_note = os.path.relpath(note, B.VAULT)
        for hit in REF.findall(text):
            hit = hit.rstrip("/.-")
            if hit != "_assets" and os.path.splitext(hit)[1]:
                refs.setdefault(hit, []).append(rel_note)
    return refs


def existing_ref(coll_dir, digest, size):
    """Return the path of an identical asset already stored, if there is one."""
    if not os.path.isdir(coll_dir):
        return None
    for fn in sorted(os.listdir(coll_dir)):
        full = os.path.join(coll_dir, fn)
        if os.path.isfile(full) and os.path.getsize(full) == size and sha256(full) == digest:
            return full
    return None


def target(coll_dir, name):
    """A free name within the collection, without clobbering different content."""
    base, ext = os.path.splitext(name)
    cand, n = os.path.join(coll_dir, base + ext), 2
    while os.path.exists(cand):
        cand = os.path.join(coll_dir, "%s-%d%s" % (base, n, ext))
        n += 1
    return cand


def anchor(note_rel, entries, sid):
    """Write the references into the note. In protected areas, through vw.py."""
    path = os.path.join(B.VAULT, note_rel)
    if not os.path.exists(path):
        die("the note does not exist: %s (create it first: no assets without a note)" % note_rel)

    # Re-adding an asset the note already cites must not duplicate the reference:
    # `add` is repeated when retrying a batch, and the note ended up with the image twice.
    # Filtering is by whole entry (reference + its caption), not line by line, so no
    # as to leave a stray caption without the image it describes.
    current = open(path, errors="replace").read()
    fresh = [text for rel, text in entries if rel not in current]
    if not fresh:
        return "already-cited"
    block = "\n".join(fresh)

    if note_rel.split(os.sep)[0] in PROTECTED:
        # These notes are shared between sessions: only vw.py may touch them.
        vw = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vw.py")
        cmd = [sys.executable, vw, "append", note_rel]
        if sid:
            cmd += ["--sid", sid]
        p = subprocess.run(cmd, input="Attachments:\n" + block, text=True,
                           capture_output=True, timeout=30)
        if p.returncode != 0:
            die("vw.py failed: %s" % (p.stderr.strip() or p.returncode))
        return "log"

    with B.flock(path):
        text = open(path, errors="replace").read()
        if HEADING in text:
            # Appended at the end of the existing section, not the end of the file:
            # that way attachments do not scatter through the note as it grows.
            cabeza, rest = text.split(HEADING, 1)
            corte = len(rest)
            for i, line in enumerate(rest.splitlines(True)):
                if i and line.startswith("#"):
                    corte = rest.index(line)
                    break
            text = cabeza + HEADING + rest[:corte].rstrip() + "\n" + block + "\n\n" + rest[corte:]
        else:
            text = text.rstrip() + "\n\n" + HEADING + "\n" + block + "\n"
        B.atomic_write(path, text)
        _ESCRITAS.append(path)
    B.mark_wrote(sid)
    return "section"


def cmd_add(args):
    coll = slugify(args.collection or os.path.splitext(os.path.basename(args.to))[0])
    coll_dir = os.path.join(ASSETS, coll)

    # Everything is validated before copying anything: if the third of five is bad, no
    # want two files inside and the note left unanchored.
    sources = []
    for src in args.file:
        src = os.path.abspath(os.path.expanduser(src))
        if not os.path.isfile(src):
            die("does not exist or is not a file: %s" % src)
        ext = os.path.splitext(src)[1].lower()
        if ext not in ALLOWED and not args.force:
            die("extension not allowed: %s (use --force if it is genuinely needed)" % ext)
        size = os.path.getsize(src)
        if size > MAX_MB * 1024 * 1024 and not args.force:
            die("%s weighs %s; the vault is cloned in full, max %d MB without --force"
                % (os.path.basename(src), human(size), MAX_MB))
        sources.append((src, size, ext))
    if not os.path.exists(os.path.join(B.VAULT, args.to)):
        die("the note does not exist: %s (create it first: no assets without a note)" % args.to)
    os.makedirs(coll_dir, exist_ok=True)

    entries, guardados = [], []
    for src, size, ext in sources:      # the extension travels with each source: when it
        digest = sha256(src)            # was taken from the validation loop, the whole
                                        # batch inherited the last file's extension.
        ya = existing_ref(coll_dir, digest, size)
        if ya:
            dst = ya
            status = "already there"
        else:
            dst = target(coll_dir, slugify(os.path.splitext(os.path.basename(src))[0]) + ext)
            shutil.copy2(src, dst)
            status = "copied"
        rel = os.path.relpath(dst, B.VAULT)
        guardados.append((rel, size, status))
        if size > WARN_MB * 1024 * 1024:
            sys.stderr.write("va: warning — %s weighs %s, it fattens the vault clone\n"
                             % (os.path.basename(rel), human(size)))

        caption_ = args.caption or os.path.splitext(os.path.basename(src))[0].replace("-", " ")
        if os.path.splitext(rel)[1].lower() in EMBEDDABLE and not args.no_embed:
            entries.append((rel, "![[%s]]\n*%s*" % (rel, caption_)))
        else:
            entries.append((rel, "- [[%s]] — %s (%s)" % (rel, caption_, human(size))))

    mode = anchor(args.to, entries, args.sid)
    for rel, size, status in guardados:
        print("%-9s %s  (%s)" % (status, rel, human(size)))
    target_txt = {"section": "Attachments section", "log": "log",
                   "already-cited": "no changes, the note already cited them"}[mode]
    print("anchored in %s (%s)" % (args.to, target_txt))


def cmd_list(args):
    if not os.path.isdir(ASSETS):
        print("no assets yet"); return
    refs = references()
    total_n = total_b = 0
    for coll in sorted(os.listdir(ASSETS)):
        cdir = os.path.join(ASSETS, coll)
        if not os.path.isdir(cdir) or (args.collection and coll != args.collection):
            continue
        files = sorted(f for f in os.listdir(cdir) if not f.startswith("."))
        size = sum(os.path.getsize(os.path.join(cdir, f)) for f in files)
        total_n += len(files); total_b += size
        print("\n%s/  — %d ficheros, %s" % (coll, len(files), human(size)))
        for f in files:
            rel = "_assets/%s/%s" % (coll, f)
            usos = refs.get(rel, [])
            print("  %-46s %8s  %s" % (f, human(os.path.getsize(os.path.join(cdir, f))),
                                       ("← " + usos[0]) if usos else "HUÉRFANO"))
    print("\ntotal: %d ficheros, %s" % (total_n, human(total_b)))


def cmd_check(args):
    refs = references()
    en_disco = set()
    for root, dirs, files in os.walk(ASSETS):
        for fn in files:
            if not fn.startswith("."):
                en_disco.add(os.path.relpath(os.path.join(root, fn), B.VAULT))

    orphans = sorted(en_disco - set(refs))
    broken = sorted(r for r in refs if r not in en_disco)
    pesados = sorted((os.path.getsize(os.path.join(B.VAULT, r)), r) for r in en_disco
                     if os.path.getsize(os.path.join(B.VAULT, r)) > WARN_MB * 1024 * 1024)

    print("assets on disk: %d   referenced: %d" % (len(en_disco), len(en_disco) - len(orphans)))
    print("\norphans (nobody cites them — link them or delete them): %d" % len(orphans))
    for h in orphans[:20]:
        print("  - %s" % h)
    print("\nbroken references (the note cites something missing): %d" % len(broken))
    for r in broken[:20]:
        print("  - %s  ← %s" % (r, ", ".join(refs[r][:2])))
    print("\npesados (> %d MB): %d" % (WARN_MB, len(pesados)))
    for size, r in pesados[:10]:
        print("  - %-52s %s" % (r, human(size)))
    return 1 if broken else 0


def main():
    ap = argparse.ArgumentParser(prog="va", description="the vault's binary assets")
    sub = ap.add_subparsers(dest="cmd")

    a = sub.add_parser("add", help="copies files into _assets/ and anchors them to a note")
    a.add_argument("file", nargs="+")
    a.add_argument("--to", required=True, help="note that explains these assets (path relative to the vault)")
    a.add_argument("--collection", default="", help="subfolder of _assets/ (defaults to the note name)")
    a.add_argument("--caption", default="", help="shared caption for the files")
    a.add_argument("--no-embed", action="store_true", help="link images instead of embedding them")
    a.add_argument("--force", action="store_true", help="skip the type and size limits")
    a.add_argument("--sid", default="")

    l = sub.add_parser("list", help="what is stored and who uses it")
    l.add_argument("--collection", default="")

    sub.add_parser("check", help="orphans, broken references and heavy files")

    args = ap.parse_args()
    if args.cmd == "add":
        cmd_add(args)
    elif args.cmd == "list":
        cmd_list(args)
    elif args.cmd == "check":
        sys.exit(cmd_check(args))
    else:
        ap.print_help(); sys.exit(1)


if __name__ == "__main__":
    main()
    if _ESCRITAS:                       # the graph is updated on every write
        B.reindex_notes(_ESCRITAS)
