"""What Mazkir says about a trip: a question at a stop, a message when you're back (§6.2, §6.3).

Both are shaped as a fast-lane `Receipt` (packages/shared-types receipt.ts),
so the bot draws them with the renderer it already has. Buttons are
`trip:<trip id>:<line>:<action>`; ✎ reuses the day view's `block:edit:…`.
Callback data carries indexes, never names, so a long answer cannot push a
button past Telegram's 64 bytes.

The trip id is written into the message text ("trip 1a2b3c4d"), because a
Telegram reply carries the text you replied to and never the buttons: that
is how a reply correcting a trip reaches the agent with the right trip.
"""

from __future__ import annotations

import datetime as dt
from typing import Any
from zoneinfo import ZoneInfo

from src.services.approval import resolve_state
from src.services.location.decide import Option
from src.services.location.guess import _duration, _metres
from src.services.location.model import Trip

LABEL_MAX = 32
_GLYPHS = {"approved": "✓", "pending": "●", "dismissed": "✕"}


def _label(text: str) -> str:
    return text if len(text) <= LABEL_MAX else text[: LABEL_MAX - 1] + "…"


def _button(label: str, data: str) -> dict[str, str]:
    return {"label": _label(label), "data": data}


def _line(i: int, glyph: str, when: str, text: str, buttons: list[dict], detail: str | None = None,
          reason: str = "", status: str = "") -> dict[str, Any]:
    return {"id": i, "glyph": glyph, "when": when, "text": text, "detail": detail, "sync": None,
            "reason": reason, "status": status, "buttons": buttons}


def _receipt(trip_id: str, lines: list[dict], open_question: str | None) -> dict[str, Any]:
    plain = []
    for line in lines:
        bits = [line["glyph"], line["when"], line["text"], line["detail"] or "", line["reason"] or ""]
        text = " ".join(b for b in bits if b)
        if text:
            plain.append(text)
    return {"turn_id": trip_id, "lines": lines, "undo": None, "open_question": open_question,
            "text": "\n".join(plain)}


def _hm(ts: dt.datetime | None, zone: ZoneInfo) -> str:
    return ts.astimezone(zone).strftime("%H:%M") if ts else "…"


USUAL_VISITS = 2


def _question_text(trip: Trip, stop_id: str | None, place_name: str | None, now: dt.datetime, zone: ZoneInfo,
                   visits: int = 0, map_label: str | None = None, area: str | None = None) -> str:
    if stop_id is None:
        return f"🚶 Trip {_hm(trip.left_at, zone)}–{_hm(trip.back_at, zone)}, {_metres(trip.distance_m)} — what was it?"
    stop = trip.stop(stop_id)
    far = f"{_metres(stop.from_home_m)} from home" if stop.from_home_m is not None else ""
    if area:
        far = f"{far}, in {area}" if far else f"in {area}"
    if stop.end is not None:
        # Asked at home, about a stop you have left.
        when = f"{_hm(stop.start, zone)}–{_hm(stop.end, zone)}"
        return f"📍 Stop {when}" + (f", {far}" if far else "") + " — what was this?"
    if visits >= USUAL_VISITS:
        where = f"your usual stop ({visits} earlier trips)"
    elif map_label:
        where = f"by {map_label}"
    else:
        where = place_name or "a new place"
    return f"📍 You've been here since {_hm(stop.start, zone)} — " + (f"{far}, " if far else "") + f"{where}. What's this?"


def _option_buttons(trip_id: str, line: str, options: list[Option], pause: bool, later: bool = False) -> list[dict]:
    buttons = [_button(o.name, f"trip:{trip_id}:{line}:a{i}") for i, o in enumerate(options[:3])]
    if pause:
        buttons.append(_button("Just a pause", f"trip:{trip_id}:{line}:p"))
    buttons.append(_button("✎ Something else", f"trip:{trip_id}:{line}:t"))
    if later:
        buttons.append(_button("Later", f"trip:{trip_id}:{line}:l"))
    return buttons


def _tag(trip_id: str, stop_id: str | None) -> str:
    return f" [trip {trip_id} · stop {stop_id}]" if stop_id else f" [trip {trip_id}]"


def question_receipt(rec: dict, stop_id: str | None, options: list[Option], now: dt.datetime, tz: str,
                     place_name: str | None = None, visits: int = 0, map_label: str | None = None,
                     area: str | None = None) -> dict[str, Any]:
    zone = ZoneInfo(tz)
    trip = Trip.from_dict(rec["trip"])
    text = _question_text(trip, stop_id, place_name, now, zone, visits, map_label, area)
    # "Later" puts the question into the arrival message, so it is offered only while you are out.
    later = stop_id is not None and not rec.get("closed")
    line = _line(0, "?", "", text, _option_buttons(rec["id"], stop_id or "trip", options, pause=stop_id is not None,
                                                   later=later),
                 status="question")
    return _receipt(rec["id"], [line], text + _tag(rec["id"], stop_id))


