#!/usr/bin/env python3
"""T1 — UserPromptSubmit hook. Injects vault pointers, on a budget.

Principles:
  - A pointer, not context: title + path. The agent reads it if it cares.
  - What gets injected stays in the transcript FOREVER -> per-session budget.
  - A note is injected once per session (dedupe).
  - On any error: silence and exit 0.
"""
import os, re, sys, time, json, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B

MAX_TOKENS_PROMPT   = 250     # cap per injection on an ordinary prompt
MAX_TOKENS_TASK     = 460     # cap when the prompt asks to EXECUTE something
MAX_TOKENS_SESSION  = 9000    # cumulative cap per session
TOP_K               = 3       # notes per injection on an ordinary prompt
TOP_K_TASK          = 6       # notes when there is a task ahead
REINJECT_AFTER      = 25      # injections after which a note may repeat

# --- relevance threshold --------------------------------------------------
# BM25 on its own does NOT tell signal from noise: measured, an irrelevant query
# ("check that memory is being consulted") scored 11.6 and a good one ("how are files
# stored in s3") scored 3.8. What does separate them is COVERAGE: what fraction of the
# prompt's terms actually appears in the note.
THRESHOLD_BASE     = 0.60        # minimum coverage to inject
THRESHOLD_STEP     = 0.10        # how much it rises after a search with no matches
THRESHOLD_CEILING  = 0.90        # no higher: it would stop injecting for good
THRESHOLD_MISSES   = 2           # CONSECUTIVE misses before the threshold starts rising

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
NOVELTY_THRESHOLD   = 0.6     # this similar to the previous prompt means a continuation
REINDEX_EVERY       = 60      # segundos


PULL_EVERY = 300               # seconds between vault pulls
PULL_TIMEOUT = 8              # a prompt never blocks longer than this on the network


def _rebase_in_progress():
    """Two stats: cheap enough to ask on the prompt path without being felt.

    It repeats vault_sync's check on purpose instead of importing it: this hook runs on
    EVERY prompt and its budget is tens of milliseconds, whereas importing vault_sync
    would drag the whole of index_vault along with it.
    """
    g = os.path.join(B.VAULT, ".git")
    return os.path.isdir(os.path.join(g, "rebase-merge")) or\
           os.path.isdir(os.path.join(g, "rebase-apply"))


def maybe_pull():
    """Fetch the vault before answering, if it has been a while since the last pull.

    It exists because the vault may have changed from another machine or another
    session: answering with stale memory is worse than taking a second longer. It uses
    the SAME flock as vault_sync, the only process allowed to touch git, and if it does
    not get the lock or the network is slow it gives up silently: the user's prompt never
    waits on the network.
    """
    marker = os.path.join(B.STATE, "last_pull")
    try:
        if time.time() - os.path.getmtime(marker) < PULL_EVERY:
            return
    except OSError:
        pass
    try:
        with B.flock(os.path.join(B.VAULT, "_index", ".gitlock"), timeout=1) as lk:
            if not lk.held:
                return
            # If a rebase was ALREADY under way on arrival, it is not ours: most likely
            # the user is resolving a conflict by hand in ~/Brain. Aborting it would wipe
            # the resolution work already done, and this runs on EVERY prompt. Leave
            # without touching anything.
            if _rebase_in_progress():
                B.log("sync", "pull-skipped-foreign-rebase")
                return
            _, head_before, _ = B.run([B.GIT, "rev-parse", "HEAD"], cwd=B.VAULT)
            code, _, err = B.run([B.GIT, "pull", "--rebase", "--autostash", "--quiet"],
                                 cwd=B.VAULT, timeout=PULL_TIMEOUT)
            # Whatever the pull rewrote now has mtime = now. Marked so the memory gate
            # cannot read someone else's commit as this session having saved.
            if code == 0 and head_before.strip():
                rc2, changed, _ = B.run([B.GIT, "diff", "--name-only",
                                         head_before.strip(), "HEAD"], cwd=B.VAULT)
                if rc2 == 0 and changed.strip():
                    B.mark_git_touched(changed.splitlines())
            # The result canNOT be ignored. A failed pull — a conflict, or the 8 s
            # timeout cutting the rebase mid-apply — leaves a half-finished
            # .git/rebase-merge, and from there everything vault_sync commits lands on a
            # detached HEAD: the vault stops converging and nobody notices. It is aborted
            # exactly as fetch_from_remote() does, here and now, with the lock still in
            # hand; a local operation, adding no network and no wait to the prompt.
            # This one IS ours: there was no rebase on entry and this pull left it.
            if code != 0 and _rebase_in_progress():
                B.run([B.GIT, "rebase", "--abort"], cwd=B.VAULT, timeout=5)
                B.log("sync", "pull-hook-rebase-abortado", err=(err or "")[:200])
        os.makedirs(B.STATE, exist_ok=True)
        open(marker, "w").close()
    except Exception as e:
        B.log_error("retrieve.maybe_pull", e)


