import os
from dotenv import load_dotenv
from anthropic import AnthropicFoundry

load_dotenv()
client = AnthropicFoundry(
    api_key=os.environ["AZURE_ANTHROPIC_API_KEY"],
    base_url=os.environ["AZURE_ANTHROPIC_BASE_URL"],
)

try:
    resp = client.messages.create(
        model=os.environ["AZURE_ANTHROPIC_DEPLOYMENT"],
        max_tokens=256,
        messages=[{"role": "user", "content": "Call the ping tool."}],
        tools=[{
            "name": "ping",
            "description": "Returns pong",
            "input_schema": {"type": "object", "properties": {}},
        }],
    )
    calls = [b for b in resp.content if b.type == "tool_use"]
    print("Claude Messages API:", "TOOL CALL OK" if calls else "no tool call (text reply)")
except Exception as e:
    print("Claude Messages API: FAILED ->", e)