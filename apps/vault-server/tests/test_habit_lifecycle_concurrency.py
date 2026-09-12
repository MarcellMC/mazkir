"""The reported bug, end to end: a habit is created and does not appear in
`list_habits`, and a logged completion awards no tokens.

Both traced back to concurrency in the agent's own tool batch rather than to
anything in the habit code. Every other agent test mocks the vault, so the
tool handlers had never been driven against a real one — which is exactly
where these live.

The two mechanisms, each pinned below:

1. `write_file` truncated in place, so a reader could observe a zero-length
   or half-written note. `frontmatter` parses both as `metadata == {}`
   instead of raising, and `list_active_habits` filters on
   `status == 'active'` — so a torn read silently dropped the habit, with
   `create_habit` still returning `ok: true`.
2. `complete_task` / `complete_habit` were marked `safe_for_parallel` on the
   premise that file-tier writes touch distinct paths. They do not: awarding
   tokens read-modify-writes two files every completion shares.
"""

import threading

import pytest
from unittest.mock import MagicMock

from src.services import habit_completion
from src.services.agent_service import AgentService
from src.services.memory_service import ConversationContext


@pytest.fixture
def agent(vault_service, tmp_path):
    """An AgentService wired to a *real* VaultService."""
    memory = MagicMock()
    memory.assemble_context.return_value = ConversationContext(
        messages=[], summary="", vault_snapshot="", knowledge="",
    )
    calendar = MagicMock()
    calendar.is_initialized = False
    return AgentService(
        claude=MagicMock(), vault=vault_service, memory=memory,
        calendar=calendar, events=MagicMock(), media_path=tmp_path / "media",
    )


def _run(agent, name, params):
    return agent._execute_tool(name, params, confidence=0.99, action="auto_execute")


def _batch(agent, calls):
    return agent._execute_tool_batch(calls, {c["id"]: (0.99, None) for c in calls})


def _total_tokens(vault):
    return vault.read_token_ledger()["metadata"]["total_tokens"]


# ── The task's acceptance check, on the real tool path ───────────────────


def test_created_habit_appears_in_list_habits(agent):
    created = _run(agent, "create_habit", {"name": "Meditate", "frequency": "daily"})
    assert created["ok"], created

    listed = _run(agent, "list_habits", {})
    assert listed["ok"], listed
    assert "Meditate" in [h["name"] for h in listed["data"]["habits"]]


def test_logging_a_completion_awards_tokens(agent, vault_service):
    _run(agent, "create_habit", {"name": "Meditate", "frequency": "daily"})
    before = _total_tokens(vault_service)

    out = _run(agent, "complete_habit", {"habit_name": "Meditate"})

    assert out["ok"], out
    assert out["data"]["tokens_earned"] > 0
    assert _total_tokens(vault_service) == before + out["data"]["tokens_earned"]


# ── Mechanism 1: writes are atomic, so a reader never sees a torn note ──


def test_write_file_never_exposes_a_truncated_file(vault_service, vault_path):
    """A reader polling during repeated writes must never see a short file.

    This is the failure that made a created habit invisible: `open(path, 'w')`
    truncates before it writes, and the gap is wide enough to lose a note from
    a concurrently-built list.
    """
    path = vault_path / "20-habits" / "workout.md"
    full = len(path.read_bytes())
    short_reads: list[int] = []
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            try:
                size = path.stat().st_size
            except FileNotFoundError:
                short_reads.append(-1)
                continue
            if size < full:
                short_reads.append(size)

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    try:
        body = "x\n" * 100_000
        meta = {"type": "habit", "name": "Workout", "status": "active"}
        for _ in range(30):
            vault_service.write_file("20-habits/workout.md", dict(meta), body)
    finally:
        stop.set()
        t.join(timeout=5)

    assert short_reads == [], f"reader saw {len(short_reads)} truncated states"


