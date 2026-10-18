#!/usr/bin/env python3
"""Tests for mail_body.py, the shared email body composer.

The bug these pin down: a body sent as a bare text/plain part is re-wrapped by the reading
client at its own fixed width, so a paragraph arrives as a tall column of about 70 characters.
Run standalone:

    python3 _bin/mail_body_test.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import datetime as dt  # noqa: E402

import mail_body  # noqa: E402
from mail_body import build_message, text_to_html  # noqa: E402

ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail and not cond else ""))


def test_reflow():
    print("\n== paragraphs flow instead of forming a column ==")
    # What a hand-rolled composer produced: prose hard-wrapped at about 70 characters.
    wrapped = ("Dana and I have been talking over the past few weeks about the new\n"
               "reporting tool. I think it fits well with what your team is\n"
               "building.")
    html = text_to_html(wrapped)
    check("a hard-wrapped paragraph is re-joined into one <p>",
          "<p>Dana and I have been talking over the past few weeks about the new reporting tool. "
          "I think it fits well with what your team is building.</p>" in html, html)
    check("no <br> is injected into prose", "<br>" not in html, html)

    two = text_to_html("First paragraph.\n\nSecond paragraph.")
    check("a blank line starts a new <p>",
          "<p>First paragraph.</p>" in two and "<p>Second paragraph.</p>" in two, two)
    check("Windows line endings are handled like any other",
          text_to_html("One.\r\n\r\nTwo.") == two.replace("First paragraph.", "One.").replace(
              "Second paragraph.", "Two."), text_to_html("One.\r\n\r\nTwo."))


def test_structure_is_kept():
    print("\n== deliberate line breaks survive ==")
    html = text_to_html("Points:\n- exports are not ready\n- the dashboard is live\n\nBest,\nDana")
    check("bullets become a <ul> even under a lead-in line",
          "<p>Points:</p>" in html
          and "<ul><li>exports are not ready</li><li>the dashboard is live</li></ul>" in html, html)
    check("a short signature keeps its break", "<p>Best,<br>Dana</p>" in html, html)
    numbered = text_to_html("1. first\n2. second")
    check("numbered lines are a list too", "<ul><li>first</li><li>second</li></ul>" in numbered, numbered)


def test_escaping():
    print("\n== the body is data, not markup ==")
    html = text_to_html("5 < 6 & \"quoted\" <script>alert(1)</script>")
    check("HTML metacharacters in a plain body are escaped",
          "&lt;script&gt;" in html and "<script>" not in html, html)


def test_message():
    print("\n== build_message ==")
    msg = build_message(["a@example.com", "b@example.com"], "Subject", "Hello there.",
                        sender="me@example.com", cc="c@example.com")
    check("it is multipart/alternative", msg.get_content_type() == "multipart/alternative",
          msg.get_content_type())
    parts = {p.get_content_type() for p in msg.walk() if not p.is_multipart()}
    check("carrying a plain part and an HTML part", parts == {"text/plain", "text/html"}, parts)
    check("a list of recipients is joined", msg["To"] == "a@example.com, b@example.com", msg["To"])
    check("headers are set", msg["From"] == "me@example.com" and msg["Cc"] == "c@example.com"
          and msg["Subject"] == "Subject", dict(msg.items()))
    check("no Bcc header unless one is given", msg["Bcc"] is None, dict(msg.items()))

    own = build_message("a@example.com", "S", "ignored text", html="<h1>Report</h1>")
    body = [p for p in own.walk() if p.get_content_type() == "text/html"][0]
    check("an explicit html body is used verbatim",
          "<h1>Report</h1>" in body.get_payload(decode=True).decode(), body)


def test_attachments_and_headers():
    print("\n== attachments and raw headers ==")
    msg = build_message("a@example.com", "Timetable", "Here it is.",
                        attachments=[("spring-timetable.pdf", b"%PDF-1.4 fake"), ("notes.unknownext", b"x")],
                        headers={"In-Reply-To": "<m1@example.com>", "References": "<m0@example.com> <m1@example.com>",
                                 "X-Empty": ""})
    check("a message with attachments is multipart/mixed", msg.get_content_type() == "multipart/mixed",
          msg.get_content_type())
    atts = list(msg.iter_attachments())
    check("each attachment keeps its name", [a.get_filename() for a in atts] == ["spring-timetable.pdf", "notes.unknownext"],
          [a.get_filename() for a in atts])
    check("its type comes from the name, octet-stream when unknown",
          [a.get_content_type() for a in atts] == ["application/pdf", "application/octet-stream"],
          [a.get_content_type() for a in atts])
    check("and its bytes arrive intact", atts and atts[0].get_payload(decode=True) == b"%PDF-1.4 fake")
    body = msg.get_body(("html",))
    check("the body is still there, as HTML", body is not None and "Here it is." in body.get_content(), body)
    check("raw headers are set", msg["In-Reply-To"] == "<m1@example.com>"
          and msg["References"] == "<m0@example.com> <m1@example.com>", dict(msg.items()))
    check("an empty header value is left out", msg["X-Empty"] is None, dict(msg.items()))


def test_replies():
    print("\n== replies ==")
    check("a subject gets one Re:", mail_body.reply_subject("Spring timetable") == "Re: Spring timetable")
    check("never two", mail_body.reply_subject("RE: Spring timetable") == "RE: Spring timetable")
    when = dt.datetime(2026, 10, 17, 11, 13)
    line = mail_body.reply_attribution("Ana Ruiz <ana@example.com>", when)
    check("the attribution line follows Gmail's English form",
          line == "On Sat, 17 Oct 2026 at 11:13, Ana Ruiz <ana@example.com> wrote:", line)
    plain, html = mail_body.reply_bodies("Thursday suits me better.", "<p>Thursday suits me better.</p>", line,
                                         "Hi,\n\nCan we move the class?\n", "<p>Hi,</p><p>Can we move the class?</p>")
    check("the plain part has the new text first, then the original quoted with > lines",
          plain.startswith("Thursday suits me better.") and "\n> Can we move the class?" in plain
          and "\n>\n" in plain and line in plain, plain)
    check("the HTML part quotes the original inside a gmail_quote blockquote",
          'class="gmail_quote"' in html and "<blockquote" in html and "<p>Can we move the class?</p>" in html, html)
    check("under the escaped attribution line", "Ana Ruiz &lt;ana@example.com&gt; wrote:" in html, html)
    check("after the new text", html.find("Thursday") < html.find("gmail_quote"), html)
    _, html2 = mail_body.reply_bodies("ok", "<p>ok</p>", line, "a <b> plain original", None)
    check("an original with no HTML part is quoted from its text, escaped", "a &lt;b&gt; plain original" in html2, html2)


if __name__ == "__main__":
    for t in (test_reflow, test_structure_is_kept, test_escaping, test_message, test_attachments_and_headers,
              test_replies):
        try:
            t()
        except Exception as exc:
            check("%s ran to the end" % t.__name__, False, "%s: %s" % (type(exc).__name__, exc))
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    sys.exit(1 if fail else 0)
