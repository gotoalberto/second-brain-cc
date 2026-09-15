#!/usr/bin/env python3
"""Vault search, relevance and rendering, with no session state.

retrieve.py (the Claude Code UserPromptSubmit hook), the MCP server's `recall` tool and
the `brain recall` CLI render vault notes through this module, so they cannot drift. What
stays in retrieve.py is what only a hook needs: per-session budget, dedupe of notes already
injected, threshold escalation after misses, the vault pull and the presence heartbeat.

The functions below were moved verbatim from retrieve.py; `rank`, `render_block` and
`search_and_render` wrap code that already lived there.
"""
import re
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B  # noqa: E402

THRESHOLD_BASE     = 0.60        # minimum coverage to inject
MAX_TOKENS_RENDER  = 460         # the hook's cap for a task prompt; the stateless default
TOP_K_RENDER       = 3

# A prompt asking to execute something needs more context than one that asks a question.
# The signal is the verb: if one of these shows up, the budget opens.
#
# The SPANISH verbs stay, and that is deliberate. Everything else got translated, but
# this list is not read against the vault — it is read against what the USER types, and
# the user types Spanish. Translating it would quietly switch off task detection, which
# is the same class of failure as renaming a marker that old data still carries.
TASK_VERBS = (
    "haz", "crea", "monta", "implementa", "arregla", "corrige", "cambia", "añade",
    "actualiza", "escribe", "genera", "revisa", "audita", "migra", "despliega",
    "refactoriza", "documenta", "prepara", "construye", "sube", "borra", "elimina",
    "configura", "instala", "integra", "optimiza", "traduce", "reestructura",
    # acknowledgements that really mean "execute what we just discussed"
    "hazlo", "sigue", "continua", "continúa", "adelante", "dale", "venga",
    # and the English ones, for when the prompt comes in English
    "do", "make", "build", "implement", "fix", "change", "add", "update", "write",
    "generate", "review", "audit", "migrate", "deploy", "refactor", "document",
    "prepare", "upload", "delete", "remove", "configure", "install", "integrate",
    "optimise", "optimize", "translate", "restructure", "continue", "carry", "go",
)

# DELIBERATELY NOT USED — do not wire this in. Kept as a record of a fix that looks
# right and is not.
#
# The idea: drop prompt terms that appear in NO note, so untranslated Spanish stops
# inflating the coverage denominator. It measures well on Spanish prompts about topics
# the vault covers. It is still wrong, because a term with zero postings has two
# meanings that need OPPOSITE treatment:
#
#   - a Spanish word with no bridge  -> noise, should be dropped
#   - the SUBJECT of a prompt about something the vault has never heard of -> the whole
#     point of staying quiet, must NOT be dropped
#
# Measured on seven prompts about topics genuinely outside this vault, the gated version
# raised false injections from 1/7 to 4/7. "how do we handle kubernetes ingress rate
# limiting in staging" loses `kubernetes`, `ingress` and `limiting` — its entire subject —
# and coverage climbs 0.43 -> 0.75, so it injects notes matched on `handle`, `rate` and
# `staging`. A retrieval system that invents relevance for what it does not know is worse
# than one that says nothing.
#
# The real fix for untranslated Spanish is GLOSSARY COVERAGE, which is measurable and has
# no such failure mode: see 30-Knowledge/2026-08-27-decision-bilingual-retrieval-measured-not-assumed.md
# and `_bin/bilingual_eval.py`.


