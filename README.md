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
