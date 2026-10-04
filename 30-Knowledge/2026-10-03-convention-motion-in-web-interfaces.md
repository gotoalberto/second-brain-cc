---
id: 2026-10-03-convention-motion-in-web-interfaces
title: Motion in web interfaces, the user's preferences and how it is built
type: convention
area: [frontend, design]
projects: []
tags: [animation, motion, css, tabs, reduced-motion, proposals, testing, convention]
status: active
confidence: high
source: user
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-04
supersedes: []
---

The animation skills decide curves and durations
([[2026-09-01-convention-web-development-skill-stack]]). This note holds what the user asked for on
top of them, and the build pattern that kept motion from rotting.

## Preferences

- **Selection indicators slide, they never jump.** A pill under a filter rail or an underline under a
  row of tabs glides from the old option to the new one, on desktop and on phones. The user asked for
  it twice in a row, on two different selectors, so it applies to every selector with a marked option.
- **Motion is tied to real state.** A figure that rises rolls up, a pending confirmation fills its
  button, an error shakes its field, a success draws its check. Decoration that implies progress or
  activity that is not real is rejected: a counter ticking up between real updates shows a number that
  does not exist yet.
- **No press "sink" on tabs.** A scale-down that makes a tab look pushed inward was disliked; subtle
  press feedback (a small scale plus a faint background) is fine on links and buttons.
- **No alarm styling on a primary action.** A coloured warning border on the main button at a risky
  input was rejected; the warning lives in the text next to it, the button stays normal.
- **Directional transitions animate only on the user's own action**, never on a programmatic reset of
  the same view.
- **Cancelling is not an error.** A user who cancels in a confirm dialog or a third-party sign-in gets no shake.
- Usually rejected as too much: full page transitions, full-screen confetti, custom cursors, text
  parallax inside product screens, animating live data values themselves.

## Let the user pick from live variants

For a motion pass over an existing app, run `find-animation-opportunities`, then publish a proposals
page with every opportunity shown **live** in two or three variants plus "none", each with a short
reason. The user picks per item; whatever they pick stands over later critic advice. Rejected ideas
are written on the page with why, so they are not proposed again.

## How a sliding indicator is built

- One indicator element moved with `transform: translateX(var(--x))` and `width: var(--w)`, around
  250 ms on the project's ease-out curve.
- Positions are measured from the real option element by a small hook that re-measures on resize and
  is instant on first paint, so the indicator appears in place on load.
- The pick shows at once; the URL or the server confirms it afterwards.
- Reduced motion: the indicator jumps. Without JavaScript, the plain `aria-current` styling remains.
- For a pill over text, clip a copy of the labels in the selected ink to the pill, so the text lightens
  as the pill arrives. Clipping a copy of fully styled pills shows pieces of two pills mid-slide.
- On Safari, give the indicator `will-change: transform`, or it can snap one device pixel when the
  transition ends ([[2026-10-03-howto-reproduce-safari-compositing-jumps-with-webkit-video]]).

## Keep motion from rotting

- **Timing rules as pure functions** (stagger, duration, count-up steps, which direction a tab enters
  from), each with a unit test that pins the values. An inline constant drifts back to slow with no
  test noticing.
- **A stylesheet contract test**: keyframes may only animate `transform`, `opacity`, `filter` and
  `stroke-dashoffset`, and every animated selector must have a `prefers-reduced-motion` version.
- **Copied motion code stays identical.** When two apps share motion pieces by copy, a test fails if
  the copies differ.
- **A live fake scenario** in the local fake data mode (the world advances every minute) lets rolling
  figures and arrival effects be seen without a backend
  ([[2026-10-03-convention-web-runs-locally-with-fake-data-every-page-reviewed]]).

## Verifying motion

- Sample the DOM per frame to tell "not there yet" from "there but still animating in", and confirm a
  suspected flash against painted pixels
  ([[2026-09-04-howto-verify-animation-timing-by-per-frame-sampling]]).
- After collapsing a tall region, restore scroll with `behavior: "auto"`, not `"smooth"`
  ([[2026-09-04-howto-scroll-restoration-after-collapse-needs-auto-not-smooth]]).
- A hidden browser tab pauses transitions and `requestAnimationFrame`; time animations in a headless
  browser that reports itself visible
  ([[2026-09-30-howto-browser-verification-when-the-agent-tab-is-hidden]]).

## Links

- [[2026-08-29-convention-design-with-scrollcraft-apple-style]]
- [[2026-08-30-convention-impeccable-craft-floor-rules-for-web]]
- [[2026-10-03-convention-one-icon-family-enforced-by-a-wrapper-and-a-test]]