def coverage(con, path, terms):
    """Fraction of the prompt's terms that appear in the note."""
    if not terms:
        return 0.0
    r = con.execute("SELECT title, body FROM notes_fts WHERE path=?", (path,)).fetchone()
    if not r:
        return 0.0
    txt = (" ".join(x or "" for x in r)).lower()
    # Whole word, not substring: with `t in txt`, the term "mar" matched "marca" and
    # "marcado", and 65 of 153 notes counted a prompt about the sea as covered. Coverage
    # came out inflated and the filter filtered nothing.
    # A term may carry several surface forms for ONE concept (see the glossary note in
    # `sanitize_fts`): covered if ANY of them appears, and counted once either way.
    #
    # A BOUNDED inflection suffix is allowed, so `store` counts a note that says `stored`
    # and `machine` counts `machines`. This is not the substring matching the comment
    # above rules out: `mar` still cannot match `marca`, because `ca` is not in the set.
    # Without it, coverage under-counted real matches in both languages and the threshold
    # filtered out notes that were genuinely about the question.
    #
    # The residual risk is a 4+ letter stem that is a prefix of a longer word differing by
    # exactly one allowed suffix (`stor` would count `stored`). Accepted: query terms come
    # from the glossary or the user's own words, and none of them are truncated stems.
    def present(term):
        for p in term.split():
            if len(p) < 4:
                pat = r"(?<![0-9a-zà-ÿ])%s(?![0-9a-zà-ÿ])" % re.escape(p)
            else:
                pat = (r"(?<![0-9a-zà-ÿ])%s(?:s|es|d|ed|ing|er|ers)?(?![0-9a-zà-ÿ])"
                       % re.escape(p))
            if re.search(pat, txt):
                return True
        return False
    return sum(1 for t in terms if present(t)) / float(len(terms))


def is_task(prompt):
    """Is the prompt asking to execute something, or only asking a question?"""
    p = " " + prompt.lower()
    return any((" " + v) in p for v in TASK_VERBS)


def neighbours(con, paths, limit=4, terms=None):
    """Notes linked from (or to) the ones already surfaced.

    This is what turns [[wikilinks]] into real retrieval: if the note that matches
    points at another, that other one is almost always needed too, even when it shares
    not a single word with the prompt.

    Resolved with brainlib.LinkResolver, the same resolver as everything else. The old
    `LIKE '%' || target || '.md'` sent `[[api]]` to an unrelated runbook, never
    followed a link by id, and missed backlinks written with a dateless slug.

    Ranked by how tied the note is (see `tie` below), then by how much of the PROMPT it
    covers, then decisions first, as search() does. Before, it was the first N rows SQLite returned; ranking by recency instead
    was tried and measured worse (bilingual_eval): for "how are credentials managed" it
    picked a homebridge diagnosis over the KeePass decision, both one link away.
    """
    if not paths:
        return []
    try:
        R = B.LinkResolver(con)
        want = set(paths)
        # Per (hit, candidate) pair the strongest tie counts ONCE: 2 if the hit links to
        # it, 1 if it only links back. Summed across different hits. A mutual link is not
        # more relevance: the homelab notes all link each other, and counting both
        # directions let that cluster crowd out the KeePass decision on a credentials
        # question.
        tie = {}
        for p in paths:
            for (tgt,) in con.execute("SELECT target FROM links WHERE source = ?", (p,)):
                c, _how = R.resolve(tgt)
                if c and c not in want:
                    tie[(p, c)] = 2
            names = sorted(R.names_for([p]))
            for i in range(0, len(names), 400):
                chunk = names[i:i + 400]
                for (src,) in con.execute(
                        "SELECT DISTINCT source FROM links WHERE target IN (%s)"
                        % ",".join("?" * len(chunk)), chunk):
                    if src not in want:
                        tie[(p, src)] = max(tie.get((p, src), 0), 1)
        score = {}
        for (_p, c), w in tie.items():
            score[c] = score.get(c, 0) + w
        if not score:
            return []
        cand = list(score)
        rows = con.execute("SELECT path, title, updated, ntype FROM notes WHERE retrievable = 1 "
                           "AND path IN (%s)" % ",".join("?" * len(cand)), cand).fetchall()
        cov = {r[0]: (coverage(con, r[0], terms) if terms else 0.0) for r in rows}
        rows.sort(key=lambda r: (score[r[0]], cov[r[0]], r[3] == "decision",
                                 str(r[2] or "")), reverse=True)
        return [(p, t) for p, t, _u, _n in rows[:limit]]
    except Exception as e:
        B.log_error("retrieve.neighbours", e)
        return []


