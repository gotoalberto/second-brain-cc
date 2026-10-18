# Source of `animated-video`

Vendored from a third-party repository, with the changes listed below. Do not edit upstream's files
here: refresh them from upstream instead (see "Third-party skills" in the repository README), then
apply the same changes again.

- Upstream repository: https://github.com/cth9191/animate
- Path in that repository: `plugins/animate/skills/animate`
- Commit: `7e5eb56feb2dd573f890e1b7b34748af43d58263`
- Licence: MIT, full text in `LICENSE` in this directory (copied from the repository root, since the
  skill directory upstream carries none)
- Copyright: Copyright (c) 2026 cth9191

## Changes made here

- `SKILL.md` front matter: `name` is `animated-video` instead of `animate`, because `animate` is
  already Emil Kowalski's UI motion skill in this plugin; the `description` is rewritten (it says so and
  drops the dashes); an `allowed-tools` line for the wrapper was added.
- `SKILL.md`: a final section, "Added in this repository", appended after upstream's text.
- `scripts/av.sh` and `scripts/av_test.py`: added here (a wrapper that runs the tools with a pinned
  Playwright runtime, and its test).

Every other file is upstream's, byte for byte.

- Refresh: clone the repository at the commit you want, replace this directory with
  `plugins/animate/skills/animate`, copy the root `LICENSE`, and redo the changes above.
