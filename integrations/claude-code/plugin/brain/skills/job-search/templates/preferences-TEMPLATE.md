# Job search preferences

Copy this file to `80-Private/job-search/preferences.md` in your vault and fill it in. `80-Private/` is
local and never pushed.

## Location and work authorization

- Based in: <country, and time zone>
- Can work for employers in: <countries or regions where you can legally be hired or contracted>

## Remote rules

- Remote only: <yes | no>
- On-site or hybrid acceptable in: <your city or area, or "never">
  Roles there qualify in any work mode and share the top tier with fully remote roles; on-site or
  hybrid anywhere else fails. Each run then searches twice: remote, and this area with no work mode
  filter.
- Time zone overlap you can accept: <hours>

## Money and contract

- Salary floor, when published: <amount and currency, per year>
- Salary floor for contractor or freelance roles: <amount>
- Contract types, in order of preference: <permanent | contractor | freelance>
- An unpublished salary is not a reason to exclude (change this line if you disagree).

## Languages

The languages you work in come from `profile.md`. A posting that requires another one is dropped
from every list and only counted in the report; a posting written entirely in another language with
no stated working language counts as requiring it. An optional language passes, with a note that it
adds points.

- Languages that should also pass when required, beyond the profile: <languages, or "none">

## Seniority

How seniority words in a title and in the body are treated. A title word listed as a ranking signal
lets the posting pass and ranks it below plainer titles; only body wording listed below fails it.

- Title words that only lower the rank: <e.g. Senior, or "none">
- Title words that fail a posting: <e.g. Lead, Principal, or "none">
- Body wording that fails a posting: <e.g. managing a team, owning the whole function, or "none">

## Hard exclusions

Anything that should fail a posting outright: sectors, role types, travel requirements. Required
languages are handled under Languages above.

- <exclusion>

## Flags

Things that should be highlighted for you but not excluded.

- <flag, e.g. degree required>

## CV

- CV file used only to judge fit (optional): <path to a file on this machine, or "none">

## Report

- Send the report to: <email address>
- Send it from Google account: <account name as configured in google.py during the first run>
- Report language: <language>
- Days to run: <e.g. weekdays>
