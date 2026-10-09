# ADR 0004: Model behind a factory

## Context

The choice of model provider is rarely closed when the code starts. If the model client is created in several places, changing provider becomes a refactor. Comparing two providers on the same evals also stops being practical, and that comparison is what would let the choice rest on data.

## Decision

No part of the graph creates a model client directly. One function does: `create_model(settings)` in `services/agent/agent_service/model_factory.py:8-16`. It builds the client from the `AZURE_OPENAI_*` settings and fixes the temperature at 0. The file has 16 lines. The function has 9 lines, and the call that creates the client takes 7 of them (`:10-16`).

There is a single call site: `turn.py:85`, `self._model or create_model(settings)`. The `or` lets tests inject a fake model. A search of `services`, `evals` and `scripts` for the Azure, OpenAI and Anthropic client constructors found only `model_factory.py:10`.

## Options considered

- **Create the client where it is needed.** Changing provider becomes a refactor, and each place gets its own configuration.
- **Our own abstraction over several providers.** It rebuilds what a gateway already does, and we would maintain it for ever.
- **A gateway from the start.** One more component to run, and not needed while there is one provider. The factory keeps the way open.

## Consequences

Better: changing provider, or putting a gateway in front, touches one function. With the same evals, quality, latency and cost can be measured on both before choosing.

Worse: the factory hides what is specific to a provider, so using such a feature means opening the abstraction. It also does not solve prompts: the same prompt often behaves differently on another model. That is why the evals are the necessary pair of this decision.

The natural next step is a gateway such as LiteLLM. The factory is what makes that a change in one place: the client points at the gateway instead of the provider.

## What I would do next

Put LiteLLM between the application and the providers, for central cost accounting and spend limits, fallback when a provider fails, and a side-by-side comparison on the same evals.
