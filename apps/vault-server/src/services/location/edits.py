"""Trip edits, kept as an overlay over the tracker's trip (repair spec §7.4).

The tracker rewrites `rec["trip"]` from live points on every event, so an
edit written into it would be gone at the next point. Edits live in
`rec["edits"]` instead, a list applied in order on top of whatever the
tracker last said, and `trip_of(rec)` is the trip with them applied. Every
reader that plans blocks or draws messages goes through `trip_of`; only the
tracker's own bookkeeping reads `rec["trip"]` directly.

The edit dicts, as stored (times ISO with offset; positions stay on this
machine, like the tracker's own stops):
- `{op: "add_stop", id: "x<n>", start, end, lat, lng, spread_m, from_home_m, absorbed_by?}`
  (`absorbed_by`: a tracker stop later reported over it took it in, `absorb_added`)
- `{op: "split_stop", stop_id, at, ids: ["<sid>a", "<sid>b"], centres: [{lat, lng, spread_m, from_home_m}, ×2]}`
  (a centre is None when that half had no points of its own: it keeps the stop's)
- `{op: "merge_stops", stop_ids (in trip order), id: first}`
- `{op: "set_stop_times", stop_id, start?, end?}`
- `{op: "remove_stop", stop_id}`
- `{op: "window", start?, end?, origin?}` (`split_trip`: the first record keeps
  what is before `end`, the record split from it what is from `start` on; a
  stop or leg belongs to the side where it starts)
- `{op: "join", other_id, prefix, trip}` (`join_trips`: the other trip as
  `trip_of` showed it, its stop ids prefixed `j`, appended to this one)

Applied to the trip as it is now, not as it was: a split cuts the stop's
current span at `at`, so a later LEFT_STOP still moves the second half's end;
a time you set is pinned and wins over the tracker's. An edit whose stop has
gone from under it (the tracker no longer reports it) is skipped.

A block you approved stays yours: a split hands the stop's block to the
first half, edited in place; a merge extends the first stop's; a stop merged
away or removed has its block cancelled (dismissed, its Google entry
cancelled), never deleted.

`name_trip`, `name_stop` and `restore_block` are not overlay edits: the first
two are answers (`pipeline.apply_answer`), the last puts a dismissed block
back to a pending proposal.

`split_trip` and `join_trips` change which record a trip is. A split makes a
second record (`split_from`; the first gets `split_into` and is closed at
the cut): the stops after the cut, what you said about them and their
blocks go with it, approved ones still approved and edited in place, and the
tracker's later events for the trip go on in it (`pipeline._route`). A join
appends the other trip to the first; the other is kept, marked
`joined_into`, and its blocks are re-planned into the first.

`apply_edit`'s result carries no coordinate and no OSM id outside `record`,
and its decision line (`EDIT`) holds the op and stop ids only.
"""

from __future__ import annotations

import copy
import datetime as dt
from contextlib import ExitStack
from dataclasses import replace
from uuid import uuid4
from typing import Any, Callable
from zoneinfo import ZoneInfo

from src.services.geo import haversine_m
from src.services.location.model import Leg, Stop, Trip

EDIT_SOURCE = "agent_edit"
CHANGED_STOP = "That stop changed — see the latest message."
JOINED_TRIP = "That trip is part of another one now — see the latest message."
GOOD_ACCURACY_M = 30.0
OVERLAY_OPS = ("add_stop", "split_stop", "merge_stops", "set_stop_times", "remove_stop")
TRIP_OPS = ("split_trip", "join_trips")
OPS = ("name_trip", "name_stop", *OVERLAY_OPS, *TRIP_OPS, "restore_block")
SIDES = ("first", "second")

Resolve = Callable[[str], "dict | None"]


def _parse(value: str | None) -> dt.datetime | None:
    return dt.datetime.fromisoformat(value) if value else None


# --- the overlay ----------------------------------------------------------------

def trip_of(rec: dict[str, Any]) -> Trip:
    """The tracker's trip with your edits applied, in order, and the record's id."""
    trip = Trip.from_dict(rec["trip"])
    trip.id = rec["id"]
    for edit in rec.get("edits") or []:
        _overlay(trip, edit)
    trip.stops.sort(key=lambda s: s.start)
    return trip


def _index(trip: Trip, stop_id: str) -> int | None:
    return next((i for i, s in enumerate(trip.stops) if s.id == stop_id), None)


def _with_centre(stop: Stop, stop_id: str, start, end, centre: dict | None) -> Stop:
    if not centre:
        return replace(stop, id=stop_id, start=start, end=end)
    return replace(stop, id=stop_id, start=start, end=end, lat=float(centre["lat"]), lng=float(centre["lng"]),
                   spread_m=float(centre.get("spread_m") or 0.0),
                   from_home_m=centre.get("from_home_m", stop.from_home_m))


def _overlay(trip: Trip, e: dict[str, Any]) -> None:
    op = e.get("op")
    if op == "add_stop":
        if not e.get("absorbed_by") and trip.stop(e["id"]) is None:
            trip.stops.append(Stop(e["id"], _parse(e["start"]), _parse(e["end"]), float(e["lat"]), float(e["lng"]),
                                   float(e.get("spread_m") or 0.0), e.get("from_home_m")))
    elif op == "split_stop":
        i = _index(trip, e["stop_id"])
        if i is None:
            return
        stop, at = trip.stops[i], _parse(e["at"])
        if not (stop.start < at and (stop.end is None or at < stop.end)):
            return                                   # the stop no longer spans the cut: leave it whole
        centres = list(e.get("centres") or []) + [None, None]
        trip.stops[i:i + 1] = [_with_centre(stop, e["ids"][0], stop.start, at, centres[0]),
                               _with_centre(stop, e["ids"][1], at, stop.end, centres[1])]
    elif op == "merge_stops":
        present = [s for s in (trip.stop(i) for i in e["stop_ids"]) if s is not None]
        if len(present) < 2:
            return
        trip.stops = [s for s in trip.stops if s not in present] + [_merged(present, e["id"])]
    elif op == "set_stop_times":
        stop = trip.stop(e["stop_id"])
        if stop is not None:
            if e.get("start"):
                stop.start = _parse(e["start"])
            if e.get("end"):
                stop.end = _parse(e["end"])
    elif op == "remove_stop":
        trip.stops = [s for s in trip.stops if s.id != e["stop_id"]]
    elif op == "window":
        _window(trip, _parse(e.get("start")), _parse(e.get("end")), e.get("origin"))
    elif op == "join":
        _append(trip, Trip.from_dict(e["trip"]))


