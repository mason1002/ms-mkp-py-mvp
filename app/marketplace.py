from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
import msal

from .config import Settings


@dataclass
class MarketplaceClient:
    settings: Settings

    _MOCK_NAMESPACE = uuid.UUID("f7e9a7e8-8c4f-4b6d-9b8c-2f56f6e23d2a")

    def _is_live(self) -> bool:
        return self.settings.marketplace_mode.lower() == "live"

    def _get_access_token(self) -> str:
        if not (
            self.settings.entra_tenant_id
            and self.settings.entra_client_id
            and self.settings.entra_client_secret
        ):
            raise RuntimeError(
                "Live mode requires ENTRA_TENANT_ID, ENTRA_CLIENT_ID, ENTRA_CLIENT_SECRET"
            )

        authority = f"https://login.microsoftonline.com/{self.settings.entra_tenant_id}"
        app = msal.ConfidentialClientApplication(
            client_id=self.settings.entra_client_id,
            client_credential=self.settings.entra_client_secret,
            authority=authority,
        )
        result = app.acquire_token_for_client(
            scopes=["https://marketplaceapi.microsoft.com/.default"],
        )
        if "access_token" not in result:
            raise RuntimeError(f"Failed to acquire token: {result}")
        return result["access_token"]

    def resolve(self, marketplace_token: str) -> dict[str, Any]:
        if not self._is_live():
            subscription_id = str(
                uuid.uuid5(self._MOCK_NAMESPACE, f"marketplace-token:{marketplace_token}")
            )
            return {
                "id": subscription_id,
                "subscriptionName": "Demo SaaS Subscription",
                "offerId": "demo-offer",
                "planId": "demo-plan",
                "quantity": 1,
                "subscription": {
                    "id": subscription_id,
                    "publisherId": "demo",
                    "offerId": "demo-offer",
                    "name": "Demo SaaS Subscription",
                    "saasSubscriptionStatus": "PendingFulfillmentStart",
                    "beneficiary": {"emailId": "test@example.com", "tenantId": "demo"},
                    "purchaser": {"emailId": "test@example.com", "tenantId": "demo"},
                    "planId": "demo-plan",
                    "autoRenew": True,
                    "isTest": True,
                    "isFreeTrial": False,
                    "allowedCustomerOperations": ["Read", "Update", "Delete"],
                    "quantity": 1,
                    "sessionMode": "None",
                },
                "_mock": True,
                "_receivedToken": marketplace_token,
            }

        url = f"{self.settings.marketplace_api_base}/api/saas/subscriptions/resolve"
        params = {"api-version": self.settings.marketplace_api_version}
        token = self._get_access_token()

        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
            "x-ms-requestid": str(uuid.uuid4()),
            "x-ms-correlationid": str(uuid.uuid4()),
            "x-ms-marketplace-token": marketplace_token,
        }

        with httpx.Client(timeout=30) as client:
            resp = client.post(url, params=params, headers=headers)
            resp.raise_for_status()
            return resp.json()

    def activate(self, subscription_id: str) -> dict[str, Any]:
        if not self._is_live():
            return {
                "subscriptionId": subscription_id,
                "activatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                "_mock": True,
            }

        url = f"{self.settings.marketplace_api_base}/api/saas/subscriptions/{subscription_id}/activate"
        params = {"api-version": self.settings.marketplace_api_version}
        token = self._get_access_token()

        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
            "x-ms-requestid": str(uuid.uuid4()),
            "x-ms-correlationid": str(uuid.uuid4()),
        }

        with httpx.Client(timeout=30) as client:
            resp = client.post(url, params=params, headers=headers, json={})
            resp.raise_for_status()
            return {"subscriptionId": subscription_id, "status": "Subscribed"}
