#!/usr/bin/env python3
"""Sync daemon. The ONLY process that touches git in the vault.

Sessions never commit or push: they only write files and mark .dirty.
Serialised with flock, so several simultaneous sessions produce no races
on index.lock and no crossed rebases.

Inviolable order:  reindex -> SECRET SCAN -> add -> commit -> push
The scan runs BEFORE the commit: a secret that reaches the remote is compromised even
if it is deleted afterwards.
"""
import os, sys, time, hashlib, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B
import index_vault

PACK_TTL_DAYS = 14
GIT = B.GIT


def git(*args):
    # `core.quotePath=false` on EVERY call: by default git escapes in octal
    # any non-ASCII path —"30-Knowledge/decisi\303\263n.md"— and ever since the `add`
    # is per path (it used to be `-A`), that escaped path matches no file at all: the
    # `add` fails and **the note is never committed**. Silent memory loss, and one accent
    # in the filename is enough.
    return B.run([GIT, "-c", "core.quotePath=false"] + list(args),
                 cwd=B.VAULT, timeout=120)


def prune_packs():
    base = os.path.join(B.VAULT, "60-Context-Packs")
    cutoff = time.time() - PACK_TTL_DAYS * 86400
    removed = 0
    if not os.path.isdir(base):
        return 0
    for fn in os.listdir(base):
        p = os.path.join(base, fn)
        try:
            if os.path.isfile(p) and os.path.getmtime(p) < cutoff:
                if "keep: true" in open(p, errors="replace").read()[:400]:
                    continue
                os.remove(p); removed += 1
        except Exception:
            pass
    return removed


def files_to_commit():
    """Pending paths, asked for in a way that returns **paths and nothing else**.

    It used to parse `git status --porcelain` by position (`line[3:]`), and that broke
    silently: `B.run()` does a `.strip()` on the output and ate the leading space of the
    FIRST line, which is part of the status code. Result:
    `0-Inbox/note.md` instead of `00-Inbox/note.md`. With `git add -A` it went unnoticed
    —it committed everything anyway—, but once `add` was narrowed to a path, that file
    stopped being committed. Always the first on the list, and always in silence.

    These two commands emit paths and nothing else, so the `strip` is harmless.
    """
    paths = []
    code, out, _ = git("diff", "--name-only", "HEAD")      # modified and deleted
    if code == 0:
        paths += [l.strip().strip('"') for l in out.splitlines() if l.strip()]
    code, out, _ = git("ls-files", "--others", "--exclude-standard")   # nuevos
    if code == 0:
        paths += [l.strip().strip('"') for l in out.splitlines() if l.strip()]
    vistos, unicos = set(), []
    for p in paths:
        if p not in vistos:
            vistos.add(p); unicos.append(p)
    return unicos


ALLOW_MARKER = "brain:allow-secrets"
# The marker only counts as a declaration if it is at the TOP of the file.
ALLOW_MARKER_LINES = 10
# Bounded so a stray huge file cannot blow up memory on the Stop hook.
SCAN_MAX_CHARS = 8_000_000


def secret_gate(paths):
    """Returns a list of (path, kind, fragment) for whatever CANNOT be committed.

    A file declaring the `brain:allow-secrets` marker in its first lines is exempt:
    those are synthetic test credentials, not real ones.
    """
    hits = []
    for rel in paths:
        full = os.path.join(B.VAULT, rel)
        if not os.path.isfile(full):
            continue
        try:
            # The read is BOUNDED, the file is not SKIPPED. Skipping meant an unscanned
            # file never entered `hits`, so it was never blocked, so it was committed and
            # pushed — while va.py's own comment promised the opposite for the .json/.sql/
            # .env-ish text it allows up to 25 MB: "if one carried a credential,
            # vault_sync.py's secret_gate blocks it before it reaches the remote". That
            # contract was false for everything between 2 MB and 25 MB.
            text = open(full, errors="replace").read(SCAN_MAX_CHARS)
        except Exception:
            continue
        # In the first LINES, as documented — not "anywhere in the first 2000 characters".
        # The wide window made every generated ALERT note exempt itself, because the
        # instructions it prints to the user quote the marker verbatim near the end. A
        # file could also acquire the exemption just by MENTIONING the marker in prose.
        if ALLOW_MARKER in "\n".join(text.splitlines()[:ALLOW_MARKER_LINES]):
            continue
        for kind, frag in B.scan_secrets(text):
            hits.append((rel, kind, frag))
    return hits


