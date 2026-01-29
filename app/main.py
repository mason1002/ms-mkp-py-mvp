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


def _require_admin() -> None:
    if not settings.is_admin_enabled():
        raise HTTPException(status_code=404, detail="Not found")


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


@app.get("/admin", response_class=HTMLResponse)
def admin_home() -> HTMLResponse:
        _require_admin()

        mode = settings.marketplace_mode.lower()
        body = _ADMIN_HTML.replace("__MODE__", mode)
        return HTMLResponse(body)


_ADMIN_HTML = """<!doctype html>
<html lang=\"en\">
    <head>
        <meta charset=\"utf-8\" />
        <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
        <title>Admin - Marketplace SaaS MVP</title>
        <style>
            body { font-family: Segoe UI, Arial, sans-serif; margin: 24px; }
            .row { display: flex; gap: 16px; flex-wrap: wrap; align-items: center; }
            input, select, button { padding: 8px; font-size: 14px; }
            button { cursor: pointer; }
            .muted { color: #666; }
            pre { background: #f6f8fa; padding: 12px; overflow: auto; border-radius: 6px; }
            table { border-collapse: collapse; width: 100%; }
            th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
            th { background: #fafafa; }
        </style>
    </head>
    <body>
        <h1>Admin</h1>
        <p class=\"muted\">Mode: <b>__MODE__</b>. This page is intended for demo/dev only.</p>

        <div class=\"row\">
            <label>Subscription ID
                <input id=\"subId\" placeholder=\"(optional)\" size=\"44\" />
            </label>
            <button onclick=\"loadSubs()\">Load subscriptions</button>
            <button onclick=\"loadEvents()\">Load webhook events</button>
        </div>

        <h2>Update status</h2>
        <div class=\"row\">
            <label>Status
                <select id=\"newStatus\">
                    <option>PendingFulfillmentStart</option>
                    <option>Subscribed</option>
                    <option>Suspended</option>
                    <option>Unsubscribed</option>
                </select>
            </label>
            <button onclick=\"updateStatus()\">Update</button>
            <span id=\"statusMsg\" class=\"muted\"></span>
        </div>

        <h2>Subscriptions</h2>
        <div id="subs"><p class="muted">(click "Load subscriptions" to fetch)</p></div>

        <h2>Webhook events</h2>
        <div id="events"><p class="muted">(click "Load webhook events" to fetch)</p></div>

        <h2>Raw JSON</h2>
        <pre id=\"raw\">(select an item)</pre>

        <script>
            function qs() {
                const subId = document.getElementById('subId').value.trim();
                const params = new URLSearchParams();
                if (subId) params.set('subscriptionId', subId);
                params.set('limit', '50');
                params.set('offset', '0');
                return params.toString();
            }

            function setRaw(obj) {
                document.getElementById('raw').textContent = JSON.stringify(obj, null, 2);
            }

            function renderTable(containerId, rows, columns) {
                const container = document.getElementById(containerId);
                if (!rows || rows.length === 0) {
                    container.innerHTML = '<p class="muted">(empty)</p>';
                    return;
                }
                let html = '<table><thead><tr>' + columns.map(c => `<th>${c.label}</th>`).join('') + '</tr></thead><tbody>';
                for (const r of rows) {
                    html += '<tr>' + columns.map(c => {
                        const v = r[c.key];
                        const text = (v === null || v === undefined) ? '' : String(v);
                        return `<td>${text}</td>`;
                    }).join('') + '</tr>';
                }
                html += '</tbody></table>';
                container.innerHTML = html;
            }

            async function loadSubs() {
                const resp = await fetch('/admin/api/subscriptions?' + qs());
                const data = await resp.json();
                setRaw(data);
                renderTable('subs', data.items, [
                    { key: 'id', label: 'id' },
                    { key: 'offerId', label: 'offerId' },
                    { key: 'planId', label: 'planId' },
                    { key: 'quantity', label: 'quantity' },
                    { key: 'status', label: 'status' },
                    { key: 'updatedAt', label: 'updatedAt' },
                ]);
            }

            async function loadEvents() {
                const params = new URLSearchParams(qs());
                params.set('includePayload', 'false');
                const resp = await fetch('/admin/api/webhook-events?' + params.toString());
                const data = await resp.json();
                setRaw(data);
                renderTable('events', data.items, [
                    { key: 'id', label: 'id' },
                    { key: 'subscriptionId', label: 'subscriptionId' },
                    { key: 'action', label: 'action' },
                    { key: 'receivedAt', label: 'receivedAt' },
                ]);
            }

            async function updateStatus() {
                const subId = document.getElementById('subId').value.trim();
                const status = document.getElementById('newStatus').value;
                const msg = document.getElementById('statusMsg');
                msg.textContent = '';
                if (!subId) {
                    msg.textContent = 'Please enter subscriptionId first.';
                    return;
                }
                const resp = await fetch('/admin/api/subscriptions/' + encodeURIComponent(subId) + '/status', {
                    method: 'POST',
                    headers: { 'content-type': 'application/json' },
                    body: JSON.stringify({ status })
                });
                const data = await resp.json();
                setRaw(data);
                msg.textContent = resp.ok ? 'Updated.' : ('Failed: ' + (data.detail || resp.status));
                await loadSubs();
            }

            window.addEventListener('DOMContentLoaded', () => {
                loadSubs().catch(err => setRaw({ error: String(err) }));
            });
        </script>
    </body>
</html>"""


@app.get("/admin/api/subscriptions")
def admin_list_subscriptions(
        limit: int = 50,
        offset: int = 0,
        subscriptionId: str | None = None,
) -> JSONResponse:
        _require_admin()
        items = repo.list_subscriptions(limit=limit, offset=offset, subscription_id=subscriptionId)
        return JSONResponse({"items": items, "count": len(items)})


@app.get("/admin/api/subscriptions/{subscription_id}")
def admin_get_subscription(subscription_id: str) -> JSONResponse:
        _require_admin()
        record = repo.get_subscription(subscription_id)
        if not record:
                raise HTTPException(status_code=404, detail="Unknown subscriptionId")
        return JSONResponse(
                {
                        "id": record.id,
                        "offerId": record.offer_id,
                        "planId": record.plan_id,
                        "quantity": record.quantity,
                        "status": record.status,
                        "rawResolve": record.raw_resolve,
                }
        )


@app.post("/admin/api/subscriptions/{subscription_id}/status")
def admin_update_subscription_status(subscription_id: str, payload: dict[str, Any] = Body(...)) -> JSONResponse:
        _require_admin()
        status = payload.get("status")
        if not status:
                raise HTTPException(status_code=400, detail="Missing status")
        if not repo.get_subscription(subscription_id):
                raise HTTPException(status_code=404, detail="Unknown subscriptionId")
        repo.update_status(subscription_id, str(status))
        return JSONResponse({"ok": True, "subscriptionId": subscription_id, "status": status})


@app.get("/admin/api/webhook-events")
def admin_list_webhook_events(
        limit: int = 50,
        offset: int = 0,
        subscriptionId: str | None = None,
        includePayload: bool = True,
) -> JSONResponse:
        _require_admin()
        items = repo.list_webhook_events(
                limit=limit,
                offset=offset,
                subscription_id=subscriptionId,
                include_payload=includePayload,
        )
        return JSONResponse({"items": items, "count": len(items)})
