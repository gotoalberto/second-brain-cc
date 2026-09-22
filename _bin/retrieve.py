#!/usr/bin/env python3
"""T1 — UserPromptSubmit hook. Injects vault pointers, on a budget.

Principles:
  - A pointer, not context: title + path. The agent reads it if it cares.
  - What gets injected stays in the transcript FOREVER -> per-session budget.
  - A note is injected once per session (dedupe).
  - On any error: silence and exit 0.
"""
import os, re, sys, time, json, hashlib, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B

# Search, relevance and rendering live in retrieve_core, shared with the MCP server's
# `recall` and the `brain recall` CLI so all three render vault notes the same way. This
# file is the Claude Code UserPromptSubmit adapter: session budget, dedupe, threshold
# escalation, pulls and heartbeats.
from retrieve_core import (HARNESS_TAGS, TASK_VERBS, THRESHOLD_BASE, coverage,  # noqa: E402,F401
                           is_harness, is_task, neighbours, rank, render_block)

MAX_TOKENS_PROMPT   = 250     # cap per injection on an ordinary prompt
MAX_TOKENS_TASK     = 460     # cap when the prompt asks to EXECUTE something
MAX_TOKENS_SESSION  = 9000    # cumulative cap per session
TOP_K               = 3       # notes per injection on an ordinary prompt
TOP_K_TASK          = 6       # notes when there is a task ahead
REINJECT_AFTER      = 25      # injections after which a note may repeat

# --- relevance threshold --------------------------------------------------
# BM25 on its own does NOT tell signal from noise: measured, an irrelevant query
# ("check that memory is being consulted") scored 11.6 and a good one (a question
# about where files are stored) scored 3.8. What does separate them is COVERAGE: what fraction of the
# prompt's terms actually appears in the note.
THRESHOLD_STEP     = 0.10        # how much it rises after a search with no matches
THRESHOLD_CEILING  = 0.90        # no higher: it would stop injecting for good
THRESHOLD_MISSES   = 2           # CONSECUTIVE misses before the threshold starts rising

NOVELTY_THRESHOLD   = 0.6     # this similar to the previous prompt means a continuation
REINDEX_EVERY       = 60      # segundos

# A term filter ("only score terms the vault already knows") is DELIBERATELY NOT USED here,
# and `terms_the_vault_knows` must not come back. It cannot tell noise from a subject the
# vault has simply never met, so it silently turns "I don't know about this" into "this
# looks relevant", which is the one failure retrieval must not have: inventing relevance is
# worse than admitting a gap. The threshold above earns its confidence from coverage
# instead. retrieve_core_test.py guards this by looking for this very comment; deleting it
# re-enables nothing, it only removes the alarm.


# The pull itself (throttle, lock, rebase safety) lives in brainlib.maybe_pull, so
# compass.py's forced pull at SessionStart shares the exact same safety logic instead of
# a second copy. Aliased here so every call site in this file keeps saying `maybe_pull()`.
maybe_pull = B.maybe_pull


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
    if B.OFFLINE:
        return                    # the hook probe: nothing detached may outlive its scratch state
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
        "pid=excluded.pid, turns=sessions.turns+1, cwd=excluded.cwd",
        (sid, cwd, B.project_name(cwd), B.current_branch(cwd),
         B.now(), B.now(), B.claude_session_pid()))
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


def already_paths(con, sid):
    return {r[0] for r in con.execute("SELECT path FROM injected WHERE sid=?", (sid,))}


def links_check(con, sid):
    """Every search looks for broken links (a standing rule).

    The classification is cheap and runs here, on every prompt. The repair runs in a
    detached linkfix.py, so a prompt never waits on it. Whatever has no safe fix is told
    to the agent, once per session for each distinct set, so it fixes it by hand.
    """
    try:
        import linkfix as LF
        res = LF.classify(con)
        LF.maybe_spawn(res)
        if not res["broken"]:
            return ""
        sig = hashlib.sha1(json.dumps(res["broken"]).encode()).hexdigest()[:16]
        marker = os.path.join(B.STATE, "%s.links" % sid)
        try:
            if open(marker).read().strip() == sig:
                return ""
        except OSError:
            pass
        B.atomic_write(marker, sig)
        return LF.notice(res)
    except Exception as e:
        B.log_error("retrieve.links_check", e)
        return ""


def bail(con, notice):
    """Every early exit goes through here, so a link notice is never lost on a prompt
    that found no notes."""
    con.close()
    if notice:
        B.emit("UserPromptSubmit", "<vault-notes>\n" + notice + "\n</vault-notes>")
    sys.exit(0)


def search(con, terms, query, project, sid, limit):
    # An already injected note is not repeated... until enough injections have gone
    # by: by then it may well have fallen out of the context window.
    total = con.execute("SELECT COUNT(*) FROM injected WHERE sid=?", (sid,)).fetchone()[0]
    if total >= REINJECT_AFTER:
        con.execute("DELETE FROM injected WHERE sid=? AND ts < ?", (sid, B.now() - 1800))
        con.commit()
    already = set(r[0] for r in con.execute("SELECT path FROM injected WHERE sid=?", (sid,)))
    return rank(con, query, project, already, limit)


@B.heartbeat("prompt-submit")
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

    if is_harness(prompt):
        con = B.db()
        B.metric(con, sid, "skip-harness", latency_ms=(time.time() - t0) * 1000,
                 extra=prompt.lstrip()[1:40].split(">")[0])
        con.close(); sys.exit(0)

    maybe_pull()
    maybe_reindex()
    maybe_beat(sid, cwd)

    san = B.sanitize_fts(prompt)
    con = B.db()
    touch_session(con, sid, cwd)
    link_notice = links_check(con, sid)

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
        bail(con, link_notice)
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
        bail(con, link_notice)
    if misses or session_threshold > THRESHOLD_BASE:
        threshold_save(sid, THRESHOLD_BASE, 0)       # there was a hit: relax all the way
    # Graph expansion: the neighbours of whatever matched come in at the end, marked,
    # so it is visible they arrive by relation and not by coincidence.
    rel = []
    if hits:
        ya = {h[1] for h in hits}
        for path, title in neighbours(con, [h[1] for h in hits[:2]], 3, terms):
            if path not in ya and path not in already_paths(con, sid):
                rel.append(("related", path, title))
    if not hits:
        B.metric(con, sid, "no-hits", latency_ms=(time.time() - t0) * 1000,
                 extra="field=%s%s terms=%s"
                       % (prompt_key, " continuation" if continuation else "",
                          B.scrub_secrets(",".join(terms))[0][:120]))
        bail(con, link_notice)

    first_time = con.execute("SELECT COUNT(*) FROM injected WHERE sid=?", (sid,)).fetchone()[0] == 0
    block, kept = render_block(hits, rel, cap, pointer_only, link_notice, first_time)

    tokens = B.est_tokens(block)
    for _, path, _, _ in hits[:kept]:
        con.execute("INSERT OR IGNORE INTO injected VALUES(?,?,?)", (sid, path, B.now()))
    con.execute("UPDATE sessions SET tokens = tokens + ? WHERE sid=?", (tokens, sid))
    B.metric(con, sid, "inject", tokens=tokens, hits=len(hits),
             latency_ms=(time.time() - t0) * 1000,
             extra="pointer_only=%d campo=%s" % (int(pointer_only), prompt_key))
    con.commit(); con.close()
    B.emit("UserPromptSubmit", block)


if __name__ == "__main__":
    main()
