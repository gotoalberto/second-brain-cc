#!/usr/bin/env python3
"""Tests for google_core.calendar_guard with a fake Calendar API. No request leaves the machine.

Every address below is invented. Run standalone:

    python3 _bin/google_core/calendar_guard_test.py
"""
import datetime as dt
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[0] = os.path.dirname(HERE)

from google_core import calendar_guard as cg  # noqa: E402

ok, fail = [], []


def check(name, cond, detail=""):
    (ok if cond else fail).append(name)
    print("  %s %s%s" % ("✓" if cond else "✗", name, ("\n      → " + str(detail)) if detail else ""))


ME = "me@example.com"
EV = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
TZ = "Europe/Paris"
NOW = dt.datetime(2029, 12, 1, tzinfo=dt.timezone.utc)


def fake(events, busy=None, current=None, fail_list=False):
    """events: own calendar items; busy: {email: [(start, end)] or None}; current: the event being patched."""
    calls = []

    def call(url, method="GET", body=None):
        calls.append((method, url, body))
        if url.endswith("/freeBusy"):
            cals = {}
            for e in body["items"]:
                b = (busy or {}).get(e["id"])
                cals[e["id"]] = {"errors": [{"reason": "notFound"}]} if b is None else \
                    {"busy": [{"start": s, "end": en} for s, en in b]}
            return {"calendars": cals}
        if "/events?" in url:
            return {"_http_error": 403, "_body": "no"} if fail_list else {"items": events}
        if "/events/" in url:
            return current or {"_http_error": 404}
        raise AssertionError(url)
    return call, calls


def ev(i, s, e, summary="x", **kw):
    d = {"id": i, "summary": summary, "start": {"dateTime": s}, "end": {"dateTime": e}}
    d.update(kw)
    return d


TEAM = ev("team", "2030-01-07T16:30:00+01:00", "2030-01-07T17:00:00+01:00", "Team sync")
BODY = {"summary": "Interview", "start": {"dateTime": "2030-01-07T16:30:00+01:00", "timeZone": TZ},
        "end": {"dateTime": "2030-01-07T17:15:00+01:00", "timeZone": TZ}}


def guard(call, url, method, body):
    return cg.guard(call, url, method, body, (ME,), now=NOW)


def test_target():
    check("POST events is a write", cg.target(EV, "POST") == ("primary", None))
    check("PATCH on an event is a write", cg.target(EV + "/abc?sendUpdates=all", "PATCH") == ("primary", "abc"))
    check("an escaped calendar id is unescaped",
          cg.target("https://www.googleapis.com/calendar/v3/calendars/a%40example.com/events", "POST")
          == ("a@example.com", None))
    check("freeBusy is not", cg.target("https://www.googleapis.com/calendar/v3/freeBusy", "POST") is None)
    check("another Google API is not", cg.target("https://www.googleapis.com/drive/v3/files", "POST") is None)
    check("quickAdd is not", cg.target(EV + "/quickAdd", "POST") is None)
    check("a GET is not", cg.target(EV, "GET") is None)
    check("a PATCH with no event id is not", cg.target(EV, "PATCH") is None)


