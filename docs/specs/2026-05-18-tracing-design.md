# Tracing & LLM Observability — Design

**Date:** 2026-05-18
**Status:** Approved (design); pending implementation plan
**Scope:** Add distributed tracing across telegram-bot → vault-server → Anthropic, surfaced through two OTLP-compatible backends (Arize Phoenix by default, Langfuse on demand).

## Motivation

The existing logging stack (structured JSON → Loki → Grafana) answers *what happened*. It does not answer *why the agent chose what it chose*: the system prompt, vault snapshot, message history, tool definitions, and per-iteration reasoning that drive Claude's behavior are not visible in flat logs. Debugging non-deterministic agent behavior requires trace trees with full LLM context.

## Goals

- See, for any Telegram update, the full causal chain: bot receipt → HTTP call → agent loop → each tool call → each Claude generation, with arguments and results.
- Capture the *complete* prompt sent to Claude on every turn, including the vault snapshot embedded in the system prompt.
- Stay vendor-neutral: instrumentation code must not bind to a single backend.
- Default backend is lightweight enough to run alongside the existing observability stack with no perceptible cost.
- Heavyweight backend (prompt registry, evals, datasets) available on demand without code changes.
- Existing JSON logs gain `trace_id` so Loki and the trace UI cross-link.

## Non-Goals

- Production-grade tracing (sampling, tail-based sampling, multi-tenant projects). Single-developer local-only setup.
- Metrics or profiling (separate concern, separate tools).
- Tracing the webapp frontend.

## Architecture

### Backends

**Phoenix** (default, single container, ~300 MB RAM, port 6006). Receives OTLP/HTTP traces on `/v1/traces`. Stores in SQLite under a named docker volume. UI optimized for live trace inspection during development.

**Langfuse v3** (opt-in, 6 containers, ~1.5 GB RAM). Receives OTLP/HTTP traces on `/api/public/otel/v1/traces`. Stores in Clickhouse + Postgres + MinIO. UI adds prompt registry, evaluation runs, scored datasets.

Both backends ingest the **same** OpenInference-formatted spans. No vendor lock-in: switching backends is one env var.

### Stack composition

`infra/observability/docker-compose.yml` — gains a `phoenix` service alongside existing loki + alloy + grafana.

`infra/observability/docker-compose.langfuse.yml` — new overlay file with Langfuse's 6 services (langfuse-web, langfuse-worker, postgres, clickhouse, redis, minio), shared `observability` network, bootstrap env (`LANGFUSE_INIT_*`) so the project + API keys exist on first boot.

`infra/observability/package.json` — gains `dev:langfuse` script: `docker compose -f docker-compose.yml -f docker-compose.langfuse.yml up`.

`turbo.json` — register `dev:langfuse` task (`cache: false`, `persistent: true`).

Apps gain a `dev:langfuse` script that overrides `OTEL_EXPORTER_OTLP_ENDPOINT` to the Langfuse OTLP path, then delegates to `npm run dev`. Phoenix and Langfuse can run simultaneously without interference; apps only ever export to one of them at a time based on env.

### Trace propagation

```
Telegram update
  └─ bot:telegram.update          (root, W3C traceparent generated)
       └─ HTTP POST /message      (traceparent injected into header)
            └─ server:POST /message    (FastAPI auto-instrumentation extracts traceparent)
                 └─ agent.handle_message
                      └─ agent.loop  (iteration=0)
                           ├─ anthropic.messages.create  (LLM generation — auto-instrumented)
                           ├─ agent.tool_call (list_tasks)
                           ├─ agent.tool_call (create_task)
                           └─ ...
                      └─ agent.loop  (iteration=1)
                           └─ ...
```

For the confirmation flow (`POST /message/confirm`), the original turn's `trace_id` is stored alongside the pending action and reattached when the confirmation resumes, so the resumed turn appears as a continuation under the same trace tree.

## Components

### `apps/vault-server/src/tracing_setup.py` (new)

