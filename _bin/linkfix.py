#!/usr/bin/env python3
"""linkfix — finds broken [[links]] in the vault and repairs the ones with a safe fix.

The user's rule (2026-09-10): every time the vault is searched, broken links are looked
for and fixed. So this runs on every search, not when someone remembers:

  - retrieve.py (every prompt) classifies from the index, which is cheap, and launches
    this detached when there is something to fix;
  - query.py (/recall) runs it inline and prints what is left.

  linkfix.py            refresh aliases if git moved, rewrite fixable links, report
  linkfix.py --list     report only, no writes
  linkfix.py --hook     the detached run from retrieve.py: quiet

What gets rewritten, and only this: a link that resolves (see brainlib.LinkResolver)
but not by the note's filename. A link by frontmatter id, by an old filename or old id
(git history), with the wrong date, or with `.md`/spaces, becomes `[[<filename>]]`.
Nothing is guessed: a link with no resolution is REPORTED, never pointed somewhere
plausible. Meeting topic links (`[[cashback]]` in 15-Meetings) are not broken, they are
topic nodes by convention, and pending `[[entity-...]]` participants connect on their
own once the entity note exists.
"""
import os, re, sys, json, time, argparse, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B

STATE = os.path.join(B.STATE, "linkfix.json")
CANONICAL = ("exact", "undated", "entity")
TOPIC_FOLDERS = ("15-Meetings",)
# A detached run is not launched more often than this, whatever the prompts do.
SPAWN_EVERY = 60
# Unfixable links alone re-trigger a run this often: git may have brought the alias.
RETRY_BROKEN_EVERY = 600


# ------------------------------------------------------------------------- state
def load_state():
    try:
        with open(STATE) as fh:
            return json.load(fh)
    except Exception:
        return {}


def save_state(**kw):
    st = load_state()
    st.update(kw)
    try:
        os.makedirs(B.STATE, exist_ok=True)
        B.atomic_write(STATE, json.dumps(st))
    except Exception as e:
        B.log_error("linkfix.save_state", e)


# ------------------------------------------------------------------ classification
def classify(con, R=None):
    """Every edge of the graph into: fix, broken, topic, pending (and fine).

    Cheap on purpose (dict lookups, no disk, no git): retrieve.py calls it on every
    prompt.
    """
    R = R or B.LinkResolver(con)
    fix, broken, topics, pending = [], [], 0, 0
    for src, tgt in con.execute("SELECT source, target FROM links ORDER BY source"):
        path, how = R.resolve(tgt)
        if path:
            if how not in CANONICAL:
                new = os.path.splitext(os.path.basename(path))[0]
                if new != tgt:
                    fix.append((src, tgt, new, how))
            continue
        if src.split("/")[0] in TOPIC_FOLDERS and not B.DATE_PREFIX.match(tgt):
            if tgt.startswith("entity-"):
                pending += 1
            else:
                topics += 1
            continue
        broken.append((src, tgt))
    return {"fix": fix, "broken": broken, "topics": topics, "pending": pending}


# ------------------------------------------------------------------------ rewrite
_CODE = re.compile(r"(?ms)^```.*?^```|`[^`\n]*`")


def rewrite(text, old, new):
    """`[[old]]`, `[[old|alias]]`, `[[old\\|alias]]`, `[[old#heading]]` -> same with `new`.

    Outside code only: a `[[x]]` inside backticks is an example (the indexer ignores it
    too, see index_vault.without_code), and rewriting it would change what it shows.
    Embeds (`![[file.png]]`) are left alone. Returns (text, count).
    """
    pat = re.compile(r"(?<!!)\[\[\s*" + re.escape(old) + r"\s*(?=\\?\||#|\]\])")
    out, last, total = [], 0, 0
    for m in _CODE.finditer(text):
        seg, n = pat.subn("[[" + new.replace("\\", "\\\\"), text[last:m.start()])
        out.append(seg)
        out.append(m.group(0))
        total += n
        last = m.end()
    seg, n = pat.subn("[[" + new.replace("\\", "\\\\"), text[last:])
    out.append(seg)
    return "".join(out), total + n


def apply(con, fixes):
    """Rewrites the fixable links in place. Returns the list of files changed.

    Per-file lock and atomic write, like vw.py. The mtime is put BACK: vault_ledger
    credits any note whose mtime lands inside a session's window to that session, and a
    background repair must not count as someone having saved memory.
    """
    by_src = {}
    for src, old, new, _how in fixes:
        by_src.setdefault(src, []).append((old, new))
    changed = []
    for src, pairs in sorted(by_src.items()):
        path = os.path.join(B.VAULT, src)
        if not B.in_vault(path):
            continue
        with B.flock(path):
            try:
                st = os.stat(path)
                text = open(path, errors="replace").read()
            except OSError:
                continue
            new_text, n = text, 0
            for old, new in pairs:
                new_text, k = rewrite(new_text, old, new)
                n += k
            if not n or new_text == text:
                continue
            B.atomic_write(path, new_text)
            try:
                os.utime(path, (st.st_atime, st.st_mtime))
            except OSError:
                pass
            changed.append(src)
    if changed:
        import index_vault as IV
        for src in changed:
            IV.index_one(con, os.path.join(B.VAULT, src))
        con.commit()
    return changed


# ----------------------------------------------------------------------- aliases
def _git(*args, timeout=30):
    code, out, _err = B.run([B.GIT, "-C", B.VAULT, "-c", "core.quotepath=off"] + list(args),
                            timeout=timeout)
    return out if code == 0 else ""


def _base(p):
    return os.path.splitext(os.path.basename(p.strip().strip('"')))[0]


