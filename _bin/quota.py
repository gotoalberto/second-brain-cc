#!/usr/bin/env python3
"""One ledger of every service with a quota, shared by every machine through the vault.

Whatever skill or routine spends a quota (API credits, a plan's usage window, a daily allowance
of generations), it is recorded in one place, so any session on any machine can see what is left
before it starts a job. Two kinds of rows, appended to 90-Meta/quota/<YYYY-MM>-<machine>.jsonl:
one file per machine and month, so vault syncs never conflict. <machine> is
machine_identity.public_id(), an 8-hex id that never carries the hostname.

  spend     something was consumed:  quota.py spend image-api 4 --what "spring fair poster" --skill poster-maker
  reading   a value read on the service's own page (the truth):
            quota.py reading image-api --remaining 960
            quota.py reading search-api --used-pct 40 --window day --resets "00:00 UTC"

  quota.py status [service]           per service: the last reading, what was spent after it, the
                                      estimate now, the spend in the last 5 h / day / week / month,
                                      and the limits the catalogue knows
  quota.py services                   the catalogue (90-Meta/quota/services.json): unit, limits,
                                      where to check
  quota.py log [service] [--days 7]   the raw rows, oldest first

Before a job that spends a quota: `status <service>` (and take a fresh `reading` when the service
shows one). After it: one `spend` row per unit of work. A service that is not in the catalogue is
refused: add it to services.json first (name, unit, limits, check, skills).
"""
import argparse
import datetime as dt
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

VAULT = os.environ.get("BRAIN_VAULT") or os.path.dirname(HERE)
QDIR = os.path.join(VAULT, "90-Meta", "quota")
SERVICES = os.path.join(QDIR, "services.json")
WINDOWS = {"5h": dt.timedelta(hours=5), "day": dt.timedelta(days=1), "week": dt.timedelta(days=7),
           "month": dt.timedelta(days=30)}


def now():
    return dt.datetime.now(dt.timezone.utc)


def machine():
    """This machine's id in the ledger: never its hostname, the files travel in the vault's git."""
    import machine_identity

    return machine_identity.public_id()


def services():
    try:
        with open(SERVICES, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as exc:
        sys.exit(f"quota: cannot read the catalogue {SERVICES} ({type(exc).__name__}); "
                 "it lists every service with a quota")
    if not isinstance(data, dict):
        sys.exit(f"quota: {SERVICES} must be a JSON object of services")
    return data


def rows(service=None, since=None):
    """Every row of every machine's file, oldest first. A line that does not parse is skipped:
    a file can arrive half synced."""
    out = []
    for path in sorted(glob.glob(os.path.join(QDIR, "*.jsonl"))):
        try:
            with open(path, encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                t = dt.datetime.fromisoformat(r["at"])
            except (ValueError, KeyError, TypeError):
                continue
            if not isinstance(r, dict) or (service and r.get("service") != service):
                continue
            if since and t < since:
                continue
            r["_t"] = t
            out.append(r)
    return sorted(out, key=lambda r: r["_t"])


def append(row):
    os.makedirs(QDIR, exist_ok=True)
    path = os.path.join(QDIR, f"{now():%Y-%m}-{row['machine']}.jsonl")
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def check_service(name, cat=None):
    cat = services() if cat is None else cat
    if name not in cat:
        sys.exit(f"quota: unknown service {name!r}; known: {', '.join(sorted(cat)) or 'none'}. "
                 f"Add it to {SERVICES} first.")
    return cat[name]


def _amount(r):
    try:
        return float(r.get("amount") or 0)
    except (TypeError, ValueError):
        return 0.0


def status(name, svc, out=print):
    rs = rows(name)
    out(f"{name}: {svc.get('name', name)} ({svc.get('unit', '?')})")
    for lim in svc.get("limits", []):
        out(f"  limit: {lim}")
    idx = [i for i, r in enumerate(rs) if r.get("kind") == "reading"]
    last = rs[idx[-1]] if idx else None
    if last:
        after = sum(_amount(r) for r in rs[idx[-1] + 1:] if r.get("kind") == "spend" and r.get("unit") == svc.get("unit"))
        bits = [f"{k}={last[k]:g}" if isinstance(last.get(k), (int, float)) else f"{k}={last[k]}"
                for k in ("remaining", "used_pct", "window", "resets") if last.get(k) is not None]
        out(f"  last reading {last['at'][:16]} ({last.get('machine', '?')}): {', '.join(bits)}")
        if last.get("remaining") is not None:
            out(f"  estimate now: {last['remaining'] - after:g} {svc.get('unit')} left ({after:g} spent since that reading)")
        elif after:
            out(f"  spent since that reading: {after:g} {svc.get('unit')}")
    else:
        out(f"  no reading yet; check: {svc.get('check', '?')}")
    t = now()
    units = sorted({r.get("unit") for r in rs if r.get("kind") == "spend" and r.get("unit")}) or [svc.get("unit")]
    for u in units:
        sums = []
        for w, d in WINDOWS.items():
            s = sum(_amount(r) for r in rs if r.get("kind") == "spend" and r.get("unit") == u and r["_t"] > t - d)
            sums.append(f"{w} {s:g}")
        out(f"  spent ({u}) in the last " + ", ".join(sums))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="quota.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("spend", help="record something consumed")
    p.add_argument("service")
    p.add_argument("amount", type=float)
    p.add_argument("--what", default="")
    p.add_argument("--skill", default="")
    p.add_argument("--unit", default="",
                   help="when the spend is counted in another unit than the service's (items on a percent quota)")
    p = sub.add_parser("reading", help="record a value read on the service's own page")
    p.add_argument("service")
    p.add_argument("--remaining", type=float)
    p.add_argument("--used-pct", type=float)
    p.add_argument("--window", default="")
    p.add_argument("--resets", default="")
    p.add_argument("--note", default="")
    p = sub.add_parser("status", help="what is left, per service")
    p.add_argument("service", nargs="?")
    sub.add_parser("services", help="the catalogue")
    p = sub.add_parser("log", help="the raw rows")
    p.add_argument("service", nargs="?")
    p.add_argument("--days", type=float, default=7)
    a = ap.parse_args(argv)

    if a.cmd == "services":
        for k, v in sorted(services().items()):
            print(f"{k}: {v.get('name', k)} | unit {v.get('unit', '?')} | check: {v.get('check', '?')}")
            for lim in v.get("limits", []):
                print(f"    {lim}")
        return 0
    if a.cmd == "status":
        cat = services()
        for k in ([a.service] if a.service else sorted(cat)):
            status(k, check_service(k, cat))
        return 0
    if a.cmd == "log":
        for r in rows(a.service, now() - dt.timedelta(days=a.days)):
            r.pop("_t")
            print(json.dumps(r, ensure_ascii=False))
        return 0
    svc = check_service(a.service)
    row = {"at": now().isoformat(timespec="seconds"), "machine": machine(), "service": a.service, "kind": a.cmd}
    if a.cmd == "spend":
        if not a.amount > 0:
            sys.exit("quota: a spend amount must be positive")
        row.update(amount=a.amount, unit=a.unit or svc.get("unit"), what=a.what, skill=a.skill)
    else:
        if a.remaining is None and a.used_pct is None:
            sys.exit("quota: a reading needs --remaining or --used-pct")
        row.update(remaining=a.remaining, used_pct=a.used_pct, window=a.window or None,
                   resets=a.resets or None, note=a.note or None)
    print("recorded in", append(row))
    return 0


if __name__ == "__main__":
    sys.exit(main())
