#!/usr/bin/env python3
"""Tests for files_core — the rules of the local file store.

Pure: every input is passed in, nothing on disk is read or written. Run standalone:

    python3 _bin/files_core_test.py
"""
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

ok, fail = [], []
NOW = dt.datetime(2026, 9, 15, 18, 0, 0)
DG = "0123456789abcdef" * 4


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def raises(fn, *args):
    try:
        fn(*args)
    except ValueError:
        return True
    return False


def test_keys(F):
    print("\n== key layout ==")
    check("the kinds are deliverable, intermediate and material", F.KINDS == ("deliverable", "intermediate", "material"))
    got = F.key("demo", "deliverable", "report.pdf", "2026-09-15", DG)
    check("a deliverable goes under <project>/<date>/<kind>/ with the sha256 fragment in its name",
          got == "demo/2026-09-15/deliverable/report-01234567.pdf", got)
    got = F.key("demo", "intermediate", "draft.md", "2026-09-15")
    check("without a digest the name is kept as it is", got == "demo/2026-09-15/intermediate/draft.md", got)
    got = F.key("demo", "material", "source.csv", "2026-09-15", DG)
    check("material has no date: <project>/material/<name>", got == "demo/material/source-01234567.csv", got)
    check("material needs no date at all", F.key("demo", "material", "a.txt", None) == "demo/material/a.txt")
    check("the same content always lands on the same key",
          F.key("demo", "deliverable", "r.pdf", "2026-09-15", DG) == F.key("demo", "deliverable", "r.pdf", "2026-09-15", DG))
    check("two contents with one name get two keys",
          F.key("demo", "deliverable", "r.pdf", "2026-09-15", DG)
          != F.key("demo", "deliverable", "r.pdf", "2026-09-15", "f" * 64))
    got = F.key("demo", "deliverable", "/tmp/some dir/my report.pdf", "2026-09-15")
    check("only the basename is used, with whitespace turned into a dash",
          got == "demo/2026-09-15/deliverable/my-report.pdf", got)
    check("a name with a backtick cannot break the note's code span",
          "`" not in F.key("demo", "material", "a`b.txt", None))
    check("an unknown kind is refused", raises(F.key, "demo", "entregable", "a.pdf", "2026-09-15"))
    check("a project with a slash is refused", raises(F.key, "a/b", "material", "x", None))
    check("a project of .. is refused", raises(F.key, "..", "material", "x", None))
    check("a deliverable without a valid date is refused", raises(F.key, "demo", "deliverable", "x", "15-09-2026"))
    check("an empty name is refused", raises(F.key, "demo", "material", "", None))
    check("the manifest key is per project", F.manifest_key("demo") == "demo/manifest.json")

    print("\n== key paths ==")
    got = F.key_path("/files", "demo/material/a.txt")
    check("a key maps to a path under the files directory", got == os.path.join("/files", "demo", "material", "a.txt"), got)
    for bad in ("../etc/passwd", "demo/../../x", "/abs/key", "", "demo//a", "demo/./a"):
        check("the key %r is refused" % bad, raises(F.key_path, "/files", bad))

    print("\n== what counts as content ==")
    check("a stored file is content", F.is_content_key("demo/material/a.txt"))
    check("the manifest is not", not F.is_content_key("demo/manifest.json"))
    check("a hidden file is not", not F.is_content_key("demo/material/.DS_Store"))
    check("a half-written copy is not", not F.is_content_key("demo/material/a.txt.tmp.4242"))
    check("human sizes", (F.human(12), F.human(2048), F.human(5 * 1024 * 1024)) == ("12 B", "2.0 KB", "5.0 MB"),
          (F.human(12), F.human(2048), F.human(5 * 1024 * 1024)))


def test_anchor(F):
    print("\n== anchoring in a note ==")
    line_a = F.entry_line("demo/material/a-01234567.txt", "the source\ndata", 2048, DG)
    check("an entry is one line with key, caption, size and a short digest",
          line_a == "- `demo/material/a-01234567.txt` · the source data · 2.0 KB · `0123456789ab`", line_a)
    line_b = F.entry_line("demo/2026-09-15/deliverable/r-01234567.pdf", "report", 10, DG)

    note = "---\ntitle: T\n---\n\n## Context\n\nBody.\n"
    text, added = F.anchor(note, [line_a])
    check("the first anchor creates a ## Files section at the end",
          text.startswith(note.rstrip("\n")) and text.endswith("## Files\n\n%s\n\n%s\n" % (F.HEADER, line_a)) and added == [line_a],
          text)
    check("the header says how to copy a file out", "files.py get <key>" in F.HEADER)
    again, added = F.anchor(text, [line_a])
    check("anchoring the same key again changes nothing", again == text and added == [], again)
    text2, added = F.anchor(text, [line_a, line_b])
    check("a new key joins the existing section, the old one is not repeated",
          added == [line_b] and text2.count("## Files") == 1 and text2.count(line_a) == 1
          and text2.rstrip("\n").endswith(line_b), text2)
    check("the same key twice in one batch is added once",
          F.anchor(note, [line_a, line_a])[1] == [line_a])

    middle = "# N\n\n## Files\n\n%s\n\n%s\n\n## Log\n\n- entry\n" % (F.HEADER, line_a)
    text, added = F.anchor(middle, [line_b])
    check("when ## Files is followed by another section, the line goes inside it, before that section",
          text == "# N\n\n## Files\n\n%s\n\n%s\n%s\n\n## Log\n\n- entry\n" % (F.HEADER, line_a, line_b), text)

    lookalike = "# N\n\n## Files the session produced\n\nprose\n"
    text, added = F.anchor(lookalike, [line_a])
    check("a heading that only starts with ## Files is not the section",
          text.count("\n## Files\n") == 1 and "## Files the session produced\n\nprose\n\n## Files\n" in text, text)

    text, _ = F.anchor("", [line_a])
    check("an empty note gets the section alone", text == "## Files\n\n%s\n\n%s\n" % (F.HEADER, line_a), text)


