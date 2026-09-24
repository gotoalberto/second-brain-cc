"""The conflict check before any calendar write google.py makes. Pure: every read goes through `call`.

The rule: whenever an event is added or moved, look at what is already in the calendar first. If
something is there, stop and propose alternatives instead of booking on top of it. It exists
because an interview was once moved onto a slot that already held another meeting, and nobody
noticed until afterwards.

How google.py uses it: `api` with POST, PATCH or PUT on a Calendar events URL goes through
`guard()` before the request leaves. When the new slot overlaps anything, nothing is written, the
conflicts and a handful of free alternatives are printed as JSON and google.py exits 3. Once the
user has picked a slot, or explicitly accepted the overlap, rerun with `--force`. `google.py slots`
runs the same check for a slot without writing anything.

What counts as a conflict:
  - the calendar being written: any event in the window that blocks time (not "free"/transparent,
    not cancelled, not declined by this account, not a working-location or focus marker left
    free), other than the event being moved;
  - other attendees: their free/busy, when Google shares it (the same organization usually does,
    outside addresses usually do not; those come back as "unknown", never as free). For a move,
    the attendee's copy of this very event, the old slot, is cut out.

Alternatives: slots of the same length where everyone visible is free, inside working hours
(09:00 to 19:00 in the event's time zone, Monday to Friday; `slots --hours` narrows it), at most
two per day, from the requested day on. They ignore other people's time zones: before offering
them, drop the ones that fall at night for someone.

`call(url, method="GET", body=None)` returns Google's JSON, or {"_http_error": status, ...} the way
google.py's `api` does. A read that fails raises GuardError: a check that could not look is not a
check that found the slot free.
"""
from __future__ import annotations

import datetime as dt
import re
import urllib.parse
from zoneinfo import ZoneInfo

EXIT_CONFLICT = 3
WORK_START, WORK_END = 9, 19
STEP_MIN = 15
MAX_SUGGESTIONS = 6
PER_DAY = 2                 # spread the suggestions over several days instead of one morning
SEARCH_DAYS = 7

CAL = "https://www.googleapis.com/calendar/v3"
_EVENTS_RE = re.compile(r"^https://www\.googleapis\.com/calendar/v3/calendars/([^/?]+)/events"
                        r"(?:/([^/?]+))?/?(?:\?.*)?$")


class GuardError(Exception):
    """The check could not read what it needs; the write must not go ahead on its own."""


def parse_ts(value, tz="UTC"):
    """A Google start/end dict or an ISO string, as an aware datetime. All-day dates start at 00:00."""
    if isinstance(value, dict):
        tz = value.get("timeZone") or tz
        value = value.get("dateTime") or value.get("date")
    if not value:
        return None
    if len(value) == 10:
        return dt.datetime.fromisoformat(value).replace(tzinfo=ZoneInfo(tz))
    d = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=ZoneInfo(tz))


def target(url, method):
    """(calendar_id, event_id or None) when this request writes a calendar event, else None."""
    m = _EVENTS_RE.match(url or "")
    if not m or method not in ("POST", "PATCH", "PUT"):
        return None
    cal, ev = urllib.parse.unquote(m.group(1)), m.group(2)
    if method == "POST" and ev:           # events/import, events/quickAdd, events/<id>/move ...
        return None
    if method in ("PATCH", "PUT") and not ev:
        return None
    return cal, ev


def _overlap(a0, a1, b0, b1):
    return a0 < b1 and b0 < a1


def _minus(blocks, hole):
    """Busy intervals with `hole` cut out of them."""
    out = []
    for s, e in blocks:
        if not _overlap(s, e, hole[0], hole[1]):
            out.append((s, e))
            continue
        if s < hole[0]:
            out.append((s, hole[0]))
        if hole[1] < e:
            out.append((hole[1], e))
    return out


def _emails(attendees, me=()):
    return [a["email"].lower() for a in attendees or []
            if a.get("email") and not a.get("resource") and not a.get("self") and a["email"].lower() not in me]