def _window(trip: Trip, start: dt.datetime | None, end: dt.datetime | None, origin: str | None) -> None:
    """Keep the part of the trip from `start` and before `end`. A stop or leg is on the side where it starts."""
    stops = []
    for s in trip.stops:
        if (start is not None and s.start < start) or (end is not None and s.start >= end):
            continue
        if end is not None and (s.end is None or s.end > end):
            s = replace(s, end=end)
        stops.append(s)
    legs = []
    for leg in trip.legs:
        if (end is not None and leg.start >= end) or (start is not None and leg.end is not None and leg.end <= start):
            continue
        a = max(leg.start, start) if start is not None else leg.start
        b = (min(leg.end, end) if leg.end is not None else end) if end is not None else leg.end
        share = 1.0
        if leg.end is not None and b is not None and leg.end > leg.start:
            share = max(0.0, (b - a).total_seconds()) / (leg.end - leg.start).total_seconds()
        legs.append(Leg(a, b, leg.distance_m * share, leg.mode))
    # The tracker's distance is its legs' sum; this part's is the sum of its
    # own, so a later point never changes the part before a cut.
    trip.distance_m = sum(leg.distance_m for leg in legs)
    trip.stops, trip.legs = stops, legs
    away = [s.from_home_m for s in stops if s.from_home_m is not None]
    if away:
        trip.max_from_home_m = max(away)
    if start is not None:
        trip.left_at, trip.start_precision, trip.origin = start, "location", origin or "stay"
    if end is not None:
        trip.back_at, trip.end_precision = end, "location"


def _append(trip: Trip, other: Trip) -> None:
    """Another trip, after this one, as part of it: its stops, its legs, its way home."""
    trip.stops.extend(other.stops)
    trip.legs.extend(other.legs)
    trip.back_at, trip.end_precision = other.back_at, other.end_precision
    trip.distance_m += other.distance_m
    trip.max_from_home_m = max(trip.max_from_home_m, other.max_from_home_m)


def window_end(rec: dict[str, Any]) -> dt.datetime | None:
    """Where a split cut this record off (its earliest window end); None when it was never split."""
    ends = [_parse(e["end"]) for e in rec.get("edits") or [] if e.get("op") == "window" and e.get("end")]
    return min(ends) if ends else None


def _merged(stops: list[Stop], stop_id: str) -> Stop:
    """One stop from several: the first's place, their whole span, a centre weighted by time."""
    first = stops[0]
    end = None if any(s.end is None for s in stops) else max(s.end for s in stops)
    weights = [max(((s.end or s.start) - s.start).total_seconds(), 60.0) for s in stops]
    total = sum(weights)
    lat = sum(s.lat * w for s, w in zip(stops, weights)) / total
    lng = sum(s.lng * w for s, w in zip(stops, weights)) / total
    spread = max(haversine_m(lat, lng, s.lat, s.lng) + s.spread_m for s in stops)
    return replace(first, id=stop_id, start=min(s.start for s in stops), end=end, lat=lat, lng=lng,
                   spread_m=spread)


def absorb_added(rec: dict[str, Any], deps) -> list[dict[str, Any]]:
    """A stop the tracker now reports over one you added: the tracker's stop takes it in.

    Called after every tracker event has rewritten `rec["trip"]`. Overlap is
    judged on the trip as you edited it (`trip_of`: times you pinned win over
    the tracker's), and only into a tracker stop with no answer of its own.
    The added stop's edit is marked `absorbed_by` (trip_of skips it); what you
    said about it moves to the tracker's stop, and so does its block. A block
    of yours that cannot move (the tracker's stop holds one already) is never
    cancelled by this: the added stop is then left as it is.

    Returns one {stop_ids: [added, tracker], cancelled, calendar_failed} per absorption.
    """
    base_ids = {s["id"] for s in (rec.get("trip") or {}).get("stops") or []}
    view = trip_of(rec)          # tracker stops with your edits: removed, merged-away and split ones are gone
    infos = rec.setdefault("stops", {})
    blocks = rec.get("blocks") or {}
    out = []
    for e in rec.get("edits") or []:
        if e.get("op") != "add_stop" or e.get("absorbed_by"):
            continue
        start, end = _parse(e["start"]), _parse(e["end"])
        over = next((s for s in view.stops
                     if s.id in base_ids and s.id != e["id"] and not _answered(infos.get(s.id))
                     and s.start < end and (s.end is None or s.end > start)), None)
        if over is None:
            continue
        mine, x_part, s_part = infos.get(e["id"]) or {}, f"stop:{e['id']}", f"stop:{over.id}"
        if x_part in blocks and s_part in blocks and _kept(rec, x_part, deps):
            continue
        e["absorbed_by"] = over.id
        sink: dict[str, list[str]] = {"cancelled": [], "calendar_failed": []}
        # An unanswered added stop moves nothing: the tracker's stop is then asked about as usual.
        if _answered(mine):
            infos[over.id] = {**mine, "source": EDIT_SOURCE}
            rekey_block(rec, x_part, s_part, deps)      # a pending one left behind, the re-plan deletes
        out.append({"stop_ids": [e["id"], over.id], **sink})
    return out


def _answered(info: dict | None) -> bool:
    return bool(info and (info.get("answered") or info.get("status") == "named"))


def _kept(rec: dict, part: str, deps) -> bool:
    """Whether the writer would keep this block when it leaves the plan: you approved, ✕'d or corrected it."""
    from src.services.approval import resolve_state
    from src.services.location.writer import fragments

    ref = (rec.get("blocks") or {}).get(part)
    if ref is None or ref.get("gone"):
        return False
    loaded = [e for f in fragments(ref) if (e := _find(deps.events, f)) is not None]
    return bool(loaded) and (any(resolve_state(e) != "pending" for e in loaded) or any(e.get("user_set") for e in loaded))


