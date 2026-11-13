"""Trips become proposed blocks, merged with yours (trips spec §4.2, §4.3, §6.5).

Two steps. `plan_blocks` is pure: from a trip record it says which blocks the
trip should be. `apply_blocks` makes the events store say that, through
`AgentService.run_tool` like the fast lane, so every write lands in the audit
log and approval later goes through the usual path.

The rules that matter most:
- **One rule for every trip.** A named stop is its own block; an unnamed stop
  has none and stays inside whatever block covers it. Which blocks the trip
  itself gets depends only on whether its purpose has a destination — moving
  as the activity (one block) or moving to get somewhere (legs and stops).
  Nothing here names an activity.
- **Never a duplicate, and what you said wins.** A block of yours that is
  the same activity is completed instead of adding one: location fills only
  what you left out, or a time the fast lane merely inferred. A time you
  stated that location disagrees with by more than 15 minutes is reported,
  never overwritten. Your later block absorbs a trip block already written.
- **Your edits stand.** A field you pinned with ✎ is never written again, and
  a block you dismissed or deleted is left alone.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import Any, Callable
from zoneinfo import ZoneInfo

from src.services.approval import resolve_state
from src.services.fast_lane.actions import STATED
from src.services.fast_lane.places import Place, match_place
from src.services.location.guess import _metres
from src.services.location.model import Stop, Trip

logger = logging.getLogger(__name__)

LEG_FOLD_S = 120
MERGE_WINDOW = dt.timedelta(minutes=15)
DISAGREE = dt.timedelta(minutes=15)
MERGE_OVERLAP = 0.5
_MODE_WORDS = {"walk": "Walk", "ride": "Ride", "vehicle": "Drive"}
_HUMAN = ("manual", "photo")


@dataclass(frozen=True)
class BlockSpec:
    part: str
    name: str
    start: dt.datetime
    end: dt.datetime | None
    start_precision: str
    end_precision: str | None
    place_id: str | None = None
    place_text: str | None = None


# --- planning -----------------------------------------------------------------

def _place(name: str | None, stop: Stop | None, places: list[Place]) -> tuple[str | None, str | None, str | None]:
    """(place_id, place_text, display name) for a stop's place."""
    if name:
        known = match_place(name, places)
        return (known.id, None, known.name) if known else (None, name, name)
    if stop is not None and stop.place_id:
        known = next((p for p in places if p.id == stop.place_id), None)
        if known is not None and known.kind != "pause":
            return known.id, None, known.name
    return None, None, None


def _mode(trip: Trip, start: dt.datetime, end: dt.datetime | None) -> str:
    end = end or dt.datetime.max.replace(tzinfo=start.tzinfo)
    overlapping = [leg for leg in trip.legs if leg.mode and leg.start < end and (leg.end or end) > start]
    if not overlapping:
        return "Travel"
    return _MODE_WORDS.get(max(overlapping, key=lambda leg: leg.distance_m).mode, "Travel")


def _stop_spec(stop: Stop, name: str, place: str | None, places: list[Place]) -> BlockSpec:
    place_id, place_text, _ = _place(place, stop, places)
    return BlockSpec(f"stop:{stop.id}", name, stop.start, stop.end, "location",
                     "location" if stop.end else None, place_id, place_text)


def plan_blocks(rec: dict[str, Any], places: list[Place]) -> list[BlockSpec]:
    trip = Trip.from_dict(rec["trip"])
    info = rec.get("stops") or {}
    purpose = rec.get("purpose") or None
    named = [(s, info[s.id]) for s in trip.stops if (info.get(s.id) or {}).get("status") == "named"]
    if purpose and purpose.get("destination"):
        return _travel(trip, purpose, named, places)
    return _activity(trip, purpose, named, places)


def _activity(trip: Trip, purpose: dict | None, named, places: list[Place]) -> list[BlockSpec]:
    if purpose and purpose.get("name"):
        name = purpose["name"]
    else:
        name = "Trip" if trip.back_at is None else f"Trip {_metres(trip.distance_m)}"
    specs = [BlockSpec("trip", name, trip.left_at, trip.back_at, trip.start_precision, trip.end_precision)]
    specs += [_stop_spec(s, i.get("name") or "Stop", i.get("place"), places) for s, i in named]
    return specs


