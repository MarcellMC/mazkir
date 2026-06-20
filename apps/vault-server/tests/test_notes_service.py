"""Tests for NotesService."""
import pytest
from src.services.notes_service import derive_kind, derive_sort_key


class TestDerive:
    def test_daily_kind_and_sort_key(self):
        assert derive_kind("2026-05-21") == "daily"
        assert derive_sort_key("2026-05-21") == "2026-05-21"

    def test_weekly_kind(self):
        assert derive_kind("2022-W34") == "weekly"

    def test_weekly_sort_key_is_last_day_of_iso_week(self):
        # ISO week 34 of 2022: Monday 2022-08-22 .. Sunday 2022-08-28
        assert derive_sort_key("2022-W34") == "2022-08-28"

    def test_weekly_sort_key_week_one(self):
        # ISO week 1 of 2023: ends Sunday 2023-01-08
        assert derive_sort_key("2023-W01") == "2023-01-08"

    def test_unknown_stem_is_daily_fallback(self):
        # Non-matching names sort by themselves, treated as daily
        assert derive_kind("random-note") == "daily"
        assert derive_sort_key("random-note") == "random-note"

    def test_weekly_invalid_week_falls_back_to_stem(self):
        # 2021 has only 52 ISO weeks; W53 is invalid and must not raise.
        assert derive_sort_key("2021-W53") == "2021-W53"


from src.services.notes_service import extract_snippet, has_photo_embed


class TestSnippet:
    def test_has_photo_embed_true(self):
        assert has_photo_embed("intro\n![[photo_2026-05-21.jpg]]\n") is True

    def test_has_photo_embed_false(self):
        assert has_photo_embed("just text, no embeds") is False

    def test_snippet_strips_headers_and_markdown(self):
        body = "# Title\n\n## Notes\n- Bought **kebabs** for the picnic\n"
        snip = extract_snippet(body)
        assert snip.startswith("Bought kebabs for the picnic")
        assert "#" not in snip
        assert "*" not in snip

    def test_snippet_truncates_to_140_chars(self):
        body = "x " * 200
        assert len(extract_snippet(body)) <= 140

    def test_snippet_empty_body(self):
        assert extract_snippet("") == ""


from pathlib import Path
from src.services.vault_service import VaultService
from src.services.notes_service import NotesService


def _make_vault(tmp_path: Path) -> VaultService:
    vault = tmp_path / "vault"
    (vault / "10-daily").mkdir(parents=True)
    (vault / "AGENTS.md").write_text("# Agents\n")
    return VaultService(vault)


class TestListNotes:
    def test_orders_newest_first_with_weekly_anchored(self, tmp_path):
        v = _make_vault(tmp_path)
        d = v.vault_path / "10-daily"
        (d / "2026-05-20.md").write_text("---\ntype: daily\n---\n\nolder day\n")
        (d / "2026-05-21.md").write_text("---\ntype: daily\n---\n\nnewer day\n")
        # ISO week 20 of 2026 ends Sunday 2026-05-17, so this sorts oldest.
        (d / "2026-W20.md").write_text("---\ntype: daily\n---\n\nweek note\n")

        notes = NotesService(v).list_notes()
        ids = [n["id"] for n in notes]
        assert ids == ["2026-05-21", "2026-05-20", "2026-W20"]
        assert notes[2]["kind"] == "weekly"
        assert notes[2]["sort_key"] == "2026-05-17"

    def test_list_item_shape(self, tmp_path):
        v = _make_vault(tmp_path)
        (v.vault_path / "10-daily" / "2026-05-21.md").write_text(
            "---\ntype: daily\n---\n\n## Notes\nBought kebabs\n![[p.jpg]]\n"
        )
        note = NotesService(v).list_notes()[0]
        assert set(note) == {"id", "sort_key", "kind", "title", "has_photos", "snippet"}
        assert note["has_photos"] is True
        assert "kebabs" in note["snippet"]

    def test_empty_dir_returns_empty(self, tmp_path):
        v = _make_vault(tmp_path)
        assert NotesService(v).list_notes() == []


class TestReadNote:
    def test_read_returns_markdown_and_frontmatter(self, tmp_path):
        v = _make_vault(tmp_path)
        (v.vault_path / "10-daily" / "2026-05-21.md").write_text(
            "---\ntype: daily\nmood: good\n---\n\n## Notes\nhello\n"
        )
        note = NotesService(v).read_note("2026-05-21")
        assert note["id"] == "2026-05-21"
        assert note["kind"] == "daily"
        assert note["sort_key"] == "2026-05-21"
        assert note["frontmatter"]["mood"] == "good"
        assert "## Notes" in note["markdown"]
        assert "hello" in note["markdown"]

    def test_read_missing_raises(self, tmp_path):
        v = _make_vault(tmp_path)
        with pytest.raises(FileNotFoundError):
            NotesService(v).read_note("2099-01-01")
