import base64
import os
import unittest

from agent.agent import GUARDRAILS, Agent
from agent.intents import classify
from agent.linq import FakeLinq, inbound_message, sign_webhook, verify_webhook
from agent.store import Store
from eval.run_eval import run_all

SECRET = "whsec_" + base64.b64encode(os.urandom(24)).decode()
MAYA = "+14155550101"


class WebhookTests(unittest.TestCase):
    def test_good_signature(self):
        sig = sign_webhook(SECRET, "evt_1", 1_700_000_000, '{"a":1}')
        h = {"webhook-id": "evt_1", "webhook-timestamp": "1700000000", "webhook-signature": sig}
        self.assertTrue(verify_webhook(SECRET, h, '{"a":1}', now=1_700_000_010))

    def test_tampered_body(self):
        sig = sign_webhook(SECRET, "evt_1", 1_700_000_000, '{"a":1}')
        h = {"webhook-id": "evt_1", "webhook-timestamp": "1700000000", "webhook-signature": sig}
        self.assertFalse(verify_webhook(SECRET, h, '{"a":2}', now=1_700_000_010))

    def test_stale_timestamp(self):
        sig = sign_webhook(SECRET, "evt_1", 1_700_000_000, "{}")
        h = {"webhook-id": "evt_1", "webhook-timestamp": "1700000000", "webhook-signature": sig}
        self.assertFalse(verify_webhook(SECRET, h, "{}", now=1_700_000_000 + 600))


class IntentTests(unittest.TestCase):
    def test_labels(self):
        cases = {"the usual": "reorder", "the usual but with oat milk": "modify", "STOP": "stop",
                 "👍": "confirm_yes", "I was charged twice": "refund", "where's my order": "status",
                 "I'd like to try the cold brew": "new_item", "my drink was wrong": "complaint",
                 "the usual, iced": "modify", "usual, large please": "modify", "the usual at SoMa": "modify",
                 "the usual x2": "modify", "stop texting me": "stop", "unsubscribe me": "stop", "please stop": "stop", "no stop": "stop",
                 "stop please": "stop", "can you stop texting me": "stop",
                 "yes please": "confirm_yes", "sure": "confirm_yes"}
        for text, want in cases.items():
            self.assertEqual(classify(text), want, text)


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.linq = FakeLinq()
        self.agent = Agent(linq=self.linq, store=Store.sample())

    def test_typing_before_each_text(self):
        self.agent.handle(inbound_message("c1", MAYA, "the usual"))
        names = [n for n, _ in self.linq.calls]
        self.assertEqual(names[:2], ["typing_start", "send"])

    def test_link_sent_alone(self):
        self.agent.handle(inbound_message("c1", MAYA, "the usual"))
        self.agent.handle(inbound_message("c1", MAYA, "yes"), now_min=1)
        links = [c for n, c in self.linq.calls if n == "send" and c["parts"][0]["type"] == "link"]
        self.assertEqual(len(links), 1)
        self.assertEqual(len(links[0]["parts"]), 1)

    def test_no_order_without_yes(self):
        self.agent.handle(inbound_message("c1", MAYA, "the usual"))
        self.assertEqual(len(self.agent.store.orders), 0)


class ReceiveTests(unittest.TestCase):
    def test_bad_signature_is_rejected_and_ignored(self):
        linq = FakeLinq()
        agent = Agent(linq=linq, store=Store.sample())
        ev = inbound_message("c1", MAYA, "the usual")
        body = __import__("json").dumps(ev)
        other = "whsec_" + base64.b64encode(os.urandom(24)).decode()
        h = {"webhook-id": ev["event_id"], "webhook-timestamp": "1700000000",
             "webhook-signature": sign_webhook(other, ev["event_id"], 1_700_000_000, body)}
        self.assertEqual(agent.receive(h, body, SECRET, now_s=1_700_000_005), 401)
        self.assertEqual(linq.calls, [])

    def test_replayed_payment_with_new_event_id_reaches_kitchen_once(self):
        from agent.linq import make_event
        linq = FakeLinq()
        agent = Agent(linq=linq, store=Store.sample())
        agent.handle(inbound_message("c1", MAYA, "the usual"))
        agent.handle(inbound_message("c1", MAYA, "yes"), now_min=1)
        pr = next(iter(linq.payment_requests.values()))
        for _ in range(2):  # two deliveries, two different event ids
            agent.handle(make_event("payment.succeeded", {"id": pr["id"], "metadata": pr["metadata"]}))
        self.assertEqual(len(agent.store.kitchen_tickets), 1)

    def test_sends_carry_idempotency_keys(self):
        linq = FakeLinq()
        agent = Agent(linq=linq, store=Store.sample())
        agent.handle(inbound_message("c1", MAYA, "the usual"))
        keys = [c["key"] for n, c in linq.calls if n == "send"]
        self.assertTrue(all(keys))


class EvalTests(unittest.TestCase):
    def test_all_cases_pass_with_guardrails_on(self):
        res = run_all({g: True for g in GUARDRAILS})
        self.assertEqual([r["id"] for r in res if not r["passed"]], [])

    def test_every_guardrail_is_caught_by_some_case(self):
        for g in GUARDRAILS:
            res = run_all({**{x: True for x in GUARDRAILS}, g: False})
            self.assertTrue(any(not r["passed"] for r in res), g)


if __name__ == "__main__":
    unittest.main()