def test_create():
    call, _ = fake([TEAM])
    rep = guard(call, EV, "POST", BODY)
    check("an overlap blocks the write", rep and rep["blocked"], rep)
    check("and names the conflicting event", rep and rep["conflicts"][0]["summary"] == "Team sync", rep)
    check("it offers alternatives that avoid it", rep and rep["alternatives"] and
          all(not a["start"].startswith("2030-01-07T16:") for a in rep["alternatives"]), rep and rep["alternatives"])
    days = {a["start"][:10] for a in rep["alternatives"]} if rep else set()
    check("at most two alternatives a day",
          rep and max(sum(a["start"][:10] == d for a in rep["alternatives"]) for d in days) <= cg.PER_DAY)
    check("never on a weekend",
          rep and all(dt.date.fromisoformat(a["start"][:10]).weekday() < 5 for a in rep["alternatives"]))
    call, _ = fake([])
    check("a free slot goes through", guard(call, EV, "POST", BODY) is None)
    call, _ = fake([dict(TEAM, transparency="transparent")])
    check("'free' events do not block", guard(call, EV, "POST", BODY) is None)
    call, _ = fake([dict(TEAM, attendees=[{"email": ME, "self": True, "responseStatus": "declined"}])])
    check("declined events do not block", guard(call, EV, "POST", BODY) is None)
    call, _ = fake([dict(TEAM, eventType="workingLocation")])
    check("a working-location marker does not block", guard(call, EV, "POST", BODY) is None)
    call, _ = fake([TEAM])
    check("an event written as free is never checked",
          guard(call, EV, "POST", dict(BODY, transparency="transparent")) is None)
    call, _ = fake([TEAM], fail_list=True)
    try:
        guard(call, EV, "POST", BODY)
        check("a calendar that cannot be read raises, never reads as free", False)
    except cg.GuardError as exc:
        check("a calendar that cannot be read raises, never reads as free", "403" in str(exc), exc)


def test_attendees():
    body = dict(BODY, attendees=[{"email": ME}, {"email": "b@example.com"}, {"email": "ext@example.org"}])
    call, calls = fake([], busy={"b@example.com": [("2030-01-07T17:00:00+01:00", "2030-01-07T18:00:00+01:00")]})
    rep = guard(call, EV, "POST", body)
    check("a busy attendee blocks", rep and rep["conflicts"][0]["who"] == "b@example.com", rep)
    check("an attendee Google does not share is listed as unknown", rep and rep["unknown"] == ["ext@example.org"])
    check("this account is not asked about in freeBusy", ME not in str([c for c in calls if "freeBusy" in c[1]]))


def test_move():
    cur = dict(BODY, id="int", start={"dateTime": "2030-01-06T16:30:00+01:00", "timeZone": TZ},
               end={"dateTime": "2030-01-06T17:15:00+01:00", "timeZone": TZ},
               attendees=[{"email": ME, "self": True}, {"email": "b@example.com"}])
    mv = {"start": BODY["start"], "end": BODY["end"]}
    call, _ = fake([TEAM, ev("int", "2030-01-06T16:30:00+01:00", "2030-01-06T17:15:00+01:00")], current=cur)
    rep = guard(call, EV + "/int", "PATCH", mv)
    check("moving onto an event blocks", rep and [c["summary"] for c in rep["conflicts"]] == ["Team sync"], rep)
    call, _ = fake([ev("int", "2030-01-07T16:30:00+01:00", "2030-01-07T17:15:00+01:00")],
                   busy={"b@example.com": [("2030-01-07T16:00:00+01:00", "2030-01-07T17:15:00+01:00")]},
                   current=dict(cur, start=BODY["start"], end=BODY["end"]))
    check("editing only the description is not checked",
          guard(call, EV + "/int", "PATCH", {"description": "new"}) is None)
    cur2 = dict(cur, start={"dateTime": "2030-01-07T16:15:00+01:00"}, end={"dateTime": "2030-01-07T17:00:00+01:00"})
    call, _ = fake([], busy={"b@example.com": [("2030-01-07T16:15:00+01:00", "2030-01-07T17:00:00+01:00")]},
                   current=cur2)
    check("the attendee's copy of the moved event is ignored", guard(call, EV + "/int", "PATCH", mv) is None)



