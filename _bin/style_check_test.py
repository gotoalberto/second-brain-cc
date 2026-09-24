#!/usr/bin/env python3
"""Tests for style_check.py (the document checker) and style_gate.py (the Stop hook).

The phrases in CAUGHT are the shapes that make text read as written by an AI, in English and
Spanish; CLEAN holds ordinary text that must not trip the check (tables with negative numbers,
hyphenated words, verbatim quotes, code, URLs). The gate runs in a subprocess whose HOME,
BRAIN_STATE and BRAIN_VAULT are temporary directories, so nothing reaches the real state.
Run standalone:

    python3 _bin/style_check_test.py
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail and not cond else ""))


CAUGHT = [
    "Son dos preguntas que van juntas. El proyecto necesita más tiempo.",
    "Two questions travel together.",
    "* The ask: a bigger test budget.",
    "* La petición: un presupuesto mayor.",
    "That is the whole idea. The rest is detail, so it is worth reading once.",
    "The service is billed per request, not a flat monthly fee.",
    "It follows the team's own calendar, not a date set from outside.",
    "The trial is short on purpose.",
    "We use a tenth of the quota, so it does not bite.",
    "The roadmap leans on the migration landing.",
    "Hi both \u2014 could we meet on Thursday?",
    "Enero y febrero - el resto del trimestre.",
    "It's not a workaround, it's a proper fix.",
    "El problema no es la velocidad, es la memoria.",
    "La clave: el índice se reconstruye cada noche.",
    "Dicho de otra forma, no hay margen.",
    "Three things decide the release date.",
    "Dos cosas a tener en cuenta antes de publicarlo.",
    "Cache \u2192 faster pages.",
    "El trimestre cierra más o menos en equilibrio.",
]

CLEAN = [
    "| Month 3 | -$4,200 | -$9,100 | 0 |",
    "- Primer punto de una lista\n- Segundo punto",
    "The fund pays $3,250 in March.",
    "El fondo paga $3,250 en marzo.",
    "on-chain, e-mail and pro-rata are words with hyphens.",
    "The reviewer said: \u201cit's not a misconfiguration, it's the plan\u201d, and was right.",
    "Verbatim: *\"It's going exactly as planned, not a bug.\"*",
    "> It's not X, it's Y, quoted from the source.",
    "Run `grep -n ' - ' file` to check.",
    "See https://example.com/a-b - c for details.",
    "The project spends up to $2,500 in the autumn and recovers it by spring.",
]


def test_patterns(S):
    print("\n== the shapes are caught, ordinary text passes ==")
    for t in CAUGHT:
        check("caught: %s" % t[:50], bool(S.find(t)), t)
    for t in CLEAN:
        check("clean: %s" % t[:50].replace("\n", " "), S.find(t) == [], S.find(t))
    hits = S.find("That is the whole idea.")
    check("a finding names its rule, an excerpt and advice",
          len(hits) == 1 and hits[0][0] == "stock phrase" and "whole idea" in hits[0][1] and hits[0][2], hits)


def _docx(path, paragraphs, cells=()):
    """The smallest .docx Word opens: one document.xml with paragraphs and a one-row table."""
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    body = "".join('<w:p><w:r><w:t xml:space="preserve">%s</w:t></w:r></w:p>' % p for p in paragraphs)
    if cells:
        body += "<w:tbl><w:tr>%s</w:tr></w:tbl>" % "".join(
            "<w:tc><w:p><w:r><w:t>%s</w:t></w:r></w:p></w:tc>" % c for c in cells)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", '<?xml version="1.0"?><w:document %s><w:body>%s</w:body></w:document>'
                   % (ns, body))


def test_readers(S, root):
    print("\n== file formats ==")
    html = os.path.join(root, "a.html")
    with open(html, "w", encoding="utf-8") as fh:
        fh.write("<html><style>p{margin:0 - 1px}</style><body><p>Two decisions travel together.</p>"
                 "<script>var a = b - c;</script></body></html>")
    text = S.read_source(html)
    check("html: the markup, scripts and styles are dropped",
          "Two decisions travel together." in text and "<p>" not in text and "margin" not in text
          and "var a" not in text, text)
    check("html: the prose is checked", sorted(h[0] for h in S.find(text)) == ["count setup", "stock phrase"],
          S.find(text))

    docx = os.path.join(root, "a.docx")
    _docx(docx, ["The plan is fine.", "The ask: more money."], cells=["Cell text \u2014 with a dash"])
    text = S.read_source(docx)
    check("docx: paragraphs are read one per line, with the standard library only",
          "The plan is fine.\nThe ask: more money." in text, text)
    check("docx: table cells are read too", "Cell text" in text, text)
    check("docx: both findings come out", sorted(h[0] for h in S.find(text)) == ["dash", "label colon"],
          S.find(text))


def _run(argv, stdin=None, env=None):
    return subprocess.run([sys.executable, os.path.join(HERE, "style_check.py")] + argv, input=stdin,
                          capture_output=True, text=True, timeout=60, env=env)


def test_cli(root):
    print("\n== the command line ==")
    clean = os.path.join(root, "clean.md")
    with open(clean, "w", encoding="utf-8") as fh:
        fh.write("The plan is fine.\n")
    bad = os.path.join(root, "bad.md")
    with open(bad, "w", encoding="utf-8") as fh:
        fh.write("That is the whole idea.\n")
    p = _run([clean])
    check("a clean file exits 0 and says so", p.returncode == 0 and "clean" in p.stdout, (p.returncode, p.stdout))
    p = _run([bad])
    check("a file with findings exits 1 and lists them",
          p.returncode == 1 and "stock phrase" in p.stdout and "1 finding" in p.stdout, (p.returncode, p.stdout))
    p = _run([clean, bad])
    check("several files: any finding makes the exit 1", p.returncode == 1, p.returncode)
    p = _run(["-"], stdin="Dos cosas a tener en cuenta.\n")
    check("'-' reads stdin", p.returncode == 1 and "count setup" in p.stdout, (p.returncode, p.stdout))
    p = _run([])
    check("no argument prints the usage and exits 2", p.returncode == 2 and "style_check.py" in p.stdout,
          (p.returncode, p.stdout))
    p = _run(["--gdoc", "abc123"])
    check("--gdoc without --account is refused with exit 2, nothing fetched",
          p.returncode == 2 and "--account" in (p.stdout + p.stderr), (p.returncode, p.stdout, p.stderr))
    p = _run([os.path.join(root, "missing.md")])
    check("a missing file exits 2 with a one-line reason", p.returncode == 2 and "missing.md" in p.stderr,
          (p.returncode, p.stderr))


def test_gdoc_export(S):
    print("\n== a Google Doc is exported as text through google.py ==")
    calls = []

    def token(account):
        calls.append(("token", account))
        return "tok-1"

    def urlopen(req, timeout=None):
        calls.append(("get", req.full_url, req.get_header("Authorization")))
        return io.BytesIO("The ask: a budget.".encode("utf-8"))

    text = S.gdoc_text("doc-1", "work", token=token, urlopen=urlopen)
    check("the token comes from the named google.py account", calls[0] == ("token", "work"), calls)
    check("the Drive export endpoint is called with it",
          calls[1][1] == "https://www.googleapis.com/drive/v3/files/doc-1/export?mimeType=text/plain"
          and calls[1][2] == "Bearer tok-1", calls)
    check("and the text is checked like any other", [h[0] for h in S.find(text)] == ["label colon"], text)


def scratch(root):
    paths = {n: os.path.join(root, n) for n in ("home", "state", "vault")}
    for p in paths.values():
        os.makedirs(p)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": paths["home"], "TMPDIR": root,
           "BRAIN_STATE": paths["state"], "BRAIN_VAULT": paths["vault"], "BRAIN_OFFLINE": "1",
           "PYTHONDONTWRITEBYTECODE": "1"}
    return env, paths


def _transcript(root, name, reply, tool_result_after=False):
    path = os.path.join(root, name + ".jsonl")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"type": "assistant", "message": {"role": "assistant",
                 "content": [{"type": "text", "text": "An older reply that says: the key: nothing."}]}}) + "\n")
        fh.write(json.dumps({"type": "user", "message": {"role": "user", "content": "a question"}}) + "\n")
        fh.write(json.dumps({"type": "assistant", "message": {"role": "assistant",
                 "content": [{"type": "text", "text": reply}]}}) + "\n")
        if tool_result_after:
            fh.write(json.dumps({"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}}) + "\n")
            fh.write(json.dumps({"type": "assistant", "message": {"role": "assistant",
                     "content": [{"type": "text", "text": "Done."}]}}) + "\n")
    return path


def test_gate(root):
    print("\n== style_gate.py, the Stop hook ==")
    env, paths = scratch(os.path.join(root, "gate"))
    gate = os.path.join(HERE, "style_gate.py")

    def run(payload):
        return subprocess.run([sys.executable, gate], input=json.dumps(payload), env=env,
                              capture_output=True, text=True, timeout=60)

    t = _transcript(root, "a", "Son dos decisiones que van juntas.")
    p1 = run({"session_id": "aaaa1111-0000", "transcript_path": t, "stop_hook_active": False})
    check("a reply with a finding blocks the stop (exit 2) and quotes it",
          p1.returncode == 2 and "van juntas" in p1.stderr, (p1.returncode, p1.stderr[-400:]))
    check("the block asks for the reply again and points at the convention",
          "Send the reply again" in p1.stderr and "write-like-a-person" in p1.stderr, p1.stderr[-400:])
    p2 = run({"session_id": "aaaa1111-0000", "transcript_path": t, "stop_hook_active": False})
    check("the same reply is let through the second time (one block per reply)", p2.returncode == 0,
          (p2.returncode, p2.stderr[-300:]))

    p = run({"session_id": "bbbb2222", "transcript_path": _transcript(root, "b", "The fund pays $3,250 in March."),
             "stop_hook_active": False})
    check("a clean reply passes", p.returncode == 0, (p.returncode, p.stderr[-300:]))
    p = run({"session_id": "cccc3333", "transcript_path": _transcript(root, "c", "That is the whole idea."),
             "stop_hook_active": True})
    check("a stop that already comes from a stop hook is never blocked", p.returncode == 0, p.returncode)
    p = run({"session_id": "dddd4444",
             "transcript_path": _transcript(root, "d", "That is the whole idea.", tool_result_after=True),
             "stop_hook_active": False})
    check("tool results do not end the reply: text before them in the same turn is checked",
          p.returncode == 2 and "whole idea" in p.stderr, (p.returncode, p.stderr[-300:]))
    p = run({"session_id": "eeee5555", "transcript_path": _transcript(root, "e", "Plain answer."),
             "stop_hook_active": False})
    check("text from before the last user prompt is not checked again", p.returncode == 0,
          (p.returncode, p.stderr[-300:]))
    p = run({"session_id": "ffff6666", "transcript_path": os.path.join(root, "nope.jsonl")})
    check("a missing transcript passes (fail open)", p.returncode == 0, p.returncode)
    p = subprocess.run([sys.executable, gate], input="not json", env=env, capture_output=True, text=True, timeout=60)
    check("a broken payload passes (fail open)", p.returncode == 0, p.returncode)
    off = dict(env, BRAIN_OFF="1")
    p = subprocess.run([sys.executable, gate], env=off, capture_output=True, text=True, timeout=60,
                       input=json.dumps({"session_id": "a1", "transcript_path": t}))
    check("with Brain switched off it never blocks", p.returncode == 0, p.returncode)


def main():
    root = tempfile.mkdtemp(prefix="style-check-test-")
    try:
        try:
            import style_check as S
        except Exception as exc:
            check("style_check imports", False, "%s: %s" % (type(exc).__name__, exc))
            S = None
        tests = [(test_cli, (root,)), (test_gate, (root,))]
        if S is not None:
            tests = [(test_patterns, (S,)), (test_readers, (S, root)), (test_gdoc_export, (S,))] + tests
        for t, args in tests:
            try:
                t(*args)
            except Exception as exc:
                check("%s ran to the end" % t.__name__, False, "%s: %s" % (type(exc).__name__, exc))
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
