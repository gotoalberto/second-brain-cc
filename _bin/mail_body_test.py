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


if __name__ == "__main__":
    for t in (test_reflow, test_structure_is_kept, test_escaping, test_message):
        try:
            t()
        except Exception as exc:
            check("%s ran to the end" % t.__name__, False, "%s: %s" % (type(exc).__name__, exc))
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    sys.exit(1 if fail else 0)
