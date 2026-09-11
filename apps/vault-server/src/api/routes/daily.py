"""Daily note API routes — blocks, gaps, coverage, todos and notes for one day."""
import logging
import re
from datetime import date as dt_date, datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
import pytz
from pydantic import BaseModel
from src.auth import verify_api_key
from src.config import settings
from src.services.daily_tasks import parse_all_todos, is_todo_line
from src.services.habit_completion import is_complete_today
from src.services.day_coverage import MINUTES_PER_DAY, day_coverage, minutes_into_day
from src.services.approval import resolve_state
from src.services.gap_proposals import HISTORY_DAYS, propose_for_gap

router = APIRouter(prefix="/daily", tags=["daily"], dependencies=[Depends(verify_api_key)])
logger = logging.getLogger(__name__)

tz = pytz.timezone(settings.vault_timezone)


class DailyBlock(BaseModel):
    """One interval of the day, from the events ledger."""
    id: str
    start: str            # "HH:MM"
    end: str              # "HH:MM"
    title: str
    source: str           # "calendar" | "timeline" | "merged" | "daily-note" | "habit"
    type: str
    completed: bool = False
    activity: str | None = None   # populated by Ship 6
    category: str | None = None   # populated by Ship 6
    # Always set explicitly from `resolve_state` in `_build_blocks_and_coverage`,
    # so this default is unreachable — but it must not name a value the
    # vocabulary no longer contains (services/approval.py).
    state: str = "pending"
    habit_progress: str | None = None  # "1/2" when a daily_target is set


class GapProposal(BaseModel):
    """What probably filled a gap. A question, not an assertion — the row
    renders it with a ✕ beside it, and `days_seen` is shown so the guess can
    be judged rather than trusted."""
    name: str
    days_seen: int


class DailyGap(BaseModel):
    start: str
    end: str
    minutes: int
    # None means "no basis to guess" — the gap asks instead (spec §4.1).
    proposal: GapProposal | None = None


class DailyIncomplete(BaseModel):
    """A block that cannot be drawn on a timeline yet.

    Missing a start or an end, so it has no interval — which is why it is
    its own array rather than a `blocks[]` entry with null fields. It is
    also why it contributes nothing to coverage: the gap it sits inside is
    the prompt to finish it.
    """
    id: str
    title: str
    start: str | None = None      # "HH:MM" when known
    end: str | None = None
    missing: list[str]            # subset of ["start_time", "end_time"]
    source: str


class DayCoverage(BaseModel):
    covered_minutes: int
    unaccounted_minutes: int
    # Minutes since local midnight for today, 1440 for a past day, 0 for a
    # future day. Carries the "is it today" signal for free: the bot needs
    # no timezone comparison at all, since the divider it draws between
    # elapsed and still-to-come rows shows exactly when
    # `0 < elapsed_minutes < 1440`.
    elapsed_minutes: int
    # Two different unions over the same block list (spec §3). `covered` is
    # every drawable block, which is what gaps are computed from — so a `░`
    # row always means nothing is there at all, and can never overlap a
    # pending block. `confirmed` is approved blocks only, and is the only
    # number the weekly readout (Ship 9) may read.
    confirmed_minutes: int = 0
    # Pending time that is not already confirmed. Subtracted rather than
    # counted independently, so two overlapping blocks of different states
    # do not add up to more than the wall clock.
    pending_minutes: int = 0


class DailyNote(BaseModel):
    text: str | None = None
    photo_path: str | None = None
    caption: str | None = None


class DailyTodo(BaseModel):
    text: str
    done: bool = False
    section: str = ""
    scheduled_at: str | None = None
    duration_minutes: int | None = None


class DailyResponse(BaseModel):
    date: str
    tokens_today: int
    tokens_total: int
    blocks: list[DailyBlock]
    gaps: list[DailyGap]
    coverage: DayCoverage
    incomplete: list[DailyIncomplete] = []
    todos: list[DailyTodo]
    notes: list[DailyNote]


def _extract_section(body: str, name: str) -> str:
    pat = re.compile(
        rf"##\s+{re.escape(name)}\s*\n(.*?)(?=^#{{2,}}\s|\Z)",
        re.DOTALL | re.MULTILINE | re.IGNORECASE,
    )
    m = pat.search(body)
    return m.group(1) if m else ""


