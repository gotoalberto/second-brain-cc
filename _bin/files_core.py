#!/usr/bin/env python3
"""The rules of the local file store, with no disk, no clock and no process.

files.py (the CLI) reads and writes the files directory and the notes; everything it decides
comes from here: the key a file is stored under, the line that anchors it in a note, how the
per-project manifest is reconciled with what is really on disk, and which references are broken
or orphaned. Paths and data in, values out. See files_core_test.py.

The layout under the files directory (brain_files.py says where that is):

  <project>/material/<name>
  <project>/<YYYY-MM-DD>/<kind>/<name>
  <project>/manifest.json
"""

import json
import os
import re

KINDS = ("deliverable", "intermediate", "material")
MARKER = "## Files"
MANIFEST = "manifest.json"
HEADER = ("Kept in the local files directory, outside the vault. Copy one out with "
          "`python3 ~/Brain/_bin/files.py get <key>`.")

_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MARKER_LINE = re.compile(r"(?m)^## Files[ \t]*$")
_NEXT_SECTION = re.compile(r"(?m)^## ")
_ENTRY_KEY = re.compile(r"(?m)^- `([^`\n]+)`")
# What a stored key looks like when a note cites it: a project slug, then either material/ or a
# date and a kind. The shape is what separates a key from any other `code` in a note.
_CITED = re.compile(r"`([A-Za-z0-9][A-Za-z0-9._-]*/(?:material|\d{4}-\d{2}-\d{2}/(?:deliverable|intermediate|material))"
                    r"/[^`\n]*)`")
_PARTIAL = re.compile(r"\.tmp\.\d+$")


def valid_slug(project):
    return bool(_SLUG.match(project or "")) and project not in (".", "..")


def valid_date(date):
    return bool(_DATE.match(date or ""))


def safe_name(name):
    """A basename fit for a key: no directory part, no backtick, whitespace runs as one dash."""
    name = re.sub(r"[\s`]+", "-", os.path.basename((name or "").replace("\\", "/")).strip())
    if name in ("", ".", ".."):
        raise ValueError("not a usable file name: %r" % name)
    return name


def key(project, kind, name, date, dg=""):
    """The key encodes project, date and kind, so the store can be browsed without opening anything.

    The first 8 hex characters of the sha256 go into the name: two different files with the same
    basename, day, project and kind get different keys instead of the second replacing the first,
    and storing the same content again lands on the same key, so a retried batch duplicates nothing.
    Material has no date: it is source material for the project as a whole.
    """
    if kind not in KINDS:
        raise ValueError("kind must be one of: %s" % ", ".join(KINDS))
    if not valid_slug(project):
        raise ValueError("not a project slug: %r (letters, digits, dot, dash, underscore)" % project)
    name = safe_name(name)
    if dg:
        root, ext = os.path.splitext(name)
        name = "%s-%s%s" % (root, dg[:8], ext)
    if kind == "material":
        return "%s/material/%s" % (project, name)
    if not valid_date(date):
        raise ValueError("not a YYYY-MM-DD date: %r" % date)
    return "%s/%s/%s/%s" % (project, date, kind, name)


def manifest_key(project):
    return "%s/%s" % (project, MANIFEST)


def key_path(root, k):
    """Where a key lives under the files directory. A key that climbs out of it is refused."""
    k = (k or "").replace("\\", "/")
    parts = k.split("/")
    if not k or k.startswith("/") or any(p in ("", ".", "..") for p in parts):
        raise ValueError("not a key: %r" % k)
    return os.path.join(root, *parts)


def is_content_key(k):
    """A stored file a note should cite: not a manifest, not a hidden file, not a half-written copy."""
    base = k.rsplit("/", 1)[-1]
    return base != MANIFEST and not base.startswith(".") and not _PARTIAL.search(base)


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%d B" % n if unit == "B" else "%.1f %s" % (n, unit)
        n /= 1024.0


def entry_line(k, caption, size, dg):
    """One reference, on one line: a newline in the caption would split it and break the dedup."""
    return "- `%s` · %s · %s · `%s`" % (k, " ".join((caption or "").split()), human(size), (dg or "")[:12])


