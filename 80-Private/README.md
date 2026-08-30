# 80-Private

Local-only notes that never leave this machine. Everything under `80-Private/` is excluded from git and is **not pushed** to the remote — it stays on your disk, out of the shared history.

Use it for the things you want the vault to hold but not to sync: raw meeting notes before you sanitise them, personal reminders, scratch thinking, a draft that mentions a real name or host you haven't abstracted yet, or a pointer to a secret (store the secret itself in 1Password and reference it with a `op://` link, never inline).

Because these notes stay off the remote, they are also outside your backup and unreachable from other machines. Treat this folder as ephemeral and single-device: don't keep anything here that you can't afford to lose if the disk does.

When a private note matures into something durable and shareable, scrub any sensitive details and move it to its proper home — a decision or how-to in `30-Knowledge/`, a project update via `_bin/vw.py`, or an entity in `70-Entities/` — then delete it from here.

How it's kept private: the repo's `.gitignore` excludes this folder's contents. If you add files here, confirm they're ignored with `git status` before you commit — nothing under `80-Private/` should ever appear as staged or tracked.
