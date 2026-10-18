# Source of `remotion`

Vendored verbatim from a third-party repository. Do not edit these files here: refresh them from
upstream instead (see "Third-party skills" in the repository README).

- Upstream repository: https://github.com/digitalsamba/claude-code-video-toolkit
- Paths in that repository: `.claude/skills/remotion` (`SKILL.md`, `reference.md`) and `lib/` (the
  shared components, theme, transitions and brand helpers the skill documents), copied here as
  `lib/`
- Commit: `959e0fc6c20210832078781e49daa7384cebb293`
- Licence: MIT, full text in `LICENSE` in this directory (the repository's root licence)
- Copyright: Copyright (c) 2024 Digital Samba

## What is not here

- The toolkit's `remotion-official` skill, a sync of the official Remotion skills
  (https://github.com/remotion-dev/skills), which the text above refers to for core Remotion
  knowledge. Those skills carry no licence of their own and live in the Remotion monorepo, under the
  Remotion License, which does not grant redistribution to everyone. They are not bundled; install
  them from upstream with `npx skills add remotion-dev/skills`.
- Remotion itself is under the Remotion License (free for individuals and small companies, a company
  licence for larger for-profit organisations): https://remotion.dev/license.

- Refresh: clone the repository at the commit you want and replace `SKILL.md`, `reference.md` and
  `lib/` with upstream's copies.
