#!/usr/bin/env python3
"""Collect tweets read through the browser into a JSONL file, deduplicated by status id.

  x_items.py add FILE            read JSON objects (one per line) on stdin and merge them
  x_items.py pending FILE        print status URLs still marked full=false
  x_items.py render FILE [--md]  print the collection, newest first (JSON lines or markdown)
  x_items.py stats FILE          counts per kind and per author

Record fields: url (https://x.com/<handle>/status/<id>), handle, name, time (ISO or the
label seen), text, kind (post | reply | quote | repost | article), title (articles),
quoted_url, reposted_by, counts {replies, reposts, likes, views}, full (bool).
Merging keeps the longest text and prefers full=true, so re-adding an item after opening
its status page upgrades it.
"""
import json
import re
import sys
from collections import Counter

ID_RE = re.compile(r"/status/(\d+)")


def load(path):
    items = {}
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if line:
                    rec = json.loads(line)
                    items[key(rec)] = rec
    except FileNotFoundError:
        pass
    return items


def key(rec):
    m = ID_RE.search(rec.get("url", ""))
    if not m:
        raise SystemExit(f"record without a status url: {rec}")
    return m.group(1)


def merge(old, new):
    out = dict(old)
    for k, v in new.items():
        if v in (None, "", [], {}):
            continue
        if k == "text" and len(v) < len(old.get("text", "")):
            continue
        if k == "full" and old.get("full"):
            continue
        out[k] = v
    return out


def save(path, items):
    with open(path, "w") as fh:
        for rec in sorted(items.values(), key=lambda r: int(key(r)), reverse=True):
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    cmd, path = sys.argv[1], sys.argv[2]
    items = load(path)
    if cmd == "add":
        n = 0
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            rec["url"] = "https://x.com" + rec["url"] if rec["url"].startswith("/") else rec["url"]
            k = key(rec)
            items[k] = merge(items[k], rec) if k in items else rec
            n += 1
        save(path, items)
        print(f"merged {n}, total {len(items)}, pending {sum(not r.get('full') for r in items.values())}")
    elif cmd == "pending":
        for rec in sorted(items.values(), key=lambda r: int(key(r)), reverse=True):
            if not rec.get("full"):
                print(rec["url"])
    elif cmd == "render":
        recs = sorted(items.values(), key=lambda r: int(key(r)), reverse=True)
        if "--md" in sys.argv:
            for r in recs:
                head = f"**{r.get('name', '')}** @{r.get('handle', '')} · {r.get('time', '')} · {r.get('kind', 'post')}"
                print(f"- [{head}]({r['url']})")
                if r.get("title"):
                    print(f"  **{r['title']}**")
                for ln in r.get("text", "").splitlines():
                    print(f"  {ln}")
                if r.get("quoted_url"):
                    print(f"  Quoted: {r['quoted_url']}")
                print()
        else:
            for r in recs:
                print(json.dumps(r, ensure_ascii=False))
    elif cmd == "stats":
        recs = list(items.values())
        print("total", len(recs), "full", sum(bool(r.get("full")) for r in recs))
        print("kinds", dict(Counter(r.get("kind", "post") for r in recs)))
        print("authors", Counter(r.get("handle") for r in recs).most_common(15))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