def test_slots_and_write_agree():
    # A dry check must give the answer the write would give. `google.py slots` calls check() the
    # way the line below does; a write goes through guard(). Same attendees, same slot, same
    # calendar replies: same conflicts, same unknowns, same alternatives, the same freeBusy asked.
    people = [ME, "dana@example.org", "lee@example.net"]
    busy = {"dana@example.org": [("2030-01-07T16:45:00+01:00", "2030-01-07T17:15:00+01:00")]}
    start, end = cg.parse_ts(BODY["start"], TZ), cg.parse_ts(BODY["end"], TZ)

    def both(busy):
        dry_call, dry_calls = fake([], busy=busy)
        dry = cg.check(dry_call, "primary", start, end, [{"email": p} for p in people], TZ, me=(ME,), now=NOW)
        write_call, write_calls = fake([], busy=busy)
        body = dict(BODY, attendees=[{"email": ME, "self": True}] + [{"email": p} for p in people[1:]])
        wet = cg.guard(write_call, EV, "POST", body, (ME,), default_tz=TZ, now=NOW)
        return dry, wet, dry_calls, write_calls

    dry, wet, dry_calls, write_calls = both(busy)
    check("a busy attendee is a conflict on both paths",
          dry["conflicts"] and wet and wet["conflicts"] == dry["conflicts"], (dry, wet))
    check("an attendee whose calendar is not shared is unknown on both, never free",
          dry["unknown"] == ["lee@example.net"] and wet and wet["unknown"] == dry["unknown"], (dry, wet))
    check("and both offer the same alternatives", wet and wet["alternatives"] == dry["alternatives"])
    check("both ask freeBusy the same question",
          [c for c in dry_calls if "freeBusy" in c[1]] == [c for c in write_calls if "freeBusy" in c[1]],
          (dry_calls, write_calls))
    dry, wet, _, _ = both({})
    check("a slot the dry check calls free is one the write books",
          dry["conflicts"] == [] and wet is None, (dry, wet))
    check("an attendee nobody can see does not stop the write; only the dry check names it as unknown",
          dry["unknown"] == ["dana@example.org", "lee@example.net"], dry)

def test_helpers():
    check("hours parse", cg.parse_hours("15-20") == (15, 20))
    for bad in ("20-15", "x", "9-24"):
        try:
            cg.parse_hours(bad)
            check("bad hours %r are refused" % bad, False)
        except ValueError:
            check("bad hours %r are refused" % bad, True)
    check("the local zone comes from TZ", cg.local_zone({"TZ": "Asia/Tokyo"}) == "Asia/Tokyo")
    check("else from the /etc/localtime link",
          cg.local_zone({}, readlink=lambda p: "/usr/share/zoneinfo/America/Chicago") == "America/Chicago")
    check("and falls back to UTC", cg.local_zone({"TZ": "Not/AZone"}, readlink=lambda p: "") == "UTC")
    check("an all-day date starts at midnight in its zone",
          cg.parse_ts({"date": "2030-01-07", "timeZone": TZ}).isoformat() == "2030-01-07T00:00:00+01:00")
    alts = cg.alternatives([], dt.datetime(2030, 1, 7, 9, tzinfo=dt.timezone.utc), dt.timedelta(minutes=30),
                           "UTC", now=dt.datetime(2030, 1, 7, 12, tzinfo=dt.timezone.utc))
    check("no alternative is in the past", alts and all(a["start"] >= "2030-01-07T12:00" for a in alts), alts)


def test_join_link():
    link = "https://meet.google.com/aaa-bbbb-ccc"
    check("the Meet link opens as the given account",
          cg.meet_join_link({"hangoutLink": link}, "dana@example.org")
          == link + "?authuser=dana%40example.org")
    check("a query string already in the link is kept",
          cg.meet_join_link({"hangoutLink": link + "?hs=1"}, ME).startswith(link + "?hs=1&authuser="))
    check("an event without a Meet gives no link", cg.meet_join_link({"summary": "x"}, ME) is None)
    check("an API error gives no link", cg.meet_join_link({"_http_error": 400}, ME) is None)
    check("no account to open it as gives no link", cg.meet_join_link({"hangoutLink": link}, "") is None)
    check("nothing at all gives no link", cg.meet_join_link(None, ME) is None)