def test_check(F):
    print("\n== references and orphans ==")
    notes = [
        ("30-Knowledge/a.md", "- `demo/material/a-01234567.txt` · x\n- `demo/2026-09-15/deliverable/r.pdf` · y\n"),
        ("10-Projects/b.md", "See `demo/material/a-01234567.txt` and the layout `demo/material/`.\n"
                             "Placeholders: `<slug>/material/<file>`, `{p}/2026-01-01/deliverable/x`.\n"
                             "Other code: `python3 x.py`, `a/b/c`, `0123456789ab`.\n"),
    ]
    cited = F.cited_keys(notes)
    check("stored-key references are found in every note, each note listed once",
          cited == {"demo/material/a-01234567.txt": ["30-Knowledge/a.md", "10-Projects/b.md"],
                    "demo/2026-09-15/deliverable/r.pdf": ["30-Knowledge/a.md"]}, cited)
    check("a folder prefix is not a reference", "demo/material/" not in cited)
    check("placeholders are not references", not any("<" in k or "{" in k for k in cited))
    check("other code in backticks is not a reference", "a/b/c" not in cited and "python3 x.py" not in cited)

    stored = ["demo/material/a-01234567.txt", "demo/material/stray.bin", "demo/manifest.json",
              "demo/material/.DS_Store", "demo/material/half.pdf.tmp.99"]
    broken, orphans = F.check(cited, stored)
    check("a cited key with no file is broken", broken == ["demo/2026-09-15/deliverable/r.pdf"], broken)
    check("a stored file nobody cites is an orphan; manifests, hidden and partial files are not",
          orphans == ["demo/material/stray.bin"], orphans)
    check("nothing cited and nothing stored is clean", F.check({}, []) == ([], []))

    print("\n== the sha256 variant ==")
    existing = ["demo/material/a-01234567.txt", "demo/material/b-aaaaaaaa.txt", "demo/material/b-bbbbbbbb.txt"]
    check("a key without the fragment finds the one file that has it",
          F.variant("demo/material/a.txt", existing) == "demo/material/a-01234567.txt")
    check("with two candidates nothing is guessed", F.variant("demo/material/b.txt", existing) is None)
    check("with none, None", F.variant("demo/material/c.txt", existing) is None)


def test_manifest(F):
    print("\n== the manifest ==")
    check("no manifest yet is an empty, readable one", F.parse_manifest("") == ([], True))
    check("a corrupt manifest is unreadable", F.parse_manifest("{nope") == ([], False))
    check("a manifest without objects is unreadable", F.parse_manifest('{"project": "demo"}') == ([], False))
    fresh = [("demo/material/a.txt", "source", 10, DG, "30-Knowledge/a.md", "material")]
    doc = F.merge_manifest("demo", [], fresh, [], NOW)
    check("a first store writes one object with its note, kind, digest and time",
          doc == {"project": "demo", "updated": "2026-09-15",
                  "objects": [{"key": "demo/material/a.txt", "description": "source", "bytes": 10, "sha256": DG,
                               "note": "30-Knowledge/a.md", "kind": "material", "stored": "2026-09-15T18:00:00"}]}, doc)
    objects, readable = F.parse_manifest(F.render_manifest(doc))
    check("the manifest round-trips", readable and objects == doc["objects"], objects)

    again = F.merge_manifest("demo", doc["objects"], fresh, ["demo/material/a.txt"], NOW)
    check("storing the same key again adds no object", len(again["objects"]) == 1, again)

    other = F.merge_manifest("demo", doc["objects"], [], ["demo/material/a.txt", "demo/material/z.txt"], NOW)
    check("a file on disk the manifest does not list is recovered, not lost",
          [o["key"] for o in other["objects"]] == ["demo/material/a.txt", "demo/material/z.txt"]
          and other["objects"][1]["description"].startswith("(recovered"), other)

    gone = F.merge_manifest("demo", doc["objects"], [], [], NOW)
    check("a listed file that is no longer on disk is marked missing, not dropped",
          gone["objects"][0].get("missing") is True and len(gone["objects"]) == 1, gone)
    back = F.merge_manifest("demo", gone["objects"], [], ["demo/material/a.txt"], NOW)
    check("and unmarked when it comes back", "missing" not in back["objects"][0], back)
    check("merging does not change what was read", "missing" in gone["objects"][0])

    aware = F.merge_manifest("demo", [], fresh, [], dt.datetime(2026, 9, 15, 18, 0, tzinfo=dt.timezone.utc))
    check("an aware time keeps its offset", aware["objects"][0]["stored"] == "2026-09-15T18:00:00+0000",
          aware["objects"][0]["stored"])
    check("the rendered manifest is JSON", json.loads(F.render_manifest(doc))["project"] == "demo")


def test_purity(F):
    print("\n== purity ==")
    src = open(os.path.join(HERE, "files_core.py")).read()
    for banned in ("import subprocess", "import socket", "urllib", "http.client", "import shutil",
                   "open(", "brainlib", "time.time", "datetime.now"):
        check("files_core does not use %s" % banned, banned not in src)


def main():
    try:
        import files_core as F
    except Exception as exc:
        check("files_core imports", False, "%s: %s" % (type(exc).__name__, exc))
    else:
        for t in (test_keys, test_anchor, test_check, test_manifest, test_purity):
            try:
                t(F)
            except Exception as exc:
                import traceback
                traceback.print_exc()
                check("%s ran to the end" % t.__name__, False, "%s: %s" % (type(exc).__name__, exc))
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
