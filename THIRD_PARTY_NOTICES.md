# Third-party notices

The skills and agents listed here are not written for this project. They are copied verbatim from
their upstream repositories, under their own licences, and bundled so that the `dev` skill's web
stack works out of the box. Everything else in this repository is under its own licence.

Each vendored skill directory carries the upstream licence text (`LICENSE`, or `LICENSE.txt` for
`frontend-design`) and a `SOURCE.md` naming the repository, path, commit and licence. The files are
not modified here; to change one, refresh it from upstream (see "Third-party skills" in
[README.md](README.md)).

All paths below are under `integrations/claude-code/plugin/brain/`.

## Emil Kowalski's skills

- Upstream: https://github.com/emilkowalski/skills, commit `e8a175de22ae1e49370fc144c1f3bb9aeedf988d`
- Licence: MIT
- Copyright (c) 2026 Emil Kowalski

| Skill | Upstream path |
|---|---|
| `skills/animate` | `skills/animate` |
| `skills/animate-expo` | `skills/animate-expo` |
| `skills/animation-vocabulary` | `skills/animation-vocabulary` |
| `skills/apple-design` | `skills/apple-design` |
| `skills/ask-sonner` | `skills/ask-sonner` |
| `skills/break-ui` | `skills/break-ui` |
| `skills/emil-design-eng` | `skills/emil-design-eng` |
| `skills/find-animation-opportunities` | `skills/find-animation-opportunities` |
| `skills/improve-animations` | `skills/improve-animations` |
| `skills/mobile-native` | `skills/mobile-native` |
| `skills/pick-ui-library` | `skills/pick-ui-library` |
| `skills/prototype` | `skills/prototype` |
| `skills/review-animations` | `skills/review-animations` |
| `skills/write-swift` | `skills/write-swift` |

## Taste Skill

- Upstream: https://github.com/leonxlnx/taste-skill, commit `ce26fc25c0e5e8cab638f883de62d9a86ee5e45b`
- Licence: MIT
- Copyright (c) 2026 Leonxlnx

| Skill | Upstream path |
|---|---|
| `skills/design-taste-frontend` | `skills/taste-skill` |

## Impeccable

- Upstream: https://github.com/pbakaus/impeccable, commit `6e802bd0ed99f53180e2359fddab6da8d97970d9`
- Licence: Apache-2.0
- Copyright 2025 Paul Bakaus
- Upstream's `NOTICE.md` is carried in `skills/impeccable/NOTICE.md`. It credits
  `platform-design-skills` by ehmo (https://github.com/ehmo/platform-design-skills, MIT) for
  `reference/ios.md` and `reference/android.md`.
- `skills/impeccable/scripts/modern-screenshot.umd.js` is a minified build of `modern-screenshot`
  (https://github.com/qq15725/modern-screenshot), MIT, Copyright (c) 2021-present wxm, bundled by
  upstream.

| File | Upstream path |
|---|---|
| `skills/impeccable` (with `reference/` and `scripts/`) | `plugin/skills/impeccable` |
| `agents/impeccable-asset-producer.md` | `plugin/agents/impeccable-asset-producer.md` |
| `agents/impeccable-documenter.md` | `plugin/agents/impeccable-documenter.md` |
| `agents/impeccable-finish-reviewer.md` | `plugin/agents/impeccable-finish-reviewer.md` |
| `agents/impeccable-manual-edit-applier.md` | `plugin/agents/impeccable-manual-edit-applier.md` |

The skill's launcher (`scripts/impeccable`) downloads upstream's engine binary from upstream's
public GitHub releases on first run when none is installed, and verifies its sha256 before running
it. See `skills/impeccable/SOURCE.md`.

## Anthropic's frontend-design skill

- Upstream: https://github.com/anthropics/skills, commit `8a1541c4a3ffa5a20a5a91de0dcf3f0bab1d1ef4`
- Licence: Apache-2.0, full text in `skills/frontend-design/LICENSE.txt` as shipped upstream
- Copyright: Anthropic (the shipped licence file carries no separate copyright line)

| Skill | Upstream path |
|---|---|
| `skills/frontend-design` | `skills/frontend-design` |