def _read(call, url, method="GET", body=None):
    data = call(url, method, body)
    if not isinstance(data, dict) or data.get("_http_error"):
        raise GuardError("could not read %s (%s)" % (url.split("?")[0], (data or {}).get("_http_error")
                                                     if isinstance(data, dict) else "no reply"))
    return data


def own_busy(call, cal, t0, t1, skip_id=None, tz="UTC"):
    q = urllib.parse.urlencode({"timeMin": t0.isoformat(), "timeMax": t1.isoformat(),
                                "singleEvents": "true", "orderBy": "startTime", "maxResults": 250})
    data = _read(call, "%s/calendars/%s/events?%s" % (CAL, urllib.parse.quote(cal), q))
    out = []
    for e in data.get("items", []):
        if e.get("status") == "cancelled" or e.get("transparency") == "transparent":
            continue
        if e.get("eventType") in ("workingLocation", "focusTime") and e.get("transparency") != "opaque":
            continue
        if skip_id and (e.get("id") == skip_id or e.get("recurringEventId") == skip_id):
            continue
        me = next((a for a in e.get("attendees", []) if a.get("self")), None)
        if me and me.get("responseStatus") == "declined":
            continue
        s, en = parse_ts(e.get("start"), tz), parse_ts(e.get("end"), tz)
        if s and en:
            out.append({"start": s, "end": en, "summary": e.get("summary") or "(no title)", "id": e.get("id")})
    return out


def others_busy(call, emails, t0, t1, tz):
    """{email: [(start, end), ...]}, or {email: None} when Google does not share it."""
    if not emails:
        return {}
    body = {"timeMin": t0.isoformat(), "timeMax": t1.isoformat(), "timeZone": tz,
            "items": [{"id": e} for e in emails]}
    data = _read(call, "%s/freeBusy" % CAL, "POST", body)
    res = {}
    for e in emails:
        c = (data.get("calendars") or {}).get(e) or {}
        if c.get("errors") or "busy" not in c:
            res[e] = None
        else:
            res[e] = [(parse_ts(b["start"], tz), parse_ts(b["end"], tz)) for b in c["busy"]]
    return res


def _fmt(d, tz):
    return d.astimezone(ZoneInfo(tz)).strftime("%a %Y-%m-%d %H:%M")


def alternatives(blocks, start, dur, tz, now, hours=(WORK_START, WORK_END)):
    """Free slots of length `dur`: working days, inside `hours`, at most PER_DAY a day. Pure."""
    z = ZoneInfo(tz)
    day0 = start.astimezone(z).replace(hour=0, minute=0, second=0, microsecond=0)
    alts = []
    for i in range(SEARCH_DAYS + 3):
        day = (day0 + dt.timedelta(days=i)).astimezone(z)
        if day.weekday() >= 5:
            continue
        t, stop, today = day.replace(hour=hours[0]), day.replace(hour=hours[1]), 0
        while t + dur <= stop and len(alts) < MAX_SUGGESTIONS and today < PER_DAY:
            if t >= now and not any(_overlap(t, t + dur, s, e) for s, e in blocks):
                alts.append({"start": t.isoformat(), "end": (t + dur).isoformat(), "label": _fmt(t, tz)})
                today += 1
                t = t + dur                       # the next suggestion starts after this one
                continue
            t += dt.timedelta(minutes=STEP_MIN)
        if len(alts) >= MAX_SUGGESTIONS:
            break
    return alts