def _build_todos(content: str, habits: list[dict], for_date: dt_date) -> list[DailyTodo]:
    """Every checkbox in the note that has not been moved away, wherever it
    lives. Checked ones are included too, carrying `done=True`.

    `schedule[]` only carries checkboxes that have a time, so without this
    an untimed todo is parsed and then silently dropped.

    A checkbox naming an active habit is reconciled against that habit's
    real state on `for_date` rather than trusted: `complete_habit` writes
    the habit file and never ticks the note, so the daily template's
    `## Daily Habits` boxes would otherwise sit unticked forever. Completed
    on `for_date` shows as done; not yet completed is omitted, since /habits
    is where outstanding habits belong and /day should not reopen them every
    morning. `for_date` must be the day being viewed, not always today —
    passing today unconditionally showed yesterday's habit todos as today's
    state and made every future date's habit todos vanish.

    Matched on habit name, not on section name, so it holds wherever the
    checkbox was written.
    """
    habit_state = {
        (h.get("metadata", {}).get("name") or "").strip().casefold():
            is_complete_today(h, for_date)
        for h in habits
    }

    todos: list[DailyTodo] = []
    for t in parse_all_todos(content):
        done = t.state == "checked"
        habit_done = habit_state.get(t.text.strip().casefold())
        if habit_done is not None:
            if not habit_done:
                continue
            done = True
        todos.append(DailyTodo(
            text=t.text,
            done=done,
            section=t.section,
            scheduled_at=t.scheduled_at,
            duration_minutes=t.duration_minutes,
        ))
    return todos


def _build_notes(content: str) -> list[DailyNote]:
    """Prose and photos from `## Notes` — checkboxes there are todos, not notes."""
    notes: list[DailyNote] = []
    for line in _extract_section(content, "Notes").splitlines():
        if is_todo_line(line):
            continue
        stripped = line.strip().lstrip("- ").strip()
        if not stripped:
            continue
        img_match = re.match(r"!\[([^\]]*)\]\(([^)]*)\)", stripped)
        if img_match:
            notes.append(DailyNote(
                caption=img_match.group(1) or None,
                photo_path=img_match.group(2) or None,
            ))
        else:
            notes.append(DailyNote(text=stripped))
    return notes


def _end_minutes(timestamp: str, date: str) -> int | None:
    """`minutes_into_day` for a block's *end*, clipped to end-of-day when the
    end falls on a later date.

    Spec §4: "Block spanning midnight → rendered clipped to the day."
    `MergerService` clamps the blocks it builds itself, but a real calendar
    entry (or a manually created event) carries its own end timestamp, and
    `minutes_into_day` returns None for one on the next date — which dropped
    the block entirely. A 22:00→01:00 shift rendered as no blocks at all and
    a single 00:00–24:00 gap: the whole day read as unaccounted. Ship 1
    displayed that event, so dropping it was a regression.

    Only a *later* date clips. An end before `date` is not a span, it is
    corrupt, and None still drops it. Ship 5 owns the second fragment.
    """
    direct = minutes_into_day(timestamp, date)
    if direct is not None:
        return direct
    day_part, sep, _ = timestamp.partition("T")
    if not sep:
        return None
    try:
        if dt_date.fromisoformat(day_part) > dt_date.fromisoformat(date):
            return MINUTES_PER_DAY
    except ValueError:
        return None
    return None


def _block_times(e: dict, date: str) -> tuple[int | None, int | None, str | None, str | None]:
    """Minute offsets for one event, alongside the raw timestamps.

    The raw values are returned too because `minutes_into_day` answers None
    for two different questions — "there is no timestamp" and "the timestamp
    belongs to another day" — and the callers need to tell those apart.
    """
    start_raw = e.get("start_time")
    end_raw = e.get("end_time")
    return (
        minutes_into_day(start_raw or "", date),
        _end_minutes(end_raw or "", date),
        start_raw,
        end_raw,
    )


def _build_incomplete(events: list[dict], date: str) -> list[DailyIncomplete]:
    """Events that belong to `date` but cannot be drawn as blocks.

    `_build_blocks_and_coverage` drops these with a bare `continue`, which is
    Bug A's exact shape: written correctly, parsed correctly, invisible. They
    are reported separately rather than as blocks with null fields because
    they have no interval — nothing to sort by, nothing to measure.
    """
    out: list[DailyIncomplete] = []
    for e in events:
        start, end, start_raw, end_raw = _block_times(e, date)
        if start is not None and end is not None:
            continue
        # A timestamp that is present but belongs to another day is a
        # neighbouring fragment, not an incomplete block — it stays out, or
        # it would appear on a day it does not belong to.
        if start_raw and end_raw:
            continue
        out.append(DailyIncomplete(
            id=e.get("id", ""),
            title=e.get("name", ""),
            start=f"{start // 60:02d}:{start % 60:02d}" if start is not None else None,
            end=f"{end // 60:02d}:{end % 60:02d}" if end is not None else None,
            missing=[f for f, v in (("start_time", start_raw), ("end_time", end_raw)) if not v],
            source=e.get("source") or "",
        ))
    return out


