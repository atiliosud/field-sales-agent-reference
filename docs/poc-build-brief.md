# field-sales-agent-reference: build brief

Version: 7 October 2026 · Owner: Atilio Moreira

## 1. What this is

A small, public reference project: an AI assistant for field salespeople that looks up customers, opportunities and stock, and logs visits. It runs locally with mock data.

It shows six architecture ideas in working code:

1. **Shared context between agents.** One context service per conversation, so text and (later) voice see the same turns, facts and artefacts.
2. **MCP tools with the user's identity.** Every tool call carries the salesperson's token; a salesperson only sees their own customers.
3. **Multi-agent with a harness.** An orchestrator agent and a specialist agent, with tool allow-lists, a step limit and timeouts.
4. **One trace per conversation.** OpenTelemetry spans for every model and tool call, plus business events (`visit_logged`, `lead_created`).
5. **No evals, no release.** A set of real-style sales questions runs in CI and blocks the merge if quality drops.
6. **Decisions written down.** An architecture diagram and four short ADRs.

Target: working end to end on a laptop with `docker compose up`, a 5-minute demo, and code the owner can explain file by file.

## 2. Ground rules

- **Contracts first.** The interfaces between components are fixed in `docs/contracts.md`. Build against them; change them only through a pull request reviewed by the owner.
- **Two developers, one owner.** The work is split in `docs/team-plan.md`. The owner reviews and merges every pull request.

- **Generic only.** No real company names, no client details, no code or data from any employer. All data is invented.
- **Small on purpose.** Five components, one language (Python), no extra frameworks. If a feature is not in this brief, it goes to "Not done yet".
- **Every file must be explainable.** No unused code, no boilerplate left behind, no comments that repeat the code.
- **Commit per step,** with clear messages. No single giant commit.
- **Honest README.** Say what works, what does not, and that the project was built with Claude Code as a pair, with every change reviewed by the owner.
- **Secrets stay out of git.** `.env` is ignored; `.env.example` documents the variables.
- **Cost cap.** Set a monthly spending limit on the model account. Evals in CI run only on request (see section 9).
- **British English** in all documentation.

## 3. Architecture

The full design is in `docs/architecture.md`. The diagram is in `docs/architecture.drawio`. Export it as `docs/architecture.svg` with "Include a copy of my diagram" ticked, so GitHub shows it and it stays editable.

**Request flow, one chat turn:**

1. The salesperson sends a message through the chat client, with a JWT that identifies them.
2. The agent service loads the context slice for this conversation from the context service.
3. The orchestrator decides: answer directly, hand off to the specialist, or ask the user to confirm an action.
4. The specialist calls MCP tools on the sales MCP server, forwarding the user's JWT. The server filters data by salesperson.
5. Write actions (`log_visit`, `create_lead`) need an explicit "yes" from the user first.
6. The orchestrator writes the turn, any new facts (for example, the customer in focus) and any artefacts back to the context service.
7. Every step produces OpenTelemetry spans, sent to Arize Phoenix. Write actions also emit a business event.

**Components:**

| Component | Folder | Port | Role |
| --- | --- | --- | --- |
| Sales MCP server | `services/mcp-sales` | 8001 | Six tools over mock CRM/ERP data, JWT check per call |
| Context service | `services/context` | 8002 | Turns, facts and artefacts per conversation, in Postgres |
| Agent service | `services/agent` | 8000 | LangGraph orchestrator and specialist, harness, chat API |
| Postgres | (docker) | 5432 | Context storage |
| Arize Phoenix | (docker) | 6006 | Trace UI and OTLP endpoint |

## 4. Tech stack

- Python 3.12, dependencies managed with `uv` (or pip), versions pinned. One `pyproject.toml` per service; the root one only holds ruff and pytest settings.
- FastAPI and Uvicorn for the HTTP services.
- LangGraph for the agents; `langchain-openai` for the model client.
- MCP Python SDK (FastMCP) for the server, streamable HTTP transport; `langchain-mcp-adapters` to load the tools into LangGraph.
- PyJWT for tokens (HS256 with a local secret, demo only).
- Postgres 16 with SQLAlchemy (async) and Alembic for the schema.
- OpenTelemetry SDK with OTLP export; OpenInference instrumentation for LangChain/LangGraph so model calls, tokens and cost show in Phoenix.
- pytest, ruff, GitHub Actions.
- Model: Azure OpenAI (or Microsoft Foundry) through environment variables. Keep the model behind one small factory function, so a gateway (LiteLLM) or Amazon Bedrock can be added later without touching the agents.

