# WorkFlex Bridge Agent

An AI-native service that turns messy `#feature-requests` Teams messages into structured Jira tickets (or comments on existing ones), enriched with client ARR from HubSpot. A human reviews and approves each draft in a browser UI before anything is written.

---

## Setup & Run

### Prerequisites

- **Docker Desktop** (with Docker Compose v2) — for running the mock API and the agent
- **An OpenRouter API key** with access to `anthropic/claude-sonnet-4.6` — get one at [openrouter.ai](https://openrouter.ai/keys)
- *(Python 3.11+ only needed if you want to run without Docker)*

### 1. Clone and configure

```bash
git clone <this-repo>
cd bridge-agent
cp .env.example .env
```

### 2. Start the mock API

The challenge ships a mock server in its own folder (`AI Engineer Coding Challenge 1/`) with its own `docker-compose.yml`. Open a terminal **in that folder** and run:

```bash
docker compose up --build
```

It listens on **http://localhost:8080**. Leave this terminal running.

### 3. Generate API tokens

Open **http://localhost:8080/dashboard** in your browser and click the buttons to generate one token per service:

- **Jira** — also asks for an email (any value works, e.g. `you@example.com`)
- **HubSpot** — click generate
- **Microsoft Teams** — click generate (this is the OAuth client secret)

### 4. Fill in `.env`

Paste the tokens from the dashboard plus your OpenRouter key into `.env`:

```dotenv
OPENROUTER_API_KEY=sk-or-v1-...
LLM_MODEL=anthropic/claude-sonnet-4.6

JIRA_EMAIL=you@example.com
JIRA_TOKEN=jira-token-xxxxxxxxxxxxxxxx
HUBSPOT_TOKEN=hs-pat-xxxxxxxxxxxxxxxx
TEAMS_CLIENT_SECRET=teams-secret-xxxxxxxxxxxxxxxx
```

Everything else (`MOCK_BASE_URL`, `TEAMS_TEAM_ID`, `TEAMS_CHANNEL_ID`, `JIRA_PROJECT_KEY`) has a sensible default in `.env.example` — leave as-is.

### 5. Start the agent

In a **second terminal**, from the `bridge-agent/` folder:

```bash
docker compose up --build
```

Wait for `Uvicorn running on http://0.0.0.0:8000`. The agent container reaches the mock via `host.docker.internal:8080`, so the two compose stacks stay independent.

### 6. Open the UI

Go to **http://localhost:8000**. You'll see:

1. Click **Process Messages** — the agent fetches Teams messages, classifies each one with the LLM, looks up client ARR in HubSpot, searches Jira for duplicates, and drafts either a new ticket or a comment. Takes ~30-60s for the full 60-message fixture.
2. Review the draft cards. Every field is editable. Toggle **Approve** on the ones you want to submit.
3. Click **Submit Approved** — the agent writes to Jira and posts "Got it!" confirmations back to the Teams channel.
4. Verify via the mock's Swagger UI at **http://localhost:8080/docs** — new `JIRA-12xx` tickets, new comments on existing ones, and new Teams messages should all be visible.

---

## Run locally without Docker

Useful for fast iteration on the agent code.

```bash
# still need the mock API running (from the challenge folder):
#   cd "AI Engineer Coding Challenge 1" && docker compose up --build

# in a separate shell:
python -m venv .venv
source .venv/Scripts/activate          # Windows (Git Bash)
# source .venv/bin/activate            # macOS / Linux

pip install -r requirements.txt

# point .env at the host-exposed mock:
echo "MOCK_BASE_URL=http://localhost:8080" >> .env

uvicorn app.main:app --reload --port 8000
```

---

## Tests

```bash
pytest
```

The suite runs the full pipeline with `httpx.MockTransport` mocking the three upstream APIs and both LLM calls monkey-patched. **No network, no API key required** — safe to run in CI.

---

## How it works

```
Browser UI  ──►  FastAPI
                   │
                   ├─ POST /api/process  →  pipeline.run()
                   │    1. Teams: fetch channel messages
                   │    2. LLM:   extract requester + client + core ask (skips internal chatter)
                   │    3. HubSpot: look up client ARR (fuzzy name matching)
                   │    4. Jira:  search candidate tickets via JQL keyword query
                   │    5. LLM:   dedupe decision + draft title/summary/comment
                   │   ─► returns List[Draft]  (nothing written yet)
                   │
                   └─ POST /api/submit   →  submitter.submit_all()
                        • create Jira issue OR add comment
                        • post "Got it!" feedback to Teams channel
```

**Design choices:**

- **Structured pipeline, not an autonomous tool-use loop.** Deterministic, easy to debug, cheaper on tokens. LLM is invoked at two decision points with strict JSON output validated against Pydantic models.
- **Defensive dedupe.** If the LLM picks `comment` but names a ticket key not in the candidate set, we downgrade to `create` rather than writing to a hallucinated ticket.
- **Human in the loop.** `/api/process` only drafts; nothing goes to Jira or Teams until the user approves and clicks Submit.
- **Per-message isolation.** A failed extract or decide call becomes an error row in the draft list; it never kills the batch.

---

## File map

| Path | Purpose |
|------|---------|
| `app/main.py` | FastAPI app, routes, static UI mount |
| `app/pipeline.py` | Orchestrator — fetch → extract → enrich → dedupe → draft |
| `app/submitter.py` | Writes approved drafts to Jira + posts feedback to Teams |
| `app/clients/{teams,jira,hubspot}.py` | Thin async HTTP wrappers per mock API |
| `app/llm/client.py` | OpenRouter-backed client with JSON-mode + Pydantic validation |
| `app/llm/extract.py` | Message → `ExtractedRequest` |
| `app/llm/dedupe.py` | Enriched request + candidates → `DraftDecision` |
| `app/models.py` | Pydantic schemas shared across layers |
| `static/index.html` | Single-page admin UI (vanilla JS + Tailwind CDN) |
| `tests/test_pipeline.py` | Offline happy-path test |

---

## Production-readiness notes

- Config via `pydantic-settings` + `.env` — no secrets in code
- Structured `logging` on every LLM call (latency + token counts) and every failure
- `httpx` transport with built-in retries (`retries=2`) on transient errors
- Non-root user in the Dockerfile, slim pinned base image
- `/healthz` endpoint for orchestrator probes

---

## Troubleshooting

| Symptom | Fix |
|--------|-----|
| `ValidationError: openrouter_api_key Field required` on startup | `.env` is missing or not in the repo root. `cp .env.example .env` and fill it in. |
| `401 Unauthorized` from Jira / HubSpot / Teams | Tokens in `.env` don't match the dashboard. Regenerate at http://localhost:8080/dashboard and update `.env`. Restart the agent. |
| Agent container can't reach mock | Inside Docker, `MOCK_BASE_URL` is `http://host.docker.internal:8080` (set by `docker-compose.yml`) — Linux hosts need the `host-gateway` extra_hosts line, which is already included. For local `uvicorn` set `MOCK_BASE_URL=http://localhost:8080` in `.env`. |
| LLM returns invalid JSON | Surfaces as a per-row error in the UI — that message is skipped, the rest still process. Click Process again to retry. |
| Port 8000 or 8080 already in use | Stop the other process, or change the port mapping in `docker-compose.yml`. |

---

## What I'd do with more time

- Stream drafts to the UI as they're ready instead of batching (SSE)
- Cache HubSpot lookups by normalized client name across a run
- Per-draft audit log (prompt, raw LLM response, token usage) surfaced in the UI
- Retrieval-ranked shortlist + cross-encoder scoring for dedup when the Jira backlog grows large
- A real eval set (messages ↔ expected action) and a `pytest` suite that flags prompt regressions