Single-purpose module called once at startup from `main.py`. Responsibilities:

1. Construct `TracerProvider` with a `Resource` carrying `service.name=vault-server` and a `BatchSpanProcessor` exporting via OTLP/HTTP to `OTEL_EXPORTER_OTLP_ENDPOINT`.
2. Register `OpenInferenceAnthropicInstrumentor` — auto-captures every `anthropic.messages.create` call as a generation span with model, system prompt, message list, tool definitions, usage tokens, and response.
3. Register `FastAPIInstrumentor` on the FastAPI app — auto-creates a server span per request and extracts `traceparent` from incoming headers.
4. Expose a module-level `tracer = trace.get_tracer("mazkir.agent")` for manual spans.

If `OTEL_EXPORTER_OTLP_ENDPOINT` is unset or empty, the module installs a no-op tracer — apps run normally without a backend.

### `apps/vault-server/src/services/agent_service.py` (modified)

Manual spans wrap business logic the auto-instrumentor cannot see:

- `agent.handle_message` — wraps the public `handle_message` entrypoint. Attributes: `chat_id`, `text_length`, `attachment_count`.
- `agent.loop` — wraps each iteration of `_run_loop`. Attributes: `iteration`, `stop_reason` (on exit).
- `agent.tool_call` — wraps `_execute_tool`. Attributes: `tool.name`, `tool.risk`, `tool.confidence`, `tool.reasoning`, `tool.params_summary` (sanitized via existing `_sanitize_params`), `tool.result_summary` (via existing `_summarize_result`), `tool.duration_ms`.

The confirmation flow stores `trace_id` and `span_id` (parent of the awaiting-confirmation point) inside the action record. `handle_confirmation` reads them and creates a span link back, so the resumed iterations attach to the original trace tree.

### `apps/vault-server/src/logging_setup.py` (modified)

Add a `logging.Filter` that, on every log record, reads the current OTel span context and adds `trace_id` and `span_id` string fields to the record. Existing JSON formatter picks them up automatically. Records emitted outside any span get `null` values.

### `apps/telegram-bot/src/tracing.ts` (new)

Initializes `@opentelemetry/sdk-node` with OTLP/HTTP exporter targeting `OTEL_EXPORTER_OTLP_ENDPOINT`. Service name `telegram-bot`. Registers `getNodeAutoInstrumentations()` for HTTP + Fetch, then `sdk.start()`. No-op if endpoint env is unset.

### `apps/telegram-bot/src/bot.ts` (modified)

A middleware near the top of the chain opens a root span `telegram.update` with attributes `{kind, chat_id, from_id, text_length}` (same shape as existing `update_received` log event). The span ends when the middleware stack returns. All downstream HTTP calls inherit context automatically via OTel's HTTP instrumentation.

### `apps/telegram-bot/src/api/client.ts` (modified)

No code change required — `traceparent` is injected automatically by the auto-instrumented `fetch` (or `undici`). If the bot uses a fetch implementation OTel can't patch, fall back to manual `propagation.inject(context.active(), headers)` before the fetch call.

### `apps/vault-server/src/main.py` (modified)

Call `configure_tracing(settings)` immediately after `configure_logging` and `configure_audit_log`. Tracing initialization must run before `FastAPI()` is constructed for instrumentation to attach.

### `apps/vault-server/src/config.py` (modified)

Add `otel_exporter_otlp_endpoint: str = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:6006/v1/traces")` and `otel_service_name: str = os.getenv("OTEL_SERVICE_NAME", "vault-server")`.

## Data Captured

### From the Anthropic auto-instrumentor (per `messages.create` call)

- `llm.model_name`
- `llm.input_messages` — full chat history including the system prompt
- `llm.system` — the system prompt as a separate attribute (includes the vault snapshot, in plaintext)
- `llm.tools` — full tool schema list
- `llm.output_messages` — Claude's response including any tool_use blocks
- `llm.token_count.prompt`, `llm.token_count.completion`, `llm.token_count.total`
- `llm.invocation_parameters` — temperature, max_tokens, etc.

