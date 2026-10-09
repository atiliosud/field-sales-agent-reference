# Developer guide: Dev B (agents)

Welcome. This guide is everything you need to work on `field-sales-agent-reference`: what you build, what you can and cannot change in the repository, how to work with Claude Code, and how your work gets reviewed and merged.

Read first, in this order: `docs/architecture.md` (all of it, especially sections 6.1, 7 and 9), `docs/contracts.md` (all of it), then this guide.

---

## 1. Your role

You build the **agents** side: the part that talks to the user and decides what to do.

| You own | Folder |
| --- | --- |
| Agent service: orchestrator, specialist, graph, confirmation flow, chat API | `services/agent/` |
| The harness (limits), together with the owner | `services/agent/harness.py` |
| Versioned prompts | `prompts/` |
| Chat CLI for the demo | `scripts/chat.py` |
| Tracing in the agent service | `services/agent/` |
| Evals and the eval job in CI | `evals/`, `.github/workflows/ci.yml` (eval job only) |

Dev A builds the MCP server and the context service in parallel. You do **not** wait for them: you start against test fakes that follow `docs/contracts.md`, and switch to the real services on Sunday.

The owner, Atilio Moreira (`@atiliosud`), owns the architecture and the contracts, reviews every pull request and merges.

## 2. What you can do in the repository

You are a collaborator with **Write** access on the owner's repository.

| You can | You cannot |
| --- | --- |
| Create branches and push to them | Push to `main` (it is protected) |
| Open pull requests and reply to review comments | Merge your own pull request: the owner merges |
| Comment on and review Dev A's pull requests | Change repository settings or add people |
| Open issues for questions or problems you find | Change `docs/contracts.md` without the owner's approval in a PR |

**Who changes what:**

| Area | Owner | Dev A | Dev B (you) |
| --- | --- | --- | --- |
| `docs/architecture.md`, `docs/contracts.md`, ADRs, README | Writes and approves | Proposes changes in a PR | Proposes changes in a PR |
| `services/mcp-sales/`, `services/context/`, `mock-data/`, `scripts/make_token.py` | Reviews | Builds | Reads only |
| `services/agent/`, `prompts/`, `evals/`, `scripts/chat.py` | Reviews | Reads only | **Builds** |
| `docker-compose.yml`, `.env.example`, root `pyproject.toml` | Reviews | Creates in Step 0 | Changes only if the step needs it, said in the PR |
| `.github/workflows/ci.yml` | Reviews | Creates in Step 0 | **Adds the eval job** in Step 6 |

If you need something changed in Dev A's area, open an issue or comment on their PR. Do not edit their files.

## 3. Set-up on your machine

You need: Git, Docker Desktop (or Docker Engine with Compose), Python 3.12, `uv`, Claude Code, and access to the repository (accept the GitHub invitation).

```bash
git clone https://github.com/atiliosud/field-sales-agent-reference.git
cd field-sales-agent-reference
cp .env.example .env          # after Step 0 is merged
docker compose up
```

**Model key:** your tests use a fake model and need no key. For manual runs, the owner sends you the `AZURE_OPENAI_*` values in a private message. The account has a spending limit. Put them only in your local `.env`, never in git, chat logs, issues or screenshots.

## 4. How you work

1. **Pick the issue** for your step (the owner creates one per step and assigns it to you).
2. **Create the branch** from an up-to-date `main`:
   ```bash
   git switch main && git pull
   git switch -c b/step-4-agent
   ```
3. **Open Claude Code** in the repository and start with:
   *"Read CLAUDE.md, docs/poc-build-brief.md, docs/architecture.md, docs/contracts.md and docs/dev-b-guide.md."*
4. **Paste the prompt for your step** (section 5). Let Claude Code finish the step, then **read every file it changed**. You must be able to explain it.
5. **Run the checks** before pushing: ruff, the tests of the agent service and `docker compose up --build`. The exact commands are in the README (written in Step 0).
6. **Commit** with a clear message, for example `feat(agent): add confirmation flow for write tools`.
7. **Open a pull request** to `main`, fill in the template and write `Closes #<issue>`.
8. **Answer review comments** with new commits on the same branch. The owner merges.

Keep pull requests to one step. Step 4 is the largest; if it grows, split it (for example graph and fakes first, then confirmation flow and harness) and say so in the PR.