def test_temp_files_are_invisible_to_list_files(vault_service, vault_path):
    """The atomic write's scratch file must not be globbed as a habit.

    A `*.md`-matching temp name would make every write briefly add a habit
    with no frontmatter — trading one invisible-note bug for its mirror image.
    """
    vault_service.create_habit(name="Meditate")
    names = {p.name for p in (vault_path / "20-habits").iterdir()}
    assert names == {"workout.md", "read-book.md", "old-habit.md", "meditate.md"}
    assert len(vault_service.list_files("20-habits")) == 4


def test_a_note_with_unreadable_frontmatter_is_logged_not_just_dropped(
    vault_service, vault_path, caplog
):
    """`status: inactive` is a decision; unparseable YAML is a fault."""
    (vault_path / "20-habits" / "torn.md").write_text(
        "---\ntype: habit\nname: Torn\nstat", encoding="utf-8",
    )
    with caplog.at_level("WARNING"):
        names = [h["metadata"].get("name") for h in vault_service.list_active_habits()]

    assert "Torn" not in names
    assert "torn.md" in caplog.text
    # The deliberately-inactive habit stays silent.
    assert "old-habit.md" not in caplog.text


# ── Mechanism 2: every award survives, and completions stay serial ──────


def test_concurrent_awards_do_not_lose_tokens(vault_service):
    """Ten threads, ten awards, one ledger.

    Before `update_tokens` held a lock this both lost updates and, worse, read
    the ledger mid-truncation as empty — taking a 50-token total down to 5.
    """
    before = _total_tokens(vault_service)
    barrier = threading.Barrier(10)

    def award():
        barrier.wait()
        vault_service.update_tokens(3, "habit")

    threads = [threading.Thread(target=award) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    ledger = vault_service.read_token_ledger()["metadata"]
    assert ledger["total_tokens"] == before + 30
    assert ledger["all_time_tokens"] == 50 + 30


def test_completion_tools_are_not_dispatched_in_parallel(agent):
    """Awarding tokens writes two files every completion shares, so the
    `safe_for_parallel` premise ("distinct vault paths") does not hold."""
    for name in ("complete_habit", "complete_task"):
        assert not agent.tools[name]["safe_for_parallel"], name
    # Creates and updates do resolve to distinct paths and stay parallel.
    for name in ("create_habit", "update_habit", "create_task"):
        assert agent.tools[name]["safe_for_parallel"], name


def test_a_batch_of_completions_awards_every_habits_tokens(agent, vault_service):
    """The reported symptom, as the agent produces it: one message asking for
    several habits to be logged arrives as one batch of tool calls."""
    names = ["Meditate", "Stretch", "Journal", "Floss"]
    for n in names:
        _run(agent, "create_habit", {"name": n})
    before = _total_tokens(vault_service)

    results = _batch(agent, [
        {"id": f"c{i}", "name": "complete_habit", "input": {"habit_name": n}}
        for i, n in enumerate(names)
    ])

    claimed = 0
    for call, _, _, result in results:
        assert result["ok"], (call["input"], result)
        claimed += result["data"]["tokens_earned"]

    assert claimed == 4 * 5
    assert _total_tokens(vault_service) == before + claimed


def test_completing_many_habits_concurrently_still_totals_correctly(vault_service):
    """Defence in depth: the completion path reached from two entry points at
    once (the agent tool and `PATCH /habits/{name}`) is not covered by the
    registry flag, only by the lock inside `update_tokens`."""
    paths = [vault_service.create_habit(name=f"Habit {i}")["path"] for i in range(8)]
    before = _total_tokens(vault_service)
    barrier = threading.Barrier(len(paths))

    def complete(path):
        barrier.wait()
        habit_completion.complete_habit(vault_service, path)

    threads = [threading.Thread(target=complete, args=(p,)) for p in paths]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    # 5 tokens per completion, the create_habit default.
    assert _total_tokens(vault_service) == before + 8 * 5


def test_rewriting_a_note_keeps_its_permissions(vault_service, vault_path):
    """`tempfile.mkstemp` creates 0600; the `open(path, 'w')` it replaced kept
    the file's existing mode."""
    import os

    path = vault_path / "20-habits" / "workout.md"
    os.chmod(path, 0o644)

    vault_service.update_file("20-habits/workout.md", {"streak": 6})

    assert path.stat().st_mode & 0o777 == 0o644
