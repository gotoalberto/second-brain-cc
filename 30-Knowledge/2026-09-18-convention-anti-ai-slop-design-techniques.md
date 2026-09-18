---
id: 2026-09-18-convention-anti-ai-slop-design-techniques
title: Techniques to keep AI-built web and presentation design from reading as AI-made
type: decision
area: [design, frontend]
projects: []
tags: [convention, design, frontend, ai-tells, motion, image-generation, video-generation, critique]
status: active
confidence: high
source: agent
provenance: "distilled from the article 'How to turn your AI into a world-class designer' by
  Anshu Chimala (ex-Apple design/eng), published in Lenny Rachitsky's newsletter, 2026-09-01;
  adopted into the `dev` skill's design gates"
updated: 2026-09-18
supersedes: []
---

## The convention

Apply these techniques whenever a web, app or presentation is built or redesigned, on top of
the `dev` skill's existing design gates. Source: "How to turn your AI into a world-class
designer" by Anshu Chimala, published in Lenny Rachitsky's newsletter, 2026-09-01. Content
below is restated, not reproduced; see the article for the full write-up and demos.

Core insight: an LLM is a next-token predictor trained to please everyone, so left alone it
makes the most predictable choice at every design decision (purple gradients, centered hero,
three feature cards). Great design is the opposite of predictable. To get real design out of
an agent, deliberately push it off its default distribution, then deliberately cut back what
it over-adds.

Three stages, mapped onto the Double Diamond: **Discover** (break out of the default
aesthetic), **Define** (give the direction its own identity), **Deliver** (polish and
subtract).

### Discover: break the default before building anything

1. **Seed-string technique** (from Sakana AI's "String Seed of Thought"). When there is no
   strong reference to anchor on, generate a long random alphanumeric string via a shell
   script *first*, derive a creative direction from it (color, layout, typography, looking
   for subpatterns rather than reading digits literally), and use that as inspiration without
   revealing the string in the output. This works because the model cannot act randomly on
   its own: asking it to "be random" just produces confident-sounding fake variety (same
   palette, same structure, different adjectives). The randomness has to come from outside
   the model.
2. **Ambitious/wild prompting.** Instead of "make it unique," anchor the brief to a concrete
   external inspiration (a video game, an interior-design movement, an art installation) and
   describe how that inspiration should bend the interface. To find a genuinely original angle
   rather than the generic list AI hands back on request, run a three-step loop: list many
   ideas shallow (breadth, no detail), react to favorites and note what's specifically off
   about each, ask for a refinement based on that reaction, then have it write the concise
   build prompt for the refined direction. Directions that sound like they can't work are
   often the ones worth trying, and worth keeping even when they fail, to retest against
   newer models later.

Both techniques exist to widen the option space before committing, not to replace a real
brief when references already exist. Use them when the brief is wide open or the answer is
"you decide."

### Define: give the direction its own identity

3. **Design critic in a fresh, blind context.** An agent reviewing its own work is not
   objective; it's anchored on its own code, decisions and rationale. Have a *separate*
   subagent, given only a screenshot (never the code, the implementation history, or the
   builder's rationale), judge it against a "top design studio" bar and return a specific,
   opinionated critique plus an objective score. Iterate until the critic independently
   clears the bar. Rules that make the loop converge instead of thrash:
   - Objective, comparative criteria beat vague ones. Worst: "does this look beautiful, not
     AI-generated." Better: "how would a top studio execute this aesthetic, judge the gap."
     Best: "here are 4 professional references and 1 screenshot of ours, rank by polish."
   - Give the critic reference images (real designs, comparable screenshots) as a baseline
     or moodboard, explicitly told not to copy them outright.
   - Don't put the passing threshold in the critic's own prompt; it should score honestly,
     not to satisfy a known target. Keep the target (e.g. clear the bar in two rounds) as a
     stopping rule the orchestrator applies, not something the critic optimizes for.
   - A stronger model as critic and a cheaper, faster model as builder is a legitimate cost
     optimization: the critic only produces short verdicts, the builder does the bulk of the
     token-heavy work.
   This is a different mechanism from a mechanical critique pass (a typography/spacing/a11y
   checklist); do both, since they catch different failure modes.
4. **Image generation, not code-only decoration.** Coding agents default to gradients, shapes
   and CSS patterns instead of real images because generating one is an extra step they don't
   take unless told to. Push it explicitly, and combine generated images with CSS shaders/3D
   effects rather than using either alone; that combination is what reads as "someone put in
   real effort" instead of a stock AI look. Route API keys for image generation through a
   credential manager (never pasted into chat, never committed) with a low, dedicated spend
   limit.
5. **Video generation for motion the CSS/animation toolkit can't produce.** Use an aggregator
   platform (so the choice of model doesn't go stale) for two specific things:
   - **Looping decorative clips**: generate on a solid background, then chroma-key or run a
     video-matting model to strip the background, so it drops into the UI like a layered asset
     instead of a visible video rectangle. Rendering the clip over the page's actual background
     colors first bakes in realistic refraction/reflection before matting.
   - **Fluid state transitions**: generate two keyframe stills (start/end state of a UI element
     or screen), then use a video model's image-to-video/interpolation mode to produce the
     in-between motion, scrubbed by scroll or triggered by navigation. Chain transitions by
     feeding each clip's last frame as the next one's seed frame, for continuity across
     multiple states.
   Same key-handling rule as image generation.

### Deliver: polish and subtract

6. **Subtraction pass.** AI adds, rarely removes. Before calling a design done, look for glow
   effects, gradients, extra labels, empty space, and custom form controls that only exist
   because the model likes to decorate, and cut them. Minimalism from an LLM has to be asked
   for as a specific edit ("simplify into an image-centric grid, remove gradients and
   containers"), not assumed from "make it minimal" in the original prompt; the model won't
   volunteer deletions on its own. Worth an explicit pass specifically looking for
   *deletions*, not just style fixes.
7. **AI-tell vocabulary.** Recognize the recurring model-favorite patterns (purple/blue glow
   gradients, glassmorphism on everything, three equal feature cards, generic
   micro-animations everywhere, em-dashes as a rhetorical tic, placeholder-shaped content)
   without banning them outright; a blanket ban just makes the model overcorrect into
   different, equally strange patterns.
8. **Copy rewritten by hand.** AI copy doesn't change the visual layout but is often the
   single biggest tell that something is AI-made; readers are fatigued by AI prose
   specifically. Treat model-written copy as placeholder text: fine to block out structure,
   never fine to ship. A human has to read every line and rephrase it in one consistent
   voice. See [[2026-09-10-convention-write-like-a-person]].

## Why

Techniques 6 to 8 are the ones most design guidance already covers, one way or another;
techniques 1 to 3 and 5 are less commonly applied and are what separates AI output that
reads as templated from output that reads as designed. The gap they close: an agent left to
its own devices never volunteers randomness, never critiques itself objectively, and never
reaches for image or video generation unless told to.

## How it's applied

- `dev` skill Gate 3a: seed-string / ambitious-brainstorm techniques as tools when the brief
  is open-ended.
- `dev` skill Gate 3d: a fresh-context blind design-critic subagent round, on top of the
  existing mechanical critique pass.
- `dev` skill Gate 3f: image+shader/3D combination and video generation as explicit tool
  options for the images/motion rounds.
- [[2026-08-25-convention-pitches-as-web-artifacts-with-infographics]]: the same techniques
  apply to a slide deck's infographics.

## Links

- [[2026-08-25-convention-pitches-as-web-artifacts-with-infographics]]
- [[2026-09-10-convention-write-like-a-person]]
