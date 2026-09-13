"""Tests for simplified ClaudeService."""

from unittest.mock import MagicMock, patch

from src.services.claude_service import ClaudeService


class TestClaudeServiceInit:
    def test_init_stores_api_key(self):
        with patch("src.services.claude_service.anthropic") as mock_anthropic:
            ClaudeService(api_key="test-key")
            mock_anthropic.Anthropic.assert_called_once_with(api_key="test-key")

    def test_has_create_method(self):
        with patch("src.services.claude_service.anthropic"):
            service = ClaudeService(api_key="test-key")
            assert hasattr(service, "create")

    def test_has_complete_method(self):
        with patch("src.services.claude_service.anthropic"):
            service = ClaudeService(api_key="test-key")
            assert hasattr(service, "complete")

    def test_no_parse_intent_method(self):
        with patch("src.services.claude_service.anthropic"):
            service = ClaudeService(api_key="test-key")
            assert not hasattr(service, "parse_intent")


class TestClaudeServiceCreate:
    def test_create_passes_tools(self):
        with patch("src.services.claude_service.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client

            service = ClaudeService(api_key="test-key")
            tools = [{"name": "test_tool", "description": "test", "input_schema": {}}]

            service.create(
                system="test system",
                messages=[{"role": "user", "content": "hello"}],
                tools=tools,
            )

            call_kwargs = mock_client.messages.create.call_args[1]
            assert call_kwargs["tools"] == tools
            assert call_kwargs["system"] == "test system"

    def test_create_without_tools(self):
        with patch("src.services.claude_service.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client

            service = ClaudeService(api_key="test-key")

            service.create(
                system="test",
                messages=[{"role": "user", "content": "hello"}],
            )

            call_kwargs = mock_client.messages.create.call_args[1]
            assert "tools" not in call_kwargs


class TestClaudeServiceCreateRouterChoice:
    def _make_service(self, mock_anthropic, response_text: str):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=response_text)]
        mock_client.messages.create.return_value = mock_response
        mock_anthropic.Anthropic.return_value = mock_client
        return ClaudeService(api_key="test-key")

    def test_parses_plain_json(self):
        with patch("src.services.claude_service.anthropic") as mock_anthropic:
            service = self._make_service(
                mock_anthropic,
                '{"skill": "capture", "reason": "user wants to save a note"}',
            )
            result = service.create_router_choice(
                user_msg="save this",
                recent_messages=[],
                skill_catalog=[{"name": "capture", "description": "d", "when_to_use": ""}],
            )
            assert result == {"skill": "capture", "reason": "user wants to save a note"}

    def test_forces_a_known_skill_through_structured_output(self):
        """The router was asked for JSON but not held to it. Given a chat
        history, Haiku sometimes just continued the chat — 11 unparseable
        replies on 2026-09-12/13, each silently routed to `mazkir`, which has
        no write tools. A schema with the skill names as an enum makes prose
        and unknown skills impossible rather than unlikely."""
        with patch("src.services.claude_service.anthropic") as mock_anthropic:
            service = self._make_service(
                mock_anthropic, '{"skill": "recall", "reason": "read-only query"}',
            )
            service.create_router_choice(
                user_msg="show tasks",
                recent_messages=[],
                skill_catalog=[
                    {"name": "capture", "description": "d", "when_to_use": ""},
                    {"name": "recall", "description": "d", "when_to_use": ""},
                ],
            )

            kwargs = mock_anthropic.Anthropic.return_value.messages.create.call_args.kwargs
            assert kwargs["output_config"] == {
                "format": {
                    "type": "json_schema",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "skill": {"type": "string", "enum": ["capture", "recall"]},
                            "reason": {"type": "string"},
                        },
                        "required": ["skill", "reason"],
                        "additionalProperties": False,
                    },
                },
            }

    def test_history_reaches_the_router_as_a_transcript_not_as_turns(self):
        """Handed the conversation as alternating turns, the router is placed
        mid-chat as the assistant, and its most natural output is the next
        reply. As a quoted transcript it is material to classify."""
        with patch("src.services.claude_service.anthropic") as mock_anthropic:
            service = self._make_service(
                mock_anthropic, '{"skill": "recall", "reason": "follow-up"}',
            )
            service.create_router_choice(
                user_msg="yes, do it",
                recent_messages=[
                    {"role": "user", "content": "move the gym block?"},
                    {"role": "assistant", "content": "Move it to 18:00?"},
                ],
                skill_catalog=[{"name": "recall", "description": "d", "when_to_use": ""}],
            )

            messages = mock_anthropic.Anthropic.return_value.messages.create.call_args.kwargs["messages"]
            assert [m["role"] for m in messages] == ["user"]
            content = messages[0]["content"]
            assert "user: move the gym block?" in content
            assert "assistant: Move it to 18:00?" in content
            assert content.rstrip().endswith("yes, do it")


class TestClaudeServiceComplete:
    def test_complete_returns_text(self):
        with patch("src.services.claude_service.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.content = [MagicMock(text="summary text")]
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.Anthropic.return_value = mock_client

            service = ClaudeService(api_key="test-key")
            result = service.complete("summarize this")

            assert result == "summary text"

    def test_complete_uses_haiku_by_default(self):
        with patch("src.services.claude_service.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.content = [MagicMock(text="ok")]
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.Anthropic.return_value = mock_client

            service = ClaudeService(api_key="test-key")
            service.complete("test")

            call_kwargs = mock_client.messages.create.call_args[1]
            assert "haiku" in call_kwargs["model"]
