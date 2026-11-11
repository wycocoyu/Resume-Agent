# Agent Streaming Protocol (Simplified)

## Client Path
- Frontend uses `streamAgent()` in `frontend/src/services/agentStream.ts`.
- Transport is plain `fetch` + `ReadableStream` + SSE line parsing.
- No CLTP session/adapter layer.

## Endpoint
- `POST /api/agent/stream`
- `Accept: text/event-stream`
- Request body:
  - `message`
  - `conversation_id`
  - `resume_data`

## Event Handling
- `thought` / `thought_chunk`: append to current thought text.
- `answer` / `answer_chunk`: append to current answer text.
- `status=complete` or `done`: mark stream done and finalize one assistant message.
- `error` / `agent_error`: surface error message in UI.

## Rendering Strategy
- Streaming stage renders received content directly.
- Markdown is rendered directly via `EnhancedMarkdown`.
- No burst smoothing, no synthetic typewriter replay.
