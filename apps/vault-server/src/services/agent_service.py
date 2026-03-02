"""Agent loop with tool-use, confidence gate, and confirmation flow."""

import json
import logging
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from src.services.claude_service import ClaudeService
from src.services.memory_service import MemoryService
from src.services.vault_service import VaultService

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 0.85


@dataclass
class AgentResponse:
    """Response from the agent loop."""
    response: str
    awaiting_confirmation: bool = False
    pending_action_id: str | None = None


@dataclass
class PendingAction:
    """Stored state when loop is paused for confirmation."""
    chat_id: int
    messages: list[dict]
    assistant_response: Any
    executed_results: list[dict]
    pending_calls: list[dict]


class AgentService:
    """Runs the Claude tool-use agent loop with confidence gating."""

    def __init__(
        self,
        claude: ClaudeService,
        vault: VaultService,
        memory: MemoryService,
        calendar: Any = None,
    ):
        self.claude = claude
        self.vault = vault
        self.memory = memory
        self.calendar = calendar
        self.max_iterations = 10
        self.pending_confirmations: dict[str, PendingAction] = {}
        self.tools = self._register_tools()

    # ── Tool Registry ────────────────────────────────────────────

    def _register_tools(self) -> dict[str, dict]:
        """Register all available tools with schemas and handlers."""
        return {
            "list_tasks": {
                "schema": {
                    "name": "list_tasks",
                    "description": "List all active tasks sorted by priority and due date.",
                    "input_schema": {"type": "object", "properties": {}, "required": []},
                },
                "handler": self._tool_list_tasks,
                "risk": "safe",
            },
            "list_habits": {
                "schema": {
                    "name": "list_habits",
                    "description": "List all active habits with streaks and stats.",
                    "input_schema": {"type": "object", "properties": {}, "required": []},
                },
                "handler": self._tool_list_habits,
                "risk": "safe",
            },
            "list_goals": {
                "schema": {
                    "name": "list_goals",
                    "description": "List all active goals with progress.",
                    "input_schema": {"type": "object", "properties": {}, "required": []},
                },
                "handler": self._tool_list_goals,
                "risk": "safe",
            },
            "get_daily": {
                "schema": {
                    "name": "get_daily",
                    "description": "Get today's daily note with habits, tokens, and calendar.",
                    "input_schema": {"type": "object", "properties": {}, "required": []},
                },
                "handler": self._tool_get_daily,
                "risk": "safe",
            },
            "get_tokens": {
                "schema": {
                    "name": "get_tokens",
                    "description": "Get current motivation token balance and stats.",
                    "input_schema": {"type": "object", "properties": {}, "required": []},
                },
                "handler": self._tool_get_tokens,
                "risk": "safe",
            },
            "search_knowledge": {
                "schema": {
                    "name": "search_knowledge",
                    "description": "Search knowledge notes by topic or keyword.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Search query"},
                            "limit": {"type": "integer", "description": "Max results (default 5)"},
                        },
                        "required": ["query"],
                    },
                },
                "handler": self._tool_search_knowledge,
                "risk": "safe",
            },
            "get_related": {
                "schema": {
                    "name": "get_related",
                    "description": "Get vault items related to a topic via graph traversal.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "topic": {"type": "string", "description": "Topic or item name to explore"},
                            "depth": {"type": "integer", "description": "Hops to traverse (default 2)"},
                        },
                        "required": ["topic"],
                    },
                },
                "handler": self._tool_get_related,
                "risk": "safe",
            },
            "create_task": {
                "schema": {
                    "name": "create_task",
                    "description": "Create a new task in the vault.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Task name"},
                            "priority": {"type": "integer", "description": "Priority 1-5 (1=highest). Default 3."},
                            "due_date": {"type": "string", "description": "Due date YYYY-MM-DD (optional)"},
                            "category": {"type": "string", "description": "Category (default 'personal')"},
                            "_confidence": {"type": "number"},
                            "_reasoning": {"type": "string"},
                        },
                        "required": ["name"],
                    },
                },
                "handler": self._tool_create_task,
                "risk": "write",
            },
            "create_habit": {
                "schema": {
                    "name": "create_habit",
                    "description": "Create a new habit to track.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Habit name"},
                            "frequency": {"type": "string", "description": "daily, weekly, 2x/week, 3x/week"},
                            "category": {"type": "string", "description": "Category (default 'personal')"},
                            "_confidence": {"type": "number"},
                            "_reasoning": {"type": "string"},
                        },
                        "required": ["name"],
                    },
                },
                "handler": self._tool_create_habit,
                "risk": "write",
            },
            "create_goal": {
                "schema": {
                    "name": "create_goal",
                    "description": "Create a new goal.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Goal name"},
                            "priority": {"type": "string", "description": "low, medium, high"},
                            "target_date": {"type": "string", "description": "Target date YYYY-MM-DD (optional)"},
                            "_confidence": {"type": "number"},
                            "_reasoning": {"type": "string"},
                        },
                        "required": ["name"],
                    },
                },
                "handler": self._tool_create_goal,
                "risk": "write",
            },
            "update_item": {
                "schema": {
                    "name": "update_item",
                    "description": "Update metadata of a vault item (task, habit, or goal).",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Relative vault path to the item"},
                            "updates": {"type": "object", "description": "Metadata fields to update"},
                            "_confidence": {"type": "number"},
                            "_reasoning": {"type": "string"},
                        },
                        "required": ["path", "updates"],
                    },
                },
                "handler": self._tool_update_item,
                "risk": "write",
            },
            "save_knowledge": {
                "schema": {
                    "name": "save_knowledge",
                    "description": "Save a knowledge note (idea, fact, or reference).",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Note title"},
                            "content": {"type": "string", "description": "Note content"},
                            "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags"},
                            "links": {"type": "array", "items": {"type": "string"}, "description": "[[wikilinks]]"},
                            "_confidence": {"type": "number"},
                            "_reasoning": {"type": "string"},
                        },
                        "required": ["name", "content"],
                    },
                },
                "handler": self._tool_save_knowledge,
                "risk": "write",
            },
            "complete_task": {
                "schema": {
                    "name": "complete_task",
                    "description": "Mark a task as completed. Awards tokens and archives it.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "task_name": {"type": "string", "description": "Task name or partial match"},
                            "_confidence": {"type": "number"},
                            "_reasoning": {"type": "string"},
                        },
                        "required": ["task_name"],
                    },
                },
                "handler": self._tool_complete_task,
                "risk": "destructive",
            },
            "complete_habit": {
                "schema": {
                    "name": "complete_habit",
                    "description": "Mark a habit as completed for today. Updates streak and awards tokens.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "habit_name": {"type": "string", "description": "Habit name or partial match"},
                            "_confidence": {"type": "number"},
                            "_reasoning": {"type": "string"},
                        },
                        "required": ["habit_name"],
                    },
                },
                "handler": self._tool_complete_habit,
                "risk": "destructive",
            },
        }

    def _tool_schemas(self) -> list[dict]:
        """Get tool schemas for Claude API call."""
        return [t["schema"] for t in self.tools.values()]

    # ── Confidence Gate ──────────────────────────────────────────

    def _check_confidence(self, name: str, params: dict) -> bool:
        """Check if a tool call passes the confidence gate."""
        risk = self.tools[name]["risk"]
        if risk == "safe":
            return True
        confidence = params.pop("_confidence", 0.0)
        params.pop("_reasoning", None)
        return confidence >= CONFIDENCE_THRESHOLD

    # ── Agent Loop ───────────────────────────────────────────────

    def handle_message(self, text: str, chat_id: int) -> AgentResponse:
        """Main entry point: process a user message through the agent loop."""
        context = self.memory.assemble_context(chat_id)

        messages = []
        if context.summary:
            messages.append({"role": "user", "content": f"[Previous conversation summary: {context.summary}]"})
            messages.append({"role": "assistant", "content": "Understood, I have the prior context."})
        for msg in context.messages:
            messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": text})

        system = self._build_system_prompt(context)

        return self._run_loop(chat_id, text, messages, system)

    def handle_confirmation(
        self, chat_id: int, action_id: str, user_response: str,
    ) -> AgentResponse:
        """Resume a paused loop after user confirms or denies."""
        pending = self.pending_confirmations.pop(action_id, None)
        if not pending:
            return AgentResponse(response="No pending action found.")

        if user_response.lower() in ("yes", "y", "ok", "sure", "do it"):
            tool_results = list(pending.executed_results)
            for call in pending.pending_calls:
                result = self._execute_tool(call["name"], call["input"])
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": call["id"],
                    "content": json.dumps(result),
                })

            messages = pending.messages
            messages.append({"role": "assistant", "content": pending.assistant_response.content})
            messages.append({"role": "user", "content": tool_results})

            system = self._build_system_prompt(
                self.memory.assemble_context(chat_id)
            )
            return self._run_loop(chat_id, user_response, messages, system)
        else:
            messages = pending.messages
            messages.append({
                "role": "user",
                "content": f"User responded to confirmation: {user_response}",
            })
            system = self._build_system_prompt(
                self.memory.assemble_context(chat_id)
            )
            return self._run_loop(chat_id, user_response, messages, system)

    def _run_loop(
        self,
        chat_id: int,
        original_text: str,
        messages: list[dict],
        system: str,
    ) -> AgentResponse:
        """Core agent loop: Claude <-> tools until end_turn or max iterations."""
        items_referenced: list[str] = []
        assistant_text = ""
        response = None

        for _ in range(self.max_iterations):
            response = self.claude.create(
                system=system,
                messages=messages,
                tools=self._tool_schemas(),
            )

            if response.stop_reason == "end_turn":
                assistant_text = self._extract_text(response)
                break

            if response.stop_reason == "tool_use":
                tool_calls = self._extract_tool_calls(response)

                needs_confirmation = []
                auto_execute = []
                for call in tool_calls:
                    if self._check_confidence(call["name"], call["input"]):
                        auto_execute.append(call)
                    else:
                        needs_confirmation.append(call)

                if needs_confirmation:
                    executed = []
                    for call in auto_execute:
                        result = self._execute_tool(call["name"], call["input"])
                        items_referenced.extend(result.get("_items", []))
                        executed.append({
                            "type": "tool_result",
                            "tool_use_id": call["id"],
                            "content": json.dumps(result),
                        })

                    action_id = str(uuid4())
                    self.pending_confirmations[action_id] = PendingAction(
                        chat_id=chat_id,
                        messages=messages,
                        assistant_response=response,
                        executed_results=executed,
                        pending_calls=needs_confirmation,
                    )

                    description = self._describe_pending_calls(needs_confirmation)
                    self.memory.save_turn(chat_id, original_text, description, items_referenced)
                    return AgentResponse(
                        response=description,
                        awaiting_confirmation=True,
                        pending_action_id=action_id,
                    )

                tool_results = []
                for call in auto_execute:
                    result = self._execute_tool(call["name"], call["input"])
                    items_referenced.extend(result.get("_items", []))
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": call["id"],
                        "content": json.dumps(result),
                    })

                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})
        else:
            # Max iterations reached
            if response:
                assistant_text = self._extract_text(response)
            if not assistant_text:
                assistant_text = "I hit my processing limit. Please try again with a simpler request."

        self.memory.save_turn(chat_id, original_text, assistant_text, items_referenced)
        self.memory.summarize_and_decay(chat_id)

        return AgentResponse(response=assistant_text)

    # ── Helpers ───────────────────────────────────────────────────

    def _build_system_prompt(self, context) -> str:
        """Build the system prompt with vault snapshot and knowledge."""
        import datetime
        now = datetime.datetime.now()

        parts = [
            "You are Mazkir, a personal AI assistant for managing tasks, habits, goals, and knowledge.",
            "",
            f"Current date/time: {now.strftime('%Y-%m-%d %H:%M')}",
            "",
            "## Tools",
            "You have tools to manage tasks, habits, goals, calendar, and knowledge.",
            "Call tools as needed. You can call multiple tools in sequence.",
            "For every write or destructive tool call, include _confidence (0.0-1.0) and _reasoning fields.",
            "_confidence reflects how sure you are this is the right action. Be honest.",
            "",
            "## Current vault state",
            context.vault_snapshot,
        ]

        if context.knowledge:
            parts.extend(["", "## Relevant knowledge", context.knowledge])

        parts.extend([
            "",
            "## Guidelines",
            "- Be concise and friendly",
            "- Use Telegram markdown: *bold*, _italic_, `monospace`",
            "- When completing items, report tokens earned and streak updates",
            "- When unsure which item the user means, ask — don't guess with low confidence",
            "- Save important facts the user shares using save_knowledge",
            "- Reference specific item names when discussing tasks/habits/goals",
        ])

        return "\n".join(parts)

    def _extract_text(self, response) -> str:
        """Extract text content from a Claude response."""
        for block in response.content:
            if hasattr(block, "text"):
                return block.text
        return ""

    def _extract_tool_calls(self, response) -> list[dict]:
        """Extract tool calls from a Claude response."""
        calls = []
        for block in response.content:
            if hasattr(block, "type") and block.type == "tool_use":
                calls.append({
                    "name": block.name,
                    "id": block.id,
                    "input": dict(block.input),
                })
        return calls

    def _execute_tool(self, name: str, params: dict) -> dict:
        """Execute a registered tool and return its result."""
        if name not in self.tools:
            return {"error": f"Unknown tool: {name}"}
        try:
            handler = self.tools[name]["handler"]
            return handler(params)
        except Exception as e:
            logger.error(f"Tool {name} failed: {e}", exc_info=True)
            return {"error": str(e)}

    def _describe_pending_calls(self, calls: list[dict]) -> str:
        """Build a human-readable description of pending tool calls."""
        lines = ["I'd like to perform the following actions:\n"]
        for call in calls:
            name = call["name"].replace("_", " ")
            params = {k: v for k, v in call["input"].items() if not k.startswith("_")}
            param_str = ", ".join(f"{k}={v}" for k, v in params.items())
            lines.append(f"  - {name}: {param_str}")
        lines.append("\nShould I proceed? (yes/no)")
        return "\n".join(lines)

    # ── Tool Handlers ────────────────────────────────────────────

    def _tool_list_tasks(self, params: dict) -> dict:
        tasks = self.vault.list_active_tasks()
        return {
            "tasks": [
                {"name": t["metadata"].get("name", ""), "path": t["path"],
                 "priority": t["metadata"].get("priority"), "due_date": t["metadata"].get("due_date")}
                for t in tasks
            ],
            "_items": [t["path"] for t in tasks],
        }

    def _tool_list_habits(self, params: dict) -> dict:
        habits = self.vault.list_active_habits()
        return {
            "habits": [
                {"name": h["metadata"].get("name", ""), "path": h["path"],
                 "streak": h["metadata"].get("streak", 0),
                 "frequency": h["metadata"].get("frequency", "daily")}
                for h in habits
            ],
            "_items": [h["path"] for h in habits],
        }

    def _tool_list_goals(self, params: dict) -> dict:
        goals = self.vault.list_active_goals()
        return {
            "goals": [
                {"name": g["metadata"].get("name", ""), "path": g["path"],
                 "progress": g["metadata"].get("progress", 0),
                 "priority": g["metadata"].get("priority")}
                for g in goals
            ],
            "_items": [g["path"] for g in goals],
        }

    def _tool_get_daily(self, params: dict) -> dict:
        try:
            daily = self.vault.read_daily_note()
            return {"daily": daily["metadata"], "content": daily["content"], "_items": [daily["path"]]}
        except Exception:
            return {"error": "No daily note found for today."}

    def _tool_get_tokens(self, params: dict) -> dict:
        try:
            ledger = self.vault.read_token_ledger()
            return {
                "total": ledger["metadata"].get("total_tokens", 0),
                "today": ledger["metadata"].get("tokens_today", 0),
                "all_time": ledger["metadata"].get("all_time_tokens", 0),
            }
        except Exception:
            return {"error": "Token ledger not found."}

    def _tool_search_knowledge(self, params: dict) -> dict:
        results = self.memory.search_knowledge(
            query=params["query"],
            limit=params.get("limit", 5),
        )
        return {"results": results}

    def _tool_get_related(self, params: dict) -> dict:
        results = self.memory.get_related(
            topic=params["topic"],
            depth=params.get("depth", 2),
        )
        return {"related": results}

    def _tool_create_task(self, params: dict) -> dict:
        result = self.vault.create_task(
            name=params["name"],
            priority=params.get("priority", 3),
            due_date=params.get("due_date"),
            category=params.get("category", "personal"),
        )
        return {
            "created": result["metadata"]["name"],
            "path": result["path"],
            "priority": result["metadata"].get("priority"),
            "due_date": result["metadata"].get("due_date"),
            "_items": [result["path"]],
        }

    def _tool_create_habit(self, params: dict) -> dict:
        result = self.vault.create_habit(
            name=params["name"],
            frequency=params.get("frequency", "daily"),
            category=params.get("category", "personal"),
        )
        return {
            "created": result["metadata"]["name"],
            "path": result["path"],
            "frequency": result["metadata"].get("frequency"),
            "_items": [result["path"]],
        }

    def _tool_create_goal(self, params: dict) -> dict:
        result = self.vault.create_goal(
            name=params["name"],
            priority=params.get("priority", "medium"),
            target_date=params.get("target_date"),
        )
        return {
            "created": result["metadata"]["name"],
            "path": result["path"],
            "_items": [result["path"]],
        }

    def _tool_update_item(self, params: dict) -> dict:
        self.vault.update_file(params["path"], params["updates"])
        return {"updated": params["path"], "_items": [params["path"]]}

    def _tool_save_knowledge(self, params: dict) -> dict:
        result = self.memory.save_knowledge(
            name=params["name"],
            content=params["content"],
            tags=params.get("tags", []),
            links=params.get("links", []),
            source="conversation",
        )
        return {"saved": result["path"], "_items": [result["path"]]}

    def _tool_complete_task(self, params: dict) -> dict:
        task = self.vault.find_task_by_name(params["task_name"])
        if not task:
            return {"error": f"No task found matching '{params['task_name']}'"}

        name, tokens, archive_path = self.vault.complete_task(task["path"])

        if self.calendar and task["metadata"].get("google_event_id"):
            try:
                self.calendar.mark_event_complete(task["metadata"]["google_event_id"])
            except Exception as e:
                logger.warning(f"Calendar update failed: {e}")

        return {
            "task": name,
            "tokens_earned": tokens,
            "archived_to": archive_path,
            "_items": [archive_path],
        }

    def _tool_complete_habit(self, params: dict) -> dict:
        import datetime as dt

        habits = self.vault.list_active_habits()
        target = params["habit_name"].lower()

        habit = None
        for h in habits:
            name = h["metadata"].get("name", "").lower()
            if target in name or name in target:
                habit = h
                break

        if not habit:
            return {"error": f"No habit found matching '{params['habit_name']}'"}

        meta = habit["metadata"]
        old_streak = meta.get("streak", 0)
        new_streak = old_streak + 1
        longest = max(meta.get("longest_streak", 0), new_streak)
        today = dt.date.today().isoformat()

        self.vault.update_file(habit["path"], {
            "streak": new_streak,
            "longest_streak": longest,
            "last_completed": today,
        })

        tokens = meta.get("tokens_per_completion", 5)
        self.vault.update_tokens(tokens, meta.get("name", "habit"))

        if self.calendar and meta.get("google_event_id"):
            try:
                self.calendar.mark_event_complete(meta["google_event_id"])
            except Exception as e:
                logger.warning(f"Calendar update failed: {e}")

        return {
            "habit": meta.get("name", ""),
            "old_streak": old_streak,
            "new_streak": new_streak,
            "longest_streak": longest,
            "tokens_earned": tokens,
            "_items": [habit["path"]],
        }