def _travel(trip: Trip, purpose: dict, named, places: list[Place]) -> list[BlockSpec]:
    if not named:
        if not trip.stops:
            place_id, place_text, _ = _place(purpose.get("destination"), None, places)
            return [BlockSpec("trip", purpose["name"], trip.left_at, trip.back_at, trip.start_precision,
                              trip.end_precision, place_id, place_text)]
        # The trip went somewhere, but no stop was named: the longest one is where it went.
        def length(s: Stop) -> float:
            return ((s.end or trip.back_at or s.start) - s.start).total_seconds()
        longest = max(trip.stops, key=length)
        named = [(longest, {"name": purpose["name"], "place": purpose.get("destination")})]

    specs: list[BlockSpec] = []
    prev_end, prev_precision = trip.left_at, trip.start_precision
    n = 0
    for stop, info in named:
        n += 1
        place_id, place_text, shown = _place(info.get("place"), stop, places)
        target = shown or info.get("name") or "stop"
        stop_spec = _stop_spec(stop, info.get("name") or target, info.get("place"), places)
        leg_s = (stop.start - prev_end).total_seconds()
        if leg_s < LEG_FOLD_S:
            stop_spec = BlockSpec(stop_spec.part, stop_spec.name, prev_end, stop_spec.end, prev_precision,
                                  stop_spec.end_precision, stop_spec.place_id, stop_spec.place_text)
        else:
            specs.append(BlockSpec(f"leg:{n}", f"{_mode(trip, prev_end, stop.start)} to {target}",
                                   prev_end, stop.start, prev_precision, "location"))
        specs.append(stop_spec)
        if stop.end is None:
            return specs
        prev_end, prev_precision = stop.end, "location"

    n += 1
    if trip.back_at is not None and (trip.back_at - prev_end).total_seconds() < LEG_FOLD_S:
        last = specs[-1]
        specs[-1] = BlockSpec(last.part, last.name, last.start, trip.back_at, last.start_precision,
                              trip.end_precision, last.place_id, last.place_text)
        return specs
    mode = _mode(trip, prev_end, trip.back_at)
    name = f"{mode} home" if trip.back_at is not None else mode
    specs.append(BlockSpec(f"leg:{n}", name, prev_end, trip.back_at, prev_precision, trip.end_precision))
    return specs


# --- applying -----------------------------------------------------------------

def _local(ts: dt.datetime, zone: ZoneInfo) -> str:
    return ts.astimezone(zone).strftime("%Y-%m-%dT%H:%M:%S")


def _parse(value: str | None, zone: ZoneInfo) -> dt.datetime | None:
    if not value:
        return None
    ts = dt.datetime.fromisoformat(value)
    return ts if ts.tzinfo else ts.replace(tzinfo=zone)


def _interval(start: dt.datetime | None, end: dt.datetime | None) -> tuple[dt.datetime, dt.datetime] | None:
    start = start or end
    if start is None:
        return None
    # An open end counts as a minute: enough to overlap, not enough to swallow a day.
    return start, end if end is not None and end > start else start + dt.timedelta(minutes=1)


def _overlap_ratio(a: tuple[dt.datetime, dt.datetime], b: tuple[dt.datetime, dt.datetime]) -> float:
    overlap = (min(a[1], b[1]) - max(a[0], b[0])).total_seconds()
    longest = max((a[1] - a[0]).total_seconds(), (b[1] - b[0]).total_seconds(), 1.0)
    return max(0.0, overlap) / longest


def _days(specs: list[BlockSpec], rec: dict, zone: ZoneInfo) -> list[str]:
    days = set()
    for s in specs:
        days.add(s.start.astimezone(zone).date().isoformat())
        if s.end is not None:
            days.add(s.end.astimezone(zone).date().isoformat())
    for ref in [*(rec.get("blocks") or {}).values(), *(rec.get("merged") or {}).values()]:
        days.add(ref["date"])
    return sorted(days)


def _user_blocks(events, days: list[str], trip_id: str, owned: set[str], zone: ZoneInfo) -> list[tuple[str, dict]]:
    out = []
    for day in days:
        for e in events.get_events(day):
            trip = e.get("trip") or {}
            if (e.get("id") in owned or e.get("proposed") or e.get("state") == "dismissed"
                    or e.get("source") not in _HUMAN or (trip and trip.get("id") != trip_id)):
                continue
            out.append((day, e))
    return out


