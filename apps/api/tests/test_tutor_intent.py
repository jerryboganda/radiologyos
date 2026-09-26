"""Deterministic tutor intent routing (ADR 0028): table-driven cases."""

from __future__ import annotations

import pytest
from packages.tutor.intent import INTENTS, classify_intent, compare_subjects, quiz_topic


@pytest.mark.parametrize(("question", "intent"), [
    ("What is crazy paving?", "explain"),
    ("Explain the dural tail sign", "explain"),
    ("Describe the imaging features of PAP", "explain"),
    ("What was reported about Bosniak IIF follow-up?", "explain"),
    ("Dermoid vs epidermoid cyst on MRI?", "compare"),
    ("Dermoid versus epidermoid", "compare"),
    ("Compare UIP and NSIP", "compare"),
    ("What is the difference between a Bosniak IIF and III cyst?", "compare"),
    ("How do schwannoma and meningioma differ at the CP angle?", "compare"),
    ("Differentiate between osteoid osteoma and osteoblastoma", "compare"),
    ("DDx of ring-enhancing lesions", "ddx"),
    ("Differential diagnosis of crazy paving", "ddx"),
    ("45-year-old with a lytic lesion in the femur", "ddx"),
    ("What could this be: a fat-containing adrenal mass", "ddx"),
    ("Causes of bilateral hilar lymphadenopathy", "ddx"),
    ("Show me the claw sign", "show_me"),
    ("What does a Bosniak III cyst look like?", "show_me"),
    ("Images of pneumatosis intestinalis", "show_me"),
    ("How do I report a CT for appendicitis?", "report"),
    ("Structured report template for prostate MRI", "report"),
    ("Write a report for this chest radiograph", "report"),
    ("Quiz me on renal masses", "quiz"),
    ("Test me on neuro spotters", "quiz"),
    ("Give me 5 MCQs on the pancreas", "quiz"),
    ("SBAs on paediatric chest", "quiz"),
    ("Ask me some questions about the knee", "quiz"),
    ("Quiz me on the DDx of dermoid vs epidermoid", "quiz"),  # quiz wins over compare
    ("Compare the DDx of ring lesions vs cystic lesions", "compare"),  # compare over ddx
])
def test_intent_table(question: str, intent: str) -> None:
    route = classify_intent(question)
    assert route.intent == intent
    assert route.intent in INTENTS


@pytest.mark.parametrize(("question", "subjects"), [
    ("Dermoid vs epidermoid cyst on MRI?", ("Dermoid", "epidermoid cyst")),
    ("Compare UIP and NSIP", ("UIP", "NSIP")),
    ("What is the difference between a Bosniak IIF and III cyst?", ("Bosniak IIF", "III cyst")),
    ("Osteoid osteoma versus osteoblastoma.", ("Osteoid osteoma", "osteoblastoma")),
    ("Compare these two", ()),
    ("X vs x", ()),
])
def test_compare_subjects(question: str, subjects: tuple[str, ...]) -> None:
    assert compare_subjects(question) == subjects


def test_compare_route_carries_subjects_and_quiz_carries_topic() -> None:
    assert classify_intent("Dermoid vs epidermoid?").subjects == ("Dermoid", "epidermoid")
    quiz = classify_intent("Quiz me on renal masses?")
    assert quiz.subjects == ("renal masses",) and quiz.topic == "renal masses"
    assert quiz_topic("test me") == "test me"


def test_classifier_is_bounded_on_long_input() -> None:
    route = classify_intent("vs " * 5000 + "compare a and b")
    assert route.intent == "compare"
    assert all(len(s) <= 120 for s in route.subjects)
