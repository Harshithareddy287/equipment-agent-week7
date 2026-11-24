"""Equipment request agent.

Connects to the MCP server as a client and lets Claude work through a request in a
ReAct loop (Thought -> Action -> Observation, repeated until a draft response).
Then reflection reviews the draft against the tool observations (agent/reflection.py),
and agent/rules.py enforces the decision rules in code.

Run from the repo root:
  DEMO_TODAY=2026-11-01 python -m agent.agent "E001: My monitor is 4 years old. Can I get a replacement?"
  DEMO_TODAY=2026-11-01 python -m agent.agent            # hardcoded E001 request
  DEMO_TODAY=2026-11-01 python -m agent.agent --single   # step 1: one tool call only
"""

import argparse
import asyncio
import json

from agent import reflection, rules
from agent.llm import make_claude
from agent.mcp_client import connect, mcp_tools_to_claude, result_as_json
from agent.prompts import SYSTEM_PROMPT

HARDCODED_REQUEST = "E001: My monitor is 4 years old. Can I get a replacement?"

# --- Step 1: one tool call -------------------------------------------------------------

async def single_tool_call(request: str) -> None:
    claude, model = make_claude()

    async with connect() as mcp:
        listing = await mcp.list_tools()
        tools = mcp_tools_to_claude(listing.tools)
        print("MCP tools available:", [t["name"] for t in tools])
        print("Request:", request)

        response = claude.messages.create(
            model=model,
            max_tokens=1024,
            system="You handle IT equipment requests. Use the tools to look up facts.",
            messages=[{"role": "user", "content": request}],
            tools=tools,
        )

        tool_use = next((b for b in response.content if b.type == "tool_use"), None)
        if tool_use is None:
            text = " ".join(b.text for b in response.content if b.type == "text")
            print("Model did not call a tool. Reply:", text)
            return

        print("\nModel chose tool:", tool_use.name)
        print("Arguments:", json.dumps(tool_use.input))

        result = await mcp.call_tool(tool_use.name, tool_use.input)
        print("MCP result:")
        print(json.dumps(result_as_json(result), indent=2))


# --- Step 2: ReAct loop ----------------------------------------------------------------

MAX_STEPS = 8  # requirements section 8.4: a step = one model call that returns tool calls

def _text_of(blocks) -> str:
    return "\n".join(b.text for b in blocks if b.type == "text").strip()


def _as_thought(text: str) -> str:
    """The model's text before a tool call, without a duplicated "Thought:" prefix."""
    text = text.strip()
    return text[len("Thought:"):].strip() if text.startswith("Thought:") else text


async def _react_loop(claude, model, mcp, tools, request: str, trace: dict) -> None:
    """The ReAct loop: Thought -> Action -> Observation until a draft (fills trace)."""
    messages = [{"role": "user", "content": request}]

    while True:
        response = claude.messages.create(
            model=model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=tools,
        )
        tool_uses = [b for b in response.content if b.type == "tool_use"]

        if response.stop_reason == "refusal":  # model/provider declined to answer
            trace["refused"] = True
            print(f"\nModel refused (stop_reason=refusal) at step {trace['num_steps'] + 1}.")
            return

        if not tool_uses:  # no more tools: this is the draft response
            trace["final_text"] = _text_of(response.content)
            print("\nDraft response:")
            print(trace["final_text"])
            return

        trace["num_steps"] += 1
        if trace["num_steps"] > MAX_STEPS:  # 9th step: stop before running its tools
            trace["num_steps"] = MAX_STEPS
            trace["step_limit_reached"] = True
            print(f"\nStep limit reached ({MAX_STEPS} steps) without a final response.")
            return

        step = trace["num_steps"]
        thought = _as_thought(_text_of(response.content))
        print(f"\n--- Step {step} ---")
        print(f"Thought: {thought or '(none written)'}")

        tool_results = []
        for tool_use in tool_uses:
            print(f"Action: {tool_use.name}({json.dumps(tool_use.input)})")
            result = await mcp.call_tool(tool_use.name, tool_use.input)
            observation = result_as_json(result)
            print(f"Observation: {json.dumps(observation)}")

            trace["steps"].append({
                "step": step,
                "thought": thought,
                "tool": tool_use.name,
                "args": tool_use.input,
                "observation": observation,
            })
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_use.id,
                "content": json.dumps(observation),
                "is_error": bool(result.is_error),
            })

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})


