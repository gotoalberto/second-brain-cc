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
"""
import argparse
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


def get_api_key():
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
    return key


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


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    u = sub.add_parser("user-tweets", help="recent tweets from one account; the response nests them under data.tweets")
    u.add_argument("--username", help="screen name, without the @")
    u.add_argument("--user-id")
    u.add_argument("--cursor", default="")
    u.add_argument("--include-replies", action="store_true")

    lt = sub.add_parser("list-timeline", help="recent tweets from an X list; tweets at the top level")
    lt.add_argument("list_id")
    lt.add_argument("--cursor", default="")

    s = sub.add_parser("search", help="advanced search; tweets at the top level")
    s.add_argument("query", help="for example: '(solar OR wind) from:someaccount since_time:1700000000'")
    s.add_argument("--type", choices=["Latest", "Top"], default="Latest", dest="query_type")
    s.add_argument("--cursor", default="")

    ui = sub.add_parser("user-info", help="profile of one account")
    ui.add_argument("username")

    t = sub.add_parser("tweets-by-ids", help="specific tweets by id")
    t.add_argument("ids", help="comma-separated tweet ids")

    a = p.parse_args(argv)

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
