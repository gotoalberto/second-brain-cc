#!/usr/bin/env python3
"""Tests for people_core and people.py: a name in a prompt, the person it means, and their notes.

A temporary vault is indexed by index_vault.py in a subprocess (BRAIN_VAULT, BRAIN_STATE and HOME
temporary), and this process imports brainlib only after pointing it there. Every person, project
and note below is invented. retrieve.py's hook itself is not run (it pulls the vault and starts the
presence heartbeat); its pure helpers are. Run standalone:

    python3 _bin/people_core_test.py
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

ok, fail = [], []
ROOT = tempfile.mkdtemp(prefix="people-core-test-")
VAULT = os.path.join(ROOT, "vault")
HOME = os.path.join(ROOT, "home")
STATE = os.path.join(ROOT, "state")
os.environ["BRAIN_VAULT"] = VAULT          # before any brainlib import: it reads these once
os.environ["HOME"] = HOME
os.environ["BRAIN_STATE"] = STATE
os.environ["BRAIN_OFFLINE"] = "1"

DANA = "70-Entities/2026-03-01-entity-dana-whitfield.md"
PROJECT = "10-Projects/2026-03-02-project-garden-planner.md"
BOTH = "30-Knowledge/2026-03-05-decision-garden-planner-uses-sqlite.md"
DANA_ONLY = "30-Knowledge/2026-03-04-reference-dana-onboarding.md"
PROJECT_ONLY = "30-Knowledge/2026-03-06-runbook-garden-planner-deploy.md"
MENTION = "50-Sessions/2026-03-07-session-planning-call.md"


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail and not cond else ""))


def note(rel, title, body, ntype="knowledge", tags=(), projects=(), extra=""):
    path = os.path.join(VAULT, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write("---\nid: %s\ntitle: %s\n%stype: %s\narea: [home]\nprojects: [%s]\ntags: [%s]\n"
                 "status: active\nconfidence: high\nsource: agent\nprovenance: test\n"
                 "updated: 2026-03-08\nsupersedes: []\n---\n\n%s\n"
                 % (os.path.splitext(os.path.basename(rel))[0], title, extra, ntype,
                    ", ".join(projects), ", ".join(tags), body))


def build_vault():
    os.makedirs(HOME)
    os.makedirs(STATE)
    note(DANA, "Dana Whitfield", "Dana keeps the garden beds and the watering schedule.",
         ntype="entity", tags=("entity", "person"), extra="aliases: [dee]\n")
    note("70-Entities/2026-03-01-entity-mark-osei.md", "Mark Osei (neighbour)", "Mark lends the tools.",
         ntype="entity", tags=("person",))
    note("70-Entities/2026-03-01-entity-sam-rivera.md", "Sam Rivera", "Sam orders seeds.",
         ntype="entity", tags=("person",))
    note("70-Entities/2026-03-01-entity-sam-okafor.md", "Sam Okafor", "Sam fixes the fence.",
         ntype="entity", tags=("person",))
    note("70-Entities/2026-03-01-entity-robin-hale.md", "Robin Hale", "The owner of this vault.",
         ntype="entity", tags=("person",))
    note("70-Entities/2026-03-01-entity-acme-tools.md", "Acme Tools", "A shop that sells rakes.",
         ntype="entity", tags=("vendor",))
    note("70-Entities/2026-03-01-entity-noor-haddad.md", "Noor Haddad", "Noor sells compost.",
         ntype="entity", tags=("contact",))
    note("70-Entities/2026-03-01-entity-lee-park.md", "Lee Park", "Lee runs the allotment club.",
         ntype="entity", tags=("member",))
    note("70-Entities/2026-03-01-entity-kit-moss.md", "Kit Moss", "Kit drops by on weekends.",
         ntype="entity", tags=("visitor",))
    note(PROJECT, "Project: garden planner", "Plan the beds for the spring season.", ntype="project")
    note(BOTH, "Decision: the garden planner keeps its data in SQLite",
         "Agreed with [[entity-dana-whitfield]] for [[2026-03-02-project-garden-planner]].", ntype="decision")
    note(DANA_ONLY, "Reference: onboarding for the garden", "Walkthrough given by [[entity-dana-whitfield]].")
    note(PROJECT_ONLY, "Runbook: deploying the planner", "Copy the build to the shed laptop.",
         projects=("garden-planner",))
    note(MENTION, "Session: planning call", "Dana Whitfield asked for raised beds.", ntype="session")
    note("90-Meta/people.md", "People detection settings", "Settings for people_core.",
         ntype="reference", extra="self: entity-robin-hale\nnot_names: [planner]\nperson_tags: [member]\n")
    p = subprocess.run([sys.executable, os.path.join(HERE, "index_vault.py"), "--full"], env=dict(os.environ),
                       capture_output=True, text=True, timeout=120)
    return p


def slugs(detected):
    return [(p.slug, strength, ambiguous) for p, strength, ambiguous in detected]


def test_directory_and_detect(P, con):
    print("\n== who a name means ==")
    config = P.load_config()
    check("the settings note names the user's own entity and extra stop words",
          config["self"] == {"entity-robin-hale"} and "planner" in config["not_names"]
          and "mark" in config["not_names"], config)
    check("person and contact are person tags by default, and the settings note adds more",
          config["person_tags"] == {"person", "contact", "member"}, config.get("person_tags"))
    folk = P.directory(con)
    check("entity notes with a person tag are people; a vendor or an unlisted tag is not",
          {"entity-dana-whitfield", "entity-mark-osei", "entity-sam-rivera", "entity-sam-okafor",
           "entity-robin-hale", "entity-noor-haddad", "entity-lee-park"} == set(folk), sorted(folk))
    only = P.directory(con, tags={"visitor"})
    check("an explicit tag list replaces the configured one", set(only) == {"entity-kit-moss"}, sorted(only))
    dana = folk.get("entity-dana-whitfield")
    check("a person carries the entity note, the title as name, and the note's aliases",
          dana is not None and dana.note == DANA and dana.name == "Dana Whitfield" and "dee" in dana.aliases,
          dana and (dana.note, dana.name, dana.aliases))
    check("and is weighed by how many notes link it", dana is not None and dana.weight == 2, dana and dana.weight)
    check("a title's parenthesis is not part of the name", folk["entity-mark-osei"].name == "Mark Osei")

    detect = lambda text, **kw: slugs(P.detect(text, folk, config=config, **kw))
    check("a first name alone is a weak match", detect("what did Dana say about it") ==
          [("entity-dana-whitfield", "weak", False)], detect("what did Dana say about it"))
    check("first and last name together are strong", detect("ask dana whitfield") ==
          [("entity-dana-whitfield", "strong", False)], detect("ask dana whitfield"))
    check("an alias from the frontmatter is strong", detect("Dee will know") ==
          [("entity-dana-whitfield", "strong", False)], detect("Dee will know"))
    check("accents and case do not matter", detect("DÁNA WHÍTFIELD?") ==
          [("entity-dana-whitfield", "strong", False)], detect("DÁNA WHÍTFIELD?"))
    check("a first name that is also a common word is not a person alone", detect("mark the task done") == [],
          detect("mark the task done"))
    check("but is with the last name", detect("Mark Osei lent the rake") == [("entity-mark-osei", "strong", False)])
    both = detect("did sam reply")
    check("a first name two people share returns both, marked ambiguous",
          sorted(both) == [("entity-sam-okafor", "weak", True), ("entity-sam-rivera", "weak", True)], both)
    check("the user's own entity is never detected", detect("robin hale wrote this") == [],
          detect("robin hale wrote this"))
    check("unless asked for by name", detect("robin hale", include_self=True) ==
          [("entity-robin-hale", "strong", False)])
    quiet = {"self": config["self"], "not_names": config["not_names"] | {"dana"}}
    check("a first name on the configured stop list is not a person alone",
          slugs(P.detect("dana said so", folk, config=quiet)) == [], slugs(P.detect("dana said so", folk, config=quiet)))
    check("but the full name still is", slugs(P.detect("dana whitfield said so", folk, config=quiet)) ==
          [("entity-dana-whitfield", "strong", False)])
    check("a prompt naming nobody detects nobody", detect("how do I water tomatoes") == [])


def test_notes(P, con):
    print("\n== the person's notes, merged with the project's ==")
    import brainlib as B
    folk = P.directory(con)
    R = B.LinkResolver(con)
    mine = P.notes_for_person(con, folk["entity-dana-whitfield"], R)
    check("notes that link the person, and notes that only name them",
          mine == {BOTH: "linked", DANA_ONLY: "linked", MENTION: "mentioned"}, mine)
    proj = P.notes_for_project(con, PROJECT, R)
    check("notes that link the project or list it in projects:",
          proj == {BOTH: "linked", PROJECT_ONLY: "assigned"}, proj)
    merged = P.merge(con, {"entity-dana-whitfield": mine}, {PROJECT: proj})
    paths = [m["path"] for m in merged]
    check("a note in both lists is listed once, and first", paths[0] == BOTH and paths.count(BOTH) == 1, paths)
    check("then the rest, newest first", paths[1:] == [MENTION, PROJECT_ONLY, DANA_ONLY], paths)
    check("each entry says which side found it",
          merged[0]["people"] == {"entity-dana-whitfield": "linked"} and merged[0]["projects"] == {PROJECT: "linked"}
          and merged[0]["date"] == "2026-03-05" and merged[0]["title"].startswith("Decision:"), merged[0])
    check("the counts say how many to read once",
          P.summary(merged) == {"person": 3, "project": 2, "common": 1, "unique": 4}, P.summary(merged))
    detected, projects, merged = P.context(con, "what did Dana decide", ["garden-planner"])
    check("context resolves a project given by its slug",
          projects == [PROJECT] and slugs(detected) == [("entity-dana-whitfield", "weak", False)], (projects, detected))
    detected, projects, merged = P.context(con, "", (), ["Dana Whitfield"], since="2026-03-06")
    check("--person and --since narrow it", [m["path"] for m in merged] == [MENTION], merged)


def test_hook_lines(P, con):
    print("\n== the prompt hook's lines ==")
    lines = P.hook_lines(con, "what did Dana Whitfield say about the garden planner", [PROJECT])
    check("one line for the person, with the entity note and the counts",
          lines and lines[0] == "· Person: Dana Whitfield \u2014 `%s` · 3 note(s), 1 shared with the project" % DANA,
          lines)
    check("then the command that lists them all once, so trimming keeps it",
          len(lines) > 1 and lines[1] == '  all, without repeats: `python3 ~/Brain/_bin/people.py context '
          '--person "Dana Whitfield" --project "%s"`' % PROJECT, lines)
    check("the shared note first, marked", len(lines) > 2 and lines[2] == "  2026-03-05 `%s` (also the project)" % BOTH,
          lines)
    check("a prompt naming nobody adds nothing", P.hook_lines(con, "how do I water tomatoes") == [])
    auto = P.hook_lines(con, "what did Dana Whitfield decide on the garden planner")
    check("with no project given, the one the prompt is about is found", any("--project" in l for l in auto), auto)


def test_retrieval(P, con):
    print("\n== retrieval carries the person ==")
    import retrieve_core as RC
    import retrieve
    people = P.hook_lines(con, "what did Dana Whitfield say", [])
    hits = [(9.0, "30-Knowledge/a.md", "Note A", ""), (5.0, "30-Knowledge/b.md", "Note B", "")]
    related = [("related", "30-Knowledge/c.md", "Note C")]
    block, _ = RC.render_block(hits, related, 10_000, False, "", False, people)
    lines = block.splitlines()
    check("the person comes right after the best hit",
          lines[1] == "· Note A \u2014 `30-Knowledge/a.md`" and lines[2].startswith("· Person: Dana Whitfield"), lines)
    small, _ = RC.render_block(hits, related, 70, True, "", False, people)
    check("a tight cap drops related notes and weaker hits before the person",
          "Person: Dana Whitfield" in small and "Note C" not in small, small)
    alone, _ = RC.render_block([], [], 10_000, False, "", False, people)
    check("a named person is injected even when no note clears the bar", "Person: Dana Whitfield" in alone, alone)
    block = RC.search_and_render(con, "what did Dana Whitfield say")
    check("search_and_render adds the person", "· Person: Dana Whitfield" in block, block)
    check("person_lines never raises on a broken index", RC.person_lines(None, "Dana Whitfield", []) == [])

    sid = "0f0f0f0f"
    con.execute("DELETE FROM injected WHERE sid=?", (sid,))
    check("a person new to the session is kept whole", retrieve.new_people(con, sid, people) == people)
    con.execute("INSERT INTO injected VALUES(?,?,?)", (sid, "person:Dana Whitfield", 0.0))
    check("a person already injected in this session is not repeated",
          retrieve.new_people(con, sid, people) == [], retrieve.new_people(con, sid, people))
    con.execute("DELETE FROM injected WHERE sid=?", (sid,))
    check("the key a person is recorded under", retrieve.person_key(people[0]) == "person:Dana Whitfield",
          retrieve.person_key(people[0]))


def run(script, *args):
    p = subprocess.run([sys.executable, os.path.join(HERE, script)] + list(args), env=dict(os.environ),
                       capture_output=True, text=True, timeout=120)
    return p.returncode, p.stdout, p.stderr


def test_cli():
    print("\n== people.py and query.py ==")
    rc, out, err = run("people.py", "context", "--person", "Dana Whitfield", "--project", "garden-planner")
    check("people.py context names the person, the project and each note once",
          rc == 0 and DANA in out and PROJECT in out and out.count(BOTH) == 1 and "both" in out
          and "4 to read once" in out, (rc, out, err))
    rc, out, err = run("people.py", "context", "Dana")
    check("a bare name works too", rc == 0 and DANA in out and DANA_ONLY in out, (rc, out, err))
    rc, out, err = run("people.py", "detect", "did", "sam", "reply")
    check("people.py detect lists both Sams as ambiguous",
          rc == 0 and "Sam Rivera" in out and "Sam Okafor" in out and "ambiguous" in out, (rc, out, err))
    rc, out, err = run("query.py", "garden", "planner", "--person", "Dana Whitfield")
    check("query.py --person ends with the person's entity note and notes",
          rc == 0 and "── people named" in out and DANA in out and DANA_ONLY in out, (rc, out, err))
    rc, out, err = run("query.py", "sqlite")
    check("query.py stays silent about people when nobody is named", rc == 0 and "people named" not in out,
          (rc, out, err))


def main():
    try:
        p = build_vault()
        check("the fixture vault indexes", p.returncode == 0, p.stderr[-400:])
        try:
            import brainlib as B
            import people_core as P
        except Exception as exc:
            check("people_core imports", False, "%s: %s" % (type(exc).__name__, exc))
            return finish()
        check("brainlib points at the fixture vault, not the real one", B.VAULT == VAULT, B.VAULT)
        con = B.db()
        try:
            for t in (test_directory_and_detect, test_notes, test_hook_lines, test_retrieval):
                try:
                    t(P, con)
                except Exception as exc:
                    import traceback
                    traceback.print_exc()
                    check("%s ran to the end" % t.__name__, False, "%s: %s" % (type(exc).__name__, exc))
        finally:
            con.close()
        try:
            test_cli()
        except Exception as exc:
            check("test_cli ran to the end", False, "%s: %s" % (type(exc).__name__, exc))
    finally:
        pass
    return finish()


def finish():
    shutil.rmtree(ROOT, ignore_errors=True)
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