def known_stop_ids(rec: dict[str, Any]) -> set[str]:
    """Every stop id this trip has ever had: the tracker's, the edits', the answered ones."""
    ids = {s["id"] for s in (rec.get("trip") or {}).get("stops") or []}
    ids |= set(rec.get("stops") or {})
    for e in rec.get("edits") or []:
        if e.get("op") == "add_stop":
            ids.add(e["id"])
        elif e.get("op") == "split_stop":
            ids.update(e.get("ids") or [])
        elif e.get("op") == "join":
            ids.update(s["id"] for s in (e.get("trip") or {}).get("stops") or [])
    return ids


def stop_changed(rec: dict[str, Any], stop_id: str) -> bool:
    """A stop this trip had, which an edit has since split, merged away or removed."""
    return stop_id in known_stop_ids(rec) and trip_of(rec).stop(stop_id) is None


# --- applying an edit ---------------------------------------------------------

def apply_edit(trip_id: str, op: str, args: dict[str, Any], deps, *, resolve: Resolve | None = None) -> dict[str, Any]:
    """One edit, made under the trip's lock: validate, record, re-plan, redraw.

    Returns `{"record", "receipt", "conflict", "cancelled", "calendar_failed"}`;
    only `record` holds positions. `cancelled` names the parts (`stop:s2`) of
    blocks you had approved or corrected whose stop the edit merged away or
    removed: they are stored dismissed, and their Google entry cancelled
    (restorable there); `calendar_failed` the ones Google did not cancel.
    `split_trip` adds `split_into` (the new record's id) and `other_receipt`
    (its arrival message); `join_trips` adds `trip_id` (the trip kept, the
    earlier one, whichever id was passed) and `joined` (the other's id).
    Raises KeyError for an unknown trip, stop, block or handle ("search
    again"), ValueError for an edit that cannot be made.
    """
    from src.services.location import pipeline

    if op not in OPS:
        raise ValueError(f"unknown op {op!r}")
    args = dict(args or {})
    if op == "join_trips":
        return _join_trips(trip_id, args, deps)
    # The lock is re-entrant (TripRecords.lock_for), so apply_answer taking it
    # again below, on this thread, does not deadlock.
    with deps.records.lock_for(trip_id):
        rec = deps.records.get(trip_id)
        if rec is None:
            raise KeyError(trip_id)
        trip = trip_of(rec)
        conflict = None
        cancelled: dict[str, list[str]] = {"cancelled": [], "calendar_failed": []}
        extra: dict[str, Any] = {}
        if rec.get("joined_into"):
            raise ValueError(f"that trip was joined into trip {rec['joined_into']}: edit that one")
        if op == "split_trip":
            rec, touched, extra = _split_trip(rec, trip, args, deps)
        elif op == "name_trip":
            out = pipeline.apply_answer(trip_id, None, _required(args, "name"),
                                        args.get("destination") or args.get("place"), deps)
            rec, conflict, touched = out["record"], out["conflict"], []
        elif op == "name_stop":
            sid = _stop(trip, args, rec)
            place, osm = args.get("place"), None
            if args.get("ref"):
                place, osm = _place_of(_resolve(args["ref"], deps, resolve), place)
            out = pipeline.apply_answer(trip_id, sid, _required(args, "name"), place, deps, osm=osm)
            rec, conflict, touched = out["record"], out["conflict"], [sid]
        elif op == "restore_block":
            touched = _restore(rec, args, deps)
            _replan(rec, deps)
        else:
            rec, conflict, touched = _overlay_edit(rec, trip, op, args, deps, resolve, cancelled)
        pipeline._log(deps, "EDIT", rec, extra={"op": op, "stop_ids": touched,
                                                **{k: v for k, v in extra.items() if k == "split_into"}})
        from src.services.location.messages import arrival_receipt

        receipt = arrival_receipt(rec, deps.events, deps.tz)    # records the line order a tap refers to
        deps.records.save(rec)
        return {"record": rec, "receipt": receipt, "conflict": conflict, **cancelled, **extra}


def _replan(rec: dict, deps) -> None:
    from src.services.location import pipeline

    pipeline._apply(rec, deps, pipeline._places(deps))
    pipeline._refresh_arrival(rec, deps)
    deps.records.save(rec)


