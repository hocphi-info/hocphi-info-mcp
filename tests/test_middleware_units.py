import re

from hocphi_mcp.logging import hash_client, parse_cloud_trace
from hocphi_mcp.middleware import client_ip


def scope(
    xff: str | None = None, client: tuple[str, int] | None = ("10.0.0.9", 1)
) -> dict:
    headers = [(b"x-forwarded-for", xff.encode())] if xff is not None else []
    return {"type": "http", "headers": headers, "client": client}


def test_client_ip_takes_the_entry_the_trusted_proxy_appended() -> None:
    # Client goi "1.1.1.1"; GFE noi them IP that "2.2.2.2" vao cuoi -> lay phan tu cuoi.
    assert client_ip(scope("1.1.1.1, 2.2.2.2"), hops=1) == "2.2.2.2"


def test_spoofed_left_side_cannot_change_the_key() -> None:
    a = client_ip(scope("fake-a, 2.2.2.2"), hops=1)
    b = client_ip(scope("fake-b, 2.2.2.2"), hops=1)
    assert a == b == "2.2.2.2"


def test_two_hops_and_fallbacks() -> None:
    assert client_ip(scope("9.9.9.9, 3.3.3.3, 4.4.4.4"), hops=2) == "3.3.3.3"
    assert client_ip(scope(None), hops=1) == "10.0.0.9"  # khong co header (chay local)
    assert client_ip(scope("only-one"), hops=2) == "10.0.0.9"  # it hon so hop tin cay
    assert client_ip(scope("1.1.1.1"), hops=0) == "10.0.0.9"  # khong tin proxy nao
    assert client_ip(scope(None, client=None), hops=1) == "unknown"


def test_hash_client_is_short_stable_and_hides_the_ip() -> None:
    h = hash_client("203.0.113.7")
    assert re.fullmatch(r"[0-9a-f]{12}", h) and h == hash_client("203.0.113.7")
    assert h != hash_client("203.0.113.8") and "203" not in h


def test_parse_cloud_trace() -> None:
    header = "105445aa7843bc8bf206b12000100000/1;o=1"
    assert parse_cloud_trace(header, "my-proj") == (
        "projects/my-proj/traces/105445aa7843bc8bf206b12000100000"
    )
    assert parse_cloud_trace(header, None) is None
    assert parse_cloud_trace(None, "p") is None
    assert parse_cloud_trace("not-a-trace/1", "p") is None
