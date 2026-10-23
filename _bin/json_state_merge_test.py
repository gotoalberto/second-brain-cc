#!/usr/bin/env python3
"""Tests for json_state_merge: the merge rules, and the driver inside a real git rebase.

Run standalone:

    python3 _bin/json_state_merge_test.py
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail and not cond else ""))


def sh(cwd, *a):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t"] + list(a), cwd=cwd,
                          capture_output=True, text=True)


def test_rules():
    import json_state_merge as M
    print("== merge rules ==")
    base = {"config": {"class_passes": 30}, "members": {"ana": {"visits": ["mon"]}}}
    ours = {"config": {"class_passes": 27}, "members": {"ana": {"visits": ["mon", "wed"]}, "noor": {"plan": "yoga"}}}
    theirs = {"config": {"class_passes": 30}, "members": {"ana": {"visits": ["mon", "fri"]}, "lee": {"plan": "swim"}}}
    m = M.merge(base, ours, theirs)
    check("a key only one side added is kept from both sides", set(m["members"]) == {"ana", "lee", "noor"}, m)
    check("a value only ours changed wins", m["config"]["class_passes"] == 27, m)
    check("two lists that both grew keep every item once", m["members"]["ana"]["visits"] == ["mon", "wed", "fri"], m)
    check("a budget spent on both machines subtracts both spends",
          M.merge({"c": 30}, {"c": 27}, {"c": 25}) == {"c": 22})
    check("a counter both sides raised takes the larger", M.merge({"n": 1}, {"n": 4}, {"n": 2}) == {"n": 4})
    check("ISO timestamps both sides moved take the later",
          M.merge({"t": "2031-03-01 10:00"}, {"t": "2031-03-02 09:00"}, {"t": "2031-03-04 12:00"})
          == {"t": "2031-03-04 12:00"})
    check("an item one side removed stays removed", M.merge([1, 2], [1], [1, 2, 3]) == [1, 3])
    check("a key theirs deleted and ours left alone goes",
          M.merge({"k": 1, "j": 2}, {"k": 1, "j": 3}, {"j": 2}) == {"j": 3})
    check("no base (both added the file) still merges", M.merge(M._MISSING, {"a": 1}, {"b": 2}) == {"a": 1, "b": 2})
    check("the same event added on both sides is kept once",
          M.merge([], [{"id": 7, "what": "lesson"}], [{"what": "lesson", "id": 7}]) == [{"id": 7, "what": "lesson"}])
    check("a flag both sides changed keeps ours", M.merge({"f": None}, {"f": True}, {"f": False}) == {"f": True})


def test_files():
    import json_state_merge as M
    print("== files ==")
    with tempfile.TemporaryDirectory() as d:
        paths = [os.path.join(d, n) for n in ("base", "ours", "theirs")]
        for p, body in zip(paths, ("{}", "{\n  \"a\": 1\n}\n", "not json")):
            with open(p, "w") as fh:
                fh.write(body)
        check("a side that is not JSON exits 1, so git keeps an ordinary conflict",
              M.merge_files(*paths) == 1)
        with open(paths[1]) as fh:
            check("and ours is left untouched", fh.read() == "{\n  \"a\": 1\n}\n")
        check("a missing argument is a usage error", M.main(["x"]) == 2)


def test_in_git():
    print("== the driver inside a real rebase ==")
    with tempfile.TemporaryDirectory() as root:
        repo = os.path.join(root, "r")
        os.makedirs(repo)
        sh(repo, "init", "-q", "-b", "main")
        driver = "%s %s %%O %%A %%B" % (sys.executable, os.path.join(HERE, "json_state_merge.py"))
        sh(repo, "config", "merge.brain-json-state.driver", driver)
        with open(os.path.join(repo, ".gitattributes"), "w") as fh:
            fh.write("*-state.json merge=brain-json-state\n")
        state = os.path.join(repo, "loans-state.json")

        def write(d):
            with open(state, "w") as fh:
                json.dump(d, fh, indent=1)
                fh.write("\n")

        write({"readers": {"r1": {"loans": ["atlas"]}}, "renewals_left": 10})
        sh(repo, "add", "-A"); sh(repo, "commit", "-qm", "base")
        sh(repo, "checkout", "-q", "-b", "other")
        write({"readers": {"r1": {"loans": ["atlas", "herbarium"]}, "r2": {}}, "renewals_left": 10})
        sh(repo, "commit", "-qam", "theirs")
        sh(repo, "checkout", "-q", "main")
        write({"readers": {"r1": {"loans": ["atlas", "tide tables"]}, "r9": {}}, "renewals_left": 8})
        sh(repo, "commit", "-qam", "ours")
        r = sh(repo, "rebase", "other")
        in_rebase = os.path.isdir(os.path.join(repo, ".git", "rebase-merge"))
        check("the rebase finishes with no conflict", r.returncode == 0 and not in_rebase, r.stderr)
        with open(state) as fh:
            got = json.load(fh)
        check("both machines' readers survive", set(got["readers"]) == {"r1", "r2", "r9"}, got)
        check("both machines' loans survive",
              set(got["readers"]["r1"]["loans"]) == {"atlas", "herbarium", "tide tables"}, got)
        check("the spend from one machine is kept", got["renewals_left"] == 8, got)
        with open(state) as fh:
            check("the file keeps its indent", fh.read().startswith('{\n "'))

        sh(repo, "config", "--unset", "merge.brain-json-state.driver")
        sh(repo, "checkout", "-q", "-b", "nodriver", "other")
        write({"readers": {}, "renewals_left": 1})
        sh(repo, "commit", "-qam", "x")
        r = sh(repo, "rebase", "main")
        check("without the driver configured git falls back to its own merge (a plain conflict)",
              r.returncode != 0 and os.path.isdir(os.path.join(repo, ".git", "rebase-merge")))
        sh(repo, "rebase", "--abort")


def test_attributes():
    print("== .gitattributes ==")
    path = os.path.join(os.path.dirname(HERE), ".gitattributes")
    try:
        with open(path) as fh:
            body = fh.read()
    except OSError:
        body = ""
    check("the vault assigns the driver to the project and meta state files",
          "10-Projects/*-state.json merge=brain-json-state" in body
          and "90-Meta/*-state.json merge=brain-json-state" in body, body)


def main():
    for t in (test_rules, test_files, test_in_git, test_attributes):
        try:
            t()
        except Exception as exc:
            import traceback
            traceback.print_exc()
            check("%s ran to the end" % t.__name__, False, "%s: %s" % (type(exc).__name__, exc))
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
