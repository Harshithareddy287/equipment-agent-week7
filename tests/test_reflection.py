"""Unit tests for agent/reflection.py parsing and application (no LLM)."""

import json

from agent.reflection import apply_reflection, parse_reflection

APPROVE_DRAFT = "Approved. It will arrive by Friday.\n\nDECISION: APPROVE"
ESCALATE_DRAFT = "Sent for review, ticket ESC-0001.\n\nDECISION: ESCALATE"


def revised(text, issues=("fixed",)):
    return {"verdict": "REVISED", "issues": list(issues), "revised_response": text}


# --- parse_reflection --------------------------------------------------------------------

def test_parse_plain_json():
    raw = json.dumps({"verdict": "CONFIRMED", "issues": [], "revised_response": ""})
    assert parse_reflection(raw) == {"verdict": "CONFIRMED", "issues": [], "revised_response": ""}


def test_parse_fenced_json():
    raw = ('```json\n{"verdict": "revised", "issues": ["promised Friday delivery"], '
           '"revised_response": "Approved.\\nDECISION: APPROVE"}\n```')
    result = parse_reflection(raw)
    assert result["verdict"] == "REVISED"           # case normalized
    assert result["issues"] == ["promised Friday delivery"]
    assert result["revised_response"].endswith("DECISION: APPROVE")


def test_parse_json_with_surrounding_text():
    raw = 'Here is my review: {"verdict": "CONFIRMED", "issues": [], "revised_response": ""} done'
    assert parse_reflection(raw)["verdict"] == "CONFIRMED"


def test_parse_invalid_text_is_error():
    result = parse_reflection("The draft looks fine to me.")
    assert result["verdict"] == "ERROR"
    assert result["issues"]


def test_parse_broken_json_and_unknown_verdict_are_errors():
    assert parse_reflection('{"verdict": "CONFIRMED", ')["verdict"] == "ERROR"
    assert parse_reflection('{"verdict": "MAYBE"}')["verdict"] == "ERROR"
    assert parse_reflection(None)["verdict"] == "ERROR"


# --- apply_reflection --------------------------------------------------------------------

def test_confirmed_keeps_draft():
    text, notes = apply_reflection(APPROVE_DRAFT, {"verdict": "CONFIRMED", "issues": []})
    assert text == APPROVE_DRAFT
    assert notes == []


def test_revised_replaces_text():
    fixed = "Approved.\n\nDECISION: APPROVE"
    text, notes = apply_reflection(APPROVE_DRAFT, revised(fixed, ["promised Friday delivery"]))
    assert text == fixed
    assert notes == []


def test_revised_cannot_loosen_escalate():
    text, notes = apply_reflection(ESCALATE_DRAFT, revised("Approved.\nDECISION: APPROVE"))
    assert text == ESCALATE_DRAFT
    assert notes == ["reflection tried to loosen ESCALATE; kept draft"]


def test_revised_can_tighten_to_escalate():
    tightened = "This needs human review.\nDECISION: ESCALATE"
    text, notes = apply_reflection(APPROVE_DRAFT, revised(tightened))
    assert text == tightened
    assert notes == []


def test_revised_without_decision_line_keeps_draft():
    text, notes = apply_reflection(APPROVE_DRAFT, revised("Approved, no decision line."))
    assert text == APPROVE_DRAFT
    assert "no valid DECISION line" in notes[0]


def test_error_keeps_draft():
    text, notes = apply_reflection(APPROVE_DRAFT, {"verdict": "ERROR", "issues": ["refused"]})
    assert text == APPROVE_DRAFT
    assert "could not run" in notes[0]
