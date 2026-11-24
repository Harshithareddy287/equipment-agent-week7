"""Deterministic decision rules for the agent (docs/requirements.md sections 8.2-8.4).

Pure functions: no LLM and no MCP, so they are unit-tested in CI. The LLM proposes a
draft decision; finalize() decides what is actually allowed to stand.
"""

import re

APPROVE, DENY, ESCALATE = "APPROVE", "DENY", "ESCALATE"

# Section 8.2 keyword triggers, in a stable order.
TRIGGER_KEYWORDS = {
    "MEDICAL_OR_ACCESSIBILITY": [
        "medical", "injury", "injured", "disability", "disabled",
        "accessibility", "ergonomic", "doctor", "pain",
    ],
    "BROKEN_OR_STOLEN": ["broken", "broke", "damaged", "cracked", "stolen", "lost", "missing"],
}

# Section 8.3: decisions allowed for each eligibility status.
ALLOWED_BY_STATUS = {
    "eligible": {APPROVE, ESCALATE},
    "ineligible": {DENY, ESCALATE},
    "borderline": {ESCALATE},
    "unknown_item": {ESCALATE},
    "error": {ESCALATE},
}

# Section 8.2: error_code -> escalation code (anything else is DATA_ERROR).
ERROR_CODE_TO_REASON = {
    "EMPLOYEE_NOT_FOUND": "UNKNOWN_EMPLOYEE",
    "INVALID_EMPLOYEE_ID": "MISSING_EMPLOYEE_ID",
}

_EMPLOYEE_ID = re.compile(r"\bE\d{3}\b", re.IGNORECASE)
_DECISION_LINE = re.compile(r"^\W*DECISION:\s*(APPROVE|DENY|ESCALATE)\b", re.IGNORECASE | re.MULTILINE)
_TRIGGER_PATTERNS = {
    code: re.compile(r"\b(" + "|".join(words) + r")\b", re.IGNORECASE)
    for code, words in TRIGGER_KEYWORDS.items()
}


def _unique(items):
    """Remove duplicates, keeping the first occurrence's order."""
    return list(dict.fromkeys(items))


# --- parsing the request and the draft -------------------------------------------------

def extract_employee_id(text: str | None) -> str | None:
    """First employee ID like E001 in the text (case-insensitive), uppercased; else None."""
    match = _EMPLOYEE_ID.search(text or "")
    return match.group(0).upper() if match else None


def detect_triggers(text: str | None) -> list[str]:
    """Escalation codes whose keywords appear as whole words in the text."""
    return [code for code, pattern in _TRIGGER_PATTERNS.items() if pattern.search(text or "")]


def parse_decision(text: str | None) -> str | None:
    """The decision on the last "DECISION: ..." line of the draft, or None."""
    found = _DECISION_LINE.findall(text or "")
    return found[-1].upper() if found else None


# --- what the tool results allow -------------------------------------------------------

def eligibility_results(trace: dict) -> list[dict]:
    """Observations of every check_request_eligibility call in the trace."""
    return [
        s["observation"] for s in trace.get("steps", [])
        if s.get("tool") == "check_request_eligibility" and isinstance(s.get("observation"), dict)
    ]


def statuses_by_item(results: list[dict]) -> dict[str, list[str]]:
    """{item: [status, ...]} from eligibility results, in call order."""
    by_item: dict[str, list[str]] = {}
    for r in results:
        by_item.setdefault(str(r.get("item")), []).append(r.get("status"))
    return by_item


def _has_conflict(statuses: dict[str, list[str]]) -> bool:
    return any(len(set(values)) > 1 for values in statuses.values())


