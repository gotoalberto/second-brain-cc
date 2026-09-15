"""The Brain guardian: keeps the vault machinery wired and speaks up when it is not.

Hexagonal on purpose, because this is the part that has to keep working when the Claude
app is closed, another account is logged in, or the model behind it changes:

  domain.py       pure rules (hook merge, alert de-duplication, due-ness). No IO.
  ports.py        the interfaces the use cases need from the world.
  application.py  the use cases: check, repair, status. Depends only on ports.
  adapters.py     the real world: settings.json, launchctl, osascript, git, files.
  mail_queue.py   the on-disk outbox that retries email on every run.
  mailer.py       the Gmail API adapter behind the Mailer port.

The entry point is `_bin/guardian.py`.
"""
