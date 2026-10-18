#!/usr/bin/env python3
"""Tests for quota.py, the global ledger of every service with a quota.

The vault, the catalogue and the ledger files are temporary; the machine is forced through
BRAIN_MACHINE_KEY and the clock is fixed. Run standalone:

    python3 _bin/quota_test.py
"""
import contextlib
import datetime as dt
import io
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

ok, fail = [], []
TMP = []
NOW = dt.datetime(2026, 10, 18, 12, 0, tzinfo=dt.timezone.utc)
CATALOGUE = {
    "image-api": {"name": "An image generation API", "unit": "credits", "limits": ["1,000 credits a month"],
                  "check": "the provider's billing page", "skills": ["poster-maker"]},
    "search-api": {"name": "A web search API", "unit": "requests", "limits": [], "check": "its dashboard"},
}


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail and not cond else ""))


def world(Q, key="studio-0f0f0f0f", catalogue=CATALOGUE):
    root = tempfile.mkdtemp(prefix="quota-test-")
    TMP.append(root)
    qdir = os.path.join(root, "90-Meta", "quota")
    os.makedirs(qdir)
    if catalogue is not None:
        with open(os.path.join(qdir, "services.json"), "w") as fh:
            json.dump(catalogue, fh)
    Q.QDIR, Q.SERVICES = qdir, os.path.join(qdir, "services.json")
    Q.now = lambda: NOW
    os.environ["BRAIN_MACHINE_KEY"] = key
    return qdir


def cli(Q, *args):
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = Q.main(list(args)) or 0
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
            if not isinstance(exc.code, int) and exc.code:
                err.write(str(exc.code))
    return code, out.getvalue(), err.getvalue()


def test_ledger(Q):
    print("\n== spend and reading rows ==")
    qdir = world(Q)
    cli(Q, "reading", "image-api", "--remaining", "100")
    cli(Q, "spend", "image-api", "10", "--what", "a poster for the spring fair", "--skill", "poster-maker")
    code, out, _ = cli(Q, "status", "image-api")
    check("the estimate is the last reading minus what was spent after it", code == 0 and "90 credits left" in out, out)
    files = sorted(f for f in os.listdir(qdir) if f.endswith(".jsonl"))
    check("rows land in one file per month and machine, named by the machine's public id",
          files == ["2026-10-0f0f0f0f.jsonl"], files)
    check("never by its hostname", not any("studio" in f for f in files), files)
    rows = [json.loads(l) for l in open(os.path.join(qdir, files[0]))] if files else []
    check("each row says when, which machine, which service and what kind",
          len(rows) == 2 and rows[1]["kind"] == "spend" and rows[1]["amount"] == 10 and rows[1]["unit"] == "credits"
          and rows[1]["machine"] == "0f0f0f0f" and rows[1]["at"] == "2026-10-18T12:00:00+00:00"
          and rows[1]["what"] == "a poster for the spring fair" and rows[1]["skill"] == "poster-maker", rows)

    print("\n== the ledger is shared ==")
    with open(os.path.join(qdir, "2026-10-1a2b3c4d.jsonl"), "w") as fh:
        fh.write(json.dumps({"at": "2026-10-18T12:00:01+00:00", "machine": "1a2b3c4d", "service": "image-api",
                             "kind": "spend", "amount": 5, "unit": "credits", "what": "", "skill": ""}) + "\n")
        fh.write("not json, a half-synced line\n\n")
    code, out, _ = cli(Q, "status", "image-api")
    check("another machine's spend counts against the same reading", code == 0 and "85 credits left" in out, out)
    check("and a broken line is skipped, not a crash", code == 0)
    code, out, _ = cli(Q, "status")
    check("status with no service covers the whole catalogue", "image-api" in out and "search-api" in out, out)
    check("a service with no reading says where to check", "no reading yet; check: its dashboard" in out, out)


