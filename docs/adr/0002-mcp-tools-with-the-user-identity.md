# ADR 0002: MCP tools with the user's identity

## Context

The agent can reach every customer record. A salesperson may see only their own. If the agent acts with an identity of its own, one well-written sentence can make the model fetch data the user could not see. This is the confused deputy problem: the intermediary has more permission than the person who asked.

## Decision

Authorisation follows ownership of the data and never lives in the prompt. The salesperson's token travels as a bearer token to the MCP server (`mcp_client.py:55`) and to the context service (`context_client.py:29`).

`authenticate` (`auth.py:19-43`) requires the `exp`, `iss`, `sub` and `region` claims, the issuer `field-sales-demo`, HS256, and a region of North or South. Each tool then checks the owner with `_own_customer` (`tools.py:23-29`): `NOT_FOUND` if the customer does not exist, `FORBIDDEN` if `owner` differs from the caller. Three tools call it: `get_customer` (`:38`), `list_opportunities` (`:44`) and `log_visit` (`:80`). `check_stock` is not per customer, and `create_lead` has no customer yet. `check_stock` also defaults `region` to `caller.region` (`tools.py:52`). Stock has no owner, so the region argument is a convenience filter, not an authorisation boundary. That is deliberate.

Each agent has a fixed allow-list. The orchestrator has no data tool, only the routing tools (`graph.py:53-62`). The specialist gets `READ_TOOLS` (`mcp_client.py:15`, used at `graph.py:158`); anything else returns `TOOL_NOT_ALLOWED` (`graph.py:176-179`). Write tools refuse without `confirmed` (`tools.py:32-34`), and the code sets it, never the model (`graph.py:154`).

## Options considered

- **Filter in the prompt.** A prompt is not access control. It is a polite request.
- **Filter in the agent, before calling.** Authorisation would live in the part of the system that changes most.
- **Service account with broad access.** A confused deputy by design.
- **Automatic tool discovery.** Fine in development. At scale, nobody wants a tool that was never reviewed to appear.

## Consequences

Better: no prompt can get round the check, and the trace shows on whose behalf the system acted. The eval `security-other-customer` (sp-001 asks for c-006, owned by sp-002) expects `get_customer` to fail, and passed in both runs.

Worse: each service validates the token again, which costs latency and duplicates code on purpose. The access control is in the tools and no prompt gets round it, but the prompt text is a separate exposure: the orchestrator system prompt names a customer (`prompts/orchestrator.v2.yaml:7`) so that it can map a name to an id. The eval `security-other-salesperson-asks` caught this; see ADR 0003. With HS256 and a shared secret, whoever validates can also issue, which is acceptable only in a demo.

## What I would do next

A real identity provider (Entra ID or Cognito) instead of HS256, with token exchange at each hop so each service gets the least scope it needs. For the model key, workload identity federation instead of a static key.
