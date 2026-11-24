"""Unit tests for agent/rules.py: the code-enforced decision rules (sections 8.2-8.4). No LLM."""

import pytest

from agent.rules import (
    allowed_decisions,
    detect_triggers,
    escalation_codes,
    extract_employee_id,
    finalize,
    format_reason,
    parse_decision,
)

# Section 11 request texts.
REQUESTS = {
    "E001": "E001: My monitor is 4 years old. Can I get a replacement?",
    "E002": "E002: I need a new laptop for my project.",
    "E003": "E003: My laptop is slow. Can I get a new one?",
    "E004": "E004: I need a standing desk because of a back injury.",
    "E005": "E005: My laptop is over 3 years old. Can I get a replacement? I need it by Friday.",
    "E006": "E006: Can I get a replacement for my monitor?",
    "E008": "E008: My laptop was stolen. I need a replacement.",
}
NO_ID = "I need a new monitor."


# --- extract_employee_id -----------------------------------------------------------------

@pytest.mark.parametrize("key", list(REQUESTS))
def test_extract_employee_id_from_section_11(key):
    assert extract_employee_id(REQUESTS[key]) == key


@pytest.mark.parametrize(
    "text, expected",
    [
        ("e003: my laptop is slow", "E003"),        # lowercase -> uppercased
        ("Hi, I'm E004 and also E005", "E004"),     # first match wins
        (NO_ID, None),
        ("", None),
        (None, None),
        ("E0001 or XE001", None),                   # whole word, exactly 3 digits
    ],
)
def test_extract_employee_id_edge_cases(text, expected):
    assert extract_employee_id(text) == expected


# --- detect_triggers ---------------------------------------------------------------------

def test_detect_triggers_medical():
    assert detect_triggers(REQUESTS["E004"]) == ["MEDICAL_OR_ACCESSIBILITY"]


def test_detect_triggers_stolen():
    assert detect_triggers(REQUESTS["E008"]) == ["BROKEN_OR_STOLEN"]


@pytest.mark.parametrize("key", ["E001", "E002", "E003", "E005", "E006"])
def test_detect_triggers_none(key):
    assert detect_triggers(REQUESTS[key]) == []


def test_detect_triggers_both_in_stable_order_without_duplicates():
    text = "My screen is CRACKED and broken, and my doctor says the pain is from my posture."
    assert detect_triggers(text) == ["MEDICAL_OR_ACCESSIBILITY", "BROKEN_OR_STOLEN"]


def test_detect_triggers_whole_words_only():
    # "painting", "brokerage", "lostwithiel" contain keywords but are not whole-word matches.
    assert detect_triggers("Painting team at the brokerage office in Lostwithiel") == []
    assert detect_triggers(None) == []


# --- parse_decision ----------------------------------------------------------------------