def _match(specs: list[BlockSpec], users: list[tuple[str, dict]], zone: ZoneInfo) -> dict[str, tuple[str, dict]]:
    """Each user block to the one spec it most plausibly is; each spec gets at most one."""
    pairs = []
    for s in specs:
        si = _interval(s.start, s.end)
        for day, e in users:
            ui = _interval(_parse(e.get("start_time"), zone), _parse(e.get("end_time"), zone))
            if ui is None:
                continue
            ratio = _overlap_ratio(si, ui)
            near = abs(ui[0] - si[0]) <= MERGE_WINDOW
            if ratio >= MERGE_OVERLAP or near:
                pairs.append((ratio + (1.0 if near else 0.0), s.part, day, e))
    pairs.sort(key=lambda p: -p[0])
    taken_specs, taken_users, out = set(), set(), {}
    for _, part, day, e in pairs:
        if part in taken_specs or e["id"] in taken_users:
            continue
        taken_specs.add(part)
        taken_users.add(e["id"])
        out[part] = (day, e)
    return out


def _find(events, day: str, event_id: str) -> dict | None:
    return next((e for e in events.get_events(day) if e.get("id") == event_id), None)


def _delete_if_pending(events, ref: dict) -> bool:
    """Delete a trip-owned block that is still only a proposal; return whether it is gone."""
    ids = ref.get("fragments") or [ref["event_id"]]
    found = [(d, e) for d in {ref["date"], *(ref.get("fragment_dates") or [])}
             for e in events.get_events(d) if e.get("id") in ids]
    if any(resolve_state(e) != "pending" for _, e in found):
        return False
    for day, e in found:
        events.delete_event(day, e["id"])
    return True


def _trip_field(rec: dict, part: str) -> dict:
    return {"id": rec["id"], "part": part}


def _merge(rec: dict, spec: BlockSpec, day: str, e: dict, previous: dict | None, run_tool, zone) -> dict:
    if previous and previous.get("rejected"):
        return previous                        # you said ✕: location fills nothing here again
    filled = dict((previous or {}).get("filled") or {})
    pinned = e.get("user_set") or {}
    updates: dict[str, Any] = {}
    fields: dict[str, Any] = {"trip": _trip_field(rec, spec.part)}
    disagree = None
    for field, value, key, precision in (("start_time", spec.start, "start_precision", spec.start_precision),
                                         ("end_time", spec.end, "end_precision", spec.end_precision)):
        if value is None:
            continue
        current = _parse(e.get(field), zone)
        stated = current is not None and (e.get(key) is None or e.get(key) in STATED or field in pinned)
        if stated:
            if abs(current - value) > DISAGREE:
                disagree = {"field": field, "location_value": value.astimezone(zone).strftime("%H:%M")}
            continue
        if current is None or current != value:
            filled.setdefault(field, e.get(field))
            updates[field] = _local(value, zone)
            fields[key] = precision or "location"
    if updates or e.get("trip") != fields["trip"]:
        result = run_tool("update_event", {"event_id": e["id"], "date": day, **updates,
                                           "_fast": {"inferred": True, "fields": fields}})
        if not result.get("ok"):
            logger.warning("location writer: completing a block failed: %s", (result.get("error") or {}).get("code"))
    return {"date": day, "event_id": e["id"], "filled": filled, "disagree": disagree}


def _create(rec: dict, spec: BlockSpec, run_tool, zone) -> dict | None:
    fields: dict[str, Any] = {"trip": _trip_field(rec, spec.part), "start_precision": spec.start_precision}
    if spec.end is not None:
        fields["end_precision"] = spec.end_precision or "location"
    if spec.place_id:
        fields["place_id"] = spec.place_id
    if spec.place_text:
        fields["place_text"] = spec.place_text
    params: dict[str, Any] = {"name": spec.name, "date": spec.start.astimezone(zone).date().isoformat(),
                              "start_time": _local(spec.start, zone), "proposed": True,
                              "_fast": {"fields": fields}}
    if spec.end is not None:
        params["end_time"] = _local(spec.end, zone)
    place_name = spec.place_text
    if place_name:
        params["location"] = {"name": place_name}
    result = run_tool("create_event", params)
    if not result.get("ok"):
        logger.warning("location writer: creating a block failed: %s", (result.get("error") or {}).get("code"))
        return None
    data = result.get("data") or {}
    ref = {"date": params["date"], "event_id": data.get("event_id")}
    if data.get("fragments"):
        ref["fragments"] = data["fragments"]
        ref["fragment_dates"] = sorted({params["date"], _local(spec.end, zone)[:10]})
    return ref