def _build_blocks_and_coverage(
    events: list[dict], date: str, elapsed_minutes: int
) -> tuple[list[DailyBlock], list[DailyGap], DayCoverage]:
    """Turn merged events into the day's timeline, plus its coverage.

    Events that *start* outside `date` are dropped: storage splits at
    midnight, so a neighbouring day's fragment here would distort this
    day's arithmetic. An event that starts on `date` and ends after it is
    clipped to `24:00` rather than dropped — see `_end_minutes`.

    Dismissed events are dropped entirely and the span they occupied becomes
    a gap (spec §2.5): a meeting you skipped means that hour really is
    unaccounted, and the gap is the prompt to say what you did instead.
    """
    blocks: list[DailyBlock] = []
    all_intervals: list[tuple[int, int]] = []
    approved_intervals: list[tuple[int, int]] = []

    for e in events:
        state = resolve_state(e)
        if state == "dismissed":
            continue
        start, end, _, _ = _block_times(e, date)
        if start is None or end is None:
            continue
        habit = e.get("habit") or {}
        target = habit.get("daily_target")
        blocks.append(DailyBlock(
            id=e.get("id", ""),
            start=f"{start // 60:02d}:{start % 60:02d}",
            end=f"{end // 60:02d}:{end % 60:02d}",
            title=e.get("name", ""),
            # `or default`, not `.get(k, default)`: a persisted event can
            # carry an explicit `null` for these keys, and `.get` only
            # supplies its default when the key is absent — an explicit
            # None sails through and 500s the endpoint at the pydantic
            # boundary (`type`/`source`/`state` are non-optional `str`).
            source=e.get("source") or "",
            type=e.get("type") or "",
            # `habit.completed` is the fallback, not the source: it is
            # where completion used to live, so persisted events written
            # before `MergedEvent.completed` existed still carry it there.
            completed=bool(e.get("completed") or habit.get("completed", False)),
            activity=e.get("activity"),
            category=e.get("category"),
            state=state,
            habit_progress=(
                f"{habit.get('completions_today', 0)}/{target}" if target else None
            ),
        ))
        all_intervals.append((start, end))
        if state == "approved":
            approved_intervals.append((start, end))

    blocks.sort(key=lambda b: b.start)

    # Two calls, two unions. Gaps come from the first — over every drawable
    # block — so a gap means nothing is there at all. Were gaps computed
    # from the approved set, every pending block would sit inside a `░` row
    # covering the same span, which is incoherent to read.
    raw_gaps, coverage = day_coverage(all_intervals, elapsed_minutes)
    _approved_gaps, approved_coverage = day_coverage(approved_intervals, elapsed_minutes)

    confirmed = approved_coverage.covered_minutes
    return (
        blocks,
        [DailyGap(start=g.start, end=g.end, minutes=g.minutes) for g in raw_gaps],
        DayCoverage(
            covered_minutes=coverage.covered_minutes,
            unaccounted_minutes=coverage.unaccounted_minutes,
            elapsed_minutes=elapsed_minutes,
            confirmed_minutes=confirmed,
            # Never negative: `confirmed` is a union over a subset of
            # `all_intervals`, so it cannot exceed `covered`.
            pending_minutes=coverage.covered_minutes - confirmed,
        ),
    )


def _load_history(events_svc, target_date: dt_date) -> list[list[dict]]:
    """The `HISTORY_DAYS` date files before `target_date`, most recent first.

    Local reads only — `get_events` returns [] for a missing file, so a short
    history needs no special case. The target's own date is excluded: today's
    blocks are not evidence about what usually happens today.
    """
    return [
        events_svc.get_events((target_date - timedelta(days=offset)).isoformat())
        for offset in range(1, HISTORY_DAYS + 1)
    ]


def _decorate_gaps(
    gaps: list[DailyGap], history: list[list[dict]]
) -> list[DailyGap]:
    """Attach a proposal to each gap that has a basis for one.

    Done here rather than inside `_build_blocks_and_coverage` so that
    function stays pure arithmetic with no service access — the same reason
    `day_coverage.py` takes minute offsets and not events.
    """
    out: list[DailyGap] = []
    for gap in gaps:
        # `minutes_into_day` needs a date only to reject timestamps belonging
        # to another day; gap times are bare "HH:MM", so "" never matches and
        # never rejects. "24:00" is deliberately unparseable (day_coverage
        # emits it for end-of-day) and comes back None rather than raising.
        start = minutes_into_day(gap.start, "")
        end = minutes_into_day(gap.end, "")
        proposal = None
        if start is not None and end is not None:
            found = propose_for_gap(start, end, history)
            if found:
                proposal = GapProposal(**found)
        out.append(gap.model_copy(update={"proposal": proposal}))
    return out


