"""Run the agent against a real Linq sandbox line and your own phone.

  export LINQ_API_KEY=...        # from the Linq dashboard; never commit it
  export TEST_PHONE=+1415...     # your iPhone, E.164
  python -m live.run_live

Your number is enrolled as the sample member "Maya" (saved usual: large House Blend). The script
texts you once, then polls the chat for your replies and feeds each one to the same Agent the eval
uses. Payment requests need a connected Stripe account, so in sandbox the payment step is
simulated and labeled as such. Everything sent is written to live/transcript.json (no key in it).
"""
from __future__ import annotations

import json
import os
import sys
import time

from agent.agent import Agent
from agent.linq import LinqClient, inbound_message
from agent.store import Store

POLL_S = 3
MAX_MIN = 10


class SandboxLinq(LinqClient):
    """Real sends and typing; payment requests are simulated until Stripe is connected."""

    def __init__(self, token):
        super().__init__(token)
        self.payment_requests = {}
        self.sent = []

    def send(self, chat_id, parts, idempotency_key=None):
        self.sent.append(parts)
        return super().send(chat_id, parts, idempotency_key)

    def create_payment_request(self, amount_cents, description, metadata):
        pr_id = f"sim_{len(self.payment_requests) + 1}"
        pr = {"id": pr_id, "status": "requested", "metadata": metadata,
              "checkout_url": "https://example.com/simulated-checkout"}
        self.payment_requests[pr_id] = pr
        return pr


def main():
    token, phone = os.environ.get("LINQ_API_KEY"), os.environ.get("TEST_PHONE")
    if not token or not phone:
        sys.exit("Set LINQ_API_KEY and TEST_PHONE first.")
    store = Store.sample()
    maya = store.members.pop("+14155550101")
    maya.phone = phone
    store.members[phone] = maya
    linq = SandboxLinq(token)
    agent = Agent(linq=linq, store=store)

    first = linq.send_new([phone], [{"type": "text", "value":
        "Hi Maya, this is the demo coffee bar. Text \"the usual\" to reorder, or \"status\" for an order."}])
    chat_id = first["chat_id"]
    agent.chat_phone[chat_id] = phone
    log = [{"t": time.time(), "from": "agent", "text": "(opener)", "service": first.get("service")}]
    seen = set()
    start = time.time()
    finished = False
    while not finished and time.time() - start < MAX_MIN * 60:
        msgs = linq._call("GET", f"/v3/chats/{chat_id}/messages?limit=100")
        for m in msgs.get("messages", msgs.get("data", [])):
            if m.get("is_from_me") or m["id"] in seen:
                continue
            seen.add(m["id"])
            text = " ".join(p.get("value", "") for p in m.get("parts", []) if p.get("type") == "text")
            log.append({"t": time.time(), "from": "customer", "text": text})
            before = len(linq.sent)
            agent.handle(inbound_message(chat_id, phone, text), now_min=(time.time() - start) / 60)
            for parts in linq.sent[before:]:
                for p in parts:
                    log.append({"t": time.time(), "from": "agent", "type": p["type"], "text": p["value"]})
            if text.strip().lower() == "done":
                finished = True  # ends the whole session, not just this batch
                break
        if not finished:
            time.sleep(POLL_S)
    with open("live/transcript.json", "w") as f:
        json.dump(log, f, indent=1, ensure_ascii=False)
    print(f"Saved {len(log)} lines to live/transcript.json")


if __name__ == "__main__":
    main()
