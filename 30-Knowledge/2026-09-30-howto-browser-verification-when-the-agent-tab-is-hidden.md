---
id: 2026-09-30-howto-browser-verification-when-the-agent-tab-is-hidden
title: Browser verification when the agent's tab is hidden
type: howto
area: [frontend, testing]
projects: []
tags: [playwright, chrome, claude-in-chrome, screenshot, intersection-observer, visibility, verification]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-10-04
supersedes: []
---

# Browser verification when the agent's tab is hidden

## The symptom

On a remote Linux desktop, the tab the browser extension drives reported
`document.visibilityState === "hidden"`, even while it looked like the active tab. A hidden document
changes what a page does, silently and with no console error:

- `IntersectionObserver` callbacks never fire, so scroll-triggered reveals stay at their start state
  (bars at zero width, sections at zero opacity) and the screenshot looks broken;
- polling stops: a data library's `refetchInterval` does not run on a hidden or unfocused tab, so
  on-screen state looks frozen while the source has moved on;
- some apps never start their first fetch, so a data-driven page stays empty;
- the window cannot be resized, and a background tab in the extension's group reports a small fixed
  width.

Check `document.visibilityState` first when a capture looks stuck mid-animation, and focus or reload
the tab before concluding that polling is broken. Scrolling the element into view does not help while
the document itself is hidden, and faking `visibilityState` from inside the page is fragile.

## What works: headless Playwright on the system Chrome

A separate headless browser reports itself visible, so observers and timers behave.

- Install `playwright-core` (or the Python `playwright` package) in a scratch directory; the bundled
  browser download is not needed.
- Launch the system Chrome: `executablePath: '/usr/bin/google-chrome'` in Node,
  `executable_path="/usr/bin/google-chrome"` in Python, `headless: true`. On some Linux machines the
  bundled Chromium is simply not installed.
- One context per width you check (for example 1440, 820 and 390), wait for the animation, then take
  an **element** screenshot of the block under review
  (`page.locator('.pricing-table').screenshot(...)`) rather than a full page.

## Real data without local secrets

When the local build's API routes need keys the machine should not hold, route those requests to the
production twin and leave everything else on the local build:

```js
await page.route('**/api/**', async route => {
  const url = new URL(route.request().url());
  const res = await fetch('https://example.org' + url.pathname + url.search);
  const headers = Object.fromEntries(res.headers);
  delete headers['content-encoding']; delete headers['content-length'];  // fetch already decoded the body
  await route.fulfill({ status: res.status, headers, body: Buffer.from(await res.arrayBuffer()) });
});
```

A plain reverse proxy in front of the local server was tried for the same purpose and did not work
for every app; the in-browser route did. The same interception can stub a client-side "who am I"
endpoint to render a page behind a login in a throwaway dev session. It never touches the server's
own check, and it never ships.

## Traps

- **Full-page captures turn touch emulation off.** Chromium disables it for a capture taller than the
  viewport. When the page has touch-specific layout, re-enable it through a CDP session
  (`Emulation.setTouchEmulationEnabled`) after the device emulation is set and before the screenshot.
- **WebGL canvases read back blank from inside the page.** `canvas.toDataURL()` returns an empty image
  unless the context was created with `preserveDrawingBuffer: true`, which most setups leave off.
  Compare screenshots taken from outside the page instead.
- **Previewing a CSS change needs no deploy.** Load production, inject the proposed rules with
  `page.addStyleTag({ content })` (and new markup with `page.evaluate`), then screenshot or compare
  computed styles and `getBoundingClientRect()` before and after. Often faster than fighting a
  worktree's dependencies for a pure CSS change.

## The desktop app's browser pane

The built-in browser pane has failure modes of its own, all silent:

- **Screenshots only paint at scroll offset 0.** `window.scrollTo()` returned a black frame, and
  translating `body` upwards produced stale tiles. What works: resize to a very tall viewport (say
  1280x4000) and shoot at scroll 0, or hide the sections above the target (`display: none`) and let the
  page settle a couple of seconds.
- **A pane that is not displayed renders nothing.** Screenshots come back as flat colour, and scroll or
  hover time out; only text reads and JavaScript evaluation keep working, since they do not need paint.
  Fall back to the headless route above instead of retrying.
- **A hidden pane throttles CSS animations**, so a working animated diagram looks frozen. Before
  judging its end state, finish every animation:
  `document.getAnimations().forEach(a => a.finish())`.
- **`element.click()` does not always fire React handlers.** Dispatch the full sequence instead,
  `pointerdown`, `mousedown`, `pointerup`, `mouseup`, `click`, each with
  `{bubbles: true, cancelable: true, composed: true}`. To fill a React-controlled input, use the
  prototype's native setter, then dispatch `input` and `change`:
  `Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(el, "42")`.
  A button that has just become enabled can still read `disabled` for a moment; check it right before
  clicking and retry rather than concluding the action failed.

Measurements (`getComputedStyle`, `getBoundingClientRect`, `elementFromPoint`) stay correct through all
of this, but they complement a screenshot, they do not replace it
([[2026-08-23-verify-frontend-findings-against-production]]). Starting the pane's server has its own traps
([[2026-09-04-howto-preview-start-launch-json-primary-cwd]]).

## Links

- [[2026-09-21-reference-where-claude-in-chrome-is-available]]
- [[2026-08-30-convention-impeccable-craft-floor-rules-for-web]]
- [[2026-09-02-convention-deploy-to-prod-on-every-change]]
