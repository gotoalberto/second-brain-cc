# LinkedIn job search in the browser (step 2c)

The logged in LinkedIn job search, run through Claude in Chrome. It is the same page the user's job
alerts open, and it shows what the guest endpoints and job boards miss: semantic search, the
industry pills and signals on each card (already applied, early applicant, connections at the
company).

## How the page works (measured)

- URL: `https://www.linkedin.com/jobs/search-results/?keywords=<text>&geoId=<id>&f_TPR=<window>[&start=25]`
- **The search is semantic.** The industry pills (Fintech, Banking, Healthcare, Software...) do not
  add a parameter: clicking one rewrites the query as `<query> in <industry>`. So the pills are
  reproduced by writing the domain into `keywords`. The pills on offer change with the query.
- **The filters of "All filters" are also rewritten into the query** (Remote becomes "remote",
  Director plus Executive becomes "director or executive") plus an opaque `f_SAL` id. The old
  `f_WT=2` parameter is **dropped** by this page (results came back hybrid). Write "remote" and the
  seniority words into `keywords` instead; tested, every result then came back Remote.
- Filters that exist: Date posted (24 hours, week, month), Easy Apply, Under 10 applicants, In my
  network, Verified, Workplace type, Experience level (Entry, Senior, Manager, Director, Executive),
  Employment type, Company. Only date travels as a clean parameter (`f_TPR`).
- `f_TPR=r86400` is 24 hours, `r604800` a week. An alert link uses `a<epoch>-` (since the alert was
  last seen); use `r86400` daily, `r604800` when yesterday's run did not happen.
- `geoId`: a country id covers on-site, hybrid and "<Country> (Remote)" roles there; the European
  Union is `91000000`. Find a country's id by searching it once on the page and reading the URL.
- 25 cards a page; next page `&start=25`, then 50. The count is in the text "`N results`".
- Semantic matching is loose: a "banking or fintech" query also returns unrelated consumer apps.
  The results still go through the normal gates (steps 3 to 7); the query only widens the net.
- The same role shows up once per country. Keep one row per company and title, the one in the
  user's country if present.

## The query set

The queries live in the user's `search-queries.md`, section "LinkedIn job search". A good set is
small, about eight queries of up to two pages each: the target titles joined with "or", the
seniority words ("director or executive", "senior") and one domain per query, each run once for
the user's country and once, prefixed with `remote `, for the wider region. Keep it small: each
page costs a load.

## Reading the cards (tested snippet, javascript_tool)

Run after the page has loaded (wait 3 s). **Use this snippet, not a screenshot or
`get_page_text`**: a run that read the screen saw "10 cards per page" and never went to page 2. The
snippet reads every card of the page, 25 when the search has that many. If it returns fewer than 25
while `total` is larger, scroll the cards in first:
`for(const c of document.querySelectorAll('div[role=button][componentkey]')){c.scrollIntoView({block:'center'});await new Promise(r=>setTimeout(r,250))}`
and run it again. When `total` is over 25, load `&start=25` too; it is not optional. It returns id,
title, company, location and the signals line. Do not return `location.href` or any URL with a
query string: the tool blocks the output.

```js
const cards=[...document.querySelectorAll('div[role=button][componentkey]')].filter(c=>c.innerText.trim().length>20);
const total=(document.body.innerText.match(/([\d,+]+) results/)||[])[1];
JSON.stringify({total, rows:cards.map(c=>{let l=c.innerText.split('\n').map(s=>s.trim()).filter(Boolean);
 const t=l[0].replace(/ \(Verified job\)$/,''); if(l[1]===t) l.splice(1,1);
 const sig=l.filter(x=>/early applicant|connection|alumni|Applied|Viewed|Saved|Posted/.test(x)).join('; ');
 return [(c.outerHTML.match(/\b4\d{9}\b/)||[''])[0],t,l[1],l[2],sig].join(' | ')})})
```

The link for the table is `https://www.linkedin.com/jobs/view/<id>/`. The signals line carries
"Applied" (already applied on LinkedIn: cross with the history), "Be an early applicant", "N
connections work here" and "Posted N hours ago": they feed the priority in step 7.

If the selector returns 0 cards on a page that shows results, LinkedIn changed its markup: fix the
snippet here (find the title text, walk up to the `div[role=button][componentkey]` card), test it,
and carry on. Never drop the step for that.
