"""Thin client for the Linq Partner API v3, plus an in-memory fake with the same surface.

Endpoints used (from docs.linqapp.com, checked 2026-11-20):
  POST   /v3/messages                  send to recipients, Linq picks the line and chat
  POST   /v3/chats/{chat_id}/messages  send into an existing chat
  POST   /v3/chats/{chat_id}/typing    start typing indicator (iMessage only)
  DELETE /v3/chats/{chat_id}/typing    stop typing indicator
  POST   /v3/payment_requests          create a payment request, returns checkout_url
Webhooks follow the Standard Webhooks spec (webhook-id, webhook-timestamp, webhook-signature).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import urllib.request
import uuid

BASE_URL = "https://api.linqapp.com/api/partner"


class LinqError(Exception):
    def __init__(self, status: int, body: str):
        super().__init__(f"Linq API {status}: {body[:300]}")
        self.status = status
        self.body = body


class LinqClient:
    """Real HTTP client. Reads nothing from disk; the caller passes the token."""

    def __init__(self, token: str, base_url: str = BASE_URL, timeout: float = 20.0):
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base_url + path, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.token}")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:  # pragma: no cover - live only
            raise LinqError(e.code, e.read().decode(errors="replace")) from None

    def send_new(self, to: list[str], parts: list[dict]) -> dict:
        return self._call("POST", "/v3/messages", {"to": to, "message": {"parts": parts}})

    def send(self, chat_id: str, parts: list[dict]) -> dict:
        return self._call("POST", f"/v3/chats/{chat_id}/messages", {"message": {"parts": parts}})

    def typing_start(self, chat_id: str) -> None:
        self._call("POST", f"/v3/chats/{chat_id}/typing")

    def typing_stop(self, chat_id: str) -> None:
        self._call("DELETE", f"/v3/chats/{chat_id}/typing")

    def create_payment_request(self, amount_cents: int, description: str, metadata: dict) -> dict:
        return self._call("POST", "/v3/payment_requests", {
            "amount": amount_cents, "currency": "usd",
            "description": description, "metadata": metadata,
        })


class FakeLinq:
    """Records every call with the same method names as LinqClient. Used by tests and the eval."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.payment_requests: dict[str, dict] = {}

    def send_new(self, to, parts):
        chat_id = str(uuid.uuid4())
        self.calls.append(("send_new", {"to": to, "parts": parts, "chat_id": chat_id}))
        return {"chat_id": chat_id, "created_new_chat": True, "service": "iMessage"}

    def send(self, chat_id, parts):
        self.calls.append(("send", {"chat_id": chat_id, "parts": parts}))
        return {"chat_id": chat_id, "message": {"id": str(uuid.uuid4()), "parts": parts}}

    def typing_start(self, chat_id):
        self.calls.append(("typing_start", {"chat_id": chat_id}))

    def typing_stop(self, chat_id):
        self.calls.append(("typing_stop", {"chat_id": chat_id}))

    def create_payment_request(self, amount_cents, description, metadata):
        pr_id = "pr_" + uuid.uuid4().hex[:12]
        pr = {"id": pr_id, "status": "requested", "amount": amount_cents, "currency": "usd",
              "description": description, "metadata": metadata,
              "checkout_url": f"https://pay.example/checkout/{pr_id}"}
        self.payment_requests[pr_id] = pr
        self.calls.append(("create_payment_request", pr))
        return pr

    # helpers for the eval
    def texts(self) -> list[str]:
        out = []
        for name, c in self.calls:
            if name in ("send", "send_new"):
                for p in c["parts"]:
                    out.append(p.get("value", ""))
        return out


# ---------------- webhooks ----------------

def sign_webhook(secret: str, msg_id: str, timestamp: int, body: str) -> str:
    key = base64.b64decode(secret.removeprefix("whsec_"))
    mac = hmac.new(key, f"{msg_id}.{timestamp}.{body}".encode(), hashlib.sha256).digest()
    return "v1," + base64.b64encode(mac).decode()


def verify_webhook(secret: str, headers: dict, body: str, now: float | None = None,
                   tolerance_s: int = 300) -> bool:
    """Standard Webhooks verification, as in Linq's docs: reject stale timestamps,
    HMAC-SHA256 over '{id}.{timestamp}.{raw body}', constant-time compare."""
    try:
        msg_id = headers["webhook-id"]
        ts = int(headers["webhook-timestamp"])
        sig_header = headers["webhook-signature"]
    except (KeyError, ValueError):
        return False
    now = time.time() if now is None else now
    if abs(now - ts) > tolerance_s:
        return False
    expected = sign_webhook(secret, msg_id, ts, body).split(",", 1)[1]
    for sig in sig_header.split(" "):
        version, _, value = sig.partition(",")
        if version == "v1" and hmac.compare_digest(value, expected):
            return True
    return False


def make_event(event_type: str, data: dict, event_id: str | None = None) -> dict:
    """Envelope shaped like Linq's 2026-02-03 webhook payloads."""
    return {
        "api_version": "v3", "webhook_version": "2026-02-03",
        "event_type": event_type, "event_id": event_id or str(uuid.uuid4()),
        "created_at": "2026-11-20T15:00:00Z", "trace_id": uuid.uuid4().hex,
        "partner_id": "demo-partner", "data": data,
    }


def inbound_message(chat_id: str, sender: str, text: str, service: str = "iMessage",
                    event_id: str | None = None) -> dict:
    return make_event("message.received", {
        "chat": {"id": chat_id, "is_group": False,
                 "health_status": {"status": "HEALTHY"}},
        "id": str(uuid.uuid4()), "direction": "inbound",
        "sender_handle": {"handle": sender, "is_me": False, "service": service},
        "parts": [{"type": "text", "value": text}],
        "service": service,
    }, event_id)
