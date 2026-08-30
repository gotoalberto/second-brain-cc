#!/usr/bin/env python3
"""Health report for the Brain system."""
import os, sys, time, subprocess, glob, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B

PY3 = "/usr/bin/python3"


def section(t):
    print("\n== %s ==" % t)


def main():
    if not B.enabled():
        print("VAULT UNAVAILABLE at %s (or BRAIN_OFF set)" % B.VAULT); return 0
    con = B.db()

    section("Vault")
    total = con.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
    print("path: %s   notes indexed: %d" % (B.VAULT, total))
    for folder, n in con.execute("SELECT folder, COUNT(*) FROM notes GROUP BY folder ORDER BY 2 DESC"):
        print("  %-18s %d" % (folder, n))
    types = ", ".join("%s:%d" % (t or "-", n) for t, n in
                      con.execute("SELECT ntype, COUNT(*) FROM notes GROUP BY ntype ORDER BY 2 DESC"))
    print("types: %s" % types)

    section("Retrieval (T1) — helping or getting in the way?")
    since = B.now() - 7 * 86400
    ev = collections.Counter()
    toks, lat, n_inj, cont = 0, [], 0, 0
    for event, tokens, ms, extra in con.execute(
            "SELECT event, tokens, latency_ms, extra FROM metrics WHERE ts > ?", (since,)):
        ev[event] += 1
        if event == "inject":
            toks += tokens or 0; n_inj += 1
        if ms:
            lat.append(ms)
        # A continuation stopped being its own event when the design changed: it is no
        # longer skipped, it searches anyway and only stays quiet if it finds nothing
        # new. Counting the old `skip-continuation` bucket alone reported a frozen
        # historical number and left today's continuations out of the denominator.
        if extra and ("continuation" in extra or "continuacion" in extra):
            cont += 1
    # `below-threshold` is a TERMINAL path of retrieve.main(), like the other four: the
    # prompt was searched and nothing cleared the coverage bar. Leaving it out of the
    # denominator made the injection rate flatter the better the noise filter worked —
    # it read 45% when the real figure was 17%. The comment two blocks down records
    # fixing this exact mistake for the continuation bucket; the largest one stayed out.
    below = ev.get("below-threshold", 0) + ev.get("bajo-umbral", 0)   # old name, kept for history
    prompts = (ev["inject"] + ev["skip-trivial"] + ev["skip-continuation"]
               + ev["no-hits"] + below)
    if prompts:
        print("last 7 days: %d prompts processed" % prompts)
        print("  injected context       %4d  (%.0f%%)" % (ev["inject"], 100.0 * ev["inject"] / prompts))
        print("  no results             %4d" % ev["no-hits"])
        print("  trivial prompt         %4d" % ev["skip-trivial"])
        print("  continuation of prior  %4d  (%d skipped outright, older design)"
              % (cont + ev["skip-continuation"], ev["skip-continuation"]))
        print("  tokens injected: %d  (mean %.0f per injection)"
              % (toks, toks / n_inj if n_inj else 0))
        if lat:
            lat.sort()
            print("  latency: median %.0f ms, p95 %.0f ms"
                  % (lat[len(lat) // 2], lat[int(len(lat) * 0.95)]))
    else:
        print("no data yet (the system has not seen real prompts)")

    if prompts or below:
        print("  below relevance threshold %4d  (searched, not injected: noise)" % below)

    section("Note hygiene")
    # An index row can point at a note no longer on disk (a
    # temporarily deleted, a file moved by hand). That used to blow doctor up with
    # a FileNotFoundError — precisely the tool one runs when something is wrong.
    orphans, ghosts = [], []
    for (rel,) in con.execute("SELECT path FROM notes WHERE retrievable=1"):
        try:
            text = open(os.path.join(B.VAULT, rel), errors="replace").read()
        except OSError:
            ghosts.append(rel)
            continue
        if "[[" not in text:
            orphans.append(rel)
    if ghosts:
        print("IN THE INDEX BUT NOT ON DISK: %d  (run index_vault.py)" % len(ghosts))
        for f in ghosts[:5]:
            print("  - %s" % f)
    print("retrievable notes with no links: %d" % len(orphans))
    for p in orphans[:5]:
        print("  - %s" % p)
    dupes = con.execute("SELECT title, COUNT(*) c FROM notes GROUP BY lower(title) "
                        "HAVING c > 1").fetchall()
    print("duplicate titles: %d %s" % (len(dupes), [d[0] for d in dupes[:3]] if dupes else ""))
    old = con.execute("SELECT COUNT(*) FROM notes WHERE retrievable=1 AND updated < ?",
                      (time.strftime("%Y-%m-%d", time.localtime(B.now() - 180 * 86400)),)).fetchone()[0]
    print("retrievable notes untouched for 6 months: %d" % old)
    lowconf = con.execute("SELECT COUNT(*) FROM notes WHERE confidence='low'").fetchone()[0]
    print("notes with confidence: low: %d" % lowconf)
    packs = glob.glob(os.path.join(B.VAULT, "60-Context-Packs", "*.md"))
    print("context packs on disk: %d" % len(packs))

    section("Bridge from Spanish into an English vault")
    # The glossary is a hand-maintained list, which is the shape that has already bitten
    # this project twice. Drift is invisible by construction: a new domain word simply
    # has no Spanish entry, and questions about it go quiet with no error. This turns
    # that drift into a number.
    try:
        import re as _re, collections as _c
        freq = _c.Counter()
        for t, b in con.execute("SELECT title, body FROM notes_fts"):
            for w in _re.findall(r"[a-z]{4,}", ((t or "") + " " + (b or "")).lower()):
                freq[w] += 1
        reach = set()
        for v in B.GLOSARIO.values():
            reach.update(v.split())
        EN_STOP = set("""this that with from they have been were will would could should
        about which their there where when what your into more than then them these those
        over under after before only just also some very much many most other another
        such each both same because while during through against between within without
        upon does doesn here itself back goes still left next first three whole nothing
        already never every real""".split())
        top = [(w, n) for w, n in freq.most_common(300)
               if w not in EN_STOP and n >= 20]
        # Inflection-tolerant, the same way `retrieve.coverage()` is: `files` is reached
        # by the bridge to `file`. Counting them as gaps would overstate the problem, and
        # an instrument that overstates gets ignored just as fast as one that flatters.
        def reached(w):
            if w in reach:
                return True
            for suf in ("s", "es", "d", "ed", "ing", "er", "ers"):
                if w.endswith(suf) and len(w) - len(suf) >= 4 and w[:-len(suf)] in reach:
                    return True
            return False
        missing = [(w, n) for w, n in top if not reached(w)]
        print("glossary: %d Spanish entries -> %d English terms" % (len(B.GLOSARIO), len(reach)))
        print("vault vocabulary (used 20+ times): %d terms, %d with no Spanish bridge"
              % (len(top), len(missing)))
        if missing:
            print("  most-used words a Spanish question cannot reach:")
            print("    " + ", ".join("%s(%d)" % (w, n) for w, n in missing[:14]))
            print("  -> many are proper nouns and need no bridge; check with:")
            print("     python3 %s/_bin/bilingual_eval.py --held-out" % B.VAULT)
    except Exception as exc:
        print("could not compute: %r" % exc)

    section("Sessions and claims")
    live = 0
    for sid, proj, hb, pid, turns in con.execute(
            "SELECT sid, project, heartbeat, pid, turns FROM sessions ORDER BY heartbeat DESC"):
        alive = B.session_alive(hb)
        live += 1 if alive else 0
        print("  %s %s  project=%s  turns=%s  %.0f min ago"
              % ("LIVE  " if alive else "dead  ", sid, proj or "?", turns,
                 (B.now() - (hb or 0)) / 60))
    print("claims recorded: %d" % con.execute("SELECT COUNT(*) FROM claims").fetchone()[0])

    section("Sync")
    code, out, _ = B.run([B.GIT, "status", "--porcelain"], cwd=B.VAULT)
    pending = len([l for l in out.splitlines() if l.strip()])
    print("uncommitted changes: %d" % pending)
    code, out, _ = B.run([B.GIT, "log", "-1", "--format=%h %cr — %s"], cwd=B.VAULT)
    print("last commit: %s" % (out or "none"))
    code, out, _ = B.run([B.GIT, "remote", "-v"], cwd=B.VAULT)
    print("remote: %s" % (out.splitlines()[0] if out.strip() else "NOT CONFIGURED (no cloud copy)"))
    # The question doctor could not answer: is the cloud copy actually current? A stale
    # remote is the failure that costs real work, and until now the report said nothing
    # about it — `last commit` looks healthy whether or not the push ever landed.
    # Never fetches: this must stay a local, offline-safe read.
    code, out, _ = B.run([B.GIT, "log", "@{u}..HEAD", "--format=%ct"], cwd=B.VAULT)
    if code != 0:
        code2, out2, _ = B.run([B.GIT, "log", "-1", "--format=%cr", "origin/main"], cwd=B.VAULT)
        print("unpushed: no upstream configured%s"
              % (" (origin/main last seen %s)" % out2.strip() if code2 == 0 and out2.strip() else ""))
    elif not out.strip():
        print("unpushed: nothing — the remote is current")
    else:
        stamps = [float(x) for x in out.split() if x.strip().isdigit()]
        mins = (B.now() - min(stamps)) / 60 if stamps else 0
        print("unpushed: %d commit(s), oldest %.0f min ago%s"
              % (len(stamps), mins,
                 "   <- STALE: check logs/daemon.log" if mins > 30 else ""))
    for d in ("rebase-merge", "rebase-apply"):
        if os.path.isdir(os.path.join(B.VAULT, ".git", d)):
            print("REBASE IN PROGRESS: the vault is not syncing until it is resolved "
                  "(git -C %s rebase --abort)" % B.VAULT)
            break
    plist = os.path.expanduser("~/Library/LaunchAgents/com.secondbrain.sync.plist")
    print("launchd daemon: %s" % ("installed" if os.path.exists(plist) else "NOT installed"))

    section("Hook configuration")
    import json
    try:
        st = json.load(open(os.path.expanduser("~/.claude/settings.json")))
        hooks = st.get("hooks", {})
        print("events wired: %s" % (", ".join(sorted(hooks.keys())) or "NONE"))
    except Exception as exc:
        print("could not read settings.json: %r" % exc)
    print("agents: %d   skills: %d"
          % (len(glob.glob(os.path.expanduser("~/.claude/agents/*.md"))),
             len(glob.glob(os.path.expanduser("~/.claude/skills/*/SKILL.md")))))

    section("Startup budget (T0)")
    try:
        import protocol_budget as PB
        import compass
        v = PB.assess(compass.build_sections(con))
        print("used: %d / %d tokens (%.0f%%)  ->  %s"
              % (v["total"], v["max"], 100 * v["ratio"], v["status"]))
        for name, _t, prio, n in sorted(v["sections"], key=lambda s: -s[3]):
            print("  %-12s %5d tokens   priority %d" % (name, n, prio))
        if v["fat_lines"]:
            print("bullets over %d tokens: %d" % (PB.MAX_LINE_TOKENS, len(v["fat_lines"])))
            for n, line in v["fat_lines"][:3]:
                print("  %4d  %s…" % (n, line[2:76]))
        if v["status"] != "OK" or v["fat_lines"]:
            print("-> %s" % PB.advice(v))
    except Exception as exc:
        print("could not compute: %r" % exc)

    section("Session transcripts — weight and screenshots")
    # A session piling up screenshots dies on its own: every turn re-sends the whole
    # conversation, and one screenshot is around 1,600 vision tokens that stay there
    # forever. It happened with the portfolio one: 143 screenshots, 101 MB, ~229k tokens
    # of image alone, and the window stopped being able to finish a turn.
    import glob as _g2
    tdir = os.path.join(os.path.expanduser("~/.claude/projects"), "-" + os.path.expanduser("~").strip("/").replace("/", "-"))
    fat = []
    for f in _g2.glob(os.path.join(tdir, "*.jsonl")):
        mb = os.path.getsize(f) / 1048576.0
        if mb < 20:
            continue
        img = 0
        try:
            with open(f, errors="replace") as fh:
                for line in fh:
                    if '"<image>"' in line or '"type":"image"' in line:
                        img += len(line)
        except OSError:
            continue
        fat.append((mb, img / 1048576.0, os.path.basename(f)[:8]))
    if fat:
        print("%-10s %9s %9s  %s" % ("session", "total", "images", "state"))
        for mb, imb, sid in sorted(fat, reverse=True):
            pct = 100.0 * imb / mb if mb else 0
            state = ("CRITICAL: will not finish a turn" if mb > 80 else
                      "watch" if mb > 40 else "ok")
            print("  %-8s %7.1f MB %7.1f MB (%2.0f%%)  %s" % (sid, mb, imb, pct, state))
        peor = max(fat)
        if peor[0] > 80:
            print("-> open a fresh session for that work: the context no longer fits.")
            print("   To iterate on screens, use `read_page` and computed CSS instead of")
            print("   screenshots; each one is ~1,600 tokens that never leave.")
    else:
        print("no transcript exceeds 20 MB")

    section("Coordination between machines")
    try:
        import presence as _P
        d = _P.cache_read()
        if d:
            age = B.now() - (d.get("read_at") or 0)
            print("presence (S3), read %.0f s ago from %s:" % (age, d.get("machine", "?")))
            for v in d.get("alive") or []:
                print("  %-16s sid=%-10s project=%-14s %.0fs ago"
                      % (v["machine"], v["sid"], v["project"], v.get("age", 0)))
            if not (d.get("alive") or []):
                print("  nobody else alive")
        else:
            print("presence (S3): no data — %s"
                  % ("the credentials volume is not mounted"
                     if not __import__("shutil").which("op") else
                     "no heartbeat yet, or no network"))
        import lease as _L
        ls = _L.cache_read()
        if ls:
            print("write leases:")
            for k, v in sorted(ls.items()):
                est = _L.local_state(v.get("note", ""))
                print("  %-52s %-6s %s" % (v.get("note", k)[:52], est or "expired",
                                           v.get("owner", "")))
        else:
            print("leases: none held on this machine")
    except Exception as exc:
        print("could not read: %r" % exc)

    section("Local logs")
    if os.path.isdir(B.LOGS):
        channels = {}
        for f in sorted(os.listdir(B.LOGS)):
            if not f.endswith(".log") and ".log." not in f:
                continue
            channel = f.split(".log")[0]
            channels.setdefault(channel, [0, 0])
            channels[channel][0] += os.path.getsize(os.path.join(B.LOGS, f))
            channels[channel][1] += 1
        print("path: %s   cap %d x %.0f MB per channel"
              % (B.LOGS, B.LOG_KEEP + 1, B.LOG_MAX_BYTES / 1048576.0))
        for channel, (weight, n) in sorted(channels.items(), key=lambda x: -x[1][0]):
            print("  %-10s %7.2f MB in %d file(s)" % (channel, weight / 1048576.0, n))
        if not channels:
            print("  (nothing written yet)")
        slow = os.path.join(B.LOGS, "slow.log")
        if os.path.exists(slow):
            lines = open(slow, errors="replace").read().strip().splitlines()[-5:]
            if lines:
                print("last slow subprocesses (>%.0fs):" % B.SLOW_SECONDS)
                for l in lines:
                    print("  %s" % l[:110])
        errors = os.path.join(B.LOGS, "errors.log")
        if os.path.exists(errors):
            n = len(open(errors, errors="replace").read().strip().splitlines())
            print("errors recorded: %d  (%s)" % (n, errors))
    else:
        print("no logs yet in %s" % B.LOGS)

    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
