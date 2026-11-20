"""Intent detection for inbound texts.

Default is a small rule-based classifier so the eval is deterministic and free to run.
An LLM classifier can be plugged in with classify(text, llm=callable); it must return one of
INTENTS. The guardrails in agent.py do not trust the classifier for anything that moves money:
an order is only placed for the member's saved usual, after an explicit YES.
"""
from __future__ import annotations

import re

INTENTS = [
    "reorder", "confirm_yes", "confirm_no", "status", "modify", "new_item",
    "refund", "complaint", "allergy", "stop", "greeting", "unclear",
]

_STOP = re.compile(r"(^\s*((please|pls|no|just|ok)[,!.]?\s+)?(stop|end|quit|stopall|cancel all)(\s+(please|pls|now|it))?\s*[.!]*\s*$)|\b(unsubscribe|opt ?out|stop (texting|messaging|sending))\b", re.I)
_YES = re.compile(r"^\s*(y|yes|yep|yeah|yup|ok|okay|sure|confirm|do it|sounds good|perfect|👍)( please| thanks| thank you| pls)?\s*[.!]*\s*$", re.I)
_NO = re.compile(r"^\s*(n|no|nope|nah|not now|never ?mind|cancel)\s*[.!]*\s*$", re.I)
_REORDER = re.compile(r"\b(usual|same as (last time|always|before)|my regular|the regular|reorder|again)\b", re.I)
_MODIFY = re.compile(r"\b(but|except|instead|with|without|extra|swap|change|no cream|oat|almond|decaf|bigger|smaller|iced|hot|large|medium|small|at|for|x ?\d|\d ?x|two|three|double)\b", re.I)
_STATUS = re.compile(r"\b(where('?s| is)|status|ready|eta|how long|done yet|is it)\b", re.I)
_REFUND = re.compile(r"\b(refund|charged twice|double charged|overcharged|money back|charge)\b", re.I)
_COMPLAINT = re.compile(r"\b(wrong|(?:was|is|came|arrived) cold|missing|terrible|bad|never got|didn'?t get|messed up|rude)\b", re.I)
_ALLERGY = re.compile(r"\b(allerg\w*|nut|nuts|gluten|dairy[- ]free|lactose|vegan)\b", re.I)
_NEW = re.compile(r"\b(try|new|what('?s| is) good|recommend|menu|can i get|i'?d like|order)\b", re.I)
_GREETING = re.compile(r"^\s*(hi|hey|hello|yo|good morning)\b", re.I)


def classify(text: str, llm=None) -> str:
    if llm is not None:
        label = llm(text)
        return label if label in INTENTS else "unclear"
    t = text.strip()
    if _STOP.search(t):
        return "stop"
    if _YES.match(t):
        return "confirm_yes"
    if _NO.match(t):
        return "confirm_no"
    if _ALLERGY.search(t):
        return "allergy"
    if _REFUND.search(t):
        return "refund"
    if _COMPLAINT.search(t):
        return "complaint"
    if _REORDER.search(t):
        rest = _REORDER.sub("", t)
        return "modify" if _MODIFY.search(rest) else "reorder"
    if _STATUS.search(t):
        return "status"
    if _NEW.search(t):
        return "new_item"
    if _GREETING.match(t):
        return "greeting"
    return "unclear"