def allowed_decisions(statuses: dict[str, list[str]], triggers: list[str]) -> set[str]:
    """Section 8.3: decisions allowed by the statuses ({item: [status, ...]}) and triggers.

    No status, any trigger, or different statuses for the same item -> ESCALATE only.
    With several items, a decision must be allowed for every one of them.
    """
    if triggers or not statuses or _has_conflict(statuses):
        return {ESCALATE}
    allowed = {APPROVE, DENY, ESCALATE}
    for values in statuses.values():
        allowed &= ALLOWED_BY_STATUS.get(values[0], {ESCALATE})
    return allowed


def escalation_codes(results: list[dict], triggers: list[str]) -> list[str]:
    """Section 8.2 reason codes implied by the eligibility results, plus trigger codes."""
    codes = []
    for r in results:
        status = r.get("status")
        if status == "borderline":
            codes.append("BORDERLINE_ELIGIBILITY")
        elif status == "unknown_item":
            codes.append("ITEM_NOT_IN_CATALOG")
        elif status == "error":
            codes.append(ERROR_CODE_TO_REASON.get(r.get("error_code"), "DATA_ERROR"))
    if _has_conflict(statuses_by_item(results)):
        codes.append("DATA_ERROR")
    return _unique(codes + list(triggers))


def format_reason(codes: list[str], explanation: str) -> str:
    """Ticket reason in the section 8.2 format: "CODE; CODE: explanation"."""
    codes = _unique(codes)
    explanation = explanation.strip()
    if not codes:
        return explanation
    return f"{'; '.join(codes)}: {explanation}" if explanation else "; ".join(codes)


# --- the final decision ----------------------------------------------------------------

def existing_ticket(trace: dict) -> str | None:
    """ticket_id of a successful flag_for_human_review call in the trace, if any."""
    for s in trace.get("steps", []):
        obs = s.get("observation")
        if (s.get("tool") == "flag_for_human_review" and isinstance(obs, dict)
                and obs.get("status") == "pending_review"):
            return obs.get("ticket_id")
    return None


def finalize(trace: dict, request: str) -> dict:
    """Decide the FINAL decision from the trace (sections 8.2-8.4).

    Returns {decision, reason_codes, needs_ticket, override_note} plus the inputs used
    (draft_decision, statuses, triggers, allowed, ticket_id) for printing.
    """
    triggers = detect_triggers(request)
    results = eligibility_results(trace)
    statuses = statuses_by_item(results)
    codes = escalation_codes(results, triggers)
    allowed = allowed_decisions(statuses, triggers)
    draft = parse_decision(trace.get("final_text"))
    ticket_id = existing_ticket(trace)

    decision, note = draft, None
    if extract_employee_id(request) is None:
        decision, codes = ESCALATE, _unique(["MISSING_EMPLOYEE_ID"] + codes)
        note = "no employee ID in the request"
    elif trace.get("refused") or not (trace.get("final_text") or "").strip():
        if trace.get("step_limit_reached"):
            decision, codes = ESCALATE, _unique(["AGENT_STEP_LIMIT"] + codes)
            note = "the agent reached the step limit without a decision"
        else:
            decision, codes = ESCALATE, _unique(["AGENT_ERROR"] + codes)
            note = "the model refused or gave no usable response"
    elif draft is None or draft not in allowed:
        decision, codes = ESCALATE, _unique(["REFLECTION_MISMATCH"] + codes)
        note = f"draft decision {draft} is not allowed (allowed: {', '.join(sorted(allowed))})"
    elif ticket_id and draft != ESCALATE:
        # A ticket was already filed; a decision can never move away from ESCALATE.
        decision, codes = ESCALATE, _unique(["REFLECTION_MISMATCH"] + codes)
        note = f"ticket {ticket_id} was filed but the draft says {draft}"

    return {
        "decision": decision,
        "reason_codes": codes if decision == ESCALATE else [],
        "needs_ticket": decision == ESCALATE and ticket_id is None,
        "override_note": note,
        "draft_decision": draft,
        "statuses": statuses,
        "triggers": triggers,
        "allowed": sorted(allowed),
        "ticket_id": ticket_id,
    }
