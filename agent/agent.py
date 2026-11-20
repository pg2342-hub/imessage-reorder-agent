"""Reorder and order-status agent over Linq.

Pilot autonomy (pick "a"): the agent handles order status and reorders of a member's saved usual
on its own. Anything new (new items, changes to the usual, refunds, complaints, allergy questions)
goes to a person. Transcripts are reviewed weekly.

Each guardrail can be switched off to see what breaks (eval/run_eval.py --ablate).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import json

from .intents import classify
from .linq import verify_webhook
from .store import ORDER_CAP_CENTS, STORES, Store

GUARDRAILS = {
    "stop_optout": "Stops all messages after STOP",
    "dedupe_events": "Handles a webhook Linq delivers twice only once",
    "verify_signature": "Rejects webhooks with a bad or stale signature",
    "handoff_changes": "Sends new items and changes to the usual to a person",
    "handoff_money": "Sends refunds, complaints and allergy questions to a person",
    "order_cap": "Sends orders over $30 to a person",
    "confirm_first": "Asks for YES before sending a payment link, and re-asks if the YES is stale",
    "no_duplicate": "Never opens a second order while one is waiting for payment",
    "store_open": "Checks the pickup store is open before taking an order",
}

CONFIRM_TTL_MIN = 30
APP_LINK = "https://example.com/app"  # placeholder for the brand's app link


@dataclass
class ChatState:
    draft: list | None = None          # items awaiting YES
    draft_at: float | None = None      # minutes clock
    handed_off: bool = False
    unclear_count: int = 0


@dataclass
class Agent:
    linq: object
    store: Store
    guards: dict = field(default_factory=lambda: {g: True for g in GUARDRAILS})
    chats: dict = field(default_factory=dict)
    seen_events: set = field(default_factory=set)
    log: list = field(default_factory=list)       # (kind, detail) for the eval
    handoffs: list = field(default_factory=list)  # (chat_id, reason)
    chat_phone: dict = field(default_factory=dict)
    _current_event: str = ""
    _n_sent: int = 0

    # ------------------------------------------------------------------ entry points
    def receive(self, headers: dict, raw_body: str, secret: str, now_s: float | None = None,
                now_min: float = 0.0) -> int:
        """What a webhook endpoint calls: verify the signature on the raw body, then handle.
        Returns the HTTP status to answer Linq with."""
        ok = verify_webhook(secret, headers, raw_body, now=now_s)
        self.handle(json.loads(raw_body), now_min=now_min, signature_ok=ok)
        return 200 if ok or not self.guards["verify_signature"] else 401

    def handle(self, event: dict, now_min: float = 0.0, signature_ok: bool = True) -> None:
        if not signature_ok and self.guards["verify_signature"]:
            self.log.append(("rejected", "bad signature"))
            return
        eid = event.get("event_id")
        if self.guards["dedupe_events"] and eid in self.seen_events:
            self.log.append(("ignored", "duplicate event"))
            return
        self.seen_events.add(eid)
        self._current_event, self._n_sent = eid, 0
        et = event["event_type"]
        if et == "message.received":
            self._on_text(event["data"], now_min)
        elif et.startswith("payment."):
            self._on_payment(et, event["data"])
        elif et == "order.ready":  # from the brand's POS, not Linq
            self._on_ready(event["data"])

    # ------------------------------------------------------------------ helpers
    def _say(self, chat_id: str, text: str) -> None:
        phone = self.chat_phone.get(chat_id)
        m = self.store.members.get(phone)
        if m and m.opted_out and self.guards["stop_optout"]:
            self.log.append(("suppressed", text))
            return
        self.linq.typing_start(chat_id)
        self.linq.send(chat_id, [{"type": "text", "value": text}],
                       idempotency_key=f"{self._current_event}-{self._n_sent}")
        self._n_sent += 1
        self.log.append(("said", text))

    def _link(self, chat_id: str, url: str) -> None:
        # link parts must be sent on their own (Linq docs, Sending Messages)
        self.linq.send(chat_id, [{"type": "link", "value": url}],
                       idempotency_key=f"{self._current_event}-{self._n_sent}")
        self._n_sent += 1
        self.log.append(("link", url))

    def _handoff(self, chat_id: str, reason: str, store_key: str | None) -> None:
        st = self.chats[chat_id]
        st.handed_off = True
        st.draft = None
        where = STORES[store_key]["name"] if store_key else "our team"
        self.handoffs.append((chat_id, reason))
        self.log.append(("handoff", reason))
        self._say(chat_id, f"I'm passing this to a teammate at {where}, and they'll reply right here.")

    # ------------------------------------------------------------------ inbound text
    def _on_text(self, data: dict, now: float) -> None:
        chat_id = data["chat"]["id"]
        phone = data["sender_handle"]["handle"]
        text = " ".join(p.get("value", "") for p in data["parts"] if p["type"] == "text")
        self.chat_phone[chat_id] = phone
        st = self.chats.setdefault(chat_id, ChatState())
        member = self.store.members.get(phone)
        intent = classify(text)
        self.log.append(("intent", intent))

        if intent == "stop":
            if member:
                member.opted_out = True
            self.log.append(("opt_out", phone))
            if not self.guards["stop_optout"]:
                self._say(chat_id, "Sorry to see you go! Your usual is still saved if you change your mind.")
            return
        if member and member.opted_out and self.guards["stop_optout"]:
            self.log.append(("suppressed", "opted out"))
            return
        if st.handed_off:
            self.log.append(("human_owns_chat", text))
            return
        if member is None:
            self._say(chat_id, f"Hi! Text ordering is for rewards members. You can order in the app: {APP_LINK}")
            return

        if intent in ("refund", "complaint", "allergy"):
            if self.guards["handoff_money"]:
                return self._handoff(chat_id, intent, member.store)
            if intent == "allergy":
                self._say(chat_id, "Good news, that one should be fine for you!")
            else:
                self._say(chat_id, "So sorry about that! I've issued a refund to your card.")
            self.log.append(("unauthorized_promise", intent))
            return

        if intent in ("modify", "new_item"):
            if self.guards["handoff_changes"]:
                return self._handoff(chat_id, intent, member.store)
            intent = "reorder"  # naive: treats it as the usual and drops the change
            self.log.append(("ignored_change", text))

        if intent == "status":
            o = self.store.latest_order(phone)
            if o is None:
                self._say(chat_id, "I don't see a recent order. Text \"the usual\" to start one.")
            else:
                words = {"awaiting_payment": "waiting on payment", "paid": "paid and in the queue",
                         "in_progress": "being made", "ready": "ready for pickup",
                         "picked_up": "picked up",
                         "expired": "closed because the payment link expired (nothing was charged)"}[o.status]
                self._say(chat_id, f"Order {o.id} is {words} at {STORES[o.store]['name']}.")
            return

        if intent == "reorder":
            return self._start_reorder(chat_id, member, now)

        if intent == "confirm_yes":
            return self._confirm(chat_id, member, now)

        if intent == "confirm_no":
            st.draft = None
            self._say(chat_id, "No problem, nothing ordered.")
            return

        # greeting / unclear
        st.unclear_count += 1
        if st.unclear_count >= 2:
            return self._handoff(chat_id, "unclear", member.store)
        self._say(chat_id, f"Hi {member.first_name}! Text \"the usual\" to reorder, or \"status\" to check an order.")

    def _start_reorder(self, chat_id, member, now):
        st = self.chats[chat_id]
        if self.guards["no_duplicate"]:
            o = self.store.latest_order(member.phone)
            if o and o.status == "awaiting_payment":
                self._say(chat_id, f"Order {o.id} is still waiting on payment. Here's the link again.")
                pr = self.linq.payment_requests.get(o.payment_request_id) if hasattr(self.linq, "payment_requests") else None
                if pr:
                    self._link(chat_id, pr["checkout_url"])
                return
        if self.guards["store_open"] and not STORES[member.store]["open"]:
            self._say(chat_id, f"{STORES[member.store]['name']} is closed right now, so I can't place it. "
                               "Want me to pass this to a teammate to pick another store?")
            self.log.append(("store_closed", member.store))
            return
        items = member.usual
        total = Store.price(items)
        if self.guards["order_cap"] and total > ORDER_CAP_CENTS:
            return self._handoff(chat_id, "over_cap", member.store)
        st.draft, st.draft_at = items, now
        if not self.guards["confirm_first"]:
            return self._place(chat_id, member)
        self._say(chat_id, f"Your usual: {Store.describe(items)} at {STORES[member.store]['name']}, "
                           f"${total/100:.2f}. Reply YES and I'll send the payment link.")

    def _confirm(self, chat_id, member, now):
        st = self.chats[chat_id]
        if st.draft is None:
            self._say(chat_id, "Nothing is waiting on a YES. Text \"the usual\" to start an order.")
            return
        if self.guards["confirm_first"] and now - (st.draft_at or 0) > CONFIRM_TTL_MIN:
            st.draft = None
            self.log.append(("stale_confirm", now))
            return self._start_reorder(chat_id, member, now)
        self._place(chat_id, member)

    def _place(self, chat_id, member):
        st = self.chats[chat_id]
        o = self.store.create_order(member.phone, st.draft, member.store)
        st.draft = None
        pr = self.linq.create_payment_request(
            o.total_cents, f"Order {o.id}", {"order_id": o.id, "chat_id": chat_id})
        o.payment_request_id = pr["id"]
        self.log.append(("order_created", o.id))
        self._say(chat_id, f"Order {o.id}, ${o.total_cents/100:.2f}. Pay with Apple Pay here and we'll start it:")
        self._link(chat_id, pr["checkout_url"])

    # ------------------------------------------------------------------ other events
    def _order_by_pr(self, pr_id):
        for o in self.store.orders.values():
            if o.payment_request_id == pr_id:
                return o
        return None

    def _on_payment(self, et, data):
        o = self._order_by_pr(data["id"])
        if o is None:
            return
        chat_id = data["metadata"]["chat_id"]
        if et == "payment.succeeded":
            # Linq gives a replayed webhook a new event_id, so also check the order's own state
            if o.status != "awaiting_payment" and self.guards["dedupe_events"]:
                self.log.append(("ignored", "order already paid"))
                return
            o.status = "paid"
            self.log.append(("paid", o.id))
            self.store.send_to_kitchen(o)  # brand POS call; not idempotent, so dedupe matters
            self._say(chat_id, f"Paid, thanks! Order {o.id} is in the queue at {STORES[o.store]['name']}. "
                               "I'll text you when it's ready.")
        elif et in ("payment.expired", "payment.canceled", "payment.declined"):
            o.status = "expired"
            self.log.append(("payment_" + et.split(".")[1], o.id))
            self._say(chat_id, f"The payment link for order {o.id} expired, so nothing was charged or made. "
                               "Text \"the usual\" any time to start again.")

    def _on_ready(self, data):
        o = self.store.orders.get(data["order_id"])
        if o is None or o.status != "paid":
            return
        o.status = "ready"
        chat_id = data["chat_id"]
        self._say(chat_id, f"Order {o.id} is ready at {STORES[o.store]['name']}. Enjoy!")
