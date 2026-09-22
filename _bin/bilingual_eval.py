#!/usr/bin/env python3
"""Does a question in Spanish find what its English twin finds?

The vault is written in English and some of its users are not. That combination can mute
retrieval silently: an unbridged Spanish term matches no note, so it adds nothing to the
FTS query and pure weight to the coverage denominator, and the real terms beside it fall
under the threshold. The prompt is searched and its answer is discarded, with no error.
Spanish is the example language because it is the one `brainlib.GLOSARIO` bridges.

    bilingual_eval.py               the two built-in sets, then the real misses
    bilingual_eval.py --held-out    only the set the glossary was NOT built from
    bilingual_eval.py --verbose     show the notes both sides surfaced
    bilingual_eval.py --from-misses only the glossary candidates learned from real misses

Reading it: a pair FAILS if the Spanish side surfaces nothing while its twin does (MUTE),
or if the two share no note at all (DISJOINT). Note COUNT alone is not a pass: a Spanish
question about where files are stored once returned nine notes, none of them about files.

Zero on BOTH sides is not a failure here. It is a gap in the vault, and it is reported
separately so it cannot be mistaken for a bridge problem.

The two sets, and why they are kept apart:

  FITTED    questions like these are what the glossary's second and third passes were built
            from, so their key terms are bridged on purpose (`contexto`, `arranque`,
            `presupuesto`, `consulta`, `aislamiento`, `aisla`, `comprometida`, `binarios`,
            `equipos`, `ficheros`, `guardan`, `reglas`, `codigo`). They measure REGRESSION only.
  HELD_OUT  written against this vault's own notes after the glossary, and never used to
            extend it. Words such as `instala`, `programadas`, `publica`, `idioma`, `salida`
            or `entregan` have no entry on purpose. This is the honest number, and it is
            spent the moment you extend the glossary to make it pass: write new questions
            instead, or better, read `--from-misses`.

See 30-Knowledge/2026-08-27-decision-bilingual-retrieval-measured-not-assumed.md
"""
import os, sys, json, time, hashlib, argparse, subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B

RETRIEVE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "retrieve.py")

# Built WITH the glossary: these shaped it, so they measure regression, not generalisation.
FITTED = [
    ("que pasa si dos maquinas escriben a la vez en el vault",
     "what happens if two machines write to the vault at once"),
    ("donde se guardan los ficheros del vault", "where are the vault files stored"),
    ("como se gestionan las credenciales y contraseñas",
     "how are credentials and passwords managed"),
    ("por que la memoria se consulta en cada prompt",
     "why is memory queried on every prompt"),
    ("como funciona el aislamiento con worktrees", "how does worktree isolation work"),
    ("que hago si el arnes de pruebas falla", "what do I do if the test harness fails"),
    ("como se escriben las notas del vault sin romper nada",
     "how are vault notes written without breaking anything"),
    ("cual es el presupuesto del contexto de arranque",
     "what is the startup context budget"),
    ("como se decide el umbral de relevancia", "how is the relevance threshold decided"),
    ("como se sincroniza el vault entre equipos", "how does the vault sync between machines"),
    ("como se rota una credencial comprometida", "how is a compromised credential rotated"),
    ("por que las notas no se borran nunca", "why are notes never deleted"),
    ("cual es la politica de imagenes y binarios",
     "what is the policy for images and binaries"),
    ("como se aisla el trabajo de cada tarea", "how is each task's work isolated"),
    ("que reglas hay para escribir codigo", "what rules are there for writing code"),
]

# HELD OUT: written after the glossary, never used to extend it. This is the honest number.
HELD_OUT = [
    ("como se instala el sistema en una maquina nueva",
     "how is the system installed on a new machine"),
    ("que tareas programadas corren en cada maquina",
     "which scheduled tasks run on each machine"),
    ("por que un agente no ejecuta scripts que piden un secreto",
     "why does an agent not run scripts that ask for a secret"),
    ("como se publica algo en un repositorio publico",
     "how is something published to a public repo"),
    ("que idioma se usa para escribir el vault", "which language is the vault written in"),
    ("como se comprueba el efecto y no el codigo de salida",
     "how do we check the effect and not the exit code"),
    ("como se entregan los informes al usuario", "how are reports delivered to the user"),
    ("que hace el guardian cuando un gancho deja de funcionar",
     "what does the guardian do when a hook stops working"),
    ("como se conecta una cuenta de google", "how is a google account connected"),
    ("que se hace cuando una busqueda no encuentra nada",
     "what do we do when a search finds nothing"),
]

