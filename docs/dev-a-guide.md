# Developer guide: Dev A (data and tools)

Welcome. This guide is everything you need to work on `field-sales-agent-reference`: what you build, what you can and cannot change in the repository, how to work with Claude Code, and how your work gets reviewed and merged.

Read first, in this order: `docs/architecture.md` (sections 1 to 7), `docs/contracts.md` (all of it), then this guide.

---

## 1. Your role

You build the **data and tools** side: everything the agents call.

| You own | Folder |
| --- | --- |
| Repository skeleton (Step 0) | root files, `docker-compose.yml`, `.env.example`, CI |
| Mock data and demo tokens | `mock-data/`, `scripts/make_token.py` |
| Sales MCP server | `services/mcp-sales/` |
| Context service | `services/context/` |

Dev B builds the agents in parallel against the same contracts. You do not need to wait for each other: you both build to `docs/contracts.md`.

The owner, Atilio Moreira (`@atiliosud`), owns the architecture and the contracts, reviews every pull request and merges.

## 2. What you can do in the repository

You are a collaborator with **Write** access on the owner's repository.

| You can | You cannot |
| --- | --- |
| Create branches and push to them | Push to `main` (it is protected) |
| Open pull requests and reply to review comments | Merge your own pull request: the owner merges |
| Comment on and review Dev B's pull requests | Change repository settings or add people |
| Open issues for questions or problems you find | Change `docs/contracts.md` without the owner's approval in a PR |

**Who changes what:**

| Area | Owner | Dev A (you) | Dev B |
| --- | --- | --- | --- |
| `docs/architecture.md`, `docs/contracts.md`, ADRs, README | Writes and approves | Proposes changes in a PR | Proposes changes in a PR |
| `services/mcp-sales/`, `services/context/`, `mock-data/`, `scripts/make_token.py` | Reviews | **Builds** | Reads only |
| `services/agent/`, `prompts/`, `evals/`, `scripts/chat.py` | Reviews | Reads only | Builds |
| `docker-compose.yml`, `.env.example`, root `pyproject.toml` | Reviews | **Creates in Step 0**; later changes only if the step needs it, said in the PR | Changes only if the step needs it |
| `.github/workflows/ci.yml` | Reviews | **Creates in Step 0** | Adds the eval job in Step 6 |

If you need something changed in Dev B's area, open an issue or comment on their PR. Do not edit their files.

## 3. Set-up on your machine

You need: Git, Docker Desktop (or Docker Engine with Compose), Python 3.12, `uv`, Claude Code, and access to the repository (accept the GitHub invitation).

```bash
git clone https://github.com/atiliosud/field-sales-agent-reference.git
cd field-sales-agent-reference
cp .env.example .env          # after Step 0 exists
docker compose up             # starts Postgres, Phoenix and the services
```

Your services do not call the model, so you do not need a model key. Never commit `.env`.

## 4. How you work

1. **Pick the issue** for your step (the owner creates one per step and assigns it to you).
2. **Create the branch** from an up-to-date `main`:
   ```bash
   git switch main && git pull
   git switch -c a/step-2-mcp-server
   ```
3. **Open Claude Code** in the repository and start with:
   *"Read CLAUDE.md, docs/poc-build-brief.md, docs/architecture.md, docs/contracts.md and docs/dev-a-guide.md."*
4. **Paste the prompt for your step** (section 5). Let Claude Code finish the step, then **read every file it changed**. You must be able to explain it.
5. **Run the checks** before pushing: ruff, the tests of your service and `docker compose up --build` to check everything still starts. The exact commands are in the README (written in Step 0).
6. **Commit** with a clear message, for example `feat(mcp-sales): add log_visit with confirmation`.
7. **Open a pull request** to `main`, fill in the template and write `Closes #<issue>`.
8. **Answer review comments** with new commits on the same branch. The owner merges.

Keep pull requests to one step. If a step grows, split it and say so in the PR.

## 5. Your steps