def check(call, cal, start, end, attendees, tz="UTC", skip_id=None, old=None, old_attendees=(), me=(),
          hours=(WORK_START, WORK_END), now=None):
    """{"conflicts": [...], "unknown": [...], "alternatives": [...]} for the slot [start, end)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    dur = end - start
    day0 = start.astimezone(ZoneInfo(tz)).replace(hour=0, minute=0, second=0, microsecond=0)
    win0, win1 = min(start, day0), max(end, day0 + dt.timedelta(days=SEARCH_DAYS + 3))

    mine = own_busy(call, cal, win0, win1, skip_id, tz)
    who = _emails(attendees, set(me) | {cal.lower()})
    theirs = others_busy(call, who, win0, win1, tz)

    def attendee_blocks(email):
        blocks = theirs.get(email) or []
        if old and email in old_attendees:        # their copy of the event being moved
            blocks = _minus(blocks, old)          # free/busy merges adjacent blocks, so cut, not drop
        return blocks

    conflicts = [{"who": "me", "summary": b["summary"], "start": _fmt(b["start"], tz), "end": _fmt(b["end"], tz)}
                 for b in mine if _overlap(start, end, b["start"], b["end"])]
    for email in who:
        for s, e in attendee_blocks(email):
            if _overlap(start, end, s, e):
                conflicts.append({"who": email, "summary": "busy", "start": _fmt(s, tz), "end": _fmt(e, tz)})
    unknown = [e for e in who if theirs.get(e) is None]

    alts = []
    if conflicts:
        blocks = [(b["start"], b["end"]) for b in mine]
        for email in who:
            blocks += attendee_blocks(email)
        alts = alternatives(blocks, start, dur, tz, now, hours)
    return {"conflicts": conflicts, "unknown": unknown, "alternatives": alts}


def guard(call, url, method, body, me=(), default_tz="UTC", now=None):
    """None when the write may go ahead, else the report to print (the write must NOT happen)."""
    t = target(url, method)
    if not t or not isinstance(body, dict):
        return None
    cal, ev = t
    current = {}
    if ev:
        current = call("%s/calendars/%s/events/%s" % (CAL, urllib.parse.quote(cal), ev))
        if not isinstance(current, dict) or current.get("_http_error"):
            current = {}
    merged = dict(current)
    merged.update(body)
    if merged.get("transparency") == "transparent" or merged.get("status") == "cancelled":
        return None
    tz = (merged.get("start") or {}).get("timeZone") or default_tz
    start, end = parse_ts(merged.get("start"), tz), parse_ts(merged.get("end"), tz)
    if not start or not end:
        return None

    old, old_att = None, set()
    if ev and current:
        old = (parse_ts(current.get("start"), tz), parse_ts(current.get("end"), tz))
        old_att = set(_emails(current.get("attendees"), me))
        moved = old != (start, end)
        new_people = set(_emails(merged.get("attendees"), me)) - old_att
        if not moved and not new_people:
            return None

    rep = check(call, cal, start, end, merged.get("attendees"), tz, skip_id=ev, old=old, old_attendees=old_att,
                me=me, now=now)
    if not rep["conflicts"]:
        return None
    out = {"blocked": True,
           "reason": "the requested slot overlaps existing events; nothing was written",
           "requested": {"start": _fmt(start, tz), "end": _fmt(end, tz), "summary": merged.get("summary")}}
    out.update(rep)
    out["next"] = ("show the conflicts and alternatives to the user; once they choose, rerun with the chosen "
                   "slot, or with --force if they accept the overlap")
    return out


def parse_hours(text):
    """"9-19" as (9, 19)."""
    try:
        h0, h1 = (int(x) for x in (text or "").split("-"))
    except ValueError:
        raise ValueError("--hours must look like 9-19")
    if not 0 <= h0 < h1 <= 23:
        raise ValueError("--hours must be two hours of the day, the first before the second")
    return h0, h1


def local_zone(environ=None, readlink=None):
    """This machine's IANA time zone name: $TZ, else the /etc/localtime link, else UTC."""
    import os
    environ = os.environ if environ is None else environ
    name = (environ.get("TZ") or "").lstrip(":").strip()
    if not name:
        try:
            link = (readlink or os.readlink)("/etc/localtime")
            name = link.split("zoneinfo/", 1)[1] if "zoneinfo/" in link else ""
        except OSError:
            name = ""
    try:
        ZoneInfo(name)
        return name
    except Exception:
        return "UTC"