def report_blocked(hits):
    """Moves and deletes nothing: it leaves the file where it is, out of the commit, and
    warns.

    Moving files would be destructive and surprising; blocking the whole vault over one
    file would be worse. Only the offender is excluded and the rest keeps syncing.
    """
    lines = ["---", "id: %s-secrets-warning" % time.strftime("%Y-%m-%d-%H%M%S"),
             "title: Files excluded from the commit for possible credentials", "type: meta",
             "area: [security]", "projects: [brain]", "tags: [security, secrets]",
             "status: active", "confidence: high", "source: agent",
             "provenance: vault_sync.py", "updated: " + time.strftime("%Y-%m-%d"),
             "supersedes: []", "---", "",
             "The daemon spotted what look like credentials. These files have **not been",
             "committed** and are still in place, never leaving this machine:", ""]
    seen = set()
    for rel, kind, frag in hits:
        key = (rel, kind)
        if key in seen:
            continue
        seen.add(key)
        lines.append("- `%s` — %s (`%s`)" % (rel, kind, frag))
    lines += ["", "What to do:",
              "1. If it is real: take it out of the file and rotate the credential.",
              "2. If it is a synthetic example (tests, docs): add the comment",
              "   `brain:allow-secrets` in the file's first lines.",
              "3. If the file should not be versioned: move it to `80-Private/`."]
    # One note per DISTINCT condition, not one per pass. The gate fires on every sync for
    # as long as the offending file sits there, and each firing used to leave another
    # note: 8 on disk, all saying the same thing. The fingerprint is the set of
    # (path, kind) pairs; while it does not change, the warning has already been given.
    fp = hashlib.sha1(("\n".join("%s|%s" % (r, k) for r, k, _ in sorted(hits)))
                      .encode()).hexdigest()[:16]
    stamp = os.path.join(B.STATE, "secret-alert.fp")
    try:
        if open(stamp).read().strip() == fp:
            return
    except OSError:
        pass
    try:
        os.makedirs(B.STATE, exist_ok=True)
        B.atomic_write(stamp, fp)
    except OSError:
        pass
    alert = "00-Inbox/ALERT-secrets-%s.md" % time.strftime("%Y%m%d-%H%M%S")
    B.atomic_write(os.path.join(B.VAULT, alert), "\n".join(lines) + "\n")
    # Written by the daemon, not by a session: it must not count as anyone having saved.
    B.mark_git_touched([alert])


def has_remote():
    code, out, _ = git("remote")
    return code == 0 and bool(out.strip())


def refresh_plugin():
    """Dumps the live harness from ~/.claude into the vault plugin, before committing.

    Without this the repo keeps the memory but not the system that uses it: agents,
    skills and hooks are edited in ~/.claude and the plugin silently falls behind. It
    really happened — the plugin ended up missing a whole skill — and the symptom only
    shows when setting up a new machine, which is the worst possible moment.

    It can never bring the sync down: if it fails, it is logged and we carry on.
    """
    try:
        import build_plugin
        build_plugin.main()
        return True
    except Exception as e:
        B.log_error("vault_sync.refresh_plugin", e)
        print("warning: could not refresh the plugin (%s)" % e)
        return False


DAEMON_LOG = os.path.join(B.LOGS, "daemon.log")
MACHINE = B._machine()


def rotate_daemon_output():
    """launchd rotates nothing: it opens StandardOutPath on every run and writes until
    the disk fills. The file had grown to 46 KB with no cap, inside the vault. Since the
    descriptor is opened per run, renaming it here is safe: this pass ends up in the
    rotated file and the next one starts a fresh file."""
    B._log_rotate(DAEMON_LOG)


def purge_dead_sessions():
    """Rows for sessions with no heartbeat, and their claims. Only the daemon does this:
    a live session must not decide that another one is dead."""
    con = B.db()
    dead_ones = [s for (s, hb) in con.execute("SELECT sid, heartbeat FROM sessions")
               if not B.session_alive(hb)]
    for s in dead_ones:
        con.execute("DELETE FROM claims WHERE sid=?", (s,))
    if dead_ones:
        con.commit()
        B.log("sync", "purga-sesiones", n=len(dead_ones))
    con.close()


def rebase_en_curso():
    return os.path.isdir(os.path.join(B.VAULT, ".git", "rebase-merge")) or\
           os.path.isdir(os.path.join(B.VAULT, ".git", "rebase-apply"))


