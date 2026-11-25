"""Reflection (assignment Part 5): review the ReAct draft against the tool observations.

Runs after the ReAct draft and before rules.finalize(). reflect() makes one Claude call;
parse_reflection() and apply_reflection() are pure and unit-tested. Reflection may
tighten a decision (APPROVE/DENY -> ESCALATE) but never loosen an ESCALATE.
"""

import json
import re

from agent import rules
from agent.prompts import REFLECTION_PROMPT

VERDICTS = ("CONFIRMED", "REVISED")
_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


def _error(message: str) -> dict:
    return {"verdict": "ERROR", "issues": [message], "revised_response": ""}


def parse_reflection(text: str | None) -> dict:
    """Parse the reviewer's JSON (code fences tolerated); anything invalid -> verdict ERROR."""
    cleaned = _FENCE.sub("", (text or "").strip())
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end < start:
        return _error("reflection output was not valid JSON")
    try:
        data = json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError:
        return _error("reflection output was not valid JSON")
    if not isinstance(data, dict):
        return _error("reflection output was not a JSON object")

    verdict = str(data.get("verdict", "")).strip().upper()
    if verdict not in VERDICTS:
        return _error(f"unknown reflection verdict: {data.get('verdict')!r}")
    issues = data.get("issues") or []
    if not isinstance(issues, list):
        issues = [str(issues)]
    revised = data.get("revised_response") or ""
    return {
        "verdict": verdict,
        "issues": [str(i) for i in issues],
        "revised_response": revised if isinstance(revised, str) else "",
    }


def apply_reflection(draft_text: str, result: dict) -> tuple[str, list[str]]:
    """Return (text to use, extra notes). Never loosens an ESCALATE draft."""
    verdict = result.get("verdict")
    if verdict == "CONFIRMED":
        return draft_text, []
    if verdict != "REVISED":
        return draft_text, ["reflection could not run; kept draft (safety check still applies)"]

    revised = result.get("revised_response") or ""
    before = rules.parse_decision(draft_text)
    after = rules.parse_decision(revised)
    if after is None:
        return draft_text, ["revised response had no valid DECISION line; kept draft"]
    if before == rules.ESCALATE and after != rules.ESCALATE:
        return draft_text, ["reflection tried to loosen ESCALATE; kept draft"]
    return revised, []


def _observations(trace: dict) -> list[dict]:
    return [{"tool": s["tool"], "args": s["args"], "observation": s["observation"]}
            for s in trace.get("steps", [])]


async def reflect(claude, model: str, request: str, trace: dict) -> dict:
    """One Claude call reviewing trace["final_text"]; returns the parsed result."""
    content = (
        f"Employee request:\n{request}\n\n"
        f"Tool observations (JSON):\n{json.dumps(_observations(trace), indent=2)}\n\n"
        f"Draft response:\n{trace['final_text']}"
    )
    try:
        response = claude.messages.create(
            model=model,
            max_tokens=1500,
            system=REFLECTION_PROMPT,
            messages=[{"role": "user", "content": content}],
        )
    except Exception as exc:  # network / API errors must not lose the draft
        return _error(f"reflection call failed: {exc}")
    if response.stop_reason == "refusal":
        return _error("reflection call was refused")
    text = "\n".join(b.text for b in response.content if b.type == "text")
    return parse_reflection(text)
