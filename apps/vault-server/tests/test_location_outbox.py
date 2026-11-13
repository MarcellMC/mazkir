"""Trips spec §6.1: queued messages, sent only once the bot acknowledges them."""

from src.services.location.outbox import Outbox


def test_outbox_serves_until_acked_then_drops_after_three(tmp_path):
    ob = Outbox(tmp_path / "outbox.json")
    i = ob.add("question", {"text": "q"}, "1a2b3c4d")
    assert [x["id"] for x in ob.serve()] == [i]
    assert ob.ack(i) is True and ob.serve() == []
    ob.add("notice", {"text": "n"}, None)
    ob.serve(); ob.serve(); ob.serve()
    assert ob.serve() == []


def test_serve_shape(tmp_path):
    ob = Outbox(tmp_path / "outbox.json")
    i = ob.add("arrival", {"text": "a"}, "1a2b3c4d")
    assert ob.serve() == [{"id": i, "kind": "arrival", "receipt": {"text": "a"}}]


def test_outbox_survives_a_restart(tmp_path):
    Outbox(tmp_path / "o.json").add("notice", {"text": "n"}, None)
    assert len(Outbox(tmp_path / "o.json").serve()) == 1


def test_find_and_update_an_unacked_item(tmp_path):
    ob = Outbox(tmp_path / "o.json")
    i = ob.add("arrival", {"text": "old"}, "1a2b3c4d")
    assert ob.find("1a2b3c4d", "arrival")["id"] == i
    assert ob.update(i, {"text": "new"}) is True
    assert ob.serve()[0]["receipt"] == {"text": "new"}
    ob.ack(i)
    assert ob.find("1a2b3c4d", "arrival") is None and ob.update(i, {"text": "x"}) is False


def test_ack_of_an_unknown_id(tmp_path):
    assert Outbox(tmp_path / "o.json").ack("deadbeef") is False
