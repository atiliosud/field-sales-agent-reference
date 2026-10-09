import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import CallToolResult, TextContent

from fakes.jwt_check import subject

CUSTOMERS = {
    "c-001": {
        "id": "c-001",
        "name": "Nordic Tools",
        "segment": "Tool retail",
        "region": "North",
        "owner": "sp-001",
    },
    "c-002": {
        "id": "c-002",
        "name": "Birchfield Builders",
        "segment": "Residential construction",
        "region": "North",
        "owner": "sp-001",
    },
    "c-006": {
        "id": "c-006",
        "name": "Sunvale Contractors",
        "segment": "Commercial construction",
        "region": "South",
        "owner": "sp-002",
    },
}
OPPORTUNITIES = {
    "c-001": [
        {
            "id": "o-001",
            "product_code": "P-104",
            "value_eur": 18500,
            "stage": "open",
            "next_step": "Send a quote",
        },
        {
            "id": "o-002",
            "product_code": "P-110",
            "value_eur": 7200,
            "stage": "open",
            "next_step": "Arrange a demonstration",
        },
        {
            "id": "o-003",
            "product_code": "P-101",
            "value_eur": 24000,
            "stage": "won",
            "next_step": "Confirm delivery",
        },
    ],
}
STOCK = {
    "P-104": (
        "Heavy-duty anchor kit",
        [
            ("Valley Depot", "South", 120),
            ("Riverside Warehouse", "South", 64),
            ("Fjord Depot", "North", 35),
        ],
    ),
}
STAGES = ("open", "quoted", "won", "lost")
OUTCOMES = ("positive", "neutral", "negative", "follow_up")


@dataclass
class McpCall:
    tool: str
    arguments: dict[str, Any]
    authorization: str | None
    session_id: str | None
    traceparent: str | None = None


@dataclass
class FakeMcp:
    """An in-memory sales MCP server that behaves like the contract, errors included."""

    calls: list[McpCall] = field(default_factory=list)
    visits: list[dict[str, Any]] = field(default_factory=list)
    leads: list[dict[str, Any]] = field(default_factory=list)
    delays: dict[str, float] = field(default_factory=dict)
    broken: set[str] = field(default_factory=set)

    def reset(self) -> None:
        self.calls.clear()
        self.visits.clear()
        self.leads.clear()
        self.delays.clear()
        self.broken.clear()


def _result(data: dict[str, Any], is_error: bool = False) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(data))],
        structuredContent=None if is_error else data,
        isError=is_error,
    )


def _error(code: str, message: str) -> CallToolResult:
    return _result({"error": {"code": code, "message": message}}, is_error=True)