def notice_receipt(text: str) -> dict[str, Any]:
    return {"turn_id": "notice", "lines": [], "undo": None, "open_question": None, "text": text}


def _find(events, day: str, event_id: str) -> dict | None:
    return next((e for e in events.get_events(day) if e.get("id") == event_id), None)


def _merged_reason(m: dict) -> str:
    filled = set(m.get("filled") or {})
    parts = []
    if filled == {"start_time", "end_time"}:
        parts.append("times from location")
    elif "end_time" in filled:
        parts.append("end from location")
    elif "start_time" in filled:
        parts.append("start from location")
    disagree = m.get("disagree")
    if disagree:
        word = "back" if disagree["field"] == "end_time" else "left"
        parts.append(f"location says {word} {disagree['location_value']}")
    return " · ".join(parts)


def arrival_receipt(rec: dict, events, tz: str) -> dict[str, Any]:
    """One line per block of the trip, ✓ ✎ on each still open, ✓ All / ✕ Not right at the end.

    Records the line order in `rec["arrival_lines"]`, which is what a tap's
    line number refers to; the caller saves the record.
    """
    zone = ZoneInfo(tz)
    trip = Trip.from_dict(rec["trip"])
    rows: list[tuple[str, str, dict, dict | None]] = []
    for part, ref in (rec.get("blocks") or {}).items():
        if not ref.get("gone"):
            rows.append((part, "own", ref, None))
    for part, m in (rec.get("merged") or {}).items():
        rows.append((part, "merged", m, m))
    found = []
    for part, kind, ref, m in rows:
        pieces = [_find(events, f["date"], f["event_id"]) for f in (ref.get("fragments") or [ref])]
        pieces = [p for p in pieces if p is not None]
        if not pieces:
            continue
        # A block split at midnight is one line: its first start, its last end,
        # and still open while any piece is.
        e = dict(pieces[0])
        e["end_time"] = pieces[-1].get("end_time")
        states = [resolve_state(p) for p in pieces]
        e["_state"] = "pending" if "pending" in states else states[0]
        found.append((e.get("start_time") or "", part, kind, ref, m, e))
    found.sort(key=lambda r: r[0])

    lines: list[dict] = []
    open_question = None
    for stop in trip.stops:
        info = (rec.get("stops") or {}).get(stop.id) or {}
        if info.get("status") == "later" and not info.get("answered"):
            options = [Option.from_dict(o) for o in info.get("options") or []]
            lines.append(_line(0, "?", "", _question_text(trip, stop.id, None, trip.back_at, zone),
                               _option_buttons(rec["id"], stop.id, options, pause=True), status="question"))
    question = rec.get("trip_question")
    if question and not (rec.get("purpose") or {}).get("name"):
        options = [Option.from_dict(o) for o in question.get("options") or []]
        text = _question_text(trip, None, None, trip.back_at or trip.left_at, zone)
        lines.append(_line(0, "?", "", text, _option_buttons(rec["id"], "trip", options, pause=False),
                           status="question"))
        open_question = text + _tag(rec["id"], None)

    order: list[str] = []
    any_open = False
    for _, part, kind, ref, m, e in found:
        order.append(part)
        n = len(order)
        state = e["_state"]
        confirmed = bool(m and m.get("confirmed"))
        open_ = state == "pending" or (kind == "merged" and not confirmed and bool(m.get("filled") or m.get("disagree")))
        any_open = any_open or open_
        when = f"{(e.get('start_time') or '')[11:16] or '…'}–{(e.get('end_time') or '')[11:16] or '…'}"
        detail = None
        if part == "trip":
            end = trip.back_at
            bits = []
            if end is not None:
                bits.append(_duration((end - trip.left_at).total_seconds()))
            bits.append(_metres(trip.distance_m))
            if trip.stops:
                bits.append(f"{len(trip.stops)} stop{'s' if len(trip.stops) != 1 else ''}")
            detail = ", ".join(bits)
        buttons = ([_button("✓", f"trip:{rec['id']}:{n}:ok"), _button("✎", f"block:edit:{ref['date']}:{e['id']}")]
                   if open_ else [])
        lines.append(_line(n, _GLYPHS.get(state, "●"), when, e.get("name") or "", buttons, detail,
                           _merged_reason(m) if m else "", state))

    footer = ([_button("✓ All", f"trip:{rec['id']}:all:ok"), _button("✕ Not right", f"trip:{rec['id']}:all:no")]
              if any_open else [])
    lines.append(_line(len(order) + 1, "", "", "", footer, f"trip {rec['id']}"))
    rec["arrival_lines"] = order
    return _receipt(rec["id"], lines, open_question)