## 5. Your steps

### Step 4: agent service (Friday) · branch `b/step-4-agent`

**Before you write `harness.py`**, open a draft PR with a short description of the harness design and tag `@atiliosud`: which limits, where each one is enforced, and what the user sees when one hits. Start coding the harness after the owner agrees.

```text
Following brief section 6.4, architecture.md sections 6.1 and 7, and contracts.md sections 6, 7 and 8, build services/agent with LangGraph: orchestrator, specialist, confirm and respond nodes. The real MCP server and context service are being built in parallel, so first create test fakes that follow the contract exactly: an in-memory fake MCP server with the same six tools and error codes, returning fixtures, and a fake context client with the same endpoints. Then build:
- the harness in harness.py, reading HARNESS_* from config (max steps, tool timeout, turn timeout); when a limit hits, the agent says it could not finish;
- prompts loaded by version from prompts/ using PROMPT_ORCHESTRATOR and PROMPT_SPECIALIST;
- MCP tools via langchain-mcp-adapters, forwarding the user's JWT;
- the confirmation flow from contracts.md section 8, using the pending_action fact;
- context loaded before and saved after each turn; only the orchestrator writes facts;
- the model behind one factory function reading AZURE_OPENAI_*;
- POST /chat and scripts/chat.py --as sp-001.
Write tests with a fake model and the fakes, covering routing, the confirmation flow and each harness limit. Keep the fakes in tests/fakes so they can be swapped for the real services later.
```

**Done when:** the graph routes as in architecture section 6.1; write actions always go through confirmation; the specialist only reports to the orchestrator; only the orchestrator writes facts; each harness limit has a test; `scripts/chat.py --as sp-001` works against the fakes; tests pass without a model key.

### Step 5: tracing (Saturday) · branch `b/step-5-tracing`

```text
Following brief section 6.5, architecture.md section 9.3 and contracts.md section 9, wire OpenTelemetry and OpenInference into the agent service, exporting to Phoenix. Propagate traceparent to the MCP server and the context service. Set session.id and user.id on every span, prompt.id and prompt.version on model spans, and harness.limit when the harness stops a turn. Make sure no token or personal data goes into attributes. Explain in the PR how to open one full conversation in Phoenix.
```

**Done when:** one conversation shows as one session in Phoenix; model spans carry prompt version, tokens and cost; no token or personal data in attributes.

### Step 6: evals and CI (Saturday) · branch `b/step-6-evals`

```text
Following brief sections 6.6 and 6.7 and architecture.md section 9.5, write evals/cases.yaml with about 25 cases across the five groups (lookup, stock, write with confirmation, out of scope, security), using the identifiers in contracts.md section 4. Write evals/run.py with rule-based checks (expected tool calls and answer content), an 85% threshold and evals/report.md as output. Extend .github/workflows/ci.yml with an eval job that runs on the run-evals label or manual trigger, starting the stack with docker compose and reading the model key from GitHub secrets.
```

**Done when:** `python evals/run.py` writes a report and fails below 85%; the eval job runs on the `run-evals` label or manually; normal CI still runs without a model key.

### Integration (Sunday, with Dev A)

1. Switch `MCP_URL` and `CONTEXT_URL` from the fakes to the real services.
2. Run the demo script (brief section 8) end to end.
3. Run the evals against the real stack.
4. Fix any mismatch in the service that broke the contract. If the contract itself is wrong, open a PR to `docs/contracts.md` and the owner decides.

## 6. Rules that are never broken

- Build to `docs/contracts.md` exactly. Your fakes must behave like the contract, not like what is convenient.
- The agent never acts with its own identity: forward the user's JWT on every call.
- Never rely on prompts for authorisation. The tools enforce it; the agent only explains the result.
- Write actions always need confirmation. Only the orchestrator writes facts.
- Prompts live in `prompts/`, versioned. No prompt text hard-coded in Python.
- No real company or client names anywhere. No secrets in git. No tokens, contact details or free-text notes in logs or span attributes.
- No dead code, no leftover scaffolding, no comments that repeat the code.

## 7. Questions

- About your step or the contract: comment on the issue or the PR, and tag `@atiliosud`.
- If the contract looks wrong: stop, write the question down, and do not work around it in code.
- Anything confidential (keys, access): only in a private message to the owner, never in the repository.
