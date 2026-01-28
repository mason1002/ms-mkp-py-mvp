from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterator


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_parent_dir(db_path: str) -> None:
    parent = os.path.dirname(os.path.abspath(db_path))
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)


@contextmanager
def connect(db_path: str) -> Iterator[sqlite3.Connection]:
    ensure_parent_dir(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        yield conn
    finally:
        conn.close()


def init_db(db_path: str) -> None:
    with connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS subscriptions (
              id TEXT PRIMARY KEY,
              offer_id TEXT,
              plan_id TEXT,
              quantity INTEGER,
              status TEXT,
              raw_resolve_json TEXT,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS marketplace_tokens (
              token TEXT PRIMARY KEY,
              subscription_id TEXT,
              created_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS webhook_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              subscription_id TEXT,
              action TEXT,
              payload_json TEXT,
              received_at TEXT
            )
            """
        )
        conn.commit()


@dataclass(frozen=True)
class SubscriptionRecord:
    id: str
    offer_id: str | None
    plan_id: str | None
    quantity: int | None
    status: str | None
    raw_resolve: dict[str, Any] | None


class Repository:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        init_db(db_path)

    def get_subscription(self, subscription_id: str) -> SubscriptionRecord | None:
        with connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM subscriptions WHERE id = ?",
                (subscription_id,),
            ).fetchone()
            if not row:
                return None
            raw = json.loads(row["raw_resolve_json"]) if row["raw_resolve_json"] else None
            return SubscriptionRecord(
                id=row["id"],
                offer_id=row["offer_id"],
                plan_id=row["plan_id"],
                quantity=row["quantity"],
                status=row["status"],
                raw_resolve=raw,
            )

    def get_subscription_by_token(self, token: str) -> SubscriptionRecord | None:
        with connect(self._db_path) as conn:
            mapping = conn.execute(
                "SELECT subscription_id FROM marketplace_tokens WHERE token = ?",
                (token,),
            ).fetchone()
            if not mapping:
                return None
            return self.get_subscription(mapping["subscription_id"])

    def upsert_subscription_from_resolve(self, token: str, resolve_json: dict[str, Any]) -> SubscriptionRecord:
        subscription_id = resolve_json.get("id") or resolve_json.get("subscription", {}).get("id")
        if not subscription_id:
            raise ValueError("Resolve response missing subscription id")

        offer_id = resolve_json.get("offerId") or resolve_json.get("subscription", {}).get("offerId")
        plan_id = resolve_json.get("planId") or resolve_json.get("subscription", {}).get("planId")
        quantity = resolve_json.get("quantity")
        status = (
            resolve_json.get("saasSubscriptionStatus")
            or resolve_json.get("subscription", {}).get("saasSubscriptionStatus")
            or resolve_json.get("subscription", {}).get("status")
        )

        now = _utc_now_iso()
        raw_str = json.dumps(resolve_json, ensure_ascii=False)

        with connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO subscriptions (id, offer_id, plan_id, quantity, status, raw_resolve_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  offer_id=excluded.offer_id,
                  plan_id=excluded.plan_id,
                  quantity=excluded.quantity,
                  status=excluded.status,
                  raw_resolve_json=excluded.raw_resolve_json,
                  updated_at=excluded.updated_at
                """,
                (subscription_id, offer_id, plan_id, quantity, status, raw_str, now, now),
            )
            conn.execute(
                """
                INSERT INTO marketplace_tokens (token, subscription_id, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(token) DO UPDATE SET subscription_id=excluded.subscription_id
                """,
                (token, subscription_id, now),
            )
            conn.commit()

        return self.get_subscription(subscription_id)  # type: ignore[return-value]

    def update_status(self, subscription_id: str, status: str) -> None:
        now = _utc_now_iso()
        with connect(self._db_path) as conn:
            conn.execute(
                "UPDATE subscriptions SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, subscription_id),
            )
            conn.commit()

    def add_webhook_event(self, subscription_id: str | None, action: str | None, payload: dict[str, Any]) -> None:
        now = _utc_now_iso()
        with connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO webhook_events (subscription_id, action, payload_json, received_at) VALUES (?, ?, ?, ?)",
                (
                    subscription_id,
                    action,
                    json.dumps(payload, ensure_ascii=False),
                    now,
                ),
            )
            conn.commit()
