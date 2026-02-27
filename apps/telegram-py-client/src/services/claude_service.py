import anthropic
from datetime import datetime
import pytz
from typing import List, Dict


class ClaudeService:
    """Service for interacting with Claude API"""

    def __init__(self, api_key: str, vault_path: str, timezone: str = "Asia/Jerusalem"):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.vault_path = vault_path
        self.tz = pytz.timezone(timezone)

        # Read AGENTS.md from vault for context
        agents_md_path = f"{vault_path}/AGENTS.md"
        try:
            with open(agents_md_path, 'r', encoding='utf-8') as f:
                self.vault_docs = f.read()
        except FileNotFoundError:
            self.vault_docs = "AGENTS.md not found"

    def build_system_prompt(self, context: Dict = None) -> str:
        """Build system prompt with vault context"""
        now = datetime.now(self.tz)

        base_prompt = f"""You are Marc's Personal AI Assistant with access to his Obsidian vault.

Current date: {now.strftime('%Y-%m-%d')}
Current time: {now.strftime('%H:%M')}
Day of week: {now.strftime('%A')}
Timezone: {self.tz.zone}

Vault location: {self.vault_path}

# Vault Documentation

{self.vault_docs}

# Your Capabilities

You can help Marc with:
- Tracking habits and building streaks
- Managing tasks and goals
- Awarding motivation tokens
- Creating and updating daily notes
- Providing progress reports and insights
- Answering questions about his vault data

# Important Guidelines

1. Be encouraging and supportive
2. Use emojis appropriately (💪🎯📖🧘🪙)
3. Be concise - Marc is busy
4. Show streaks, totals, and progress
5. Suggest next actions
6. NEVER delete user data without explicit confirmation
7. ALWAYS update the 'updated' field when modifying files

When Marc completes an activity:
1. Identify the type (habit/task/goal)
2. Calculate tokens earned (see token values in AGENTS.md)
3. Update the relevant files
4. Respond with encouragement + stats
"""

        if context:
            base_prompt += f"\n\n# Additional Context\n\n{context}\n"

        return base_prompt

    def chat(self, message: str, context: Dict = None, model: str = "claude-sonnet-4-20250514", max_tokens: int = 4000) -> str:
        """Send message to Claude and get response

        Args:
            message: User's message
            context: Optional context dictionary
            model: Claude model to use
            max_tokens: Maximum tokens in response

        Returns:
            Claude's response as text
        """
        system_prompt = self.build_system_prompt(context)

        response = self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{
                "role": "user",
                "content": message
            }]
        )

        return response.content[0].text

    def parse_intent(self, message: str, habits_list: List[str] = None,
                     tasks_list: List[str] = None) -> Dict:
        """Parse user message to determine intent and extract structured data

        Args:
            message: User's message
            habits_list: List of habit names for context
            tasks_list: List of task names for context

        Returns:
            Dict with 'intent', 'data', and 'reasoning'
        """
        now = datetime.now(self.tz)

        # Build context
        context_parts = []
        if habits_list:
            context_parts.append(f"Available habits: {', '.join(habits_list)}")
        if tasks_list:
            context_parts.append(f"Active tasks: {', '.join(tasks_list[:10])}")  # Limit to 10

        context = "\n".join(context_parts) if context_parts else ""

        intent_prompt = f"""Analyze this message and determine the user's intent.

Message: "{message}"

Current date: {now.strftime('%Y-%m-%d')}
Current time: {now.strftime('%H:%M')}
{context}

Possible intents:
1. HABIT_COMPLETION - User completed a habit (e.g., "I completed gym", "did meditation", "finished reading")
2. HABIT_CREATION - User wants to create a new habit (e.g., "create habit: morning run", "add habit for reading")
3. TASK_CREATION - User wants to create a task (e.g., "create task: buy milk", "add task to buy groceries", "remind me to...")
4. TASK_COMPLETION - User completed a task (e.g., "I finished buying groceries", "done with taxes", "completed the task")
5. GOAL_CREATION - User wants to create a goal (e.g., "create goal: learn python", "new goal to lose weight")
6. QUERY - User is asking a question (e.g., "show my streaks", "what's my progress", "list tasks")
7. GENERAL_CHAT - General conversation or unclear intent

Return a JSON object with:
{{
  "intent": "HABIT_COMPLETION|HABIT_CREATION|TASK_CREATION|TASK_COMPLETION|GOAL_CREATION|QUERY|GENERAL_CHAT",
  "data": {{
    // For HABIT_COMPLETION: {{"habit_name": "gym", "confidence": "high|medium|low"}}
    // For HABIT_CREATION: {{"habit_name": "morning run", "frequency": "daily", "category": "health"}}
    // For TASK_CREATION: {{"task_name": "buy milk", "priority": 3, "due_date": "2026-02-06" or null, "category": "personal"}}
    // For TASK_COMPLETION: {{"task_name": "buy groceries", "confidence": "high|medium|low"}}
    // For GOAL_CREATION: {{"goal_name": "learn python", "priority": "high|medium|low", "category": "learning"}}
    // For QUERY: {{"query_type": "streaks|progress|tokens|tasks|habits|goals"}}
    // For GENERAL_CHAT: {{}}
  }},
  "reasoning": "Brief explanation of why you chose this intent"
}}

Respond ONLY with valid JSON, no other text."""

        response = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            messages=[{
                "role": "user",
                "content": intent_prompt
            }]
        )

        import json
        import re

        # Extract JSON from response
        response_text = response.content[0].text
        # Try to find JSON in the response
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        else:
            # Fallback to general chat if JSON parsing fails
            return {
                "intent": "GENERAL_CHAT",
                "data": {},
                "reasoning": "Failed to parse intent"
            }
