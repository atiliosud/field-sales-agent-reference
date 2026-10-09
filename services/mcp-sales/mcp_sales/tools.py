from typing import Any

from mcp_sales import repository, telemetry
from mcp_sales.auth import REGIONS, Caller
from mcp_sales.errors import ToolFailure

STAGES = ("open", "quoted", "won", "lost")
OUTCOMES = ("positive", "neutral", "negative", "follow_up")
MAX_SUMMARY_LENGTH = 500


def _one_of(field: str, value: str, allowed: tuple[str, ...]) -> None:
    if value not in allowed:
        options = ", ".join(allowed)
        raise ToolFailure("INVALID_INPUT", f"{field} must be one of: {options}.")


def _not_blank(field: str, value: str) -> None:
    if not value.strip():
        raise ToolFailure("INVALID_INPUT", f"{field} must not be empty.")


def _own_customer(caller: Caller, customer_id: str) -> dict[str, Any]:
    customer = repository.get_customer(customer_id)
    if customer is None:
        raise ToolFailure("NOT_FOUND", f"Customer {customer_id} was not found.")
    if customer["owner"] != caller.id:
        raise ToolFailure("FORBIDDEN", f"Customer {customer_id} is not assigned to you.")
    return customer


def _require_confirmation(confirmed: bool) -> None:
    if not confirmed:
        raise ToolFailure("CONFIRMATION_REQUIRED", "The user has not confirmed this action yet.")


def get_customer(caller: Caller, customer_id: str) -> dict[str, Any]:
    return _own_customer(caller, customer_id)


def find_customer(caller: Caller, name: str) -> dict[str, Any]:
    _not_blank("name", name)
    needle = name.strip().casefold()
    return {
        "customers": [
            {"id": c["id"], "name": c["name"]}
            for c in repository.list_customers()
            if c["owner"] == caller.id and needle in c["name"].casefold()
        ]
    }


def list_opportunities(caller: Caller, customer_id: str, stage: str | None) -> dict[str, Any]:
    if stage is not None:
        _one_of("stage", stage, STAGES)
    _own_customer(caller, customer_id)
    return {
        "customer_id": customer_id,
        "opportunities": repository.list_opportunities(customer_id, stage),
    }


def check_stock(caller: Caller, product_code: str, region: str | None) -> dict[str, Any]:
    region = region or caller.region
    _one_of("region", region, REGIONS)
    lines = repository.get_stock(product_code)
    if not lines:
        raise ToolFailure("NOT_FOUND", f"Product {product_code} was not found.")
    warehouses = [
        {"warehouse": line["warehouse"], "quantity": line["quantity"]}
        for line in lines
        if line["region"] == region
    ]
    return {
        "product_code": product_code,
        "name": lines[0]["name"],
        "region": region,
        "warehouses": warehouses,
        "total": sum(w["quantity"] for w in warehouses),
    }


def log_visit(
    caller: Caller, customer_id: str, summary: str, outcome: str, confirmed: bool
) -> dict[str, Any]:
    _not_blank("summary", summary)
    if len(summary) > MAX_SUMMARY_LENGTH:
        raise ToolFailure(
            "INVALID_INPUT", f"summary must be at most {MAX_SUMMARY_LENGTH} characters."
        )
    _one_of("outcome", outcome, OUTCOMES)
    _own_customer(caller, customer_id)
    _require_confirmation(confirmed)

    visit = repository.add_visit(caller.id, customer_id, summary, outcome)
    telemetry.business_event("business.visit_logged", customer_id=customer_id)
    return {
        "visit_id": visit["visit_id"],
        "customer_id": customer_id,
        "logged_at": visit["created_at"],
    }


def create_lead(
    caller: Caller, company_name: str, contact: str, notes: str, confirmed: bool
) -> dict[str, Any]:
    _not_blank("company_name", company_name)
    _not_blank("contact", contact)
    _require_confirmation(confirmed)

    lead = repository.add_lead(caller.id, company_name, contact, notes)
    telemetry.business_event("business.lead_created")
    return {
        "lead_id": lead["lead_id"],
        "company_name": company_name,
        "created_at": lead["created_at"],
    }
