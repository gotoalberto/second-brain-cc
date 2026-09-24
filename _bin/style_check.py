#!/usr/bin/env python3
"""Finds the expressions that make text read as written by an AI, in English and Spanish.

The convention (30-Knowledge/2026-09-10-convention-write-like-a-person.md) says none of these
shapes go into a reply to the user or a document written for the user or in their name, in any
language. Knowing the rule was never enough: it sat in the startup context and was still broken,
so this is the mechanical check. The Stop hook style_gate.py runs it on every chat reply;
documents are checked with the command line before they are delivered.

Precision over recall: every pattern is a shape a reader flagged, or a direct variant of one.
Verbatim quotes, code, blockquotes and URLs are left out of the scan, since a quote stays as
it was said. A new shape goes in RULES with a case in style_check_test.py (CAUGHT), plus an
ordinary sentence that must not trip it (CLEAN). Spanish is here as the second language; add
the patterns of your own language the same way.

  style_check.py FILE [FILE ...]            .txt .md .html .htm .docx (anything else is read as text)
  style_check.py -                          stdin
  style_check.py --gdoc DOC_ID --account NAME
                                            a Google Doc, exported as text with the google.py account NAME

Exit status: 0 clean, 1 something was found (findings on stdout), 2 asked wrongly or a source
could not be read. Standard library only.
"""
import os
import re
import subprocess
import sys
import urllib.request
import zipfile
from xml.etree import ElementTree

HERE = os.path.dirname(os.path.abspath(__file__))

# (name, compiled regex, advice). Flags: case-insensitive, multiline.
_F = re.I | re.M
# A count that announces a list: at the start of a sentence or heading, or followed by a colon.
_COUNT = (r"\b(?:two|three|four|five|dos|tres|cuatro|cinco) (?:things|decisions|reasons|ideas|lessons|"
          r"takeaways|changes|questions|points|traps|cosas|decisiones|razones|ideas|lecciones|claves|"
          r"cambios|preguntas|puntos|trampas)\b")
RULES = [
    ("dash", re.compile(r"[\u2014\u2013]|(?<=\w) - (?=\w)"),
     "no dashes as punctuation; use a comma, a full stop or a new sentence"),
    ("label colon", re.compile(
        r"^[ \t]*(?:[-*\u2022]|\d+\.)?[ \t]*\**(?:the (?:ask|return|risk|catch|trap|key|point|"
        r"takeaway|bottom line|short version|upshot|twist|kicker|problem|fix|answer)|"
        r"la (?:petici[oó]n|clave|trampa|conclusi[oó]n|respuesta|soluci[oó]n)|"
        r"el (?:retorno|riesgo|truco|problema|resumen))\**[ \t]*:", _F),
     "a label and a colon before the point; write the sentence"),
    ("reveal colon", re.compile(
        r"\b(?:the (?:key|trap|catch|twist|kicker|bottom line|upshot)|the real (?:problem|issue|"
        r"question|pattern|story|reason)|la clave|el truco|la trampa|lo importante|"
        r"el verdadero (?:problema|riesgo|reto))\s*:", _F),
     "a colon that sets up a punchline; state it plainly"),
    ("not X, it is Y", re.compile(
        r"\b(?:it'?s|it is|this is|that'?s|that is|is) not (?:just |only |about )?[^.;:\n]{1,45}"
        r"[,;] (?:it'?s|it is|but)\b|\bnot just [^.;\n]{1,45},? but\b|"
        r"\bno es [^.;\n]{1,45}, (?:es|sino)\b|\bno (?:solo|s[oó]lo) [^.;\n]{1,45},? sino\b", _F),
     "a contrast built to sound conclusive; say what it is"),
    ("X, not Y", re.compile(
        r"\w,\s+not (?:just |only )?(?:a|an|the|to|as|from|on|new|our|any)\b|"
        r"\w,\s+no (?:un|una|el|la|los|las|a|de)\b", _F),
     "a trailing contrast; drop it or make it its own sentence"),
    ("count setup", re.compile(
        r"(?:(?:^|[.!?]\s+)[#*> \t]*" + _COUNT + r")|(?:" + _COUNT + r"[^.\n]{0,60}:)", _F),
     "announcing a count before a list; just give the list"),
    ("stock phrase", re.compile(
        r"\b(?:that'?s the whole idea|that is the whole idea|worth reading once|here'?s the thing|"
        r"here is the thing|the short answer|the bottom line|in short\b|put simply|"
        r"at the end of the day|(?:it'?s|it is) worth noting|worth noting that|genuinely|delve|"
        r"i hope this helps|great question|happy to help|let me know if you need|"
        r"does(?: not|n'?t) bite|travel together|the picture changes|leans on|where the upside sits|"
        r"a named source|close[sd]? about even|never a second ask|what actually|in silence|"
        r"nobody noticed|game.changer|on purpose|the thing that pays|"
        r"van juntas|m[aá]s o menos en equilibrio|sin una segunda petici[oó]n|"
        r"lo que de verdad|el verdadero (?:problema|riesgo|reto)|en silencio|sin que nadie|"
        r"en resumen|en definitiva|no es casualidad|cabe destacar|es importante destacar|"
        r"ah[ií] est[aá] la clave|abri[oó]? el mel[oó]n|recogi[oó] el guante|"
        r"la pelota en el tejado|baj[oó]? (?:la propuesta )?a tierra|dicho de otra forma)\b", _F),
     "stock phrase; say it the way a colleague would"),
    ("arrow", re.compile(r"[\u2192\u21d2\u279c]"), "no arrows in prose"),
]

