#!/usr/bin/env python3
"""Controlled client for twitterapi.io, a paid third-party API for reading X/Twitter content.

  twitterapi_io.py user-tweets --username NAME [--user-id ID] [--cursor C] [--include-replies]
  twitterapi_io.py list-timeline LIST_ID [--cursor C]
  twitterapi_io.py search QUERY [--type Latest|Top] [--cursor C]
  twitterapi_io.py user-info NAME
  twitterapi_io.py tweets-by-ids ID,ID,...

Prints the API's raw JSON on stdout. An HTTP error prints {"_http_error": code, "_body": ...}
and exits 1.

The key (the `x-api-key` header) lives in the user's KeePass database at
kp://apis/twitterapi-io and is read once per run through `kp.py get ... --pipe cat`: never in
argv, never printed, never logged. kp.py is found through BRAIN_KP_SCRIPT, else
<vault>/_bin/kp.py, the vault being BRAIN_VAULT or the path the installer wrote below.

Window mode (importable, and `--hours N` on user-tweets, list-timeline and search):
read_window() pages with next_cursor until every tweet of the last N hours has been read,
dedupes by id, and stops at a page cap. It says whether the window was really covered.
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = os.environ.get("TWITTERAPI_IO_BASE_URL") or "https://api.twitterapi.io"
KP_ENTRY = "apis/twitterapi-io"
INSTALLED_VAULT = "__VAULT__"  # the installer writes this machine's vault path here


def kp_script():
    explicit = os.environ.get("BRAIN_KP_SCRIPT")
    if explicit:
        return explicit
    vault = os.environ.get("BRAIN_VAULT") or INSTALLED_VAULT
    if not os.path.isdir(vault):
        vault = os.path.expanduser("~/Brain")
    return os.path.join(vault, "_bin", "kp.py")


_KEY = None


class TwitterApiError(RuntimeError):
    """An HTTP error from twitterapi.io; the message carries the code and the start of the body."""


def get_api_key():
    global _KEY
    if _KEY:
        return _KEY
    try:
        result = subprocess.run([sys.executable, kp_script(), "get", KP_ENTRY, "--pipe", "cat"],
                                capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print("could not read the API key from KeePass: %s" % exc, file=sys.stderr)
        sys.exit(1)
    if result.returncode != 0:
        print("could not read the API key from KeePass: %s" % result.stderr.strip(), file=sys.stderr)
        sys.exit(1)
    key = result.stdout.strip()
    if not key:
        print("KeePass returned an empty API key for %s" % KP_ENTRY, file=sys.stderr)
        sys.exit(1)
    _KEY = key
    return key


def _url(path, params):
    url = f"{BASE_URL}{path}"
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
    return url


def fetch_page(path, params=None):
    """One request, decoded JSON. Raises TwitterApiError on an HTTP error."""
    req = urllib.request.Request(_url(path, params), headers={"x-api-key": get_api_key()})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        raise TwitterApiError(f"HTTP {e.code}: {body[:300]}") from None


# ---------- window mode ----------

MAX_PAGES_CAP = 25  # hard ceiling whatever the caller asks: each page is about 20 paid tweets
WHY_OLDER = "oldest tweet fetched is older than the window"
WHY_END = "no more pages from the API"
WHY_STALE = "a page brought no new tweets"


def parse_created(t):
    """createdAt of a tweet as an aware datetime, None when missing or unreadable."""
    try:
        return dt.datetime.strptime(t["createdAt"], "%a %b %d %H:%M:%S %z %Y")
    except Exception:
        return None


def page_tweets(d):
    """(tweets, next_cursor or "") from any endpoint shape: top level, or nested under data."""
    inner = d.get("data") if isinstance(d.get("data"), dict) else {}
    tweets = d.get("tweets") or inner.get("tweets") or []
    more = bool(d.get("has_next_page", inner.get("has_next_page")))
    nxt = d.get("next_cursor") or inner.get("next_cursor") or ""
    return tweets, (nxt if more else "")


def window_request(kind, target, hours, query_type="Latest", include_replies=False, now=None):
    """(path, params, chrono) for one window read.

    kind: "list" (target = list id), "search" (target = query; since_time is appended),
    "user" (target = username). chrono says whether the feed comes newest first."""
    now = now or dt.datetime.now(dt.timezone.utc)
    if kind == "list":
        return "/twitter/list/tweets_timeline", {"listId": target}, True
    if kind == "user":
        return "/twitter/user/last_tweets", {
            "userName": target, "includeReplies": "true" if include_replies else None}, True
    if kind == "search":
        since = int((now - dt.timedelta(hours=hours)).timestamp())
        return "/twitter/tweet/advanced_search", {
            "query": f"{target} since_time:{since}", "queryType": query_type}, query_type == "Latest"
    raise ValueError(f"unknown window kind {kind!r}")


def read_window(kind, target, hours, max_pages=5, query_type="Latest", include_replies=False,
                page_fn=None, now=None):
    """Every tweet of the last `hours` from a list, a search or a user, paging with next_cursor.

    Stops when the oldest tweet fetched is older than the window (chronological feeds only;
    a Top search is not ordered by time), when the API has no next page, when a page brings
    nothing new, or at max_pages (clamped to 1..MAX_PAGES_CAP). Tweets are deduped by id and
    returned as fetched, without filtering by time: callers cut and sort.

    Returns a dict: tweets, pages, oldest (datetime or None), cut (datetime), covered (bool),
    why (text). covered=False means the result is partial: absence proves nothing.
    page_fn(path, params) -> decoded JSON replaces the HTTP call in tests."""
    page_fn = page_fn or fetch_page
    now = now or dt.datetime.now(dt.timezone.utc)
    cut = now - dt.timedelta(hours=hours)
    cap = max(1, min(int(max_pages), MAX_PAGES_CAP))
    path, params, chrono = window_request(kind, target, hours, query_type, include_replies, now)
    tweets, seen, cursor, pages, oldest = [], set(), "", 0, None
    covered, why = False, ""
    while True:
        batch, cursor = page_tweets(page_fn(path, dict(params, cursor=cursor or None)))
        pages += 1
        new = 0
        for t in batch:
            tid = t.get("id")
            if tid is not None and tid in seen:
                continue
            seen.add(tid)
            tweets.append(t)
            new += 1
            w = parse_created(t)
            if w and (oldest is None or w < oldest):
                oldest = w
        if chrono and oldest is not None and oldest < cut:
            covered, why = True, WHY_OLDER
        elif not cursor:
            covered, why = True, WHY_END
        elif not new:
            why = WHY_STALE
        elif pages >= cap:
            why = f"page cap {cap} reached with more pages left"
        else:
            continue
        break
    return {"tweets": tweets, "pages": pages, "oldest": oldest, "cut": cut, "covered": covered, "why": why}


def window_summary(res, hours):
    """One line saying what was really read, for stderr."""
    o = res["oldest"]
    old = f"oldest {o:%Y-%m-%d %H:%M} UTC" if o else "no dated tweet"
    status = "window covered" if res["covered"] else "window NOT covered, partial result"
    return (f"-- {len(res['tweets'])} tweets in {res['pages']} page(s); {old}; asked {hours:g}h; "
            f"{status} ({res['why']})")


def call(path, params=None):
    key = get_api_key()
    url = BASE_URL + path
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
    req = urllib.request.Request(url, headers={"x-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        print(json.dumps({"_http_error": exc.code, "_body": body}))
        sys.exit(1)
    print(body)


def add_window_args(sp):
    sp.add_argument("--hours", type=float, help="window mode: page until every tweet of the last N hours is read")
    sp.add_argument("--max-pages", type=int, default=5,
                    help=f"window mode page cap (default 5, never more than {MAX_PAGES_CAP})")


def window_cli(args, page_fn=None):
    """Window mode on the CLI: one JSON object on stdout, the summary line on stderr."""
    if args.cmd == "user-tweets":
        if not args.username:
            print("window mode on user-tweets needs --username", file=sys.stderr)
            sys.exit(2)
        kind, target, qtype = "user", args.username, "Latest"
    elif args.cmd == "list-timeline":
        kind, target, qtype = "list", args.list_id, "Latest"
    else:
        kind, target, qtype = "search", args.query, args.query_type
    try:
        res = read_window(kind, target, args.hours, args.max_pages, qtype,
                          getattr(args, "include_replies", False), page_fn)
    except TwitterApiError as e:
        print(json.dumps({"_error": str(e)}))
        sys.exit(1)
    out = dict(res, oldest=res["oldest"].isoformat() if res["oldest"] else None,
               cut=res["cut"].isoformat(), hours=args.hours)
    print(json.dumps(out))
    print(window_summary(res, args.hours), file=sys.stderr)
    return res


def main(argv=None, page_fn=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    u = sub.add_parser("user-tweets", help="recent tweets from one account; the response nests them under data.tweets")
    u.add_argument("--username", help="screen name, without the @")
    u.add_argument("--user-id")
    u.add_argument("--cursor", default="")
    u.add_argument("--include-replies", action="store_true")
    add_window_args(u)

    lt = sub.add_parser("list-timeline", help="recent tweets from an X list; tweets at the top level")
    lt.add_argument("list_id")
    lt.add_argument("--cursor", default="")
    add_window_args(lt)

    s = sub.add_parser("search", help="advanced search; tweets at the top level")
    s.add_argument("query", help="for example: '(solar OR wind) from:someaccount since_time:1700000000'")
    s.add_argument("--type", choices=["Latest", "Top"], default="Latest", dest="query_type")
    s.add_argument("--cursor", default="")
    add_window_args(s)

    ui = sub.add_parser("user-info", help="profile of one account")
    ui.add_argument("username")

    t = sub.add_parser("tweets-by-ids", help="specific tweets by id")
    t.add_argument("ids", help="comma-separated tweet ids")

    a = p.parse_args(argv)

    if getattr(a, "hours", None) is not None:
        return window_cli(a, page_fn)
    if a.cmd == "user-tweets":
        if not a.username and not a.user_id:
            print("user-tweets needs --username or --user-id", file=sys.stderr)
            sys.exit(2)
        call("/twitter/user/last_tweets", {"userName": a.username, "userId": a.user_id, "cursor": a.cursor,
                                           "includeReplies": "true" if a.include_replies else None})
    elif a.cmd == "list-timeline":
        call("/twitter/list/tweets_timeline", {"listId": a.list_id, "cursor": a.cursor})
    elif a.cmd == "search":
        call("/twitter/tweet/advanced_search", {"query": a.query, "queryType": a.query_type, "cursor": a.cursor})
    elif a.cmd == "user-info":
        call("/twitter/user/info", {"userName": a.username})
    elif a.cmd == "tweets-by-ids":
        call("/twitter/tweets", {"tweet_ids": a.ids})


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        sys.stderr.close()
        sys.exit(0)
