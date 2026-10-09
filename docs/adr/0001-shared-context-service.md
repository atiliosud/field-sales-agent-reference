# ADR 0001: Shared context service

## Context

A conversation has to outlive the agent process and be visible to more than one agent. Keeping the history in the agent and sending all of it every turn breaks four things. A restart loses the conversation. A second instance knows nothing about it. A voice session cannot continue what started as text. Every agent receives everything, including what is not its business.

## Decision

Context lives outside the agents, in its own service. It stores turns, versioned facts and artefacts, per conversation id. Each turn has a `channel`, `text` or `voice` (`api.py:21`), so voice writes to the same conversation.

Each agent reads a slice for its role. The orchestrator slice has the last turns, all facts and the artefacts (`slices.py:17`). The specialist slice has only `current_customer`, and only when it has a value (`slices.py:48-54`). Only the orchestrator writes facts: `orchestrator_only` (`api.py:44-47`) guards the fact endpoint (`api.py:131`). The role comes from the `X-Agent-Role` header (`api.py:35-41`). The agent keeps no state.

## Options considered

- **History in the agent's memory.** Dies with the process; a second instance or a voice session cannot join.
- **Pass the whole history between agents.** The prompt grows without limit and each agent sees what it does not need.
- **Vector store for short-term memory.** A conversation is looked up by id, not by similarity. Postgres with `jsonb` is enough.
- **Both agents write facts.** Two writers mean two accounts of one conversation.

## Consequences

Better: the agent scales sideways, voice joins by writing turns, prompts are smaller. A stale write gets `409 CONFLICT`: `put_fact` compares `If-Match` with the stored version (`facts.py:26-27`).

Worse: one more service and database to run, an extra HTTP read and write per turn, and fact versions to track.

One design error was corrected. The first slices left out cleared facts. That hid the version from the writer, so the agent sent `If-Match: 0` for a fact that existed and got a 409. A workaround read the version from the error message, which the contract does not fix. The orchestrator slice now shows a cleared fact as `value: null` with its version (`test_facts.py:101`). The specialist slice still omits it (`test_facts.py:116`).

## What I would do next

Retention per conversation, and encryption once content holds personal data. Long-term memory across conversations is a separate problem: it needs consent, review and deletion.
