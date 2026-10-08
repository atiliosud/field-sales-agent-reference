import httpx
import pytest

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}
HEADERS = {"Accept": "application/json, text/event-stream"}


def initialize(server_url, host):
    return httpx.post(
        f"{server_url}/mcp", json=INITIALIZE, headers={**HEADERS, "Host": host}, timeout=10
    )


@pytest.mark.parametrize("host", ["localhost:8001", "127.0.0.1:8001", "mcp-sales:8001"])
def test_known_hosts_are_accepted(server_url, host):
    assert initialize(server_url, host).status_code == 200


def test_unknown_host_is_rejected(server_url):
    assert initialize(server_url, "evil.example:8001").status_code == 421