def maybe_beat(sid, cwd):
    """The presence heartbeat is renewed because the user is working.

    This is the real engine: without it, presence would only be written at session start
    and would expire with the user sitting right there. It is throttled by the cache file
    `presence.py` leaves behind, and always DETACHED: zero network on the prompt's path.
    """
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import presence as P
        if P.should_beat():
            project = B.project_name(cwd)
            B.presence_beat_async(sid, project)
            # The lease is renewed for the same reason and with the same throttle:
            # because the user is working. A lease renewed by a timer alone would be
            # immortal even with nobody behind it.
            B.lease_acquire_async(B.project_note(project), sid)
    except Exception as e:
        B.log_error("retrieve.maybe_beat", e)


def maybe_reindex():
    """Reindexes in the background if it has been a while; never blocks the prompt."""
    stamp = os.path.join(B.VAULT, "_index", ".last-index")
    try:
        age = time.time() - os.path.getmtime(stamp)
    except Exception:
        age = 1e9
    if age < REINDEX_EVERY:
        return
    try:
        open(stamp, "w").write(str(time.time()))
        subprocess.Popen(["/usr/bin/python3",
                          os.path.join(B.VAULT, "_bin", "index_vault.py")],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except Exception:
        pass


def touch_session(con, sid, cwd):
    con.execute(
        "INSERT INTO sessions(sid,cwd,project,branch,started,heartbeat,pid,turns) "
        "VALUES(?,?,?,?,?,?,?,1) "
        "ON CONFLICT(sid) DO UPDATE SET heartbeat=excluded.heartbeat, "
        "turns=sessions.turns+1, cwd=excluded.cwd",
        (sid, cwd, B.project_name(cwd), B.current_branch(cwd),
         B.now(), B.now(), 0))
    con.commit()


def threshold_path(sid):
    return os.path.join(B.STATE, "%s.threshold" % sid)


def threshold_state(sid):
    """(threshold, consecutive misses) for this session."""
    try:
        u, f = open(threshold_path(sid)).read().split()
        return min(THRESHOLD_CEILING, max(THRESHOLD_BASE, float(u))), int(f)
    except Exception:
        return THRESHOLD_BASE, 0


def threshold_save(sid, value, misses):
    try:
        os.makedirs(B.STATE, exist_ok=True)
        B.atomic_write(threshold_path(sid), "%.2f %d" % (value, misses))
    except Exception as e:
        B.log_error("retrieve.threshold_save", e)


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


def already_paths(con, sid):
    return {r[0] for r in con.execute("SELECT path FROM injected WHERE sid=?", (sid,))}


def is_task(prompt):
    """Is the prompt asking to execute something, or only asking a question?"""
    p = " " + prompt.lower()
    return any((" " + v) in p for v in TASK_VERBS)


def neighbours(con, paths, limit=4):
    """Notes linked from (or to) the ones already surfaced.

    This is what turns [[wikilinks]] into real retrieval: if the note that matches
    points at another, that other one is almost always needed too, even when it shares
    not a single word with the prompt.
    """
    if not paths:
        return []
    slugs = []
    for p in paths:
        slug = os.path.splitext(os.path.basename(p))[0]
        slugs.append(slug)
    markers = ",".join("?" * len(slugs))
    outside = ",".join("?" * len(paths))
    # No string formatting over the SQL: LIKE's '%' clashes with %s.
    sql = ("SELECT DISTINCT n.path, n.title FROM links l "
           "JOIN notes n ON (n.path LIKE '%' || l.target || '.md' OR n.path = l.source) "
           "WHERE (l.source IN (" + outside + ") OR l.target IN (" + markers + ")) "
           "  AND n.retrievable = 1 AND n.path NOT IN (" + outside + ") LIMIT ?")
    try:
        return con.execute(sql, list(paths) + slugs + list(paths) + [limit]).fetchall()
    except Exception as e:
        B.log_error("retrieve.neighbours", e)
        return []


def search(con, terms, query, project, sid, limit):
    # An already injected note is not repeated... until enough injections have gone
    # by: by then it may well have fallen out of the context window.
    total = con.execute("SELECT COUNT(*) FROM injected WHERE sid=?", (sid,)).fetchone()[0]
    if total >= REINJECT_AFTER:
        con.execute("DELETE FROM injected WHERE sid=? AND ts < ?", (sid, B.now() - 1800))
        con.commit()
    already = set(r[0] for r in con.execute("SELECT path FROM injected WHERE sid=?", (sid,)))
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


@B.fail_open
def main():
    t0 = time.time()
    data = B.read_hook_input()
    # The field name has varied across Claude Code versions; we accept every known
    # alias instead of trusting a single one.
    prompt, prompt_key = "", ""
    for key in ("user_message", "prompt", "user_prompt", "message", "input", "text"):
        v = data.get(key)
        if isinstance(v, str) and v.strip():
            prompt, prompt_key = v, key
            break
    sid = B.sid8(data.get("session_id"))
    cwd = data.get("cwd") or os.getcwd()

    maybe_pull()
    maybe_reindex()
    maybe_beat(sid, cwd)

    san = B.sanitize_fts(prompt)
    con = B.db()
    touch_session(con, sid, cwd)

    # "do it", "go on", "ok": there is nothing in them to search for, but they mean
    # "execute what we were discussing". The previous prompt's terms are inherited,
    # which is exactly the context needed to carry it out.
    inherited = False
    if not san:
        row = con.execute("SELECT terms FROM lastprompt WHERE sid=?", (sid,)).fetchone()
        anteriores = json.loads(row[0]) if row and row[0] else []
        if anteriores and is_task(prompt):
            san = (" OR ".join('"%s"' % w for w in anteriores), anteriores)
            inherited = True

    if not san:                                   # trivial prompt, or no text at all
        # If no text arrived, record which fields DID: it is the only way to detect a
        # schema change instead of suffering it in silence.
        extra = "" if prompt else "no-text keys=%s" % ",".join(sorted(data.keys()))[:180]
        B.metric(con, sid, "skip-trivial", latency_ms=(time.time() - t0) * 1000, extra=extra)
        con.close(); sys.exit(0)
    query, terms = san

    # a continuation of the previous prompt? then there is no new topic to retrieve
    row = con.execute("SELECT terms FROM lastprompt WHERE sid=?", (sid,)).fetchone()
    prev = json.loads(row[0]) if row and row[0] else []
    if not inherited:      # a "do it" does not redefine the topic: it inherits it
        con.execute("INSERT INTO lastprompt VALUES(?,?,?) ON CONFLICT(sid) DO UPDATE "
                    "SET terms=excluded.terms, ts=excluded.ts",
                    (sid, json.dumps(terms), B.now()))
    con.commit()
    # A continuation is NOT skipped: it searches all the same and only stays quiet if
    # nothing new turns up. Skipping the search left 17% of prompts unconsulted
    # memory, and those are exactly the mid-conversation messages, where the topic
    # drifts step by step and ends far from where it started.
    continuation = bool(prev) and B.jaccard(terms, prev) > NOVELTY_THRESHOLD

    spent = con.execute("SELECT tokens FROM sessions WHERE sid=?", (sid,)).fetchone()
    spent = spent[0] if spent else 0
    pointer_only = spent >= MAX_TOKENS_SESSION

    project = B.project_name(cwd)
    is_task_prompt = is_task(prompt)
    if continuation and not is_task_prompt:
        top_k, cap = 2, 140          # only what has not been said already
    else:
        top_k = TOP_K_TASK if is_task_prompt else TOP_K
        cap = MAX_TOKENS_TASK if is_task_prompt else MAX_TOKENS_PROMPT
    hits = search(con, terms, query, project, sid, top_k)

    # Relevance filter: out goes anything not covering enough of the prompt's terms.
    # On a continuation or an inherited "hazlo" the BASE threshold is ALWAYS used and it
    # never escalates: the best notes on that topic were already injected, so what is
    # left scores lower by construction. Penalising it there raised the bar and muted the
    # rest of the conversation, which is the opposite of the point.
    recycled = inherited or continuation
    session_threshold, misses = threshold_state(sid)
    threshold = THRESHOLD_BASE if recycled else session_threshold
    measured = [(coverage(con, h[1], terms), h) for h in hits]
    hits = [h for cob, h in measured if cob >= threshold]
    best = max([c for c, _ in measured], default=0.0)
    if not hits:
        # Nothing clears the bar: the vault does not cover this topic. The threshold
        # rises so the session stops trying and stops adding noise. Only on prompts
        # new ones: an already injected topic is no proof of missing coverage.
        if not recycled:
            # A single miss is not evidence: it may be a passing question. It only
            # rises after several in a row, which is when the vault really does not
            # covers the conversation. Before, one isolated miss killed the next query
            # siguiente aunque fuera buena.
            misses += 1
            new_one = threshold + THRESHOLD_STEP if misses >= THRESHOLD_MISSES else threshold
            threshold_save(sid, min(THRESHOLD_CEILING, new_one), misses)
        # The TERMS, not just the score. A miss recorded only as `best=0.17` says the
        # system failed and never what it was looking for, so the gaps could only be
        # guessed at. With the terms, the held-out set can be built from the user's real
        # questions instead of invented ones — and an invented set is spent the moment
        # its results are known.
        B.metric(con, sid, "below-threshold", latency_ms=(time.time() - t0) * 1000,
                 extra="best=%.2f threshold=%.2f terms=%s"
                       % (best, threshold, B.scrub_secrets(",".join(terms))[0][:120]))
        con.close(); sys.exit(0)
    if misses or session_threshold > THRESHOLD_BASE:
        threshold_save(sid, THRESHOLD_BASE, 0)       # there was a hit: relax all the way
    # Graph expansion: the neighbours of whatever matched come in at the end, marked,
    # so it is visible they arrive by relation and not by coincidence.
    rel = []
    if hits:
        ya = {h[1] for h in hits}
        for path, title in neighbours(con, [h[1] for h in hits[:2]], 3):
            if path not in ya and path not in already_paths(con, sid):
                rel.append(("related", path, title))
    if not hits:
        B.metric(con, sid, "no-hits", latency_ms=(time.time() - t0) * 1000,
                 extra="field=%s%s terms=%s"
                       % (prompt_key, " continuation" if continuation else "",
                          B.scrub_secrets(",".join(terms))[0][:120]))
        con.close(); sys.exit(0)

    first_time = con.execute("SELECT COUNT(*) FROM injected WHERE sid=?", (sid,)).fetchone()[0] == 0
    lines = []
    for i, (score, path, title, excerpt) in enumerate(hits):
        lines.append("· %s — `%s`" % (title, path))
        if i == 0 and not pointer_only and excerpt and score > 3.0:
            lines.append("  %s" % excerpt[:160])
    for _, path, title in rel:
        lines.append("· %s — `%s`  (related)" % (title, path))
    body = "\n".join(lines) + "\nRead them with Read only if they are relevant."

    if first_time:
        block = B.wrap_untrusted(body)
    else:
        block = "<vault-notes>\n" + body + "\n</vault-notes>"

    # hard cap per injection
    while B.est_tokens(block) > cap and len(lines) > 1:
        lines.pop()
        body = "\n".join(lines) + "\nRead them with Read only if they are relevant."
        block = (B.wrap_untrusted(body) if first_time
                 else "<vault-notes>\n" + body + "\n</vault-notes>")

    tokens = B.est_tokens(block)
    for _, path, _, _ in hits[:len(lines)]:
        con.execute("INSERT OR IGNORE INTO injected VALUES(?,?,?)", (sid, path, B.now()))
    con.execute("UPDATE sessions SET tokens = tokens + ? WHERE sid=?", (tokens, sid))
    B.metric(con, sid, "inject", tokens=tokens, hits=len(hits),
             latency_ms=(time.time() - t0) * 1000,
             extra="pointer_only=%d campo=%s" % (int(pointer_only), prompt_key))
    con.commit(); con.close()
    B.emit("UserPromptSubmit", block)


if __name__ == "__main__":
    main()
