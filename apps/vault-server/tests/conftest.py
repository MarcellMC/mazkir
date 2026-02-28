import pytest
from pathlib import Path
from src.services.vault_service import VaultService


# --- Template contents (copied from memory/00-system/templates/) ---

TASK_TEMPLATE = """\
---
type: task
name: "{{title}}"
status: active
priority: 3
due_date: null
category: personal
tags: [task]
tokens_on_completion: 5
google_event_id: null
created: "{{date}}"
updated: "{{date}}"
---

# {{title}}

## Description


## Checklist
- [ ]

## Notes
"""

HABIT_TEMPLATE = """\
---
type: habit
name: "{{title}}"
frequency: daily
streak: 0
longest_streak: 0
last_completed: null
status: active
category: personal
difficulty: medium
tokens_per_completion: 5
google_event_id: null
scheduled_time: null
scheduled_days: []
tags: [habit]
created: "{{date}}"
updated: "{{date}}"
---

# {{title}}

## Goal


## Schedule


## Completion Log


## Notes
"""

GOAL_TEMPLATE = """\
---
type: goal
name: "{{title}}"
status: not-started
priority: medium
start_date: "{{date}}"
target_date: null
progress: 0
category: personal
tags: [goal]
milestones: []
related_tasks: []
created: "{{date}}"
updated: "{{date}}"
---

# {{title}}

## Why This Matters


## Success Criteria
- [ ]

## Milestones

### 1. First Milestone
**Due:**
**Status:** Not Started

- [ ]

## Related Tasks


## Resources


## Notes
"""

DAILY_TEMPLATE = """\
---
type: daily
date: "{{date}}"
day_of_week: "{{day}}"
tokens_earned: 0
tokens_total: 0
mood: null
energy: null
completed_habits: []
tags: [daily]
created: "{{date}}"
updated: "{{date}}"
---

# {{day_full}}, {{date_formatted}}

## Tokens Today: 0
**Total Bank:** 0 tokens

## Daily Habits
- [ ] Review Email
- [ ] Review Browser Tabs

## Tasks
- [ ]

## Notes
"""


def _write(path: Path, content: str):
    """Helper to create a file with parent dirs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture
def vault_path(tmp_path):
    """Create a temporary vault directory with templates and sample files."""
    vault = tmp_path / "vault"
    vault.mkdir()

    # Required: AGENTS.md
    _write(vault / "AGENTS.md", "# Agents\n")

    # Templates
    templates = vault / "00-system" / "templates"
    _write(templates / "_task_.md", TASK_TEMPLATE)
    _write(templates / "_habit_.md", HABIT_TEMPLATE)
    _write(templates / "_goal_.md", GOAL_TEMPLATE)
    _write(templates / "_daily_.md", DAILY_TEMPLATE)

    # Token ledger
    _write(vault / "00-system" / "motivation-tokens.md", """\
---
type: system
total_tokens: 50
tokens_today: 10
all_time_tokens: 50
created: '2026-01-01'
updated: '2026-01-01'
---

# Motivation Tokens Ledger
""")

    # Sample active tasks (varying priorities and due dates)
    _write(vault / "40-tasks" / "active" / "buy-groceries.md", """\
---
type: task
name: Buy groceries
status: active
priority: 3
due_date: '2026-03-01'
category: personal
tokens_on_completion: 5
google_event_id: null
created: '2026-02-20'
updated: '2026-02-20'
---

# Buy groceries
""")

    _write(vault / "40-tasks" / "active" / "finish-report.md", """\
---
type: task
name: Finish report
status: active
priority: 5
due_date: '2026-02-28'
category: work
tokens_on_completion: 25
google_event_id: null
created: '2026-02-15'
updated: '2026-02-15'
---

# Finish report
""")

    _write(vault / "40-tasks" / "active" / "learn-rust.md", """\
---
type: task
name: Learn Rust basics
status: active
priority: 2
due_date: null
category: learning
tokens_on_completion: 10
google_event_id: null
created: '2026-02-10'
updated: '2026-02-10'
---

# Learn Rust basics
""")

    # Archive dir (empty)
    (vault / "40-tasks" / "archive").mkdir(parents=True)

    # Sample habits
    _write(vault / "20-habits" / "workout.md", """\
---
type: habit
name: Workout
frequency: 3x/week
streak: 5
longest_streak: 8
last_completed: '2026-02-27'
status: active
category: health
difficulty: medium
tokens_per_completion: 15
google_event_id: evt-123
tags: [habit, health]
created: '2026-02-01'
updated: '2026-02-27'
---

# Workout
""")

    _write(vault / "20-habits" / "read-book.md", """\
---
type: habit
name: Read book
frequency: daily
streak: 0
longest_streak: 3
last_completed: '2026-02-20'
status: active
category: learning
difficulty: easy
tokens_per_completion: 5
google_event_id: null
tags: [habit, learning]
created: '2026-02-01'
updated: '2026-02-20'
---

# Read book
""")

    _write(vault / "20-habits" / "old-habit.md", """\
---
type: habit
name: Old habit
frequency: daily
streak: 0
longest_streak: 0
last_completed: null
status: inactive
category: personal
difficulty: easy
tokens_per_completion: 5
google_event_id: null
tags: [habit]
created: '2026-01-01'
updated: '2026-01-01'
---

# Old habit
""")

    # Sample goals
    (vault / "30-goals" / "2026").mkdir(parents=True)
    _write(vault / "30-goals" / "2026" / "get-fit.md", """\
---
type: goal
name: Get fit
status: in-progress
priority: high
start_date: '2026-01-01'
target_date: '2026-06-01'
progress: 30
category: health
tags: [goal, health]
milestones: []
related_tasks: []
created: '2026-01-01'
updated: '2026-02-20'
---

# Get fit
""")

    _write(vault / "30-goals" / "2026" / "learn-python.md", """\
---
type: goal
name: Learn Python
status: not-started
priority: medium
start_date: '2026-02-01'
target_date: '2026-12-31'
progress: 0
category: learning
tags: [goal, learning]
milestones: []
related_tasks: []
created: '2026-02-01'
updated: '2026-02-01'
---

# Learn Python
""")

    _write(vault / "30-goals" / "2026" / "done-goal.md", """\
---
type: goal
name: Done goal
status: completed
priority: low
progress: 100
category: personal
tags: [goal]
milestones: []
related_tasks: []
created: '2026-01-01'
updated: '2026-02-15'
---

# Done goal
""")

    # Daily notes dir
    (vault / "10-daily").mkdir(parents=True)

    return vault


@pytest.fixture
def vault_service(vault_path):
    """Create a VaultService instance pointing at the temp vault."""
    return VaultService(vault_path)
