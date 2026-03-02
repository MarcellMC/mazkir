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