MISS_EVENTS = ("no-hits", "below-threshold")


# ------------------------------------------------------------------ pure logic
def classify(pes, pen):
    """One pair's verdict from the notes each side surfaced: 'ok', 'gap', 'mute' or 'disjoint'.

    Only the Spanish side can fail. English finding nothing while Spanish finds something is
    not a bridge problem, and nothing on either side is a gap in the vault."""
    if not pes and not pen:
        return "gap"
    if not pes:
        return "mute"
    if pen and not (pes & pen):
        return "disjoint"
    return "ok"


MARKS = {"ok": "ok", "gap": "gap in the vault (both languages)",
         "mute": "MUTE IN SPANISH", "disjoint": "DISJOINT"}


def score(pairs, ask):
    """Ask both sides of every pair through `ask(prompt, side, index) -> set of paths`.

    Returns (rows, summary). A row is (es, pes, pen, verdict); the summary counts failures
    (mute or disjoint), vault gaps and the note totals behind the parity figure."""
    rows = []
    for i, (es, en) in enumerate(pairs):
        pes, pen = set(ask(es, "es", i)), set(ask(en, "en", i))
        rows.append((es, pes, pen, classify(pes, pen)))
    fails = [(r[3], r[0]) for r in rows if r[3] in ("mute", "disjoint")]
    gaps = [r[0] for r in rows if r[3] == "gap"]
    tot_es = sum(len(r[1]) for r in rows)
    tot_en = sum(len(r[2]) for r in rows)
    return rows, {"fails": fails, "gaps": gaps, "tot_es": tot_es, "tot_en": tot_en,
                  "parity": 100.0 * tot_es / max(tot_en, 1)}


def paths_in_context(ctx):
    """The note paths a retrieval block names."""
    return {s.strip("`,()") for s in (ctx or "").split() if s.strip("`,()").endswith(".md")}


def miss_terms(extras):
    """Count the terms recorded on retrieval misses (`terms=a,b,c` in a metric's extra)."""
    seen = {}
    for extra in extras:
        for chunk in (extra or "").split("terms=")[1:]:
            for t in chunk.split(" ")[0].split(","):
                t = t.strip()
                if t and not t.startswith("[REDACTED"):
                    seen[t] = seen.get(t, 0) + 1
    return seen


def miss_candidates(seen, reach, stop, vault_knows):
    """Missed terms the vault has never used AND no glossary value reaches, most missed first.

    `vault_knows(term)` says whether any note contains the term. A term that passes is
    evidence of one of three things: a Spanish word wanting a glossary entry, a proper noun
    wanting nothing, or a subject the vault lacks, which wants a note."""
    out = []
    for t, n in sorted(seen.items(), key=lambda kv: (-kv[1], kv[0])):
        if t in reach or t in stop or vault_knows(t):
            continue
        out.append((t, n))
    return out


def glossary_reach(glossary):
    reach = set()
    for v in glossary.values():
        reach.update(v.split())
    return reach


# ------------------------------------------------------------------ adapters
def _sid(tag, i, run):
    """A fresh id per RUN. retrieve.py dedups notes already injected to a sid and raises
    that sid's threshold on misses, so reusing ids measures the dedup, not the retrieval.
    That is exactly how this eval first fooled itself."""
    return (tag + hashlib.sha1(("%s-%d" % (run, i)).encode()).hexdigest())[:8]


def _wipe(sids):
    """Forget everything the eval's own sessions left behind, metrics included, so its
    invented questions never show up later as real misses in `--from-misses`."""
    con = B.db()
    for s in sids:
        for t in ("injected", "lastprompt", "sessions", "claims", "vault_writes", "metrics"):
            try:
                con.execute("DELETE FROM %s WHERE sid=?" % t, (B.sid8(s),))
            except Exception:
                pass
        try:
            os.remove(os.path.join(B.STATE, "%s.threshold" % B.sid8(s)))
        except OSError:
            pass
    con.commit(); con.close()


