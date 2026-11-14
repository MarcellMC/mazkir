"""Map places at a stop (map spec §5): buttons, the model's choice, the question, answers.

Each test writes a small OSM file around the synthetic walk's stop (700 m north
of a made-up home) and builds an index from it.
"""

from __future__ import annotations

import json
from pathlib import Path
from xml.sax.saxutils import quoteattr

from src.services.fast_lane.places import load_places
from src.services.location import pipeline as pipeline_mod
from src.services.location.map_index import build_index
from src.services.location.pipeline import handle_event
from src.services.location.runtime import LocationRuntime
from src.services.location.tracker import Tracker
from tests.location_fixtures import HOME, Track, at, feed_all, t
from tests.location_pipeline_fixtures import FakeModel, make_deps

M_LAT, M_LNG = 111_195.0, 94_294.0
STOP_N = 700.0


def walk():
    return Track(t(13, 16, 0)).stay(10).walk_to(STOP_N).stay(6).walk_to(0).stay(5)


def run(deps, clock, events):
    for ev in events:
        clock["now"] = ev.ts
        handle_event(ev, deps)
    return deps.records.get("1a2b3c4d")


def events(places=()):
    return feed_all(Tracker(HOME, list(places), new_id=lambda: "1a2b3c4d"), walk().fixes)


def osm_index(tmp_path: Path, nodes=(), rects=()) -> Path:
    """nodes: (north_m, east_m, tags); rects: (north_m, east_m, size_m, tags), centred there."""
    out, nid, ways = ['<?xml version="1.0" encoding="UTF-8"?>', '<osm version="0.6">'], [1000], []

    def node(n, e, tags=None):
        nid[0] += 1
        lat, lng = at(n, e)
        tag_xml = "".join(f"<tag k={quoteattr(k)} v={quoteattr(v)}/>" for k, v in (tags or {}).items())
        out.append(f'<node id="{nid[0]}" version="1" lat="{lat:.8f}" lon="{lng:.8f}">{tag_xml}</node>')
        return nid[0]

    for n, e, tags in nodes:
        node(n, e, tags)
    for i, (n, e, size, tags) in enumerate(rects, 1):
        h = size / 2
        ids = [node(n - h, e - h), node(n + h, e - h), node(n + h, e + h), node(n - h, e + h)]
        ways.append((i, ids + ids[:1], tags))
    for wid, refs, tags in ways:
        body = "".join(f'<nd ref="{r}"/>' for r in refs) + "".join(
            f"<tag k={quoteattr(k)} v={quoteattr(v)}/>" for k, v in tags.items())
        out.append(f'<way id="{wid}" version="1">{body}</way>')
    out.append("</osm>")
    src = tmp_path / "around.osm"
    src.write_text("\n".join(out), encoding="utf-8")
    db = tmp_path / "index.sqlite"
    build_index(src, db)
    return db


DOG_PARK_IN_PARK = dict(rects=[(STOP_N, 0, 90, {"leisure": "park"}), (STOP_N, 0, 30, {"leisure": "dog_park"})],
                        nodes=[(STOP_N + 100, 0, {"place": "neighbourhood", "name": "Neve Sha'anan"})])
BARZILAY = dict(nodes=[(STOP_N + 5, 0, {"amenity": "cafe", "name": "קפה ברזילי"})])


def _deps(tmp_path, model=None, **osm):
    deps, clock = make_deps(tmp_path, model or FakeModel())
    deps.map_index = osm_index(tmp_path, **osm) if osm else None
    return deps, clock


def _asked(deps, clock):
    rec = run(deps, clock, events()[:2])
    return rec, rec["stops"]["s1"]


def test_map_places_become_buttons(tmp_path):
    deps, clock = _deps(tmp_path, **DOG_PARK_IN_PARK)
    rec, info = _asked(deps, clock)
    assert info["status"] == "asked"
    assert [o["name"] for o in info["options"]] == ["Dog park", "Park"]
    assert info["options"][0]["osm"].startswith("w")


def test_one_good_guess_is_offered_alone(tmp_path):
    model = FakeModel({"stop": [{"purpose": "Coffee", "likelihood": "plausible", "history_id": None,
                                 "map_id": "m1", "cites": [], "destination": None}]})
    deps, clock = _deps(tmp_path, model, **BARZILAY)
    _, info = _asked(deps, clock)
    assert [o["name"] for o in info["options"]] == ["Coffee"]


def test_only_the_nearest_map_place_when_none_is_close(tmp_path):
    deps, clock = _deps(tmp_path, nodes=[(STOP_N + 25, 0, {"amenity": "pharmacy", "name": "Super-Pharm"}),
                                          (STOP_N - 28, 0, {"shop": "kiosk"})])
    _, info = _asked(deps, clock)
    assert [o["name"] for o in info["options"]] == ["Super-Pharm"]


def test_a_guess_citing_the_map_keeps_the_place(tmp_path):
    model = FakeModel({"stop": [{"purpose": "Coffee at קפה ברזילי", "likelihood": "strong", "history_id": None,
                                 "map_id": "m1", "cites": [], "destination": None}]})
    deps, clock = _deps(tmp_path, model, **BARZILAY)
    _, info = _asked(deps, clock)
    assert info["options"][0]["name"] == "Coffee at קפה ברזילי"
    assert info["options"][0]["destination"] == "קפה ברזילי"
    assert info["status"] == "asked"                          # never named silently from the map


