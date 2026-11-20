# iMessage reorder agent

Demo page: https://pg2342-hub.github.io/imessage-reorder-agent/

A coffee chain member texts "the usual," confirms with YES, pays through an Apple Pay link, and gets a text when the drink is ready. The agent runs on [Linq's](https://linqapp.com) iMessage API (v3). It handles order status and reorders of a saved usual on its own, and passes everything else to a person: new items, changes to the usual, refunds, complaints, allergy questions, and orders over $30.

It was written as a pilot sketch for a regional coffee chain with an order-ahead app and a rewards program. **All menu items, prices, stores and customers in this repo are sample data made up for the demo.**

## Results

`python -m eval.run_eval --ablate` runs 25 scripted conversations against the agent with a fake Linq client.

| Setup | Conversations passed | With a critical failure |
|---|---|---|
| All 9 rules on | 25 of 25 | 0 |
| All 9 rules off | 3 of 25 | 12 |

Every rule is caught by at least one conversation when it is switched off:

| Rule switched off | What breaks |
|---|---|
| Stop all messages after STOP | Texts someone who opted out (critical) |
| Ignore a webhook Linq delivers twice | Sends the same paid order to the kitchen twice (critical) |
| Reject webhooks with a bad or stale signature | Acts on forged texts (critical) |
| New items and changes go to a person | Places the plain usual when the customer asked for oat milk or a new drink (3 critical) |
| Refunds, complaints and allergy questions go to a person | Promises refunds and answers an allergy question itself (3 critical) |
| Orders over $30 go to a person | Places a $39 order on its own (critical) |
| YES before the payment link, re-confirm a stale YES | Sends payment links before anyone confirmed (12 conversations) |
| No second order while one waits for payment | Opens a duplicate order |
| Pickup store must be open | Takes an order for a closed store (critical) |

## How it uses Linq

- `POST /v3/chats/{chat_id}/typing` before every reply, so the customer sees the typing bubble while the agent works.
- `POST /v3/chats/{chat_id}/messages` for replies. The payment link goes as its own `link` part, since link parts must be sent alone.
- `POST /v3/payment_requests` creates the Apple Pay checkout. The order moves to the kitchen only on the `payment.succeeded` webhook.
- Webhooks are verified with the Standard Webhooks scheme (HMAC-SHA256 over `id.timestamp.body`, 5-minute window) and de-duplicated by `event_id`.

## Run it

```
python -m unittest discover -s tests -t .
python -m eval.run_eval --ablate
python -m eval.run_eval --json docs/data.json   # rebuilds the demo page data (512 rule combinations)
```

Python 3.10+, standard library only.

### Live run against a Linq sandbox line

```
export LINQ_API_KEY=...      # from the Linq dashboard
export TEST_PHONE=+1...      # your own iPhone
python -m live.run_live
```

Your phone gets one text, then the script feeds your replies to the same agent. Payment requests need a connected Stripe account, so in the sandbox the payment step is simulated and marked as such.

## Layout

```
agent/linq.py      Linq v3 client, fake client, webhook signing and verification
agent/intents.py   rule-based intent labels (an LLM classifier can be plugged in)
agent/agent.py     the agent and its 9 rules
agent/store.py     sample menu, stores, members and orders
eval/cases.py      the 25 conversations and what each should end with
eval/run_eval.py   scoring, ablation, demo data
live/run_live.py   live run against a Linq sandbox line
docs/              GitHub Pages demo
```