### From manual spans

- Per tool call: name, risk, confidence, reasoning, sanitized inputs, summarized outputs, duration
- Per loop iteration: index, stop reason
- Per turn: chat_id, attachment count, message length

### Explicitly excluded

- Raw photo bytes (only paths + EXIF summary stored)
- API keys (`ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, Google OAuth tokens)

### Privacy note

The vault snapshot embedded in the system prompt contains personal task/habit/goal names in plaintext, stored in the trace backend's Clickhouse (Langfuse) or SQLite (Phoenix). Both backends run locally on the developer's machine — no data leaves the host. This is a deliberate choice favoring debuggability.

## Log ↔ Trace Correlation

Every JSON log record gets `trace_id` and `span_id` injected when emitted from within a span. Grafana's Loki data source gains a derived field with a data link to Phoenix's trace UI:

```
http://localhost:6006/projects/default/traces/{trace_id}
```

When using Langfuse, the equivalent link is:

```
http://localhost:3001/trace/{trace_id}
```

For the initial implementation, the Grafana provisioning configures the Phoenix link only. Switching the Loki datasource to Langfuse links is a one-line config edit, not a code change.

## Environment Config

Default `.env` (both apps):

```
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:6006/v1/traces
OTEL_SERVICE_NAME=vault-server   # or telegram-bot
```

`dev:langfuse` script overrides only `OTEL_EXPORTER_OTLP_ENDPOINT` to `http://localhost:3001/api/public/otel/v1/traces`.

`infra/observability/.env` (new, gitignored, committed with `.env.example` template) holds Langfuse bootstrap creds so `turbo dev:langfuse` works without manual UI setup:

```
LANGFUSE_INIT_ORG_ID=mazkir
LANGFUSE_INIT_PROJECT_PUBLIC_KEY=pk-lf-local-dev
LANGFUSE_INIT_PROJECT_SECRET_KEY=sk-lf-local-dev
```

## Error Handling

- OTel SDK initialization failures (unreachable endpoint, bad config) log a warning and install a no-op tracer. Apps must never fail to start because tracing is broken.
- Span export failures are dropped silently by the `BatchSpanProcessor` after retry; they do not propagate to user-visible errors.
- Anthropic instrumentor failures (e.g. SDK version mismatch) log a warning and proceed without LLM auto-spans. Manual tool/loop spans still work.

## Testing

- `apps/vault-server/tests/test_tracing_setup.py` — verifies `configure_tracing` is idempotent, installs no-op tracer when endpoint is empty, and registers the FastAPI + Anthropic instrumentors when endpoint is set. Uses `InMemorySpanExporter` to assert spans are produced.
- `apps/vault-server/tests/test_agent_service.py` — extend existing tests with assertions on span attributes: a successful turn emits `agent.handle_message` → `agent.loop` → `agent.tool_call` spans with expected names and `tool.risk`/`tool.confidence` attributes.
- `apps/telegram-bot/tests/` — add a tracing init test verifying SDK starts without throwing when endpoint env is set vs unset.
- Manual verification matrix:
  - `turbo dev`: send a Telegram message, open Phoenix at `localhost:6006`, confirm a single trace tree spanning bot → server → Claude, with the system prompt visible on the generation span.
  - `turbo dev:langfuse`: same flow, open Langfuse at `localhost:3001`, confirm the same trace tree appears there.
  - Trigger a low-confidence confirmation flow, send "yes" — confirm the resumed iteration appears under the original trace.

## Operational Notes

- `data/logs/` (existing) is unchanged in shape — only gains two new fields per record.
- Phoenix and Langfuse both persist to docker named volumes. `docker compose down` keeps data; `docker compose down -v` wipes it.
- Phoenix's SQLite has no built-in retention. For long-running dev sessions this is fine; in practice, traces accumulate at ~10–50 KB each.

## Open Questions

None at design time. Implementation plan to address rollout order and the precise call sites for manual spans in `agent_service.py`.
