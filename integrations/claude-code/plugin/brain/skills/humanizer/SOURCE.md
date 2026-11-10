# Source

Upstream: https://github.com/blader/humanizer (MIT, Siqi Chen), SKILL.md v3.1.0, commit 0ef9fe5.
Not modified here.

Every document, post, message and text-producing routine runs its text through this skill
(embedded mode, final text only) before sending or publishing; the routine preamble block
`90-Meta/routines/_preamble/humanizer.md` puts that rule in front of every routine prompt.

House rules that override it: no dashes at all (even if a sample uses them), and the voice and
format rules of the calling skill win where they are stricter.

To update: clone upstream, copy SKILL.md and LICENSE here, bump this file and
THIRD_PARTY_NOTICES.md, then `python3 _bin/install_plugin.py sync`.
