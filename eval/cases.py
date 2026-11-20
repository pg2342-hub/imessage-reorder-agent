"""25 eval conversations. Steps:
  ("text", who, text, minute)   inbound iMessage from a sample member (or an unknown number)
  ("pay", status)               payment.<status> webhook for that customer's latest payment request
  ("ready",)                    the store marks that customer's latest order ready
  ("dup",)                      Linq delivers the previous webhook again (same event_id)
  ("forged", who, text)         a webhook with a bad signature
Expectations:
  orders        number of orders the agent should create
  status        status of the latest order at the end (optional)
  handoff       reason the chat should go to a person, or None
  say / not_say substrings that must / must not appear in what the agent texted
  silent        the agent must send nothing at all
"""
MAYA, DEV, ANA, SAM, STRANGER = "+14155550101", "+14155550102", "+14155550103", "+14155550104", "+14155550199"

CASES = [
    # --- reorders the agent completes on its own (8)
    dict(id=1, group="Reorder", title="\"the usual\", YES, pays, pickup",
         steps=[("text", MAYA, "the usual", 0), ("text", MAYA, "YES", 1), ("pay", "succeeded"), ("ready",)],
         orders=1, status="ready", handoff=None, say=["Reply YES", "ready at Mission St"]),
    dict(id=2, group="Reorder", title="\"same as last time pls\" with two items",
         steps=[("text", DEV, "same as last time pls", 0), ("text", DEV, "yes", 2), ("pay", "succeeded")],
         orders=1, status="paid", handoff=None, say=["$11.00"]),
    dict(id=3, group="Reorder", title="Thumbs-up emoji as the YES",
         steps=[("text", MAYA, "usual", 0), ("text", MAYA, "👍", 1), ("pay", "succeeded")],
         orders=1, status="paid", handoff=None),
    dict(id=4, group="Reorder", title="Starts a reorder, then says no",
         steps=[("text", MAYA, "reorder my usual", 0), ("text", MAYA, "no", 1)],
         orders=0, handoff=None, say=["nothing ordered"]),
    dict(id=5, group="Reorder", title="\"Can I get the usual?\"",
         steps=[("text", DEV, "Can I get the usual?", 0), ("text", DEV, "ok", 1), ("pay", "succeeded")],
         orders=1, status="paid", handoff=None),
    dict(id=6, group="Reorder", title="Texts again before paying (no second order)",
         steps=[("text", MAYA, "the usual", 0), ("text", MAYA, "yes", 1), ("text", MAYA, "the usual", 3)],
         orders=1, status="awaiting_payment", handoff=None, say=["still waiting on payment"]),
    dict(id=7, group="Reorder", title="YES after 45 minutes gets re-confirmed first",
         steps=[("text", MAYA, "the usual", 0), ("text", MAYA, "yes", 45), ("text", MAYA, "yes", 46)],
         orders=1, status="awaiting_payment", handoff=None, stale=True),
    dict(id=8, group="Reorder", title="Payment link expires, nothing charged",
         steps=[("text", MAYA, "the usual", 0), ("text", MAYA, "yes", 1), ("pay", "expired"),
                ("text", MAYA, "status?", 30)],
         orders=1, status="expired", handoff=None, say=["nothing was charged"]),
    # --- order status (4)
    dict(id=9, group="Status", title="Asks for status with no recent order",
         steps=[("text", MAYA, "is my order ready?", 0)],
         orders=0, handoff=None, say=["don't see a recent order"]),
    dict(id=10, group="Status", title="Asks where the order is after paying",
         steps=[("text", MAYA, "the usual", 0), ("text", MAYA, "yes", 1), ("pay", "succeeded"),
                ("text", MAYA, "where's my order", 5)],
         orders=1, status="paid", handoff=None, say=["paid and in the queue"]),
    dict(id=11, group="Status", title="Asks for status before paying",
         steps=[("text", DEV, "the usual", 0), ("text", DEV, "yes", 1), ("text", DEV, "status?", 4)],
         orders=1, status="awaiting_payment", handoff=None, say=["waiting on payment"]),
    dict(id=12, group="Status", title="Asks once it's ready",
         steps=[("text", MAYA, "the usual", 0), ("text", MAYA, "yes", 1), ("pay", "succeeded"), ("ready",),
                ("text", MAYA, "is it ready", 9)],
         orders=1, status="ready", handoff=None, say=["ready for pickup"]),
    # --- goes to a person (8)
    dict(id=13, group="Handoff", title="\"the usual but with oat milk\", then yes",
         steps=[("text", MAYA, "the usual but with oat milk", 0), ("text", MAYA, "yes", 1)], orders=0, handoff="modify"),
    dict(id=14, group="Handoff", title="Wants to try a new drink, then says yes",
         steps=[("text", DEV, "I'd like to try the cold brew today", 0), ("text", DEV, "yes", 1)], orders=0, handoff="new_item"),
    dict(id=15, group="Handoff", title="Asks to add a croissant, then yes",
         steps=[("text", MAYA, "can I get a croissant too", 0), ("text", MAYA, "yes", 1)], orders=0, handoff="new_item"),
    dict(id=16, group="Handoff", title="\"I was charged twice yesterday\"",
         steps=[("text", DEV, "I was charged twice yesterday", 0)], orders=0, handoff="refund",
         not_say=["issued a refund"]),
    dict(id=17, group="Handoff", title="\"my drink was wrong this morning\"",
         steps=[("text", MAYA, "my drink was wrong this morning", 0)], orders=0, handoff="complaint",
         not_say=["issued a refund"]),
    dict(id=18, group="Handoff", title="Allergy question",
         steps=[("text", DEV, "does the iced mint have nuts? I'm allergic", 0)], orders=0, handoff="allergy",
         not_say=["should be fine for you"]),
    dict(id=19, group="Handoff", title="Usual is 6 drinks, $39 (over the $30 cap)",
         steps=[("text", SAM, "the usual", 0), ("text", SAM, "yes", 1)], orders=0, handoff="over_cap"),
    dict(id=20, group="Handoff", title="Two unclear texts, then the person owns the chat",
         steps=[("text", MAYA, "hey", 0), ("text", MAYA, "hmm idk", 1), ("text", MAYA, "the usual", 2),
                ("text", MAYA, "yes", 3)],
         orders=0, handoff="unclear"),
    # --- must not act (5)
    dict(id=21, group="No action", title="STOP, then \"the usual\"",
         steps=[("text", MAYA, "STOP", 0), ("text", MAYA, "the usual", 5), ("text", MAYA, "yes", 6)],
         orders=0, handoff=None, silent=True),
    dict(id=22, group="No action", title="Linq delivers the payment webhook twice",
         steps=[("text", MAYA, "the usual", 0), ("text", MAYA, "yes", 1), ("pay", "succeeded"), ("dup",)],
         orders=1, status="paid", handoff=None),
    dict(id=23, group="No action", title="Forged webhooks with a bad signature",
         steps=[("forged", MAYA, "the usual"), ("forged", MAYA, "yes")],
         orders=0, handoff=None, silent=True),
    dict(id=24, group="No action", title="Pickup store is closed",
         steps=[("text", ANA, "the usual", 0), ("text", ANA, "yes", 1)],
         orders=0, handoff=None, say=["closed right now"]),
    dict(id=25, group="No action", title="Unknown number texts \"the usual\"",
         steps=[("text", STRANGER, "the usual", 0), ("text", STRANGER, "yes", 1)],
         orders=0, handoff=None, say=["rewards members"]),
]
