#!/usr/bin/env python3
"""Tests for files.py, the file store's CLI, run as a subprocess in a scratch world.

A temporary vault, state directory, HOME and files directory; nothing on the real machine is
touched. Run standalone:

    python3 _bin/files_test.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, "files.py")
sys.path.insert(0, HERE)

ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)
    return path


def main():
    root = tempfile.mkdtemp(prefix="files-cli-")
    try:
        vault, state, home = (os.path.join(root, n) for n in ("vault", "state", "home"))
        files = os.path.join(root, "files")
        os.makedirs(home)
        note_rel = "30-Knowledge/2026-09-15-demo.md"
        note = write(os.path.join(vault, note_rel), "---\ntitle: Demo\n---\n\n## Context\n\nA demo.\n")
        write(os.path.join(vault, "10-Projects", "other.md"), "# Other\n")
        src = os.path.join(root, "src")
        report = write(os.path.join(src, "report.pdf"), "pdf bytes\n")
        data = write(os.path.join(src, "data.csv"), "a,b\n1,2\n")
        base = {k: v for k, v in os.environ.items() if not k.startswith("BRAIN_")}
        base.update(HOME=home, BRAIN_VAULT=vault, BRAIN_STATE=state, PYTHONDONTWRITEBYTECODE="1")

        def run(*args, **env):
            e = dict(base, **env)
            p = subprocess.run([sys.executable, CLI] + list(args), env=e, cwd=root, stdin=subprocess.DEVNULL,
                               capture_output=True, text=True, timeout=120)
            return p.returncode, p.stdout, p.stderr

        print("\n== unconfigured ==")
        rc, out, err = run("put", report, "--to", note_rel, "--project", "demo")
        check("with no files directory configured put stops with exit 3 and names the first-run step",
              rc == 3 and "first_run.py" in err and "files" in err, (rc, out, err))
        check("and writes nothing into the note", "## Files" not in open(note).read())

        print("\n== put, through BRAIN_FILES_DIR ==")
        rc, out, err = run("put", report, data, "--to", note_rel, "--project", "demo", "--kind", "deliverable",
                           "--caption", "the demo\nreport", "--date", "2026-09-15", BRAIN_FILES_DIR=files)
        stored = sorted(os.path.relpath(os.path.join(dp, f), files) for dp, _, fs in os.walk(files) for f in fs)
        check("put exits 0", rc == 0, (rc, out, err))
        pdf = [s for s in stored if s.endswith(".pdf")]
        check("the files land under <project>/<date>/<kind>/ with the digest in the name",
              len(pdf) == 1 and pdf[0].startswith(os.path.join("demo", "2026-09-15", "deliverable", "report-"))
              and any(s.startswith(os.path.join("demo", "2026-09-15", "deliverable", "data-")) for s in stored), stored)
        check("the stored copy is the same content", open(os.path.join(files, pdf[0])).read() == "pdf bytes\n")
        text = open(note).read()
        check("the note gets one ## Files section with both references on single lines",
              text.count("\n## Files\n") == 1 and text.count("- `demo/2026-09-15/deliverable/") == 2
              and "the demo report" in text, text)
        manifest = json.load(open(os.path.join(files, "demo", "manifest.json")))
        check("the project manifest lists both, with the note and kind",
              len(manifest["objects"]) == 2 and all(o["note"] == note_rel and o["kind"] == "deliverable"
                                                   for o in manifest["objects"]), manifest)

        rc, out, err = run("put", report, "--to", note_rel, "--project", "demo", "--date", "2026-09-15",
                           BRAIN_FILES_DIR=files)
        check("storing the same file again copies nothing and anchors nothing new",
              rc == 0 and "already stored" in out and "0 new reference" in out
              and open(note).read() == text, (rc, out, err))

        print("\n== ls and get ==")
        rc, out, err = run("ls", "--project", "demo", BRAIN_FILES_DIR=files)
        check("ls lists the project's files and not the manifest",
              rc == 0 and "2 file(s)" in out and "manifest.json" not in out, (rc, out, err))
        key = pdf[0].replace(os.sep, "/")
        outdir = os.path.join(root, "out")
        rc, out, err = run("get", key, "--out", outdir, BRAIN_FILES_DIR=files)
        check("get copies a stored file out", rc == 0 and open(os.path.join(outdir, os.path.basename(key))).read()
              == "pdf bytes\n", (rc, out, err))
        rc, out, err = run("get", "demo/2026-09-15/deliverable/report.pdf", "--out", outdir, BRAIN_FILES_DIR=files)
        check("a key without the digest finds the one file that has it", rc == 0 and "is not there" in err, (rc, out, err))
        rc, out, err = run("get", "../etc/passwd", BRAIN_FILES_DIR=files)
        check("a key that climbs out of the directory is refused", rc == 2, (rc, err))

        print("\n== check ==")
        rc, out, err = run("check", BRAIN_FILES_DIR=files)
        check("with every file cited check exits 0", rc == 0 and "broken references (the note cites something no longer "
              "there): 0" in out and "orphans (stored but nobody cites them): 0" in out, (rc, out, err))
        write(os.path.join(files, "demo", "material", "stray.bin"), "x")
        os.remove(os.path.join(files, pdf[0]))
        rc, out, err = run("check", BRAIN_FILES_DIR=files)
        check("a removed file is a broken reference and an uncited one an orphan, exit 1",
              rc == 1 and key in out and "demo/material/stray.bin" in out, (rc, out, err))

        print("\n== refusals ==")
        rc, _, err = run("put", report, "--to", note_rel, "--project", "demo", "--kind", "entregable",
                         BRAIN_FILES_DIR=files)
        check("an unknown kind is a usage error", rc == 2 and "deliverable" in err, (rc, err))
        rc, _, err = run("put", report, "--to", note_rel, "--project", "../up", BRAIN_FILES_DIR=files)
        check("a project that is not a slug is refused", rc == 2, (rc, err))
        rc, _, err = run("put", report, "--to", "30-Knowledge/missing.md", "--project", "demo", BRAIN_FILES_DIR=files)
        check("a note that does not exist is refused", rc == 1 and "does not exist" in err, (rc, err))
        rc, _, err = run("put", report, "--to", "../outside.md", "--project", "demo", BRAIN_FILES_DIR=files)
        check("a note outside the vault is refused", rc == 1, (rc, err))

        print("\n== the first-run config file ==")
        import brain_files

        chosen = os.path.join(root, "chosen")
        brain_files.set_files_dir(chosen, config_path=os.path.join(state, "files-dir.json"))
        rc, out, err = run("put", data, "--to", "10-Projects/other.md", "--project", "other", "--kind", "material")
        check("with no BRAIN_FILES_DIR the directory recorded by the first run is used",
              rc == 0 and os.path.isdir(os.path.join(chosen, "other", "material")), (rc, out, err))
        rc, out, err = run("ls", BRAIN_FILES_DIR=files)
        check("and BRAIN_FILES_DIR still wins over it", rc == 0 and "other/material" not in out, (rc, out))
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