def refresh_aliases(con, force=False):
    """Old filenames and old ids -> the note that carries them now. From git history.

    Half a second on this vault, so it only runs when HEAD moved since the last time.
    A current name always wins: an alias is never stored for a name some note has today.
    """
    head = _git("rev-parse", "HEAD", timeout=5)
    if not head:
        return 0
    if not force and load_state().get("alias_head") == head:
        return 0
    renames = {}
    for line in _git("log", "--format=", "--name-status", "-M", "--diff-filter=R",
                     "--", "*.md").splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0].startswith("R"):
            renames[_base(parts[1])] = _base(parts[2])
    old_ids, cur = {}, None
    for line in _git("log", "--format=commit %H", "-p", "--unified=0", "-G^id: ",
                     "--", "*.md", timeout=60).splitlines():
        if line.startswith("diff --git "):
            cur = _base(line.rsplit(" b/", 1)[-1]) if " b/" in line else None
        elif line.startswith("-id: ") and cur:
            oid = line[5:].strip().strip("'\"")
            if oid:
                old_ids.setdefault(oid, cur)

    def follow(name):
        seen = set()
        while name in renames and name not in seen:
            seen.add(name)
            name = renames[name]
        return name

    R = B.LinkResolver(con)
    taken = set(R.exact) | set(R.ids)
    rows = {}
    for old, new in renames.items():
        path = R.exact.get(follow(new))
        if path and old not in taken:
            rows[old] = (path, "rename")
    for oid, base in old_ids.items():
        path = R.exact.get(follow(base))
        if path and oid not in taken and oid not in rows:
            rows[oid] = (path, "old-id")
    con.execute("DELETE FROM link_aliases")
    con.executemany("INSERT OR REPLACE INTO link_aliases VALUES(?,?,?)",
                    [(a, p, h) for a, (p, h) in rows.items()])
    con.commit()
    save_state(alias_head=head)
    return len(rows)


# --------------------------------------------------------------------------- run
def run(con, write=True, refresh=True, force_refresh=False):
    """One full pass. Returns (result, files_changed, links_fixed)."""
    lk = B.flock(os.path.join(B.STATE, "linkfix.run"), timeout=0.5)
    lk.__enter__()
    try:
        if not getattr(lk, "held", True):
            return classify(con), [], 0          # another pass is running right now
        if refresh:
            refresh_aliases(con, force_refresh)
        res = classify(con)
        changed, fixed = [], 0
        if write and res["fix"]:
            fixed = len(res["fix"])
            changed = apply(con, res["fix"])
            res = classify(con)
        save_state(ts=B.now(), broken=res["broken"][:200], fix_left=len(res["fix"]))
        B.metric(con, "linkfix", "linkfix", hits=fixed,
                 extra="files=%d broken=%d fix_left=%d topics=%d pending=%d"
                       % (len(changed), len(res["broken"]), len(res["fix"]),
                          res["topics"], res["pending"]))
        return res, changed, fixed
    finally:
        lk.__exit__()


def spawn_detached():
    """Fire and forget: a prompt must never wait on a repair."""
    save_state(spawned=B.now())
    try:
        subprocess.Popen([sys.executable or "/usr/bin/python3", os.path.abspath(__file__),
                          "--hook"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
    except Exception as e:
        B.log_error("linkfix.spawn", e)


def maybe_spawn(res):
    """What retrieve.py calls with the cheap classification it already has."""
    if B.OFFLINE:
        return False              # the hook probe: nothing detached may outlive its scratch state
    st = load_state()
    if B.now() - st.get("spawned", 0) < SPAWN_EVERY:
        return False
    if res["fix"] or (res["broken"] and B.now() - st.get("ts", 0) > RETRY_BROKEN_EVERY):
        spawn_detached()
        return True
    return False


def notice(res, limit=3):
    """What the agent is told when a link has no safe fix: it has to fix it by hand."""
    broken = res["broken"]
    if not broken:
        return ""
    lines = ["Broken [[links]] with no safe automatic fix (%d). Point each at the right "
             "note, or remove it:" % len(broken)]
    for src, tgt in broken[:limit]:
        lines.append("  `%s` -> [[%s]]" % (src, tgt))
    if len(broken) > limit:
        lines.append("  all of them: `python3 ~/Brain/_bin/linkfix.py --list`")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(prog="linkfix")
    ap.add_argument("--list", action="store_true", help="report only, no writes")
    ap.add_argument("--hook", action="store_true", help="quiet detached run")
    ap.add_argument("--refresh", action="store_true", help="rebuild aliases even if HEAD did not move")
    args = ap.parse_args()
    if not B.enabled():
        return 0
    con = B.db()
    try:
        res, changed, fixed = run(con, write=not args.list, force_refresh=args.refresh)
    finally:
        con.close()
    if args.hook:
        return 0
    if args.list and res["fix"]:
        print("fixable (%d), rewritten on the next run:" % len(res["fix"]))
        for src, old, new, how in res["fix"]:
            print("  %-8s %s: [[%s]] -> [[%s]]" % (how, src, old, new))
    if fixed:
        print("fixed %d link(s) in %d file(s):" % (fixed, len(changed)))
        for src in changed:
            print("  %s" % src)
    if res["broken"]:
        print("broken, need a hand (%d):" % len(res["broken"]))
        for src, tgt in res["broken"]:
            print("  %s -> [[%s]]" % (src, tgt))
    print("links: %d broken, %d fixable left, %d meeting topics, %d pending entities"
          % (len(res["broken"]), len(res["fix"]), res["topics"], res["pending"]))
    return 1 if res["broken"] else 0


if __name__ == "__main__":
    sys.exit(main())
