# IT Equipment Request Handler — Requirements

## 1. Purpose

Employees submit equipment requests in plain English. The system looks up the employee and their
role's policy, then decides to **APPROVE**, **DENY**, or **ESCALATE** to a human reviewer.
Policy decisions are made by deterministic code (the MCP tools and a keyword check in the agent).
The LLM agent chooses which tools to call and writes the response, but never invents policy.

## 2. Request data

| Field | Type | Required | Notes |
|---|---|---|---|
| `employee_id` | string, e.g. `E001` | Yes | Extracted from the request text. Missing → ESCALATE (`MISSING_EMPLOYEE_ID`) |
| `item` | string | Yes | Normalized to a catalog item (section 4) |
| `request_type` | `replacement` or `additional` | No | Inferred if not given (section 5) |
| `reason` | free text | No | Checked for escalation keywords by `detect_triggers` (section 8.2) |
| `request_date` | date | Auto | Always "today" (section 3) |

## 3. Dates

- **Today** is read from the `DEMO_TODAY` environment variable (format `YYYY-MM-DD`). If it is not set,
  the real current date is used. All demo runs use `DEMO_TODAY=2026-11-01`.
- **Adding months:** calendar months. If the day doesn't exist in the target month, use the last day of
  that month (e.g. 2024-01-31 + 1 month = 2024-02-29).
- **Tenure:** the number of *completed* months between `hire_date` and today, reported as
  `tenure_months` and as `{years, months}` (e.g. hired 2021-03-15, today 2026-11-01 → 67 months =
  5 years 7 months).

## 4. Catalog

Requestable items: `laptop`, `monitor`, `keyboard`, `mouse`, `headset`, `docking_station`.

**Normalization**, in order:
1. Lowercase and strip surrounding whitespace.
2. If the text is a catalog item or a synonym, use it.
3. Otherwise, if it ends in "s", remove the "s" and try step 2 again (so "monitors", "screens",
   "docking stations" match).
4. Otherwise the item is **not in the catalog**.

| Synonym | Catalog item |
|---|---|
| screen, display | monitor |
| notebook, computer, macbook | laptop |
| dock, docking station | docking_station |
| headphone, headphones | headset |
| mice | mouse |

Anything else (e.g. standing desk, chair, phone, tablet) → status `unknown_item`, and the tool returns
the catalog list.

## 5. Request types

- **additional**: the employee wants one more of an item ("second", "another", "extra", or they
  have none yet). Checked against `max_count`.
- **replacement**: the employee wants to replace an item they already have ("replace", "new one",
  "old", "slow"). Checked against `refresh_months`, measured from the **oldest** acquisition of that
  item (the unit that would be replaced).
- **Inference when not given:** if the employee has none of the item → `additional`; otherwise
  `replacement`. The agent should pass the type explicitly when the wording makes it clear, because
  "second monitor" from someone who already has one is `additional`, not `replacement`.
- `replacement` when the employee has none of the item → treated as `additional`.
- Any other `request_type` value → status `error` with `error_code: INVALID_REQUEST_TYPE`.

## 6. Policy table

Each cell shows max_count / refresh_months for that role. "Not allowed" means the role cannot request the item. Source of truth: `data/policies.json`.

| Item | standard | manager | engineer | contractor |
|---|---|---|---|---|
| laptop | 1 / 48 | 1 / 24 | 1 / 36 | Not allowed |
| monitor | 2 / 36 | 2 / 36 | 3 / 24 | Not allowed |
| keyboard | 1 / 24 | 1 / 24 | 1 / 12 | Not allowed |
| mouse | 1 / 24 | 1 / 24 | 1 / 12 | Not allowed |
| headset | 1 / 24 | 1 / 24 | 1 / 24 | Not allowed |
| docking_station | Not allowed | 1 / 36 | 1 / 36 | Not allowed |

Contractors are not eligible for any company hardware (their agency supplies it).
Only these four roles exist in the policy. An employee with any other role (e.g. E009, `intern`) is
a data error.

## 7. Eligibility rules (`check_request_eligibility`)

Checked in this order; the first rule that matches decides the status.

| # | Condition | Status | `error_code` |
|---|---|---|---|
| 1a | Employee ID empty or whitespace | `error` | `INVALID_EMPLOYEE_ID` |
| 1b | Employee ID not found | `error` | `EMPLOYEE_NOT_FOUND` |
| 1c | Employee's role not in the policy | `error` | `ROLE_NOT_IN_POLICY` |
| 1d | `request_type` given but not `replacement` / `additional` | `error` | `INVALID_REQUEST_TYPE` |
| 2 | Item not in the catalog (after normalization) | `unknown_item` | — |
| 3 | Role is not allowed the item | `ineligible` | — |
| 4 | `additional` and current count ≥ `max_count` | `ineligible` | — |
| 5 | `additional` and current count < `max_count` | `eligible` | — |
| 6 | `replacement` and today ≥ next eligible date | `eligible` | — |
| 7 | `replacement` and next eligible date is 1–60 days away | `borderline` | — |
| 8 | `replacement` and next eligible date is more than 60 days away | `ineligible` | — |

