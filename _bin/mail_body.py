"""Compose an email body that renders as flowing paragraphs at the reader's width.

Why this exists: a body sent as a bare `text/plain` part gets wrapped by the reading
client at its own fixed width, so a normal paragraph arrives as a tall column of about
70 characters. Sending the same text as `text/html`, with one <p> per paragraph, lets
the client flow it to the window width.

So every mail Brain composes goes through `build_message` here, whichever account or
transport sends it (guardian_core/mailer.py, which google.py send also uses). Write the
body as plain text with blank lines between paragraphs; this module turns it into a
multipart/alternative with an HTML part (what people see) and the original text as the
fallback part.
"""

from __future__ import annotations

import html as _html
import re
from email.message import EmailMessage

__all__ = ["text_to_html", "build_message"]

# A line that is part of a list rather than prose: "- item", "* item", "1. item".
_BULLET = re.compile(r"^\s*(?:[-*\u2022]|\d+[.)])\s+")


def _split_paragraphs(text: str) -> list[str]:
    """Blank lines separate paragraphs; single newlines inside one are just wrapping."""
    chunks = re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip())
    return [c for c in (chunk.strip() for chunk in chunks) if c]


def _render_block(lines: list[str]) -> str:
    """One run of non-bullet lines as a <p>.

    Prose wrapped across several lines is joined so it can re-flow, but a run of short
    lines (a signature, an address) keeps its breaks: joining those is what turns
    "Best,\\nDana" into one line.
    """
    stripped = [line.strip() for line in lines if line.strip()]
    if not stripped:
        return ""
    if len(stripped) > 1 and all(len(line) < 40 for line in stripped):
        return "<p>%s</p>" % "<br>".join(_html.escape(line) for line in stripped)
    return "<p>%s</p>" % _html.escape(" ".join(stripped))


def text_to_html(text: str) -> str:
    """A plain text body as HTML whose paragraphs flow at the reader's width.

    Bullet lines become a <ul> wherever they appear, so a list keeps its breaks even
    when a lead-in line ("Points:") sits above it; prose is joined into a <p> and left
    to wrap at the reader's width.
    """
    parts = []
    for para in _split_paragraphs(text):
        pending: list[str] = []  # non-bullet lines waiting to be flushed as a <p>
        bullets: list[str] = []
        for line in para.split("\n"):
            if _BULLET.match(line):
                if pending:
                    parts.append(_render_block(pending))
                    pending = []
                bullets.append(_BULLET.sub("", line).strip())
                continue
            if bullets:
                parts.append("<ul>%s</ul>"
                             % "".join("<li>%s</li>" % _html.escape(b) for b in bullets))
                bullets = []
            pending.append(line)
        if bullets:
            parts.append("<ul>%s</ul>"
                         % "".join("<li>%s</li>" % _html.escape(b) for b in bullets))
        if pending:
            parts.append(_render_block(pending))
    body = "\n".join(part for part in parts if part)
    # No fixed width and no font override: the client's own defaults read best.
    return "<html><body>%s</body></html>" % body


def build_message(to, subject, body, sender=None, cc=None, bcc=None, html=None):
    """An EmailMessage ready to serialise, with the HTML part the reader actually sees.

    `to` and `cc` take a string or a list of addresses. `body` is plain text; pass
    `html` to supply your own markup instead of the text-to-HTML conversion.
    """

    def _join(value):
        if value is None:
            return None
        if isinstance(value, (list, tuple)):
            return ", ".join(str(v) for v in value if v)
        return str(value)

    msg = EmailMessage()
    msg["To"] = _join(to)
    msg["Subject"] = subject
    if sender:
        msg["From"] = sender
    if cc:
        msg["Cc"] = _join(cc)
    if bcc:
        msg["Bcc"] = _join(bcc)

    # The plain text stays as the fallback part, so nothing is lost for a reader
    # that refuses HTML; the HTML part is what a normal client shows.
    msg.set_content(body)
    msg.add_alternative(html if html is not None else text_to_html(body), subtype="html")
    return msg
