"""Score the trips tracker and history against the labels (trips spec §9). Offline and free by default.

    python scripts/location_replay.py --from 2026-11-05 --to 2026-11-10
    python scripts/location_replay.py --from 2026-11-05 --to 2026-11-10 --with-model --confirm-cost

Replays the raw points through the tracker, matches trips to the labels in
data/eval/location/, and prints the §9 measures:
- trips found, missed and invented;
- how long leaving took to detect;
- start/end error;
- whether history alone names every dog walk (each day scored against the
  other days' labels, so a day never predicts itself);
- how many questions a day that would mean.

--with-model also makes the real guess for each trip (about $0.007 a call), and
refuses to run without --confirm-cost.

--map prints, for every stop, the top 3 places the local map copy shows there
and the area name (map spec §8.3). Offline; labels only, never coordinates.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # apps/vault-server

STRONG_SCORE = 0.75
RUNNER_UP_MAX = 0.5
COST_PER_CALL = 0.007


def _ts(value: str | None) -> dt.datetime | None:
    return dt.datetime.fromisoformat(value) if value else None


def _span(start: dt.datetime, end: dt.datetime | None) -> tuple[dt.datetime, dt.datetime]:
    return start, end if end and end > start else start + dt.timedelta(minutes=1)


def match_trips(trips: list[dict], labels: list[dict]) -> list[tuple[dict | None, dict | None]]:
    """(trip, label) pairs: each label to the trip overlapping it most; trips no label overlaps are (trip, None)."""
    pairs: list[tuple[dict | None, dict | None]] = []
    used: set[int] = set()
    for lab in labels:
        ls, le = _span(_ts(lab["start"]), _ts(lab.get("end")))
        best, best_overlap = None, 0.0
        for i, trip in enumerate(trips):
            ts, te = _span(_ts(trip["left_at"]), _ts(trip.get("back_at")) or ls + dt.timedelta(hours=12))
            overlap = (min(le, te) - max(ls, ts)).total_seconds()
            if overlap > best_overlap:
                best, best_overlap = i, overlap
        if best is None:
            pairs.append((None, lab))
        else:
            used.add(best)
            pairs.append((trips[best], lab))
    pairs.extend((trip, None) for i, trip in enumerate(trips) if i not in used)
    return pairs


def _p(values: list[float], pct: int) -> float | None:
    if not values:
        return None
    values = sorted(values)
    return round(values[min(len(values) - 1, int(pct / 100 * len(values)))], 1)


def measures(pairs: list[tuple[dict | None, dict | None]]) -> dict:
    found = sum(1 for trip, lab in pairs if trip is not None and lab is not None)
    missed = sum(1 for trip, lab in pairs if trip is None)
    invented = sum(1 for trip, lab in pairs if lab is None)
    by_trip: dict[int, list[dict]] = {}
    trips: dict[int, dict] = {}
    for trip, lab in pairs:
        if trip is not None and lab is not None:
            by_trip.setdefault(id(trip), []).append(lab)
            trips[id(trip)] = trip
    leaving, start_err, end_err = [], [], []
    for key, labs in by_trip.items():
        trip = trips[key]
        labs = sorted(labs, key=lambda lab: lab["start"])
        first, last = labs[0], labs[-1]
        left = _ts(trip["left_at"])
        true_start = _ts(first["start"])
        if trip.get("detected_at"):
            leaving.append((_ts(trip["detected_at"]) - true_start).total_seconds() / 60)
        start_err.append(abs((left - true_start).total_seconds()) / 60)
        if trip.get("back_at") and last.get("end"):
            end_err.append(abs((_ts(trip["back_at"]) - _ts(last["end"])).total_seconds()) / 60)
    return {"found": found, "missed": missed, "invented": invented,
            "leaving_p50_min": _p(leaving, 50), "start_err_p50_min": _p(start_err, 50),
            "start_err_p90_min": _p(start_err, 90), "end_err_p50_min": _p(end_err, 50),
            "end_err_p90_min": _p(end_err, 90)}


def _run_tracker(first: dt.date, last: dt.date, tz: str):
    from src.config import settings
    from src.services.fast_lane.places import load_places
    from src.services.location.home import find_home
    from src.services.location.raw import load_fixes
    from src.services.location.tracker import Tracker

    fixes = load_fixes(settings.location_data_path, first, last)
    all_places = load_places(settings.events_data_path.parent / "places.json")
    home = next(((p.lat, p.lng) for p in all_places if p.id == "home" and p.lat is not None), None)
    if home is None:
        # Learn it as the runtime would, from every raw day there is, not only the scored range.
        today = dt.date.today()
        wide = load_fixes(settings.location_data_path, first - dt.timedelta(days=14), today)
        home = find_home(wide, tz, today, days=(today - first).days + 14)
    places = [p for p in all_places if p.id != "home"]
    counter = iter(range(1, 1 << 32))
    tracker = Tracker(home, places, new_id=lambda: f"{next(counter):08x}")
    detected: dict[str, dt.datetime] = {}
    closed = []
    for f in fixes:
        for e in tracker.feed(f):
            if e.kind == "LEFT":
                detected[e.trip.id] = e.ts
            if e.kind == "BACK_HOME":
                closed.append(e.trip)
    if fixes:
        closed += [e.trip for e in tracker.tick(fixes[-1].ts + dt.timedelta(seconds=61)) if e.kind == "BACK_HOME"]
    if tracker.trip is not None:
        closed.append(tracker.trip)
    return closed, detected


def map_lines(trips, index: Path | None, tz: str) -> list[str]:
    """One line per stop: when, which stop, the top 3 map labels, the area. No coordinates."""
    from src.services.location.map_lookup import map_area, map_near

    zone = ZoneInfo(tz)
    out = []
    for trip in trips:
        for stop in trip.stops:
            labels = [m.label for m in map_near(index, stop.lat, stop.lng, stop.spread_m)[:3]]
            area = map_area(index, stop.lat, stop.lng)
            out.append(f"    {stop.start.astimezone(zone):%m-%d %H:%M}  stop {stop.id}  "
                       f"map: {' · '.join(labels) or '-'}  area: {area or '-'}")
    return out


def _labels(eval_dir: Path, first: dt.date, last: dt.date) -> list[dict]:
    rows = []
    for path in sorted(eval_dir.glob("*.json")):
        day = dt.date.fromisoformat(path.stem) if path.stem[:4].isdigit() else None
        if day is None or not first <= day <= last:
            continue
        rows.extend(r for r in json.loads(path.read_text(encoding="utf-8")).get("trips", []) if not r.get("not_a_trip"))
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="start", required=True)
    ap.add_argument("--to", dest="end", required=True)
    ap.add_argument("--with-model", action="store_true")
    ap.add_argument("--confirm-cost", action="store_true")
    ap.add_argument("--map", action="store_true", help="print the map places at every stop")
    args = ap.parse_args()

    from src.config import settings
    from src.services.location.history import ConfirmedTrip, score_history

    tz = settings.vault_timezone
    zone = ZoneInfo(tz)
    first, last = dt.date.fromisoformat(args.start), dt.date.fromisoformat(args.end)
    trips, detected = _run_tracker(first, last, tz)
    labels = _labels(settings.events_data_path.parent / "eval" / "location", first, last)
    trip_dicts = [{**t.to_dict(), "detected_at": detected.get(t.id).isoformat() if detected.get(t.id) else None}
                  for t in trips]
    pairs = match_trips(trip_dicts, labels)
    m = measures(pairs)

    print(f"trips {len(trips)}, labels {len(labels)}")
    print(f"found {m['found']}  missed {m['missed']}  invented {m['invented']}")
    for trip, lab in pairs:
        if trip is None:
            print(f"    MISSED    {lab['start'][:16]}  {lab['purpose']}")
        elif lab is None:
            print(f"    INVENTED  {_ts(trip['left_at']).astimezone(zone):%m-%d %H:%M}  "
                  f"up to {trip['max_from_home_m']:.0f} m")
    print(f"leaving detected after (p50)  {m['leaving_p50_min']} min")
    print(f"start error p50/p90  {m['start_err_p50_min']} / {m['start_err_p90_min']} min")
    print(f"end error   p50/p90  {m['end_err_p50_min']} / {m['end_err_p90_min']} min")

    # History, leave-one-day-out.
    def confirmed_except(day: str) -> list[ConfirmedTrip]:
        out = []
        for lab in labels:
            f = lab.get("features")
            if not f or lab["start"][:10] == day:
                continue
            start = _ts(lab["start"])
            end = _ts(lab.get("end")) or start
            out.append(ConfirmedTrip(lab["purpose"], lab.get("destination"), start, (end - start).total_seconds(),
                                     f.get("origin") or "home", f.get("mode"), f.get("distance_m") or 0,
                                     f.get("max_from_home_m") or 0))
        return out

    by_id = {t.id: t for t in trips}
    named, walks = 0, 0
    questions: Counter[str] = Counter()
    for trip, lab in pairs:
        if trip is None:
            continue
        tr = by_id[trip["id"]]
        day = tr.left_at.astimezone(zone).date().isoformat()
        ranked = score_history(tr, confirmed_except(day), tr.back_at or tr.left_at, tz)
        top = ranked[0] if ranked else None
        runner = ranked[1].score if len(ranked) > 1 else 0.0
        strong = top is not None and top.score >= STRONG_SCORE and runner < RUNNER_UP_MAX
        if lab is not None and lab["purpose"] == "Dog walk":
            walks += 1
            ok = strong and top.purpose == "Dog walk"
            named += ok
            if not ok:
                print(f"    walk not named  {day} {tr.left_at.astimezone(zone):%H:%M}  "
                      f"top={top.purpose if top else None} {top.score if top else ''}")
        questions[day] += len(tr.stops) + (0 if strong else 1)
    print(f"dog walks named from history  {named} / {walks}")
    print("questions a day (stops + unnamed trips, before the cap of 6):  "
          + ", ".join(f"{d[5:]} {n}" for d, n in sorted(questions.items())))

    if args.map:
        from src.services.location.map_update import index_path

        print("map places at each stop:")
        print("\n".join(map_lines(trips, index_path(settings.location_map_path), tz)) or "    (no stops)")

    if args.with_model:
        calls = sum(len(by_id[t["id"]].stops) + 1 for t, _ in pairs if t is not None)
        if not args.confirm_cost:
            raise SystemExit(f"--with-model makes about {calls} calls (≈ ${calls * COST_PER_CALL:.2f}); "
                             "add --confirm-cost to run them")
        from src.services.claude_service import ClaudeService
        from src.services.location.guess import describe_trip, guess

        claude = ClaudeService(api_key=settings.anthropic_api_key)
        for trip, lab in pairs:
            if trip is None:
                continue
            tr = by_id[trip["id"]]
            day = tr.left_at.astimezone(zone).date().isoformat()
            history = score_history(tr, confirmed_except(day), tr.back_at or tr.left_at, tz)
            kept, _ = guess("trip", describe_trip(tr, None, [], tr.back_at or tr.left_at, tz), history, [], claude,
                            model=settings.location_guess_model, timeout_s=settings.location_guess_timeout_s)
            print(f"    {day} {tr.left_at.astimezone(zone):%H:%M}  label={lab['purpose'] if lab else '-'}  "
                  f"model={[(g.purpose, g.likelihood) for g in kept]}")


if __name__ == "__main__":
    main()