def test_unknown_map_id_is_dropped(tmp_path):
    logs: list[dict] = []
    model = FakeModel({"stop": [{"purpose": "Gym", "likelihood": "strong", "history_id": None,
                                 "map_id": "m9", "cites": [], "destination": "Gym"}]})
    deps, clock = make_deps(tmp_path, model, logs=logs)
    deps.map_index = osm_index(tmp_path, **BARZILAY)
    _, info = _asked(deps, clock)
    assert [o["name"] for o in info["options"]] == ["קפה ברזילי"]
    stopped = [line for line in logs if line["event"] == "STOPPED"][0]
    assert {"purpose": "Gym", "reason": "unknown map id"} in stopped["dropped"]


def test_question_says_what_is_there(tmp_path):
    deps, clock = _deps(tmp_path, **DOG_PARK_IN_PARK)
    run(deps, clock, events()[:2])
    [q] = deps.outbox.serve()
    text = q["receipt"]["lines"][0]["text"]
    assert "by Dog park" in text and ", in Neve Sha'anan" in text


def test_tapping_a_map_option_saves_the_place_with_its_osm_id(tmp_path):
    deps, clock = _deps(tmp_path, **BARZILAY)
    evs = events()
    run(deps, clock, evs[:2])
    rt = LocationRuntime.__new__(LocationRuntime)
    rt.deps = deps
    rt.tap("1a2b3c4d", "s1", "a0")
    [place] = [p for p in load_places(deps.places_path) if p.name == "קפה ברזילי"]
    assert place.osm and place.osm.startswith("n") and place.lat is not None
    # The next visit is named from your place, silently.
    deps2, clock2 = make_deps(tmp_path / "again")
    deps2.places_path.write_text(deps.places_path.read_text())
    deps2.map_index = deps.map_index
    rec = run(deps2, clock2, events(load_places(deps2.places_path))[:2])
    assert rec["stops"]["s1"]["status"] == "named" and rec["stops"]["s1"]["name"] == "קפה ברזילי"


def test_user_place_wins_and_skips_the_map(tmp_path, monkeypatch):
    deps, clock = _deps(tmp_path, **BARZILAY)
    from src.services.fast_lane.places import learn_place
    lat, lng = at(STOP_N)
    learn_place(deps.places_path, "Café Barzilay", lat, lng, 10)

    def boom(*a, **k):
        raise AssertionError("the map was consulted")
    monkeypatch.setattr(pipeline_mod, "map_near", boom)
    _, info = _asked(deps, clock)
    assert info["status"] == "named" and info["name"] == "Café Barzilay"
    assert deps.claude.calls == []                            # nothing to guess either


def test_no_index_means_todays_behaviour(tmp_path):
    deps, clock = _deps(tmp_path)
    rec, info = _asked(deps, clock)
    assert info["status"] == "asked" and info["options"] == []
    [q] = deps.outbox.serve()
    assert "a new place" in q["receipt"]["lines"][0]["text"]


def test_trip_purpose_still_never_names_a_stop(tmp_path):
    model = FakeModel({"stop": [{"purpose": "Dog walk", "likelihood": "strong", "history_id": None,
                                 "map_id": "m1", "cites": [], "destination": None}]})
    deps, clock = _deps(tmp_path, model, **DOG_PARK_IN_PARK)
    rec = run(deps, clock, events()[:1])
    rec["purpose"] = {"name": "Dog walk", "destination": None, "source": "answer"}
    deps.records.save(rec)
    rec = run(deps, clock, events()[1:2])
    assert "Dog walk" not in [o["name"] for o in rec["stops"]["s1"]["options"]]


def test_hebrew_and_long_map_labels(tmp_path):
    long_name = "בית קפה ומאפייה שכונתית של רחוב ברזילי"
    deps, clock = _deps(tmp_path, nodes=[(STOP_N + 5, 0, {"amenity": "cafe", "name": long_name})])
    run(deps, clock, events()[:2])
    [q] = deps.outbox.serve()
    first = q["receipt"]["lines"][0]["buttons"][0]
    assert first["label"].endswith("…") and len(first["label"]) == 32
    assert first["data"] == "trip:1a2b3c4d:s1:a0"


def test_model_and_log_never_see_coordinates_or_osm_ids(tmp_path):
    logs: list[dict] = []
    model = FakeModel()
    deps, clock = make_deps(tmp_path, model, logs=logs)
    deps.map_index = osm_index(tmp_path, **DOG_PARK_IN_PARK)
    rec = run(deps, clock, events())
    lat = f"{rec['trip']['stops'][0]['lat']:.4f}"
    content = "\n".join(c["content"] for c in model.calls)
    assert "MAP:" in content and "Dog park" in content
    assert lat not in content and lat not in json.dumps(logs, ensure_ascii=False)
    osm_ids = [m["osm"] for m in rec["stops"]["s1"]["map"]]
    assert osm_ids and not any(o in content for o in osm_ids)
    stopped = [line for line in logs if line["event"] == "STOPPED"][0]
    assert stopped["map"][0]["label"] == "Dog park"