def _overlay_edit(rec: dict, trip: Trip, op: str, args: dict, deps, resolve,
                  cancelled: dict[str, list[str]]) -> tuple[dict, str | None, list[str]]:
    from src.services.location import pipeline

    zone = ZoneInfo(deps.tz)
    now = deps.now()
    name = place = osm = None
    infos = rec.setdefault("stops", {})
    if op == "add_stop":
        start, end = _when(_required(args, "start"), trip, zone, now), _when(_required(args, "end"), trip, zone, now)
        if end <= start:
            raise ValueError("the stop must end after it starts")
        _inside(trip, start, end, now, zone)
        for s in trip.stops:
            if s.start < end and (s.end or now) > start:
                raise ValueError(f"that overlaps stop {s.id} — set its times or split it instead")
        if args.get("ref"):
            resolved = _resolve(args["ref"], deps, resolve)
            centre = {"lat": float(resolved["lat"]), "lng": float(resolved["lng"]),
                      "spread_m": float(resolved.get("accuracy_m") or 0.0)}
            place, osm = _place_of(resolved, args.get("place"))
            name = args.get("name") or (place if resolved.get("label") else None)
        else:
            centre = _centre(deps, start, end, zone)
            if centre is None:
                raise ValueError("no location points then — say where it was")
            place, name = args.get("place"), args.get("name")
        sid = _new_id(rec, "x")
        edit = {"op": op, "id": sid, "start": start.isoformat(), "end": end.isoformat(),
                **centre, "from_home_m": _from_home(deps, centre)}
        infos[sid] = _fresh_info()
        touched = [sid]
    elif op == "split_stop":
        sid = _stop(trip, args, rec)
        stop = trip.stop(sid)
        at = _when(_required(args, "at"), trip, zone, now)
        if not (stop.start < at < (stop.end or now)):
            raise ValueError(f"{hm(at, zone)} is not inside stop {sid} "
                             f"({hm(stop.start, zone)}–{hm(stop.end, zone) if stop.end else 'now'})")
        ids = [f"{sid}a", f"{sid}b"]
        if ids[0] in known_stop_ids(rec) or ids[1] in known_stop_ids(rec):
            raise ValueError(f"stop {sid} was split before")
        centres = []
        for a, b in ((stop.start, at), (at, stop.end or now)):
            c = _centre(deps, a, b, zone)
            centres.append({**c, "from_home_m": _from_home(deps, c)} if c else None)
        edit = {"op": op, "stop_id": sid, "at": at.isoformat(), "ids": ids, "centres": centres}
        # The first half keeps what you said about the stop; the second is asked about.
        first = {**(infos.get(sid) or _fresh_info()), "source": EDIT_SOURCE}
        if first.get("status") == "asked":
            first["status"] = "later"      # its live question is withdrawn below: ask at home
        infos[ids[0]] = first
        infos[ids[1]] = _fresh_info()
        # The stop's block is the first half's now, edited in place: one you
        # approved stays approved (spec §7.4), and only the second half is new.
        rekey_block(rec, f"stop:{sid}", f"stop:{ids[0]}", deps)
        touched = [sid, *ids]
    elif op == "merge_stops":
        wanted = args.get("stop_ids") or []
        if len(set(wanted)) < 2:
            raise ValueError("merging takes two or more stops")
        for sid in wanted:
            _stop(trip, {"stop_id": sid}, rec)
        positions = sorted(_index(trip, sid) for sid in set(wanted))
        if positions != list(range(positions[0], positions[0] + len(positions))):
            raise ValueError("only stops next to each other can be merged")
        ordered = [trip.stops[i].id for i in positions]
        edit = {"op": op, "stop_ids": ordered, "id": ordered[0]}
        infos[ordered[0]] = {**(infos.get(ordered[0]) or _fresh_info()), "source": EDIT_SOURCE}
        touched = ordered
    elif op == "set_stop_times":
        sid = _stop(trip, args, rec)
        stop = trip.stop(sid)
        if not args.get("start") and not args.get("end"):
            raise ValueError("give a start, an end, or both")
        start = _when(args["start"], trip, zone, now) if args.get("start") else stop.start
        end = _when(args["end"], trip, zone, now) if args.get("end") else stop.end
        if end is not None and end <= start:
            raise ValueError("the stop must end after it starts")
        _inside(trip, start, end or start, now, zone)
        i = _index(trip, sid)
        before = trip.stops[i - 1] if i > 0 else None
        after = trip.stops[i + 1] if i + 1 < len(trip.stops) else None
        if before is not None and before.end is not None and start < before.end:
            raise ValueError(f"that starts inside stop {before.id}")
        if after is not None and (end is None or end > after.start):
            raise ValueError(f"that runs into stop {after.id}")
        edit = {"op": op, "stop_id": sid,
                **({"start": start.isoformat()} if args.get("start") else {}),
                **({"end": end.isoformat()} if args.get("end") else {})}
        infos.setdefault(sid, _fresh_info())["source"] = EDIT_SOURCE
        touched = [sid]
    else:                                                   # remove_stop
        sid = _stop(trip, args, rec)
        edit = {"op": op, "stop_id": sid}
        infos.setdefault(sid, _fresh_info())["source"] = EDIT_SOURCE
        touched = [sid]

    rec.setdefault("edits", []).append(edit)
    # A question still waiting about a stop that is no longer one is taken back.
    current = {s.id for s in trip_of(rec).stops}
    for gone in [s for s in touched if s not in current]:
        deps.outbox.withdraw(pipeline.question_key(rec["id"], gone))
        if op in ("merge_stops", "remove_stop"):
            _cancel_block(rec, f"stop:{gone}", deps, cancelled)
    if op in ("split_stop", "merge_stops", "remove_stop"):
        _follow_legs(rec, edit, deps, cancelled)
    deps.records.save(rec)
    if name:
        out = pipeline.apply_answer(rec["id"], edit["id"], name, place, deps, osm=osm)
        return out["record"], out["conflict"], touched
    _replan(rec, deps)
    return rec, None, touched


def _restore(rec: dict, args: dict, deps) -> list[str]:
    part = _required(args, "part")
    ref = (rec.get("blocks") or {}).get(part)
    if ref is None:
        raise KeyError(part)
    if ref.get("gone"):
        raise ValueError("that block was deleted, not dismissed")
    from src.services.location import pipeline
    from src.services.location.writer import fragments, plan_blocks

    if part not in {s.part for s in plan_blocks(rec, pipeline._places(deps))}:
        # Its stop was merged away or removed: made pending, the re-plan would delete it at once.
        raise ValueError("that block's stop is no longer part of the trip")

    dismissed = [f for f in fragments(ref)
                 if (next((e for e in deps.events.get_events(f["date"]) if e.get("id") == f["event_id"]), None)
                     or {}).get("state") == "dismissed"]
    if not dismissed:
        raise ValueError("that block is not dismissed")
    for frag in fragments(ref):
        deps.events.update_event(date=frag["date"], event_id=frag["event_id"], updates={"state": None})
    return [part[5:]] if part.startswith("stop:") else []


def _find(events, frag: dict) -> dict | None:
    return next((e for e in events.get_events(frag["date"]) if e.get("id") == frag["event_id"]), None)


def rekey_block(rec: dict, old: str, new: str, deps) -> bool:
    """Hand the block planned as `old` to the part `new`, the store's `trip` field included."""
    from src.services.location.writer import fragments

    blocks = rec.get("blocks") or {}
    if old not in blocks or new in blocks:
        return False
    blocks[new] = blocks.pop(old)
    if not blocks[new].get("gone"):
        for frag in fragments(blocks[new]):
            e = _find(deps.events, frag)
            if e is not None and (e.get("trip") or {}).get("part") == old:
                deps.events.update_event(date=frag["date"], event_id=frag["event_id"],
                                         updates={"trip": {"id": rec["id"], "part": new}})
    return True


def _leg_ends(part: str) -> tuple[str, str] | None:
    """`leg:<from>-<to>` as (from, to); None for anything else (an old positional `leg:<n>`)."""
    if not part.startswith("leg:") or "-" not in part:
        return None
    a, b = part[4:].split("-", 1)
    return a, b


