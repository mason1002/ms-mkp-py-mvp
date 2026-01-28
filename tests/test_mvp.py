from __future__ import annotations

import os
import importlib
from pathlib import Path

from fastapi.testclient import TestClient


def _new_client(tmp_path: Path) -> TestClient:
    os.environ["MARKETPLACE_MODE"] = "mock"
    os.environ["DATABASE_PATH"] = str(tmp_path / "app.db")

    if "ADMIN_ENABLED" in os.environ:
        del os.environ["ADMIN_ENABLED"]

    # Import after env is set (module-level settings are read on import)
    import app.main as main  # noqa: WPS433
    importlib.reload(main)

    return TestClient(main.app)


def _new_client_with_admin(tmp_path: Path, *, enabled: bool) -> TestClient:
    os.environ["MARKETPLACE_MODE"] = "mock"
    os.environ["DATABASE_PATH"] = str(tmp_path / "app.db")
    os.environ["ADMIN_ENABLED"] = "true" if enabled else "false"

    import app.main as main  # noqa: WPS433
    importlib.reload(main)
    return TestClient(main.app)


def test_healthz(tmp_path: Path) -> None:
    client = _new_client(tmp_path)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_landing_resolves_and_caches(tmp_path: Path) -> None:
    client = _new_client(tmp_path)

    token = "demo-token"
    r1 = client.get(f"/landing?token={token}")
    assert r1.status_code == 200
    assert "Subscription" in r1.text

    r2 = client.post("/api/resolve", json={"token": token})
    assert r2.status_code == 200
    assert r2.json()["cached"] is True


def test_activate_mock(tmp_path: Path) -> None:
    client = _new_client(tmp_path)

    token = "activate-token"
    resolved = client.post("/api/resolve", json={"token": token}).json()
    subscription_id = resolved["subscriptionId"]

    r = client.post("/api/activate", json={"subscriptionId": subscription_id})
    assert r.status_code == 200
    assert r.json()["subscriptionId"] == subscription_id


def test_mock_subscription_id_is_deterministic_across_fresh_dbs(tmp_path: Path) -> None:
    token = "same-token"

    client1 = _new_client(tmp_path / "db1")
    sub1 = client1.post("/api/resolve", json={"token": token}).json()["subscriptionId"]

    client2 = _new_client(tmp_path / "db2")
    sub2 = client2.post("/api/resolve", json={"token": token}).json()["subscriptionId"]

    assert sub1 == sub2


def test_admin_page_enabled_in_mock_by_default(tmp_path: Path) -> None:
    client = _new_client(tmp_path)
    r = client.get("/admin")
    assert r.status_code == 200
    assert "Admin" in r.text


def test_admin_api_lists_subscriptions(tmp_path: Path) -> None:
    client = _new_client(tmp_path)
    sub_id = client.post("/api/resolve", json={"token": "t1"}).json()["subscriptionId"]

    r = client.get("/admin/api/subscriptions")
    assert r.status_code == 200
    items = r.json()["items"]
    assert any(i["id"] == sub_id for i in items)


def test_admin_can_update_status(tmp_path: Path) -> None:
    client = _new_client(tmp_path)
    sub_id = client.post("/api/resolve", json={"token": "t2"}).json()["subscriptionId"]

    r = client.post(f"/admin/api/subscriptions/{sub_id}/status", json={"status": "Suspended"})
    assert r.status_code == 200

    r2 = client.get(f"/admin/api/subscriptions/{sub_id}")
    assert r2.status_code == 200
    assert r2.json()["status"] == "Suspended"


def test_admin_disabled_returns_404(tmp_path: Path) -> None:
    client = _new_client_with_admin(tmp_path, enabled=False)
    r = client.get("/admin")
    assert r.status_code == 404
