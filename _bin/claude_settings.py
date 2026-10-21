#!/usr/bin/env python3
"""claude_settings.py — the harness's recommended Claude Code settings, merged only with your yes.

  claude_settings.py show  [--example PATH] [--settings PATH]
      what a merge would add to ~/.claude/settings.json; changes nothing
  claude_settings.py merge [--example PATH] [--settings PATH] [--yes]
      add what is missing: `permissions.allow` (and `deny`, `ask`) entries you do not have, and keys
      you have not set. A value you already set is never changed and nothing is removed. Hooks are
      never merged from here: the guardian installs and repairs those (guardian.py repair --hooks-only).
      Asks before writing, unless --yes; without a terminal and without --yes it writes nothing.
      The file is backed up before the write. A value you set differently from the recommendation
      is listed as kept, so you can change it by hand if you want the reference setup.
  claude_settings.py chrome-allow HOST... [--settings PATH] [--yes]
      let Claude in Chrome act on these sites without asking: one `ClaudeInChromeDomain(<host>)`
      allow rule per host. The host is exact: a scheme, a path and a leading `www.` are dropped, a
      port is kept, and wildcards do not work (see the 2026-10-21 Chrome classifier note).

The example is integrations/claude-code/settings.example.json. `__VAULT__` in it becomes the vault
path; keys starting with `_` are comments.
"""

import argparse
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

PLACEHOLDER = "__VAULT__"
LIST_PERMISSIONS = ("allow", "deny", "ask")
CHROME_DOMAIN = "ClaudeInChromeDomain(%s)"


def localize(value, vault):
    if isinstance(value, str):
        return value.replace(PLACEHOLDER, vault)
    if isinstance(value, list):
        return [localize(v, vault) for v in value]
    if isinstance(value, dict):
        return {k: localize(v, vault) for k, v in value.items()}
    return value


def merge(current: dict, example: dict, vault: str):
    """(merged settings, [one line per addition]). Pure: `current` is not modified."""
    wanted = localize({k: v for k, v in example.items() if not k.startswith("_") and k != "hooks"}, vault)
    merged = copy.deepcopy(current)
    changes = []
    for key, value in wanted.items():
        if key == "permissions" and isinstance(value, dict):
            if "permissions" in merged and not isinstance(merged["permissions"], dict):
                continue
            perms = merged.setdefault("permissions", {})
            for pkey, pvalue in value.items():
                if pkey in LIST_PERMISSIONS and isinstance(pvalue, list):
                    have = perms.setdefault(pkey, [])
                    if not isinstance(have, list):
                        continue
                    for item in pvalue:
                        if item not in have:
                            have.append(item)
                            changes.append("permissions.%s += %s" % (pkey, item))
                elif pkey not in perms:
                    perms[pkey] = pvalue
                    changes.append("permissions.%s = %s" % (pkey, json.dumps(pvalue)))
        elif isinstance(value, dict) and isinstance(merged.get(key), dict):
            for sub, subvalue in value.items():
                if sub not in merged[key]:
                    merged[key][sub] = subvalue
                    changes.append("%s.%s = %s" % (key, sub, json.dumps(subvalue)))
        elif key not in merged:
            merged[key] = value
            changes.append("%s = %s" % (key, json.dumps(value)))
    return merged, changes


def kept(current: dict, example: dict, vault: str):
    """One line per recommended value the user has set to something else. A merge keeps those."""
    wanted = localize({k: v for k, v in example.items() if not k.startswith("_") and k != "hooks"}, vault)
    out = []
    for key, value in wanted.items():
        have = current.get(key)
        if not isinstance(value, dict):
            if key in current and have != value:
                out.append("%s = %s (recommended: %s)" % (key, json.dumps(have), json.dumps(value)))
            continue
        if not isinstance(have, dict):
            continue
        for sub, subvalue in value.items():
            if sub in LIST_PERMISSIONS and key == "permissions":
                continue
            if sub in have and have[sub] != subvalue:
                out.append("%s.%s = %s (recommended: %s)" % (key, sub, json.dumps(have[sub]), json.dumps(subvalue)))
    return out


def chrome_host(text: str) -> str:
    """The host Claude in Chrome matches a rule against: no scheme, path or `www.`, port kept."""
    host = (text or "").strip().lower()
    if "://" in host:
        host = host.split("://", 1)[1]
    host = host.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    if host.startswith("www."):
        host = host[4:]
    if not host or "*" in host or any(c.isspace() for c in host):
        raise ValueError("not a host Claude in Chrome can match: %r (exact host, no wildcards)" % text)
    return host


def chrome_rules(hosts):
    """A permissions fragment with one allow rule per host, in the order given, without repeats."""
    rules = []
    for h in hosts:
        rule = CHROME_DOMAIN % chrome_host(h)
        if rule not in rules:
            rules.append(rule)
    return {"permissions": {"allow": rules}}


def main(argv=None):
    vault = os.environ.get("BRAIN_VAULT") or os.path.dirname(HERE)
    ap = argparse.ArgumentParser(prog="claude_settings.py", description="merge recommended Claude Code settings")
    sub = ap.add_subparsers(dest="cmd")
    for name in ("show", "merge", "chrome-allow"):
        p = sub.add_parser(name)
        if name == "chrome-allow":
            p.add_argument("hosts", nargs="+", help="sites, for example github.com or localhost:3000")
        else:
            p.add_argument("--example", default=os.path.join(vault, "integrations", "claude-code", "settings.example.json"))
        p.add_argument("--settings", default=os.path.join(os.path.expanduser("~"), ".claude", "settings.json"))
        if name != "show":
            p.add_argument("--yes", action="store_true", help="merge without asking")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)
    if not args.cmd:
        ap.print_help(sys.stderr)
        return 2

    from guardian_core.claude_code import FileSettingsStore
    from guardian_core.ports import SettingsUnreadable

    store = FileSettingsStore(args.settings)
    try:
        current = store.load()
        if args.cmd == "chrome-allow":
            example = chrome_rules(args.hosts)
        else:
            with open(args.example, encoding="utf-8") as fh:
                example = json.load(fh)
    except SettingsUnreadable as exc:
        print("claude_settings.py: %s is not valid JSON; fix it by hand first (%s)" % (args.settings, exc),
              file=sys.stderr)
        return 1
    except ValueError as exc:
        if args.cmd == "chrome-allow":
            print("claude_settings.py: %s" % exc, file=sys.stderr)
            return 2
        print("claude_settings.py: cannot read the example %s: %s" % (args.example, exc), file=sys.stderr)
        return 1
    except OSError as exc:
        print("claude_settings.py: cannot read the example %s: %s" % (args.example, exc), file=sys.stderr)
        return 1
    merged, changes = merge(current, example, vault)
    for line in kept(current, example, vault):
        print("kept as you have it: " + line)
    if not changes:
        print("nothing to add: %s already has every recommended setting" % args.settings)
        return 0
    print("A merge would add to %s:" % args.settings)
    for line in changes:
        print("  " + line)
    if args.cmd == "show":
        return 0
    if not args.yes:
        if not sys.stdin.isatty():
            print("Not a terminal: nothing written. To merge: python3 _bin/claude_settings.py %s --yes"
                  % " ".join([args.cmd] + list(getattr(args, "hosts", []))))
            return 0
        answer = input("Merge these (a backup is kept)? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("nothing written")
            return 0
    backup = store.save(merged, "claude_settings.py merge")
    print("merged; previous file kept at %s" % (backup or "(none: the file was new)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
