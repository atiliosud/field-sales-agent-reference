# CLAUDE.md

Rules for working in this repository. At the start of every session, read this file, `docs/poc-build-brief.md`, `docs/architecture.md`, `docs/contracts.md`, `docs/team-plan.md` and your own guide (`docs/dev-a-guide.md` or `docs/dev-b-guide.md`).

## What this repo is

A small reference project: an AI assistant for field salespeople, built to show shared context between agents, MCP tools with the user's identity, a multi-agent harness, tracing and an eval gate. Mock data only. The spec is `docs/poc-build-brief.md`; the design is `docs/architecture.md`; the interfaces are `docs/contracts.md`; who builds what is `docs/team-plan.md`; each developer's steps and prompts are in their guide.

## How to work

- Two developers work in parallel. Work only on the step assigned to you in your guide, on its own branch (`a/step-N-...` or `b/step-N-...`). The "Who changes what" table in `docs/team-plan.md` says which folders you may edit.
- Do one step at a time. Stop at the end of the step and summarise what changed.
- Build against `docs/contracts.md` exactly. Never change an interface on your own: if the contract looks wrong, stop and write down the question for the owner.
- Do not edit files that belong to the other developer's services. Shared files (`docker-compose.yml`, `.env.example`, `.github/workflows/ci.yml`) change only when the step says so.
- Keep it small. If something is not in the brief, do not build it; add it to "Not done yet" in the README instead.
- Ask before adding a new dependency, and say why it is needed. Add it to that service's own `pyproject.toml`.
- Every change comes with tests. Run `ruff` and `pytest` before saying a step is done.
- No dead code, no leftover scaffolding, no comments that repeat the code.
- Prefer clear, boring code over clever code. The owner must be able to explain every file.
- At the end of each step, suggest a commit message and a pull request description that follows `.github/pull_request_template.md`.

## Hard rules

- No real company or client names anywhere: code, data, commits or docs. All data is invented.
- Never commit secrets. Use `.env` (git-ignored) and keep `.env.example` in line with `docs/contracts.md`.
- Never put tokens or personal data in logs or span attributes.
- Write tools (`log_visit`, `create_lead`) must refuse unless `confirmed` is true.
- Only the orchestrator writes facts to the context service.
- Never push to `main`. Every change goes through a pull request.

## Style

- Python 3.12, type hints, small modules.
- British English in docs and user-facing text.
- Do not rewrite README or ADR wording written by the owner. Point out problems instead.

## Useful commands

- `docker compose up` starts everything.
- `python scripts/make_token.py sp-001` prints a demo token.
- `python scripts/chat.py --as sp-001` opens the chat client.
- `python evals/run.py` runs the evals and writes `evals/report.md`.
