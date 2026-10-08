# field-sales-agent-reference

An AI assistant for field salespeople that looks up customers, opportunities and stock, and logs visits. It runs locally with mock data.

## Development

You need Docker with Compose, Python 3.12 and [uv](https://docs.astral.sh/uv/).

### Run the stack

```bash
cp .env.example .env
docker compose up --build
```

| What | Where |
| --- | --- |
| Agent service | http://localhost:8000/health |
| Sales MCP server | http://localhost:8001/health (MCP at `/mcp`) |
| Context service | http://localhost:8002/health |
| Arize Phoenix | http://localhost:6006 |

### Lint

Ruff is pinned in CI; use the same version locally.

```bash
uvx ruff@0.16.8 check .                    # whole repository
uvx ruff@0.16.8 format --check .
uvx ruff@0.16.8 check services/agent       # one service
```

### Tests

Each service has its own environment. Run the tests from the service folder:

```bash
cd services/agent && uv run pytest         # one service
```

All services:

```bash
for s in services/*/; do (cd "$s" && uv run pytest) || exit 1; done
```

The mock data and the demo token script are tested from the repository root, with their own environment in `scripts/`:

```bash
uv run --project scripts pytest tests
```

### Demo token

Print a token for a salesperson (`sp-001` or `sp-002`). The script reads `JWT_SECRET` from the environment or from `.env`:

```bash
uv run --project scripts python scripts/make_token.py sp-001
```

### Chat client

With the stack running and the `AZURE_OPENAI_*` values in `.env`, chat as a salesperson. Type `yes` to confirm a pending action and `exit` to leave:

```bash
uv run --project scripts python scripts/chat.py --as sp-001
```