def create_fake_mcp(state: FakeMcp) -> tuple[FastMCP, Any]:
    mcp = FastMCP("sales")

    async def run(
        ctx: Context, tool: str, arguments: dict[str, Any], action: Any
    ) -> CallToolResult:
        headers = ctx.request_context.request.headers  # type: ignore[union-attr]
        state.calls.append(
            McpCall(
                tool,
                arguments,
                headers.get("authorization"),
                headers.get("x-session-id"),
                headers.get("traceparent"),
            )
        )
        await asyncio.sleep(state.delays.get(tool, 0))
        caller = subject(headers)
        if caller is None:
            return _error("UNAUTHENTICATED", "A valid bearer token is required.")
        if tool in state.broken:
            return _error("INTERNAL", "The request could not be completed.")
        failure = action(*caller)
        return failure if isinstance(failure, CallToolResult) else _result(failure)

    def own_customer(sub: str, customer_id: str) -> dict[str, Any] | CallToolResult:
        customer = CUSTOMERS.get(customer_id)
        if customer is None:
            return _error("NOT_FOUND", f"Customer {customer_id} was not found.")
        if customer["owner"] != sub:
            return _error("FORBIDDEN", f"Customer {customer_id} is not assigned to you.")
        return customer

    @mcp.tool()
    async def get_customer(customer_id: str, ctx: Context) -> CallToolResult:
        """Get one of your customers."""
        return await run(
            ctx,
            "get_customer",
            {"customer_id": customer_id},
            lambda sub, region: own_customer(sub, customer_id),
        )

    @mcp.tool()
    async def find_customer(name: str, ctx: Context) -> CallToolResult:
        """Find your customers by name."""

        def action(sub: str, region: str) -> Any:
            return {
                "customers": [
                    {"id": c["id"], "name": c["name"]}
                    for c in CUSTOMERS.values()
                    if c["owner"] == sub and name.strip().casefold() in c["name"].casefold()
                ]
            }

        return await run(ctx, "find_customer", {"name": name}, action)

    @mcp.tool()
    async def list_opportunities(
        customer_id: str, ctx: Context, stage: str | None = None
    ) -> CallToolResult:
        """List the opportunities of one of your customers."""

        def action(sub: str, region: str) -> Any:
            if stage is not None and stage not in STAGES:
                return _error("INVALID_INPUT", f"stage must be one of: {', '.join(STAGES)}.")
            found = own_customer(sub, customer_id)
            if isinstance(found, CallToolResult):
                return found
            items = [o for o in OPPORTUNITIES.get(customer_id, []) if stage in (None, o["stage"])]
            return {"customer_id": customer_id, "opportunities": items}

        return await run(
            ctx, "list_opportunities", {"customer_id": customer_id, "stage": stage}, action
        )

    @mcp.tool()
    async def check_stock(
        product_code: str, ctx: Context, region: str | None = None
    ) -> CallToolResult:
        """Check the stock of a product."""

        def action(sub: str, caller_region: str) -> Any:
            wanted = region or caller_region
            if wanted not in ("North", "South"):
                return _error("INVALID_INPUT", "region must be one of: North, South.")
            if product_code not in STOCK:
                return _error("NOT_FOUND", f"Product {product_code} was not found.")
            name, lines = STOCK[product_code]
            warehouses = [{"warehouse": w, "quantity": q} for w, r, q in lines if r == wanted]
            return {
                "product_code": product_code,
                "name": name,
                "region": wanted,
                "warehouses": warehouses,
                "total": sum(w["quantity"] for w in warehouses),
            }

        return await run(
            ctx, "check_stock", {"product_code": product_code, "region": region}, action
        )

    @mcp.tool()
    async def log_visit(
        customer_id: str, summary: str, outcome: str, ctx: Context, confirmed: bool = False
    ) -> CallToolResult:
        """Record a visit. Needs confirmed true."""

        def action(sub: str, region: str) -> Any:
            if not summary.strip() or len(summary) > 500:
                return _error("INVALID_INPUT", "summary must have 1 to 500 characters.")
            if outcome not in OUTCOMES:
                return _error("INVALID_INPUT", f"outcome must be one of: {', '.join(OUTCOMES)}.")
            found = own_customer(sub, customer_id)
            if isinstance(found, CallToolResult):
                return found
            if not confirmed:
                return _error(
                    "CONFIRMATION_REQUIRED", "The user has not confirmed this action yet."
                )
            visit = {
                "visit_id": f"v-{len(state.visits) + 1:03}",
                "customer_id": customer_id,
                "logged_at": "2026-10-08T10:00:00+00:00",
            }
            state.visits.append({**visit, "summary": summary, "outcome": outcome, "sub": sub})
            return visit

        args = {
            "customer_id": customer_id,
            "summary": summary,
            "outcome": outcome,
            "confirmed": confirmed,
        }
        return await run(ctx, "log_visit", args, action)

    @mcp.tool()
    async def create_lead(
        company_name: str, contact: str, notes: str, ctx: Context, confirmed: bool = False
    ) -> CallToolResult:
        """Record a lead. Needs confirmed true."""

        def action(sub: str, region: str) -> Any:
            if not company_name.strip() or not contact.strip():
                return _error("INVALID_INPUT", "company_name and contact must not be empty.")
            if not confirmed:
                return _error(
                    "CONFIRMATION_REQUIRED", "The user has not confirmed this action yet."
                )
            lead = {
                "lead_id": f"l-{len(state.leads) + 1:03}",
                "company_name": company_name,
                "created_at": "2026-10-08T10:00:00+00:00",
            }
            state.leads.append({**lead, "contact": contact, "notes": notes, "sub": sub})
            return lead

        args = {
            "company_name": company_name,
            "contact": contact,
            "notes": notes,
            "confirmed": confirmed,
        }
        return await run(ctx, "create_lead", args, action)

    return mcp, mcp.streamable_http_app()
