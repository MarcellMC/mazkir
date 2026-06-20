"""Agent loop with tool-use, confidence gate, and confirmation flow."""

import base64
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from opentelemetry import trace as _otel_trace
from opentelemetry.trace import NonRecordingSpan, SpanContext, Status, StatusCode, set_span_in_context
from openinference.instrumentation import using_attributes
from openinference.semconv.trace import SpanAttributes

from src.logging_setup import emit_agent_turn
from src.tracing_setup import fs_span
from src.services.tracing_helpers import with_span_status
from src.services.claude_service import ClaudeService
from src.services.hooks import register_hook, run_pre_hooks, run_post_hooks
from src.services.hooks.validate_schema import validate_schema as _validate_schema_hook
from src.services.hooks.audit_log import audit_log as _audit_log_hook
from src.services.hooks.sync_to_calendar import sync_to_calendar as _sync_to_calendar_hook
from src.services.memory_service import MemoryService
from src.services.preview import register_preview_fn, render_preview
from src.services.skill_executor import SkillExecutor
from src.services.tool_response import ErrorCode, err, ok
from src.services.vault_service import VaultService

logger = logging.getLogger(__name__)

_tracer = _otel_trace.get_tracer("mazkir.agent")

# Canonical task-priority scale (matches memory/AGENTS.md and the Telegram UI):
# 5 = highest urgency, 1 = lowest. Keep tool schemas and reply text aligned.
_PRIORITY_LABELS = {1: "lowest", 2: "low", 3: "medium", 4: "high", 5: "highest"}


def _fmt_priority(value: Any) -> str:
    """Render a priority value with its label, e.g. '4 (high)'."""
    try:
        return f"{value} ({_PRIORITY_LABELS[int(value)]})"
    except (KeyError, TypeError, ValueError):
        return str(value)


def _register_destructive_previews() -> None:
    """Register human-readable preview functions for all destructive tools.

    Called from AgentService.__init__ (idempotent — re-registration is a no-op
    because register_preview_fn simply overwrites the same key).
    """

    def _preview_delete_task(params: dict, ctx: Any) -> str:
        return f"Would delete task: **{params.get('task_name', '?')}**"

    def _preview_archive_task(params: dict, ctx: Any) -> str:
        return f"Would archive task: **{params.get('task_name', '?')}**"

    def _preview_delete_habit(params: dict, ctx: Any) -> str:
        return f"Would delete habit: **{params.get('habit_name', '?')}**"

    def _preview_archive_goal(params: dict, ctx: Any) -> str:
        return f"Would archive goal: **{params.get('goal_name', '?')}**"

    def _preview_complete_task(params: dict, ctx: Any) -> str:
        return f"Would mark task **{params.get('task_name', '?')}** as done"

    def _preview_complete_habit(params: dict, ctx: Any) -> str:
        return f"Would log completion of habit **{params.get('habit_name', '?')}**"

    register_preview_fn("delete_task", _preview_delete_task)
    register_preview_fn("archive_task", _preview_archive_task)
    register_preview_fn("delete_habit", _preview_delete_habit)
    register_preview_fn("archive_goal", _preview_archive_goal)
    register_preview_fn("complete_task", _preview_complete_task)
    register_preview_fn("complete_habit", _preview_complete_habit)

CONFIDENCE_THRESHOLD = 0.85

_RISK_DEFAULT_THRESHOLDS: dict[str, float | None] = {
    "safe": None,
    "write": 0.85,
    "destructive": 0.95,
}


def _confidence_threshold_for(risk: str) -> float | None:
    """Return the default confidence threshold for a given risk class."""
    return _RISK_DEFAULT_THRESHOLDS.get(risk)


def _sanitize_params(params: dict) -> dict:
    """Strip internal fields and truncate long strings for safe logging."""
    out: dict[str, Any] = {}
    for k, v in params.items():
        if k.startswith("_"):
            continue
        if isinstance(v, str) and len(v) > 200:
            out[k] = v[:200] + "…"
        else:
            out[k] = v
    return out


def _summarize_result(result: dict) -> dict:
    """Compact form of a tool result for the audit record."""
    summary: dict[str, Any] = {}
    for k, v in result.items():
        if k == "_items":
            continue
        if isinstance(v, str) and len(v) > 200:
            summary[k] = v[:200] + "…"
        elif isinstance(v, list):
            summary[k] = f"<list len={len(v)}>"
        else:
            summary[k] = v
    return summary


@dataclass
class AgentResponse:
    """Response from the agent loop."""
    response: str
    awaiting_confirmation: bool = False
    pending_action_id: str | None = None
    iterations: int = 0


@dataclass
class PendingAction:
    """Stored state when loop is paused for confirmation."""
    chat_id: int
    messages: list[dict]
    assistant_response: Any
    executed_results: list[dict]
    pending_calls: list[dict]
    parent_span_context: SpanContext | None = None


