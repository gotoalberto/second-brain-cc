# LinkedIn job notifications in the browser (step 2d)

Saved job alerts and LinkedIn's recommendations often arrive only as in-app notifications in the
Jobs tab, not by email, so neither the mail nor the logged in search of step 2c sees them.

## What is there

`https://www.linkedin.com/notifications/?filter=jobs` (the Jobs tab of the notifications). Three
kinds of item:

- **Saved alerts**, "`<alert keywords>`: new opportunities in `<place>`".
- **Similar jobs**, "See 10 jobs similar to one you recently viewed: `<role>` at `<company>`".
- **A recommended job**, "`<role>` at `<company>` recommended for you."

Each "View jobs" opens `/jobs/search-results/` with the alert's keywords, `geoId`, `f_TPR=a<epoch>-`
(new since the alert was last seen) and `origin=SEMANTIC_SEARCH_JOB_ALERT_IN_APP_NOTIFICATION`. It is
the same page as step 2c, so the card reading snippet of `linkedin-jobs-search.md` works unchanged.

## Method

1. Navigate to the Jobs tab and wait 3 s. Run this snippet. It keeps the links in the page and
   returns only age, text and index, because the tool blocks any output with a query string:

   ```js
   const by=new Map(); for(const a of document.querySelectorAll('main a')){ if(!/\/jobs\//.test(a.pathname)) continue; if(by.has(a.href)) continue; let n=a; while(n&&!/\n\s*\d+\s*(m|h|d|w|mo|min|hr)\s*$/.test(n.innerText||'')) n=n.parentElement; if(!n) continue; const l=n.innerText.split('\n').map(s=>s.trim()).filter(x=>x&&!/^View jobs?$/.test(x)); by.set(a.href,{age:l[l.length-1], text:l.slice(0,-1).join(' / ').slice(0,150), href:a.href}); } window.jobNotifs=[...by.values()]; window.jobNotifs.map((x,i)=>i+': ['+x.age+'] '+x.text).join('\n')
   ```

   The classes are obfuscated, so the snippet walks up from each link to the block that ends in the
   age ("1h", "4h", "1d"). If it returns nothing on a page that shows notifications, the markup
   changed: fix the snippet here, test it and carry on.

2. **Window:** every item newer than the previous run (a day, or since the last report when a day
   was missed); when in doubt, the last 48 hours. Scroll the list if the oldest item shown is still
   inside the window. Write the count in the report.

3. For each item in the window, from the Jobs tab: run the snippet again (the page reloads, the
   window variable is gone) and open item i with
   `setTimeout(()=>{location.href=window.jobNotifs[i].href},100)`. Wait 3 s, then scroll the cards in
   and read them with the snippet of `linkedin-jobs-search.md`, both pages when the total is over 25.
   A recommended job opens on its own card: read that one.

4. Every card goes to steps 3 to 7 like any other posting, with "via LinkedIn notification" as the
   source in the table. An alert whose title is outside the targets is still opened and read: the user
   saved it, and the cards often hold roles that fit. The gates decide, not the alert's name. Dedup by
   LinkedIn job id against the other steps, so a posting found twice is one row.

Read only: never Easy Apply, save, follow, dismiss or turn off a notification, and never change an
alert. Opening an alert moves its "since last seen" point, which is how the phone app works too. No
browser: one line in the report, and the run carries on.
