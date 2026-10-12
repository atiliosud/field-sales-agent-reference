import json
from datetime import timedelta

import pytest
from opentelemetry.trace import StatusCode

from mcp_sales import repository

VISIT = {
    "customer_id": "c-001",
    "summary": "Asked for a quote on anchor kits.",
    "outcome": "follow_up",
}
LEAD = {"company_name": "Harbour Fixings", "contact": "Anna Berg", "notes": "Met at a trade fair."}


def assert_error(result, parse, code, message=None):
    assert result.isError is True
    error = parse(result)
    assert list(error) == ["error"]
    assert list(error["error"]) == ["code", "message"]
    assert error["error"]["code"] == code
    if message:
        assert error["error"]["message"] == message


def runtime_records(runtime_dir, name):
    path = runtime_dir / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


# --- UNAUTHENTICATED ---------------------------------------------------------


def test_no_token_is_unauthenticated(call, parse):
    result = call("get_customer", {"customer_id": "c-001"}, token=None)

    assert_error(result, parse, "UNAUTHENTICATED")


def test_malformed_authorization_header_is_unauthenticated(call, parse):
    result = call(
        "get_customer",
        {"customer_id": "c-001"},
        token=None,
        headers={"Authorization": "Basic abc"},
    )

    assert_error(result, parse, "UNAUTHENTICATED")


def test_garbage_token_is_unauthenticated(call, parse):
    result = call("get_customer", {"customer_id": "c-001"}, token="not-a-jwt")

    assert_error(result, parse, "UNAUTHENTICATED")


def test_token_signed_with_another_secret_is_unauthenticated(call, parse, make_token):
    token = make_token(secret="another-secret-with-enough-length-for-hs256")

    result = call("get_customer", {"customer_id": "c-001"}, token=token)

    assert_error(result, parse, "UNAUTHENTICATED")


def test_expired_token_is_unauthenticated(call, parse, make_token):
    token = make_token(expires_in=timedelta(hours=-1))

    result = call("get_customer", {"customer_id": "c-001"}, token=token)

    assert_error(result, parse, "UNAUTHENTICATED", "The token has expired.")


def test_token_without_expiry_is_unauthenticated(call, parse, make_token):
    token = make_token(expires_in=None)

    result = call("get_customer", {"customer_id": "c-001"}, token=token)

    assert_error(result, parse, "UNAUTHENTICATED")


def test_token_from_another_issuer_is_unauthenticated(call, parse, make_token):
    token = make_token(issuer="someone-else")

    result = call("get_customer", {"customer_id": "c-001"}, token=token)

    assert_error(result, parse, "UNAUTHENTICATED")


def test_missing_token_never_returns_data_from_any_tool(call, parse):
    calls = {
        "get_customer": {"customer_id": "c-001"},
        "find_customer": {"name": "Nordic"},
        "list_opportunities": {"customer_id": "c-001"},
        "check_stock": {"product_code": "P-104"},
        "search_products": {"query": "anchor"},
        "log_visit": {**VISIT, "confirmed": True},
        "create_lead": {**LEAD, "confirmed": True},
    }

    for name, arguments in calls.items():
        assert_error(call(name, arguments, token=None), parse, "UNAUTHENTICATED")


# --- FORBIDDEN and NOT_FOUND -------------------------------------------------


def test_salesperson_cannot_read_a_customer_of_another_salesperson(call, parse):
    result = call("get_customer", {"customer_id": "c-006"})

    assert_error(result, parse, "FORBIDDEN", "Customer c-006 is not assigned to you.")


def test_salesperson_cannot_list_opportunities_of_another_salesperson(call, parse):
    result = call("list_opportunities", {"customer_id": "c-006"})

    assert_error(result, parse, "FORBIDDEN")


def test_salesperson_cannot_log_a_visit_for_another_salesperson(call, parse, runtime_dir):
    result = call("log_visit", {**VISIT, "customer_id": "c-006", "confirmed": True})

    assert_error(result, parse, "FORBIDDEN")
    assert runtime_records(runtime_dir, "visits") == []