def _follow_legs(rec: dict, edit: dict, deps, cancelled: dict[str, list[str]]) -> None:
    """Legs you approved follow the stops they join (spec §7.4: legs keyed by what they join).

    Legs are keyed by their two ends, so a split, merge or remove leaves an
    approved leg under a key the new plan no longer has: drawn beside the new
    pending leg that replaces it. Before re-planning, each such leg is handed
    to the planned leg it now is, edited in place there and still approved;
    a leg with nothing left to be (it led out of a removed stop, or ran
    inside a merged span) is cancelled, reversibly. Pending legs need
    nothing: the writer replaces them.
      split s:  x→s becomes x→sa;  s→y becomes sb→y (else the planned leg into y)
      merge:    legs inside the span go; s_last→y becomes s_first→y; x→s_i becomes x→s_first
      remove s: x→s becomes the joined leg out of x;  s→y goes
    """
    from src.services.location import pipeline
    from src.services.location.writer import _delete_if_pending, plan_blocks

    blocks = rec.get("blocks") or {}
    planned = [s.part for s in plan_blocks(rec, pipeline._places(deps)) if _leg_ends(s.part)]
    op = edit["op"]
    if op == "split_stop":
        sid, (first, second) = edit["stop_id"], edit["ids"]
        as_from, as_to, inside = {sid: second}, {sid: first}, set()
    elif op == "merge_stops":
        ids, keep = edit["stop_ids"], edit["id"]
        as_from = {i: keep for i in ids}
        as_to = {i: keep for i in ids}
        inside = set(ids)
    else:
        sid = edit["stop_id"]
        as_from, as_to, inside = {sid: None}, {sid: None}, set()

    for part in [p for p in list(blocks) if _leg_ends(p) and p not in planned]:
        if not _kept(rec, part, deps) or blocks[part].get("cancelled"):
            continue
        a, b = _leg_ends(part)
        if a in inside and b in inside:
            _cancel_block(rec, part, deps, cancelled)
            continue
        a2, b2 = as_from.get(a, a), as_to.get(b, b)
        if a2 is None:                                    # it led out of a stop that is gone
            _cancel_block(rec, part, deps, cancelled)
            continue
        candidates = [f"leg:{a2}-{b2}"] if b2 is not None else []
        candidates += [p for p in planned if b2 is not None and _leg_ends(p)[1] == b2]
        candidates += [p for p in planned if _leg_ends(p)[0] == a2]
        target = next((p for p in candidates if p in planned and _free(rec, p, deps, _delete_if_pending)), None)
        if target is None or not rekey_block(rec, part, target, deps):
            _cancel_block(rec, part, deps, cancelled)


def _free(rec: dict, part: str, deps, delete_if_pending, carry: list[dict] | None = None) -> bool:
    """A planned part nothing holds, or held only by a pending guess, which goes to make room.

    The guess's photos go into `carry` when given, for the block that takes its place.
    """
    blocks = rec.get("blocks") or {}
    ref = blocks.get(part)
    if ref is None:
        return True
    if _kept(rec, part, deps):
        return False
    photos = None if ref.get("gone") else delete_if_pending(deps.events, ref)
    if ref.get("gone") or photos is not None:
        blocks.pop(part)
        if carry is not None and photos:
            carry.extend(photos)
        return True
    return False


def _cancel_block(rec: dict, part: str, deps, cancelled: dict[str, list[str]]) -> None:
    """A block whose stop is gone, which the writer would keep (approved or corrected): cancel it, reversibly.

    Still only Mazkir's guess, the re-plan deletes it as usual. Otherwise it
    is never deleted: it is stored dismissed, and its Google entry, when it
    has one in Mazkir's calendar, is cancelled there (as `POST
    /events/{date}/{id}/cancel` does), where it can be restored.
    """
    from src.services.approval import resolve_state
    from src.services.async_bridge import maybe_await
    from src.services.location.writer import fragments

    ref = (rec.get("blocks") or {}).get(part)
    if ref is None or ref.get("gone") or ref.get("cancelled"):
        return
    loaded = [(f, e) for f in fragments(ref) if (e := _find(deps.events, f)) is not None]
    pinned = any(e.get("user_set") for _, e in loaded)
    states = {resolve_state(e) for _, e in loaded}
    if not loaded or (states == {"pending"} and not pinned):
        return
    if states == {"dismissed"}:
        ref["cancelled"] = True        # you had ✕'d it already: just no longer drawn
        return
    failed = False
    for frag, e in loaded:
        google = (e.get("source_ids") or {}).get("calendar_id")
        if google and e.get("calendar") in (None, "Mazkir"):
            calendar = getattr(deps, "calendar", None)
            try:
                ok = bool(calendar is not None and maybe_await(calendar.cancel_event(google)))
            except Exception:
                ok = False
            failed = failed or not ok
        deps.events.update_event(date=frag["date"], event_id=frag["event_id"], updates={"state": "dismissed"})
    ref["cancelled"] = True
    cancelled["cancelled"].append(part)
    if failed:
        cancelled["calendar_failed"].append(part)


# --- splitting and joining trips -----------------------------------------------