## 5. Repository structure

```text
field-sales-agent-reference/
├── README.md
├── CLAUDE.md                     # rules for Claude Code in this repo
├── docker-compose.yml
├── .env.example
├── pyproject.toml                # ruff and pytest settings only
├── docs/
│   ├── architecture.md
│   ├── contracts.md
│   ├── team-plan.md
│   ├── dev-a-guide.md
│   ├── dev-b-guide.md
│   ├── architecture.drawio
│   ├── architecture.svg
│   └── adr/
│       ├── 0001-shared-context-service.md
│       ├── 0002-mcp-tools-with-user-identity.md
│       ├── 0003-eval-gate-in-ci.md
│       └── 0004-model-behind-a-factory.md
├── mock-data/
│   ├── salespeople.json
│   ├── customers.json
│   ├── opportunities.json
│   └── stock.json
├── prompts/
│   ├── orchestrator.v1.yaml
│   └── specialist.v1.yaml
├── services/
│   ├── mcp-sales/
│   ├── context/
│   └── agent/
├── evals/
│   ├── cases.yaml
│   └── run.py
├── scripts/
│   ├── make_token.py
│   └── chat.py
├── tests/
└── .github/
    ├── workflows/ci.yml
    ├── CODEOWNERS
    └── pull_request_template.md
```

## 6. Component details

### 6.1 Mock data

- `salespeople.json`: two salespeople, `sp-001` (region North) and `sp-002` (region South).
- `customers.json`: ten customers, each with `id`, `name`, `segment`, `region` and `owner` (salesperson id). Five per salesperson.
- `opportunities.json`: about fifteen opportunities with `id`, `customer_id`, `product_code`, `value_eur`, `stage` (open, quoted, won, lost) and `next_step`.
- `stock.json`: about twenty product lines with `product_code`, `name`, `warehouse`, `region` and `quantity`.
- Visits and leads are written to an in-memory store in the MCP server (or a JSON file under `mock-data/runtime/`, git-ignored).

### 6.2 Sales MCP server (`services/mcp-sales`)

Six tools, each with a clear description and typed inputs:

| Tool | Type | What it does |
| --- | --- | --- |
| `get_customer(customer_id)` | read | Customer details, only if owned by the caller |
| `find_customer(name)` | read | The caller's customers whose name contains the text; a customer of someone else looks the same as one that does not exist |
| `list_opportunities(customer_id, stage?)` | read | Opportunities for a customer owned by the caller |
| `check_stock(product_code, region?)` | read | Stock by warehouse; defaults to the caller's region |
| `log_visit(customer_id, summary, outcome, confirmed)` | write | Records a visit; refuses unless `confirmed` is true |
| `create_lead(company_name, contact, notes, confirmed)` | write | Records a new lead; refuses unless `confirmed` is true |

- Read the `Authorization: Bearer <JWT>` header on every call, validate it and get `salesperson_id`. No token or a bad token means an error, not empty data.
- A customer owned by someone else returns a clear "not allowed" error.
- Every tool call creates a span with `tool.name`, `salesperson.id` and `customer.id` (when present).
- `log_visit` and `create_lead` add a span event `business.visit_logged` or `business.lead_created`.

### 6.3 Context service (`services/context`)

Postgres tables:

- `conversations`: `id`, `salesperson_id`, `created_at`.
- `turns`: `id`, `conversation_id`, `channel` (text or voice), `role` (user, orchestrator, specialist), `content`, `created_at`.
- `facts`: `conversation_id`, `key`, `value` (jsonb), `version`, `updated_by`, `updated_at`. Example keys: `current_customer`, `pending_action`.
- `artifacts`: `id`, `conversation_id`, `type` (for example, `visit_summary`), `payload` (jsonb), `created_at`.

Endpoints:

- `POST /conversations` creates a conversation for the caller.
- `GET /conversations/{id}/context?agent=orchestrator|specialist` returns only what that agent needs: the orchestrator gets recent turns and all facts; the specialist gets the task, `current_customer` and nothing else.
- `POST /conversations/{id}/turns` appends a turn.
- `PUT /conversations/{id}/facts/{key}` writes a fact. It requires the header `X-Agent-Role: orchestrator` and an `If-Match` version, so two writers cannot overwrite each other.
- `POST /conversations/{id}/artifacts` stores an artefact.

The `channel` column is what lets voice join later: the voice session writes turns to the same conversation.

### 6.4 Agent service (`services/agent`)

- **Graph:** `orchestrator` → (`specialist` | `confirm` | `respond`). The specialist returns its result to the orchestrator, never to the user directly.
- **Orchestrator:** owns the conversation, decides the route, writes facts, and asks for confirmation before any write action. It has no data tools.
- **Specialist:** sales data agent. Tool allow-list: all six MCP tools, but write tools only run when the orchestrator passes `confirmed: true`.
- **Harness (in `harness.py`, from config):** maximum 6 steps per turn, 10 seconds per tool call, 60 seconds per turn. When a limit hits, the agent says it could not finish and the span records why.
- **Prompts:** loaded from `prompts/*.yaml` by version (`orchestrator.v1`, `specialist.v1`). The active versions come from config, and each model span carries `prompt.id` and `prompt.version`.
- **Context:** load the slice before each turn, save the turn and facts after it.
- **API:** `POST /chat` with body `{conversation_id?, message}` and the user's JWT. Returns the answer, the conversation id and, when relevant, a pending action waiting for confirmation.
- **CLI client:** `scripts/chat.py --as sp-001` for the demo.

### 6.5 Observability

- OTLP export to Phoenix at `http://phoenix:6006/v1/traces`.
- OpenInference instrumentation for LangChain/LangGraph covers model calls, tokens and cost.
- Set `session.id` = conversation id on every span, so Phoenix groups a whole conversation.
- Custom spans for tool calls in the MCP server, and business events as span events.
- Never put the JWT or full personal data in span attributes.

### 6.6 Evals (`evals/`)

`cases.yaml` holds about 25 cases, in five groups:

| Group | Example | Check |
| --- | --- | --- |
| Lookup | "What's open with Nordic Tools?" | Calls `list_opportunities`; answer names the open opportunities |
| Stock | "Do we have product P-104 in the South?" | Calls `check_stock`; answer has the right quantity |
| Write with confirmation | "Log a visit to Nordic Tools, they want a quote" | Asks for confirmation first; logs only after "yes" |
| Out of scope | "What discount should I give?" | Does not invent a policy; says it cannot decide that |
| Security | sp-001 asks about a customer owned by sp-002 | No data from the other salesperson in the answer |

- `run.py` runs each case against the agent, checks the expected tool calls and answer content with simple rules (no LLM judge, so results are repeatable), and writes `evals/report.md`.
- Pass rate below 85% exits with an error.

### 6.7 CI (`.github/workflows/ci.yml`)

- On every push and pull request: ruff, unit tests and integration tests with a fake model.
- Eval job: runs on pull requests with the label `run-evals` or by manual trigger. It starts the stack with docker compose, uses the model key from GitHub secrets, runs `evals/run.py` and uploads the report. This keeps cost under control.

### 6.8 Documentation

- **README:** Problem · What this shows · Architecture (the SVG) · Decisions (links to ADRs) · How to run · Demo script · Not done yet · How it was built (Claude Code as a pair, every change reviewed).
- **ADRs** (one page each): Context · Decision · Options considered · Consequences · What I would do next.
    - 0001 Shared context service instead of passing full history between agents.
    - 0002 MCP tools that act with the user's identity, with an allow-list per agent.
    - 0003 Eval gate in CI, rule-based first.
    - 0004 Model behind a factory, ready for a gateway and a second provider.

## 7. Build plan with Claude Code

With two developers, use the split in `docs/team-plan.md` and the prompts in `docs/dev-a-guide.md` and `docs/dev-b-guide.md`; they follow these steps but name the owner of each and the exact contract to build against.

One step per session, one commit per step. Start every session by asking Claude Code to read `CLAUDE.md` and this brief.

**Step 0: set-up (Wednesday).**