def anchor(text, lines):
    """(new text, lines added): the references go under the note's `## Files` section.

    A file with no pointer from a note is a lost file, so this is what makes the store memory. The
    section is created at the end of the note the first time; after that new lines join it and a
    key already cited there is not added twice.
    """
    seen, fresh = set(), []
    m = _MARKER_LINE.search(text)
    if m:
        start = m.end()
        nxt = _NEXT_SECTION.search(text, start)
        end = nxt.start() if nxt else len(text)
        seen = set(_ENTRY_KEY.findall(text[start:end]))
    for line in lines:
        found = _ENTRY_KEY.match(line)
        k = found.group(1) if found else line
        if k in seen:
            continue
        seen.add(k)
        fresh.append(line)
    if not fresh:
        return text, []
    if not m:
        body = text.rstrip("\n")
        return "%s\n\n%s\n\n%s\n\n%s\n" % (body, MARKER, HEADER, "\n".join(fresh)) if body else \
            "%s\n\n%s\n\n%s\n" % (MARKER, HEADER, "\n".join(fresh)), fresh
    before, after = text[:end].rstrip("\n"), text[end:].lstrip("\n")
    if after:
        return "%s\n%s\n\n%s" % (before, "\n".join(fresh), after), fresh
    return "%s\n%s\n" % (before, "\n".join(fresh)), fresh


def cited_keys(notes):
    """{key: [note, ...]} for every stored-key reference in (relative path, text) pairs.

    A folder prefix (`demo/material/`) explains the layout and points at no file, and a key with
    `<`, `>`, `{` or `}` is a documentation placeholder: neither is a reference, and reporting them
    as broken would teach you to ignore the report.
    """
    cited = {}
    for rel, text in notes:
        for ref in _CITED.findall(text or ""):
            if ref.endswith("/") or any(c in ref for c in "<>{}"):
                continue
            where = cited.setdefault(ref, [])
            if rel not in where:
                where.append(rel)
    return cited


def check(cited, stored):
    """(broken, orphans): cited keys with no file, and stored files no note cites. Both sorted."""
    stored = {k for k in stored if is_content_key(k)}
    broken = sorted(k for k in cited if k not in stored)
    orphans = sorted(k for k in stored if k not in cited)
    return broken, orphans


def variant(k, existing):
    """The same key with the sha256 fragment in its name, when exactly one such file exists.

    A note may cite a name without the fragment. With several candidates nothing is chosen: they
    are different contents, and guessing would be worse than failing.
    """
    root, ext = os.path.splitext(k)
    pat = re.compile(r"^%s-[0-9a-f]{8}%s$" % (re.escape(root), re.escape(ext)))
    found = sorted(e for e in existing if pat.match(e))
    return found[0] if len(found) == 1 else None


def parse_manifest(text):
    """(objects, readable). A missing manifest is ([], True); a corrupt one is ([], False)."""
    if not (text or "").strip():
        return [], True
    try:
        data = json.loads(text)
    except ValueError:
        return [], False
    objects = data.get("objects") if isinstance(data, dict) else None
    if not isinstance(objects, list):
        return [], False
    return [dict(o) for o in objects if isinstance(o, dict) and isinstance(o.get("key"), str)], True


def merge_manifest(project, prev, fresh, real, now):
    """Reconcile the manifest that was read with what is on disk and what was just stored.

    `fresh` is [(key, caption, size, sha256, note, kind)]; `real` the content keys the project's
    folder really holds; `now` a datetime. What is on disk wins: a file nobody listed is recovered
    with a placeholder description, and a listed file that is gone is marked missing (and unmarked
    if it comes back), never silently dropped.
    """
    objects = [dict(o) for o in prev]
    real = set(real)
    seen = {o["key"] for o in objects}
    stamp = now.strftime("%Y-%m-%dT%H:%M:%S%z") if now.tzinfo else now.strftime("%Y-%m-%dT%H:%M:%S")
    for k, caption, size, dg, note, kind in fresh:
        real.add(k)
        if k in seen:
            continue
        objects.append({"key": k, "description": caption, "bytes": size, "sha256": dg, "note": note,
                        "kind": kind, "stored": stamp})
        seen.add(k)
    for k in sorted(real - seen):
        objects.append({"key": k, "description": "(recovered from the directory listing)", "bytes": None,
                        "sha256": None, "note": None, "kind": None, "stored": None})
    for o in objects:
        if o["key"] in real:
            o.pop("missing", None)
        else:
            o["missing"] = True
    return {"project": project, "updated": now.strftime("%Y-%m-%d"), "objects": objects}


def render_manifest(doc):
    return json.dumps(doc, ensure_ascii=False, indent=1) + "\n"
