import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _find_data_dir() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "mock-data").is_dir():
            return parent / "mock-data"
    raise RuntimeError("mock-data directory not found")


DATA_DIR = _find_data_dir()
RUNTIME_DIR = DATA_DIR / "runtime"


def _load(name: str) -> list[dict[str, Any]]:
    return json.loads((DATA_DIR / f"{name}.json").read_text(encoding="utf-8"))


def list_customers() -> list[dict[str, Any]]:
    return _load("customers")


def get_customer(customer_id: str) -> dict[str, Any] | None:
    return next((c for c in _load("customers") if c["id"] == customer_id), None)


def list_opportunities(customer_id: str, stage: str | None) -> list[dict[str, Any]]:
    return [
        {key: o[key] for key in ("id", "product_code", "value_eur", "stage", "next_step")}
        for o in _load("opportunities")
        if o["customer_id"] == customer_id and (stage is None or o["stage"] == stage)
    ]


def get_stock(product_code: str) -> list[dict[str, Any]]:
    return [line for line in _load("stock") if line["product_code"] == product_code]


def _append(name: str, id_key: str, id_prefix: str, record: dict[str, Any]) -> dict[str, Any]:
    path = RUNTIME_DIR / f"{name}.json"
    records = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    stored = {
        id_key: f"{id_prefix}-{uuid.uuid4().hex[:8]}",
        **record,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([*records, stored], indent=2), encoding="utf-8")
    return stored


def add_visit(salesperson_id: str, customer_id: str, summary: str, outcome: str) -> dict[str, Any]:
    return _append(
        "visits",
        "visit_id",
        "v",
        {
            "salesperson_id": salesperson_id,
            "customer_id": customer_id,
            "summary": summary,
            "outcome": outcome,
        },
    )


def add_lead(salesperson_id: str, company_name: str, contact: str, notes: str) -> dict[str, Any]:
    return _append(
        "leads",
        "lead_id",
        "l",
        {
            "salesperson_id": salesperson_id,
            "company_name": company_name,
            "contact": contact,
            "notes": notes,
        },
    )