### Step 0: skeleton (Thursday) · branch `a/step-0-skeleton`

```text
Create the repository structure from section 5 of the brief. Give each service under services/ its own pyproject.toml with pinned dependencies, and a root pyproject.toml with ruff and pytest settings only. Add .env.example exactly as in contracts.md section 2, a .gitignore, and docker-compose.yml with Postgres, Arize Phoenix and all three services (agent, mcp-sales, context) with the ports from contracts.md section 1. Each service can start with a minimal health endpoint for now. Add .github/workflows/ci.yml running ruff and pytest for every service. Add a short "Development" section to README.md with the commands to run ruff and the tests, per service and for the whole repository. Show me the tree and the compose file. Do not write business logic yet.
```

**Done when:** `docker compose up` starts everything; Phoenix opens on port 6006; each service answers on its health endpoint; CI is green.

This step unblocks Dev B, so open the PR as early as you can.

### Step 1: mock data and tokens (Friday) · branch `a/step-1-mock-data`

```text
Following brief section 6.1 and contracts.md sections 3 and 4, create the mock data files with exactly the identifiers in contracts.md (sp-001/sp-002, c-001 to c-010, c-001 = Nordic Tools, P-101 to P-120). Create scripts/make_token.py with the claims in contracts.md section 3. Add tests: every opportunity points to an existing customer, every customer has a valid owner, and a generated token decodes with the right claims.
```

**Done when:** data matches the identifiers in the contract; `python scripts/make_token.py sp-001` prints a valid token; tests pass.

### Step 2: sales MCP server (Friday) · branch `a/step-2-mcp-server`

```text
Following brief section 6.2 and contracts.md sections 5 and 6, build services/mcp-sales with FastMCP over streamable HTTP at /mcp on port 8001. Implement the five tools with exactly the inputs, outputs and error codes in the contract. Validate the JWT on every call. Write tools return CONFIRMATION_REQUIRED unless confirmed is true. Add tool spans and the business events from contracts.md section 9, propagating traceparent. Tests: no token, wrong owner, each read tool, write tools with and without confirmation, and one test per error code.
```

**Done when:** all five tools follow the contract; `sp-001` cannot read `c-006`; write tools refuse without confirmation; spans and business events appear in Phoenix; tests pass.

### Step 3: context service (Saturday) · branch `a/step-3-context`

```text
Following brief section 6.3 and contracts.md section 7, build services/context with FastAPI, SQLAlchemy async and Alembic on port 8002. Implement every endpoint in the contract, the per-agent context slice, the X-Agent-Role check (only orchestrator writes facts) and optimistic concurrency with If-Match returning 409 CONFLICT. A salesperson can only access their own conversations. Tests: the two context slices, a version conflict, a specialist trying to write a fact, and access to another salesperson's conversation.
```

**Done when:** every endpoint follows the contract; the two slices return the right fields; a specialist cannot write facts; a stale `If-Match` returns 409; migrations run on start; tests pass.

### Integration (Sunday, with Dev B)

1. Dev B points the agent at your real services.
2. Run the demo script (brief section 8) end to end.
3. Fix any mismatch in the service that broke the contract. If the contract itself is wrong, open a PR to `docs/contracts.md` and the owner decides.

## 6. Rules that are never broken

- Build to `docs/contracts.md` exactly. Do not rename fields, codes or endpoints.
- Authorisation lives in your services, by data ownership. Never trust the caller to filter data.
- No real company or client names anywhere: code, data, commits, docs.
- No secrets in git. No tokens, contact details or free-text notes in logs or span attributes.
- Write tools refuse unless `confirmed` is true.
- Only `X-Agent-Role: orchestrator` writes facts.
- No dead code, no leftover scaffolding, no comments that repeat the code.

## 7. Questions

- About your step or the contract: comment on the issue or the PR, and tag `@atiliosud`.
- If the contract looks wrong: stop, write the question down, and do not work around it in code.
- Anything confidential (keys, access): only in a private message to the owner, never in the repository.
