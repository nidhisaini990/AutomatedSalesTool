# AI Sales Agent MVP

A compact, runnable FastAPI MVP for a workspace-isolated AI sales workflow. It is deliberately
transparent: discovery, enrichment, and email delivery use deterministic local mock providers and
make **no external network calls**.

## Included

- Password hashing (PBKDF2-SHA256) and signed, expiring HS256 bearer JWTs
- UUID primary keys and UTC creation/update timestamps on all domain records
- Workspace membership checks on every workspace resource
- Mock discovery with source IDs and provenance; mock enrichment and email provider interfaces
- Deterministic lead scores with a persisted, human-readable factor breakdown
- Campaign recipient creation and dispatch that never sends to suppressed leads
- Deterministic reply classification; opt-outs suppress immediately and positive/objection replies
  schedule a follow-up
- A small browser UI at `/` and interactive OpenAPI docs at `/docs`

## Run locally

Requires Python 3.11+.

```bash
cp .env.example .env
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open <http://localhost:8000>. SQLite (`sales_agent.db`) is the default local database. The API
creates tables automatically on start.

## Run with PostgreSQL

The application accepts normal SQLAlchemy URLs, including `postgresql+psycopg://...` and common
`postgres://...` URLs. Start the included local stack with:

```bash
docker compose up --build
```

Compose uses example development credentials only. Set a unique `JWT_SECRET` and real database
credentials before any non-local deployment.

## API workflow

All endpoints below except registration/login need an `Authorization` header using the JWT bearer
scheme.

1. `POST /api/auth/register` with `{"email":"rep@example.test","password":"at-least-8-chars"}`
2. `POST /api/workspaces` with `{"name":"Sales"}`
3. `POST /api/workspaces/{workspace_id}/discover` with `{"query":"B2B SaaS","limit":5}`
4. Optionally `POST /api/workspaces/{workspace_id}/leads/{lead_id}/enrich`
5. `POST /api/workspaces/{workspace_id}/campaigns` with a name and `lead_ids`
6. Review a sequence draft at `GET /api/workspaces/{workspace_id}/campaigns/{campaign_id}`
7. `POST /api/workspaces/{workspace_id}/campaigns/{campaign_id}/dispatch`
8. Send incoming content to `POST /api/workspaces/{workspace_id}/replies`.

`GET /api/workspaces/{workspace_id}/leads` exposes each lead's provenance, score, and score
explanation. Suppress a lead using
`POST /api/workspaces/{workspace_id}/leads/{lead_id}/suppress`; suppression is checked both while
creating recipients and immediately before mock dispatch.

Replies are deterministically classified as interested, meeting requested, pricing requested, more
information, follow up later, not interested, unsubscribe, out of office, or unknown. Actionable
positive replies schedule a follow-up; unsubscribe replies suppress the lead immediately.

## Test

```bash
pytest -q
```

The focused suite verifies workspace isolation, provenance/scoring, enrichment, campaign
suppression enforcement, reply classification, opt-out behavior, and automatic follow-ups.