@router.get("", response_model=DailyResponse)
async def get_daily(date: dt_date | None = None):
    """`date` is typed, not a raw string: FastAPI rejects anything that
    isn't a real calendar date with 422 before it ever reaches a filesystem
    path. It used to be `str | None`, and `date`'s only use was interpolated
    straight into `10-daily/{date}.md` and into the events-preview call —
    `?date=../../../../etc/hosts` read an arbitrary file off disk and
    returned its body through notes[]/todos[]. This parameter took no input
    at all before this route grew ?date=, so there was nothing to validate
    before now.
    """
    from src.main import get_vault
    from src.api.routes.events import get_events_preview

    vault = get_vault()
    now = datetime.now(tz)
    today_date = now.date()
    target_date = date or today_date
    target = target_date.isoformat()

    # read_daily_note catches FileNotFoundError internally and returns an
    # empty note rather than raising, so there is no exception here to
    # handle — a missing note for `target` is a legitimate empty day.
    daily = vault.read_daily_note(target)
    content = daily.get("content", "")

    # Blocks come from the events ledger, which owns temporal data. We call
    # a read-only preview rather than the persisting GET /events/{date}:
    # /daily is called on every navigation tap, and persisting on every tap
    # would let browsing a date rewrite data/events/{date}.json for it from
    # whatever the vault looks like *now* — a persisted block for a past
    # date could be silently dropped because a habit was since renamed. We
    # also call the shared merge rather than re-merging here: two
    # implementations of the same merge is how the ordinal bug in the Phase
    # 2 design §7 happened.
    events: list[dict] = []
    try:
        payload = await get_events_preview(target_date)
        events = payload.get("events", [])
    except Exception:
        # A silent [] here would render identically to a genuinely empty
        # day — log it so a failing events service doesn't look like the
        # user did nothing.
        logger.warning(
            "GET /daily?date=%s: fetching events failed, showing no blocks",
            target, exc_info=True,
        )

    if target_date < today_date:
        elapsed = 24 * 60
    elif target_date > today_date:
        elapsed = 0
    else:
        elapsed = now.hour * 60 + now.minute

    blocks, gaps, coverage = _build_blocks_and_coverage(events, target, elapsed)
    incomplete = _build_incomplete(events, target)

    # Gap proposals read the persisted store for previous dates. Local file
    # reads, no network — and a failure here must cost the proposals only,
    # never the day: an unreadable history is not a reason to show no blocks.
    from src.main import get_events as get_events_svc
    events_svc = get_events_svc()
    if events_svc is not None:
        try:
            gaps = _decorate_gaps(gaps, _load_history(events_svc, target_date))
        except Exception:
            logger.warning(
                "GET /daily?date=%s: gap proposals failed, gaps will ask instead",
                target, exc_info=True,
            )

    habits = vault.list_active_habits()
    # `target_date`, not today: habit checkboxes are reconciled against the
    # day being viewed, or yesterday shows this morning's completions and
    # every future date's habit todos vanish.
    todos = _build_todos(content, habits, target_date)
    notes = _build_notes(content)

    try:
        ledger = vault.read_token_ledger()
        tokens_today = ledger["metadata"].get("tokens_today", 0)
        tokens_total = ledger["metadata"].get("total_tokens", 0)
    except Exception:
        tokens_today = 0
        tokens_total = 0

    return DailyResponse(
        date=target,
        tokens_today=tokens_today,
        tokens_total=tokens_total,
        blocks=blocks,
        gaps=gaps,
        coverage=coverage,
        incomplete=incomplete,
        todos=todos,
        notes=notes,
    )


class FillGapBody(BaseModel):
    start: str                      # "HH:MM"
    end: str                        # "HH:MM"
    # Absent means "use whatever you proposed for this interval". The client
    # never sends the proposed name: a name can exceed the 64-byte callback
    # budget, and a client-supplied name is a client-supplied write (§4.2).
    name: str | None = None


