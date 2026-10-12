import json
from pathlib import Path

import pytest

DATA = Path(__file__).resolve().parent.parent / "mock-data"


def load(name: str) -> list[dict]:
    return json.loads((DATA / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def salespeople() -> list[dict]:
    return load("salespeople")


@pytest.fixture(scope="module")
def customers() -> list[dict]:
    return load("customers")


@pytest.fixture(scope="module")
def opportunities() -> list[dict]:
    return load("opportunities")


@pytest.fixture(scope="module")
def stock() -> list[dict]:
    return load("stock")


def test_every_opportunity_points_to_an_existing_customer(customers, opportunities):
    customer_ids = {customer["id"] for customer in customers}

    assert {o["customer_id"] for o in opportunities} <= customer_ids


def test_every_customer_has_a_valid_owner(salespeople, customers):
    salesperson_ids = {person["id"] for person in salespeople}

    assert {customer["owner"] for customer in customers} <= salesperson_ids


def test_customers_are_split_between_the_two_salespeople(customers):
    owners = {customer["id"]: customer["owner"] for customer in customers}

    assert owners == {f"c-{n:03}": "sp-001" if n <= 5 else "sp-002" for n in range(1, 11)}


def test_customers_are_in_their_owners_region(salespeople, customers):
    regions = {person["id"]: person["region"] for person in salespeople}

    assert all(customer["region"] == regions[customer["owner"]] for customer in customers)


def test_opportunities_cover_every_stage(opportunities):
    assert {o["stage"] for o in opportunities} == {"open", "quoted", "won", "lost"}


def test_nordic_tools_has_at_least_two_open_opportunities(customers, opportunities):
    nordic_tools = next(c for c in customers if c["name"] == "Nordic Tools")
    open_ones = [
        o for o in opportunities if o["customer_id"] == nordic_tools["id"] and o["stage"] == "open"
    ]

    assert nordic_tools["id"] == "c-001"
    assert len(open_ones) >= 2


def test_stock_covers_p101_to_p120_and_not_p204(stock):
    product_codes = {line["product_code"] for line in stock}

    assert product_codes == {f"P-{n}" for n in range(101, 121)}
    assert "P-204" not in product_codes


def test_p104_is_in_stock_in_the_south(stock):
    south = [
        line for line in stock if line["product_code"] == "P-104" and line["region"] == "South"
    ]

    assert sum(line["quantity"] for line in south) > 0


def test_products_cover_p101_to_p120_and_match_the_stock_names(stock):
    products = load("products")
    names = {line["product_code"]: line["name"] for line in stock}

    assert {p["product_code"]: p["name"] for p in products} == names
    assert all(p["description"].strip() for p in products)


def test_price_lists_point_to_existing_customers_and_products(customers):
    rows = load("price_lists")
    product_codes = {p["product_code"] for p in load("products")}

    assert {row["customer_id"] for row in rows} <= {c["id"] for c in customers}
    assert {row["product_code"] for row in rows} <= product_codes
    assert len({(row["customer_id"], row["product_code"]) for row in rows}) == len(rows)


def test_the_same_product_has_a_different_price_for_two_customers():
    rows = load("price_lists")
    anchors = {
        row["customer_id"]: row["unit_price_eur"] for row in rows if row["product_code"] == "P-104"
    }

    assert len(set(anchors.values())) == len(anchors) > 1
