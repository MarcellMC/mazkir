"""Trip edits, kept as an overlay over the tracker's trip (repair spec §7.4).

The tracker rewrites `rec["trip"]` from live points on every event, so an
edit written into it would be gone at the next point. Edits live in
`rec["edits"]` instead, a list applied in order on top of whatever the
tracker last said, and `trip_of(rec)` is the trip with them applied. Every
reader that plans blocks or draws messages goes through `trip_of`; only the
tracker's own bookkeeping reads `rec["trip"]` directly.

The edit dicts, as stored (times ISO with offset; positions stay on this
machine, like the tracker's own stops):
- `{op: "add_stop", id: "x<n>", start, end, lat, lng, spread_m, from_home_m}`
- `{op: "split_stop", stop_id, at, ids: ["<sid>a", "<sid>b"], centres: [{lat, lng, spread_m, from_home_m}, ×2]}`
  (a centre is None when that half had no points of its own: it keeps the stop's)
- `{op: "merge_stops", stop_ids (in trip order), id: first}`
- `{op: "set_stop_times", stop_id, start?, end?}`
- `{op: "remove_stop", stop_id}`

Applied to the trip as it is now, not as it was: a split cuts the stop's
current span at `at`, so a later LEFT_STOP still moves the second half's end;
a time you set is pinned and wins over the tracker's. An edit whose stop has
gone from under it (the tracker no longer reports it) is skipped.

`name_trip`, `name_stop` and `restore_block` are not overlay edits: the first
two are answers (`pipeline.apply_answer`), the last puts a dismissed block
back to a pending proposal.

`apply_edit`'s result carries no coordinate and no OSM id outside `record`,
and its decision line (`EDIT`) holds the op and stop ids only.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import replace
from typing import Any, Callable
from zoneinfo import ZoneInfo

from src.services.geo import haversine_m
from src.services.location.model import Stop, Trip

EDIT_SOURCE = "agent_edit"
CHANGED_STOP = "That stop changed — see the latest message."
GOOD_ACCURACY_M = 30.0
OVERLAY_OPS = ("add_stop", "split_stop", "merge_stops", "set_stop_times", "remove_stop")
OPS = ("name_trip", "name_stop", *OVERLAY_OPS, "restore_block")

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
        if trip.stop(e["id"]) is None:
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


def known_stop_ids(rec: dict[str, Any]) -> set[str]:
    """Every stop id this trip has ever had: the tracker's, the edits', the answered ones."""
    ids = {s["id"] for s in (rec.get("trip") or {}).get("stops") or []}
    ids |= set(rec.get("stops") or {})
    for e in rec.get("edits") or []:
        if e.get("op") == "add_stop":
            ids.add(e["id"])
        elif e.get("op") == "split_stop":
            ids.update(e.get("ids") or [])
    return ids


def stop_changed(rec: dict[str, Any], stop_id: str) -> bool:
    """A stop this trip had, which an edit has since split, merged away or removed."""
    return stop_id in known_stop_ids(rec) and trip_of(rec).stop(stop_id) is None


# --- applying an edit ---------------------------------------------------------

def apply_edit(trip_id: str, op: str, args: dict[str, Any], deps, *, resolve: Resolve | None = None) -> dict[str, Any]:
    """One edit, made under the trip's lock: validate, record, re-plan, redraw.

    Returns `{"record", "receipt", "conflict"}`; only `record` holds
    positions. Raises KeyError for an unknown trip, stop, block or handle
    ("search again"), ValueError for an edit that cannot be made.
    """
    from src.services.location import pipeline

    if op not in OPS:
        raise ValueError(f"unknown op {op!r}")
    args = dict(args or {})
    # The lock is re-entrant (TripRecords.lock_for), so apply_answer taking it
    # again below, on this thread, does not deadlock.
    with deps.records.lock_for(trip_id):
        rec = deps.records.get(trip_id)
        if rec is None:
            raise KeyError(trip_id)
        trip = trip_of(rec)
        conflict = None
        if op == "name_trip":
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
            rec, conflict, touched = _overlay_edit(rec, trip, op, args, deps, resolve)
        pipeline._log(deps, "EDIT", rec, extra={"op": op, "stop_ids": touched})
        from src.services.location.messages import arrival_receipt

        receipt = arrival_receipt(rec, deps.events, deps.tz)    # records the line order a tap refers to
        deps.records.save(rec)
        return {"record": rec, "receipt": receipt, "conflict": conflict}


def _replan(rec: dict, deps) -> None:
    from src.services.location import pipeline

    pipeline._apply(rec, deps, pipeline._places(deps))
    pipeline._refresh_arrival(rec, deps)
    deps.records.save(rec)


def _overlay_edit(rec: dict, trip: Trip, op: str, args: dict, deps, resolve) -> tuple[dict, str | None, list[str]]:
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
        infos[ids[0]] = {**(infos.get(sid) or _fresh_info()), "source": EDIT_SOURCE}
        infos[ids[1]] = _fresh_info()
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
    from src.services.location.writer import fragments

    dismissed = [f for f in fragments(ref)
                 if (next((e for e in deps.events.get_events(f["date"]) if e.get("id") == f["event_id"]), None)
                     or {}).get("state") == "dismissed"]
    if not dismissed:
        raise ValueError("that block is not dismissed")
    for frag in fragments(ref):
        deps.events.update_event(date=frag["date"], event_id=frag["event_id"], updates={"state": None})
    return [part[5:]] if part.startswith("stop:") else []


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
