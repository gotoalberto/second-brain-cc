#!/usr/bin/env python3
"""People in the vault: which person a name means, and the notes about that person.

A name in a prompt ("what did Dana say about the planner") is the strongest signal a question
carries, and full-text search alone misses it: a note about a person links them by
`[[entity-<slug>]]`, not by the words of the question. This module turns a name into the person
(an entity note in 70-Entities tagged `person`) and the person into the notes that link or name
them, so every place that searches for context (the prompt hook, `query.py`, `people.py`) can
add them.

When the same prompt names a person AND a project, the notes of each are fetched and merged by
path, so a note on both lists is read and processed once, and those notes come first.

Who counts as a person, and how a name is matched:

- an entity note whose `tags:` include a person tag (`person` and `contact` by default, more in
  the settings note). Its title is the name; Obsidian's `aliases:` field adds the short forms people actually use;
- two words of the name in order, or an alias, are a strong match; a first or last name alone
  is weak, and a word several people share returns all of them marked ambiguous;
- a first name that is also an ordinary word ("mark", "will") is not a person on its own. The
  built-in list is extended by the settings note below;
- the user's own entity is never detected: it would match every note they wrote.

Settings, all optional, in the frontmatter of the vault note `90-Meta/people.md`:

    self: entity-<your-slug>           the user's own entity note (a list is accepted)
    not_names: [word, word]            more first names that are ordinary words
    person_tags: [tag, tag]            more entity tags that mark a person

Stateless and read only: it asks the index (`notes`, `links`, `note_ids`, `notes_fts`).
"""
import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B  # noqa: E402

ENTITIES = "70-Entities"
SETTINGS = "90-Meta/people.md"
PERSON_TAGS = frozenset({"person", "contact"})
DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}-")

# First names that are also ordinary English words: alone, they are not taken as a person.
DEFAULT_NOT_NAMES = frozenset("""
will mark may june april august grace hope faith joy rose summer dawn bill frank art pat sue
max ray rob jack chase hunter page sky river drew wade lane dean guy major king rich sunny
amber ivy holly penny ruby crystal angel august autumn brook cliff dale glen heath miles
""".split())