```text
Read CLAUDE.md and docs/poc-build-brief.md. Create the repository structure from section 5, pyproject.toml with pinned dependencies, .env.example, .gitignore and a docker-compose.yml with Postgres and Arize Phoenix only. Do not write service code yet. Show me the tree and the compose file.
```

Done when: `docker compose up` starts Postgres and Phoenix, and the Phoenix UI opens on port 6006.

**Step 1: mock data and tokens (Wednesday).**

```text
Following section 6.1, create the mock data files and scripts/make_token.py, which prints an HS256 JWT for sp-001 or sp-002 using JWT_SECRET from .env. Keep the data small and realistic. Add a test that checks every opportunity points to an existing customer.
```

**Step 2: sales MCP server (Thursday).**

```text
Following section 6.2, build services/mcp-sales with FastMCP over streamable HTTP on port 8001. Validate the JWT on every call and filter by salesperson. Write tools refuse unless confirmed is true. Add the spans and business events from section 6.5. Write tests for: no token, wrong owner, each read tool, and write tools with and without confirmation. Add the service to docker-compose.
```

**Step 3: context service (Friday).**

```text
Following section 6.3, build services/context with FastAPI, SQLAlchemy async and Alembic. Implement the endpoints, the per-agent context slice and optimistic concurrency on facts with If-Match. Only X-Agent-Role orchestrator may write facts. Write tests for the slice and for a version conflict. Add the service to docker-compose.
```

**Step 4: agent service (Friday).**

```text
Following section 6.4, build services/agent with LangGraph: orchestrator, specialist, confirm and respond nodes, the harness limits from config, prompts loaded by version from prompts/, MCP tools via langchain-mcp-adapters with the user's JWT forwarded, and context loaded before and saved after each turn. Put the model behind one factory function reading AZURE_OPENAI_* variables. Add POST /chat and scripts/chat.py. Write integration tests with a fake model.
```

**Step 5: observability (Saturday).**

```text
Following section 6.5, wire OpenTelemetry and OpenInference into the agent service and the MCP server, exporting to Phoenix. Set session.id to the conversation id. Make sure prompt.id and prompt.version are on model spans and that no token or personal data goes into attributes. Tell me how to see one full conversation in Phoenix.
```

**Step 6: evals and CI (Saturday).**

```text
Following sections 6.6 and 6.7, write evals/cases.yaml with about 25 cases across the five groups, evals/run.py with rule-based checks and an 85% threshold, and .github/workflows/ci.yml with lint, tests and an eval job that runs on the run-evals label or manual trigger.
```

**Step 7: documentation (Sunday).** Write this step yourself, with Claude Code only reviewing: README, the four ADRs and the exported SVG. The ADRs should sound like you, because you will defend them in an interview.

```text
Review README.md and docs/adr/ for accuracy against the code. List anything that claims more than the code does, and anything missing from "Not done yet". Do not rewrite my wording; only point out problems.
```

**Step 8: rehearse the demo (Sunday).** Run the demo script in section 8 twice from a clean `docker compose up`.

## 8. Demo script (5 minutes)

1. `docker compose up`, then `python scripts/chat.py --as sp-001`.
2. Ask "What's open with Nordic Tools?" and show the answer.
3. Ask "Do we have P-104 in the South?"
4. Say "Log a visit to Nordic Tools, they asked for a quote." Show that it asks for confirmation, then answer "yes".
5. Ask about a customer owned by sp-002 and show that no data leaks.
6. Open Phoenix: one trace for the conversation, model and tool spans, prompt version, tokens, and the `business.visit_logged` event.
7. Show the last eval report and one ADR.

## 9. Not done yet (for the README)

- Voice through a realtime model, writing turns to the same context service.
- A web front end using AG-UI events.
- A model gateway (LiteLLM) to compare Microsoft Foundry and Amazon Bedrock with the same evals.
- Deployment on AWS ECS Fargate with Terraform.
- Real identity (Entra ID or Cognito) instead of local HS256 tokens.

## 10. Cautions

- Build it in your own time, on your own equipment.
- No names or details from any employer or client in code, data, commits or docs.
- Keep `.env` out of git and set a spending limit on the model account.
- In an interview, offer the demo at the end; do not force it. Send the link in the follow-up.
