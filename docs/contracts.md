# Contracts

The interfaces between the components. Both developers build against this file. Change it only through a pull request reviewed by Atilio, and say in the PR what breaks.

## 1. Ports and services

| Service | Folder | Port | OTel service name |
| --- | --- | --- | --- |
| Agent service | `services/agent` | 8000 | `agent-service` |
| Sales MCP server | `services/mcp-sales` | 8001 (path `/mcp`) | `mcp-sales` |
| Context service | `services/context` | 8002 | `context-service` |
| Postgres | docker | 5432 | – |
| Arize Phoenix | docker | 6006 (UI and OTLP HTTP at `/v1/traces`) | – |

## 2. Environment variables (`.env.example`)

```text
JWT_SECRET=change-me
DATABASE_URL=postgresql+asyncpg://fsa:fsa@postgres:5432/fsa
MCP_URL=http://mcp-sales:8001/mcp
CONTEXT_URL=http://context:8002
OTEL_EXPORTER_OTLP_ENDPOINT=http://phoenix:6006/v1/traces
AZURE_OPENAI_ENDPOINT=
AZURE_OPENAI_API_KEY=
AZURE_OPENAI_DEPLOYMENT=
AZURE_OPENAI_API_VERSION=
PROMPT_ORCHESTRATOR=orchestrator.v4
PROMPT_SPECIALIST=specialist.v3
HARNESS_MAX_STEPS=6
HARNESS_TOOL_TIMEOUT_S=10
HARNESS_TURN_TIMEOUT_S=60
```

## 3. Identity (JWT)

- Algorithm HS256, signed with `JWT_SECRET`. Demo only.
- Claims: `sub` (salesperson id, `sp-001` or `sp-002`), `name`, `region` (`North` or `South`), `iss` = `field-sales-demo`, `exp` (8 hours).
- Sent as `Authorization: Bearer <token>` on every call: chat client → agent → MCP server and context service.
- `scripts/make_token.py sp-001` prints a valid token.

## 4. Mock data identifiers

- Salespeople: `sp-001` (North), `sp-002` (South).
- Customers: `c-001` to `c-005` owned by `sp-001`; `c-006` to `c-010` owned by `sp-002`. `c-001` is "Nordic Tools" (used in the demo and evals).
- Products: `P-101` to `P-120`. `P-204` does not exist; use `P-104` in the demo.
- Opportunity stages: `open`, `quoted`, `won`, `lost`.

## 5. Error format (all services)

```json
{ "error": { "code": "FORBIDDEN", "message": "Customer c-006 is not assigned to you." } }
```

Codes: `UNAUTHENTICATED`, `FORBIDDEN`, `NOT_FOUND`, `INVALID_INPUT`, `CONFIRMATION_REQUIRED`, `CONFLICT`, `INTERNAL`. `INTERNAL` means an unexpected failure; its message is always generic and never carries internal detail. In MCP, return the same JSON as the tool result text with `isError: true`.

## 6. Sales MCP server: tools

Server name `sales`, streamable HTTP at `/mcp`. Every tool reads the JWT from the request headers.

