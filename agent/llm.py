"""Claude client for the agent (Claude via Azure AI Foundry, configured from .env)."""

import os
from pathlib import Path

from anthropic import AnthropicFoundry
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent


def make_claude() -> tuple[AnthropicFoundry, str]:
    """Claude via Azure AI Foundry, configured from .env (same as check_llm.py)."""
    load_dotenv(REPO_ROOT / ".env")
    client = AnthropicFoundry(
        api_key=os.environ["AZURE_ANTHROPIC_API_KEY"],
        base_url=os.environ["AZURE_ANTHROPIC_BASE_URL"],
    )
    return client, os.environ["AZURE_ANTHROPIC_DEPLOYMENT"]