- Next eligible date = **oldest** acquisition of the item + `refresh_months`.
- Boundaries: exactly on the eligible date → `eligible`; exactly 60 days away → `borderline`;
  61 days away → `ineligible`.
- Every result includes `status`, a human-readable `reason`, the normalized `item` and the
  `request_type` used. Date rules also return `next_eligible_date` and `days_until_eligible`.
  `unknown_item` also returns `catalog`. `error` also returns `error_code`.
- `get_employee_info` and `get_policy_limits` return errors in the same shape:
  `{"error": "<message>", "error_code": "<code>"}`.

**Result details:**
- `status` and `reason` are always the first two keys of a `check_request_eligibility` result.
- `days_until_eligible` is `0` when the request is already eligible (never negative).
- `request_type` is matched case-insensitively (`"Replacement"` works). An empty or whitespace
  value (`""`) is treated as not given and inferred per section 5.
- `unknown_item` results report `request_type: "additional"` (or the type given), since an item
  outside the catalog cannot already be owned.
- `error` results include `status: "error"`, `reason` (the error message) and `error_code`, so every
  result has the same core keys.

## 8. Decision rules (agent)

### 8.1 Decisions

| Decision | When |
|---|---|
| **APPROVE** | Status is `eligible` and no escalation trigger applies |
| **DENY** | Status is `ineligible` and no escalation trigger applies |
| **ESCALATE** | Any escalation trigger in 8.2 applies |

**DENY vs. "outside policy":** the assignment asks both to escalate requests outside policy and to
show a clearly denied request. DENY is used only when a rule clearly says no and none of the facts are
in doubt (role not allowed the item, maximum count reached, or eligibility more than 60 days away).
Anything uncertain, close to a boundary, outside the catalog, or involving special circumstances is
escalated.

### 8.2 Escalation triggers

Each trigger has a reason code that goes into `flag_for_human_review`.

| Code | Trigger | Detected by |
|---|---|---|
| `BORDERLINE_ELIGIBILITY` | Status `borderline` | Tool result |
| `ITEM_NOT_IN_CATALOG` | Status `unknown_item` | Tool result |
| `UNKNOWN_EMPLOYEE` | `error_code` `EMPLOYEE_NOT_FOUND` | Tool result |
| `MISSING_EMPLOYEE_ID` | No employee ID in the request text, or `INVALID_EMPLOYEE_ID` | Agent code |
| `DATA_ERROR` | Any other `error_code` (e.g. `ROLE_NOT_IN_POLICY`, `INVALID_REQUEST_TYPE`) | Tool result |
| `MEDICAL_OR_ACCESSIBILITY` | Request text contains: medical, injury, injured, disability, disabled, accessibility, ergonomic, doctor, pain | `detect_triggers` |
| `BROKEN_OR_STOLEN` | Request text contains: broken, broke, damaged, cracked, stolen, lost, missing | `detect_triggers` |
| `AGENT_STEP_LIMIT` | The agent reached the step limit (8.4) without a decision | Agent code |
| `REFLECTION_MISMATCH` | The draft decision is not allowed for the status (8.3) | Agent code |

`detect_triggers(text)` is a deterministic function in the agent: case-insensitive whole-word matching
against the keyword lists above. It returns a list of codes and is unit-tested in CI.

`extract_employee_id(text)` is a deterministic function in the agent: the first match of the regex
`\bE\d{3}\b` (case-insensitive), returned in uppercase (e.g. "e003" → "E003"). If there is no match,
the request is escalated with `MISSING_EMPLOYEE_ID` without calling any tool. It is unit-tested in CI.

Escalation triggers override the status: an `eligible` request with a medical reason is ESCALATED, and
an `ineligible` laptop request because the laptop was stolen is ESCALATED, not denied.

**Multiple codes, one ticket:** all codes that apply go into a single `flag_for_human_review` call,
joined with `"; "` and followed by a short explanation, e.g.
`"ITEM_NOT_IN_CATALOG; MEDICAL_OR_ACCESSIBILITY: standing desk requested for a back injury"`.

### 8.3 Allowed decisions per status

Enforced by code after the draft and again after reflection:

| Status | Allowed decisions |
|---|---|
| `eligible` | APPROVE, ESCALATE |
| `ineligible` | DENY, ESCALATE |
| `borderline`, `unknown_item`, `error` | ESCALATE only |

- If a `detect_triggers` code applies, only ESCALATE is allowed, whatever the status.
- APPROVE and DENY are allowed only if `check_request_eligibility` was called and returned a status.
  Without one (e.g. `MISSING_EMPLOYEE_ID`), only ESCALATE is allowed.
- If several `check_request_eligibility` calls for the same item return different statuses (e.g. the
  model retries with a different `request_type`), only ESCALATE is allowed, with `DATA_ERROR`.
- Every ESCALATE must create a ticket with `flag_for_human_review`. If the agent decided ESCALATE but
  never called the tool, the code calls it.