def _split_trip(rec: dict, trip: Trip, args: dict, deps) -> tuple[dict, list[str], dict[str, Any]]:
    """The trip becomes two at a moment (spec §7.4). Called under the first record's lock.

    The first record keeps its id, its purpose (unless `purpose_to` is
    "second") and everything before the cut, and is closed there. The new
    record starts at the cut with the tracker's same trip under a window;
    the stops from then on, your answers about them and their blocks move
    to it. A block you approved moves as it is and stays approved; the
    `trip` block stays with the first. A split of a record already split
    puts the new one between the two.
    """
    from src.services.location import pipeline
    from src.services.location.messages import arrival_receipt
    from src.services.location.records import new_record

    zone, now = ZoneInfo(deps.tz), deps.now()
    side = args.get("stop_side") or "first"
    purpose_to = args.get("purpose_to") or "first"
    if side not in SIDES or purpose_to not in SIDES:
        raise ValueError('stop_side and purpose_to are "first" or "second"')
    cut, origin = _cut(rec, trip, _required(args, "at"), side, zone, now)
    new_id = uuid4().hex[:8]
    while deps.records.get(new_id) is not None:
        new_id = uuid4().hex[:8]

    with ExitStack() as held:
        # Locked in trip order (this one is held already): the order
        # `pipeline._route` takes them in, so neither can wait on the other.
        held.enter_context(deps.records.lock_for(new_id))
        after_id = rec.get("split_into")
        after = None
        if after_id:
            held.enter_context(deps.records.lock_for(after_id))
            after = deps.records.get(after_id)
        second = new_record(Trip.from_dict(rec["trip"]))
        second.update(id=new_id, closed=bool(rec.get("closed")), split_from=rec["id"],
                      last_event_ts=rec.get("last_event_ts"),
                      edits=copy.deepcopy(rec.get("edits") or [])
                      + [{"op": "window", "start": cut.isoformat(), **({"origin": origin} if origin else {})}])
        if after is not None:
            second["split_into"] = after_id
            after["split_from"] = new_id
            deps.records.save(after)
        rec.setdefault("edits", []).append({"op": "window", "end": cut.isoformat()})
        rec["split_into"] = new_id
        rec["closed"] = True

        moved = [s.id for s in trip_of(second).stops]
        infos = rec.setdefault("stops", {})
        for sid in moved:
            deps.outbox.withdraw(pipeline.question_key(rec["id"], sid))
            info = infos.pop(sid, None)
            if info is not None:
                if info.get("status") == "asked" and not info.get("answered"):
                    info["status"] = "later"       # its question was the first record's: asked again from here
                second["stops"][sid] = info
        if purpose_to == "second":
            second["purpose"], second["confirmed"] = rec.get("purpose"), bool(rec.get("confirmed"))
            second["trip_question"] = rec.get("trip_question")
            rec["purpose"], rec["confirmed"], rec["trip_question"] = None, False, None
        _move_blocks(rec, second, cut, deps, zone)
        deps.records.save(rec)
        deps.records.save(second)
        _settle(second, deps, "SPLIT")
        pipeline._log(deps, "EDIT", second, extra={"op": "split_trip", "stop_ids": moved, "split_from": rec["id"]})
        other_receipt = arrival_receipt(second, deps.events, deps.tz)
        deps.records.save(second)
    _settle(rec, deps, "SPLIT")
    return rec, moved, {"split_into": new_id, "other_receipt": other_receipt}


def _cut(rec: dict, trip: Trip, at: str, side: str, zone: ZoneInfo, now: dt.datetime) -> tuple[dt.datetime, str | None]:
    """The moment to cut at, on a stop's edge, and where the second trip leaves from (a place id or None).

    A stop id cuts at its end (the stop stays in the first) or, for the
    second, at its start. A time inside a stop goes to that stop's edge the
    same way, so a stop is never in both trips.
    """
    text = str(at).strip()
    stop = None
    if ":" not in text:
        stop = trip.stop(_stop(trip, {"stop_id": text}, rec))
    else:
        cut = _when(text, trip, zone, now)
        stop = next((s for s in trip.stops if s.start < cut and (s.end is None or cut < s.end)), None)
    if stop is not None:
        if side == "second":
            cut = stop.start
        elif stop.end is None:
            raise ValueError(f"stop {stop.id} is still going on: split at its start (stop_side second) or earlier")
        else:
            cut = stop.end
    last = trip.back_at or now
    if not (trip.left_at < cut < last):
        raise ValueError(f"{hm(cut, zone)} is not inside the trip ({hm(trip.left_at, zone)}–"
                         f"{hm(trip.back_at, zone) if trip.back_at else 'now'})")
    left_from = stop if stop is not None and side == "first" else None
    return cut, (left_from.place_id if left_from is not None else None)


def _block_start(events, ref: dict, zone: ZoneInfo) -> dt.datetime | None:
    from src.services.location.writer import _parse as parse_local, fragments

    if ref.get("gone"):
        return None
    e = _find(events, fragments(ref)[0])
    return parse_local(e.get("start_time"), zone) if e else None


def _restamp(ref: dict, deps, trip_id: str | None, part: str | None) -> None:
    """The store's `trip` field of every piece of a block: {id, part}, or none (the block is yours)."""
    from src.services.location.writer import fragments

    if ref.get("gone"):
        return
    updates: dict[str, Any] = {"trip": {"id": trip_id, "part": part} if trip_id else None}
    if trip_id is None:
        updates["proposed"] = False         # no trip's guess any more: the writer's merge rules see it as yours
    for frag in fragments(ref):
        if _find(deps.events, frag) is not None:
            deps.events.update_event(date=frag["date"], event_id=frag["event_id"], updates=updates)


def _move_blocks(first: dict, second: dict, cut: dt.datetime, deps, zone: ZoneInfo) -> None:
    """Blocks move with their stops: a stop's by its id, a leg by where it starts; `trip` stays.

    Every block moves whatever its state, so one you approved stays approved
    and is edited in place by the second's re-plan. A leg from a stop left in
    the first becomes the second's leg from its start; a leg the first keeps,
    into a stop that moved, becomes its leg home.
    """
    later = {s.id for s in trip_of(second).stops}
    earlier = {s.id for s in trip_of(first).stops}
    blocks, merged = first.setdefault("blocks", {}), first.setdefault("merged", {})

    def on_later_side(part: str, ref: dict) -> bool:
        if part.startswith("stop:"):
            return part[5:] in later
        start = _block_start(deps.events, ref, zone)
        if start is not None:
            return start >= cut
        ends = _leg_ends(part)
        return bool(ends and ends[0] in later)

    for part in [p for p in blocks if p != "trip"]:
        ref = blocks[part]
        ends = _leg_ends(part)
        if not on_later_side(part, ref):
            if ends and ends[1] not in earlier and ends[1] != "home":
                rekey_block(first, part, f"leg:{ends[0]}-home", deps)
            continue
        new = f"leg:start-{ends[1]}" if ends and ends[0] not in later else part
        if new in second["blocks"]:
            new = part
        second["blocks"][new] = blocks.pop(part)
        _restamp(second["blocks"][new], deps, second["id"], new)
    for part in [p for p in merged if p != "trip"]:
        m = merged[part]
        e = _find(deps.events, m)
        start = _block_start(deps.events, m, zone) if e else None
        if part.startswith("stop:") and part[5:] in later or (not part.startswith("stop:") and start and start >= cut):
            second.setdefault("merged", {})[part] = merged.pop(part)
            if e is not None:
                deps.events.update_event(date=m["date"], event_id=m["event_id"],
                                         updates={"trip": {"id": second["id"], "part": part}})