class AgentService:
    """Runs the Claude tool-use agent loop with confidence gating."""

    def __init__(
        self,
        claude: ClaudeService,
        vault: VaultService,
        memory: MemoryService,
        calendar: Any = None,
        media_path: Path | None = None,
        events: Any = None,
        *,
        skill_registry: Any = None,
        router: Any = None,
    ):
        self.claude = claude
        self.vault = vault
        self.memory = memory
        self.calendar = calendar
        self.media_path = media_path or Path.home() / "dev" / "mazkir" / "data" / "media"
        self.events = events
        self.skill_registry = skill_registry
        self.router = router
        self.max_iterations = 10
        self.pending_confirmations: dict[str, PendingAction] = {}
        # Transient: set during a streaming handle_message turn, cleared in finally.
        self._stream_callback: "Callable[[str], None] | None" = None
        self.tools = self._register_tools()
        # Register built-in hooks (idempotent — safe to call multiple times)
        register_hook("validate_schema", _validate_schema_hook)
        register_hook("audit_log", _audit_log_hook)
        register_hook("sync_to_calendar", _sync_to_calendar_hook)
        # Register preview functions for destructive tools (idempotent)
        _register_destructive_previews()
        # Instantiate the skill loop orchestrator when skills are enabled.
        # Use a lambda so monkeypatching agent._run_loop in tests still works.
        if self.skill_registry is not None and self.router is not None:
            self._skill_executor: SkillExecutor | None = SkillExecutor(
                skill_registry=self.skill_registry,
                router=self.router,
                tools=self.tools,
                run_loop=lambda *a, **kw: self._run_loop(*a, **kw),
                build_base_system_prompt=self._build_system_prompt,
                build_static_prefix=self._build_static_prefix,
            )
        else:
            self._skill_executor = None

    # ── Tool Registry ────────────────────────────────────────────

    def _register_tools(self) -> dict[str, dict]:
        """Register all available tools with schemas and handlers."""
        tools = {
            "list_tasks": {
                "schema": {
                    "name": "list_tasks",
                    "description": "List all active tasks sorted by priority and due date.",
                    "input_schema": {"type": "object", "properties": {}, "required": []},
                },
                "handler": self._tool_list_tasks,
                "risk": "safe",
                "pre_hooks": [],
            },
            "list_habits": {
                "schema": {
                    "name": "list_habits",
                    "description": "List all active habits with streaks and stats.",
                    "input_schema": {"type": "object", "properties": {}, "required": []},
                },
                "handler": self._tool_list_habits,
                "risk": "safe",
                "pre_hooks": [],
            },
            "list_goals": {
                "schema": {
                    "name": "list_goals",
                    "description": "List all active goals with progress.",
                    "input_schema": {"type": "object", "properties": {}, "required": []},
                },
                "handler": self._tool_list_goals,
                "risk": "safe",
                "pre_hooks": [],
            },
            "get_daily": {
                "schema": {
                    "name": "get_daily",
                    "description": "Get today's daily note with habits, tokens, and calendar.",
                    "input_schema": {"type": "object", "properties": {}, "required": []},
                },
                "handler": self._tool_get_daily,
                "risk": "safe",
                "pre_hooks": [],
            },
            "read_daily_section": {
                "schema": {
                    "name": "read_daily_section",
                    "description": "Read the content of a daily note section (e.g., Notes, Tasks, Daily Habits).",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "section": {"type": "string", "description": "Section name (e.g., 'Notes', 'Tasks', 'Daily Habits')"},
                            "date": {"type": "string", "description": "Date YYYY-MM-DD (default: today)"},
                        },
                        "required": ["section"],
                    },
                },
                "handler": self._tool_read_daily_section,
                "risk": "safe",
                "pre_hooks": [],
            },
            "edit_daily_section": {
                "schema": {
                    "name": "edit_daily_section",
                    "description": "Replace the content of a daily note section. Use read_daily_section first to see current content.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "section": {"type": "string", "description": "Section name (e.g., 'Notes', 'Tasks')"},
                            "content": {"type": "string", "description": "New section content (replaces existing)"},
                            "date": {"type": "string", "description": "Date YYYY-MM-DD (default: today)"},
                            "_confidence": {"type": "number"},
                            "_reasoning": {"type": "string"},
                        },
                        "required": ["section", "content"],
                    },
                },
                "handler": self._tool_edit_daily_section,
                "risk": "write",
                "pre_hooks": ["validate_schema"],
            },
            "daily_add_task": {
                "schema": {
                    "name": "daily_add_task",
                    "description": (
                        "Add a checkbox task to today's daily note `## Tasks` section. "
                        "Optional `scheduled_at` (HH:MM) and `duration_minutes` produce "
                        "the inline `HH:MM — text (NNm)` annotation."
                    ),
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "scheduled_at": {"type": ["string", "null"], "description": "HH:MM"},
                            "duration_minutes": {"type": ["integer", "null"]},
                            "date": {"type": ["string", "null"], "description": "YYYY-MM-DD; default today"},
                            "_confidence": {"type": "number"},
                            "_reasoning": {"type": "string"},
                        },
                        "required": ["text"],
                        "additionalProperties": False,
                    },
                },
                "handler": self._tool_daily_add_task,
                "risk": "write",
            },
            "daily_set_task_state": {
                "schema": {
                    "name": "daily_set_task_state",
                    "description": (
                        "Change a daily-tier task's state. Match by `text` substring "
                        "(case-insensitive). state is one of: checked, unchecked, moved."
                    ),
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "state": {"type": "string", "enum": ["checked", "unchecked", "moved"]},
                            "date": {"type": ["string", "null"], "description": "YYYY-MM-DD; default today"},
                            "_confidence": {"type": "number"},
                            "_reasoning": {"type": "string"},
                        },
                        "required": ["text", "state"],
                        "additionalProperties": False,
                    },
                },
                "handler": self._tool_daily_set_task_state,
                "risk": "write",
            },
            "daily_rollover": {
                "schema": {
                    "name": "daily_rollover",
                    "description": (
                        "Roll over unchecked top-level tasks from one day to another. "
                        "Marks originals as moved (strikethrough) and copies them to the "
                        "target day with a `moved from [[<first_original>#Tasks]]` "
                        "annotation. Defaults: from_date = yesterday, to_date = today. "
                        "Idempotent — skips items already rolled over."
                    ),
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "from_date": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
                            "to_date":   {"type": ["string", "null"], "description": "YYYY-MM-DD"},
                            "_confidence": {"type": "number"},
                            "_reasoning": {"type": "string"},
                        },
                        "additionalProperties": False,
                    },
                },
                "handler": self._tool_daily_rollover,
                "risk": "write",
            },
            "promote_daily_task": {
                "schema": {
                    "name": "promote_daily_task",
                    "description": (
                        "Convert a daily-tier checkbox task into a file-tier task in "
                        "40-tasks/active/. Walks the `moved from [[...]]` chain to find "
                        "the original creation date and uses it for the new file's "
                        "`created` field. Replaces the daily line with a wikilink "
                        "[[<slug>]] to the new file."
                    ),
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string", "description": "Daily task text (substring match)"},
                            "priority": {"type": ["integer", "null"], "minimum": 1, "maximum": 5, "description": "Priority 1-5. 5=highest/most urgent, 1=lowest."},
                            "due_date": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
                            "date": {"type": ["string", "null"], "description": "Daily note date; default today"},
                            "_confidence": {"type": "number"},
                            "_reasoning": {"type": "string"},
                        },
                        "required": ["text"],
                        "additionalProperties": False,
                    },
                },
                "handler": self._tool_promote_daily_task,
                "risk": "write",
            },
            "get_tokens": {
                "schema": {
                    "name": "get_tokens",
                    "description": "Get current motivation token balance and stats.",
                    "input_schema": {"type": "object", "properties": {}, "required": []},
                },
                "handler": self._tool_get_tokens,
                "risk": "safe",
                "pre_hooks": [],
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
                "pre_hooks": [],
            },
            "read_knowledge": {
                "schema": {
                    "name": "read_knowledge",
                    "description": (
                        "Read the full body of a knowledge note. Use after search_knowledge "
                        "(which only returns titles/paths) to actually read a note's contents."
                    ),
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Vault-relative path as returned by search_knowledge.",
                            },
                            "name": {
                                "type": "string",
                                "description": "Note name/title, used when path is unknown.",
                            },
                        },
                        "required": [],
                    },
                },
                "handler": self._tool_read_knowledge,
                "risk": "safe",
                "pre_hooks": [],
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
                "pre_hooks": [],
            },
            "create_task": {
                "schema": {
                    "name": "create_task",
                    "description": "Create a new task in the vault.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Task name"},
                            "description": {"type": "string", "description": "Details accompanying the task (steps, context, links). Saved into the task note's ## Description section — use this instead of a separate knowledge note."},
                            "priority": {"type": "integer", "minimum": 1, "maximum": 5, "description": "Priority 1-5. 5=highest/most urgent, 1=lowest. Default 3."},
                            "due_date": {"type": "string", "description": "Due date YYYY-MM-DD (optional)"},
                            "category": {"type": "string", "description": "Category (default 'personal')"},
                            "scheduled_at": {"type": ["string", "null"], "description": "ISO datetime (e.g. 2026-06-05T14:00)"},
                            "duration_minutes": {"type": ["integer", "null"]},
                            "due_soft": {"type": ["string", "null"], "description": "Soft deadline YYYY-MM-DD"},
                            "_confidence": {"type": "number"},
                            "_reasoning": {"type": "string"},
                        },
                        "required": ["name"],
                    },
                },
                "handler": self._tool_create_task,
                "risk": "write",
                "pre_hooks": ["validate_schema"],
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
                            "scheduled_at": {"type": ["string", "null"], "description": "Recurring daily slot HH:MM"},
                            "duration_minutes": {"type": ["integer", "null"]},
                            "_confidence": {"type": "number"},
                            "_reasoning": {"type": "string"},
                        },
                        "required": ["name"],
                    },
                },
                "handler": self._tool_create_habit,
                "risk": "write",
                "pre_hooks": ["validate_schema"],
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
                            "start_date": {"type": ["string", "null"], "description": "Goal start date YYYY-MM-DD"},
                            "_confidence": {"type": "number"},
                            "_reasoning": {"type": "string"},
                        },
                        "required": ["name"],
                    },
                },
                "handler": self._tool_create_goal,
                "risk": "write",
                "pre_hooks": ["validate_schema"],
            },
            "update_task": {
                "schema": {
                    "name": "update_task",
                    "description": (
                        "Update fields on an existing task. Specify the task by fuzzy "
                        "`name` match. Provide only the fields you want to change. "
                        "`append_note` adds free-text to the task body with a timestamp."
                    ),
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Task name (fuzzy match)"},
                            "priority": {"type": "integer", "minimum": 1, "maximum": 5, "description": "Priority 1-5. 5=highest/most urgent, 1=lowest. 'min/lowest priority' means 1; 'top/highest priority' means 5."},
                            "status": {"type": "string", "enum": ["active", "blocked", "done", "archived"]},
                            "category": {"type": "string"},
                            "scheduled_at": {"type": ["string", "null"], "description": "ISO datetime"},
                            "duration_minutes": {"type": ["integer", "null"]},
                            "due_date": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
                            "due_soft": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
                            "append_note": {"type": "string"},
                            "_confidence": {"type": "number"},
                            "_reasoning": {"type": "string"},
                        },
                        "required": ["name"],
                        "additionalProperties": False,
                    },
                },
                "handler": self._tool_update_task,
                "risk": "write",
                "pre_hooks": ["validate_schema"],
            },
            "update_habit": {
                "schema": {
                    "name": "update_habit",
                    "description": "Update fields on an existing habit. Specify by fuzzy `name`.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "frequency": {"type": "string", "enum": ["daily", "weekly", "monthly"]},
                            "scheduled_at": {"type": ["string", "null"], "description": "HH:MM"},
                            "duration_minutes": {"type": ["integer", "null"]},
                            "tokens_per_completion": {"type": "integer"},
                            "append_note": {"type": "string"},
                            "_confidence": {"type": "number"},
                            "_reasoning": {"type": "string"},
                        },
                        "required": ["name"],
                        "additionalProperties": False,
                    },
                },
                "handler": self._tool_update_habit,
                "risk": "write",
                "pre_hooks": ["validate_schema"],
            },
            "update_goal": {
                "schema": {
                    "name": "update_goal",
                    "description": "Update fields on an existing goal. Specify by fuzzy `name`.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "status": {"type": "string", "enum": ["active", "paused", "completed", "archived", "in-progress", "not-started"]},
                            "progress": {"type": "integer", "minimum": 0, "maximum": 100},
                            "priority": {"type": "integer", "minimum": 1, "maximum": 5, "description": "Priority 1-5. 5=highest/most urgent, 1=lowest."},
                            "start_date": {"type": ["string", "null"]},
                            "target_date": {"type": ["string", "null"]},
                            "append_note": {"type": "string"},
                            "_confidence": {"type": "number"},
                            "_reasoning": {"type": "string"},
                        },
                        "required": ["name"],
                        "additionalProperties": False,
                    },
                },
                "handler": self._tool_update_goal,
                "risk": "write",
                "pre_hooks": ["validate_schema"],
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
                "pre_hooks": ["validate_schema"],
            },
            "attach_to_daily": {
                "schema": {
                    "name": "attach_to_daily",
                    "description": (
                        "Attach a saved photo or file to a daily note (today's by default). "
                        "Pass 'date' to target a different day's note. "
                        "Use after a photo has been saved to disk. "
                        "Can include wikilinks (e.g. [[City Watch]]) and location coordinates."
                    ),
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "vault_path": {
                                "type": "string",
                                "description": "Path to saved attachment (from '[Photo saved to: ...]' context)",
                            },
                            "caption": {
                                "type": "string",
                                "description": "Caption/description for the attachment",
                            },
                            "wikilinks": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Wikilink targets to include, e.g. ['City Watch']",
                            },
                            "location": {
                                "type": "object",
                                "properties": {
                                    "lat": {"type": "number"},
                                    "lng": {"type": "number"},
                                    "name": {"type": "string"},
                                },
                                "description": "Location coordinates — rendered as a map link in the daily note (name used as the link label)",
                            },
                            "section": {
                                "type": "string",
                                "description": "Daily note section to add under (default: 'Notes')",
                            },
                            "date": {
                                "type": "string",
                                "description": "Target daily note date (YYYY-MM-DD). Defaults to today.",
                            },
                            "_confidence": {"type": "number"},
                            "_reasoning": {"type": "string"},
                        },
                        "required": ["vault_path", "caption"],
                    },
                },
                "handler": self._tool_attach_to_daily,
                "risk": "write",
                "pre_hooks": ["validate_schema"],
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
                "preview": True,
                "pre_hooks": ["validate_schema"],
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
                "preview": True,
                "pre_hooks": ["validate_schema"],
            },
            "delete_task": {
                "schema": {
                    "name": "delete_task",
                    "description": "Permanently delete a task. Use archive_task if you want to keep it.",
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
                "handler": self._tool_delete_task,
                "risk": "destructive",
                "preview": True,
                "pre_hooks": ["validate_schema"],
            },
            "archive_task": {
                "schema": {
                    "name": "archive_task",
                    "description": "Archive a task without completing it. No tokens awarded. Use for abandoned or deferred tasks.",
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
                "handler": self._tool_archive_task,
                "risk": "destructive",
                "preview": True,
                "pre_hooks": ["validate_schema"],
            },
            "delete_habit": {
                "schema": {
                    "name": "delete_habit",
                    "description": "Permanently delete a habit.",
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
                "handler": self._tool_delete_habit,
                "risk": "destructive",
                "preview": True,
                "pre_hooks": ["validate_schema"],
            },
            "archive_goal": {
                "schema": {
                    "name": "archive_goal",
                    "description": "Archive a goal (set status to archived).",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "goal_name": {"type": "string", "description": "Goal name or partial match"},
                            "_confidence": {"type": "number"},
                            "_reasoning": {"type": "string"},
                        },
                        "required": ["goal_name"],
                    },
                },
                "handler": self._tool_archive_goal,
                "risk": "destructive",
                "preview": True,
                "pre_hooks": ["validate_schema"],
            },
            "list_events": {
                "schema": {
                    "name": "list_events",
                    "description": "List today's events (calendar, timeline, manual). Returns event IDs, names, times, locations, and photo counts.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "date": {"type": "string", "description": "Date YYYY-MM-DD (default: today)"},
                        },
                        "required": [],
                    },
                },
                "handler": self._tool_list_events,
                "risk": "safe",
                "pre_hooks": [],
            },
            "attach_photo_to_event": {
                "schema": {
                    "name": "attach_photo_to_event",
                    "description": (
                        "Attach a saved photo to an existing event. "
                        "Use list_events first to find the right event ID."
                    ),
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "event_id": {"type": "string", "description": "Event ID from list_events"},
                            "photo_path": {"type": "string", "description": "Path from '[Photo saved to: ...]'"},
                            "caption": {"type": "string", "description": "Photo caption"},
                            "wikilinks": {"type": "array", "items": {"type": "string"}, "description": "Wikilinks"},
                            "date": {
                                "type": "string",
                                "description": (
                                    "Date of the event (YYYY-MM-DD), e.g. from list_events. "
                                    "Optional — the event is located by ID across dates if omitted."
                                ),
                            },
                            "_confidence": {"type": "number"},
                            "_reasoning": {"type": "string"},
                        },
                        "required": ["event_id", "photo_path"],
                    },
                },
                "handler": self._tool_attach_photo_to_event,
                "risk": "write",
                "pre_hooks": ["validate_schema"],
            },
            "create_event": {
                "schema": {
                    "name": "create_event",
                    "description": (
                        "Create a new event. Use for photo stops, ad-hoc activities, "
                        "or any event not already in the calendar/timeline. "
                        "Events are recorded in the daily note's ## Schedule section "
                        "and synced to Google Calendar when available."
                    ),
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Event name"},
                            "date": {"type": "string", "description": "Event date YYYY-MM-DD (defaults to today)"},
                            "start_time": {"type": "string", "description": "Start time ISO or HH:MM"},
                            "end_time": {"type": "string", "description": "End time (optional, defaults to start_time)"},
                            "location": {
                                "type": "object",
                                "properties": {"lat": {"type": "number"}, "lng": {"type": "number"}, "name": {"type": "string"}},
                                "description": "Location (optional)",
                            },
                            "category": {"type": "string", "description": "Activity category (optional)"},
                            "photo_path": {"type": "string", "description": "Path to photo (optional)"},
                            "caption": {"type": "string", "description": "Photo caption (optional)"},
                            "wikilinks": {"type": "array", "items": {"type": "string"}, "description": "Wikilinks (optional)"},
                            "_confidence": {"type": "number"},
                            "_reasoning": {"type": "string"},
                        },
                        "required": ["name", "start_time"],
                    },
                },
                "handler": self._tool_create_event,
                "risk": "write",
                "pre_hooks": ["validate_schema"],
            },
            "update_event": {
                "schema": {
                    "name": "update_event",
                    "description": (
                        "Update an existing event's fields (name, start_time, end_time, location, category). "
                        "Use list_events first to find the event ID."
                    ),
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "event_id": {"type": "string", "description": "Event ID from list_events"},
                            "date": {"type": "string", "description": "Event date YYYY-MM-DD (defaults to today)"},
                            "name": {"type": "string", "description": "New event name"},
                            "start_time": {"type": "string", "description": "New start time ISO or HH:MM"},
                            "end_time": {"type": "string", "description": "New end time ISO or HH:MM"},
                            "location": {
                                "type": "object",
                                "properties": {"lat": {"type": "number"}, "lng": {"type": "number"}, "name": {"type": "string"}},
                                "description": "New location",
                            },
                            "category": {"type": "string", "description": "New activity category"},
                            "_confidence": {"type": "number"},
                            "_reasoning": {"type": "string"},
                        },
                        "required": ["event_id"],
                    },
                },
                "handler": self._tool_update_event,
                "risk": "write",
                "pre_hooks": ["validate_schema"],
            },
        }
        from src.services.tool_registry import stamp_tool_registry
        stamp_tool_registry(tools)
        # File-tier writes touch distinct vault paths via the resolver, so they
        # can run concurrently. Daily-section and event writes share a single
        # file and stay unsafe (default False from stamp_tool_registry).
        SAFE_WRITES = {
            "create_task", "create_habit", "create_goal",
            "update_task", "update_habit", "update_goal",
            "complete_task", "complete_habit",
            "delete_task", "archive_task", "delete_habit", "archive_goal",
            "save_knowledge",
        }
        for name in SAFE_WRITES:
            if name in tools:
                tools[name]["safe_for_parallel"] = True
        # Attach sync_to_calendar post-hook to all task/habit write tools.
        SYNC_TOOLS = {
            "create_task", "update_task", "complete_task",
            "archive_task", "delete_task",
            "create_habit", "update_habit", "complete_habit",
            "delete_habit",
        }
        for name in SYNC_TOOLS:
            if name in tools and "sync_to_calendar" not in tools[name].get("post_hooks", []):
                tools[name].setdefault("post_hooks", []).append("sync_to_calendar")
        return tools

    def _tool_schemas(self) -> list[dict]:
        """Get tool schemas for Claude API call."""
        return [t["schema"] for t in self.tools.values()]

    # ── Confidence Gate ──────────────────────────────────────────

    def _check_confidence(self, name: str, params: dict) -> tuple[float, str]:
        """Strip internal fields and return (score, action).

        action is 'auto_execute' or 'needs_confirmation'.
        Internal fields (_confidence, _reasoning) are popped from params as a side effect.
        """
        threshold = self.tools[name].get("confidence_threshold")
        params.pop("_reasoning", None)  # strip from params regardless
        if threshold is None:
            params.pop("_confidence", None)
            return (1.0, "auto_execute")  # safe risk — no gate

        score = float(params.pop("_confidence", 0.0))
        if score >= threshold:
            return (score, "auto_execute")
        return (score, "needs_confirmation")

    # ── Agent Loop ───────────────────────────────────────────────

    def handle_message(
        self,
        text: str,
        chat_id: int,
        attachments: list[dict] | None = None,
        reply_to: dict | None = None,
        forwarded_from: dict | None = None,
        stream_callback: "Callable[[str], None] | None" = None,
    ) -> AgentResponse:
        """Main entry point: process a user message through the agent loop.

        Args:
            stream_callback: Optional callable invoked with each final text chunk
                when streaming is requested.  Only the last agent iteration's
                chunks are forwarded (i.e. after all tool calls complete).
                Intermediate tool-use iterations are buffered and discarded so
                that internal reasoning steps are not surfaced to the caller.
        """
        self._stream_callback = stream_callback
        session_id = str(chat_id)
        user_id = str(chat_id)
        try:
            with using_attributes(session_id=session_id, user_id=user_id):
                _input_text = (text or "")[:2000]
                with _tracer.start_as_current_span(
                    "agent.handle_message",
                    attributes={
                        SpanAttributes.OPENINFERENCE_SPAN_KIND: "AGENT",
                        SpanAttributes.SESSION_ID: session_id,
                        SpanAttributes.USER_ID: user_id,
                        SpanAttributes.INPUT_VALUE: _input_text,
                        SpanAttributes.INPUT_MIME_TYPE: "text/plain",
                        "chat_id": chat_id,
                        "attachment_count": len(attachments or []),
                    },
                ) as span:
                    with with_span_status(span):
                        if len(text or "") > 2000:
                            span.set_attribute("truncated", True)
                        result = self._handle_message_inner(
                            text, chat_id, attachments, reply_to, forwarded_from
                        )
                    _output_text = result.response[:2000]
                    span.set_attribute(SpanAttributes.OUTPUT_VALUE, _output_text)
                    if len(result.response) > 2000:
                        span.set_attribute("truncated", True)
                    span.set_attribute(SpanAttributes.OUTPUT_MIME_TYPE, "text/plain")
                    span.set_attribute(
                        SpanAttributes.METADATA,
                        json.dumps({
                            "awaiting_confirmation": result.awaiting_confirmation,
                            "pending_action_id": result.pending_action_id,
                        }),
                    )
                return result
        finally:
            self._stream_callback = None

    def _handle_message_inner(
        self,
        text: str,
        chat_id: int,
        attachments: list[dict] | None,
        reply_to: dict | None,
        forwarded_from: dict | None,
    ) -> AgentResponse:
        t0 = time.perf_counter()
        context = self.memory.assemble_context(chat_id)
        _otel_trace.get_current_span().set_attribute(
            "vault.snapshot.compute_ms",
            int((time.perf_counter() - t0) * 1000),
        )

        messages = []
        if context.summary:
            messages.append({"role": "user", "content": f"[Previous conversation summary: {context.summary}]"})
            messages.append({"role": "assistant", "content": "Understood, I have the prior context."})
        for msg in context.messages:
            messages.append({"role": msg["role"], "content": msg["content"]})

        # Build enriched user content (with image blocks if photo attached)
        user_content = self._build_user_content(
            text, attachments, reply_to, forwarded_from,
        )
        messages.append({"role": "user", "content": user_content})

        # For conversation log, build a text-only version (no base64)
        log_text = text
        if attachments:
            att_notes = []
            for att in attachments:
                if att["type"] == "photo":
                    att_notes.append(f"photo: {att.get('filename', 'photo')}")
                elif att["type"] == "location":
                    att_notes.append(f"location: {att.get('latitude')}, {att.get('longitude')}")
            if att_notes:
                log_text = f"({', '.join(att_notes)}) {text}".strip()
        if reply_to:
            log_text = f"(replying to {reply_to.get('from', 'user')}: \"{reply_to['text'][:50]}\") {log_text}".strip()

        static_prefix = self._build_static_prefix()
        system = self._build_system_prompt(context)

        if self._skill_executor is not None:
            return self._handle_via_skills(
                chat_id, log_text, messages, system, context,
            )

        return self._run_agent_turn(
            chat_id, log_text, messages, system,
            tool_schemas=self._tool_schemas(),
            max_iterations=self.max_iterations,
            cache_static_prefix=static_prefix,
        )

    # ── Skill-aware path ─────────────────────────────────────────

    def _handle_via_skills(
        self,
        chat_id: int,
        log_text: str,
        messages: list[dict],
        system: str,
        context: Any,
    ) -> AgentResponse:
        """Delegate to SkillExecutor for router→skill→handoff loop."""
        assert self._skill_executor is not None
        result = self._skill_executor.run(
            chat_id=chat_id,
            user_msg=log_text,
            context_messages=context.messages,
            messages=messages,
            context=context,
        )
        return AgentResponse(response=result.response_text, iterations=result.iterations)

    def handle_confirmation(
        self, chat_id: int, action_id: str, user_response: str,
    ) -> AgentResponse:
        """Resume a paused loop after user confirms or denies."""
        # Re-attach to the original turn's trace when possible so the resumed
        # work appears under the same trace tree as the message that asked for
        # confirmation. The inbound /message/confirm HTTP span stays in its
        # own trace; we just override the parent for the agent span.
        pending = self.pending_confirmations.get(action_id)
        parent_ctx = None
        if pending and pending.parent_span_context is not None:
            parent_ctx = set_span_in_context(NonRecordingSpan(pending.parent_span_context))

        session_id = str(chat_id)
        user_id = str(chat_id)
        with using_attributes(session_id=session_id, user_id=user_id):
            with _tracer.start_as_current_span(
                "agent.handle_confirmation",
                context=parent_ctx,
                attributes={
                    SpanAttributes.OPENINFERENCE_SPAN_KIND: "AGENT",
                    SpanAttributes.SESSION_ID: session_id,
                    SpanAttributes.USER_ID: user_id,
                    SpanAttributes.INPUT_VALUE: user_response[:2000],
                    SpanAttributes.INPUT_MIME_TYPE: "text/plain",
                    "chat_id": chat_id,
                    "action_id": action_id,
                },
            ) as span:
                if len(user_response) > 2000:
                    span.set_attribute("truncated", True)
                result = self._handle_confirmation_inner(chat_id, action_id, user_response)
                _conf_output = result.response[:2000]
                span.set_attribute(SpanAttributes.OUTPUT_VALUE, _conf_output)
                if len(result.response) > 2000:
                    span.set_attribute("truncated", True)
                span.set_attribute(SpanAttributes.OUTPUT_MIME_TYPE, "text/plain")
                span.set_status(Status(StatusCode.OK))
                return result

    def _handle_confirmation_inner(
        self, chat_id: int, action_id: str, user_response: str,
    ) -> AgentResponse:
        pending = self.pending_confirmations.pop(action_id, None)
        if not pending:
            return AgentResponse(response="No pending action found.")

        if user_response.lower() in ("yes", "y", "ok", "sure", "do it"):
            tool_results = list(pending.executed_results)
            pre_tools_audit: list[dict] = []
            for call in pending.pending_calls:
                params = dict(call["input"])
                reasoning = params.get("_reasoning")
                confidence, _ = self._check_confidence(call["name"], params)
                result = self._execute_tool(call["name"], params, confidence=confidence, action="auto_execute")
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": call["id"],
                    "content": json.dumps(result),
                })
                pre_tools_audit.append({
                    "name": call["name"],
                    "params": _sanitize_params(params),
                    "confidence": confidence,
                    "reasoning": reasoning,
                    "result_summary": _summarize_result(result) if isinstance(result, dict) else None,
                    "confirmed": True,
                })

            messages = pending.messages
            messages.append({"role": "assistant", "content": pending.assistant_response.content})
            messages.append({"role": "user", "content": tool_results})

            context = self.memory.assemble_context(chat_id)
            system = self._build_system_prompt(context)
            return self._run_agent_turn(
                chat_id, user_response, messages, system,
                tool_schemas=self._tool_schemas(),
                max_iterations=self.max_iterations,
                pre_tools=pre_tools_audit,
                action_id=action_id,
                cache_static_prefix=self._build_static_prefix(),
            )
        else:
            messages = pending.messages
            messages.append({
                "role": "user",
                "content": f"User responded to confirmation: {user_response}",
            })
            context = self.memory.assemble_context(chat_id)
            system = self._build_system_prompt(context)
            return self._run_agent_turn(
                chat_id, user_response, messages, system,
                tool_schemas=self._tool_schemas(),
                max_iterations=self.max_iterations,
                action_id=action_id,
                cache_static_prefix=self._build_static_prefix(),
            )

    def _run_loop(
        self,
        chat_id: int,
        log_text: str,
        messages: list[dict],
        system: str,
        tool_schemas: list[dict],
        max_iterations: int,
        cache_static_prefix: str | None = None,
        model: str | None = None,
    ) -> tuple[str, str]:
        """Parameterized inner Claude tool-use loop. Returns (response_text, stop_reason).

        Delegates to _run_agent_turn which handles the full iteration logic including
        confidence gating, confirmation flow, memory persistence, and audit emission.
        When a confirmation is needed, "needs_confirmation" is returned as the stop_reason.

        Args:
            cache_static_prefix: Static system-prompt prefix to cache via Anthropic
                prompt caching.  Passed through to ClaudeService.create so that
                the cacheable portion is marked with ``cache_control``.
        """
        result = self._run_agent_turn(
            chat_id=chat_id,
            original_text=log_text,
            messages=messages,
            system=system,
            tool_schemas=tool_schemas,
            max_iterations=max_iterations,
            cache_static_prefix=cache_static_prefix,
            model=model,
        )
        if result.awaiting_confirmation:
            return result.response, "needs_confirmation"
        return result.response, "end_turn"

    def _run_agent_turn(
        self,
        chat_id: int,
        original_text: str,
        messages: list[dict],
        system: str,
        tool_schemas: list[dict],
        max_iterations: int,
        pre_tools: list[dict] | None = None,
        action_id: str | None = None,
        cache_static_prefix: str | None = None,
        model: str | None = None,
    ) -> AgentResponse:
        """Core agent loop: Claude <-> tools until end_turn or max iterations.

        ``model`` overrides the LLM model for this turn (e.g. the active skill's
        declared model). When None, ClaudeService.create's default is used.
        """
        items_referenced: list[str] = []
        tools_audit: list[dict] = list(pre_tools) if pre_tools else []
        assistant_text = ""
        response = None
        iters = 0
        stop_reason: str | None = None

        for iter_num in range(max_iterations):
            iters = iter_num + 1
            _last_msg = messages[-1] if messages else {}
            _last_content = str(_last_msg.get("content", ""))[:2000]
            with _tracer.start_as_current_span(
                "agent.loop",
                attributes={
                    SpanAttributes.OPENINFERENCE_SPAN_KIND: "CHAIN",
                    "iteration": iter_num,
                    SpanAttributes.INPUT_VALUE: _last_content,
                },
            ) as _loop_otel_span:
                with with_span_status(_loop_otel_span):
                    _loop_span = _otel_trace.get_current_span()
                    if len(str(_last_msg.get("content", ""))) > 2000:
                        _loop_span.set_attribute("truncated", True)
                    _prompt_chars = len(system) + (len(cache_static_prefix) if cache_static_prefix else 0)
                    _loop_span.set_attribute("system_prompt.token_estimate", _prompt_chars // 4)

                    # Buffer streaming chunks for this iteration; only flush to
                    # the caller when this turns out to be the final iteration
                    # (i.e. no tool_use blocks).  Intermediate tool-use iterations
                    # are silently discarded so the user never sees internal steps.
                    _iter_chunks: list[str] = []

                    def _on_chunk(text: str) -> None:
                        _iter_chunks.append(text)

                    _use_stream = self._stream_callback is not None
                    response = self.claude.create(
                        system=system,
                        messages=messages,
                        tools=tool_schemas,
                        cache_static_prefix=cache_static_prefix,
                        stream=_use_stream,
                        on_chunk=_on_chunk if _use_stream else None,
                        # Use the skill's declared model when provided; otherwise
                        # fall back to ClaudeService.create's default.
                        **({"model": model} if model else {}),
                    )

                    _usage = getattr(response, "usage", None)
                    if _usage is not None:
                        _loop_span.set_attribute(
                            "llm.token_count.prompt_cached_read",
                            getattr(_usage, "cache_read_input_tokens", 0) or 0,
                        )
                        _loop_span.set_attribute(
                            "llm.token_count.prompt_cached_write",
                            getattr(_usage, "cache_creation_input_tokens", 0) or 0,
                        )

                    stop_reason = response.stop_reason

                    _first_text = ""
                    for _block in response.content:
                        if hasattr(_block, "text"):
                            _first_text = _block.text[:2000]
                            break
                    _loop_output = f"stop_reason={stop_reason}; {_first_text}"
                    _loop_span.set_attribute(SpanAttributes.OUTPUT_VALUE, _loop_output)

                    if stop_reason == "end_turn":
                        logger.info(
                            "agent_iter",
                            extra={
                                "event_type": "agent_iter",
                                "chat_id": chat_id,
                                "iter": iters,
                                "stop_reason": stop_reason,
                                "tool_calls": 0,
                            },
                        )
                        assistant_text = self._extract_text(response)
                        # Flush buffered chunks to the caller — this is the final
                        # iteration (no tool calls) so it's safe to stream.
                        if self._stream_callback is not None:
                            for _chunk in _iter_chunks:
                                try:
                                    self._stream_callback(_chunk)
                                except Exception:
                                    pass
                        break

                    if stop_reason == "tool_use":
                        tool_calls = self._extract_tool_calls(response)

                        needs_confirmation = []
                        auto_execute = []
                        gate_info: dict[str, tuple[float, str | None]] = {}
                        preview_texts: dict[str, str] = {}
                        for call in tool_calls:
                            reasoning = call["input"].get("_reasoning")
                            confidence, action = self._check_confidence(call["name"], call["input"])
                            gate_info[call["id"]] = (confidence, reasoning)
                            # Preview gate: destructive tools with preview=True always
                            # require confirmation so the user sees the preview text
                            # before the action executes — even at high confidence.
                            tool_entry = self.tools.get(call["name"], {})
                            if action == "auto_execute" and tool_entry.get("preview"):
                                preview_text = render_preview(
                                    call["name"],
                                    dict(call["input"]),
                                    ctx={"vault": self.vault, "tool": tool_entry},
                                )
                                preview_texts[call["id"]] = preview_text
                                action = "needs_confirmation"
                                _otel_trace.get_current_span().set_attribute("preview.tool", call["name"])
                                _otel_trace.get_current_span().set_attribute("preview.text_length", len(preview_text))
                            if action == "auto_execute":
                                auto_execute.append(call)
                            else:
                                needs_confirmation.append(call)

                        logger.info(
                            "agent_iter",
                            extra={
                                "event_type": "agent_iter",
                                "chat_id": chat_id,
                                "iter": iters,
                                "stop_reason": stop_reason,
                                "tool_calls": len(tool_calls),
                                "auto_execute": [
                                    {"name": c["name"], "confidence": gate_info[c["id"]][0]}
                                    for c in auto_execute
                                ],
                                "needs_confirmation": [
                                    {"name": c["name"], "confidence": gate_info[c["id"]][0]}
                                    for c in needs_confirmation
                                ],
                            },
                        )

                        if needs_confirmation:
                            executed = []
                            for call, confidence, reasoning, result in self._execute_tool_batch(auto_execute, gate_info):
                                items_referenced.extend(result.get("_items", []))
                                executed.append({
                                    "type": "tool_result",
                                    "tool_use_id": call["id"],
                                    "content": json.dumps(result),
                                })
                                tools_audit.append({
                                    "name": call["name"],
                                    "params": _sanitize_params(call["input"]),
                                    "confidence": confidence,
                                    "reasoning": reasoning,
                                    "result_summary": _summarize_result(result) if isinstance(result, dict) else None,
                                    "confirmed": False,
                                })

                            pending_action_id = str(uuid4())
                            current_ctx = _otel_trace.get_current_span().get_span_context()
                            self.pending_confirmations[pending_action_id] = PendingAction(
                                chat_id=chat_id,
                                messages=messages,
                                assistant_response=response,
                                executed_results=executed,
                                pending_calls=needs_confirmation,
                                parent_span_context=current_ctx if current_ctx.is_valid else None,
                            )

                            for call in needs_confirmation:
                                confidence, reasoning = gate_info[call["id"]]
                                tools_audit.append({
                                    "name": call["name"],
                                    "params": _sanitize_params(call["input"]),
                                    "confidence": confidence,
                                    "reasoning": reasoning,
                                    "result_summary": None,
                                    "confirmed": False,
                                    "pending": True,
                                })

                            description = self._describe_pending_calls(needs_confirmation, preview_texts)
                            self.memory.save_turn(chat_id, original_text, description, items_referenced)
                            _otel_trace.get_current_span().set_attribute(
                                SpanAttributes.METADATA,
                                json.dumps({
                                    "iters": iters,
                                    "stop_reason": stop_reason,
                                    "tools_used": [t["name"] for t in tools_audit],
                                    "awaiting_confirmation": True,
                                }),
                            )
                            self._emit_turn_audit(
                                chat_id=chat_id,
                                user_text=original_text,
                                tools_audit=tools_audit,
                                assistant_text=description,
                                items_referenced=items_referenced,
                                awaiting_confirmation=True,
                                pending_action_id=pending_action_id,
                                prior_action_id=action_id,
                                iters=iters,
                                stop_reason=stop_reason,
                            )
                            return AgentResponse(
                                response=description,
                                awaiting_confirmation=True,
                                pending_action_id=pending_action_id,
                            )

                        tool_results = []
                        for call, confidence, reasoning, result in self._execute_tool_batch(auto_execute, gate_info):
                            items_referenced.extend(result.get("_items", []))
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": call["id"],
                                "content": json.dumps(result),
                            })
                            tools_audit.append({
                                "name": call["name"],
                                "params": _sanitize_params(call["input"]),
                                "confidence": confidence,
                                "reasoning": reasoning,
                                "result_summary": _summarize_result(result) if isinstance(result, dict) else None,
                                "confirmed": False,
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

        _otel_trace.get_current_span().set_attribute(
            SpanAttributes.METADATA,
            json.dumps({
                "iters": iters,
                "stop_reason": stop_reason,
                "tools_used": [t["name"] for t in tools_audit],
            }),
        )

        self._emit_turn_audit(
            chat_id=chat_id,
            user_text=original_text,
            tools_audit=tools_audit,
            assistant_text=assistant_text,
            items_referenced=items_referenced,
            awaiting_confirmation=False,
            pending_action_id=None,
            prior_action_id=action_id,
            iters=iters,
            stop_reason=stop_reason,
        )
        return AgentResponse(response=assistant_text)

    def _emit_turn_audit(
        self,
        *,
        chat_id: int,
        user_text: str,
        tools_audit: list[dict],
        assistant_text: str,
        items_referenced: list[str],
        awaiting_confirmation: bool,
        pending_action_id: str | None,
        prior_action_id: str | None,
        iters: int,
        stop_reason: str | None,
    ) -> None:
        emit_agent_turn({
            "chat_id": chat_id,
            "user_text": user_text,
            "tools": tools_audit,
            "assistant_text": assistant_text,
            "items_referenced": items_referenced,
            "awaiting_confirmation": awaiting_confirmation,
            "pending_action_id": pending_action_id,
            "prior_action_id": prior_action_id,
            "iters": iters,
            "stop_reason": stop_reason,
        })

    # ── Attachments ────────────────────────────────────────────────

    def _save_photo(self, attachment: dict) -> dict | None:
        """Save photo to disk, extract EXIF, write sidecar metadata.json.

        Returns dict with keys: path, exif_location, exif_timestamp, exif_camera.
        Returns None on failure.
        """
        import datetime as dt
        today = dt.date.today().isoformat()
        media_dir = self.media_path / today
        media_dir.mkdir(parents=True, exist_ok=True)

        filename = attachment.get("filename", f"photo_{today}.jpg")
        file_path = media_dir / filename

        try:
            photo_bytes = base64.b64decode(attachment["data"])
            with fs_span("write", file_path, "media") as span:
                span.set_attribute("fs.bytes", len(photo_bytes))
                file_path.write_bytes(photo_bytes)
            rel_path = str(file_path.relative_to(self.media_path.parent.parent))
        except Exception as e:
            logger.error(f"Failed to save photo: {e}")
            return None

        # Extract EXIF metadata
        from src.services.exif_service import extract_exif_metadata
        exif = extract_exif_metadata(photo_bytes)

        # Use Telegram message timestamp as fallback when EXIF is stripped
        timestamp = exif.get("timestamp")
        if not timestamp and attachment.get("telegram_date"):
            timestamp = attachment["telegram_date"]

        # Write/append to sidecar metadata.json
        meta_path = media_dir / "metadata.json"
        entries = []
        if meta_path.exists():
            try:
                entries = json.loads(meta_path.read_text())
            except Exception:
                entries = []

        entries.append({
            "filename": filename,
            "path": rel_path,
            "saved_at": dt.datetime.now().isoformat(),
            "exif_timestamp": timestamp,
            "exif_location": exif.get("location"),
            "exif_camera": exif.get("camera"),
        })
        meta_payload = json.dumps(entries, indent=2)
        with fs_span("write", meta_path, "media") as span:
            span.set_attribute("fs.bytes", len(meta_payload.encode("utf-8")))
            meta_path.write_text(meta_payload)

        return {
            "path": rel_path,
            "exif_location": exif.get("location"),
            "exif_timestamp": timestamp,
            "exif_camera": exif.get("camera"),
        }

    def _build_user_content(
        self,
        text: str,
        attachments: list[dict] | None = None,
        reply_to: dict | None = None,
        forwarded_from: dict | None = None,
    ) -> str | list[dict]:
        """Build user message content, potentially with image blocks for vision."""
        text_parts: list[str] = []
        image_blocks: list[dict] = []

        if attachments:
            for att in attachments:
                if att["type"] == "photo" and att.get("data"):
                    # Save photo to disk + extract EXIF
                    photo_info = self._save_photo(att)

                    # Add image block for Claude vision
                    image_blocks.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": att.get("mime_type", "image/jpeg"),
                            "data": att["data"],
                        },
                    })

                    if photo_info:
                        parts = [f"Photo saved to: {photo_info['path']}"]
                        loc = photo_info.get("exif_location")
                        ts = photo_info.get("exif_timestamp")
                        cam = photo_info.get("exif_camera")
                        if loc:
                            parts.append(f"EXIF GPS: {loc['lat']}, {loc['lng']}")
                        if ts:
                            parts.append(f"taken {ts}")
                        if cam:
                            parts.append(f"Camera: {cam}")
                        text_parts.append(f"[{' | '.join(parts)}]")
                    else:
                        text_parts.append("[Photo attachment failed to save]")

                elif att["type"] == "location":
                    lat = att.get("latitude", 0)
                    lng = att.get("longitude", 0)
                    loc_str = f"[Location: {lat}, {lng}]"
                    if att.get("title"):
                        loc_str = f"[Location: {lat}, {lng} — {att['title']}]"
                    text_parts.append(loc_str)

        if reply_to:
            from_role = reply_to.get("from", "user")
            text_parts.append(f'[Replying to {from_role}: "{reply_to["text"]}"]')

        if forwarded_from:
            text_parts.append(
                f'[Forwarded from {forwarded_from["from_name"]}: "{forwarded_from["text"]}"]'
            )

        if text:
            text_parts.append(text)

        combined_text = "\n".join(text_parts)

        # If there are image blocks, return multi-content list
        if image_blocks:
            content: list[dict] = list(image_blocks)
            content.append({"type": "text", "text": combined_text})
            return content

        return combined_text

    # ── Helpers ───────────────────────────────────────────────────

    # ── Prompt construction ───────────────────────────────────────

    @staticmethod
    def _static_guidelines() -> list[str]:
        """Parts of the system prompt that are identical across every turn.

        These lines are placed in the cacheable static prefix so that Anthropic
        prompt caching can avoid re-charging input tokens on repeated requests
        within the same conversation.
        """
        return [
            "You are Mazkir, a personal AI assistant for managing tasks, habits, goals, and knowledge.",
            "",
            "## Tools",
            "You have tools to manage tasks, habits, goals, calendar, and knowledge.",
            "Call tools as needed. You can call multiple tools in sequence.",
            "For every write or destructive tool call, include _confidence (0.0-1.0) and _reasoning fields.",
            "_confidence reflects how sure you are this is the right action. Be honest.",
            "",
            "## Tool responses",
            "Every tool returns either:",
            '  - success: {"ok": true, "data": {...}, "_items": [...]}',
            '  - error:   {"ok": false, "error": {"code": "...", "message": "...", "details": {...}}, "_items": []}',
            "",
            "Error codes (what to do):",
            "  - PATH_NOT_FOUND: target name/path doesn't match anything. Ask the user to clarify or rephrase.",
            "  - AMBIGUOUS_MATCH: multiple candidates close in score. Inspect details.candidates and either ask the user or pick one explicitly by path.",
            "  - SCHEMA_INVALID: your tool call had wrong fields or types. Re-emit with the correct schema.",
            "  - STATE_CONFLICT: target changed since you read it. Re-read and try again.",
            "  - ALREADY_DONE: the action is a no-op (item already in the desired state). Tell the user; do not retry.",
            "  - EXTERNAL_FAILURE: integration error (e.g. GCal). Mention the failure to the user; do not retry blindly.",
            "  - AUTH_REQUIRED: a permission step the user hasn't completed. Surface to the user.",
            "  - CANCELLED_BY_USER: confirmation flow returned no. Move on; do not retry the same action.",
            "",
            "## Guidelines",
            "- Be concise and friendly",
            "- Use Telegram markdown: *bold*, _italic_, `monospace`",
            "- When completing items, report tokens earned and streak updates",
            "- When unsure which item the user means, ask — don't guess with low confidence",
            "- Save important facts the user shares using save_knowledge",
            "- Reference specific item names when discussing tasks/habits/goals",
            "- When the user sends a photo, you can SEE the image (vision). Describe what you see if relevant.",
            "- Use list_events to check today's events before deciding how to handle a photo",
            "- Use attach_photo_to_event to link a photo to an existing event, or create_event for a new one",
            "- Use attach_to_daily only for simple logging (screenshots, memes, non-event photos)",
            "- When a location is provided, include it when attaching to daily note",
            "- Reply context [Replying to ...] shows what message the user is responding to — use it for context",
            "- Forward context [Forwarded from ...] shows forwarded messages — treat as shared information",
        ]

    def _build_static_prefix(self, skill=None) -> str:
        """Return the cacheable static prefix for the system prompt.

        The prefix contains the skill's own system prompt (if any) followed by
        the base guidelines that are identical across every conversation turn.
        Because this text never changes within a conversation it is a perfect
        candidate for Anthropic prompt caching.

        Args:
            skill: Optional Skill object whose ``system_prompt`` is prepended.

        Returns:
            Plain string to be passed as ``cache_static_prefix`` to
            ``ClaudeService.create``.
        """
        parts: list[str] = []
        if skill is not None:
            parts.append(skill.system_prompt)
            parts.append("")
        parts.extend(self._static_guidelines())
        return "\n".join(parts)

    def _build_system_prompt(self, context) -> str:
        """Build the dynamic system prompt tail (current date + vault snapshot).

        This is the portion of the system prompt that changes each turn.  It is
        kept separate from the static prefix so the static prefix can be cached
        by Anthropic's prompt caching feature.
        """
        import datetime
        now = datetime.datetime.now()

        parts = [
            f"Current date/time: {now.strftime('%Y-%m-%d %H:%M')}",
            "",
            "## Current vault state",
            context.vault_snapshot,
        ]

        if context.knowledge:
            parts.extend(["", "## Relevant knowledge", context.knowledge])

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

    def _execute_tool(
        self,
        name: str,
        params: dict,
        *,
        confidence: float | None = None,
        action: str | None = None,
    ) -> dict:
        entry = self.tools.get(name, {})
        risk = entry.get("risk", "unknown")
        schema = entry.get("schema", {}) or {}
        _tool_input_str = json.dumps(_sanitize_params(params))[:2000]
        attrs: dict[str, Any] = {
            SpanAttributes.OPENINFERENCE_SPAN_KIND: "TOOL",
            SpanAttributes.TOOL_NAME: name,
            SpanAttributes.INPUT_VALUE: _tool_input_str,
            SpanAttributes.INPUT_MIME_TYPE: "application/json",
            "tool.risk": risk,
        }
        if len(json.dumps(_sanitize_params(params))) > 2000:
            attrs["truncated"] = True
        if schema.get("description"):
            attrs[SpanAttributes.TOOL_DESCRIPTION] = schema["description"]
        if schema.get("input_schema"):
            attrs[SpanAttributes.TOOL_PARAMETERS] = json.dumps(schema["input_schema"])
        with _tracer.start_as_current_span("agent.tool_call", attributes=attrs) as span:
            with with_span_status(span):
                threshold = entry.get("confidence_threshold")
                span.set_attribute("tool.confidence_threshold", float(threshold) if threshold is not None else 0.0)
                span.set_attribute("tool.confidence_score", float(confidence) if confidence is not None else 1.0)
                span.set_attribute("confirmation.required", action == "needs_confirmation")
                result = self._execute_tool_inner(name, params, risk)
                if isinstance(result, dict):
                    summary = _summarize_result(result)
                    _tool_output_str = json.dumps(summary)[:2000]
                    span.set_attribute(SpanAttributes.OUTPUT_VALUE, _tool_output_str)
                    if len(json.dumps(summary)) > 2000:
                        span.set_attribute("truncated", True)
                    span.set_attribute(SpanAttributes.OUTPUT_MIME_TYPE, "application/json")
            # Option B: with_span_status sets OK on clean exit; override to ERROR
            # when the handler returned an application-level error (ok=False) without
            # raising — so error traces propagate even when no exception was thrown.
            if isinstance(result, dict) and not result.get("ok", True):
                _err_code = result.get("error", {}).get("code", "UNKNOWN") if isinstance(result.get("error"), dict) else "UNKNOWN"
                span.set_status(Status(StatusCode.ERROR, _err_code))
                span.set_attribute("tool.error.code", _err_code)
            return result

    def _execute_tool_inner(self, name: str, params: dict, risk: str) -> dict:
        """Execute a registered tool and return its result.

        Delegates to :func:`src.services.tool_executor.execute_tool` which owns
        the pre-hooks → handler → post-hooks → structured-log pipeline.
        """
        from src.services.tool_executor import execute_tool
        return execute_tool(
            name=name,
            params=params,
            risk=risk,
            tools=self.tools,
            ctx={"vault": self.vault, "memory": self.memory, "calendar": self.calendar},
        )

    def _execute_tool_batch(self, calls: list[dict], gate_info: dict) -> list[tuple[dict, float, str | None, dict]]:
        """Execute a batch of auto_execute tool calls, using parallel dispatch when safe.

        Returns a list of (call, confidence, reasoning, result) tuples in input order.

        When every call in the batch has `safe_for_parallel = True` in the tool registry,
        calls are dispatched concurrently via :func:`parallel_executor.execute_calls_maybe_parallel`.
        Otherwise falls back to serial execution. OTel spans are emitted per-call via
        `_execute_tool`, which is called from each thread.
        """
        import concurrent.futures as _cf
        import asyncio as _asyncio

        if not calls:
            return []

        if len(calls) == 1:
            call = calls[0]
            confidence, reasoning = gate_info[call["id"]]
            result = self._execute_tool(call["name"], call["input"], confidence=confidence, action="auto_execute")
            return [(call, confidence, reasoning, result)]

        all_parallel_safe = all(
            self.tools.get(c["name"], {}).get("safe_for_parallel", False) for c in calls
        )

        if not all_parallel_safe:
            # Serial path
            out = []
            for call in calls:
                confidence, reasoning = gate_info[call["id"]]
                result = self._execute_tool(call["name"], call["input"], confidence=confidence, action="auto_execute")
                out.append((call, confidence, reasoning, result))
            return out

        # Parallel path — each call runs in its own thread with its own OTel span
        logger.info(
            "parallel_executor",
            extra={
                "event_type": "parallel_executor",
                "mode": "parallel",
                "call_count": len(calls),
                "calls": [c["name"] for c in calls],
            },
        )

        # Worker threads start with an empty OTel context, which would make the
        # agent.tool_call spans roots of separate traces. Capture the caller's
        # context and attach it in each worker so spans parent correctly.
        from opentelemetry import context as _otel_context
        parent_otel_ctx = _otel_context.get_current()

        def _run_one(call: dict) -> tuple[dict, float, str | None, dict]:
            token = _otel_context.attach(parent_otel_ctx)
            try:
                confidence, reasoning = gate_info[call["id"]]
                result = self._execute_tool(call["name"], call["input"], confidence=confidence, action="auto_execute")
                return (call, confidence, reasoning, result)
            finally:
                _otel_context.detach(token)

        async def _run_all() -> list[tuple]:
            loop = _asyncio.get_running_loop()
            with _cf.ThreadPoolExecutor(max_workers=len(calls)) as pool:
                tasks = [
                    loop.run_in_executor(pool, lambda c=c: _run_one(c))
                    for c in calls
                ]
                return list(await _asyncio.gather(*tasks))

        try:
            try:
                loop = _asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop is not None and loop.is_running():
                # FastAPI context: nested loop — run in worker thread with its own event loop
                with _cf.ThreadPoolExecutor(max_workers=1) as ex:
                    results = ex.submit(_asyncio.run, _run_all()).result()
            else:
                results = _asyncio.run(_run_all())

            # asyncio.gather preserves task order matching input, so results[i] corresponds to calls[i]
            return results
        except Exception as e:
            logger.warning(
                "parallel_executor: parallel dispatch failed (%s), falling back to serial", e,
                extra={"event_type": "parallel_executor", "mode": "serial_fallback"},
            )
            out = []
            for call in calls:
                confidence, reasoning = gate_info[call["id"]]
                result = self._execute_tool(call["name"], call["input"], confidence=confidence, action="auto_execute")
                out.append((call, confidence, reasoning, result))
            return out

    def _describe_pending_calls(
        self, calls: list[dict], preview_texts: dict[str, str] | None = None
    ) -> str:
        """Build a human-readable description of pending tool calls.

        When a call has an entry in `preview_texts` (keyed by call ID), that
        preview text is shown instead of the raw param list — giving the user
        a friendlier "Would delete task: **X**" summary before they confirm.
        """
        lines = ["I'd like to perform the following actions:\n"]
        for call in calls:
            if preview_texts and call["id"] in preview_texts:
                lines.append(f"  - {preview_texts[call['id']]}")
            else:
                name = call["name"].replace("_", " ")
                params = {k: v for k, v in call["input"].items() if not k.startswith("_")}
                param_str = ", ".join(f"{k}={v}" for k, v in params.items())
                lines.append(f"  - {name}: {param_str}")
        lines.append("\nShould I proceed? (yes/no)")
        return "\n".join(lines)

    # ── Tool Handlers ────────────────────────────────────────────

    def _tool_list_tasks(self, params: dict) -> dict:
        import datetime as dt
        from src.services.daily_tasks import parse_tasks_section

        today = dt.date.today().isoformat()

        # Daily-tier
        try:
            daily = self.vault.read_daily_note(today)
            daily_tasks = parse_tasks_section(daily["content"])
        except Exception:
            daily_tasks = []

        n = 1
        daily_pending = []
        for t in daily_tasks:
            if t.state == "unchecked":
                daily_pending.append({
                    "n": n,
                    "text": t.text,
                    "scheduled_at": t.scheduled_at,
                    "duration_minutes": t.duration_minutes,
                })
                n += 1
        daily_done_today = [
            {"text": t.text} for t in daily_tasks if t.state == "checked"
        ]

        # File-tier
        file_tier = self.vault.list_active_tasks()
        by_priority: dict[int, list] = {}
        overdue: list = []
        for t in file_tier:
            meta = t["metadata"]
            try:
                prio = int(meta.get("priority", 3))
            except (TypeError, ValueError):
                prio = 3
            entry = {
                "path": t["path"],
                "name": meta.get("name", ""),
                "priority": prio,
                "due_date": meta.get("due_date"),
                "scheduled_at": meta.get("scheduled_at"),
                "status": meta.get("status"),
            }
            by_priority.setdefault(prio, []).append(entry)
            if (
                meta.get("due_date")
                and str(meta["due_date"]) < today
                and meta.get("status") == "active"
            ):
                overdue.append({
                    "path": t["path"],
                    "name": meta.get("name", ""),
                    "due_date": str(meta["due_date"]),
                    "priority": prio,
                })

        # Assign sequential numbers to file-tier tasks (high → medium → low, matching UI order)
        for prio in sorted(by_priority.keys(), reverse=True):
            for entry in by_priority[prio]:
                entry["n"] = n
                n += 1

        return ok({
            "daily_pending": daily_pending,
            "daily_done_today": daily_done_today,
            "file_tier_by_priority": by_priority,
            "overdue": overdue,
        }, items=[])

    def _tool_list_habits(self, params: dict) -> dict:
        habits = self.vault.list_active_habits()
        return ok(
            {
                "habits": [
                    {"name": h["metadata"].get("name", ""), "path": h["path"],
                     "streak": h["metadata"].get("streak", 0),
                     "frequency": h["metadata"].get("frequency", "daily")}
                    for h in habits
                ],
            },
            items=[h["path"] for h in habits],
        )

    def _tool_list_goals(self, params: dict) -> dict:
        goals = self.vault.list_active_goals()
        return ok(
            {
                "goals": [
                    {"name": g["metadata"].get("name", ""), "path": g["path"],
                     "progress": g["metadata"].get("progress", 0),
                     "priority": g["metadata"].get("priority")}
                    for g in goals
                ],
            },
            items=[g["path"] for g in goals],
        )

    def _tool_get_daily(self, params: dict) -> dict:
        try:
            daily = self.vault.read_daily_note()
            return ok(
                {"daily": daily["metadata"], "content": daily["content"]},
                items=[daily["path"]],
            )
        except Exception:
            return err(ErrorCode.PATH_NOT_FOUND, "No daily note found for today.")

    def _tool_get_tokens(self, params: dict) -> dict:
        try:
            ledger = self.vault.read_token_ledger()
            return ok({
                "total": ledger["metadata"].get("total_tokens", 0),
                "today": ledger["metadata"].get("tokens_today", 0),
                "all_time": ledger["metadata"].get("all_time_tokens", 0),
            })
        except Exception:
            return err(ErrorCode.PATH_NOT_FOUND, "Token ledger not found.")

    def _tool_search_knowledge(self, params: dict) -> dict:
        results = self.memory.search_knowledge(
            query=params["query"],
            limit=params.get("limit", 5),
        )
        return ok({"results": results})

    def _tool_read_knowledge(self, params: dict) -> dict:
        path = params.get("path")
        name = params.get("name")
        if not path and not name:
            return err(
                ErrorCode.SCHEMA_INVALID,
                "read_knowledge requires 'path' or 'name'.",
            )

        if not path:
            slug = name.lower().strip().replace(" ", "-")
            target = name.lower().strip()
            candidates: list[str] = []
            for subdir in ("60-knowledge/notes", "60-knowledge/insights"):
                for file_path in self.vault.list_files(subdir):
                    rel = str(file_path)
                    stem = file_path.stem.lower() if hasattr(file_path, "stem") else rel.lower()
                    try:
                        data = self.vault.read_file(rel)
                    except FileNotFoundError:
                        continue
                    note_name = data["metadata"].get("name", "").lower()
                    if slug == stem or target == note_name:
                        candidates.append(rel)
            candidates = sorted(set(candidates))
            if not candidates:
                return err(
                    ErrorCode.PATH_NOT_FOUND,
                    f"No knowledge note matching {name!r}.",
                )
            if len(candidates) > 1:
                return err(
                    ErrorCode.AMBIGUOUS_MATCH,
                    f"Multiple knowledge notes match {name!r}.",
                    details={"candidates": candidates},
                )
            path = candidates[0]

        try:
            data = self.vault.read_file(path)
        except FileNotFoundError:
            return err(ErrorCode.PATH_NOT_FOUND, f"Knowledge note not found: {path}")

        meta = data["metadata"]
        return ok(
            {
                "path": data["path"],
                "name": meta.get("name", ""),
                "tags": meta.get("tags", []),
                "content": data["content"],
                "links": meta.get("links", []),
                "source": meta.get("source", ""),
            },
            items=[data["path"]],
        )

    def _tool_get_related(self, params: dict) -> dict:
        results = self.memory.get_related(
            topic=params["topic"],
            depth=params.get("depth", 2),
        )
        return ok({"related": results})

    def _tool_create_task(self, params: dict) -> dict:
        result = self.vault.create_task(
            name=params["name"],
            priority=params.get("priority", 3),
            due_date=params.get("due_date"),
            category=params.get("category", "personal"),
            scheduled_at=params.get("scheduled_at"),
            duration_minutes=params.get("duration_minutes"),
            due_soft=params.get("due_soft"),
            description=params.get("description"),
        )
        return ok(
            {
                "created": result["metadata"]["name"],
                "path": result["path"],
                "priority": result["metadata"].get("priority"),
                "due_date": result["metadata"].get("due_date"),
            },
            items=[result["path"]],
        )

    def _tool_create_habit(self, params: dict) -> dict:
        result = self.vault.create_habit(
            name=params["name"],
            frequency=params.get("frequency", "daily"),
            category=params.get("category", "personal"),
            scheduled_at=params.get("scheduled_at"),
            duration_minutes=params.get("duration_minutes"),
        )
        return ok(
            {
                "created": result["metadata"]["name"],
                "path": result["path"],
                "frequency": result["metadata"].get("frequency"),
            },
            items=[result["path"]],
        )

    def _tool_create_goal(self, params: dict) -> dict:
        result = self.vault.create_goal(
            name=params["name"],
            priority=params.get("priority", "medium"),
            target_date=params.get("target_date"),
            start_date=params.get("start_date"),
        )
        return ok(
            {
                "created": result["metadata"]["name"],
                "path": result["path"],
            },
            items=[result["path"]],
        )

    def _tool_update_task(self, params: dict) -> dict:
        from src.services.resolver import resolve_item

        resolved = resolve_item("task", params["name"], self.vault)
        if not resolved["ok"]:
            return resolved

        path = resolved["data"]["path"]
        current = self.vault.read_file(path)
        meta = dict(current["metadata"])
        body = current["content"]

        history_lines: list[str] = []

        field_map = [
            ("priority", "Priority"),
            ("status", "Status"),
            ("category", "Category"),
            ("scheduled_at", "Scheduled"),
            ("duration_minutes", "Duration (min)"),
            ("due_date", "Due"),
            ("due_soft", "Soft due"),
        ]
        for key, label in field_map:
            if key in params and params[key] != meta.get(key):
                if key == "priority":
                    history_lines.append(
                        f"{label} changed: {_fmt_priority(meta.get(key))} → {_fmt_priority(params[key])}"
                    )
                else:
                    history_lines.append(f"{label} changed: {meta.get(key)} → {params[key]}")
                meta[key] = params[key]

        if "append_note" in params and params["append_note"]:
            body = body.rstrip() + "\n\n" + params["append_note"].strip() + "\n"
            history_lines.append(f"Note appended: {params['append_note'][:60]}")

        from datetime import datetime
        today = datetime.now(self.vault.tz).strftime("%Y-%m-%d")
        if history_lines:
            meta["updated"] = today
            for line in history_lines:
                body = self.vault.append_history_line(body, line)

        self.vault.write_file(path, meta, body)

        return ok(
            {"path": path, "name": meta.get("name", ""), "changes": history_lines},
            items=[path],
        )

    def _tool_update_habit(self, params: dict) -> dict:
        from src.services.resolver import resolve_item

        resolved = resolve_item("habit", params["name"], self.vault)
        if not resolved["ok"]:
            return resolved

        path = resolved["data"]["path"]
        current = self.vault.read_file(path)
        meta = dict(current["metadata"])
        body = current["content"]

        history_lines: list[str] = []
        field_map = [
            ("frequency", "Frequency"),
            ("scheduled_at", "Scheduled at"),
            ("duration_minutes", "Duration (min)"),
            ("tokens_per_completion", "Tokens per completion"),
        ]
        for key, label in field_map:
            if key in params and params[key] != meta.get(key):
                history_lines.append(f"{label} changed: {meta.get(key)} → {params[key]}")
                meta[key] = params[key]

        if "append_note" in params and params["append_note"]:
            body = body.rstrip() + "\n\n" + params["append_note"].strip() + "\n"
            history_lines.append(f"Note appended: {params['append_note'][:60]}")

        from datetime import datetime
        today = datetime.now(self.vault.tz).strftime("%Y-%m-%d")
        if history_lines:
            meta["updated"] = today
            for line in history_lines:
                body = self.vault.append_history_line(body, line)

        self.vault.write_file(path, meta, body)
        return ok(
            {"path": path, "name": meta.get("name", ""), "changes": history_lines},
            items=[path],
        )

    def _tool_update_goal(self, params: dict) -> dict:
        from src.services.resolver import resolve_item

        resolved = resolve_item("goal", params["name"], self.vault)
        if not resolved["ok"]:
            return resolved

        path = resolved["data"]["path"]
        current = self.vault.read_file(path)
        meta = dict(current["metadata"])
        body = current["content"]

        history_lines: list[str] = []
        field_map = [
            ("status", "Status"),
            ("progress", "Progress"),
            ("priority", "Priority"),
            ("start_date", "Start date"),
            ("target_date", "Target date"),
        ]
        for key, label in field_map:
            if key in params and params[key] != meta.get(key):
                history_lines.append(f"{label} changed: {meta.get(key)} → {params[key]}")
                meta[key] = params[key]

        if "append_note" in params and params["append_note"]:
            body = body.rstrip() + "\n\n" + params["append_note"].strip() + "\n"
            history_lines.append(f"Note appended: {params['append_note'][:60]}")

        from datetime import datetime
        today = datetime.now(self.vault.tz).strftime("%Y-%m-%d")
        if history_lines:
            meta["updated"] = today
            for line in history_lines:
                body = self.vault.append_history_line(body, line)

        self.vault.write_file(path, meta, body)
        return ok(
            {"path": path, "name": meta.get("name", ""), "changes": history_lines},
            items=[path],
        )

    def _tool_save_knowledge(self, params: dict) -> dict:
        result = self.memory.save_knowledge(
            name=params["name"],
            content=params["content"],
            tags=params.get("tags", []),
            links=params.get("links", []),
            source="conversation",
        )
        return ok({"saved": result["path"]}, items=[result["path"]])

    def _tool_attach_to_daily(self, params: dict) -> dict:
        import datetime as dt
        vault_path = params["vault_path"]
        caption = params["caption"]
        wikilinks = params.get("wikilinks", [])
        location = params.get("location")
        section = params.get("section", "Notes")
        date = params.get("date")

        now = dt.datetime.now()
        time_str = now.strftime("%H:%M")

        # Build markdown content block
        from pathlib import Path
        filename = Path(vault_path).name
        lines = []
        lines.append(f"![[{filename}]]")
        meta_parts = [f"*{time_str} — {caption}*"]
        if wikilinks:
            meta_parts.append(" | ".join(f"[[{link}]]" for link in wikilinks))
        lines.append(" | ".join(meta_parts))
        if location:
            lat, lng = location["lat"], location["lng"]
            label = location.get("name") or "Map"
            map_url = f"https://www.google.com/maps?q={lat},{lng}"
            lines.append(f"\U0001f4cd [{label}]({map_url})")

        content = "\n".join(lines)

        result = self.vault.append_to_daily_section(section=section, content=content, date=date)
        daily_path = result.get("path", self.vault.get_daily_note_path())

        return ok(
            {
                "path": daily_path,
                "section": section,
                "attachment": vault_path,
            },
            items=[daily_path],
        )

    def _tool_delete_task(self, params: dict) -> dict:
        from src.services.resolver import resolve_item

        resolved = resolve_item("task", params["task_name"], self.vault)
        if not resolved["ok"]:
            return resolved

        path = resolved["data"]["path"]
        task = self.vault.read_file(path)
        self.vault.delete_file(path)
        return ok({"deleted": task["metadata"].get("name", "")}, items=[path])

    def _tool_archive_task(self, params: dict) -> dict:
        from src.services.resolver import resolve_item

        resolved = resolve_item("task", params["task_name"], self.vault)
        if not resolved["ok"]:
            return resolved

        path = resolved["data"]["path"]
        result = self.vault.archive_task(path)
        return ok(
            {
                "task": result["task_name"],
                "archived_to": result["archive_path"],
            },
            items=[result["archive_path"]],
        )

    def _tool_delete_habit(self, params: dict) -> dict:
        from src.services.resolver import resolve_item

        resolved = resolve_item("habit", params["habit_name"], self.vault)
        if not resolved["ok"]:
            return resolved

        path = resolved["data"]["path"]
        habit = self.vault.read_file(path)
        self.vault.delete_file(path)
        return ok({"deleted": habit["metadata"].get("name", "")}, items=[path])

    def _tool_archive_goal(self, params: dict) -> dict:
        from src.services.resolver import resolve_item

        resolved = resolve_item("goal", params["goal_name"], self.vault)
        if not resolved["ok"]:
            return resolved

        path = resolved["data"]["path"]
        goal = self.vault.read_file(path)
        if goal["metadata"].get("status") == "archived":
            return err(
                ErrorCode.ALREADY_DONE,
                f"Goal '{goal['metadata'].get('name', '')}' is already archived",
                details={"path": path},
            )
        self.vault.update_file(path, {"status": "archived"})
        return ok({"archived": goal["metadata"].get("name", "")}, items=[path])

    def _parse_date(self, date_str: str | None):
        """Parse YYYY-MM-DD string to datetime or None for today."""
        if not date_str:
            return None
        import datetime as dt
        return dt.datetime.fromisoformat(date_str)

    def _tool_read_daily_section(self, params: dict) -> dict:
        date = self._parse_date(params.get("date"))
        content = self.vault.read_daily_section(params["section"], date)
        return ok({"section": params["section"], "content": content})

    def _tool_edit_daily_section(self, params: dict) -> dict:
        date = self._parse_date(params.get("date"))
        result = self.vault.replace_daily_section(
            section=params["section"],
            new_content=params["content"],
            date=date,
        )
        return ok(
            {"path": result["path"], "section": result["section"]},
            items=[result["path"]],
        )

    def _tool_daily_add_task(self, params: dict) -> dict:
        from src.services.tool_handlers.daily import daily_add_task
        return daily_add_task(self.vault, params)

    def _tool_daily_set_task_state(self, params: dict) -> dict:
        from src.services.tool_handlers.daily import daily_set_task_state
        return daily_set_task_state(self.vault, params)

    def _tool_daily_rollover(self, params: dict) -> dict:
        from src.services.tool_handlers.daily import daily_rollover
        return daily_rollover(self.vault, params)

    def _tool_promote_daily_task(self, params: dict) -> dict:
        from src.services.tool_handlers.daily import promote_daily_task
        return promote_daily_task(self.vault, params)

    def _tool_list_events(self, params: dict) -> dict:
        import datetime as dt
        date = params.get("date", dt.date.today().isoformat())
        if not self.events:
            return err(ErrorCode.EXTERNAL_FAILURE, "Events service not available")
        events = self.events.get_events(date)
        summary = []
        for e in events:
            summary.append({
                "id": e["id"],
                "name": e["name"],
                "type": e.get("type", "unknown"),
                "start_time": e.get("start_time"),
                "end_time": e.get("end_time"),
                "location": e.get("location"),
                "photo_count": len(e.get("photos", [])),
                "source": e.get("source"),
            })
        return ok({"events": summary, "date": date})

    def _tool_attach_photo_to_event(self, params: dict) -> dict:
        if not self.events:
            return err(ErrorCode.EXTERNAL_FAILURE, "Events service not available")
        # date is an optional hint — attach_photo locates the event by ID across
        # all date files when it's omitted or doesn't match.
        date = params.get("date")
        result = self.events.attach_photo(
            date=date,
            event_id=params["event_id"],
            photo_path=params["photo_path"],
            caption=params.get("caption"),
            wikilinks=params.get("wikilinks"),
        )
        if "error" in result:
            return err(ErrorCode.PATH_NOT_FOUND, result["error"], details={"event_id": params["event_id"]})
        resolved_date = result.get("date")
        items = [str(self.events._file_path(resolved_date))] if resolved_date else []
        return ok(result, items=items)

    def _tool_create_event(self, params: dict) -> dict:
        import datetime as dt
        if not self.events:
            return err(ErrorCode.EXTERNAL_FAILURE, "Events service not available")
        date = params.get("date", dt.date.today().isoformat())

        def _normalize_time(t: str | None) -> str | None:
            if not t:
                return t
            # Time-only like "18:34" → "2026-03-06T18:34:00"
            if "T" not in t and len(t) <= 5:
                return f"{date}T{t}:00"
            return t

        start_time = _normalize_time(params["start_time"])
        end_time = _normalize_time(params.get("end_time"))

        # Extract HH:MM for GCal (strip date prefix if present)
        def _extract_hhmm(iso_time: str | None) -> str | None:
            if not iso_time:
                return None
            if "T" in iso_time:
                return iso_time.split("T")[1][:5]
            return iso_time[:5]

        # Sync to Google Calendar if available
        source_ids: dict | None = None
        calendar_synced = False
        if self.calendar and not params.get("photo_path"):
            try:
                import asyncio
                coro = self.calendar.create_event(
                    name=params["name"],
                    date=date,
                    start_time=_extract_hhmm(start_time),
                    end_time=_extract_hhmm(end_time),
                )
                try:
                    loop = asyncio.get_running_loop()
                    # Already in an async context — create a task
                    import concurrent.futures
                    future = concurrent.futures.Future()
                    async def _run():
                        try:
                            future.set_result(await coro)
                        except Exception as exc:
                            future.set_exception(exc)
                    loop.create_task(_run())
                    gcal_id = future.result(timeout=30)
                except RuntimeError:
                    # No running loop — use asyncio.run
                    gcal_id = asyncio.run(coro)
                if gcal_id:
                    source_ids = {"calendar_id": gcal_id}
                    calendar_synced = True
            except Exception as e:
                logger.warning(f"Failed to sync event to Google Calendar: {e}")

        result = self.events.create_event(
            date=date,
            name=params["name"],
            start_time=start_time,
            end_time=end_time,
            location=params.get("location"),
            category=params.get("category"),
            photo_path=params.get("photo_path"),
            caption=params.get("caption"),
            wikilinks=params.get("wikilinks"),
            source_ids=source_ids,
        )
        result["event_id"] = result.pop("id")
        items = [result["path"]]
        if calendar_synced:
            result["calendar_synced"] = True

        # Unified record: also log the event in the daily note's ## Schedule section.
        # Best-effort — a failure here never invalidates the events-store write.
        if not params.get("photo_path"):
            try:
                from src.services.daily_schedule import (
                    ScheduleEntry,
                    parse_schedule_section,
                    render_schedule_section,
                )
                from src.services.daily_tasks import replace_or_append_section

                text = params["name"]
                loc = params.get("location") or {}
                if loc.get("name"):
                    text = f"{text} @ {loc['name']}"
                for link in params.get("wikilinks") or []:
                    text = f"{text} [[{link}]]"

                daily = self.vault.read_daily_note(date)
                body = daily["content"]
                entries = parse_schedule_section(body)
                entries.append(
                    ScheduleEntry(
                        start=_extract_hhmm(start_time),
                        end=_extract_hhmm(end_time),
                        text=text,
                    )
                )
                new_section = render_schedule_section(entries)
                new_body = replace_or_append_section(body, "Schedule", new_section)
                self.vault.write_daily_note(date, new_body)
                daily_path = f"10-daily/{date}.md"
                items.append(daily_path)
                result["daily_note"] = daily_path
            except Exception as e:
                logger.warning(f"Failed to write event to daily note: {e}")

        return ok(result, items=items)

    def _tool_update_event(self, params: dict) -> dict:
        import datetime as dt
        if not self.events:
            return err(ErrorCode.EXTERNAL_FAILURE, "Events service not available")
        date = params.get("date", dt.date.today().isoformat())

        def _normalize_time(t: str | None) -> str | None:
            if not t:
                return t
            if "T" not in t and len(t) <= 5:
                return f"{date}T{t}:00"
            return t

        updates = {}
        if "name" in params:
            updates["name"] = params["name"]
        if "start_time" in params:
            updates["start_time"] = _normalize_time(params["start_time"])
        if "end_time" in params:
            updates["end_time"] = _normalize_time(params["end_time"])
        if "location" in params:
            updates["location"] = params["location"]
        if "category" in params:
            updates["activity_category"] = params["category"]

        result = self.events.update_event(
            date=date,
            event_id=params["event_id"],
            updates=updates,
        )
        if "error" in result:
            return err(ErrorCode.PATH_NOT_FOUND, result["error"], details={"event_id": params["event_id"]})
        items = [str(self.events._file_path(date))]
        return ok(result, items=items)

    def _tool_complete_task(self, params: dict) -> dict:
        from src.services.resolver import resolve_item

        resolved = resolve_item("task", params["task_name"], self.vault)
        if not resolved["ok"]:
            return resolved

        path = resolved["data"]["path"]
        task = self.vault.read_file(path)

        if task["metadata"].get("status") == "done":
            return err(
                ErrorCode.ALREADY_DONE,
                f"Task '{task['metadata'].get('name', '')}' is already done",
                details={"path": path},
            )

        result = self.vault.complete_task(path)
        name = result["task_name"]
        tokens = result["tokens_earned"]
        archive_path = result["archive_path"]

        if self.calendar and task["metadata"].get("google_event_id"):
            try:
                self.calendar.mark_event_complete(task["metadata"]["google_event_id"])
            except Exception as e:
                logger.warning(f"Calendar update failed: {e}")

        return ok(
            {
                "task": name,
                "tokens_earned": tokens,
                "archived_to": archive_path,
            },
            items=[archive_path],
        )

    def _tool_complete_habit(self, params: dict) -> dict:
        import datetime as dt
        from src.services.resolver import resolve_item

        resolved = resolve_item("habit", params["habit_name"], self.vault)
        if not resolved["ok"]:
            return resolved

        path = resolved["data"]["path"]
        habit = self.vault.read_file(path)

        today = dt.date.today().isoformat()
        if habit["metadata"].get("last_completed") == today:
            return err(
                ErrorCode.ALREADY_DONE,
                f"Habit '{habit['metadata'].get('name', '')}' already completed today",
                details={"path": path, "streak": habit["metadata"].get("streak", 0)},
            )

        meta = habit["metadata"]
        old_streak = meta.get("streak", 0)
        new_streak = old_streak + 1
        longest = max(meta.get("longest_streak", 0), new_streak)

        self.vault.update_file(path, {
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

        return ok(
            {
                "habit": meta.get("name", ""),
                "old_streak": old_streak,
                "new_streak": new_streak,
                "longest_streak": longest,
                "tokens_earned": tokens,
            },
            items=[path],
        )
