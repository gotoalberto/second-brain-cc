---
id: 2026-09-04-howto-cra-react-helmet-async-dev-unstyled
title: Create React App with react-helmet-async on React 19 in the dev server
type: howto
area: [frontend]
projects: []
tags: [cra, craco, react-helmet-async, react19, dev-server, howto]
status: active
confidence: medium
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-04
supersedes: []
---

## The trap

In a Create React App (with craco) project on React 19, `npm start` rendered the landing page completely
unstyled: no `<title>` and no stylesheet `<link>` in the document head. `react-helmet-async`, which managed
the head, injected nothing in that dev setup. Reverting to the unmodified baseline reproduced the same
blank page, so it was pre-existing and not caused by the change under review.

## What to do

Review anything visual on a production build instead:

```sh
CI=true npm run build
npx serve -s build
```

`CI=true` keeps the build from prompting or hanging in some configurations.

## The general lesson

When a dev server shows a page that looks like a CSS regression, check `document.head.innerHTML` before
diagnosing CSS, and reproduce on the untouched baseline before blaming your own change. The dev server is
not the product ([[2026-08-23-verify-frontend-findings-against-production]]).

To confirm a client-rendered app's deploy from outside, see the bundle check in
[[2026-09-02-convention-deploy-to-prod-on-every-change]].
