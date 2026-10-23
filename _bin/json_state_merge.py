#!/usr/bin/env python3
"""Git merge driver for the machine-written JSON state files (`merge=brain-json-state`).

    json_state_merge.py <base> <ours> <theirs>      # git's %O %A %B; the result goes to <ours>

Several machines can write the same state file: a scheduled routine on one, an interactive
session on another. Git's line merge cannot merge two edits of one JSON document, so every
sync between them conflicts, and a conflict in the middle of a sync's rebase can leave the
vault stuck mid-rebase. A JSON document can be merged by key instead:

- dicts: the union of keys; a key one side left untouched takes the other side's value;
  a key both sides changed is merged recursively.
- lists: ours in order, then what theirs added; an item one side removed from the base
  stays removed. Items compare by their canonical JSON, so two copies of the same event
  collapse into one.
- one scalar both sides changed: both went down from the base (a budget being spent on two
  machines) → the base minus both spends; otherwise the larger value (counters and ISO
  timestamps only move forward); values of different types → ours.

Exits 0 with the merged file written to <ours>, or 1 when a side is not valid JSON, which
makes git fall back to an ordinary conflict. The attribute is declared in .gitattributes;
the guardian sets the driver in the vault's .git/config on every machine.
"""
import json
import sys


def _key(v):
    return json.dumps(v, sort_keys=True, ensure_ascii=False)


_MISSING = object()


def merge_scalar(base, ours, theirs):
    if isinstance(ours, bool) or isinstance(theirs, bool):
        return ours
    nums = (int, float)
    if isinstance(ours, nums) and isinstance(theirs, nums):
        if isinstance(base, nums) and not isinstance(base, bool) and ours < base and theirs < base:
            return ours + theirs - base
        return max(ours, theirs)
    if isinstance(ours, str) and isinstance(theirs, str):
        return max(ours, theirs)
    if ours is None:
        return theirs
    if theirs is None:
        return ours
    return ours


def merge_list(base, ours, theirs):
    base_keys = {_key(x) for x in (base if isinstance(base, list) else [])}
    ours_keys = {_key(x) for x in ours}
    theirs_keys = {_key(x) for x in theirs}
    out, seen = [], set()
    for x in ours:
        k = _key(x)
        if k in seen or (k in base_keys and k not in theirs_keys):
            continue
        seen.add(k)
        out.append(x)
    for x in theirs:
        k = _key(x)
        if k in seen or k in base_keys:
            continue
        seen.add(k)
        out.append(x)
    return out


def merge(base, ours, theirs):
    if _key(ours) == _key(theirs):
        return ours
    if base is not _MISSING and _key(ours) == _key(base):
        return theirs
    if base is not _MISSING and _key(theirs) == _key(base):
        return ours
    if isinstance(ours, dict) and isinstance(theirs, dict):
        b = base if isinstance(base, dict) else {}
        out = {}
        for k in list(ours.keys()) + [k for k in theirs if k not in ours]:
            bv = b.get(k, _MISSING)
            if k not in theirs:
                if bv is not _MISSING and _key(bv) == _key(ours[k]):
                    continue                          # theirs deleted it, ours left it alone
                out[k] = ours[k]
            elif k not in ours:
                if bv is not _MISSING and _key(bv) == _key(theirs[k]):
                    continue                          # ours deleted it, theirs left it alone
                out[k] = theirs[k]
            else:
                out[k] = merge(bv, ours[k], theirs[k])
        return out
    if isinstance(ours, list) and isinstance(theirs, list):
        return merge_list(None if base is _MISSING else base, ours, theirs)
    return merge_scalar(None if base is _MISSING else base, ours, theirs)


def indent_of(text):
    """The indent the file already uses, so a merge does not rewrite every line."""
    for line in text.splitlines()[1:]:
        stripped = line.lstrip(" ")
        if stripped and stripped != line:
            return len(line) - len(stripped)
        if stripped:
            return None
    return None


def merge_files(base_path, ours_path, theirs_path):
    with open(ours_path, encoding="utf-8") as fh:
        ours_text = fh.read()
    try:
        ours = json.loads(ours_text)
        with open(theirs_path, encoding="utf-8") as fh:
            theirs = json.load(fh)
    except ValueError:
        return 1
    try:
        with open(base_path, encoding="utf-8") as fh:
            base_text = fh.read()
        base = json.loads(base_text) if base_text.strip() else _MISSING
    except (OSError, ValueError):
        base = _MISSING
    result = merge(base, ours, theirs)
    out = json.dumps(result, ensure_ascii=False, indent=indent_of(ours_text))
    if ours_text.endswith("\n"):
        out += "\n"
    with open(ours_path, "w", encoding="utf-8") as fh:
        fh.write(out)
    return 0


def main(argv):
    if len(argv) < 4:
        print("usage: json_state_merge.py <base> <ours> <theirs>", file=sys.stderr)
        return 2
    return merge_files(argv[1], argv[2], argv[3])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
