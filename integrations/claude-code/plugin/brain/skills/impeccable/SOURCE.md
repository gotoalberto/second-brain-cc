# Source of `impeccable`

Vendored verbatim from a third-party repository. Do not edit these files here: refresh them from
upstream instead (see "Third-party skills" in the repository README).

- Upstream repository: https://github.com/pbakaus/impeccable
- Path in that repository: `plugin/skills/impeccable`
- Commit: `6e802bd0ed99f53180e2359fddab6da8d97970d9`
- Licence: Apache-2.0, full text in `LICENSE` in this directory
- Copyright: Copyright 2025 Paul Bakaus
- Refresh: copy `plugin/skills/impeccable` and `plugin/agents/` from a fresh clone of the upstream
  repository (`npx impeccable install` is upstream's own per-project installer)

`NOTICE.md` is upstream's own notice file, carried as the Apache licence requires. It credits the
MIT-licensed `platform-design-skills` by ehmo for `reference/ios.md` and `reference/android.md`.
`scripts/modern-screenshot.umd.js` is a minified build of `modern-screenshot`
(https://github.com/qq15725/modern-screenshot, MIT, Copyright (c) 2021-present wxm) that upstream
bundles for its live mode.

This is upstream's Claude Code plugin build (`plugin/skills/impeccable`), which resolves its
scripts through `${CLAUDE_SKILL_DIR}`. Its four subagents ship with it upstream in
`plugin/agents/` and are vendored, unchanged, as `agents/impeccable-*.md` in this plugin.

Network use: `scripts/impeccable` is a launcher for upstream's engine binary. When no binary is
found locally (`$IMPECCABLE_BIN`, `~/.impeccable/bin/`, or `impeccable` on `PATH`) it downloads
the version named in `scripts/VERSION` from upstream's public GitHub releases
(`https://github.com/pbakaus/impeccable/releases`) into `~/.impeccable/bin/<version>/` and runs it
only after checking its published sha256. Nothing in this copy is configured for any particular
user; live mode talks to a server on `localhost` only.
