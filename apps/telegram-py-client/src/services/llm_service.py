"""LLM service abstraction using LangChain."""
import logging
from typing import Literal

from langchain_anthropic import ChatAnthropic
from langchain_ollama import ChatOllama

from src.config import settings

logger = logging.getLogger(__name__)

LLMProvider = Literal["claude", "ollama"]


class LLMService:
    """Service for interacting with LLMs via LangChain."""

    def __init__(self, provider: LLMProvider = "ollama"):
        """Initialize LLM service with specified provider."""
        self.provider = provider
        self.llm = self._initialize_llm(provider)

    def _initialize_llm(self, provider: LLMProvider):
        """Initialize the appropriate LLM client."""
        if provider == "claude":
            if not settings.anthropic_api_key:
                raise ValueError("ANTHROPIC_API_KEY not set in environment")
            return ChatAnthropic(
                model="claude-3-5-sonnet-20241022",
                api_key=settings.anthropic_api_key,
            )
        elif provider == "ollama":
            return ChatOllama(
                model=settings.ollama_model,
                base_url=settings.ollama_base_url,
            )
        else:
            raise ValueError(f"Unknown provider: {provider}")

    async def generate(self, prompt: str) -> str:
        """Generate text from the LLM."""
        try:
            response = await self.llm.ainvoke(prompt)
            return response.content
        except Exception as e:
            logger.error(f"Error generating response from {self.provider}: {e}")
            raise

    async def analyze_messages(self, messages: list[str]) -> str:
        """Analyze a list of messages and provide insights."""
        prompt = f"""
Analyze the following messages and provide insights, patterns, and suggestions:

Messages:
{chr(10).join(f"- {msg}" for msg in messages)}

Please provide:
1. Main topics and themes
2. Important action items or reminders
3. Patterns or trends
4. Suggestions for organization or follow-up
"""
        return await self.generate(prompt)