def fetch_from_remote():
    """`pull --rebase`, and on conflict it ABORTS and says so loudly.

    Without this, a conflict between two machines left the repo mid-rebase: every
    following pass failed and **the system stopped syncing in silence**.
    A vault that believes it syncs and does not is worse than one that never tries.
    """
    _, head_before, _ = git("rev-parse", "HEAD")
    code, out, err = git("pull", "--rebase", "--autostash")
    if code == 0:
        # Everything the rebase rewrote carries mtime = now. Marked, or the memory gate
        # reads the OTHER machine's commit as this session having saved something.
        if head_before.strip():
            rc2, changed, _ = git("diff", "--name-only", head_before.strip(), "HEAD")
            if rc2 == 0 and changed.strip():
                B.mark_git_touched(changed.splitlines())
        return True
    # A note is written ONLY for a real rebase conflict. Every other non-zero pull — host
    # unreachable, auth, remote gone — used to produce one too, with instructions that are
    # simply wrong for those cases ("resolve it by hand"), and one more on every pass for
    # as long as the outage lasted. An outage is not a conflict, and a fail-open system
    # must not answer repetition with unbounded growth.
    was_conflict = rebase_en_curso()
    if was_conflict:
        git("rebase", "--abort")
    else:
        B.log("sync", "pull-failed", machine=MACHINE, err=(err or "")[:200])
        print("pull failed (no rebase conflict): %s" % (err or "").strip()[:160])
        return False
    warn_rel = "00-Inbox/CONFLICT-sync-%s.md" % time.strftime("%Y%m%d-%H%M%S")
    warning = os.path.join(B.VAULT, warn_rel)
    B.mark_git_touched([warn_rel])
    try:
        with open(warning, "w") as fh:
            fh.write("---\ntitle: Sync conflict with the remote\n"
                     "type: reference\nstatus: active\n---\n\n"
                     "The `pull --rebase` failed on **%s** and was aborted so the "
                     "repository would not be left half-done.\n\nIt has to be resolved "
                     "by hand:\n\n"
                     "```bash\ncd %s && git pull --rebase\n```\n\n"
                     "git output:\n\n```\n%s\n%s\n```\n"
                     % (MACHINE, B.VAULT, (out or "")[:1500], (err or "")[:1500]))
    except OSError:
        pass
    B.log("sync", "rebase-conflict", machine=MACHINE, err=(err or "")[:200])
    print("CONFLICT with the remote: rebase aborted, notice in %s"
          % os.path.basename(warning))
    return False


def push_with_retry(attempts=3):
    """Pushes, retrying on a race with another machine.

    Two machines committing produce a `non-fast-forward`. It used to be postponed to "the
    next cycle" — 10 minutes — and with both machines active it might never converge.
    """
    for i in range(attempts):
        code, out, err = git("push")
        if code == 0:
            return True, ""
        text = (err or "") + (out or "")
        if "non-fast-forward" not in text and "fetch first" not in text\
           and "rejected" not in text:
            return False, text[:200]          # not a race: do not insist
        B.log("sync", "push-rechazado", attempt=i + 1, machine=MACHINE)
        if not fetch_from_remote():
            return False, "rebase conflict"
    return False, "%d attempts and the remote is still ahead" % attempts


