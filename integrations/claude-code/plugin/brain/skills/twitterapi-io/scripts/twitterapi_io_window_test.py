#!/usr/bin/env python3
"""Tests for twitterapi_io.py window mode.

No network and no paid call: HTTP is a fake page function, or a patched urlopen with a fake key.
Run standalone: python3 twitterapi_io_window_test.py
"""
import contextlib
import datetime as dt
import io
import json
import os
import sys
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import twitterapi_io as tw  # noqa: E402

ok, fail = [], []
NOW = dt.datetime.now(dt.timezone.utc)


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail and not cond else ""))


def tweet(tid, hours_ago, likes=0, user="someone"):
    when = NOW - dt.timedelta(hours=hours_ago)
    return {"id": str(tid), "createdAt": when.strftime("%a %b %d %H:%M:%S +0000 %Y"), "likeCount": likes,
            "retweetCount": 0, "viewCount": 0, "text": f"tweet {tid}", "url": f"https://x.com/{user}/status/{tid}",
            "author": {"userName": user, "followers": 10}, "lang": "en"}


class Pages:
    """Fake page_fn: serves pages in order, records every request."""

    def __init__(self, pages, nested=False):
        self.pages, self.nested, self.calls = pages, nested, []

    def __call__(self, path, params):
        self.calls.append((path, dict(params)))
        i = len(self.calls) - 1
        tweets = self.pages[i] if i < len(self.pages) else []
        more = i + 1 < len(self.pages)
        body = {"tweets": tweets, "has_next_page": more, "next_cursor": f"c{i + 1}" if more else ""}
        return {"data": body} if self.nested else body


def test_read_window():
    print("== read_window ==")
    pg = Pages([[tweet(1, 1), tweet(2, 5)], [tweet(3, 10), tweet(4, 30)], [tweet(5, 40)]])
    r = tw.read_window("list", "L1", 24, max_pages=5, page_fn=pg, now=NOW)
    check("a list stops once the oldest tweet is older than the window", r["pages"] == 2 and r["covered"], r)
    check("the reason says the window was passed", r["why"] == tw.WHY_OLDER, r["why"])
    check("the second request carries the cursor of the first", pg.calls[1][1].get("cursor") == "c1", pg.calls)
    check("the first request carries no cursor", pg.calls[0][1].get("cursor") is None, pg.calls[0])
    check("list requests hit the list endpoint with the id",
          pg.calls[0][0] == "/twitter/list/tweets_timeline" and pg.calls[0][1]["listId"] == "L1", pg.calls[0])
    check("oldest is the oldest tweet fetched", abs((r["oldest"] - (NOW - dt.timedelta(hours=30))).total_seconds()) < 2)

    pg = Pages([[tweet(1, 1)], [tweet(2, 2)], [tweet(3, 3)], [tweet(4, 4)]])
    r = tw.read_window("list", "L1", 24, max_pages=2, page_fn=pg, now=NOW)
    check("the page cap stops it and the window is not covered",
          r["pages"] == 2 and not r["covered"] and "page cap 2" in r["why"], r)

    pg = Pages([[tweet(1, 1)]] * 40)
    r = tw.read_window("list", "L1", 24, max_pages=999, page_fn=pg, now=NOW)
    check("a page with nothing new stops a loop of repeated pages", r["pages"] == 2 and r["why"] == tw.WHY_STALE, r)

    pg = Pages([[tweet(i, 1)] for i in range(40)])
    r = tw.read_window("list", "L1", 24, max_pages=999, page_fn=pg, now=NOW)
    check(f"max_pages is clamped to {tw.MAX_PAGES_CAP}", r["pages"] == tw.MAX_PAGES_CAP, r["pages"])

    pg = Pages([[tweet(1, 1), tweet(2, 2)], [tweet(2, 2), tweet(3, 3)]])
    r = tw.read_window("list", "L1", 24, page_fn=pg, now=NOW)
    check("tweets repeated across pages are kept once", [t["id"] for t in r["tweets"]] == ["1", "2", "3"], r["tweets"])
    check("the end of the feed counts as covered", r["covered"] and r["why"] == tw.WHY_END, r)

    pg = Pages([[tweet(1, 1), tweet(2, 50)], [tweet(3, 2)]])
    r = tw.read_window("search", "stablecoins", 24, query_type="Top", page_fn=pg, now=NOW)
    check("a Top search is not chronological, an old tweet does not stop it", r["pages"] == 2 and r["covered"], r)
    since = int((NOW - dt.timedelta(hours=24)).timestamp())
    check("search appends since_time to the query",
          pg.calls[0][1]["query"] == f"stablecoins since_time:{since}" and pg.calls[0][1]["queryType"] == "Top",
          pg.calls[0])

    pg = Pages([[tweet(1, 1)], [tweet(2, 30)]], nested=True)
    r = tw.read_window("user", "someaccount", 24, page_fn=pg, now=NOW)
    check("user tweets read the nested data.tweets shape and page on",
          r["pages"] == 2 and r["covered"] and len(r["tweets"]) == 2, r)
    check("user tweets hit last_tweets with the username",
          pg.calls[0][0] == "/twitter/user/last_tweets" and pg.calls[0][1]["userName"] == "someaccount", pg.calls[0])


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_http_and_cli():
    print("== fetch_page and CLI ==")
    seen = []

    def fake_urlopen(req, timeout=30):
        seen.append(req)
        return FakeResp(json.dumps({"tweets": [tweet(9, 1)], "has_next_page": False}).encode())

    real_open, real_key = tw.urllib.request.urlopen, tw._KEY
    tw.urllib.request.urlopen, tw._KEY = fake_urlopen, "fake-key"
    try:
        d = tw.fetch_page("/twitter/list/tweets_timeline", {"listId": "L1", "cursor": None})
        check("fetch_page decodes the JSON body", d["tweets"][0]["id"] == "9", d)
        check("the key goes in the x-api-key header, never in the URL",
              seen[0].get_header("X-api-key") == "fake-key" and "fake-key" not in seen[0].full_url, seen[0].full_url)
        check("empty params are left out of the URL", "cursor" not in seen[0].full_url, seen[0].full_url)

        def http_error(req, timeout=30):
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many", {}, io.BytesIO(b"slow down"))
        tw.urllib.request.urlopen = http_error
        try:
            tw.fetch_page("/x", {})
            check("an HTTP error raises TwitterApiError", False)
        except tw.TwitterApiError as e:
            check("an HTTP error raises TwitterApiError", "429" in str(e) and "slow down" in str(e), e)
    finally:
        tw.urllib.request.urlopen, tw._KEY = real_open, real_key

    pg = Pages([[tweet(1, 1)], [tweet(2, 30)]])
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        tw.main(["list-timeline", "L1", "--hours", "24", "--max-pages", "3"], page_fn=pg)
    j = json.loads(out.getvalue())
    check("--hours prints one JSON object with the window result",
          j["pages"] == 2 and j["covered"] and len(j["tweets"]) == 2 and j["hours"] == 24, j)
    check("--hours prints a summary line on stderr", "window covered" in err.getvalue(), err.getvalue())


def main():
    test_read_window()
    test_http_and_cli()
    print(f"\nRESULT: {len(ok)} passed, {len(fail)} failed")
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