### `get_customer`
- Input: `customer_id: str`
- Output: `{ "id", "name", "segment", "region", "owner" }`
- Errors: `UNAUTHENTICATED`, `NOT_FOUND`, `FORBIDDEN` (not the caller's customer)

### `find_customer`
- Input: `name: str` (part of a name; case does not matter)
- Output: `{ "customers": [ { "id", "name" } ] }`, only customers owned by the caller; an empty list when none matches
- Errors: `UNAUTHENTICATED`, `INVALID_INPUT` (empty name). A customer of another salesperson gives the same empty list as one that does not exist, never `FORBIDDEN` or `NOT_FOUND`

### `list_opportunities`
- Input: `customer_id: str`, `stage?: "open" | "quoted" | "won" | "lost"`
- Output: `{ "customer_id", "opportunities": [ { "id", "product_code", "value_eur", "stage", "next_step" } ] }`
- Errors: as `get_customer`

### `check_stock`
- Input: `product_code: str`, `region?: "North" | "South"` (defaults to the caller's region)
- Output: `{ "product_code", "name", "region", "warehouses": [ { "warehouse", "quantity" } ], "total" }`
- Errors: `UNAUTHENTICATED`, `NOT_FOUND`

### `search_products`
- Input: `query: str` (words; case and accents do not matter, each word may match part of a word in the name or description), `in_stock_only?: bool` (default false; keeps products with stock in the caller's region), `customer_id?: str`
- Output: `{ "query", "customer_id", "products": [ { "product_code", "name", "description", "unit_price_eur"? } ] }`. Products have no owner, so the search is open to every salesperson. `unit_price_eur` is the price on the price list of `customer_id` and is present only when `customer_id` is given; it is `null` for a product that is not on that list. Without `customer_id` the result carries no price at all
- Errors: `UNAUTHENTICATED`, `INVALID_INPUT` (empty query), and for a `customer_id`: `NOT_FOUND`, `FORBIDDEN` (not the caller's customer; no product and no price is returned)

### `log_visit` (write)
- Input: `customer_id: str`, `summary: str` (max 500 chars), `outcome: "positive" | "neutral" | "negative" | "follow_up"`, `confirmed: bool`
- Output: `{ "visit_id", "customer_id", "logged_at" }`
- Errors: `CONFIRMATION_REQUIRED` when `confirmed` is false, plus those of `get_customer`
- Span event: `business.visit_logged` with `customer.id`

### `create_lead` (write)
- Input: `company_name: str`, `contact: str`, `notes: str`, `confirmed: bool`
- Output: `{ "lead_id", "company_name", "created_at" }`
- Errors: `CONFIRMATION_REQUIRED`, `UNAUTHENTICATED`, `INVALID_INPUT`
- Span event: `business.lead_created`

## 7. Context service: API

Base URL `CONTEXT_URL`. Every call needs the JWT; a salesperson can only read and write their own conversations. Every call also sends `X-Agent-Role: orchestrator` or `X-Agent-Role: specialist`.

| Method and path | Body | Response |
| --- | --- | --- |
| `POST /conversations` | – | `201 { "id", "salesperson_id", "created_at" }` |
| `GET /conversations/{id}/context?agent=orchestrator` | – | `200 { "conversation_id", "turns": [last 10], "facts": { key: { "value", "version" } }, "artifacts": [...] }` |
| `GET /conversations/{id}/context?agent=specialist` | – | `200 { "conversation_id", "facts": { "current_customer"?: {...} } }` |
| `POST /conversations/{id}/turns` | `{ "channel": "text" \| "voice", "role": "user" \| "orchestrator" \| "specialist", "content" }` | `201 { "id", "created_at" }` |
| `PUT /conversations/{id}/facts/{key}` | `{ "value": <json> }`, header `If-Match: <version>` (0 for a new fact) | `200 { "key", "value", "version" }`; `403` unless role is orchestrator; `409 CONFLICT` on a version mismatch |
| `POST /conversations/{id}/artifacts` | `{ "type", "payload": <json> }` | `201 { "id" }` |

Fact keys in use: `current_customer`, `pending_action`.

A fact is cleared with `PUT` and `{ "value": null }` and the current `If-Match`. The version keeps rising. The orchestrator slice lists a cleared fact with `"value": null` and its version, so that the next write can send the right `If-Match`; callers treat a `null` value as no fact. The specialist slice leaves cleared facts out.

## 8. Agent service: API

`POST /chat` with the JWT.

- Body: `{ "conversation_id"?: str, "message": str, "confirm"?: bool }`
- Response: `{ "conversation_id", "answer", "pending_action"?: { "tool", "summary" } }`

**Confirmation flow:** when a write is needed, the orchestrator saves `pending_action` as a fact and returns it without calling the tool. The next request with `confirm: true` (or a clear "yes") runs the tool with `confirmed: true` and clears the fact.

## 9. Tracing

- Propagate the W3C `traceparent` header from the agent to the MCP server and the context service, so one turn is one trace across services.
- On every span: `session.id` = conversation id, `user.id` = salesperson id.
- The agent sends the header `X-Session-Id: <conversation id>` on every call to the MCP server. The MCP server sets `session.id` from it on its spans; without the header, the span has no `session.id`. The context service does not need the header, because the conversation id is in the URL.
- All three services follow the OpenInference conventions on their spans, so that Phoenix shows one consistent trace. In particular, tool spans carry `openinference.span.kind` = `TOOL`.
- Model spans: `prompt.id`, `prompt.version` (tokens and cost come from OpenInference).
- Tool spans: `tool.name`, `customer.id` when present.
- When the harness stops a turn: `harness.limit` = `max_steps`, `tool_timeout` or `turn_timeout`.
- Never put the token, contact details or free-text notes in attributes.