_QUOTES = re.compile(r"\u201c[^\u201d]*\u201d|\u00ab[^\u00bb]*\u00bb|\"[^\"\n]{1,400}\"|\*\"[^\n]*?\"\*")
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
EXPORT_URL = "https://www.googleapis.com/drive/v3/files/%s/export?mimeType=text/plain"


class SourceError(Exception):
    """A source that could not be read: a missing file, a broken docx, a Google Doc not exported."""


def prose(text):
    """Text with code, URLs, blockquotes and verbatim quotes blanked out (same length per line)."""
    text = re.sub(r"```.*?```", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.S)
    text = re.sub(r"`[^`\n]*`", lambda m: " " * len(m.group(0)), text)
    text = re.sub(r"https?://\S+", lambda m: " " * len(m.group(0)), text)
    text = re.sub(r"(?m)^[ \t]*>.*$", lambda m: " " * len(m.group(0)), text)
    text = _QUOTES.sub(lambda m: " " * len(m.group(0)), text)
    return text


def find(text):
    """[(rule, excerpt, advice)] for every match in the prose part of text."""
    out, p = [], prose(text)
    for name, rx, advice in RULES:
        for m in rx.finditer(p):
            a, b = max(0, m.start() - 45), min(len(text), m.end() + 45)
            ex = " ".join(text[a:b].split())
            out.append((name, ex, advice))
    return out


def report(hits, limit=25):
    lines = ["%-15s %s" % (n, e) for n, e, _ in hits[:limit]]
    if len(hits) > limit:
        lines.append("... and %d more" % (len(hits) - limit))
    return "\n".join(lines)


def _docx_text(path):
    """Paragraph text of a .docx, one paragraph per line, table cells included. No python-docx:
    a .docx is a zip whose word/document.xml holds every paragraph as <w:p> with <w:t> runs."""
    with zipfile.ZipFile(path) as z:
        root = ElementTree.fromstring(z.read("word/document.xml"))
    lines = []
    for p in root.iter(_W + "p"):
        lines.append("".join(t.text or "" for t in p.iter(_W + "t")))
    return "\n".join(lines)


def read_source(path):
    """The text to check in one file (or stdin for '-'). Raises SourceError."""
    if path == "-":
        return sys.stdin.read()
    low = path.lower()
    try:
        if low.endswith(".docx"):
            return _docx_text(path)
        with open(path, encoding="utf-8", errors="replace") as fh:
            s = fh.read()
    except (OSError, KeyError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise SourceError("cannot read %s (%s)" % (path, type(exc).__name__))
    if low.endswith((".html", ".htm")):
        s = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", s)
        s = re.sub(r"<[^>]+>", " ", s)
    return s


def _google_token(account):
    p = subprocess.run([sys.executable, os.path.join(HERE, "google.py"), "token", "--account", account],
                       capture_output=True, text=True, timeout=60)
    tok = p.stdout.strip()
    if p.returncode != 0 or not tok:
        raise SourceError("no Google token for account %s: %s" % (account, (p.stderr or "").strip()[:200]))
    return tok


def gdoc_text(doc_id, account, token=_google_token, urlopen=urllib.request.urlopen):
    """A Google Doc exported as plain text through the Drive API, with the google.py account's token."""
    req = urllib.request.Request(EXPORT_URL % doc_id, headers={"Authorization": "Bearer " + token(account)})
    try:
        return urlopen(req, timeout=60).read().decode("utf-8", "replace")
    except Exception as exc:
        raise SourceError("cannot export Google Doc %s (%s: %s)" % (doc_id, type(exc).__name__, exc))


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    account, docs, files = None, [], []
    it = iter(argv)
    for a in it:
        if a in ("--gdoc", "--account"):
            value = next(it, None)
            if not value:
                sys.stderr.write("style_check.py: %s needs a value\n" % a)
                return 2
            if a == "--gdoc":
                docs.append(value)
            else:
                account = value
        elif a in ("-h", "--help"):
            print(__doc__)
            return 0
        else:
            files.append(a)
    if docs and not account:
        sys.stderr.write("style_check.py: --gdoc needs --account NAME (a google.py account)\n")
        return 2
    srcs = []
    try:
        for f in files:
            srcs.append((f, read_source(f)))
        for d in docs:
            srcs.append(("gdoc " + d, gdoc_text(d, account)))
    except SourceError as exc:
        sys.stderr.write("style_check.py: %s\n" % exc)
        return 2
    bad = 0
    for label, text in srcs:
        hits = find(text)
        if hits:
            bad = 1
            print("== %s: %d finding(s)" % (label, len(hits)))
            print(report(hits))
        else:
            print("== %s: clean" % label)
    return bad


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
