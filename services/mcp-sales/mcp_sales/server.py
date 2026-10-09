import logging
from collections.abc import Callable
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult
from starlette.requests import Request
from starlette.responses import JSONResponse

from mcp_sales import auth, telemetry, tools
from mcp_sales.auth import Caller
from mcp_sales.errors import ToolFailure, failure, success

telemetry.setup()

logger = logging.getLogger(__name__)

HOSTS = ("localhost", "127.0.0.1", "[::1]", "mcp-sales")

mcp = FastMCP(
    "sales",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[f"{host}:*" for host in HOSTS],
        allowed_origins=[f"http://{host}:*" for host in HOSTS],
    ),
)


def run_tool(
    ctx: Context,
    tool_name: str,
    action: Callable[[Caller], dict[str, Any]],
    customer_id: str | None = None,
) -> CallToolResult:
    request = ctx.request_context.request
    headers = request.headers if request is not None else {}
    with telemetry.tool_span(tool_name, headers, customer_id) as span:
        try:
            caller = auth.authenticate(headers)
            span.set_attribute("user.id", caller.id)
            return success(action(caller))
        except ToolFailure as error:
            telemetry.mark_failed(span, error.code)
            return failure(error)
        except Exception as error:
            logger.error("Unexpected failure in %s: %s", tool_name, type(error).__name__)
            telemetry.mark_failed(span, "INTERNAL")
            return failure(ToolFailure("INTERNAL", "The request could not be completed."))


@mcp.tool()
async def get_customer(customer_id: str, ctx: Context) -> CallToolResult:
    """Get the details of one of your customers.

    Fails with FORBIDDEN when the customer belongs to another salesperson.
    """
    return run_tool(
        ctx, "get_customer", lambda caller: tools.get_customer(caller, customer_id), customer_id
    )


@mcp.tool()
async def find_customer(name: str, ctx: Context) -> CallToolResult:
    """Find your customers by name. Part of the name is enough and case does not matter.

    Returns the id and name of each match. The list is empty when none of your customers matches.
    """
    return run_tool(ctx, "find_customer", lambda caller: tools.find_customer(caller, name))


@mcp.tool()
async def list_opportunities(
    customer_id: str, ctx: Context, stage: str | None = None
) -> CallToolResult:
    """List the sales opportunities of one of your customers.

    stage is optional and must be one of: open, quoted, won, lost.
    """
    return run_tool(
        ctx,
        "list_opportunities",
        lambda caller: tools.list_opportunities(caller, customer_id, stage),
        customer_id,
    )


@mcp.tool()
async def check_stock(product_code: str, ctx: Context, region: str | None = None) -> CallToolResult:
    """Check the stock of a product by warehouse.

    region is optional, North or South, and defaults to your own region.
    """
    return run_tool(
        ctx, "check_stock", lambda caller: tools.check_stock(caller, product_code, region)
    )


@mcp.tool()
async def log_visit(
    customer_id: str, summary: str, outcome: str, ctx: Context, confirmed: bool = False
) -> CallToolResult:
    """Record a visit to one of your customers. This changes data.

    summary has at most 500 characters. outcome must be one of: positive, neutral, negative,
    follow_up. Fails with CONFIRMATION_REQUIRED unless confirmed is true, which is only
    allowed after the user has said yes.
    """
    return run_tool(
        ctx,
        "log_visit",
        lambda caller: tools.log_visit(caller, customer_id, summary, outcome, confirmed),
        customer_id,
    )


@mcp.tool()
async def create_lead(
    company_name: str, contact: str, notes: str, ctx: Context, confirmed: bool = False
) -> CallToolResult:
    """Record a new sales lead. This changes data.

    Fails with CONFIRMATION_REQUIRED unless confirmed is true, which is only allowed after the
    user has said yes.
    """
    return run_tool(
        ctx,
        "create_lead",
        lambda caller: tools.create_lead(caller, company_name, contact, notes, confirmed),
    )


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


app = mcp.streamable_http_app()
