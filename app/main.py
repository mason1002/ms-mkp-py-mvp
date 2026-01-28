from __future__ import annotations

from typing import Any

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from .config import get_settings
from .db import Repository
from .marketplace import MarketplaceClient

settings = get_settings()
repo = Repository(settings.database_path)
mp = MarketplaceClient(settings=settings)

app = FastAPI(title="Marketplace SaaS MVP", version="0.1.0")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


def _require_token(token: str | None) -> str:
    if not token:
        raise HTTPException(status_code=400, detail="Missing token")
    return token


@app.get("/landing", response_class=HTMLResponse)
def landing(token: str | None = None) -> HTMLResponse:
    token = _require_token(token)

    existing = repo.get_subscription_by_token(token)
    if existing:
        subscription_id = existing.id
        status = existing.status or "Unknown"
        body = (
            f"<h1>Marketplace SaaS MVP</h1>"
            f"<p><b>Subscription</b>: {subscription_id}</p>"
            f"<p><b>Status</b>: {status}</p>"
            f"<p>This token was already resolved.</p>"
        )
        return HTMLResponse(body)

    try:
        resolved = mp.resolve(token)
    except Exception as ex:
        raise HTTPException(status_code=502, detail=f"Resolve failed: {ex}")

    record = repo.upsert_subscription_from_resolve(token, resolved)

    body = (
        f"<h1>Marketplace SaaS MVP</h1>"
        f"<p><b>Token</b>: (received)</p>"
        f"<p><b>Subscription</b>: {record.id}</p>"
        f"<p><b>Offer</b>: {record.offer_id}</p>"
        f"<p><b>Plan</b>: {record.plan_id}</p>"
        f"<p><b>Status</b>: {record.status}</p>"
        f"<hr/>"
        f"<p>Next: POST /api/activate with subscriptionId</p>"
    )
    return HTMLResponse(body)


@app.post("/api/resolve")
def api_resolve(payload: dict[str, Any] = Body(...)) -> JSONResponse:
    token = _require_token(payload.get("token"))

    existing = repo.get_subscription_by_token(token)
    if existing and existing.raw_resolve:
        return JSONResponse({"subscriptionId": existing.id, "resolve": existing.raw_resolve, "cached": True})

    resolved = mp.resolve(token)
    record = repo.upsert_subscription_from_resolve(token, resolved)
    return JSONResponse({"subscriptionId": record.id, "resolve": resolved, "cached": False})


@app.post("/api/activate")
def api_activate(payload: dict[str, Any] = Body(...)) -> JSONResponse:
    subscription_id = payload.get("subscriptionId")
    if not subscription_id:
        raise HTTPException(status_code=400, detail="Missing subscriptionId")

    if not repo.get_subscription(subscription_id):
        raise HTTPException(status_code=404, detail="Unknown subscriptionId")

    try:
        result = mp.activate(subscription_id)
    except Exception as ex:
        raise HTTPException(status_code=502, detail=f"Activate failed: {ex}")

    repo.update_status(subscription_id, "Subscribed")
    return JSONResponse({"subscriptionId": subscription_id, "result": result})


@app.post("/api/webhook")
async def api_webhook(request: Request) -> JSONResponse:
    payload = await request.json()

    # The webhook schema varies by action; we store the full payload.
    subscription_id = payload.get("subscriptionId") or payload.get("id")
    action = payload.get("action") or payload.get("eventType")

    repo.add_webhook_event(subscription_id=subscription_id, action=action, payload=payload)

    # If status is present, attempt to apply it.
    status = payload.get("status") or payload.get("saasSubscriptionStatus")
    if subscription_id and status:
        try:
            repo.update_status(subscription_id, status)
        except Exception:
            pass

    return JSONResponse({"ok": True})
