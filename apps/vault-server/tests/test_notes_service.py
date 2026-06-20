"""Tests for NotesService."""
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