def _settle_legs(rec: dict, deps, places) -> None:
    """A leg you approved that this record no longer plans by its key takes the planned leg it now is.

    Into the same stop first, then out of the same one; only a part that is
    free or held by a pending guess. A leg with nothing to be stays as it is:
    a split or join never cancels a block you approved.
    """
    from src.services.location.writer import _delete_if_pending, plan_blocks

    blocks = rec.get("blocks") or {}
    planned = [s.part for s in plan_blocks(rec, places) if _leg_ends(s.part)]
    for part in [p for p in list(blocks) if _leg_ends(p) and p not in planned]:
        if blocks[part].get("cancelled") or not _kept(rec, part, deps):
            continue
        a, b = _leg_ends(part)
        candidates = [p for p in planned if _leg_ends(p)[1] == b] + [p for p in planned if _leg_ends(p)[0] == a]
        target = next((p for p in candidates if _free(rec, p, deps, _delete_if_pending)), None)
        if target is not None:
            rekey_block(rec, part, target, deps)


def _settle(rec: dict, deps, event: str) -> None:
    """Re-plan a record a split or join changed; a closed one is finished as at home (it asks why)."""
    from src.services.location import pipeline

    places = pipeline._places(deps)
    _settle_legs(rec, deps, places)
    if rec.get("closed"):
        pipeline.close_trip(rec, deps, places, event)
    else:
        pipeline._apply(rec, deps, places)
    pipeline._refresh_arrival(rec, deps)
    deps.records.save(rec)


def _join_trips(trip_id: str, args: dict, deps) -> dict[str, Any]:
    """Two closed trips, one after the other, become one: the earlier keeps its id (spec §7.4).

    The later is appended to it as a `join` edit, its stop ids prefixed
    `j`; its record is kept, marked `joined_into`. Its blocks: one you
    approved (or ✕'d, or corrected) moves to the joined trip's part when
    that is planned there and free, else it loses its `trip` field and is
    yours, for the writer's merge rules; its pending guesses are dropped by
    the re-plan, their photos going to the block that covers them.
    """
    from src.services.location import pipeline
    from src.services.location.messages import arrival_receipt
    from src.services.location.writer import _carry_photos, _delete_if_pending, fragments, plan_blocks

    other_id = _required(args, "other_trip_id")
    if other_id == trip_id:
        raise ValueError("a trip cannot be joined with itself")
    pair = [deps.records.get(trip_id), deps.records.get(other_id)]
    for rec, rid in zip(pair, (trip_id, other_id)):
        if rec is None:
            raise KeyError(rid)
    first_id, second_id = (r["id"] for r in sorted(pair, key=lambda r: trip_of(r).left_at))
    zone = ZoneInfo(deps.tz)
    with deps.records.lock_for(first_id), deps.records.lock_for(second_id):
        first, second = deps.records.get(first_id), deps.records.get(second_id)
        if not first.get("closed") or not second.get("closed"):
            raise ValueError("a trip is still open")
        for r in (first, second):
            if r.get("joined_into"):
                raise ValueError(f"trip {r['id']} was joined into trip {r['joined_into']} already")
        t1, t2 = trip_of(first), trip_of(second)
        if t2.left_at < t1.back_at:
            raise ValueError("those trips overlap")
        if (t2.left_at.astimezone(zone).date() - t1.back_at.astimezone(zone).date()).days > 1:
            raise ValueError("those trips are not on the same day or the next")
        for r in deps.records.all():
            if r["id"] in (first_id, second_id) or r.get("joined_into") or not r.get("trip"):
                continue
            if t1.back_at <= trip_of(r).left_at < t2.left_at:
                raise ValueError(f"trip {r['id']} came between them: those trips are not consecutive")

        known = known_stop_ids(first)
        prefix = "j"
        while any(f"{prefix}{s.id}" in known for s in t2.stops):
            prefix = "j" + prefix
        joined = replace(t2, stops=[replace(s, id=f"{prefix}{s.id}") for s in t2.stops])
        first.setdefault("edits", []).append({"op": "join", "other_id": second_id, "prefix": prefix,
                                              "trip": joined.to_dict()})
        joined_ids = [s.id for s in joined.stops]
        infos = first.setdefault("stops", {})
        for sid, info in (second.get("stops") or {}).items():
            deps.outbox.withdraw(pipeline.question_key(second_id, sid))
            infos[f"{prefix}{sid}"] = {**info, **({"status": "later"} if info.get("status") == "asked"
                                                  and not info.get("answered") else {})}
        if not (first.get("purpose") or {}).get("name") and (second.get("purpose") or {}).get("name"):
            first["purpose"], first["confirmed"] = second["purpose"], bool(second.get("confirmed"))
            first["trip_question"] = None

        planned = {s.part for s in plan_blocks(first, pipeline._places(deps))}
        blocks = first.setdefault("blocks", {})
        for part, ref in (second.get("blocks") or {}).items():
            if ref.get("gone"):
                continue
            if not _kept(second, part, deps):
                # A pending guess: the first's re-plan deletes it and finds its photos a home.
                blocks[f"joined:{second_id}:{part}"] = ref
                continue
            carry: list[dict] = []
            target = next((p for p in _joined_parts(part, prefix, planned)
                           if p in planned and _free(first, p, deps, _delete_if_pending, carry)), None)
            if target is None:
                _restamp(ref, deps, None, None)
                continue
            blocks[target] = ref
            _restamp(ref, deps, first_id, target)
            head = fragments(ref)[0]
            _carry_photos(deps.events, head["date"], head["event_id"], carry)
        merged = first.setdefault("merged", {})
        for part, m in (second.get("merged") or {}).items():
            # Your block the other trip had merged with is yours again, for the joined trip to match;
            # what location filled in it, or your ✕, is kept by event id.
            if _find(deps.events, m) is not None:
                deps.events.update_event(date=m["date"], event_id=m["event_id"], updates={"trip": None})
            merged[f"joined:{second_id}:{part}"] = m
        deps.outbox.remove(second.get("arrival_item"))
        second.update(joined_into=first_id, blocks={}, merged={}, arrival_item=None)
        deps.records.save(second)
        deps.records.save(first)
        _settle(first, deps, "JOIN")
        pipeline._log(deps, "EDIT", first, extra={"op": "join_trips", "stop_ids": joined_ids, "joined": second_id})
        receipt = arrival_receipt(first, deps.events, deps.tz)
        deps.records.save(first)
        return {"record": first, "receipt": receipt, "conflict": None, "cancelled": [], "calendar_failed": [],
                "trip_id": first_id, "joined": second_id}