def norm(text):
    """Lowercase, no accents, words separated by single spaces."""
    t = unicodedata.normalize("NFKD", text or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return " ".join(re.findall(r"[a-z0-9]+", t))


def slug_of(name):
    """`entity-<slug>` for a filename, an id or a bare slug; dates and `.md` dropped."""
    base = DATE_PREFIX.sub("", os.path.splitext(os.path.basename(str(name or "").strip()))[0])
    return base if base.startswith("entity-") else "entity-" + base


def slug_words(slug):
    words = slug[len("entity-"):].split("-") if slug.startswith("entity-") else slug.split("-")
    return [w for w in words if w]


class Person(object):
    __slots__ = ("slug", "name", "words", "note", "aliases", "weight")

    def __init__(self, slug, name, note, aliases=(), weight=0):
        self.slug, self.name, self.note = slug, name, note
        self.words = slug_words(slug)
        self.aliases = sorted({norm(a) for a in aliases if norm(a)})
        self.weight = weight

    def __repr__(self):
        return "Person(%s)" % self.slug


def load_config(vault=None):
    """{"self": {slug, ...}, "not_names": {word, ...}, "person_tags": {tag, ...}} from the settings
    note, defaults otherwise."""
    config = {"self": set(), "not_names": set(DEFAULT_NOT_NAMES), "person_tags": set(PERSON_TAGS)}
    try:
        with open(os.path.join(vault or B.VAULT, SETTINGS), encoding="utf-8", errors="replace") as fh:
            meta, _body = B.parse_frontmatter(fh.read())
    except OSError:
        return config
    config["self"] = {slug_of(s) for s in B.as_list(meta.get("self")) if s.strip()}
    config["not_names"] |= {norm(w) for w in B.as_list(meta.get("not_names")) if norm(w)}
    config["person_tags"] |= {t.strip().lower() for t in B.as_list(meta.get("person_tags")) if t.strip()}
    return config


def _weights(con, resolver, paths):
    """{entity path: how many other notes link it}."""
    want = set(paths)
    out = dict.fromkeys(want, 0)
    sources = {}
    for source, target in con.execute("SELECT source, target FROM links"):
        path, _how = resolver.resolve(target)
        if path in want and source != path:
            sources.setdefault(path, set()).add(source)
    for path, srcs in sources.items():
        out[path] = len(srcs)
    return out


def directory(con, resolver=None, tags=None):
    """{slug: Person} for every entity note carrying one of `tags` (the configured person tags)."""
    R = resolver or B.LinkResolver(con)
    wanted = set(tags) if tags is not None else load_config()["person_tags"]
    rows = []
    for path, title, tags in con.execute("SELECT path, title, tags FROM notes WHERE folder = ?", (ENTITIES,)):
        slug = slug_of(path)
        tagset = {t.strip().lower() for t in (tags or "").split(",") if t.strip()}
        if tagset & wanted:
            rows.append((path, title, slug))
    weights = _weights(con, R, [r[0] for r in rows])
    people = {}
    for path, title, slug in rows:
        aliases = []
        for (nid,) in con.execute("SELECT id FROM note_ids WHERE path = ?", (path,)):
            if DATE_PREFIX.match(nid):
                continue
            aliases.append(" ".join(slug_words(nid)) if nid.startswith("entity-") else nid)
        name = re.split(r"\s+[(\u2014-]\s*", str(title or ""), 1)[0].strip() or " ".join(slug_words(slug)).title()
        people[slug] = Person(slug, name, path, aliases, weights.get(path, 0))
    return people


def detect(text, people, config=None, include_self=False):
    """The people a text names, best first. Each entry is (Person, strength, ambiguous).

    strong: two words of the name in order ("dana whitfield") or an alias.
    weak:   the first or the last name alone. A word that names several people returns all of
            them marked ambiguous, the most linked first, unless one carries it five times more
            often than the next. A word some person matches strongly is not also read as
            someone else's first name.
    """
    config = config or load_config()
    words = norm(text).split()
    if not words:
        return []
    padded = " %s " % " ".join(words)
    wordset = set(words)
    not_names = set(config.get("not_names") or ()) | set(B.STOP)
    mine = set(config.get("self") or ())
    strong, weak, strong_words = {}, {}, set()
    for p in people.values():
        if p.slug in mine and not include_self:
            continue
        w, hit = p.words, None
        if len(w) >= 2:
            for later in w[1:]:
                if (" %s %s " % (w[0], later)) in padded:
                    hit = (w[0], later)
                    break
            if not hit and (" %s " % " ".join(w)) in padded:
                hit = tuple(w)
        if not hit:
            for a in p.aliases:
                if (" %s " % a) in padded:
                    hit = tuple(a.split())
                    break
        if hit:
            strong[p.slug] = p
            strong_words.update(hit)
            continue
        for cand in ({w[0], w[-1]} if w else ()):
            if cand in wordset and len(cand) >= 3 and cand not in not_names and not cand.isdigit():
                weak.setdefault(cand, []).append(p)
    out = [(p, "strong", False) for p in sorted(strong.values(), key=lambda p: (-p.weight, p.slug))]
    for word, ps in sorted(weak.items()):
        if word in strong_words:
            continue
        ps = sorted((p for p in ps if p.slug not in strong), key=lambda p: (-p.weight, p.slug))
        if len(ps) > 1 and ps[1].weight * 5 < ps[0].weight:
            ps = ps[:1]
        out.extend((p, "weak", len(ps) > 1) for p in ps)
    seen, uniq = set(), []
    for item in out:
        if item[0].slug not in seen:
            seen.add(item[0].slug)
            uniq.append(item)
    return uniq


def person_words(detected):
    """The prompt words that were read as names, to leave out of the topic."""
    out = set()
    for p, _s, _a in detected:
        out.update(p.words)
        for a in p.aliases:
            out.update(a.split())
    return out


def _linking(con, names, exclude):
    found = set()
    names = sorted(names)
    for i in range(0, len(names), 400):
        chunk = names[i:i + 400]
        for (src,) in con.execute("SELECT DISTINCT source FROM links WHERE target IN (%s)"
                                  % ",".join("?" * len(chunk)), chunk):
            if src != exclude:
                found.add(src)
    return found


def notes_for_person(con, person, resolver=None, limit=400):
    """{note path: how}: `linked` when the note links the person's entity note, `mentioned` when
    the full name only appears in its text. The entity note itself is not listed."""
    R = resolver or B.LinkResolver(con)
    names = R.names_for([person.note]) | {person.slug, person.slug[len("entity-"):]}
    found = {src: "linked" for src in _linking(con, names, person.note)}
    if len(person.words) >= 2:
        phrase = '"%s %s"' % (person.words[0], person.words[-1])
        try:
            for (src,) in con.execute("SELECT path FROM notes_fts WHERE notes_fts MATCH ? LIMIT ?", (phrase, limit)):
                if src != person.note:
                    found.setdefault(src, "mentioned")
        except Exception as e:
            B.log_error("people.notes_for_person", e)
    return found


def notes_for_project(con, path, resolver=None):
    """{note path: how} for a project or area note: `assigned` when a note's `projects:` names it,
    `linked` when a note only links it. The project note itself is not listed."""
    R = resolver or B.LinkResolver(con)
    base = os.path.splitext(os.path.basename(path))[0]
    short = DATE_PREFIX.sub("", base)
    names = R.names_for([path]) | {base, short}
    if short.startswith("project-"):
        names.add(short[len("project-"):])
    found = {}
    for src, projects in con.execute("SELECT path, projects FROM notes WHERE projects != ''"):
        if src != path and {x.strip() for x in (projects or "").split(",")} & names:
            found[src] = "assigned"
    for src in _linking(con, names, path):
        found.setdefault(src, "linked")
    return found


def merge(con, by_person, by_project):
    """One entry per note across every list, keyed by path.

    by_person / by_project: {label: {path: how}}. Returns dicts {path, title, date, people:
    {label: how}, projects: {label: how}}: the notes on BOTH a person's and a project's list
    first, then newest first.
    """
    merged = {}
    for side, groups in (("people", by_person), ("projects", by_project)):
        for label, found in groups.items():
            for path, how in found.items():
                m = merged.setdefault(path, {"path": path, "title": "", "date": "", "people": {}, "projects": {}})
                m[side].setdefault(label, how)
    if merged:
        rows = con.execute("SELECT path, title, updated FROM notes WHERE path IN (%s)"
                           % ",".join("?" * len(merged)), list(merged)).fetchall()
        meta = {p: (t, u) for p, t, u in rows}
        for m in merged.values():
            title, updated = meta.get(m["path"], ("", ""))
            m["title"] = title or os.path.basename(m["path"])
            d = re.match(r"(\d{4}-\d{2}-\d{2})", os.path.basename(m["path"]))
            m["date"] = d.group(1) if d else str(updated or "")[:10]
    return sorted(merged.values(),
                  key=lambda m: (bool(m["people"]) and bool(m["projects"]), m["date"], m["path"]), reverse=True)


def summary(merged):
    """Counts for a merged list: per side, in common, and how many notes to read once."""
    return {"person": sum(1 for m in merged if m["people"]),
            "project": sum(1 for m in merged if m["projects"]),
            "common": sum(1 for m in merged if m["people"] and m["projects"]),
            "unique": len(merged)}


def resolve_note(con, resolver, ref):
    """A project given as a path, a filename or a slug (`garden-planner` finds `project-garden-planner`)."""
    ref = (ref or "").strip()
    if not ref:
        return None
    if os.path.exists(os.path.join(B.VAULT, ref)) and ref.endswith(".md"):
        return ref
    base = os.path.splitext(os.path.basename(ref))[0]
    for name in (base, "project-" + base, "area-" + base):
        path, _how = resolver.resolve(name)
        if path:
            return path
    return None


def context(con, text, projects=(), people_names=(), since="", config=None):
    """The people named in `text` (plus the ones given by name), the project notes given, and
    their notes merged. Returns (detected, project paths, merged)."""
    config = config or load_config()
    R = B.LinkResolver(con)
    folk = directory(con, R, config.get("person_tags"))
    detected = detect(text, folk, config) if text else []
    for name in people_names:
        for item in detect(name, folk, config, include_self=True):
            if item[0].slug not in {d[0].slug for d in detected}:
                detected.append(item)
    by_person = {p.slug: notes_for_person(con, p, R) for p, _s, _a in detected}
    by_project = {}
    for ref in projects:
        path = resolve_note(con, R, ref)
        if path:
            by_project[path] = notes_for_project(con, path, R)
    merged = merge(con, by_person, by_project)
    if since:
        merged = [m for m in merged if m["date"] >= since]
    return detected, list(by_project), merged


def likely_projects(con, text, detected, limit=2):
    """Project and area notes the prompt is about, scored with the names taken out of the terms,
    so "Dana and the garden planner" is scored on "garden planner" alone."""
    import retrieve_core as RC
    skip = person_words(detected)
    rest = " ".join(w for w in norm(text).split() if w not in skip)
    san = B.sanitize_fts(rest)
    if not san:
        return []
    query, terms = san
    projects, areas = [], []
    for _s, path, _t, _e in RC.rank(con, query, None, set(), 12):
        folder = path.split("/")[0]
        if folder in ("10-Projects", "20-Areas") and RC.coverage(con, path, terms) >= RC.THRESHOLD_BASE:
            (projects if folder == "10-Projects" else areas).append(path)
    # An area holds most notes of its people, so it only stands in when no project matches.
    return (projects or areas)[:limit]


PERSON_PREFIX = "· Person: "


def hook_lines(con, prompt, project_paths=(), max_people=2, max_notes=3, config=None):
    """The pointer lines the prompt hook adds when a prompt names someone, [] when it names nobody.

    One line per person (their entity note and how many notes are about them), the command that
    lists everything without repeats right under the first person (so trimming keeps it), then
    the newest notes, the ones shared with a project the prompt is about first and marked.
    """
    try:
        config = config or load_config()
        R = B.LinkResolver(con)
        detected = detect(prompt, directory(con, R, config.get("person_tags")), config)
    except Exception as e:
        B.log_error("people.hook_lines", e)
        return []
    if not detected:
        return []
    detected = [d for d in detected if d[1] == "strong" or not d[2]][:max_people] or detected[:1]
    projects = list(project_paths) or likely_projects(con, prompt, detected)
    by_project = {p: notes_for_project(con, p, R) for p in projects}
    lines = []
    for p, _strength, ambiguous in detected:
        merged = merge(con, {p.slug: notes_for_person(con, p, R)}, by_project)
        mine = [m for m in merged if m["people"]]
        shared = [m for m in mine if m["projects"]]
        head = "%s%s \u2014 `%s` · %d note(s)" % (PERSON_PREFIX, p.name, p.note, len(mine))
        if projects:
            head += ", %d shared with the project" % len(shared)
        if ambiguous:
            head += " · ambiguous name, confirm who"
        lines.append(head)
        for m in (shared + [m for m in mine if not m["projects"]])[:max_notes]:
            lines.append("  %s `%s`%s" % (m["date"], m["path"], " (also the project)" if m["projects"] else ""))
    names = " ".join('--person "%s"' % p.name for p, _s, _a in detected)
    projs = " ".join('--project "%s"' % x for x in projects)
    lines.insert(1, "  all, without repeats: `python3 ~/Brain/_bin/people.py context %s%s`"
                 % (names, (" " + projs) if projs else ""))
    return lines
