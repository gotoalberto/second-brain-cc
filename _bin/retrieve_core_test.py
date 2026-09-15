#!/usr/bin/env python3
"""Tests for retrieve_core — the search and rendering behind per-prompt retrieval.

retrieve.py (the Claude Code UserPromptSubmit hook), the MCP server's `recall` and the
`brain recall` CLI all render vault notes the same way through this module. A temporary
vault is indexed by index_vault.py in a subprocess (BRAIN_VAULT and HOME temporary), and
this process imports brainlib only after pointing it there. retrieve.py's hook itself is
not run: it pulls the vault from git and beats presence to S3, neither of which a test may
do. Run standalone:

    python3 _bin/retrieve_core_test.py
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

ok, fail = [], []
ROOT = tempfile.mkdtemp(prefix="retrieve-core-test-")
VAULT = os.path.join(ROOT, "vault")
HOME = os.path.join(ROOT, "home")
os.environ["BRAIN_VAULT"] = VAULT          # before any brainlib import: it reads these once
os.environ["HOME"] = HOME
os.environ.pop("BRAIN_STATE", None)


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def note(rel, title, body, ntype="knowledge"):
    path = os.path.join(VAULT, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write("---\nid: %s\ntitle: %s\ntype: %s\narea: [harness]\nprojects: []\ntags: []\n"
                 "status: active\nconfidence: high\nsource: agent\nprovenance: test\n"
                 "updated: 2026-09-15\nsupersedes: []\n---\n\n%s\n"
                 % (os.path.splitext(os.path.basename(rel))[0], title, ntype, body))


def build_vault():
    os.makedirs(HOME)
    note("30-Knowledge/2026-09-01-decision-credentials-live-in-keepass.md",
         "Decision: credentials live in the KeePass database",
         "Every credential is stored in the KeePass kdbx database. Notes keep only kp references. "
         "See [[2026-09-02-runbook-rotating-a-keepass-credential]].", ntype="decision")
    note("30-Knowledge/2026-09-02-runbook-rotating-a-keepass-credential.md",
         "Runbook: rotating a credential",
         "How to rotate an entry: generate, update the service, file the new value.")
    note("30-Knowledge/2026-09-03-reference-sourdough-starter.md",
         "Reference: sourdough starter feeding",
         "Flour and water ratios for a sourdough starter, feeding twice a day.")
    env = dict(os.environ)
    p = subprocess.run([sys.executable, os.path.join(HERE, "index_vault.py"), "--full"], env=env,
                       capture_output=True, text=True, timeout=120)
    return p


def main():
    try:
        p = build_vault()
        check("the fixture vault indexes", p.returncode == 0, p.stderr[-400:])
        try:
            import retrieve_core as R
            import brainlib as B
            import retrieve
        except Exception as exc:
            check("retrieve_core imports", False, "%s: %s" % (type(exc).__name__, exc))
            return finish()
        check("brainlib points at the fixture vault, not the real one", B.VAULT == VAULT, B.VAULT)

        print("\n== prompt classification ==")
        for prompt, task in (("haz la migración", True), ("fix the sync", True),
                             ("what did we decide about keepass?", False), ("hola", False)):
            check("is_task(%r) is %s" % (prompt, task), R.is_task(prompt) is task)
            check("retrieve.is_task agrees on %r" % prompt, retrieve.is_task(prompt) is R.is_task(prompt))
        for prompt, harness in (("<task-notification>id 3</task-notification>", True),
                                ("<system-reminder>x", True), ("<b>bold question</b>", False), ("plain", False)):
            check("is_harness(%r) is %s" % (prompt[:20], harness), R.is_harness(prompt) is harness)

        print("\n== search_and_render ==")
        con = B.db()
        try:
            block = R.search_and_render(con, "where are credentials stored keepass")
            check("a question the vault covers returns its note",
                  "2026-09-01-decision-credentials-live-in-keepass.md" in block, block)
            check("wrapped as untrusted data, the way the hook injects a first result",
                  block.startswith(B.UNTRUSTED_HEADER) and block.rstrip().endswith(B.UNTRUSTED_FOOTER), block)
            check("the linked runbook comes along as related",
                  "rotating-a-keepass-credential" in block and "(related)" in block, block)
            check("an unrelated note is not included", "sourdough" not in block, block)
            check("a question about something the vault does not know returns nothing",
                  R.search_and_render(con, "kubernetes ingress rate limiting in staging") == "")
            check("a trivial prompt returns nothing", R.search_and_render(con, "ok") == "")
            check("the result is the same on a second call (no session state involved)",
                  R.search_and_render(con, "where are credentials stored keepass") == block)
        finally:
            con.close()

        print("\n== render_block ==")
        hits = [(9.0, "30-Knowledge/a.md", "Note A", "the excerpt of A"),
                (5.0, "30-Knowledge/b.md", "Note B", ""),
                (4.0, "30-Knowledge/c.md", "Note C", "")]
        block, kept = R.render_block(hits, [("related", "30-Knowledge/d.md", "Note D")], cap=10_000,
                                     pointer_only=False, link_notice="", first_time=False)
        check("each hit is a pointer line with its path, the first with its excerpt",
              "· Note A — `30-Knowledge/a.md`\n  the excerpt of A" in block and "`30-Knowledge/c.md`" in block, block)
        check("related notes are marked", "· Note D — `30-Knowledge/d.md`  (related)" in block, block)
        check("a non-first injection uses the short wrapper",
              block.startswith("<vault-notes>\n") and "Read them with Read only if they are relevant." in block, block)
        small, kept_small = R.render_block(hits, [], cap=40, pointer_only=True, link_notice="", first_time=False)
        check("a tight cap trims lines from the end, keeping at least one",
              kept_small >= 1 and kept_small < 3 and "Note A" in small and "Note C" not in small, (kept_small, small))
        check("pointer_only drops the excerpt", "the excerpt of A" not in small, small)
    finally:
        pass
    return finish()


def finish():
    shutil.rmtree(ROOT, ignore_errors=True)
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