def _joined_parts(part: str, prefix: str, planned: set[str]) -> list[str]:
    """The parts a block of the joined trip may become in the first: its own, prefixed; for a leg, the
    planned leg into the same stop, then out of it."""
    if part == "trip":
        return ["trip"]
    if part.startswith("stop:"):
        return [f"stop:{prefix}{part[5:]}"]
    ends = _leg_ends(part)
    if ends is None:
        return []
    a = ends[0] if ends[0] == "start" else f"{prefix}{ends[0]}"
    b = ends[1] if ends[1] == "home" else f"{prefix}{ends[1]}"
    legs = [p for p in planned if _leg_ends(p)]
    return ([f"leg:{a}-{b}"] if a != "start" else []) + [p for p in legs if _leg_ends(p)[1] == b] \
        + ([p for p in legs if _leg_ends(p)[0] == a] if a != "start" else [])


# --- helpers ------------------------------------------------------------------

def hm(ts: dt.datetime, zone: ZoneInfo) -> str:
    return ts.astimezone(zone).strftime("%H:%M")


def _required(args: dict, key: str) -> Any:
    value = args.get(key)
    if value in (None, "", []):
        raise ValueError(f"{key} is required")
    return value


def _fresh_info() -> dict[str, Any]:
    # "later": asked about in the arrival message, like a stop nobody answered.
    return {"status": "later", "name": None, "place": None, "options": [], "asked_at": None,
            "source": EDIT_SOURCE}


def _stop(trip: Trip, args: dict, rec: dict) -> str:
    sid = _required(args, "stop_id")
    if trip.stop(sid) is None:
        raise KeyError(f"stop {sid} changed — read the trip again" if stop_changed(rec, sid) else sid)
    return sid


def _new_id(rec: dict, prefix: str) -> str:
    known = known_stop_ids(rec)
    n = 1 + sum(1 for e in rec.get("edits") or [] if e.get("op") == "add_stop")
    while f"{prefix}{n}" in known:
        n += 1
    return f"{prefix}{n}"


def _when(value: str, trip: Trip, zone: ZoneInfo, now: dt.datetime) -> dt.datetime:
    """An ISO time (with or without offset) or a bare HH:MM on the trip's day."""
    text = str(value).strip()
    try:
        if len(text) <= 5 and ":" in text:
            hh, mm = (int(x) for x in text.split(":"))
            day = trip.left_at.astimezone(zone).date()
            ts = dt.datetime.combine(day, dt.time(hh, mm), zone)
            if ts < trip.left_at and ts + dt.timedelta(days=1) <= (trip.back_at or now):
                ts += dt.timedelta(days=1)                 # a trip past midnight
            return ts
        ts = dt.datetime.fromisoformat(text)
    except ValueError:
        raise ValueError(f"not a time: {text!r}") from None
    return ts if ts.tzinfo else ts.replace(tzinfo=zone)


def _inside(trip: Trip, start: dt.datetime, end: dt.datetime, now: dt.datetime, zone: ZoneInfo) -> None:
    last = trip.back_at or now
    if start < trip.left_at or end > last:
        raise ValueError(f"outside the trip ({hm(trip.left_at, zone)}–"
                         f"{hm(trip.back_at, zone) if trip.back_at else 'now'})")


def _resolve(ref: str, deps, resolve: Resolve | None) -> dict[str, Any]:
    """A handle as {kind, label?, osm?, lat, lng, accuracy_m?}; KeyError("search again") when unknown."""
    if ref.startswith("place:"):
        from src.services.fast_lane.places import load_places

        pid = ref[len("place:"):]
        p = next((p for p in load_places(deps.places_path) if p.id == pid and p.lat is not None), None)
        if p is None:
            raise KeyError("search again")
        return {"kind": "place", "label": p.name, "lat": p.lat, "lng": p.lng, "accuracy_m": p.radius_m}
    found = resolve(ref) if resolve is not None else None
    if not found or found.get("lat") is None:
        raise KeyError("search again")
    return found


def _place_of(resolved: dict, place: str | None) -> tuple[str | None, str | None]:
    """(the place to name, its OSM id): a map or user place gives its label; an anchor only a position."""
    label = resolved.get("label") if resolved.get("kind") in ("map", "place") else None
    return place or label, resolved.get("osm") if resolved.get("kind") == "map" else None


def _centre(deps, start: dt.datetime, end: dt.datetime, zone: ZoneInfo) -> dict[str, float] | None:
    """The centre of the raw points between start and end, preferring good ones; None without points."""
    if getattr(deps, "raw_dir", None) is None:
        return None
    from src.services.location.raw import load_fixes

    # load_fixes takes the location root and reads <root>/raw/<date>.jsonl.
    fixes = [f for f in load_fixes(deps.raw_dir.parent, start.astimezone(zone).date(), end.astimezone(zone).date())
             if start <= f.ts <= end]
    good = [f for f in fixes if f.accuracy_m is None or f.accuracy_m <= GOOD_ACCURACY_M] or fixes
    if not good:
        return None
    lat = sum(f.lat for f in good) / len(good)
    lng = sum(f.lng for f in good) / len(good)
    spread = max(haversine_m(lat, lng, f.lat, f.lng) for f in good)
    return {"lat": lat, "lng": lng, "spread_m": round(spread, 1)}


def _from_home(deps, centre: dict | None) -> float | None:
    if not centre:
        return None
    from src.services.fast_lane.places import load_places

    home = next((p for p in load_places(deps.places_path) if p.id == "home" and p.lat is not None), None)
    return round(haversine_m(home.lat, home.lng, centre["lat"], centre["lng"]), 1) if home else None