@router.post("/{date}/gaps/fill")
async def fill_gap(date: dt_date, body: FillGapBody):
    """Turn a gap into a block (spec §4.4).

    A gap has no id — it is derived — so this keys on the interval. Without a
    `name`, the proposal for that interval is recomputed here rather than
    taken from the client.

    `date` is typed, not a raw string, for the same reason as `get_daily`:
    FastAPI rejects anything that isn't a real calendar date with 422 before
    it reaches `EventsService.create_event` / `_file_path`.
    """
    from src.main import get_events as get_events_svc
    events_svc = get_events_svc()
    if not events_svc:
        raise HTTPException(503, "Events service not initialized")

    date_str = date.isoformat()
    name = body.name
    was_guess = False

    if not name:
        start = minutes_into_day(body.start, "")
        end = minutes_into_day(body.end, "")
        if start is None or end is None:
            raise HTTPException(422, f"Unusable interval {body.start}-{body.end}")
        proposal = propose_for_gap(start, end, _load_history(events_svc, date))
        if not proposal:
            raise HTTPException(
                422, f"Nothing to propose for {body.start}-{body.end} — send a name.",
            )
        name = proposal["name"]
        was_guess = True

    created = events_svc.create_event(
        date=date_str, name=name,
        start_time=f"{date_str}T{body.start}", end_time=f"{date_str}T{body.end}",
    )
    return {"ok": True, "event_id": created.get("id", ""), "name": name,
            "was_guess": was_guess}


# Thin seams so approve-all is testable without a live events service, and so
# both routes share one implementation of each action.
async def _set_state_for_approve_all(date: str, event_id: str, body):
    from src.api.routes.events import set_event_state
    # set_event_state takes a real `date` object (R8) — FastAPI coerces that
    # from the path string on an HTTP call, but this is a direct Python
    # call, so the string has to be converted here or `.isoformat()` inside
    # set_event_state raises AttributeError on every real (non-mocked) run.
    return await set_event_state(dt_date.fromisoformat(date), event_id, body)


async def _fill_gap_for_approve_all(date: str, body: FillGapBody):
    # `fill_gap` now takes a real `date` object too, for the same reason as
    # the seam above: this is a direct Python call, so FastAPI's path-param
    # coercion never runs and the string has to be converted here.
    return await fill_gap(dt_date.fromisoformat(date), body)


@router.post("/{date}/approve-all")
async def approve_all(date: dt_date):
    """Approve every elapsed pending block on `date`, and bank every proposal.

    Proposals are included deliberately (spec §5.6) — decided 2026-09-10
    against the recommendation. The mitigation is that the response names what
    it banked and flags guesses, so the bot can say "Approved 3, including
    Sleep 00:20-06:40 (a guess)" and a wrong one is correctable in the same
    breath rather than discovered weeks later in the readout.

    One failure never aborts the rest: a 409 on a ticked habit must not strand
    the approvals after it.

    `date` is typed, not a raw string, for the same reason as `get_daily` and
    `fill_gap`: FastAPI rejects anything that isn't a real calendar date with
    422 before this ever calls into `get_daily` or the seams below.
    """
    from src.api.routes.events import SetStateBody

    date_str = date.isoformat()
    day = await get_daily(date)
    elapsed = day.coverage.elapsed_minutes
    approved: list[dict] = []
    failed: list[dict] = []

    for block in day.blocks:
        if block.state != "pending":
            continue
        # A block that has not happened cannot be confirmed. The /day view
        # gives it no buttons for the same reason (spec §5.1's `◌`), so
        # sweeping it here would confirm something the surface says you can't.
        start = minutes_into_day(block.start, "")
        if start is None or start >= elapsed:
            continue
        try:
            await _set_state_for_approve_all(
                date_str, block.id, SetStateBody(state="approved")
            )
            approved.append({"event_id": block.id, "name": block.title,
                             "was_guess": False})
        except HTTPException as exc:
            failed.append({"event_id": block.id, "reason": str(exc.detail)})

    for gap in day.gaps:
        if gap.proposal is None:
            continue
        try:
            result = await _fill_gap_for_approve_all(
                date_str, FillGapBody(start=gap.start, end=gap.end)
            )
            approved.append({"event_id": result["event_id"],
                             "name": result["name"], "was_guess": True})
        except HTTPException as exc:
            # `event_id` here is a synthesized `gap:{start}-{end}` marker, not
            # a real event id — gaps have no id of their own (spec §4.4), so
            # this is a label for the failed[] row, not an addressable id.
            failed.append({"event_id": f"gap:{gap.start}-{gap.end}",
                           "reason": str(exc.detail)})

    return {"ok": True, "approved": approved, "failed": failed}