def test_meeting():
    start = cg.parse_ts("2030-01-07T11:00:00+01:00")
    w = cg.meeting_windows(start, 90, 40)
    check("the trip there ends when the meeting starts",
          w[0][0] == "travel_to" and w[0][1] == start - dt.timedelta(minutes=40) and w[0][2] == start, w)
    check("the main slot is the meeting itself",
          w[1] == ("main", start, start + dt.timedelta(minutes=90)), w)
    check("the trip back starts when it ends",
          w[2][0] == "travel_back" and w[2][1] == start + dt.timedelta(minutes=90)
          and w[2][2] == start + dt.timedelta(minutes=130), w)
    check("without travel only the main slot is checked", [x[0] for x in cg.meeting_windows(start, 30)] == ["main"])

    def cal(*events):
        return fake([ev(n, s, e, n) for n, s, e in events], busy={"sam@example.org": []})[0]

    me = {"home": ("me@example.com",), "work": ("me@example.org",)}
    free = {"home": cal(), "work": cal()}
    rep = cg.check_meeting(free, me, "home", start, 90, 40, tz=TZ, now=NOW)
    check("everything free: no clashes and no alternatives",
          rep["clashes"] == [] and rep["alternatives"] == [] and rep["host"] == "home", rep)

    calls = {"home": cal(), "work": cal(("Standup", "2030-01-07T10:30:00+01:00", "2030-01-07T10:45:00+01:00"))}
    rep = cg.check_meeting(calls, me, "home", start, 90, 40, tz=TZ, now=NOW)
    check("a clash on the other calendar during the trip there is reported",
          [(c["account"], c["slot"]) for c in rep["clashes"]] == [("work", "travel_to")], rep)
    check("and names the event", rep["clashes"][0]["conflicts"][0]["summary"] == "Standup", rep)
    check("a clash outside the host's main slot offers no alternatives", rep["alternatives"] == [], rep)

    calls = {"home": cal(("Lunch", "2030-01-07T12:00:00+01:00", "2030-01-07T13:00:00+01:00")), "work": cal()}
    rep = cg.check_meeting(calls, me, "work", start, 90, 40, tz=TZ, now=NOW)
    slots = [(c["account"], c["slot"]) for c in rep["clashes"]]
    check("a clash on the mirror calendar during the meeting is reported", ("home", "main") in slots, rep)
    check("and so is the trip back that overlaps it", ("home", "travel_back") in slots, rep)

    calls = {"home": cal(), "work": cal(("Sync", "2030-01-07T11:00:00+01:00", "2030-01-07T11:30:00+01:00"))}
    rep = cg.check_meeting(calls, me, "work", start, 30, tz=TZ, now=NOW)
    check("a clash on the host's main slot comes with alternatives", rep["alternatives"], rep)

    seen = []

    def spy(url, method="GET", body=None):
        if url.endswith("/freeBusy"):
            seen.append(tuple(i["id"] for i in body["items"]))
            return {"calendars": {i["id"]: {"busy": []} for i in body["items"]}}
        return {"items": []}

    rep = cg.check_meeting({"home": spy, "work": spy}, me, "home", start, 30, 20,
                           guests=("sam@example.org", "kim@example.net"), tz=TZ, now=NOW)
    check("guests are looked up once, for the host's main slot", seen == [("sam@example.org", "kim@example.net")], seen)
    try:
        cg.check_meeting(free, me, "elsewhere", start, 30, tz=TZ, now=NOW)
        check("a host that is not one of the accounts is refused", False)
    except ValueError:
        check("a host that is not one of the accounts is refused", True)
    try:
        cg.check_meeting(free, me, "home", start, 30, -5, tz=TZ, now=NOW)
        check("negative travel is refused", False)
    except ValueError:
        check("negative travel is refused", True)


def main():
    for t in (test_target, test_create, test_attendees, test_move, test_slots_and_write_agree, test_helpers,
              test_join_link, test_meeting):
        print("\n== %s ==" % t.__name__)
        try:
            t()
        except Exception as exc:
            import traceback
            traceback.print_exc()
            check("%s ran without raising" % t.__name__, False, repr(exc))
    print("\nRESULT: %d passed, %d failed" % (len(ok), len(fail)))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