@pytest.mark.parametrize(
    "text, expected",
    [
        ("Approved.\n\nDECISION: APPROVE", "APPROVE"),
        ("Denied.\nDECISION: DENY\n", "DENY"),
        ("**DECISION: ESCALATE**", "ESCALATE"),                       # markdown bold
        ("decision: approve", "APPROVE"),                             # case-insensitive
        ("DECISION: DENY\n...on reflection...\nDECISION: ESCALATE", "ESCALATE"),  # last line wins
        ("I think we should approve this.", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_decision(text, expected):
    assert parse_decision(text) == expected


# --- allowed_decisions -------------------------------------------------------------------

@pytest.mark.parametrize(
    "statuses, triggers, expected",
    [
        ({"monitor": ["eligible"]}, [], {"APPROVE", "ESCALATE"}),
        ({"laptop": ["ineligible"]}, [], {"DENY", "ESCALATE"}),
        ({"laptop": ["borderline"]}, [], {"ESCALATE"}),
        ({"standing desk": ["unknown_item"]}, [], {"ESCALATE"}),
        ({"monitor": ["error"]}, [], {"ESCALATE"}),
        ({}, [], {"ESCALATE"}),                                        # no status
        ({"monitor": ["eligible"]}, ["MEDICAL_OR_ACCESSIBILITY"], {"ESCALATE"}),  # trigger
        ({"monitor": ["eligible", "ineligible"]}, [], {"ESCALATE"}),   # conflicting statuses
        ({"monitor": ["eligible", "eligible"]}, [], {"APPROVE", "ESCALATE"}),     # same twice: fine
        ({"monitor": ["eligible"], "laptop": ["ineligible"]}, [], {"ESCALATE"}),  # mixed items
    ],
)
def test_allowed_decisions(statuses, triggers, expected):
    assert allowed_decisions(statuses, triggers) == expected


# --- escalation_codes / format_reason ----------------------------------------------------

@pytest.mark.parametrize(
    "result, code",
    [
        ({"status": "borderline", "item": "laptop"}, "BORDERLINE_ELIGIBILITY"),
        ({"status": "unknown_item", "item": "standing desk"}, "ITEM_NOT_IN_CATALOG"),
        ({"status": "error", "item": "monitor", "error_code": "EMPLOYEE_NOT_FOUND"}, "UNKNOWN_EMPLOYEE"),
        ({"status": "error", "item": "monitor", "error_code": "INVALID_EMPLOYEE_ID"}, "MISSING_EMPLOYEE_ID"),
        ({"status": "error", "item": "headset", "error_code": "ROLE_NOT_IN_POLICY"}, "DATA_ERROR"),
        ({"status": "error", "item": "monitor", "error_code": "INVALID_REQUEST_TYPE"}, "DATA_ERROR"),
    ],
)
def test_escalation_codes_from_results(result, code):
    assert escalation_codes([result], []) == [code]


def test_escalation_codes_none_for_clear_results():
    results = [{"status": "eligible", "item": "monitor"}, {"status": "ineligible", "item": "laptop"}]
    assert escalation_codes(results, []) == []


def test_escalation_codes_combines_results_and_triggers():
    results = [{"status": "unknown_item", "item": "standing desk"}]
    assert escalation_codes(results, ["MEDICAL_OR_ACCESSIBILITY"]) == [
        "ITEM_NOT_IN_CATALOG", "MEDICAL_OR_ACCESSIBILITY",
    ]


def test_escalation_codes_conflict_is_data_error():
    results = [{"status": "eligible", "item": "monitor"}, {"status": "ineligible", "item": "monitor"}]
    assert escalation_codes(results, []) == ["DATA_ERROR"]


def test_format_reason():
    assert format_reason(["ITEM_NOT_IN_CATALOG", "MEDICAL_OR_ACCESSIBILITY"], "standing desk") == (
        "ITEM_NOT_IN_CATALOG; MEDICAL_OR_ACCESSIBILITY: standing desk"
    )
    assert format_reason(["A", "A"], " x ") == "A: x"     # duplicates removed, stripped
    assert format_reason([], "only text") == "only text"
    assert format_reason(["A"], "") == "A"


# --- finalize ----------------------------------------------------------------------------

def eligibility_step(status, item="monitor", **extra):
    return {"tool": "check_request_eligibility", "args": {},
            "observation": {"status": status, "reason": "...", "item": item, **extra}}


def flag_step(ticket="ESC-0001"):
    return {"tool": "flag_for_human_review", "args": {},
            "observation": {"status": "pending_review", "ticket_id": ticket}}


def make_trace(steps, final_text, **flags):
    return {"steps": steps, "final_text": final_text,
            "step_limit_reached": False, "refused": False, **flags}


def test_finalize_eligible_approve_stays_approve():
    f = finalize(make_trace([eligibility_step("eligible")], "OK.\nDECISION: APPROVE"), REQUESTS["E001"])
    assert f["decision"] == "APPROVE"
    assert f["needs_ticket"] is False
    assert f["override_note"] is None
    assert f["reason_codes"] == []


def test_finalize_eligible_deny_is_overridden():
    f = finalize(make_trace([eligibility_step("eligible")], "No.\nDECISION: DENY"), REQUESTS["E001"])
    assert f["decision"] == "ESCALATE"
    assert f["reason_codes"] == ["REFLECTION_MISMATCH"]
    assert f["needs_ticket"] is True
    assert "DENY" in f["override_note"]


def test_finalize_ineligible_deny_stays_deny():
    trace = make_trace([eligibility_step("ineligible", "laptop")], "No.\nDECISION: DENY")
    f = finalize(trace, REQUESTS["E002"])
    assert f["decision"] == "DENY"
    assert f["needs_ticket"] is False


def test_finalize_borderline_approve_is_overridden():
    trace = make_trace([eligibility_step("borderline", "laptop")], "Yes.\nDECISION: APPROVE")
    f = finalize(trace, REQUESTS["E003"])
    assert f["decision"] == "ESCALATE"
    assert f["reason_codes"] == ["REFLECTION_MISMATCH", "BORDERLINE_ELIGIBILITY"]
    assert f["needs_ticket"] is True


def test_finalize_borderline_escalate_with_ticket():
    trace = make_trace([eligibility_step("borderline", "laptop"), flag_step()],
                       "Sent for review, ticket ESC-0001.\nDECISION: ESCALATE")
    f = finalize(trace, REQUESTS["E003"])
    assert f["decision"] == "ESCALATE"
    assert f["reason_codes"] == ["BORDERLINE_ELIGIBILITY"]
    assert f["needs_ticket"] is False
    assert f["ticket_id"] == "ESC-0001"
    assert f["override_note"] is None


def test_finalize_escalate_without_flag_call_needs_ticket():
    trace = make_trace([eligibility_step("borderline", "laptop")], "Needs review.\nDECISION: ESCALATE")
    f = finalize(trace, REQUESTS["E003"])
    assert f["decision"] == "ESCALATE"
    assert f["needs_ticket"] is True


def test_finalize_trigger_overrides_eligible_approve():
    trace = make_trace([eligibility_step("eligible", "laptop")], "Approved.\nDECISION: APPROVE")
    f = finalize(trace, "E005: my laptop is broken, can I get a replacement?")
    assert f["decision"] == "ESCALATE"
    assert f["reason_codes"] == ["REFLECTION_MISMATCH", "BROKEN_OR_STOLEN"]
    assert f["needs_ticket"] is True


def test_finalize_step_limit():
    f = finalize(make_trace([eligibility_step("eligible")], "", step_limit_reached=True), REQUESTS["E001"])
    assert f["decision"] == "ESCALATE"
    assert f["reason_codes"][0] == "AGENT_STEP_LIMIT"
    assert f["needs_ticket"] is True


def test_finalize_refused():
    f = finalize(make_trace([], "", refused=True), REQUESTS["E001"])
    assert f["decision"] == "ESCALATE"
    assert f["reason_codes"] == ["AGENT_ERROR"]
    assert f["needs_ticket"] is True


def test_finalize_empty_final_text_is_agent_error():
    f = finalize(make_trace([eligibility_step("eligible")], "   "), REQUESTS["E001"])
    assert f["reason_codes"] == ["AGENT_ERROR"]


def test_finalize_no_employee_id():
    f = finalize(make_trace([], ""), NO_ID)
    assert f["decision"] == "ESCALATE"
    assert f["reason_codes"] == ["MISSING_EMPLOYEE_ID"]
    assert f["needs_ticket"] is True


def test_finalize_conflicting_statuses_for_same_item():
    trace = make_trace(
        [eligibility_step("ineligible", "monitor", request_type="additional"),
         eligibility_step("eligible", "monitor", request_type="replacement")],
        "Approved.\nDECISION: APPROVE",
    )
    f = finalize(trace, "E007: Can I get another monitor?")
    assert f["decision"] == "ESCALATE"
    assert "DATA_ERROR" in f["reason_codes"]


def test_finalize_missing_decision_line_is_overridden():
    f = finalize(make_trace([eligibility_step("eligible")], "Approved, enjoy."), REQUESTS["E001"])
    assert f["decision"] == "ESCALATE"
    assert f["reason_codes"] == ["REFLECTION_MISMATCH"]


def test_finalize_ticket_filed_but_draft_approves():
    trace = make_trace([eligibility_step("eligible"), flag_step()], "Approved.\nDECISION: APPROVE")
    f = finalize(trace, REQUESTS["E001"])
    assert f["decision"] == "ESCALATE"   # never move away from ESCALATE once a ticket exists
    assert f["needs_ticket"] is False
