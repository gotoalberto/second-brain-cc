"""The guardian's outbox: alert email waits here until it can be sent.

Every alert is queued first and sent from the queue, so a mail channel that is down —
disabled, no token, a token without the send scope, no network — costs nothing but a
delay: the message stays on disk and the next guardian run (every 15 minutes) tries
again. Nothing here raises to the caller: the guardian must keep checking even when it
cannot talk.

With no mailer configured the outbox is disabled: it still queues and logs, and the
queue is sent the day a mailer is configured. The queue is bounded in count and in age
so that day does not bring a flood of stale alerts.
"""

from __future__ import annotations

import json
import time
import uuid

from .adapters import atomic_write, locked


class FileMailQueue:
    def __init__(self, path, mailer=None, log=None, now=time.time, max_messages=200,
                 max_age_s=7 * 86400):
        self.path, self.mailer = path, mailer
        self.log = log or (lambda s: None)
        self.now, self.max_messages, self.max_age_s = now, max_messages, max_age_s

    def _read(self) -> list:
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as exc:
            self.log("mail queue unreadable, starting empty: %s" % exc)
            return []
        return data if isinstance(data, list) else []

    def _write(self, msgs: list) -> None:
        atomic_write(self.path, json.dumps(msgs, indent=2, ensure_ascii=False))

    def enabled(self) -> bool:
        return self.mailer is not None

    def enqueue(self, to: str, subject: str, body: str) -> None:
        try:
            with locked(self.path):
                msgs = self._read()
                msgs.append({"id": uuid.uuid4().hex[:12], "to": to, "subject": subject,
                             "body": body, "queued_at": self.now(), "attempts": 0})
                self._write(msgs[-self.max_messages:])
        except Exception as exc:
            self.log("mail queue: could not enqueue %r: %s: %s" % (subject, type(exc).__name__, exc))

    def flush(self):
        """Send what is queued, oldest first. Stops at the first failure. (sent, kept)."""
        try:
            with locked(self.path):
                msgs = self._read()
                if not msgs:
                    return 0, 0
                now = self.now()
                fresh = [m for m in msgs if now - m.get("queued_at", now) <= self.max_age_s]
                if len(fresh) != len(msgs):
                    self.log("mail queue: dropped %d message(s) older than %.0f h"
                             % (len(msgs) - len(fresh), self.max_age_s / 3600))
                if self.mailer is None:
                    if fresh:
                        self.log("mail disabled: %d message(s) queued" % len(fresh))
                    if len(fresh) != len(msgs):
                        self._write(fresh)
                    return 0, len(fresh)
                sent, kept = 0, []
                for i, m in enumerate(fresh):
                    try:
                        self.mailer.send(m["to"], m["subject"], m["body"])
                        sent += 1
                    except Exception as exc:
                        m["attempts"] = m.get("attempts", 0) + 1
                        m["last_error"] = ("%s: %s" % (type(exc).__name__, exc))[:300]
                        kept = fresh[i:]
                        self.log("mail unavailable, %d message(s) kept for the next run: %s"
                                 % (len(kept), m["last_error"]))
                        break
                self._write(kept)
                if sent:
                    self.log("mail sent: %d message(s)" % sent)
                return sent, len(kept)
        except Exception as exc:
            self.log("mail queue: flush failed: %s: %s" % (type(exc).__name__, exc))
            return 0, self.pending()

    def pending(self) -> int:
        return len(self._read())

    def oldest_age_s(self):
        msgs = self._read()
        if not msgs:
            return None
        return max(0.0, self.now() - min(m.get("queued_at", self.now()) for m in msgs))
