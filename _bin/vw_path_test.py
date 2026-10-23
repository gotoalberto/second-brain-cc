#!/usr/bin/env python3
"""Tests for vw.normalize: where a note path given to vw.py actually lands.

A session standing in $HOME that runs `vw.py append Brain/10-Projects/x.md` used to get a
second tree, <vault>/Brain/10-Projects/, that no search, project lookup or sync rule reads.
Pure: no notes are written.

    python3 _bin/vw_path_test.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import vw  # noqa: E402

ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail and not cond else ""))


def main():
    vault = "/tmp/example-home/Brain"
    n = lambda rel: vw.normalize(rel, vault)
    P = "10-Projects/2031-04-02-project-bakery-menu.md"

    check("a path relative to the vault is kept", n(P) == (P, None), n(P))
    check("the vault folder's name in front is dropped", n("Brain/" + P) == (P, None), n("Brain/" + P))
    check("so is ./", n("./" + P) == (P, None), n("./" + P))
    check("an absolute path inside the vault is fine", n(vault + "/" + P) == (P, None))
    check("and an absolute path with the doubled folder lands in the right place",
          n(vault + "/Brain/" + P) == (P, None), n(vault + "/Brain/" + P))
    check("a path outside the vault is refused", n("/etc/hosts")[0] is None)
    check("so is one that climbs out", n("../x/10-Projects/a.md")[0] is None)
    check("a folder that is not a note folder is refused",
          n("2031-04-02-project-bakery-menu/a.md")[0] is None, n("2031-04-02-project-bakery-menu/a.md"))
    check("and the refusal names the note folders", "10-Projects" in (n("x/a.md")[1] or ""))
    check("a file at the vault root is not a note", n("README.md")[0] is None)
    check("the vault's own name with nothing after it is refused", n("Brain")[0] is None)
    check("a folder named like the vault deeper down is left as it is",
          n("30-Knowledge/Brain/a.md") == ("30-Knowledge/Brain/a.md", None), n("30-Knowledge/Brain/a.md"))

    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
