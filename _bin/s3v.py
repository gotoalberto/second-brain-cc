#!/usr/bin/env python3
"""s3v — the vault's file store, in S3.

The git vault holds the MEMORY (notes, relations, decisions). The files
— deliverables, intermediate steps, source material — live here. That way the memory
never fattens and never has to be summarised or collapsed: every note carries pointers.

    s3v.py put <file...> --to <note> --project <slug> [--kind entregable|intermedio|material]
    s3v.py ls [--project <slug>]
    s3v.py get <key> [--out <dir>]
    s3v.py check                      # note references no longer present in S3
    s3v.py url <key> [--min 60]       # temporary signed link

The secret NEVER passes through argv nor stays in the shell environment: the process
re-executes through `secret.py get ... --pipe`, which hands it over on stdin.
The `--kind` values and the S3 prefixes stay in Spanish on purpose: they are the
layout of objects already in the bucket, and renaming them would orphan them.
See 30-Knowledge on the file vault in S3.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B

BUCKET = os.environ.get("BRAIN_S3_BUCKET", "CHANGE-ME-your-bucket")
REGION = "eu-west-1"
# S3 credentials, via the optional 1Password module (or the standard AWS environment).
# The Secret Access Key is resolved through secret.py from a 1Password reference; the
# Access Key ID comes from $AWS_ACCESS_KEY_ID or its own reference. Override with envs.
SECRET_REF = os.environ.get("BRAIN_AWS_SECRET_REF", "op://Private/aws-brain-s3/credential")
SECRET_ID_REF = os.environ.get("BRAIN_AWS_KEYID_REF", "op://Private/aws-brain-s3/username")
SECRET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "secret.py")
AWS = "/opt/homebrew/bin/aws"

KINDS = ("entregable", "intermedio", "material")
MARCA = "## Files in S3"

# The cached Access Key ID. It is the UserName field of the 1Password item entry, NOT the
# secret, and STATE lives outside the repository.
CACHE_KEY_ID = os.path.join(B.STATE, "aws-key-id")
# Coordination state, not content: one definition, read by cmd_check and by
# coordination_lifecycle. DO NOT TRANSLATE — see presence.PREFIX.
COORD_PREFIXES = ("locks/", "presencia/")
PRESIGN_MAX_MIN = 7 * 24 * 60      # SigV4 caps a presigned URL at 7 days
CAS_ATTEMPTS = 5          # retry cap for the manifest compare-and-swap

# "This credential is not valid", which is different from "the network failed". Only
# these errors invalidate the Access Key ID cache: if the cached ID belongs to a rotated
# key, without this the cache would poison every run that follows.
CRED_REJECTED = ("InvalidAccessKeyId", "SignatureDoesNotMatch",
                  "InvalidClientTokenId", "AuthFailure", "ExpiredToken")
# A conditional put losing the race: 412 if the ETag is no longer the one we read,
# 409 if two conditionals overlap. Both are normal and get retried.
# The numeric codes go in AS WELL AS the name because the CLI does not phrase it the same
# depending on where the error comes from: against the real bucket a 412 arrives as "An
# error occurred (412) ... Precondition Failed" — with a space — when the response has no
# XML body, and as "(PreconditionFailed)" when it does. Matching only one shape left the
# retry dead and turned losing the race into aborting.
CAS_LOST = ("(412)", "(409)", "PreconditionFailed", "Precondition Failed",
               "ConditionalRequestConflict")
# `aws s3 cp` when the key does not exist. Telling it apart from a 403 matters: on a 404
# the hashed variant can be looked up; on a 403 one must give up and say so.
NOT_FOUND = ("(404)", "Not Found", "does not exist")


# ---------------------------------------------------------------- utilidades
def die(msg, code=1):
    sys.stderr.write("s3v: %s\n" % msg)
    sys.exit(code)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def human(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return "%.1f %s" % (n, u) if u != "B" else "%d B" % n
        n /= 1024.0


_CRED_REFRESCADA = [False]      # the retry on a rejected credential happens exactly once


def aws(*args, **kw):
    """Runs the CLI with the credentials already in THIS process's environment.

    It leaves a trace of every call: this is the network, it takes time, and when an
    upload fails at three in the morning the log is all that is left. The arguments go to
    the log as they are because they are paths and object keys; the credentials live in
    the environment, not here, so there is nothing to redact.

    With raw=True it returns (rc, stdout, stderr) instead of dying. Without that,
    tolerate=True only returned stdout and threw away the code and stderr: a 412
    PreconditionFailed —the NORMAL result of losing a compare-and-swap, which must be
    retried— was the same empty string as a 404, a 403 or a dropped connection, which
    demand aborting. With those four indistinguishable there was no way to write the
    manifest without clobbering someone.
    """
    _t0 = time.time()
    p = subprocess.run([AWS] + list(args), capture_output=True, text=True,
                       timeout=kw.get("timeout", 600))
    B.log("s3", args[0] if args else "?", secs="%.2f" % (time.time() - _t0),
           rc=p.returncode, args=" ".join(args[1:4]))
    if p.returncode != 0 and any(m in p.stderr for m in CRED_REJECTED)\
            and _refresh_key_id():
        return aws(*args, **kw)
    if p.returncode != 0 and not (kw.get("tolerate") or kw.get("raw")):
        die("aws %s failed: %s" % (args[0] if args else "", p.stderr.strip()[:300]))
    if kw.get("raw"):
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    return p.stdout.strip()


def _refresh_key_id():
    """Drop the Access Key ID cache, reread it from the 1Password item and say if a retry is worth it.

    It is the counterpart of caching: without this, rotating the key in the 1Password item left the ID
    old one in the cache file and EVERY run that followed failed the same way, with no
    clue why. It happens once per process: if the reread ID is the same, the thing that is
    invalid is the secret, and retrying would be a loop.
    """
    if _CRED_REFRESCADA[0] or not os.environ.get("AWS_SECRET_ACCESS_KEY"):
        return False
    _CRED_REFRESCADA[0] = True
    try:
        os.remove(CACHE_KEY_ID)
    except OSError:
        pass
    new_one = access_key_id(cache=False)
    if not new_one or new_one == os.environ.get("AWS_ACCESS_KEY_ID"):
        return False
    os.environ["AWS_ACCESS_KEY_ID"] = new_one
    return True


# --------------------------------------------------------- keys and references
def key(project, kind, name, date=None, dg=""):
    """The key encodes project, date and kind: it can be browsed without opening anything.

    The sha256 fragment in the name exists because without it two DIFFERENT files with
    the same basename, the same day, the same project and the same kind landed on the same
    key and the second clobbered the first in silence (`report.pdf` from two machines).
    It also makes the upload idempotent: the same content always lands on the same key,
    so retrying a batch duplicates nothing.

    Old keys —without a hash— remain valid: `get`, `url` and `ls` receive the
    literal key and never recompute it, so notes already citing them open
    exactly the object they always did.
    """
    if dg:
        raiz, ext = os.path.splitext(name)
        name = "%s-%s%s" % (raiz, dg[:8], ext)
    if kind == "material":
        return "material/%s/%s" % (project, name)
    return "proyectos/%s/%s/%s/%s" % (project, date or time.strftime("%Y-%m-%d"), kind, name)


def note_path(rel):
    full = os.path.join(B.VAULT, rel)
    if not os.path.isfile(full):
        die("the note does not exist: %s" % rel)
    return full


def anchor(note_rel, entries):
    """Writes the references into the note. This is what turns S3 into memory:
    a file with no pointer from a note is a lost file.

    The whole read-modify-write goes INSIDE a flock because without it other people's
    work was lost: if a `vw.py append` slipped in between the open().read() and the
    atomic_write, its entry vanished whole and silently, and the note reverted to the
    content we had read.

    It does not delegate to vw.py the way va.py does in protected areas: vw.py only knows
    how to append to `## Log`, and the references have to stay grouped under their own
    section so
    the note stays readable after twenty uploads and so that dedup by key works. What is
    copied from it is what actually matters — the same flock, the same atomic write and
    the same credential redaction — plus the reindex outside the critical section.
    """
    full = note_path(note_rel)
    # One entry = ONE line: the description comes from --caption, and a newline in there
    # split the reference in two, so the dedup below stopped
    # of recognising it and the note ended up citing the same object twice.
    lines = ["- `%s` — %s · %s · `%s`" % (k, " ".join(desc.split()), human(size), dg[:12])
              for k, desc, size, dg in entries]
    # --caption is free text: if someone pastes a credential in there, it never reaches the vault.
    limpio, redactadas = B.scrub_secrets("\n".join(lines))
    if redactadas:
        sys.stderr.write("s3v: " + B.redaction_notice(redactadas))
    lines = limpio.splitlines()
    with B.flock(full):
        txt = open(full, errors="replace").read()
        if MARCA in txt:
            i = txt.index(MARCA) + len(MARCA)
            j = txt.find("\n## ", i)
            section_ = txt[i:j if j > 0 else len(txt)]
            fresh = [l for l in lines if l.split(" — ")[0] not in section_]
            if not fresh:
                return 0
            corte = j if j > 0 else len(txt)
            txt = (txt[:corte].rstrip("\n") + "\n" + "\n".join(fresh) + "\n\n"
                   + txt[corte:].lstrip("\n"))
        else:
            cab = ("\n\n%s\n\nThe bucket is private: these keys are opened with "
                   "`python3 ~/Brain/_bin/s3v.py get <clave>`.\n\n" % MARCA)
            txt = txt.rstrip("\n") + cab + "\n".join(lines) + "\n"
            fresh = lines
        B.atomic_write(full, txt)
    # The reindex goes OUTSIDE the flock: inside, the process hung waiting on the database
    # (the same failure vw.py already had written down).
    B.reindex_notes([full])     # the note and its links enter the index right away
    return len(fresh)


class S3Unknown(Exception):
    """We do not know what is in S3. Different from "there is nothing": it forces an abort
    rather than writing a degraded manifest."""


def real_objects(project):
    """What S3 REALLY says the project has. It is TWO prefixes, not one.

    This used to list only `proyectos/<p>/`, but `key()` sends material to
    `material/<p>/`: the set came out without a single material key and the marking loop
    below declared `ausente: true` over ALL the project's material, that is,
    the manifest declared lost exactly what was there.
    """
    real = set()
    for pref in ("proyectos/%s/" % project, "material/%s/" % project):
        # `aws s3 ls` on an EMPTY prefix returns rc=1 with empty stderr —
        # indistinguishable from an AccessDenied — so with the rc check below a new
        # project would always abort. `list-objects-v2` returns rc=0
        # and the string "None" when there is nothing. Verified against the real bucket.
        rc, listing, err = aws("s3api", "list-objects-v2", "--bucket", BUCKET,
                               "--prefix", pref, "--query", "Contents[].[Key]",
                               "--output", "text", raw=True)
        # A listing that FAILS is not an empty listing. Throwing away the rc, an
        # AccessDenied, a SlowDown or a dropped connection gave an empty set, and the
        # below stamped `ausente: true` over EVERY object in the project — with a
        # conditional put that also succeeded, because the ETag had not changed. The
        # manifest ended up written declaring lost what was actually there.
        # A genuinely empty prefix returns rc=0 and empty output: that one is "nothing".
        if rc != 0:
            raise S3Unknown("could not list %s: %s" % (pref, (err or "")[:160]))
        # list-objects-v2 with --output text gives one key per line, and "None" if the
        # prefix is empty (not a key: it is the CLI's way of saying the query returned
        # nothing).
        for line in listing.splitlines():
            key = line.strip()
            if key and key != "None" and not key.endswith("manifest.json"):
                real.add(key)
    return real


def read_manifest(key, tmp):
    """(etag, objects) of the manifest currently in S3. Empty etag if it does not exist.

    The ETag is the compare-and-swap witness. The head-object was already happening, but
    result was used only as an "exists or not" boolean: it threw away precisely the datum
    that allows writing afterwards without clobbering anyone.
    """
    rc, out, _ = aws("s3api", "head-object", "--bucket", BUCKET, "--key", key, raw=True)
    if rc != 0:
        return "", []
    try:
        etag = json.loads(out).get("ETag") or ""
    except ValueError:
        etag = ""
    rc, _, err = aws("s3", "cp", "s3://%s/%s" % (BUCKET, key), tmp,
                     "--only-show-errors", raw=True)
    if rc != 0:
        # It exists but cannot be read. Writing over it would replace a manifest
        # good one with a blindly rebuilt one: it aborts and nothing is touched.
        die("the manifest %s exists and could not be read (%s): it is left alone."
            % (key, err[:200]))
    try:
        return etag, json.load(open(tmp)).get("objetos", [])
    except Exception:
        # Corrupt JSON: rebuilding it from the bucket listing is the only option,
        # but it is said out loud, because the descriptions and notes are lost.
        sys.stderr.write("s3v: warning — %s is not valid JSON; rebuilding from the "
                         "bucket listing (descriptions are lost)\n" % key)
        return etag, []


def merge_entries(project, prev, fresh, real):
    """Reconcile what was read with what S3 says is there and what we just uploaded.

    Read-modify-write over a shared key LOSES updates: if two sessions (or two machines)
    upload at once, the second writes over a
    manifest it read before the first one added its own, and that entry vanishes
    silently. Here it is reconciled against what S3 **actually** says is there: the bucket
    listing wins over whatever we had read.
    """
    # A copy: this is redone on every CAS attempt, and mutating what was read would drag
    # the previous attempt's entries into the next one.
    prev = [dict(o) for o in prev]
    real = set(real)
    vistas = {o["clave"] for o in prev}
    for k, desc, size, dg, note, kind in fresh:
        real.add(k)
        if k in vistas:
            continue
        prev.append({"clave": k, "descripcion": desc, "bytes": size, "sha256": dg,
                     "nota": note, "tipo": kind, "subido": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                                        time.gmtime())})
        vistas.add(k)

    # What is in S3 and the manifest does not mention: another session added it while we
    # had ours read. It is recovered rather than deleted on rewrite.
    for k in sorted(real - vistas):
        prev.append({"clave": k, "descripcion": "(recovered from the bucket listing)",
                     "bytes": None, "sha256": None, "nota": None, "tipo": None,
                     "subido": None})
    # And whatever the manifest cites but no longer exists is marked, not invented. The mark
    # it is REMOVED if the object comes back: since it was only ever set, a re-uploaded
    # file stayed
    # declared absent forever.
    for o in prev:
        if o["clave"] not in real:
            o["ausente"] = True
        else:
            o.pop("ausente", None)
    return {"proyecto": project, "actualizado": time.strftime("%Y-%m-%d"), "objetos": prev}


def write_manifest(project, fresh):
    """One index per project INSIDE S3, so the relations can be rebuilt even without the
    git vault at hand.

    It is written with compare-and-swap: only if the manifest is still the one we read
    (--if-match with its ETag) or if it genuinely did not exist (--if-none-match *).
    `aws s3 cp` accepts neither condition, which is why this drops down to
    `s3api put-object`.
    """
    key = "proyectos/%s/manifest.json" % project
    # The PID goes in the name because the path used to be fixed: two simultaneous `put`s
    # on the same project shared /tmp/s3v-manifest-<p>.json and the second read or deleted
    # the
    # first one's file halfway through the upload.
    tmp = os.path.join("/tmp", "s3v-manifest-%s-%d.json" % (project, os.getpid()))
    try:
        for attempt in range(CAS_ATTEMPTS):
            etag, prev = read_manifest(key, tmp)
            try:
                reales = real_objects(project)
            except S3Unknown as e:
                # Without knowing what is really in the bucket, any manifest we wrote
                # would be a lie about what is missing. The files are already uploaded and
                # anchored: the only thing lost is the index, and it
                # rebuilt on the next upload.
                print("manifest for %s NOT updated: %s" % (project, e))
                print("  (the files ARE uploaded and anchored in the note)")
                return -1
            doc = merge_entries(project, prev, fresh, reales)
            with open(tmp, "w") as fh:
                json.dump(doc, fh, ensure_ascii=False, indent=1)
            cond = ["--if-match", etag] if etag else ["--if-none-match", "*"]
            rc, _, err = aws("s3api", "put-object", "--bucket", BUCKET, "--key", key,
                             "--body", tmp, *cond, raw=True)
            if rc == 0:
                return len(doc["objetos"])
            if not any(m in err for m in CAS_LOST):
                die("could not write the manifest for %s: %s" % (project, err[:300]))
            time.sleep(0.2 * (attempt + 1))     # someone else won the race: reread and retry
        # Never fall back to an unconditional write: that would turn "the manifest was
        # not written" into "I overwrote someone else's with a worse one", which is the
        # failure the CAS came to prevent. It aborts and says what DID get done.
        die("the manifest of %s changed under our feet %d times in a row: nothing is "
            "written.\n    The files ARE uploaded and anchored in the note; "
            "repeat the `put` to rebuild the manifest." % (project, CAS_ATTEMPTS))
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


# ------------------------------------------------------------------ acciones
def cmd_put(a):
    if a.kind not in KINDS:
        die("--kind must be one of: %s" % ", ".join(KINDS))
    note_path(a.to)
    entries, for_manifest = [], []
    for f in a.file:
        if not os.path.isfile(f):
            die("does not exist: %s" % f)
        size, dg = os.path.getsize(f), sha256(f)
        k = key(a.project, a.kind, os.path.basename(f), a.date, dg)
        # the hash and the note travel with the object: they survive without the vault
        aws("s3", "cp", f, "s3://%s/%s" % (BUCKET, k), "--only-show-errors",
            "--metadata", "sha256=%s,nota=%s" % (dg, a.to.replace("/", "|")))
        desc = a.caption or os.path.basename(f)
        entries.append((k, desc, size, dg))
        for_manifest.append((k, desc, size, dg, a.to, a.kind))
        print("uploaded %s  (%s)" % (k, human(size)))
    n = anchor(a.to, entries)
    # The anchoring is announced BEFORE touching the manifest: manifest() aborts the
    # process if it cannot win the compare-and-swap, and in the previous order the user
    # without knowing the note had in fact been written.
    print("anchored in %s (%d new reference(s))" % (a.to, n))
    print("manifest for %s: %d objects" % (a.project, write_manifest(a.project, for_manifest)))


def cmd_ls(a):
    """A project lives under TWO prefixes, and `--project` listed only one.

    `key()` sends deliverables and intermediates to `proyectos/<p>/` but material to
    `material/<p>/`. Listing only the first hid every piece of source material a project
    had — the same asymmetry that once made the manifest declare it all `ausente`.

    `aws s3 ls` also returns rc=1 on an empty prefix, indistinguishable from a denial, so
    the `(empty)` branch below was unreachable and a fresh slug aborted instead.
    """
    prefixes = (["proyectos/%s/" % a.project, "material/%s/" % a.project]
                if a.project else [""])
    rows, total = [], 0
    for pref in prefixes:
        rc, out, err = aws("s3", "ls", "s3://%s/%s" % (BUCKET, pref),
                           "--recursive", "--human-readable", raw=True)
        if rc != 0 and (err or "").strip():
            die("could not list %s: %s" % (pref, (err or "").strip()[:200]))
        rows.extend(l.split(None, 4) for l in (out or "").splitlines())
    for f in rows:
        if len(f) >= 5:
            print("  %-10s %-9s %s" % (f[0], f[2] + " " + f[3], f[4]))
            total += 1
    if not total:
        print("(empty)")
        return
    print("\n%d object(s)" % total)


def variant(key):
    """The same key with the sha256 in the name, if there is exactly one candidate.

    A safety net for the keys notes already cited before `key()` gained the hash: if
    the literal one is missing, the object may live today at `<name>-<sha8>.<ext>`. It is
    only used after a 404, so it costs nothing on the normal path. With several
    candidates nothing is chosen: they are different contents and
    guessing would be worse than failing.
    """
    raiz, ext = os.path.splitext(key)
    _, listing, _ = aws("s3", "ls", "s3://%s/%s-" % (BUCKET, raiz), "--recursive",
                        raw=True)
    pat = re.compile(r"^%s-[0-9a-f]{8}%s$" % (re.escape(raiz), re.escape(ext)))
    cands = [p[3] for p in (l.split(None, 3) for l in listing.splitlines())
             if len(p) >= 4 and pat.match(p[3])]
    return cands[0] if len(cands) == 1 else None


def cmd_get(a):
    dest = os.path.join(a.out or os.getcwd(), os.path.basename(a.key))
    rc, _, err = aws("s3", "cp", "s3://%s/%s" % (BUCKET, a.key), dest,
                     "--only-show-errors", raw=True)
    if rc != 0:
        alt = variant(a.key) if any(m in err for m in NOT_FOUND) else None
        if not alt:
            die("could not download %s: %s" % (a.key, err[:300]))
        sys.stderr.write("s3v: %s is not there; downloading %s\n" % (a.key, alt))
        aws("s3", "cp", "s3://%s/%s" % (BUCKET, alt), dest, "--only-show-errors")
    print("downloaded: %s (%s)" % (dest, human(os.path.getsize(dest))))


def cmd_url(a):
    # Argument validation first: it costs nothing and must not need a round-trip to AWS.
    # `presign` signs LOCALLY, so an out-of-range expiry is never rejected by the CLI —
    # it emits a link that 403s the moment anyone opens it. SigV4 caps it at 7 days.
    if not 1 <= a.min <= PRESIGN_MAX_MIN:
        die("--min must be between 1 and %d minutes (7 days); got %d"
            % (PRESIGN_MAX_MIN, a.min))
    # `presign` signs LOCALLY: it does not talk to AWS and always returns rc=0, so on
    # this path the credential is never exercised and the Access Key ID cache is never
    # invalidated. After rotating the key in the 1Password item, this would keep signing links
    # with the old ID —good-looking links that give 403 on opening, which is the worst
    # way to fail—. It is checked beforehand with a cheap call that DOES go to AWS.
    rc, _, err = aws("s3api", "head-object", "--bucket", BUCKET, "--key", a.key,
                     raw=True)
    if rc != 0 and any(m in (err or "") for m in CRED_REJECTED):
        _refresh_key_id()
        rc, _, err = aws("s3api", "head-object", "--bucket", BUCKET, "--key", a.key,
                         raw=True)
    if rc != 0:
        die("cannot sign %s: %s" % (a.key, (err or "")[:200]))
    print(aws("s3", "presign", "s3://%s/%s" % (BUCKET, a.key),
              "--expires-in", str(a.min * 60)))


def coordination_lifecycle():
    """Are the rules that stop coordination objects piling up in place?

    The bucket is versioned, and the objects under `locks/` and `presencia/` are rewritten
    every few minutes: each renewal leaves a permanent noncurrent version. The rule that
    already existed (`versiones-antiguas-a-IA`) moves them to STANDARD_IA at 60 days, but
    never deletes them, and at 300 bytes they do not even reach the 128K threshold. That is:
    rubbish that grows slowly and forever. It is checked here and not in the harness
    because this needs the network, and the harness has to pass without it.
    """
    rc, out, err = aws("s3api", "get-bucket-lifecycle-configuration",
                       "--bucket", BUCKET, raw=True)
    if rc != 0:
        return None, (err or "").strip()[:150]
    try:
        reglas = json.loads(out).get("Rules", [])
    except ValueError:
        return None, "unreadable response"
    missing = []
    for pref in COORD_PREFIXES:
        ok = any((r.get("Filter") or {}).get("Prefix") == pref
                 and r.get("Status") == "Enabled"
                 and (r.get("NoncurrentVersionExpiration") or {}).get("NoncurrentDays")
                 for r in reglas)
        if not ok:
            missing.append(pref)
    return missing, ""


def cmd_check(a):
    """References in notes that no longer exist in S3, and objects nobody cites."""
    cited = {}
    for root, dirs, files in os.walk(B.VAULT):
        dirs[:] = [d for d in dirs if not d.startswith((".", "_")) or d == "_assets"]
        for fn in files:
            if not fn.endswith(".md"):
                continue
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, B.VAULT)
            for m in re.finditer(r'`((?:proyectos|material)/[^`]+)`', open(full, errors="replace").read()):
                ref = m.group(1)
                # A folder prefix (`material/my-project/`) is not an object: the
                # notes cite them to explain the layout, not to point at
                # a file. Marking them broken turns the check into noise.
                if ref.endswith("/"):
                    continue
                cited.setdefault(ref, []).append(rel)
    out = aws("s3", "ls", "s3://%s/" % BUCKET, "--recursive")
    en_s3 = {l.split(None, 3)[3] for l in out.splitlines() if len(l.split(None, 3)) >= 4}
    # A key with `<` or `{` is a documentation PLACEHOLDER, not a reference:

    # `proyectos/<p>/manifest.json` in a note explaining the format came out

    # as a broken reference and made `check` exit with code 1.

    cited = {k: v for k, v in cited.items()

               if not any(c in k for c in "<>{}")}
    broken = sorted(k for k in cited if k not in en_s3)
    # `locks/` and `presencia/` are COORDINATION STATE, not content: no note
    # cites them nor should, and they all came out as orphans — a warning that cannot be
    # acted on and that ends up teaching you to ignore the whole list.
    COORD = COORD_PREFIXES
    orphans = sorted(k for k in en_s3
                       if k not in cited and not k.endswith("manifest.json")
                       and not k.startswith(COORD))
    print("objects in S3: %d   cited by notes: %d" % (len(en_s3), len(cited)))
    print("\nbroken references (the note cites something no longer there): %d" % len(broken))
    for k in broken[:10]:
        print("  %s  ← %s" % (k, ", ".join(cited[k])))
    print("\norphans (in S3 but nobody cites them): %d" % len(orphans))
    for k in orphans[:10]:
        print("  %s" % k)
    missing, err = coordination_lifecycle()
    if err:
        print("\ncould not check the bucket lifecycle: %s" % err)
    elif missing:
        print("\nMISSING lifecycle rule for: %s" % ", ".join(missing))
        print("  Without it, every presence or lease renewal leaves a permanent version")
        print("  permanently in the bucket. NoncurrentVersionExpiration is needed.")
    else:
        print("\ncoordination lifecycle: locks/ and presencia/ purge versions at 1 day")

    return 1 if (broken or orphans) else 0


# -------------------------------------------------------------------- arranque
def access_key_id(cache=True):
    """The Access Key ID comes from the 1Password item entry's UserName field, not from the code.

    That way no AWS identifier is left in the repository (the secret scanner would block
    it, and rightly so) and rotating the key means changing only the 1Password item.

    It is cached in STATE because asking the 1Password item costs a WHOLE secret.py invocation per
    command — measured at 0.47 s with the master already cached, and considerably more
    with the 1Password item cold on the network mount — against an `s3v.py ls` that takes 1.5 s in
    total. What is cached is the UserName, NEVER the secret, and STATE is outside the
    repository. If the ID stops working, _refresh_key_id() deletes the file and comes back
    here.
    """
    if cache:
        try:
            guardado = open(CACHE_KEY_ID).read().strip()
        except OSError:
            guardado = ""
        # A half-truncated file (or one edited by hand) would poison the environment with
        # an invalid ID and the AWS error would not say where it came from: only what
        # has the shape of an Access Key ID.
        if re.match(r"^[A-Z0-9]{16,128}$", guardado):
            return guardado
    # Prefer the standard AWS environment; fall back to the 1Password reference.
    kid = os.environ.get("AWS_ACCESS_KEY_ID", "").strip()
    if not kid:
        kid = subprocess.run([sys.executable, SECRET, "get", SECRET_ID_REF, "--show"],
                             capture_output=True, text=True, timeout=60).stdout.strip()
    if re.match(r"^[A-Z0-9]{16,128}$", kid):
        try:
            B.atomic_write(CACHE_KEY_ID, kid + "\n")
            os.chmod(CACHE_KEY_ID, 0o600)
        except Exception:
            pass        # without the cache it still works: only the saving is lost
        return kid
    die("could not read the Access Key ID (set $AWS_ACCESS_KEY_ID or %s)" % SECRET_ID_REF, 4)


def worker():
    """Second pass: the secret arrives on stdin from secret.py."""
    secret = sys.stdin.readline().strip()
    if not secret:
        die("no secret arrived on stdin", 4)
    os.environ.update({"AWS_ACCESS_KEY_ID": access_key_id(),
                       "AWS_SECRET_ACCESS_KEY": secret,
                       "AWS_DEFAULT_REGION": REGION})
    sys.argv = [sys.argv[0]] + sys.argv[2:]
    sys.exit(main(directo=True) or 0)


def main(directo=False):
    import argparse
    p = argparse.ArgumentParser(prog="s3v", description="the vault's file store, in S3")
    sub = p.add_subparsers(dest="cmd", required=True)

    q = sub.add_parser("put", help="uploads files and anchors them to a note")
    q.add_argument("file", nargs="+")
    q.add_argument("--to", required=True, help="note that explains them (path relative to the vault)")
    q.add_argument("--project", required=True, help="project slug")
    q.add_argument("--kind", default="entregable", help="entregable | intermedio | material")
    q.add_argument("--caption", help="shared description")
    q.add_argument("--date", help="folder date (defaults to today)")
    q.set_defaults(fn=cmd_put)

    q = sub.add_parser("ls", help="what is stored")
    q.add_argument("--project")
    q.set_defaults(fn=cmd_ls)

    q = sub.add_parser("get", help="downloads an object")
    q.add_argument("key"); q.add_argument("--out")
    q.set_defaults(fn=cmd_get)

    q = sub.add_parser("url", help="temporary signed link")
    q.add_argument("key"); q.add_argument("--min", type=int, default=60)
    q.set_defaults(fn=cmd_url)

    q = sub.add_parser("check", help="broken references and orphaned objects")
    q.set_defaults(fn=cmd_check)

    a = p.parse_args()
    if not directo:
        # re-execute through secret.py to receive the secret on stdin
        cmd = "%s %s __worker %s" % (sys.executable, os.path.abspath(__file__),
                                     " ".join(map(_q, sys.argv[1:])))
        os.execv(sys.executable, [sys.executable, SECRET, "get", SECRET_REF, "--pipe", cmd])
    return a.fn(a)


def _q(s):
    return "'" + s.replace("'", "'\\''") + "'"


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "__worker":
        worker()
    main()