- Reflection may change a decision to ESCALATE, but never from ESCALATE to APPROVE or DENY (the
  ticket has already been filed).

### 8.4 Step limit

A **step** is one model call that returns at least one tool call. One step may request several tools
at once. The limit is **8 steps**. If the model makes a 9th step, the loop stops before running its
tools, and the request is escalated with `AGENT_STEP_LIMIT`.

## 9. Response rules

The response to the employee must:
- State the decision and the policy reason in plain language.
- Only state facts returned by the tools.
- **Allowed:** stating `next_eligible_date` from the tool (e.g. "you will be eligible for a
  replacement from 2028-11-15").
- **Not allowed:** promising delivery dates or times, specific models or brands, or that a future
  request *will* be approved.
- For ESCALATE: say it was sent for human review and give the ticket ID.
- End with a machine-readable line: `DECISION: APPROVE`, `DECISION: DENY` or `DECISION: ESCALATE`.

## 10. Tools

| Tool | Input | Output | Errors |
|---|---|---|---|
| `get_employee_info` | `employee_id` | id, name, role, department, hire_date, tenure, equipment | `INVALID_EMPLOYEE_ID`, `EMPLOYEE_NOT_FOUND` |
| `get_policy_limits` | `role` | item limits for the role | `ROLE_NOT_IN_POLICY`; matching is case-insensitive |
| `check_request_eligibility` | `employee_id`, `item`, optional `request_type` | section 7 | section 7 error codes |
| `flag_for_human_review` | `employee_id`, `request`, `reason` | `{ticket_id, status: "pending_review"}` | `EMPTY_REASON` for an empty or whitespace reason; **accepts unknown employee IDs** |

The date ("today") is **not** a tool argument. The MCP tools use `DEMO_TODAY` or the real date. The
plain Python functions accept an optional `today` so tests can fix the date.

### Escalation ticket record

`flag_for_human_review` appends one record to the escalations file (a JSON list; created if missing):

| Field | Example |
|---|---|
| `ticket_id` | `ESC-0001` (sequential: number of existing tickets + 1, zero-padded to 4 digits) |
| `employee_id` | `E004` (stored as given, even if unknown) |
| `request` | `"I need a standing desk for my back injury"` |
| `reason` | `"ITEM_NOT_IN_CATALOG; MEDICAL_OR_ACCESSIBILITY: ..."` |
| `created_at` | ISO 8601 timestamp |
| `status` | `pending_review` |

Data file paths can be overridden with `EMPLOYEES_PATH`, `POLICIES_PATH` and `ESCALATIONS_PATH`
(used by tests).

## 11. Test employees and expected outcomes (DEMO_TODAY = 2026-11-01)

| ID | Role | Relevant equipment | Request text | Status | Expected |
|---|---|---|---|---|---|
| E001 | standard | monitor 2022-09-01 (eligible 2025-09-01) | "E001: My monitor is 4 years old. Can I get a replacement?" | eligible | **APPROVE** |
| E002 | contractor | none | "E002: I need a new laptop for my project." | ineligible | **DENY** (role not allowed) |
| E003 | manager | laptop 2024-12-01 (eligible 2026-12-01, 30 days) | "E003: My laptop is slow. Can I get a new one?" | borderline | **ESCALATE** `BORDERLINE_ELIGIBILITY` |
| E004 | standard | — | "E004: I need a standing desk because of a back injury." | unknown_item | **ESCALATE** `ITEM_NOT_IN_CATALOG; MEDICAL_OR_ACCESSIBILITY` |
| E005 | engineer | laptop 2023-06-15 (eligible 2026-06-15) | "E005: My laptop is over 3 years old. Can I get a replacement? I need it by Friday." | eligible | **APPROVE** (response must not promise Friday) |
| E006 | standard | monitor 2025-11-15 (eligible 2028-11-15) | "E006: Can I get a replacement for my monitor?" | ineligible | **DENY** (inside refresh window) |
| E007 | engineer | 3 monitors (max 3) | "E007: Can I get another monitor?" | ineligible | **DENY** (maximum count reached) |
| E008 | manager | laptop 2025-08-01 (eligible 2027-08-01) | "E008: My laptop was stolen. I need a replacement." | ineligible | **ESCALATE** `BROKEN_OR_STOLEN` |
| E009 | intern (not in policy) | laptop | "E009: Can I get a headset?" | error (`ROLE_NOT_IN_POLICY`) | **ESCALATE** `DATA_ERROR` |
| E999 | does not exist | — | "E999: I need a new monitor." | error (`EMPLOYEE_NOT_FOUND`) | **ESCALATE** `UNKNOWN_EMPLOYEE` |
| — | — | — | "I need a new monitor." (no ID) | — | **ESCALATE** `MISSING_EMPLOYEE_ID` |

**Demo set for the assignment (Part 6):**
- Approve: E001
- Deny: E002 (role not allowed) and E006 (inside refresh window), two different deny rules
- Escalate: E003 (borderline) and E004 (not in catalog plus medical), two different reasons
- Reflection: E005
