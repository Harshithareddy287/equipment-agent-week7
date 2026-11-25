# IT Equipment Request Agent (MCP + ReAct)

Repository: equipment-agent-week7

![CI](https://github.com/Harshithareddy287/equipment-agent-week7/actions/workflows/ci.yml/badge.svg)

## 1. What it is

An internal **IT equipment request handler**. Employees ask for equipment in plain English
(e.g. "E001: My monitor is 4 years old. Can I get a replacement?"). An **MCP server** exposes the
employee, policy and eligibility data as tools, and a **ReAct agent** (Claude via Azure AI Foundry)
uses those tools to **APPROVE**, **DENY** or **ESCALATE** the request to a human reviewer. Before the
response is final, a **reflection** step checks the draft against the tool results.

Policy decisions are made by deterministic Python, not by the LLM. The LLM chooses which tools to
call and writes the response; code enforces which decisions are allowed. The full spec is in
[docs/requirements.md](docs/requirements.md).

## 2. Architecture

```
Employee request (plain English)
        │
        ▼
agent/  ── Anthropic Messages API (HTTPS) ──►  Claude (Azure AI Foundry)
        │
        │  MCP: JSON-RPC over stdio (server runs as a subprocess)
        ▼
server/server.py  (MCP tools, thin wrappers)
        │  plain function calls
        ▼
server/tools.py   (business logic)  ──►  data/*.json
```

After the ReAct loop, reflection and a code safety check run before the final response (see §4).

| Path | Contents |
|---|---|
| `server/tools.py` | The business logic as plain, unit-tested functions |
| `server/server.py` | `MCPServer` that registers the four tools (wrappers only) |
| `server/config.py` | `DEMO_TODAY`, data file paths, month arithmetic |
| `server/hello_server.py` | Minimal one-tool (`ping`) server used to prove the MCP setup first |
| `agent/mcp_client.py` | Starts the server over stdio, converts MCP tools to Claude's tool format |
| `agent/llm.py` | Claude client (`AnthropicFoundry`) configured from `.env` |
| `agent/prompts.py` | `SYSTEM_PROMPT` (ReAct agent) and `REFLECTION_PROMPT` (reviewer) |
| `agent/agent.py` | The ReAct loop, reflection and safety-check wiring, CLI |
| `agent/rules.py` | Code-enforced decision rules (pure functions, no LLM) |
| `agent/reflection.py` | Reflection call plus pure parsing and apply logic |
| `data/` | `employees.json`, `policies.json`; `escalations.json` is written at runtime (gitignored) |
| `docs/requirements.md` | Requirements, policy table, decision rules, expected outcomes |

## 3. The four MCP tools

| Tool | What it does |
|---|---|
| `get_employee_info(employee_id)` | Returns role, department, hire date, tenure and equipment on file |
| `get_policy_limits(role)` | Returns `allowed` / `max_count` / `refresh_months` for every catalog item for a role |
| `check_request_eligibility(employee_id, item, request_type?)` | Returns `eligible`, `ineligible`, `borderline`, `unknown_item` or `error`, with a reason and dates |
| `flag_for_human_review(employee_id, request, reason)` | **Side effect:** appends a ticket (`ESC-0001`, ...) to the escalations file |

The date is never a tool argument: the tools use `DEMO_TODAY` or the real date.

## 4. Decision flow

1. **Employee ID check:** if the request has no ID like `E001`, it is escalated (`MISSING_EMPLOYEE_ID`)
   without calling the model.
2. **ReAct loop:** Claude explains each step (printed as `Thought:`), calls a tool through MCP
   (`Action:`) and sees the result (`Observation:`), until it writes a **draft** ending with
   `DECISION: APPROVE|DENY|ESCALATE`. Limit: 8 steps.
3. **Reflection:** a second Claude call checks the draft against the observations and returns
   `CONFIRMED` or `REVISED` (with the issues found). It can tighten a decision to ESCALATE but never
   loosen an ESCALATE.
4. **Safety check (`rules.finalize`)**: code checks the decision against the eligibility statuses and
   the keyword triggers (medical/accessibility, broken/stolen). A decision that is not allowed is
   overridden to ESCALATE.
5. **Ticket:** every ESCALATE has a ticket. If the agent did not file one, the code calls
   `flag_for_human_review` itself.

## 5. Setup

Requires Python 3.14 (the MCP SDK v2 needs 3.10+).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # then fill in the values
```

`.env` needs `AZURE_ANTHROPIC_API_KEY`, `AZURE_ANTHROPIC_BASE_URL` and
`AZURE_ANTHROPIC_DEPLOYMENT`. **Never commit `.env`** (it is in `.gitignore`). It is only needed
for the agent; the tests and MCP clients run without it.

Run `python check_llm.py` to verify the Azure connection and tool calling.

## 6. Usage

```bash
pytest -q                                          # all tests (no LLM, no secrets)
python client_hello.py                             # minimal ping server: lists tools, calls ping
DEMO_TODAY=2026-11-01 python client_test.py        # calls all four tools on the real server
DEMO_TODAY=2026-11-01 python -m agent.agent "E001: My monitor is 4 years old. Can I get a replacement?"
DEMO_TODAY=2026-11-01 python -m agent.agent --single   # one tool call only (no loop)
```

`client_test.py` writes its test ticket to a temporary file unless `ESCALATIONS_PATH` is set.
The agent writes tickets to `data/escalations.json`.

## 7. Demo results

Run with `DEMO_TODAY=2026-11-01`. Full traces are in [demo_outputs/](demo_outputs/).

| Request | Eligibility status | Final decision | Reason / ticket | Reflection |
|---|---|---|---|---|
| E001: monitor 4 years old, replacement | `eligible` | **APPROVE** | — | REVISED |
| E002: contractor asks for a laptop | `ineligible` | **DENY** | role not allowed | CONFIRMED |
| E003: manager laptop is slow | `borderline` (30 days) | **ESCALATE** | `BORDERLINE_ELIGIBILITY`, ESC-0001 | CONFIRMED |
| E004: standing desk for a back injury | `unknown_item` | **ESCALATE** | `ITEM_NOT_IN_CATALOG; MEDICAL_OR_ACCESSIBILITY`, ESC-0002 | CONFIRMED |

## 8. Testing and CI

`pytest` runs 150 tests with **no LLM calls and no secrets**:

| File | Covers |
|---|---|
| `tests/test_employee_info.py` | `get_employee_info`, tenure, date helpers, path overrides |
| `tests/test_policy_limits.py` | `get_policy_limits`, case-insensitive roles, unknown roles |
| `tests/test_eligibility.py` | `check_request_eligibility`: every rule, the 60-day boundaries, normalization, oldest unit |
| `tests/test_review.py` | `flag_for_human_review`: ticket records, numbering, empty reason, unknown or empty IDs |
| `tests/test_mcp_integration.py` | Starts the real server over stdio and calls each tool through MCP |
| `tests/test_agent_rules.py` | ID extraction, keyword triggers, decision parsing, allowed decisions, `finalize` |
| `tests/test_reflection.py` | Parsing the reflection JSON and the rules for applying it |

Tests point `ESCALATIONS_PATH` at a temporary file, so they never write to `data/`.
GitHub Actions ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs `pytest -v` on
Python 3.14 on every push and on pull requests to `main`.

## 9. Development workflow

The project was built in 8 branches. Each was merged into `main` by a pull request after CI passed.

| # | Branch | Added |
|---|---|---|
| 1 | `setup/project-ci` | Project skeleton, CI workflow, smoke test |
| 2 | `docs/requirements` | Requirements doc, policy rules, mock data |
| 3 | `feature/minimal-server` | `ping` server, then `get_employee_info` with tests and an MCP client |
| 4 | `feature/policy-tool` | `get_policy_limits` and the MCP integration test |
| 5 | `feature/eligibility-tool` | `check_request_eligibility` |
| 6 | `feature/review-tool` | `flag_for_human_review`; all four tools complete |
| 7 | `feature/react-agent` | ReAct agent, MCP client, code-enforced decision rules |
| 8 | `feature/reflection-demo` | Reflection step, demo runs, README |

Each tool was written as a plain function with unit tests first, then wrapped as an MCP tool and
checked through a client.
