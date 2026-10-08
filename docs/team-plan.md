# Team plan

How two developers build `field-sales-agent-reference` in parallel on the owner's GitHub repository, with the owner reviewing everything.

| Document | For | What it covers |
| --- | --- | --- |
| `docs/architecture.md` | Everyone | What we build, how and why |
| `docs/contracts.md` | Everyone | The exact interfaces between components |
| `docs/poc-build-brief.md` | Everyone | Full spec, demo script, cautions |
| `docs/team-plan.md` (this file) | Everyone | Roles, rules, timeline, integration |
| `docs/dev-a-guide.md` | Dev A | Set-up, workflow and prompts for data and tools |
| `docs/dev-b-guide.md` | Dev B | Set-up, workflow and prompts for agents |

## 1. Roles

| Who | Owns | Steps |
| --- | --- | --- |
| **Owner** (Atilio Moreira, `@atiliosud`) | Architecture, contracts, harness design, ADRs, README, every review and merge, the demo | 7 and 8, plus all reviews |
| **Dev A** | Data and tools: skeleton, mock data, tokens, sales MCP server, context service | 0, 1, 2, 3 |
| **Dev B** | Agents: orchestrator and specialist, harness, prompts, chat API and CLI, tracing, evals, CI eval job | 4, 5, 6 |

## 2. Who changes what

| Area | Owner | Dev A | Dev B |
| --- | --- | --- | --- |
| `docs/architecture.md`, `docs/contracts.md`, ADRs, README | Writes and approves | Proposes in a PR | Proposes in a PR |
| `services/mcp-sales/`, `services/context/`, `mock-data/`, `scripts/make_token.py` | Reviews | Builds | Reads only |
| `services/agent/`, `prompts/`, `evals/`, `scripts/chat.py` | Reviews | Reads only | Builds |
| `docker-compose.yml`, `.env.example`, root `pyproject.toml` | Reviews | Creates in Step 0 | Changes only if the step needs it |
| `.github/workflows/ci.yml` | Reviews | Creates in Step 0 | Adds the eval job in Step 6 |

## 3. Repository rules

- The repository lives on the owner's GitHub account. Both developers are collaborators with **Write** access.
- `main` is protected: pull requests only, one approval from the code owner, CI must pass, no force pushes. The owner merges.
- One issue and one branch per step: `a/step-2-mcp-server`, `b/step-4-agent`. The PR says `Closes #<issue>`.
- Small pull requests using the template in `.github/pull_request_template.md`.
- Each service has its own `pyproject.toml`; the root one only holds ruff and pytest settings.
- `docker-compose.yml` gets every service in Step 0, so nobody needs to edit it later.
- Never commit secrets. Never use real company or client names. All data is invented.

## 4. Owner's set-up checklist

1. Create the repository `field-sales-agent-reference` on `github.com/atiliosud`.
2. First commit, directly on `main`: `CLAUDE.md`, the six documents above in `docs/`, `docs/architecture.drawio`, and `.github/CODEOWNERS` and `.github/pull_request_template.md`.
3. Settings → Collaborators: invite Dev A and Dev B with **Write**.
4. Settings → Branches: protect `main` (require a pull request, 1 approval, code owner review, status checks once CI exists; block force pushes).
5. Create one issue per step (0 to 6) and assign them; label the eval PR `run-evals` when it is time.
6. Add the model key to GitHub secrets for the eval job, and send it privately to Dev B for local runs. Set a spending limit on the account.

## 5. Timeline (until Sunday)

| Day | Dev A | Dev B | Owner |
| --- | --- | --- | --- |
| Thursday | Step 0: skeleton and compose | Read the docs; set up; plan Step 4 | Repository set-up; merge Step 0 |
| Friday | Steps 1 and 2: mock data, tokens, MCP server | Step 4 against fakes (harness design agreed first) | Agree the harness design; review and merge |
| Saturday | Step 3: context service | Steps 5 and 6: tracing, evals and CI | Review; start ADRs |
| Sunday | Integration with Dev B | Integration with Dev A | README, ADRs, SVG; rehearse the demo twice |

## 6. Integration (Sunday, both)

1. Dev B points the agent at the real services instead of the fakes.
2. Run the demo script in brief section 8 end to end.
3. Run the evals against the real stack.
4. Any mismatch is fixed in the service that broke the contract. If the contract itself was wrong, open a PR to `docs/contracts.md` and the owner decides.

## 7. Definition of done for every pull request

- Matches `docs/contracts.md`; no undocumented change to an interface.
- Tests added and passing; ruff clean.
- No secrets, no real company names, no tokens or personal data in logs or spans.
- No dead code or leftover scaffolding.
- The PR says what changed, how it was tested and anything left for later.