def test_unknown_customer_is_not_found(call, parse):
    result = call("get_customer", {"customer_id": "c-999"})

    assert_error(result, parse, "NOT_FOUND", "Customer c-999 was not found.")


def test_unknown_product_is_not_found(call, parse):
    result = call("check_stock", {"product_code": "P-204"})

    assert_error(result, parse, "NOT_FOUND", "Product P-204 was not found.")


# --- read tools --------------------------------------------------------------


def test_get_customer_returns_the_contract_fields(call, parse):
    result = call("get_customer", {"customer_id": "c-001"})

    assert result.isError is False
    assert parse(result) == {
        "id": "c-001",
        "name": "Nordic Tools",
        "segment": "Tool retail",
        "region": "North",
        "owner": "sp-001",
    }
    assert result.structuredContent == parse(result)


def test_find_customer_matches_part_of_a_name_without_regard_to_case(call, parse):
    result = call("find_customer", {"name": "nORDIC"})

    assert result.isError is False
    assert parse(result) == {"customers": [{"id": "c-001", "name": "Nordic Tools"}]}
    assert result.structuredContent == parse(result)


def test_find_customer_returns_only_the_customers_of_the_caller(call, parse, make_token):
    token = make_token(sub="sp-002", region="South")

    result = call("find_customer", {"name": "Con"}, token=token)

    assert [c["id"] for c in parse(result)["customers"]] == ["c-006", "c-007"]


def test_find_customer_with_no_match_is_an_empty_list(call, parse):
    result = call("find_customer", {"name": "zzz"})

    assert result.isError is False
    assert parse(result) == {"customers": []}


def test_a_customer_of_another_salesperson_looks_the_same_as_one_that_does_not_exist(
    call, parse, make_token
):
    token = make_token(sub="sp-002", region="South")

    other_owner = call("find_customer", {"name": "Nordic Tools"}, token=token)
    unknown = call("find_customer", {"name": "Nonexistent Ltd"}, token=token)

    assert other_owner.isError is False
    assert parse(other_owner) == parse(unknown) == {"customers": []}


def test_find_customer_with_a_blank_name_is_invalid(call, parse):
    result = call("find_customer", {"name": "   "})

    assert_error(result, parse, "INVALID_INPUT", "name must not be empty.")


def test_list_opportunities_returns_all_stages(call, parse):
    result = call("list_opportunities", {"customer_id": "c-001"})

    data = parse(result)
    assert data["customer_id"] == "c-001"
    assert [o["id"] for o in data["opportunities"]] == ["o-001", "o-002", "o-003"]
    assert list(data["opportunities"][0]) == [
        "id",
        "product_code",
        "value_eur",
        "stage",
        "next_step",
    ]


def test_list_opportunities_filters_by_stage(call, parse):
    result = call("list_opportunities", {"customer_id": "c-001", "stage": "open"})

    stages = {o["stage"] for o in parse(result)["opportunities"]}
    assert stages == {"open"}


def test_check_stock_defaults_to_the_region_of_the_caller(call, parse, make_token):
    token = make_token(sub="sp-002", region="South")

    result = call("check_stock", {"product_code": "P-104"}, token=token)

    assert parse(result) == {
        "product_code": "P-104",
        "name": "Heavy-duty anchor kit",
        "region": "South",
        "warehouses": [
            {"warehouse": "Valley Depot", "quantity": 120},
            {"warehouse": "Riverside Warehouse", "quantity": 64},
        ],
        "total": 184,
    }


def test_check_stock_accepts_an_explicit_region(call, parse, make_token):
    token = make_token(sub="sp-002", region="South")

    result = call("check_stock", {"product_code": "P-104", "region": "North"}, token=token)

    data = parse(result)
    assert data["region"] == "North"
    assert data["total"] == 35


def test_check_stock_without_stock_in_the_region_is_empty_not_an_error(call, parse, make_token):
    token = make_token(sub="sp-002", region="South")

    result = call("check_stock", {"product_code": "P-102"}, token=token)

    assert result.isError is False
    assert parse(result)["warehouses"] == []
    assert parse(result)["total"] == 0


# --- search_products ---------------------------------------------------------