def ask_retrieve(prompt, sid):
    """Run the real UserPromptSubmit hook on `prompt` and return the note paths it injected."""
    p = subprocess.run([sys.executable, RETRIEVE], timeout=30,
                       input=json.dumps({"session_id": sid, "prompt": prompt,
                                         "cwd": os.path.expanduser("~"),
                                         "hook_event_name": "UserPromptSubmit"}).encode(),
                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    out = p.stdout.decode().strip()
    if not out:
        return set()
    try:
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    except Exception:
        return set()
    return paths_in_context(ctx)


def run(pairs, label, run_id, verbose=False):
    sids = [_sid(t, i, run_id) for i in range(len(pairs)) for t in ("es", "en")]
    _wipe(sids)
    print("\n== %s (%d pairs) ==" % (label, len(pairs)))
    try:
        rows, s = score(pairs, lambda prompt, side, i: ask_retrieve(prompt, _sid(side, i, run_id)))
    finally:
        _wipe(sids)
    for es, pes, pen, verdict in rows:
        print("  %-50s es=%-2d en=%-2d shared=%-2d %s"
              % (es[:50], len(pes), len(pen), len(pes & pen), MARKS[verdict]))
        if verbose:
            for p in sorted(pes & pen):
                print("        both: %s" % p)
    print("  --")
    print("  failures: %d of %d   parity: %.0f%%   vault gaps: %d"
          % (len(s["fails"]), len(pairs), s["parity"], len(s["gaps"])))
    for verdict, es in s["fails"]:
        print("    %s: %s" % (verdict.upper(), es))
    return len(s["fails"])


def from_misses(days=30, limit=40):
    """Glossary candidates learned from REAL misses, not invented questions.

    An invented held-out set is spent the moment its results are known: the next glossary
    extension fits to it, and the number stops meaning anything. The user's own questions
    are an inexhaustible and honest source. retrieve.py records the TERMS of every
    `no-hits` and `below-threshold` miss in the metrics table, scrubbed of credentials.
    """
    con = B.db()
    since = B.now() - days * 86400
    extras = [r[0] for r in con.execute(
        "SELECT extra FROM metrics WHERE ts > ? AND event IN (%s) AND extra LIKE '%%terms=%%'"
        % ",".join("?" * len(MISS_EVENTS)), (since,) + MISS_EVENTS)]

    def vault_knows(t):
        try:
            return con.execute("SELECT 1 FROM notes_fts WHERE notes_fts MATCH ? LIMIT 1",
                               ('"%s"' % t.replace('"', ""),)).fetchone() is not None
        except Exception:
            return True       # unsearchable term: do not claim it is a gap

    cands = miss_candidates(miss_terms(extras), glossary_reach(B.GLOSARIO), B.STOP, vault_knows)
    con.close()
    print("\n== terms that missed, over the last %d days ==" % days)
    if not cands:
        print("  nothing the vault does not know and the glossary cannot reach.")
        print("  (a miss is not automatically a gap: the vault may simply not cover it)")
        return 0
    print("  %d term(s) the vault has never seen and no Spanish word bridges:" % len(cands))
    for t, n in cands[:limit]:
        print("    %-24s missed %d time(s)" % (t, n))
    print("  A Spanish word here wants a GLOSARIO entry in brainlib.py; a proper noun wants")
    print("  nothing; a real subject the vault lacks wants a NOTE, not a glossary entry.")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="bilingual_eval.py", description=__doc__.splitlines()[0])
    ap.add_argument("--held-out", action="store_true",
                    help="only the set the glossary was NOT built from")
    ap.add_argument("--verbose", action="store_true", help="list the shared notes")
    ap.add_argument("--from-misses", action="store_true",
                    help="only the glossary candidates learned from real misses")
    ap.add_argument("--days", type=int, default=30)
    a = ap.parse_args(argv)
    if not B.enabled():
        print("vault unavailable"); return 0
    if a.from_misses:
        return from_misses(a.days)
    run_id = "%d" % int(time.time())
    bad = 0
    if not a.held_out:
        bad += run(FITTED, "fitted set, measures regression", run_id, a.verbose)
    bad += run(HELD_OUT, "held-out set, measures generalisation", run_id, a.verbose)
    print("\n%s" % ("all pairs agree" if not bad else "%d pair(s) disagree" % bad))

    # Both sets above are hand-written, so they measure the bridge only where somebody
    # thought to look. A green run means "the questions we invented still pass", never
    # "the bridge works". So the real evidence always runs too, never as a separate opt-in.
    print("\n  the pairs above are hand-written: they measure the bridge on questions somebody")
    print("  thought of. What users actually asked and missed is below, and that is the only")
    print("  part of this report that can find an unknown gap.")
    from_misses(a.days)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
