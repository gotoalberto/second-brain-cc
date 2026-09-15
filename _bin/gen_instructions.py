#!/usr/bin/env python3
"""Generates AGENTS.md and CLAUDE.md at the vault root, and 90-Meta/HOOKS-WITHOUT-CLAUDE.md.
Never edit them by hand.

  gen_instructions.py          write each one whose content changed
  gen_instructions.py --check  exit 1 if any is out of date; writes nothing

AGENTS.md is for an agent with no adapter wired into Brain (OpenCode, a plain CLI agent,
Codex, anything that reads AGENTS.md): the compact protocol, every Brain event, and the
degraded-mode table — what does not fire on its own for that agent and what to run
instead. Built from 90-Meta/events.json and 90-Meta/PROTOCOL-COMPACT.md.

90-Meta/HOOKS-WITHOUT-CLAUDE.md lists, per event, every way to trigger it without Claude Code
(`brain hook <event-id>`, CLI, MCP, git hooks, the file watch, launchd) and its handler command.

CLAUDE.md is a two-line pointer to AGENTS.md, generated too, so the two cannot drift. The
copy of AGENTS.md in the home directory is machine-local install state and is not written
here.
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from events_core import adapters as EAD  # noqa: E402
from events_core import application as EA  # noqa: E402
from events_core import domain as ED  # noqa: E402


def vault_dir():
    return os.environ.get("BRAIN_VAULT") or os.path.dirname(HERE)


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="gen_instructions.py",
                                 description="generate AGENTS.md and CLAUDE.md from the event registry")
    ap.add_argument("--check", action="store_true", help="exit 1 if any generated file is out of date; write nothing")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)

    vault = vault_dir()
    registry_path = os.path.join(vault, "90-Meta", "events.json")
    protocol_path = os.path.join(vault, "90-Meta", "PROTOCOL-COMPACT.md")
    try:
        registry = ED.load_registry(_read(registry_path))
        protocol = _read(protocol_path)
    except (OSError, ED.RegistryError) as exc:
        print("gen_instructions: cannot build from %s and %s: %s" % (registry_path, protocol_path, exc),
              file=sys.stderr)
        return 2

    known = set(ED.AGENT_INDEPENDENT)
    files = EAD.VaultFiles(vault)
    if args.check:
        wanted = {"AGENTS.md": ED.render_agents_md(registry, protocol, known), "CLAUDE.md": ED.CLAUDE_MD_POINTER,
                  ED.HOOKS_DOC_REL: ED.render_hooks_without_claude(registry)}
        stale = [rel for rel, text in wanted.items() if files.read(rel) != text]
        if stale:
            print("out of date (regenerate with gen_instructions.py): %s" % ", ".join(stale), file=sys.stderr)
            return 1
        print("%s are current" % ", ".join(wanted))
        return 0

    ports = EA.Ports(snapshot=None, state=None, runner=None, session=None, alerts=None, git=None,
                     files=files, clock=None)
    for result in (EA.generate_agents_md(ports, registry, protocol, known), EA.generate_claude_md(ports),
                   EA.generate_hooks_doc(ports, registry)):
        print("%s %s" % ("wrote    " if result.changed else "unchanged", result.path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