def codes(result, parse):
    return [product["product_code"] for product in parse(result)["products"]]


def test_search_products_matches_the_name_without_regard_to_case(call, parse):
    result = call("search_products", {"query": "ANCHOR"})

    assert codes(result, parse) == ["P-104"]


def test_search_products_matches_the_description_and_ignores_accents(call, parse):
    result = call("search_products", {"query": "MÁSONRY"})

    assert "P-101" in codes(result, parse)


def test_search_products_matches_part_of_a_word(call, parse):
    result = call("search_products", {"query": "extract"})

    assert codes(result, parse) == ["P-109"]


def test_search_products_needs_every_word_to_match(call, parse):
    assert codes(call("search_products", {"query": "anchor concrete"}), parse) == ["P-104"]
    assert codes(call("search_products", {"query": "anchor laser"}), parse) == []


def test_search_products_returns_the_catalogue_fields(call, parse):
    product = parse(call("search_products", {"query": "anchor"}))["products"][0]

    assert list(product) == ["product_code", "name", "description"]


def test_search_products_is_open_to_every_salesperson(call, parse, make_token):
    other = make_token(sub="sp-002", region="South")

    mine = call("search_products", {"query": "drill"})
    theirs = call("search_products", {"query": "drill"}, token=other)

    assert codes(mine, parse) == codes(theirs, parse) != []


def test_search_products_without_a_customer_carries_no_price(call, parse):
    result = call("search_products", {"query": "drill"})

    assert parse(result)["customer_id"] is None
    assert all("unit_price_eur" not in product for product in parse(result)["products"])


def test_search_products_gives_the_price_of_one_of_my_customers(call, parse):
    result = call("search_products", {"query": "anchor", "customer_id": "c-001"})

    assert [(p["product_code"], p["unit_price_eur"]) for p in parse(result)["products"]] == [
        ("P-104", 41.8)
    ]


def test_search_products_gives_no_price_for_a_product_off_the_price_list(call, parse):
    result = call("search_products", {"query": "laser", "customer_id": "c-001"})

    assert [(p["product_code"], p["unit_price_eur"]) for p in parse(result)["products"]] == [
        ("P-105", None)
    ]


def test_search_products_with_the_customer_of_another_salesperson_returns_no_price(call, parse):
    result = call("search_products", {"query": "anchor", "customer_id": "c-006"})

    assert_error(result, parse, "FORBIDDEN", "Customer c-006 is not assigned to you.")
    assert "43.5" not in result.content[0].text
    assert "P-104" not in result.content[0].text


def test_search_products_cannot_read_the_price_list_of_another_salesperson(call, parse, make_token):
    token = make_token(sub="sp-002", region="South")

    result = call("search_products", {"query": "anchor", "customer_id": "c-001"}, token=token)

    assert_error(result, parse, "FORBIDDEN")
    assert "41.8" not in result.content[0].text


def test_search_products_with_an_unknown_customer_is_not_found(call, parse):
    result = call("search_products", {"query": "anchor", "customer_id": "c-999"})

    assert_error(result, parse, "NOT_FOUND")


def test_search_products_in_stock_only_looks_at_the_region_of_the_caller(call, parse, make_token):
    south = make_token(sub="sp-002", region="South")

    north_result = call("search_products", {"query": "hammer", "in_stock_only": True})
    south_result = call("search_products", {"query": "hammer", "in_stock_only": True}, token=south)
    anywhere = call("search_products", {"query": "hammer"}, token=south)

    assert codes(north_result, parse) == ["P-102"]
    assert codes(south_result, parse) == []
    assert codes(anywhere, parse) == ["P-102"]


# --- write tools -------------------------------------------------------------


def test_log_visit_records_the_visit_when_confirmed(call, parse, runtime_dir):
    result = call("log_visit", {**VISIT, "confirmed": True})

    data = parse(result)
    assert result.isError is False
    assert list(data) == ["visit_id", "customer_id", "logged_at"]
    assert data["customer_id"] == "c-001"
    [stored] = runtime_records(runtime_dir, "visits")
    assert stored["visit_id"] == data["visit_id"]
    assert stored["salesperson_id"] == "sp-001"
    assert stored["summary"] == VISIT["summary"]


