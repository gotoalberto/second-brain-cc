---
id: 2026-09-23-howto-linkedin-content-search-calibration
title: LinkedIn content search, querying it and reading its results page
type: howto
area: [research, career]
projects: []
tags: [linkedin, search, browser, content-search, chrome, calibration, job-search]
status: active
confidence: high
source: agent
provenance: "generalized from real incidents in a working vault; names and numbers are illustrative"
updated: 2026-09-23
supersedes: []
---

## Context

LinkedIn's content search (posts, not job postings) exists only behind a signed in session. There is
no public endpoint for it, so it is driven through a real browser with Claude in Chrome
([[2026-09-21-reference-where-claude-in-chrome-is-available]]), and its results page is fragile in ways
worth writing down once. It was calibrated for step 2b of the `job-search` skill (people who are
hiring), but the mechanics apply to any skill that searches LinkedIn posts.

## URL and facets

```
https://www.linkedin.com/search/results/content/?keywords=<q>&datePosted=%22past-24h%22&sortBy=%22date_posted%22
```

- `sortBy`: `"date_posted"` (Latest) or `"relevance"`. Use Latest for anything daily.
- `datePosted`: `"past-24h"`, `"past-week"`, `"past-month"`.
- `postedBy=%5B%22first%22%5D` restricts to 1st degree connections.
- `contentType` exists, but its "Job posts" value filters out exactly the hand-written posts a
  search for people wants.

## Query grammar

- **Two terms, three at most.** The search ANDs everything; a third constraint such as a city tends to
  return nothing over a whole week. Drop a term when a query goes empty.
- **A hiring phrase with a title alone does not filter.** It returns agencies on other continents,
  unrelated industries and near-miss titles. Pairing the phrase with one domain term removes that
  noise, because it never contains the domain word.
- **In a second language, the verb goes in that language and the job title stays in English.** In
  Spanish, every query that quoted a Spanish job title returned zero results over a week, while the
  same hiring verb with the English title returned real posts. Localised domain words can be equally
  dead: use the word people actually write.
- **Some phrases belong to two languages.** `"estamos contratando"` is Portuguese as well as Spanish
  and on its own drags in the other market.

## The dominant false positive

Content search indexes the author's headline as well as the post. A query for a job title returns
people who have that title and are looking for work as often as people hiring for it: the top hit for
a "hiring" query with a title was a post reading "I'm looking for my next role" by someone whose
headline carried that exact title. Tell a hiring post from a candidate post by the direction of the ask
in the body, never by the title.

## No permalink on the results page

The results DOM carries no `urn:li:activity` and no `/feed/update/` link, and each post's timestamp
links back to the search URL itself. What the page does carry is the author's profile URL: `read_page`
with `filter: "interactive"` lists the `/in/<slug>` links in post order, each one twice. So the
deliverable of a content search is the profile link, never a constructed post URL. The CSS class names
are build hashes that change between deploys; never key a scraper on them.

## Reading the page

Three posts render on load; each scroll of about ten wheel ticks adds roughly three more. Results
stream in after load, so an immediate read returns an empty shell. The cheapest reliable read:

```js
await new Promise(r => setTimeout(r, 2500));
document.querySelector('main').innerText
```

`get_page_text` is the unbounded fallback.

## Links

[[2026-09-21-reference-where-claude-in-chrome-is-available]] ·
[[2026-09-22-decision-job-search-accepts-onsite-and-hybrid-in-a-configured-area]]
