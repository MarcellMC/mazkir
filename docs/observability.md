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