# Messages the harness injects as if the user typed them. They are not questions: a
# `<task-notification>` carries ids, paths and tool-use ids, and searching the vault with
# them only produced misses (task-notification, tool-use-id and claude-501 were the three
# most missed terms of the whole log, 450, 358 and 317 times).
HARNESS_TAGS = ("task-notification", "cross-session-message", "system-reminder",
                "local-command-stdout", "local-command-caveat", "command-name",
                "command-message", "ci-monitor-event", "bash-notification")


def is_harness(prompt):
    p = prompt.lstrip()
    return p.startswith("<") and any(p.startswith("<" + t) for t in HARNESS_TAGS)



def rank(con, query, project, exclude, limit):
    """The best notes for an FTS query, scored as retrieve.py always scored them.

    BM25, plus the current project, plus decisions; minus low confidence and old notes.
    `exclude` holds paths not to return (the hook passes what this session already saw).
    """
    already = set(exclude or ())
    rows = []
    try:
        cur = con.execute(
            "SELECT f.path, bm25(notes_fts) AS score, n.title, n.excerpt, n.ntype, "
            "       n.projects, n.updated, n.confidence "
            "FROM notes_fts f JOIN notes n ON n.path = f.path "
            "WHERE notes_fts MATCH ? AND n.retrievable = 1 "
            "ORDER BY score LIMIT 40", (query,))
        rows = cur.fetchall()
    except Exception:
        return []
    scored = []
    for path, score, title, excerpt, ntype, projects, updated, confidence in rows:
        if path in already:
            continue
        s = -float(score)                       # bm25: lower is better
        if project and project in (projects or ""):
            s += 2.0
        if ntype == "decision":
            s += 1.0
        if confidence == "low":
            s -= 1.0
        try:
            year = int(str(updated)[:4])
            if year and year < time.localtime().tm_year - 1:
                s -= 0.5
        except Exception:
            pass
        scored.append((s, path, title, excerpt))
    scored.sort(reverse=True)
    return scored[:limit]


def render_block(hits, related, cap, pointer_only, link_notice, first_time):
    """The injected text, trimmed to `cap` estimated tokens. Returns (block, lines kept).

    A pointer per note (title and path), the first note's excerpt unless in pointer-only
    mode, related notes marked, and the untrusted-data wrapper on a session's first
    injection. Lines are dropped from the end until the block fits, keeping at least one.
    """
    lines = []
    for i, (score, path, title, excerpt) in enumerate(hits):
        lines.append("· %s — `%s`" % (title, path))
        if i == 0 and not pointer_only and excerpt and score > 3.0:
            lines.append("  %s" % excerpt[:160])
    for _, path, title in related:
        lines.append("· %s — `%s`  (related)" % (title, path))

    def build():
        body = "\n".join(lines) + "\nRead them with Read only if they are relevant."
        if link_notice:
            body += "\n" + link_notice
        return B.wrap_untrusted(body) if first_time else "<vault-notes>\n" + body + "\n</vault-notes>"

    block = build()
    # hard cap per injection
    while B.est_tokens(block) > cap and len(lines) > 1:
        lines.pop()
        block = build()
    return block, len(lines)


def search_and_render(con, prompt, top_n=TOP_K_RENDER, project=None, cap=MAX_TOKENS_RENDER):
    """Stateless retrieval: what the hook would inject for `prompt` in a fresh session.

    "" when the prompt has nothing to search for or nothing clears the relevance bar —
    silence, not noise, for topics the vault does not cover.
    """
    san = B.sanitize_fts(prompt or "")
    if not san:
        return ""
    query, terms = san
    hits = [h for h in rank(con, query, project, set(), top_n) if coverage(con, h[1], terms) >= THRESHOLD_BASE]
    if not hits:
        return ""
    seen = {h[1] for h in hits}
    related = [("related", path, title) for path, title in neighbours(con, [h[1] for h in hits[:2]], 3, terms)
               if path not in seen]
    block, _ = render_block(hits, related, cap, False, "", True)
    return block