def _update_owned(rec: dict, spec: BlockSpec, ref: dict, events, run_tool, zone) -> dict | None:
    """Bring a trip-owned block up to date. Returns the ref to keep, or None to recreate it."""
    if ref.get("gone"):
        return ref
    e = _find(events, ref["date"], ref["event_id"])
    if e is None:
        return {**ref, "gone": True}           # you deleted it: it stays deleted
    if e.get("state") == "dismissed":
        return ref
    crosses = spec.end is not None and spec.start.astimezone(zone).date() != spec.end.astimezone(zone).date()
    if ref.get("fragments") or crosses:
        stored = (_parse(e.get("start_time"), zone), None if ref.get("fragments") else _parse(e.get("end_time"), zone))
        unchanged = ref.get("fragments") and stored[0] == spec.start and ref.get("end") == _local(spec.end, zone)
        if unchanged:
            return ref
        if resolve_state(e) == "pending" and _delete_if_pending(events, ref):
            return None
        return ref
    pinned = e.get("user_set") or {}
    updates: dict[str, Any] = {}
    fields: dict[str, Any] = {}
    if e.get("name") != spec.name and "name" not in pinned:
        updates["name"] = spec.name
    for field, value, key, precision in (("start_time", spec.start, "start_precision", spec.start_precision),
                                         ("end_time", spec.end, "end_precision", spec.end_precision)):
        if field in pinned or value is None:
            continue
        if _parse(e.get(field), zone) != value:
            updates[field] = _local(value, zone)
            fields[key] = precision or "location"
    if updates:
        params = {"event_id": e["id"], "date": ref["date"], **updates, "_fast": {"inferred": True, "fields": fields}}
        result = run_tool("update_event", params)
        if not result.get("ok"):
            logger.warning("location writer: updating a block failed: %s", (result.get("error") or {}).get("code"))
    return ref


def apply_blocks(rec: dict[str, Any], specs: list[BlockSpec], *, run_tool: Callable[[str, dict], dict],
                 events, tz: str) -> dict[str, Any]:
    zone = ZoneInfo(tz)
    blocks: dict[str, dict] = dict(rec.get("blocks") or {})
    previous_merged: dict[str, dict] = dict(rec.get("merged") or {})
    owned = {i for ref in blocks.values() for i in (ref.get("fragments") or [ref["event_id"]])}
    days = _days(specs, rec, zone)
    matches = _match(specs, _user_blocks(events, days, rec["id"], owned, zone), zone)
    by_event = {m["event_id"]: m for m in previous_merged.values()}

    merged: dict[str, dict] = {}
    for spec in specs:
        if spec.part in matches:
            day, e = matches[spec.part]
            if spec.part in blocks and not blocks[spec.part].get("gone"):
                if _delete_if_pending(events, blocks[spec.part]):
                    blocks.pop(spec.part)
            merged[spec.part] = _merge(rec, spec, day, e, by_event.get(e["id"]), run_tool, zone)
            continue
        ref = blocks.get(spec.part)
        if ref is not None:
            kept = _update_owned(rec, spec, ref, events, run_tool, zone)
            if kept is not None:
                blocks[spec.part] = kept
                continue
            blocks.pop(spec.part)
        created = _create(rec, spec, run_tool, zone)
        if created is not None:
            if created.get("fragments") and spec.end is not None:
                created["end"] = _local(spec.end, zone)
            blocks[spec.part] = created

    planned = {s.part for s in specs}
    for part in list(blocks):
        if part not in planned or part in merged:
            ref = blocks[part]
            if ref.get("gone") or _delete_if_pending(events, ref):
                blocks.pop(part)
    rec["blocks"] = blocks
    rec["merged"] = merged
    return rec