def _escalation_message(codes: list[str], ticket_id: str | None) -> str:
    """Code-written response used when the code overrides or files the ticket itself."""
    return (
        "Your request has been sent to a human reviewer for a decision.\n"
        f"Ticket: {ticket_id or '(ticket could not be created)'}\n"
        f"Reason: {'; '.join(codes)}\n"
        "A reviewer will follow up with you.\n\n"
        "DECISION: ESCALATE"
    )


async def run_agent(request: str) -> dict:
    """Run one request end to end: ReAct loop, then the code-enforced safety check."""
    print(f"\n=== Request: {request} ===")
    trace = {"request": request, "steps": [], "final_text": "", "num_steps": 0,
             "step_limit_reached": False, "refused": False}

    async with connect() as mcp:
        if rules.extract_employee_id(request) is None:
            # Section 8.2: no ID -> escalate without calling the model or any lookup tool.
            print("\nNo employee ID found in the request; escalating without running the agent.")
        else:
            claude, model = make_claude()
            tools = mcp_tools_to_claude((await mcp.list_tools()).tools)
            await _react_loop(claude, model, mcp, tools, request, trace)

        print(f"\n(steps used: {trace['num_steps']} of {MAX_STEPS})")

        # --- Reflection (Part 5): review the draft before the safety check. ---
        if trace["final_text"].strip():
            result = await reflection.reflect(claude, model, request, trace)
            text_after, notes = reflection.apply_reflection(trace["final_text"], result)
            issues = result["issues"] + notes
            print(f"\nReflection: {result['verdict']}")
            print("Issues found:" + ("".join(f"\n- {i}" for i in issues) if issues else " none"))
            if result["verdict"] == "REVISED":
                print("Revised response:")
                print(result["revised_response"])
                if text_after != result["revised_response"]:
                    print("(revision not applied; keeping the draft)")
            trace["reflection"] = {"verdict": result["verdict"], "issues": issues,
                                   "text_before": trace["final_text"], "text_after": text_after}
            trace["final_text"] = text_after

        # --- Safety check (sections 8.2-8.4): the code decides what may stand. ---
        final = rules.finalize(trace, request)
        ticket_id = final["ticket_id"]
        if final["needs_ticket"]:
            explanation = final["override_note"] or "escalated by the agent"
            if final["statuses"]:  # section 8.1: the ticket notes the status of every item
                explanation += "; statuses: " + ", ".join(
                    f"{item}={'/'.join(values)}" for item, values in final["statuses"].items())
            reason = rules.format_reason(final["reason_codes"], explanation)
            args = {"employee_id": rules.extract_employee_id(request) or "",
                    "request": request, "reason": reason}
            print(f"Action (code): flag_for_human_review({json.dumps(args)})")
            observation = result_as_json(await mcp.call_tool("flag_for_human_review", args))
            print(f"Observation: {json.dumps(observation)}")
            ticket_id = observation.get("ticket_id") if isinstance(observation, dict) else None

    overridden = final["decision"] != final["draft_decision"]
    # The code writes the response when it overrode the draft or filed the ticket itself
    # (the model's draft cannot contain a ticket ID it never received).
    if overridden or final["needs_ticket"]:
        response_text = _escalation_message(final["reason_codes"], ticket_id)
    else:
        response_text = trace["final_text"]

    print(
        f"\nSafety check: statuses={final['statuses']}, triggers={final['triggers']}, "
        f"allowed={final['allowed']}, draft decision={final['draft_decision']}, "
        f"final decision={final['decision']}"
        + (f", (override: {final['override_note']})" if overridden else "")
    )
    print(f"Final decision: {final['decision']}")
    if final["decision"] == rules.ESCALATE:
        print(f"Escalation reason: {'; '.join(final['reason_codes']) or '(given by the agent)'}")
        print(f"Ticket: {ticket_id}")
    print("Final response:")
    print(response_text)

    trace.update({
        "draft_decision": final["draft_decision"],
        "final_decision": final["decision"],
        "reason_codes": final["reason_codes"],
        "ticket_id": ticket_id,
        "override_note": final["override_note"] if overridden else None,
        "final_response": response_text,
    })
    return trace


def main() -> None:
    parser = argparse.ArgumentParser(description="IT equipment request agent")
    parser.add_argument("request", nargs="?", default=HARDCODED_REQUEST,
                        help="the employee's request (default: the hardcoded E001 request)")
    parser.add_argument("--single", action="store_true",
                        help="step 1 only: make a single tool call and stop")
    args = parser.parse_args()

    if args.single:
        asyncio.run(single_tool_call(args.request))
    else:
        asyncio.run(run_agent(args.request))


if __name__ == "__main__":
    main()