def test_units_and_windows(Q):
    print("\n== units and windows ==")
    qdir = world(Q)
    cli(Q, "reading", "image-api", "--remaining", "50")
    cli(Q, "spend", "image-api", "3", "--unit", "posters")
    code, out, _ = cli(Q, "status", "image-api")
    check("a spend in another unit is not subtracted from the reading", "50 credits left" in out, out)
    check("but it is summed in its own unit", "spent (posters) in the last 5h 3" in out, out)
    old = {"at": (NOW - dt.timedelta(days=3)).isoformat(timespec="seconds"), "machine": "0f0f0f0f",
           "service": "search-api", "kind": "spend", "amount": 7, "unit": "requests", "what": "", "skill": ""}
    with open(os.path.join(qdir, "2026-10-0f0f0f0f.jsonl"), "a") as fh:
        fh.write(json.dumps(old) + "\n")
    code, out, _ = cli(Q, "status", "search-api")
    check("the windows sum only what falls inside them",
          "spent (requests) in the last 5h 0, day 0, week 7, month 7" in out, out)
    code, out, _ = cli(Q, "log", "search-api", "--days", "1")
    check("log --days leaves older rows out", out.strip() == "", out)
    code, out, _ = cli(Q, "log", "search-api", "--days", "7")
    check("and prints the rows inside the window as JSON", json.loads(out.strip())["amount"] == 7, out)


def test_refusals(Q):
    print("\n== refusals ==")
    world(Q)
    code, out, err = cli(Q, "spend", "unknown-api", "1")
    check("an unknown service is refused, naming the catalogue", code != 0 and "services.json" in err, (code, err))
    code, out, err = cli(Q, "spend", "image-api", "-5")
    check("a negative or zero spend is refused", code != 0 and "positive" in err, (code, err))
    code, out, err = cli(Q, "spend", "image-api", "0")
    check("a zero spend is refused too", code != 0 and "positive" in err, (code, err))
    code, out, err = cli(Q, "reading", "image-api")
    check("a reading needs --remaining or --used-pct", code != 0 and "--remaining" in err, (code, err))
    code, out, _ = cli(Q, "reading", "image-api", "--used-pct", "40", "--window", "day", "--resets", "00:00")
    code, out, _ = cli(Q, "status", "image-api")
    check("a percent reading is shown as read", "used_pct=40" in out and "window=day" in out, out)
    world(Q, catalogue=None)
    code, out, err = cli(Q, "services")
    check("a missing catalogue is one clear line, not a traceback",
          code != 0 and "services.json" in err and "Traceback" not in err, (code, err))
    code, out, _ = (lambda: (world(Q), cli(Q, "services"))[1])()
    check("services lists the catalogue with units and where to check",
          code == 0 and "image-api: An image generation API | unit credits | check: the provider's billing page" in out,
          out)


def test_shipped_catalogue(Q):
    print("\n== the catalogue shipped with the vault ==")
    path = os.path.join(os.path.dirname(HERE), "90-Meta", "quota", "services.json")
    try:
        with open(path) as fh:
            cat = json.load(fh)
    except (OSError, ValueError) as exc:
        cat = None
        check("90-Meta/quota/services.json parses", False, exc)
    if cat is not None:
        check("it is an object of services", isinstance(cat, dict) and cat, cat)
        check("each service has a name, a unit and where to check it",
              all(isinstance(v, dict) and v.get("name") and v.get("unit") and v.get("check") for v in cat.values()),
              cat)


def main():
    saved = os.environ.get("BRAIN_MACHINE_KEY")
    try:
        import quota as Q
    except Exception as exc:
        check("quota imports", False, "%s: %s" % (type(exc).__name__, exc))
    else:
        for t in (test_ledger, test_units_and_windows, test_refusals, test_shipped_catalogue):
            try:
                t(Q)
            except Exception as exc:
                import traceback
                traceback.print_exc()
                check("%s ran to the end" % t.__name__, False, "%s: %s" % (type(exc).__name__, exc))
    finally:
        if saved is None:
            os.environ.pop("BRAIN_MACHINE_KEY", None)
        else:
            os.environ["BRAIN_MACHINE_KEY"] = saved
        for d in TMP:
            shutil.rmtree(d, ignore_errors=True)
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