def test_log_visit_requires_confirmation(call, parse, runtime_dir):
    result = call("log_visit", {**VISIT, "confirmed": False})

    assert_error(result, parse, "CONFIRMATION_REQUIRED")
    assert runtime_records(runtime_dir, "visits") == []


def test_log_visit_without_the_confirmed_argument_is_not_confirmed(call, parse, runtime_dir):
    result = call("log_visit", VISIT)

    assert_error(result, parse, "CONFIRMATION_REQUIRED")
    assert runtime_records(runtime_dir, "visits") == []


def test_create_lead_records_the_lead_when_confirmed(call, parse, runtime_dir):
    result = call("create_lead", {**LEAD, "confirmed": True})

    data = parse(result)
    assert result.isError is False
    assert list(data) == ["lead_id", "company_name", "created_at"]
    assert data["company_name"] == "Harbour Fixings"
    [stored] = runtime_records(runtime_dir, "leads")
    assert stored["lead_id"] == data["lead_id"]
    assert stored["contact"] == "Anna Berg"


def test_create_lead_requires_confirmation(call, parse, runtime_dir):
    result = call("create_lead", {**LEAD, "confirmed": False})

    assert_error(result, parse, "CONFIRMATION_REQUIRED")
    assert runtime_records(runtime_dir, "leads") == []


# --- INVALID_INPUT -----------------------------------------------------------


def test_summary_longer_than_500_characters_is_invalid(call, parse, runtime_dir):
    result = call("log_visit", {**VISIT, "summary": "x" * 501, "confirmed": True})

    assert_error(result, parse, "INVALID_INPUT", "summary must be at most 500 characters.")
    assert runtime_records(runtime_dir, "visits") == []


def test_summary_of_exactly_500_characters_is_accepted(call, parse):
    result = call("log_visit", {**VISIT, "summary": "x" * 500, "confirmed": True})

    assert result.isError is False


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("log_visit", {**VISIT, "outcome": "great", "confirmed": True}),
        ("log_visit", {**VISIT, "summary": "  ", "confirmed": True}),
        ("list_opportunities", {"customer_id": "c-001", "stage": "pending"}),
        ("check_stock", {"product_code": "P-104", "region": "East"}),
        ("search_products", {"query": " "}),
        ("search_products", {"query": "?!"}),
        ("create_lead", {**LEAD, "company_name": " ", "confirmed": True}),
        ("create_lead", {**LEAD, "contact": "", "confirmed": True}),
    ],
)
def test_invalid_input_is_reported(call, parse, tool, arguments):
    result = call(tool, arguments)

    assert_error(result, parse, "INVALID_INPUT")


# --- order of the checks -----------------------------------------------------


def test_authentication_is_checked_before_input(call, parse):
    result = call("log_visit", {**VISIT, "outcome": "great", "confirmed": True}, token=None)

    assert_error(result, parse, "UNAUTHENTICATED")


def test_input_is_checked_before_ownership(call, parse):
    arguments = {**VISIT, "customer_id": "c-006", "outcome": "great", "confirmed": True}

    assert_error(call("log_visit", arguments), parse, "INVALID_INPUT")


def test_ownership_is_checked_before_confirmation(call, parse):
    arguments = {**VISIT, "customer_id": "c-006", "confirmed": False}

    assert_error(call("log_visit", arguments), parse, "FORBIDDEN")


# --- INTERNAL ----------------------------------------------------------------


def test_unexpected_failure_is_reported_without_detail(call, parse, monkeypatch, span_exporter):
    def broken(customer_id):
        raise RuntimeError("disk exploded at /secret/path for c-001")

    monkeypatch.setattr(repository, "get_customer", broken)

    result = call("get_customer", {"customer_id": "c-001"})

    assert_error(result, parse, "INTERNAL", "The request could not be completed.")
    assert "secret" not in result.content[0].text
    [span] = [s for s in span_exporter.get_finished_spans() if s.name == "get_customer"]
    assert span.status.status_code is StatusCode.ERROR
    assert span.status.description == "INTERNAL"
    assert "secret" not in str(span.events)
