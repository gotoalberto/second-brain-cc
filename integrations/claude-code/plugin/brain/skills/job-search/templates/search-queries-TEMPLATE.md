# Job search queries

Copy this file to `80-Private/job-search/search-queries.md` in your vault and fill it in. Categories
are run in order: the first three on a normal day, all of them on a broad run.

## Category 1: <name>

- Queries: "<exact role title> remote", "<role title> <domain term>"
- Sources: <job boards or sites you trust for this category>
- Notes: <what this source gets wrong, e.g. its location column shows a nominal city>

## Category 2: <name>

- Queries:
- Sources:
- Notes:

## Category 3: <name>

- Queries:
- Sources:
- Notes:

## LinkedIn hiring posts

Queries for step 2b, run in LinkedIn's content search (see `reference/linkedin-hiring-posts.md`). Each
is one hiring phrase and one domain term from your profile, two terms and three at most. A bare title
matches people with that title who are looking for work.

- In English, last 24 hours: `hiring "<target title>" <domain term>`, `"we're hiring" <role area> <domain term>`,
  `"looking for a" "<target title>" <domain term>`
- In your second language, if you search one, last week: `"<hiring phrase in that language>" "<target title>"`
- Network pass, 1st connections only, last week: `"we're hiring"`, `"<hiring phrase in that language>"`

## LinkedIn job search

Queries for step 2c, run in LinkedIn's logged in job search (see `reference/linkedin-jobs-search.md`).
Filters are written into the text: seniority words, the target titles joined with "or", one domain
per query. Run each once with your country's `geoId` and once, prefixed with `remote `, with the
wider region's. About eight queries, up to two pages each.

| # | geoId | keywords |
|---|---|---|
| 1 | <your country id> | <seniority words> <title> or <title> in <domain 1> |
| 2 | <your country id> | <seniority words> <title> or <title> in <domain 2> |
| 3 | <region id> | remote <seniority words> <title> or <title> in <domain 1> |

## Calibration notes

Write down what you learn about each source as the searches run, so the next run does not repeat the
mistake: exact title phrases that work, filters that let hybrid roles through, sites that are often
stale.
