#!/usr/bin/env python3
"""Sync the skills catalogue into the vault's 40-Skills/.

Reads the frontmatter of every SKILL.md and regenerates THIS machine's index plus one
note per skill, preserving the hand-written section between the
marcadores AUTO.
"""
import os, sys, glob, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B

AUTO_BEGIN, AUTO_END = "<!-- AUTO:BEGIN -->", "<!-- AUTO:END -->"
HOME = os.path.expanduser("~")


def sources(cwd=None):
    pats = [os.path.join(HOME, ".claude", "skills", "*", "SKILL.md"),
            os.path.join(HOME, ".claude", "plugins", "*", "skills", "*", "SKILL.md"),
            os.path.join(HOME, ".claude", "plugins", "*", "*", "skills", "*", "SKILL.md"),
            os.path.join(B.VAULT, ".claude", "skills", "*", "SKILL.md")]
    if cwd:
        pats.append(os.path.join(cwd, ".claude", "skills", "*", "SKILL.md"))
    out = []
    for p in pats:
        out.extend(glob.glob(p))
    return sorted(set(out))


def scope_of(path):
    if path.startswith(os.path.join(HOME, ".claude", "plugins")):
        return "plugin"
    if path.startswith(os.path.join(HOME, ".claude")):
        return "user"
    if B.in_vault(path):
        return "vault"
    return "project"


def collect(cwd=None):
    skills = []
    for path in sources(cwd):
        try:
            text = open(path, errors="replace").read()
        except Exception:
            continue
        meta, body = B.parse_frontmatter(text)
        name = meta.get("name") or os.path.basename(os.path.dirname(path))
        if isinstance(name, list):
            name = name[0] if name else "?"
        desc = meta.get("description") or ""
        if isinstance(desc, list):
            desc = " ".join(desc)
        skills.append({
            "name": str(name), "desc": str(desc)[:300],
            "when": str(meta.get("when_to_use") or "")[:300],
            "tools": str(meta.get("allowed-tools") or ""),
            "ctx": str(meta.get("context") or ""), "agent": str(meta.get("agent") or ""),
            "model": str(meta.get("model") or ""), "path": path, "scope": scope_of(path),
            "body": body.strip()[:1200],
        })
    return skills


def index_path():
    """One index per machine. This is what kills the ping-pong between machines.

    With a single `INDEX.md`, each machine regenerated it with the skills installed
    LOCALLY: each machine's SessionStart produced a commit undoing the other's,
    indefinitely. A lock does not fix that, it only
    serialises the ping-pong; what fixes it is the data model — the same
    trick as `90-Meta/presence/`, one file per machine, which git merges on its own
    because nobody writes anyone else's file. The machine name comes from
    brainlib (the same one `presence_mark` uses) so the two places cannot
    disagree.
    """
    return os.path.join(B.VAULT, "40-Skills", "INDEX-%s.md" % B._machine())


def write_index(skills):
    today = time.strftime("%Y-%m-%d")
    maq = B._machine()
    lines = ["---", "id: %s-skills-index-%s" % (today, maq.lower()),
             "title: Skills catalogue (%s)" % maq,
             "type: meta", "area: [infra-personal]", "projects: [brain]",
             "tags: [skills, catalogo]", "status: active", "confidence: high",
             "source: agent", "provenance: skills_index.py", "maquina: " + maq,
             "updated: " + today,
             "supersedes: []", "---", "",
             "Skills installed on **%s**. Regenerated automatically. "
             "**Do not edit by hand.**" % maq, "",
             "Each machine keeps its own `INDEX-<machine>.md`: a skill missing here "
             "only means it is not installed on this machine.", ""]
    for s in skills:
        one = (s["desc"] or s["when"] or "").replace("\n", " ").strip()
        if len(one) > 150:
            one = one[:147] + "..."
        lines.append("- `/%s` (%s) — %s" % (s["name"], s["scope"], one))
    lines.append("")
    lines.append("One note per skill in `40-Skills/<name>.md`.")
    B.atomic_write(index_path(), "\n".join(lines) + "\n")


