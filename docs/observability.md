# Observability — logs & per-turn audit

Mazkir writes structured JSON logs to `data/logs/`. A local docker-compose
stack (Loki + Alloy + Grafana) ships the same files into a queryable UI.

## Files

- `data/logs/vault-server.jsonl` — every log line from the Python backend.
- `data/logs/agent-turns.jsonl` — one JSON object per agent turn (the headline
  audit artifact). Each record contains `chat_id`, `user_text`, every tool the
  agent invoked (with `confidence`, `reasoning`, sanitized `params`, and a
  compact `result_summary`), the final `assistant_text`, and `iters`.
- `data/logs/telegram-bot.jsonl` — every inbound update + outbound API call.

All three rotate at 10 MB × 5 files. They are gitignored (under `data/`).

## Stack — local Loki/Alloy/Grafana

```bash
cd infra/observability
docker compose up -d
```

Verify:

- Loki: <http://localhost:3100/ready>
- Grafana: <http://localhost:3000> (anonymous-admin enabled)
- Alloy UI: <http://localhost:12345>

The default dashboard "Mazkir" has four panels:

1. **Agent turns** — `{service="vault-server", event_type="agent_iter"} | json`
2. **Tool calls** — `{service="vault-server", event_type="tool_call"} | json`
3. **Errors** — `{level="ERROR"}`
4. **Bot inbound** — `{service="telegram-bot", event_type="update_received"} | json`

`agent-turns.jsonl` is also ingested under `service="agent-turns"` and is the
best place to reconstruct exactly what happened in a single Mazkir reply.

## Config

- `LOG_LEVEL` (env, default `INFO`) — controls the root logger level for the
  Python backend.
- `LOGS_DIR` (env, default `~/dev/mazkir/data/logs/`) — where JSON files land.
  Honored by both vault-server and telegram-bot.
- `MAZKIR_LOGS_DIR` (compose-only) — bind-mount source for Alloy. Defaults to
  `../../data/logs` relative to the compose file.

## Useful queries

- All tool calls in the last hour, with status:
  `{service="vault-server", event_type="tool_call"} | json | line_format "{{.tool}} {{.status}} {{.duration_ms}}ms {{.params}}"`

- Just the failing tool calls:
  `{service="vault-server", event_type="tool_call"} | json | status="error"`

- Everything for one chat:
  `{service="vault-server"} | json | chat_id="123"`

## Querying without Grafana

`agent-turns.jsonl` is grep-friendly:

```bash
tail -f data/logs/agent-turns.jsonl | jq .
jq 'select(.chat_id == 123 and .awaiting_confirmation == true)' data/logs/agent-turns.jsonl
```

## Tracing

The stack also includes [Arize Phoenix](https://phoenix.arize.com) for distributed
tracing. Every Telegram update produces a single trace tree spanning:
`telegram.update → POST /message → agent.handle_message → agent.loop →
agent.tool_call` plus an LLM generation span per Claude call (system prompt,
tools, token usage all captured automatically).

Spans carry OpenInference attributes — `input.value`, `output.value`,
`session.id`, `user.id` — so Phoenix renders readable I/O and groups a chat
into a session. Tool calls that touch the filesystem emit a child `fs.write`
or `fs.delete` span carrying `fs.path`, `fs.store` (`vault` / `events` /
`media`), and `fs.bytes`, so a trace confirms which files were written and how
long the I/O took.

grammY long-polls Telegram's `getUpdates` endpoint continuously; those requests
are filtered out at the SDK (`shouldIgnoreOutgoingRequest` in
`telegram-bot/src/tracing.ts`) so they never become spans and never flood the
trace view.

- **Phoenix UI:** <http://localhost:6006>
- **OTLP endpoint:** `http://localhost:6006/v1/traces`
- **Project:** `mazkir` (set via `openinference.project.name` resource attribute)

### Langfuse (opt-in)

For prompt-management, eval, and dataset workflows, run the heavier Langfuse
stack:

```bash
npx turbo dev:langfuse
```

This brings up Phoenix and Langfuse side-by-side and points the apps at
Langfuse's OTLP endpoint. UI at <http://localhost:3001>. First-boot bootstrap
keys live in `infra/observability/.env.example` — copy to
`infra/observability/.env` before first run.

Caveat: the current `langfuse/langfuse:3` image expects ClickHouse Keeper for
its `ON CLUSTER` migrations, which the bundled `clickhouse:24.3-alpine` doesn't
ship. The overlay is committed as a scaffold; bringing the web UI up to login
still needs either an embedded-Keeper config or a v2 image pin. Phoenix remains
fully functional as the default backend in the meantime.

### Log ↔ trace correlation

Every JSON log line carries `trace_id` and `span_id` when emitted inside a
span. In Grafana Explore, the Loki datasource exposes `trace_id` as a clickable
derived field that links straight into the matching Phoenix trace.
