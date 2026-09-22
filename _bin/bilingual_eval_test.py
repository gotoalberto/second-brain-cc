#!/usr/bin/env python3
"""Tests for bilingual_eval: how a (Spanish, English) pair is judged, and how real misses turn
into glossary candidates. Pure: the retrieval is a fake `ask`, the vault lookup a fake
predicate, so no index, no subprocess and no database are needed. Run standalone:

    python3 _bin/bilingual_eval_test.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import bilingual_eval as E

ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def test_classify():
    a, b = "30-Knowledge/a.md", "30-Knowledge/b.md"
    check("nothing on either side is a vault gap, not a failure", E.classify(set(), set()) == "gap")
    check("Spanish empty while English finds notes is MUTE", E.classify(set(), {a}) == "mute")
    check("no shared note is DISJOINT", E.classify({a}, {b}) == "disjoint")
    check("one shared note is a pass", E.classify({a, b}, {b}) == "ok")
    check("Spanish finding what English misses is not a bridge failure", E.classify({a}, set()) == "ok")


def test_score_with_fake_retrieval():
    answers = {
        "es-pass": {"n/a.md", "n/b.md"}, "en-pass": {"n/b.md"},
        "es-mute": set(), "en-mute": {"n/c.md"},
        "es-disjoint": {"n/d.md"}, "en-disjoint": {"n/e.md"},
        "es-gap": set(), "en-gap": set(),
    }
    calls = []

    def ask(prompt, side, i):
        calls.append((side, i))
        return answers[prompt]

    pairs = [("es-pass", "en-pass"), ("es-mute", "en-mute"),
             ("es-disjoint", "en-disjoint"), ("es-gap", "en-gap")]
    rows, s = E.score(pairs, ask)
    check("every pair gets a verdict in order", [r[3] for r in rows] == ["ok", "mute", "disjoint", "gap"],
          [r[3] for r in rows])
    check("both sides are asked, tagged by side and index",
          calls == [("es", 0), ("en", 0), ("es", 1), ("en", 1), ("es", 2), ("en", 2), ("es", 3), ("en", 3)], calls)
    check("failures are the mute and the disjoint pairs only",
          s["fails"] == [("mute", "es-mute"), ("disjoint", "es-disjoint")], s["fails"])
    check("the gap is reported apart from the failures", s["gaps"] == ["es-gap"], s["gaps"])
    check("parity is Spanish notes over English notes", (s["tot_es"], s["tot_en"]) == (3, 3)
          and round(s["parity"]) == 100, s)
    rows, s = E.score([], ask)
    check("an empty set scores without dividing by zero", s["parity"] == 0.0 and not s["fails"], s)


def test_paths_in_context():
    ctx = "## Memory\n- `30-Knowledge/x.md` (decision) and (10-Projects/y.md), plus text.md, not a.txt"
    check("paths are read out of a retrieval block",
          E.paths_in_context(ctx) == {"30-Knowledge/x.md", "10-Projects/y.md", "text.md"}, E.paths_in_context(ctx))
    check("an empty block names nothing", E.paths_in_context("") == set())


def test_miss_candidates():
    extras = ["best=0.20 threshold=0.60 terms=instala,system,[REDACTED:jwt]",
              "field=prompt terms=instala,kubernetes",
              "field=prompt continuation terms=codigo",
              "pointer_only=0 campo=prompt"]
    seen = E.miss_terms(extras)
    check("terms are counted across misses", seen == {"instala": 2, "system": 1, "kubernetes": 1, "codigo": 1}, seen)
    reach = E.glossary_reach({"codigo": "code", "guardan": "save store"})
    check("a multi-sense glossary value reaches every sense", reach == {"code", "save", "store"}, reach)
    cands = E.miss_candidates(seen, reach | {"codigo"}, {"que"}, lambda t: t == "system")
    check("terms the vault knows or the glossary reaches drop out, most missed first",
          cands == [("instala", 2), ("kubernetes", 1)], cands)


def test_sets_are_honest():
    fitted = {es for es, _ in E.FITTED}
    held = {es for es, _ in E.HELD_OUT}
    check("no question is in both sets", not (fitted & held), fitted & held)
    check("every pair has two non-empty sides",
          all(es and en and es != en for es, en in E.FITTED + E.HELD_OUT))
    # Bridging these to make the held-out set pass would spend it: write new questions instead.
    for w in ("instala", "programadas", "publica", "idioma", "salida", "entregan"):
        check("held-out word %r has no glossary entry" % w, w not in E.B.GLOSARIO)


def main():
    for t in (test_classify, test_score_with_fake_retrieval, test_paths_in_context,
              test_miss_candidates, test_sets_are_honest):
        print("\n== %s ==" % t.__name__)
        try:
            t()
        except Exception as exc:
            check("%s ran without raising" % t.__name__, False, repr(exc))
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