def write_note(s):
    today = time.strftime("%Y-%m-%d")
    path = os.path.join(B.VAULT, "40-Skills", "%s.md" % s["name"])
    auto = [AUTO_BEGIN,
            "**Scope**: %s" % s["scope"],
            "**File**: `%s`" % s["path"],
            "**Invocation**: `/%s`" % s["name"], ""]
    if s["desc"]:
        auto += ["**What it does**", s["desc"], ""]
    if s["when"]:
        auto += ["**When it triggers**", s["when"], ""]
    extra = [x for x in (("tools: " + s["tools"]) if s["tools"] else "",
                         ("contexto: " + s["ctx"]) if s["ctx"] else "",
                         ("agente: " + s["agent"]) if s["agent"] else "",
                         ("modelo: " + s["model"]) if s["model"] else "") if x]
    if extra:
        auto += ["**Config**: " + " · ".join(extra), ""]
    if s["body"]:
        auto += ["**Instructions (excerpt)**", "```", s["body"], "```", ""]
    auto.append(AUTO_END)
    auto_block = "\n".join(auto)

    manual = "\n## Usage notes\n\n_(human section: when it helped, when it failed, real examples)_\n"
    if os.path.exists(path):
        old = open(path, errors="replace").read()
        if AUTO_END in old:
            manual = old.split(AUTO_END, 1)[1]
    head = ("---\nid: %s-skill-%s\ntitle: Skill %s\ntype: skill\narea: [infra-personal]\n"
            "projects: [brain]\ntags: [skill]\nstatus: active\nconfidence: high\n"
            "source: agent\nprovenance: skills_index.py\nupdated: %s\nsupersedes: []\n---\n\n"
            % (today, s["name"], s["name"], today))
    B.atomic_write(path, head + auto_block + manual)


def remove_old_index():
    """Deletes the shared `INDEX.md` that `INDEX-<machine>.md` replaces.

    Leaving it was worse than deleting it: nobody regenerates it any more, so it stays
    frozen on the snapshot of the last machine that wrote it while still announcing
    "regenerated automatically", and there are agents (context-scout, skill-forge) that
    read it as though it were the real catalogue.

    It is deleted only if it carries our signature in the frontmatter: an `INDEX.md`
    someone wrote by hand is not ours and is not touched. While the other
    machine still on the old code will recreate it and it will be deleted again here;
    that back-and-forth ends by itself once `_bin/` is pulled through git, and it is one
    entry a day, not one per SessionStart like the ping-pong we removed.
    """
    old_one = os.path.join(B.VAULT, "40-Skills", "INDEX.md")
    try:
        if not os.path.exists(old_one):
            return False
        meta, _ = B.parse_frontmatter(open(old_one, errors="replace").read())
        if meta.get("provenance") != "skills_index.py":
            return False
        os.remove(old_one)
        return True
    except Exception as e:
        B.log_error("skills_index.remove_old_index", e)
        return False


@B.fail_open
def main():
    data = B.read_hook_input()
    cwd = data.get("cwd") or None
    skills = collect(cwd)
    write_index(skills)
    retirado = remove_old_index()
    for s in skills:
        write_note(s)
    # Skills not installed HERE are no longer flipped to `status: archived`: each machine
    # has its own set, so marking them was declaring
    # archived what is still live on the other machine, and the other machine
    # unflagged it on its next startup. A skill that is genuinely retired is
    # archived by hand; the per-machine index already says who has it.
    if "--verbose" in sys.argv:
        print("catalogadas %d skills -> %s%s"
              % (len(skills), index_path(),
                 " (retirado INDEX.md compartido)" if retirado else ""))
    sys.exit(0)


if __name__ == "__main__":
    main()