def main():
    if not B.enabled():
        return 0
    rotate_daemon_output()

    # Hook mode: this runs at the END OF EVERY TURN, with the user waiting. There is no
    # blocking 30 s on a lock and no copying the whole plugin (148 files from `impeccable`
    # alone) each time. If another sync is under way, it exits and the daemon picks it up
    # on its next pass, 10 minutes later. The rule: the turn ends, whatever happens.
    hook = "--hook" in sys.argv
    with B.flock(os.path.join(B.VAULT, "_index", ".gitlock"),
                 timeout=1.5 if hook else 30) as lk:
        if not lk.held:
            print("another sync in progress, leaving (the daemon will pick it up)")
            return 0

        if not hook:
            refresh_plugin()
            purge_dead_sessions()
            n_pres = B.presence_purge()
            if n_pres:
                print("orphaned presences withdrawn: %d" % n_pres)
        index_vault.reindex()
        pruned = prune_packs()

        code, _, _ = git("rev-parse", "--git-dir")
        if code != 0:
            print("the vault is not a git repo")
            return 0

        # A half-finished rebase on ARRIVAL here is not ours: either a dead pass left
        # it, or — the important case — the user is resolving a conflict by hand in
        # ~/Brain. It used to be aborted outright, and that wiped the resolution work
        # already done.
        #
        # Nor can we carry on: committing with a rebase in progress puts the
        # commits on DETACHED HEAD, hanging off nothing, invisible to
        # any push. The work would look saved without being saved — and that was the
        # failure that stopped it converging.
        #
        # So it neither aborts nor commits: it stops and says so loudly. A vault that
        # cannot sync has to shout about it, not paper over it.
        if rebase_en_curso():
            B.log("sync", "stopped-rebase-in-progress", machine=MACHINE)
            print("REBASE IN PROGRESS in %s: nothing is committed (the commits would go\n"
                  "  to a detached HEAD). Finish or abort it by hand:\n"
                  "    cd %s && git rebase --continue   # or --abort" % (B.VAULT, B.VAULT))
            return 1

        # The network is NOT on the path that closes the turn. The local commit already
        # puts the work out of harm's way; pushing it means having a cloud copy, and that
        # can wait for the daemon's next pass (10 min). It used to be ~2 s of pull+push on
        # EVERY turn, and if the network stalled, the turn never finished.
        if has_remote() and not hook:
            fetch_from_remote()

        paths = files_to_commit()

        # --- Isolation between sessions on the same machine --------------------
        # They all share ONE working tree, so one session's `git add -A` sweeps up what
        # another is halfway through writing. With NOTES that is harmless: `vw.py`/`va.py`
        # write atomically, so committing them is always safe no matter who wrote them.
        # CODE can genuinely be mid-refactor, and there only what has gone `QUIESCENCE`
        # seconds untouched gets committed.
        def is_note(rel):
            return rel.split("/")[0] in B.VAULT_NOTES

        otras = B.live_sessions(B.db(), exclude=None)
        en_vuelo = [r for r in paths
                    if not is_note(r) and not B.at_rest(os.path.join(B.VAULT, r))]
        if en_vuelo:
            paths = [r for r in paths if r not in en_vuelo]
            print("in flight, left for the next pass (%d live session(s)): %s"
                  % (len(otras), ", ".join(en_vuelo[:5])))
            B.log("sync", "deferred-in-flight", n=len(en_vuelo),
                  files_=",".join(en_vuelo[:5]))

        if not paths:
            print("nothing to commit (packs purged: %d)" % pruned)
            return 0

        hits = secret_gate(paths)
        blocked = sorted(set(rel for rel, _, _ in hits))
        if blocked:
            report_blocked(hits)
            print("EXCLUDED from the commit for possible credentials: %s" % ", ".join(blocked))

        # `add` scoped to what was decided, not `-A`: that way whatever another session
        # has in flight cannot slip in through the back door.
        #
        # A blocked path is never added in the first place. It used to be added and then
        # reset out of the index — but `git add` writes the file's full content into
        # `.git/objects` as a loose blob, and `git reset` only touches the index. Every
        # credential the gate had ever blocked was therefore sitting verbatim inside the
        # very repository the gate exists to keep it out of, readable with
        # `git cat-file -p <sha>` and carried along by any copy or backup of the vault.
        # The gate reported success while leaking. Unreachable objects are not pushed, so
        # the blast radius was this machine — but they survive until someone prunes them.
        for rel in paths:
            if rel in blocked:
                continue
            git("add", "--", rel)
        code, out, _ = git("diff", "--cached", "--name-only")
        if not out.strip():
            print("no effective changes (everything pending was blocked)" if blocked
                  else "no effective changes")
            return 2 if blocked else 0
        n = len(out.splitlines())
        # Who committed, so the history is readable with several machines in play.
        msg = "vault: %d file(s) — %s — %s" % (
            n, MACHINE, time.strftime("%Y-%m-%d %H:%M"))
        code, out, err = git("commit", "-q", "-m", msg)
        if code != 0:
            print("commit failed: %s %s" % (out[:200], err[:200]))
            return 1
        print("committed: %s%s" % (msg, " (with %d file(s) excluded)" % len(blocked) if blocked else ""))

        if hook:
            # Committed locally, which is what saves the work. The push is done by the
            # daemon does the push; that way the turn ends without waiting on the network.
            print("local commit; the push is left to the daemon")
        elif has_remote():
            ok, reason = push_with_retry()
            if not ok:
                print("push failed: %s" % reason)
                return 1
            print("push OK")
        else:
            print("no remote configured: local commit only")
        try:
            os.remove(os.path.join(B.VAULT, "_index", ".dirty"))
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
