# Cross-midnight time handling: what to reuse

Research date: 2026-11-17. The question: how do time-management apps and AI
assistants handle activities, conversations and "today" when they cross
midnight, and which of their practices should Mazkir adopt?

Three parts. The two research parts summarize their sources. The audit part
reads Mazkir's own code. It was written from reading the code only, and none
of it was run.

- [Summary and recommendation](#summary)
- [Part 1: time-management, calendar, sleep and location apps](#part-1-apps)
- [Part 2: LLM agents and assistants](#part-2-agents)
- [Part 3: audit of Mazkir's own day rules](#part-3-audit)

## Summary

### The failures that prompted this

- **A walk that started at 23:15 was missed.** At 00:20 the user said what they
  were doing. The open trip's block was in the previous date's file, so
  `list_events` for today didn't see it. The agent created a duplicate block
  from 00:20, invented an end time, and pushed it to Google straight away.
- **The question quota misfired.** It counts by a day that runs to 05:00. Earlier
  trips had used it up, so a night trip's stops went unasked.
- **The model got a schedule entry backwards.** It saw "Band practice
  18:00–23:00". It ignored it at 18:43, while it was going on, and applied it at
  23:38, after it had ended.
- **The conversation file lost its timestamps.** It is one file per calendar
  date. When it is summarized, every kept message is restamped with the current
  time, and the older half is deleted.

### Reusable practices

1. **Store an activity once, as one interval with real start and end times.** A
   day is a view of it, not where it lives. This is how RFC 5545 works, as do
   Arc/LocoKit, Google's Timeline export and HealthKit. Splitting at midnight
   is the source of most fragment bugs (approve, delete, sync, habit credit).
2. **Query a day by overlap: `start < day_end AND end > day_start`.** Never
   query by which file a row is in. CalDAV does this, as do Google Calendar's
   `timeMin`/`timeMax` and LocoKit.
3. **Treat an open interval (a start, no end) as overlapping up to now.** Whoop's
   open cycle works this way. Make it part of the shared overlap function, not
   a special case in `/day`.
4. **One `logical_day(instant)` function with one boundary constant (05:00).**
   Use it for every "today", quota, streak, habit, token and todo decision.
   ManicTime, Timing, ActivityWatch and Anki all have this setting.
   ActivityWatch once queried 04:00–04:00 but drew 00:00–24:00, and night
   events seemed to vanish. That is our bug.
5. **Count by the start's logical day; add up minutes by clipping to the
   window.** GTFS service days do this, and so does Toggl's start-day rule. Sleep
   is the documented exception and goes to the wake day (Fitbit, Garmin).
6. **Use half-open intervals `[start, end)`.** This is RFC 5545's non-inclusive
   DTEND. It removes the 23:59:59 and 24:00 special cases.
7. **Compute "is it happening now" in code, and give the model labels.** For
   example "Band practice: on now, ends in 4 h 17 min" or "ended 38 min ago",
   not raw `HH:MM–HH:MM`. Benchmarks (TRAM, TimeBench, Test of Time,
   ChronoSense) show models are unreliable at interval relations and date
   arithmetic. Extracting the structure and computing in code works (TempLogic,
   TReMu).
8. **Give the agent a per-turn time block, outside the cached prefix.** It holds
   the local time, the weekday, the IANA zone, the logical day and the boundary,
   plus **what is in progress**: the open trip and its stops, and blocks still
   going. OpenClaw does this. Anthropic's context-engineering guidance
   recommends small, always-relevant facts up front, and When2Call shows models
   are unreliable at deciding when to call a lookup tool.
9. **Ask for blocks by time window, not by date.** `list_events(start, end)`
   should default to the last few hours up to now, across midnight.
10. **Check for an existing block inside the create tool.** If an open or
    overlapping block of the same activity exists, extend it or attach to it.
    Never invent an end time. Don't push a guess to Google before it's confirmed.
11. **Messages keep their original timestamps, unchanged.** A summary carries the
    time span it covers. Memory is a rolling window (the last 24 h) or a logical
    day, not a calendar-date file. Sources are OpenClaw, Anthropic on compaction,
    LongMemEval and Zep's bi-temporal edges.
12. **No promise without a mechanism.** The agent says "I'll…" only when
    something will do it, such as a scheduled trigger or the trip message itself.
    ChatGPT ties future work to its automations tool.
13. **Sync one logical interval to Google as one event.** Google stores a
    cross-midnight event natively.
14. **Test the night.** Add cases to the replay harnesses for:
    - a block open across 00:00;
    - an entry that ended N minutes ago;
    - a 00:20 message about the evening;
    - DST fall-back day.

### Recommendation

Start with 4, 7, 8 and 10. Together they would have prevented all four
failures without a data migration. Then do 2, 3 and 9, and finally 1, 6 and
13, which together are the storage change. Fix the concrete bugs the audit
found (Part 3) along the way. The pytz offset bug is verified and shifts
Google's day window by 21 minutes.

---

## Part 1: apps

Some areas had no primary source and are marked as unverified rather than
filled in from memory:
- Arc's day view, Moves, Life Cycle and Gyroscope;
- Things 3, TickTick and Loop;
- how Google Calendar renders a timed event longer than 24 h.

### Time trackers

- **Toggl Track** gives the whole entry to its start day "by design". To fix
  it, users split the entry by hand at 23:59. Users complain about daily totals
  and billing weeks.
  https://community.toggl.com/t/time-entries-spanning-multiple-days-dont-show-up-properly-in-reports/438
- **Clockify** has a manual split. It counts entries on their start day, but its
  dashboard grouping later moved to the end day without notice. Silent rule
  drift is the complaint.
  https://forum.clockify.me/t/group-entries-by-day-based-on-start-time-rather-than-end-time-working-past-midnight/1490 ,
  https://clockify.me/help/track-time-and-expenses/split-time-entries
- **Harvest:** a timer left running from an earlier day keeps running until it
  is stopped.
  https://support.getharvest.com/hc/en-us/articles/47201092522509-Stopping-a-stuck-or-runaway-timer
- **Timing (macOS)** has a "Wrap days at" setting, e.g. 5am, and warns that a
  late value moves earlier time to the previous day. https://timingapp.com/help/faq
- **ManicTime** has "Shift day start by (hours)", making days 05:00–05:00.
  https://docs.manictime.com/win-client/settings/shift-day-start
- **RescueTime** uses a fixed midnight. Its API aggregates by day, so a 02:00
  cutoff can't be rebuilt from it. https://help.beeminder.com/article/76-rescuetime
- **ActivityWatch** has "Start of day" (04:00).
  - PR #766: the view queried 04:00–04:00 but drew midnight–midnight, so
    00:00–04:00 seemed to vanish.
  - PR #774: the setting was stored as text, and a shared
    `get_day_start_with_offset()` helper was proposed.
  
  https://github.com/ActivityWatch/aw-webui/pull/766 ,
  https://github.com/ActivityWatch/aw-webui/pull/774

### Sleep and health

- **Fitbit:** `dateOfSleep` is the date the sleep ended.
  https://dev.fitbit.com/build/reference/web-api/sleep/get-sleep-log-by-date/
- **Garmin:** sleep goes to the wake day, with an explicit `calendarDate`.
  https://help.labfront.com/garmin-sleep-data-defined
- **Oura:** a "Sleep Day" runs 18:00–18:00, and the longest sleep in the window
  scores it. https://partnersupport.ouraring.com/hc/en-us/articles/29040334963219
- **Whoop:** has no calendar day. A cycle runs from one sleep onset to the next,
  and an open cycle is the current one. Boundaries can be revised for days.
  https://developer.whoop.com/docs/developing/user-data/cycle
- **HealthKit:** samples carry only a start and an end, and each app picks its own
  day rule. Store the time-zone metadata. https://sahha.ai/blog/which-day-does-sleep-belong-to/

### Calendars

- **RFC 5545:** DTEND is the non-inclusive end, so intervals are half-open.
  https://icalendar.org/iCalendar-RFC-5545/3-6-1-event-component.html
- **CalDAV (RFC 4791 §9.9):** the time-range query is a pure overlap test.
  https://icalendar.org/CalDAV-Access-RFC-4791/9-9-caldav-time-range-xml-element.html
- **Google Calendar API:** `timeMin` bounds an event's end and `timeMax` bounds
  its start. So an event from 23:15 to 00:40 is returned for both days and stored
  once. https://developers.google.com/calendar/api/v3/reference/events/list
- **Apple Calendar:** draws timed overnight events across the day columns.
  https://support.apple.com/guide/calendar/icl1039/mac

### Location timelines

- **Arc (LocoKit):** the day query is `endDate > startOfDay AND startDate <
  endOfDay`. A visit is one item, even when it lasts for days.
  https://github.com/sobri909/LocoKit
- **Google's on-device Timeline export:** one record per visit or activity, with a
  UTC offset for each end, because a trip can change time zone.
  https://dawarich.app/blog/whats-inside-your-google-timeline-export/

### "Day starts at X"

- **Anki:** the default is 04:00. Set it deep in sleeping hours and don't change
  it back and forth, because changing it shifts intervals.
  https://docs.ankiweb.net/preferences.html
- **Habitica:** Custom Day Start moves "cron". "Record Yesterday's Activity" is
  the escape hatch. A custom boundary breaks integrations such as Beeminder.
  https://habitica.fandom.com/wiki/Auto_Cron
- **Others:** Todoist has no setting. Habitify, Sunsama and Day One all have
  open requests for one. https://feedback.habitify.me/p/start-day-at

### Transit (GTFS)

- A service day may run past 24:00:00, so 01:30 the next morning is written
  25:30:00 on the trip's own service day. Times are measured from "noon minus
  12 h", which handles DST. https://gtfs.org/documentation/schedule/reference/

### Pitfalls

- **DST:** days are 23 or 25 hours long. Compare local dates, not rolling 24 h
  windows, and test the repeated hour.
- **Travel:** store IANA zones and the offset at each end.
- **Streaks:** a midnight cutoff breaks night owls, and a custom cutoff breaks
  integrations.
- **Silent rule drift:** pin the rule with tests.
- **Late data:** a trip closed late must be able to re-attribute its counts.

---

## Part 2: agents

### Temporal grounding

- **Most frameworks inject the clock:**
  - Agno's `add_datetime_to_instructions` (https://docs.agno.com/context/agent/datetime-instructions);
  - Google ADK's `InstructionProvider` and `{state}` (https://google.github.io/adk-docs/sessions/state);
  - LangChain v1's `dynamic_prompt` middleware (https://docs.langchain.com/oss/python/langchain/runtime).
- **OpenClaw** (https://docs.openclaw.ai/date-time/index.html):
  - It uses an IANA zone for the user.
  - Each inbound message is stamped, e.g. `[Mon 2026-01-05 16:26:34 PST]`, plus
    elapsed time.
  - A per-turn temporal block sits outside the cached prefix.
  - Tool payloads are normalized to epoch and UTC.
- **Zep/Graphiti** (https://arxiv.org/abs/2501.13956):
  - Each fact has four timestamps: `valid_at` and `invalid_at` for when it was
    true, `created_at` and `expired_at` for when the system knew it.
  - A relative phrase is resolved against the time of the message it came from.
- **Mem0:** `add(timestamp=…)` takes the time of the event, not of ingestion.
  https://docs.mem0.ai/platform/features/timestamp
- **Inject or query?** No controlled study was found. Anthropic's guidance
  favours a hybrid: small, high-value context up front, the rest fetched just
  in time.
  https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
  When2Call shows models are unreliable at deciding when to call a tool.
  https://arxiv.org/abs/2504.18851

### Temporal reasoning research

- **Benchmarks:**
  - TRAM (https://arxiv.org/abs/2310.00835) and TimeBench
    (https://arxiv.org/abs/2311.17667) show a persistent gap to humans.
  - Test of Time finds multi-step date arithmetic is where models degrade
    (https://arxiv.org/abs/2406.09170).
- **Intervals and robustness:**
  - ChronoSense finds Allen's interval relations handled inconsistently
    (https://arxiv.org/abs/2501.03040).
  - Rewording the same constraint problem moves accuracy by 25–62 points
    (https://arxiv.org/html/2511.10654v1).
  - How the tokenizer splits dates predicts errors (https://arxiv.org/html/2505.16088v3).
- **Mitigations that work:**
  - TempLogic: the model extracts structure and a solver does the logic
    (https://arxiv.org/abs/2305.15014).
  - TReMu: a dated timeline plus generated code (https://arxiv.org/abs/2502.01630).

### Conversation memory across days

- **LongMemEval** (https://arxiv.org/abs/2410.10813):
  - Indexing memory by the times of the events it holds helps.
  - Filtering memory by a time range taken from the question adds 6.8–11.3% on
    temporal questions.
- **Compaction:** Anthropic warns that over-aggressive compaction loses context.
  Keep original stamps, and give summaries the time span they cover.
- **Product examples:**
  - MinuteDock's Night Owl Mode files 00:00–04:00 under the previous day
    (https://minutedock.com/help/en/articles/15255988-personal-time-tracking-settings).
  - Sunsama still rolls over at midnight
    (https://roadmap.sunsama.com/improvements/p/option-to-change-rollover-time-end-of-day-time-to-after-midnight).
  - No public documentation was found for how Gemini-in-Calendar, Reclaim or
    Motion resolve "today" at 00:20.

### Tool design

- **Query by overlap.** Google's `events.list` is the model to follow.
- **Deduplicate on the server.** Derive keys from workflow state, never from
  model output. Put the existence check inside the create tool, because a
  read-then-write done by the agent can race.
  https://tianpan.co/blog/2026-04-19-idempotency-agentic-tool-calling-saga-deduplication

### Honest commitments

- **OpenAI's prompt**, from a community-compiled copy whose provenance is
  unverified:
  - "Never promise to do background work unless calling the automations tool".
  - Partial completion beats a promise.
- **The pattern:** future work goes through a real scheduling tool. A prompt
  rule forbids every other promise.

---

## Part 3: audit

Rule labels:
- **CS:** calendar date of the start;
- **CE:** calendar date of the end;
- **LD(H):** logical day with boundary hour H;
- **SL:** server-local today;
- **VT:** today in the vault timezone.

Paths are under `apps/vault-server/src` unless they start with `telegram-bot/`.

### Storage and events

- **One file per date** (`services/events_service.py:184`). The file a row sits
  in is its day, and nothing checks the timestamps against it.
- **Cross-date move** (`events_service.py:424`, CS via `[:10]` at line 127).
  - An edit never re-splits a block.
  - Extending an end past midnight leaves one unsplit row in the start date's
    file.
  - The next day never shows that row's 00:00 onwards.
- **Bare-time edits:**
  - `_normalize_time` anchors `HH:MM` to the stored date and doesn't wrap past
    midnight (`agent_service.py:3547-3552`), while `derive_interval` does wrap.
  - So "it ended at 01:30" on a 22:00 block is refused as an inverted interval.

### Splitting and fragments

- **`split_at_midnight`** (`interval.py:146`):
  - The first fragment ends at 23:59:59 (line 163). `minutes_into_day` floors
    that, which leaves a one-minute gap at 23:59.
  - The `date` parameter of `create_event` defaults to SL (`agent_service.py:3270`).
- **Blocks that cross midnight are never synced to Google** (`agent_service.py:3346-3350`, `calendar_push.py:44`).
- **`_update_fragments`** (`agent_service.py:3721-3760`):
  - It looks only at day−1 and day+1.
  - Only name, activity and location propagate.
  - Delete (`3762`) and approve (`api/routes/events.py:384`) ignore
    `logical_id`, so approving one half of a night leaves the other half pending.
- **Habit ticks disagree.** The hook ticks the last fragment, stamped at the end
  (CE; `hooks/habit_hook.py:46-62`, `fast_lane/habits.py:82-84`). Approve stamps
  the file date at 12:00 (CS; `events.py:432-437`).

### /day assembly

- **`_with_ongoing`** (`api/routes/daily.py:274-301`) carries only open blocks,
  from only the previous file, at most 12 h old. It doesn't carry complete
  unsplit rows.
- **Blocks and coverage** (`daily.py:304-381`, CS) drop events that start on
  another date.
- **Source merge** (`services/day_assembly.py`):
  - Google is queried by overlap, but the result is then dropped by the
    start-date rule above. `GET /events` persists such a row into the second
    day's file.
  - `MergerService(timezone="Asia/Jerusalem")` is hard-coded (`day_assembly.py:107`).
- **pytz offset bug (verified):** `datetime(y, m, d, tzinfo=pytz_zone)` at
  `calendar_service.py:771` gives `+02:21` (local mean time). So the day window
  Mazkir asks Google for is off by 21 minutes.
- **`list_events`** (`agent_service.py:3124-3155`) defaults to SL and reads only
  that date.
- **`gap_proposals`** (`gap_proposals.py:45-63`, CS) ignores blocks that cross
  midnight and counts fragments twice.
- **`fill_gap` / approve-all** (`daily.py:574-577`) can write `T24:00`, which
  `minutes_into_day` rejects. The block is never drawn and the gap returns.

### Fast lane

- **The boundary is LD(5)** (`config.py:83`, `time_resolver.py:85-88`). Night
  words use LD, but plain day words use the calendar date (line 197). So at
  01:00 "tonight" and "tomorrow" disagree.
- **Context and actions use different rules:**
  - blocks: today, plus yesterday only before 05:00 (`fast_lane/context.py:120-133`);
  - todos: calendar today (`fast_lane/context.py:136`);
  - event date: CS (`actions.py:92`);
  - todo add and check: LD (`actions.py:286`);
  - rollover: calendar today (`actions.py:277-280`).
- **`covering_block`** (`fast_lane/photos.py:41`) reads one file, so a 00:30
  photo misses a block opened at 22:00.
- **Sleep medians are skewed.** Split sleep adds a 00:00 start and two short
  durations, which skews `typical_bedtime` and `typical_minutes`.

### Location trips

- **The question count is LD(5)** (`location/pipeline.py:120-123`), consistent
  with `records.py`.
- **`location/context.py`:**
  - The conversation is a 24 h window, which is correct.
  - Todos, blocks and habits are calendar today only, so at 00:20 the
    evening's blocks are invisible.
- **The trip writer** (`location/writer.py:327`) uses CS and goes through
  `create_event`, so new blocks split. Approved blocks and merged user blocks
  are edited in place, and become unsplit rows that cross midnight.

### Memory and conversation

- **`_get_conversation_path`** (`memory_service.py:57-60`) is VT. Every reader
  reads today's file only: `assemble_context`, the trace lookup, and the fast
  lane's `_recent_turns`. At 00:01 the agent has no memory of 23:58.
- **`summarize_and_decay`** (`memory_service.py:182-186`) restamps kept messages
  with the current time and deletes the older half from the vault.
  `location/context.py` parses those timestamps.
- **`_previous_skill`** (`api/routes/message.py:390`) resets at midnight.

### Tokens and habits

- **`update_tokens`** sets `tokens_today` by write time. A backdated approval at
  00:30 counts toward the new day.
- **`/daily` reads `tokens_today` without the stale-day reset** that
  `routes/tokens.py:21-23` applies. After midnight `/day` shows yesterday's
  tokens.
- **Two day rules for habit completions.** `completions_today` defaults to SL;
  `count_on` uses the calendar date of the completion.

### Server-local and naive leftovers

- The prompt's "Current date/time" is a naive `datetime.now()`
  (`agent_service.py:2270`).
- Many `dt.date.today()` defaults remain, in `agent_service.py` and
  `tool_handlers/daily.py`, and in the memory snapshot (`memory_service.py:428,
  447`).
- The prompt's list of incomplete blocks reads only today's file (2290). A
  block left open from before midnight disappears at 00:00.

### Bot

- **The selected-date hint has no clock** (`state/selected-date.ts`). A view of
  the 14th opened at 23:55 still steers a message at 00:10.
- **Photo filenames use the process's local time** (`conversations/message.ts:278`).

### The day notions in use

1. **File-is-day (CS):** storage, `/day`, `list_events`, `covering_block`, gap
   history, timeline.
2. **Calendar date of the end (CE):** habit ticks on split blocks.
3. **Overlap:** the Google query, `_with_ongoing` (partly), the location
   conversation window.
4. **Logical day with a 05:00 boundary:** fast-lane todos and night words, the
   trip question quota.
5. **Today in the vault timezone (VT):** `/day`, the conversation file, tokens, the
   bot label.
6. **Server-local today (SL):** agent defaults, the prompt clock, tool handlers,
   the memory snapshot.

Between 00:00 and 05:00, notions 4, 5 and 1 disagree. Overlap reads feed
start-date renderers, so unsplit rows that cross midnight vanish on day 2.
Fragments are unified only for renames.
